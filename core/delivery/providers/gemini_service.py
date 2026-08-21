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
from ...short_io.client import create_short_link
from ..models import (
	DeliveryOutcome,
	OUTCOME_AWAITING_CONFIRMATION,
	OUTCOME_COMPLETED,
	OUTCOME_IGNORED,
	OUTCOME_SEND_FAILED,
	OUTCOME_WAITING_STOCK,
)
from ..service import AutoDeliveryService
from .gemini import format_gemini_delivery_message, normalize_gemini_delivery_settings
from .gemini_storage import (
	GeminiDeliveryStorage,
	OrderReservationRequest,
	STATUS_AWAITING_CONFIRMATION,
	STATUS_CANCELLED,
	STATUS_COMPLETED,
	STATUS_GIST_CREATED,
	STATUS_PREPARATION_FAILED,
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
		short_link_creator: Callable[..., Any] = create_short_link,
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
		self.short_link_creator = short_link_creator
		self.topic_notifier = topic_notifier or self.notify_chat_sync
		self.admin_notifier = admin_notifier or (lambda text: None)
		self.confirmation_notifier: Callable[[str], bool] = lambda order_id: False
		self.handle_new_order = AutoDeliveryService.handle_new_order.__get__(self)
		self.handle_delayed_new_order = AutoDeliveryService.handle_delayed_new_order.__get__(self)
		self.handle_new_order_locked = AutoDeliveryService.handle_new_order_locked.__get__(self)
		self.is_matching_new_order = AutoDeliveryService.is_matching_new_order.__get__(self)

	def set_confirmation_notifier(self, notifier: Callable[[str], bool]) -> None:
		self.confirmation_notifier = notifier

	def handle_new_order(self, event: object) -> DeliveryOutcome:
		with self.lock:
			config = normalize_gemini_delivery_settings(
				self.settings_getter().get("gemini_delivery")
			)
			if config["mode"] == "off":
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
		if config["mode"] == "off":
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
			if status == STATUS_AWAITING_CONFIRMATION:
				return DeliveryOutcome(OUTCOME_AWAITING_CONFIRMATION, request.order_id)
			if status == STATUS_CANCELLED:
				return DeliveryOutcome(OUTCOME_IGNORED, request.order_id, "Выдача отменена администратором.")

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
			if config["mode"] == "off":
				return DeliveryOutcome(OUTCOME_IGNORED, request.order_id, "Gemini delivery is disabled.")
			status = order.get("status")
			if status == STATUS_AWAITING_CONFIRMATION:
				if config["mode"] == "auto":
					return self.confirm_order(request.order_id)
				self.notify_confirmation(request.order_id)
				return DeliveryOutcome(OUTCOME_AWAITING_CONFIRMATION, request.order_id)
			if status == STATUS_COMPLETED:
				return DeliveryOutcome(OUTCOME_COMPLETED, request.order_id)
			if status == STATUS_SEND_FAILED:
				return DeliveryOutcome(OUTCOME_SEND_FAILED, request.order_id, order.get("last_error", ""))
			if status == STATUS_CANCELLED:
				return DeliveryOutcome(OUTCOME_IGNORED, request.order_id, "Выдача отменена администратором.")
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
				return self.request_confirmation(request.order_id)
			if status == STATUS_AWAITING_CONFIRMATION:
				return DeliveryOutcome(OUTCOME_AWAITING_CONFIRMATION, request.order_id)
			if status == STATUS_CANCELLED:
				return DeliveryOutcome(OUTCOME_IGNORED, request.order_id, "Выдача отменена администратором.")

		provider = str((existing or {}).get("provider") or config["link_provider"])
		error = self.provider_config_error(provider, config, settings)
		if error:
			if self.storage.record_error(request, error):
				record = self.storage.get_order(request.order_id) or {}
				self.topic_notifier(record, f"⚠️ Автовыдача #{request.order_id}: {error}")
			return DeliveryOutcome(OUTCOME_IGNORED, request.order_id, error)

		reservation = self.storage.reserve(request, config["shortage_mode"])
		if reservation.status == STATUS_GIST_CREATED:
			return self.request_confirmation(request.order_id)
		if reservation.status == STATUS_AWAITING_CONFIRMATION:
			return DeliveryOutcome(OUTCOME_AWAITING_CONFIRMATION, request.order_id)
		if reservation.status == STATUS_WAITING_STOCK:
			self.notify_shortage_once(
				request.order_id,
				reservation,
				self.storage.stock_count(),
			)
			return DeliveryOutcome(OUTCOME_WAITING_STOCK, request.order_id)
		if reservation.status not in {STATUS_RESERVED, STATUS_PREPARATION_FAILED}:
			return DeliveryOutcome(OUTCOME_IGNORED, request.order_id)

		provider = self.storage.set_provider(request.order_id, provider)
		if reservation.shortage:
			self.notify_shortage_once(
				request.order_id,
				reservation,
				self.storage.stock_count(),
			)
		reservation = self.storage.reserve(request, config["shortage_mode"])
		if provider == "short_io":
			return self.prepare_short_io(request, reservation, config)
		return self.prepare_github(request, reservation, settings)

	def provider_config_error(
		self,
		provider: str,
		config: dict[str, Any],
		settings: dict[str, Any],
	) -> str:
		if provider == "short_io":
			short_io = config["short_io"]
			if not short_io["api_key"]:
				return "Short.io API key не задан."
			if not short_io["domain"]:
				return "Short.io домен не задан."
			return ""
		gist_config = normalize_gist_settings(settings.get("gist"))
		return "" if gist_config["token"] else "GitHub token не задан."

	def prepare_github(
		self,
		request: OrderReservationRequest,
		reservation,
		settings: dict[str, Any],
	) -> DeliveryOutcome:
		if reservation.prepared_links:
			return self.request_confirmation(request.order_id)

		gist_config = normalize_gist_settings(settings.get("gist"))

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
		return self.request_confirmation(request.order_id)

	def prepare_short_io(
		self,
		request: OrderReservationRequest,
		reservation,
		config: dict[str, Any],
	) -> DeliveryOutcome:
		short_io = config["short_io"]
		prepared_count = len(reservation.prepared_links)
		for original_url in reservation.links[prepared_count:]:
			try:
				result = self.short_link_creator(
					short_io["api_key"],
					short_io["domain"],
					original_url,
				)
			except Exception as exc:
				error = str(exc)
				self.storage.mark_preparation_failed(request.order_id, error)
				self.notify_preparation_failure(request.order_id, "Short.io", error)
				return DeliveryOutcome(OUTCOME_IGNORED, request.order_id, error)
			self.storage.append_prepared_link(
				request.order_id,
				original_url,
				result.url,
				result.duplicate,
			)
		return self.request_confirmation(request.order_id)

	def request_confirmation(self, order_id: str) -> DeliveryOutcome:
		self.storage.mark_awaiting_confirmation(order_id)
		if normalize_gemini_delivery_settings(self.settings_getter().get("gemini_delivery"))["mode"] == "auto":
			return self.confirm_order(order_id)
		self.notify_confirmation(order_id)
		return DeliveryOutcome(OUTCOME_AWAITING_CONFIRMATION, order_id)

	def notify_confirmation(self, order_id: str) -> bool:
		try:
			return self.confirmation_notifier(order_id)
		except Exception as exc:
			logger.warning(f"{LOGGER_PREFIX} Failed to request Gemini confirmation for {order_id}: {exc}")
			logger.debug("TRACEBACK", exc_info=True)
			return False

	def notify_preparation_failure(self, order_id: str, provider: str, error: str) -> None:
		record = self.storage.get_order(order_id) or {}
		warning = f"⚠️ Автовыдача #{order_id}: ошибка {provider}.\n{error}"
		try:
			self.topic_notifier(record, warning)
		except Exception:
			logger.debug("TRACEBACK", exc_info=True)
		try:
			self.admin_notifier(warning)
		except Exception:
			logger.debug("TRACEBACK", exc_info=True)

	def confirm_order(self, order_id: str) -> DeliveryOutcome:
		with self.lock:
			record = self.storage.begin_send(order_id)
			if record is None:
				existing = self.storage.get_order(order_id) or {}
				status = existing.get("status")
				if status == STATUS_COMPLETED:
					return DeliveryOutcome(OUTCOME_COMPLETED, order_id)
				if status == STATUS_SEND_FAILED:
					return DeliveryOutcome(OUTCOME_SEND_FAILED, order_id, existing.get("last_error", ""))
				return DeliveryOutcome(OUTCOME_IGNORED, order_id, "Заказ уже обработан.")

			prepared_urls = tuple(item["url"] for item in record.get("prepared_links", []))
			manual_links = "\n".join(prepared_urls)
			config = normalize_gemini_delivery_settings(self.settings_getter().get("gemini_delivery"))
			try:
				chat_id = self.resolve_chat_id(record)
				if chat_id is None:
					raise RuntimeError("Не удалось определить чат покупателя.")
				sent = self.cardinal.send_message(
					chat_id=chat_id,
					message_text=format_gemini_delivery_message(config["message_template"], prepared_urls),
				)
				if sent is False:
					raise RuntimeError("Cardinal не подтвердил отправку.")
			except Exception as exc:
				error = str(exc)
				self.storage.mark_send_failed(order_id, error)
				self.topic_notifier(
					record,
					f"❌ Автовыдача #{order_id}: не удалось отправить сообщение покупателю.\n"
					f"Отправьте ссылки вручную:\n{manual_links}\n"
					f"Ошибка: {error}",
				)
				return DeliveryOutcome(OUTCOME_SEND_FAILED, order_id, error)

			self.storage.mark_completed(order_id)
			return DeliveryOutcome(OUTCOME_COMPLETED, order_id)

	def cancel_order(self, order_id: str) -> DeliveryOutcome:
		with self.lock:
			if self.storage.mark_cancelled(order_id):
				return DeliveryOutcome(OUTCOME_IGNORED, order_id, "Выдача отменена администратором.")
			record = self.storage.get_order(order_id) or {}
			if record.get("status") == STATUS_COMPLETED:
				return DeliveryOutcome(OUTCOME_COMPLETED, order_id)
			return DeliveryOutcome(OUTCOME_IGNORED, order_id, "Заказ уже обработан.")

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
