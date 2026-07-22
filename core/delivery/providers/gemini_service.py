from __future__ import annotations

import logging
import re
from threading import Timer
from typing import Any, Callable

from ...config.constants import LOGGER_NAME, LOGGER_PREFIX
from ...funpay.chat_sync import (
	find_chat_sync_topic,
	get_chat_sync_obj,
	send_chat_sync_topic_message,
)
from ...gist.service import create_gist_result, resolve_gist_filename
from ...gist.settings import normalize_gist_settings
from ..models import DeliveryOutcome, OUTCOME_COMPLETED, OUTCOME_IGNORED, OUTCOME_SEND_FAILED, OUTCOME_WAITING_STOCK
from ..service import AutoDeliveryService
from .gemini import normalize_gemini_delivery_settings
from .gemini_storage import (
	GeminiDeliveryStorage,
	OrderReservationRequest,
	STATUS_COMPLETED,
	STATUS_GIST_CREATED,
	STATUS_RESERVED,
	STATUS_SEND_FAILED,
	STATUS_WAITING_STOCK,
)


logger = logging.getLogger(LOGGER_NAME)

GEMINI_MARKER_PATTERN = re.compile(r"#geminilink\b", re.IGNORECASE)

class GeminiDeliveryService(AutoDeliveryService):
	name = "gemini"
	settings_key = "gemini_delivery"
	def __init__(
		self,
		cardinal,
		settings_getter: Callable[[], dict[str, Any]],
		storage: GeminiDeliveryStorage,
		gist_creator: Callable[..., Any] = create_gist_result,
		topic_notifier: Callable[[dict[str, Any], str], bool] | None = None,
		admin_notifier: Callable[[str], None] | None = None,
		timer_factory: Callable[[int, Callable[[], None]], Any] = Timer,
	):
		super().__init__(
			cardinal,
			settings_getter,
			storage,
			normalize_gemini_delivery_settings,
			has_gemini_marker,
			timer_factory,
		)
		self.gist_creator = gist_creator
		self.topic_notifier = topic_notifier or self.notify_chat_sync
		self.admin_notifier = admin_notifier or (lambda text: None)
		self.handle_new_order = AutoDeliveryService.handle_new_order.__get__(self)
		self.handle_delayed_new_order = AutoDeliveryService.handle_delayed_new_order.__get__(self)
		self.handle_new_order_locked = AutoDeliveryService.handle_new_order_locked.__get__(self)
		self.is_matching_new_order = AutoDeliveryService.is_matching_new_order.__get__(self)

	def handle_new_order(self, event: object) -> DeliveryOutcome:
		with self.lock:
			config = normalize_gemini_delivery_settings(
				self.settings_getter().get("gemini_delivery")
			)
			if not config["enabled"]:
				return DeliveryOutcome(OUTCOME_IGNORED)
			if config["delay_seconds"] <= 0:
				return self.handle_new_order_locked(event)
			if not self.is_matching_new_order(event):
				return DeliveryOutcome(OUTCOME_IGNORED)
			timer = self.timer_factory(
				config["delay_seconds"],
				lambda: self.handle_delayed_new_order(event),
			)
			timer.daemon = True
			timer.start()
			return DeliveryOutcome(OUTCOME_IGNORED)

	def handle_delayed_new_order(self, event: object) -> DeliveryOutcome:
		with self.lock:
			return self.handle_new_order_locked(event)

	def handle_new_order_locked(self, event: object) -> DeliveryOutcome:
		settings = self.settings_getter()
		config = normalize_gemini_delivery_settings(settings.get("gemini_delivery"))
		if not config["enabled"]:
			return DeliveryOutcome(OUTCOME_IGNORED)

		event_order = getattr(event, "order", None)
		if not event_order:
			return DeliveryOutcome(OUTCOME_IGNORED)

		order = self.get_full_order(event_order)
		if not has_gemini_marker(self.order_description(order, event_order)):
			return DeliveryOutcome(OUTCOME_IGNORED)

		request = self.order_request(order, event_order)
		if not request.order_id:
			return DeliveryOutcome(OUTCOME_IGNORED)

		existing = self.storage.get_order(request.order_id)
		if existing:
			status = existing.get("status")
			if status == STATUS_COMPLETED:
				return DeliveryOutcome(OUTCOME_COMPLETED, request.order_id)
			if status == STATUS_SEND_FAILED:
				return DeliveryOutcome(OUTCOME_SEND_FAILED, request.order_id, existing.get("last_error", ""))
			if status == STATUS_WAITING_STOCK:
				return DeliveryOutcome(OUTCOME_WAITING_STOCK, request.order_id)

		return self.deliver(request, config, settings)

	def is_matching_new_order(self, event: object) -> bool:
		event_order = getattr(event, "order", None)
		if not event_order:
			return False
		order = self.get_full_order(event_order)
		if not has_gemini_marker(self.order_description(order, event_order)):
			return False
		return bool(self.order_request(order, event_order).order_id)

	def retry_order(self, order_id: str) -> DeliveryOutcome:
		with self.lock:
			order = self.storage.get_order(order_id)
			if not order:
				return DeliveryOutcome(OUTCOME_IGNORED, str(order_id))

			request = OrderReservationRequest(
				order_id=order["order_id"],
				requested_amount=normalize_order_amount(order.get("requested_amount")),
				buyer_username=str(order.get("buyer_username") or ""),
				fp_chat_id=order.get("fp_chat_id"),
			)
			settings = self.settings_getter()
			config = normalize_gemini_delivery_settings(settings.get("gemini_delivery"))
			if not config["enabled"]:
				return DeliveryOutcome(OUTCOME_IGNORED, request.order_id, "Gemini delivery is disabled.")
			return self.deliver(request, config, settings)

	def deliver(
		self,
		request: OrderReservationRequest,
		config: dict[str, Any],
		settings: dict[str, Any] | None = None,
	) -> DeliveryOutcome:
		settings = settings or self.settings_getter()
		existing = self.storage.get_order(request.order_id)
		if existing:
			status = existing.get("status")
			if status == STATUS_COMPLETED:
				return DeliveryOutcome(OUTCOME_COMPLETED, request.order_id)
			if status == STATUS_SEND_FAILED:
				return DeliveryOutcome(OUTCOME_SEND_FAILED, request.order_id, existing.get("last_error", ""))
			if status == STATUS_GIST_CREATED:
				return self.send_gist(request.order_id, existing["raw_url"], config)

		gist_config = normalize_gist_settings(settings.get("gist"))
		if not gist_config["token"]:
			error = "GitHub token не задан."
			if self.storage.record_error(request, error):
				record = self.storage.get_order(request.order_id) or {}
				self.topic_notifier(record, f"⚠️ Автовыдача #{request.order_id}: {error}")
			return DeliveryOutcome(OUTCOME_IGNORED, request.order_id, error)

		reservation = self.storage.reserve(request, config["shortage_mode"])
		if reservation.status == STATUS_GIST_CREATED:
			return self.send_gist(request.order_id, reservation.raw_url, config)
		if reservation.status == STATUS_WAITING_STOCK:
			self.notify_shortage_once(
				request.order_id,
				reservation,
				self.storage.stock_count(),
			)
			return DeliveryOutcome(OUTCOME_WAITING_STOCK, request.order_id)
		if reservation.status != STATUS_RESERVED:
			return DeliveryOutcome(OUTCOME_IGNORED, request.order_id)

		if reservation.shortage:
			self.notify_shortage_once(
				request.order_id,
				reservation,
				self.storage.stock_count(),
			)

		gist_settings = {
			"token": gist_config["token"],
			"visibility": "secret",
			"filename": {
				"mode": "off",
				"custom": "",
			},
		}
		filename = resolve_gist_filename(
			{"filename": {"mode": "order_id"}},
			order_id=request.order_id,
		)
		try:
			result = self.gist_creator(
				gist_settings,
				"\n\n".join(reservation.links),
				filename=filename,
			)
		except Exception as exc:
			error = str(exc)
			self.storage.restore_reservation(request.order_id, error)
			logger.warning(f"{LOGGER_PREFIX} Gemini Gist creation failed for {request.order_id}: {error}")
			logger.debug("TRACEBACK", exc_info=True)
			return DeliveryOutcome(OUTCOME_IGNORED, request.order_id, error)

		self.storage.mark_gist_created(request.order_id, result.url)
		return self.send_gist(request.order_id, result.url, config)

	def send_gist(
		self,
		order_id: str,
		raw_url: str,
		config: dict[str, Any],
	) -> DeliveryOutcome:
		record = self.storage.get_order(order_id) or {}
		try:
			chat_id = self.resolve_chat_id(record)
			if chat_id is None:
				raise RuntimeError("Не удалось определить чат покупателя.")
			sent = self.cardinal.send_message(
				chat_id=chat_id,
				message_text=config["message_template"].format(link=raw_url),
			)
			if sent is False:
				raise RuntimeError("Cardinal не подтвердил отправку.")
		except Exception as exc:
			error = str(exc)
			self.storage.mark_send_failed(order_id, error)
			record = self.storage.get_order(order_id) or record
			self.topic_notifier(
				record,
				f"❌ Автовыдача #{order_id}: не удалось отправить сообщение покупателю.\n"
				f"Отправьте ссылку вручную:\n{raw_url}\n"
				f"Ошибка: {error}",
			)
			return DeliveryOutcome(OUTCOME_SEND_FAILED, order_id, error)

		self.storage.mark_completed(order_id)
		return DeliveryOutcome(OUTCOME_COMPLETED, order_id)

	def notify_shortage_once(self, order_id: str, reservation, stock_left: int) -> None:
		if not self.storage.mark_shortage_notified(order_id):
			return
		record = self.storage.get_order(order_id) or {}
		warning = (
			f"⚠️ Нехватка Gemini-ссылок для заказа #{order_id}.\n"
			f"Требуется: {reservation.requested_amount}\n"
			f"Выдано: {len(reservation.links)}\n"
			f"Осталось в стоке: {stock_left}"
		)
		self.notify_buyer_shortage(record, warning)
		try:
			self.topic_notifier(record, warning)
		except Exception as exc:
			logger.warning(f"{LOGGER_PREFIX} Failed to notify Chat Sync about Gemini shortage: {exc}")
			logger.debug("TRACEBACK", exc_info=True)
		try:
			self.admin_notifier(warning)
		except Exception as exc:
			logger.warning(f"{LOGGER_PREFIX} Failed to notify administrators about Gemini shortage: {exc}")
			logger.debug("TRACEBACK", exc_info=True)

	def notify_buyer_shortage(self, record: dict[str, Any], warning: str) -> None:
		try:
			chat_id = self.resolve_chat_id(record)
			if chat_id is None:
				raise RuntimeError("Не удалось определить чат покупателя.")
			self.cardinal.send_message(chat_id=chat_id, message_text=warning)
		except Exception as exc:
			logger.warning(f"{LOGGER_PREFIX} Failed to notify buyer about Gemini shortage: {exc}")
			logger.debug("TRACEBACK", exc_info=True)

	def notify_chat_sync(self, record: dict[str, Any], text: str) -> bool:
		topic = find_chat_sync_topic(
			record.get("fp_chat_id"),
			str(record.get("buyer_username") or ""),
		)
		if not topic:
			logger.warning(
				f"{LOGGER_PREFIX} Chat Sync topic not found for order {record.get('order_id', '')}."
			)
			return False

		cs = get_chat_sync_obj()
		bot = getattr(cs, "current_bot", None) if cs else None
		if not bot:
			telegram = getattr(self.cardinal, "telegram", None)
			bot = getattr(telegram, "bot", None) if telegram else None
		if not bot:
			logger.warning(f"{LOGGER_PREFIX} Chat Sync bot is unavailable.")
			return False
		return send_chat_sync_topic_message(bot, topic, text)

	def get_full_order(self, event_order: object) -> object:
		try:
			return self.cardinal.account.get_order(getattr(event_order, "id"))
		except Exception as exc:
			logger.warning(
				f"{LOGGER_PREFIX} Failed to fetch full order {getattr(event_order, 'id', '')}: {exc}"
			)
			logger.debug("TRACEBACK", exc_info=True)
			return event_order

	def order_request(
		self,
		order: object,
		fallback_order: object | None = None,
	) -> OrderReservationRequest:
		fallback_order = fallback_order or order
		order_id = str(
			getattr(order, "id", None)
			or getattr(fallback_order, "id", "")
		).strip().lstrip("#")
		buyer_username = str(
			getattr(order, "buyer_username", None)
			or getattr(fallback_order, "buyer_username", "")
			or ""
		)
		fp_chat_id = (
			getattr(order, "chat_id", None)
			or getattr(fallback_order, "chat_id", None)
		)
		amount = getattr(order, "amount", None)
		if amount is None:
			amount = getattr(fallback_order, "amount", None)
		return OrderReservationRequest(
			order_id=order_id,
			requested_amount=normalize_order_amount(amount),
			buyer_username=buyer_username,
			fp_chat_id=fp_chat_id,
		)

	def resolve_chat_id(self, record: dict[str, Any]) -> int | str | None:
		chat_id = record.get("fp_chat_id")
		if chat_id is not None:
			return chat_id

		username = str(record.get("buyer_username") or "")
		if not username:
			return None
		chat = self.cardinal.account.get_chat_by_name(username, True)
		return getattr(chat, "id", None) if chat else None

	@staticmethod
	def order_description(order: object, fallback_order: object) -> str:
		for source in (order, fallback_order):
			for field in ("full_description", "description", "title"):
				value = getattr(source, field, None)
				if isinstance(value, str) and value:
					return value
		return ""


def has_gemini_marker(text: str) -> bool:
	return bool(GEMINI_MARKER_PATTERN.search(text or ""))


def normalize_order_amount(value: Any) -> int:
	if isinstance(value, bool):
		return 1
	try:
		amount = int(value)
	except (TypeError, ValueError):
		return 1
	return amount if amount > 0 else 1
