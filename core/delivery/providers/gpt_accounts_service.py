from __future__ import annotations

import logging
import re
from threading import Timer
from typing import Any, Callable

from ...config.constants import LOGGER_NAME, LOGGER_PREFIX
from ...funpay.chat_sync import find_chat_sync_topic, get_chat_sync_obj, send_chat_sync_topic_message
from ...runtime import run_effects
from ..models import DeliveryOutcome, OUTCOME_COMPLETED, OUTCOME_IGNORED, OUTCOME_SEND_FAILED, OUTCOME_WAITING_STOCK
from ..service import AutoDeliveryService
from .gpt_accounts import format_delivery_message, normalize_gpt_accounts_delivery_settings
from .gpt_accounts_storage import (
	GptAccountsDeliveryStorage,
	OrderReservationRequest,
	STATUS_COMPLETED,
	STATUS_SEND_FAILED,
	STATUS_WAITING_STOCK,
)


logger = logging.getLogger(LOGGER_NAME)
GPT_ACCOUNTS_MARKER_PATTERN = re.compile(r"#gptacc\b", re.IGNORECASE)
class GptAccountsDeliveryService(AutoDeliveryService):
	name = "gpt_accounts"
	settings_key = "gpt_accounts_delivery"
	def __init__(
		self,
		cardinal,
		settings_getter: Callable[[], dict[str, Any]],
		storage: GptAccountsDeliveryStorage,
		topic_notifier: Callable[[dict[str, Any], str], bool] | None = None,
		admin_notifier: Callable[[str], None] | None = None,
		timer_factory: Callable[[int, Callable[[], None]], Any] = Timer,
	):
		super().__init__(
			cardinal,
			settings_getter,
			storage,
			normalize_gpt_accounts_delivery_settings,
			has_gpt_accounts_marker,
			timer_factory,
		)
		self.topic_notifier = topic_notifier or self.notify_chat_sync
		self.admin_notifier = admin_notifier or (lambda text: None)
		self.handle_new_order = AutoDeliveryService.handle_new_order.__get__(self)
		self.handle_delayed_new_order = AutoDeliveryService.handle_delayed_new_order.__get__(self)
		self.handle_new_order_locked = AutoDeliveryService.handle_new_order_locked.__get__(self)
		self.is_matching_new_order = AutoDeliveryService.is_matching_new_order.__get__(self)

	def handle_new_order(self, event: object) -> DeliveryOutcome:
		with self.lock:
			config = normalize_gpt_accounts_delivery_settings(self.settings_getter().get("gpt_accounts_delivery"))
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
		config = normalize_gpt_accounts_delivery_settings(self.settings_getter().get("gpt_accounts_delivery"))
		if not config["enabled"]:
			return DeliveryOutcome(OUTCOME_IGNORED)
		event_order = getattr(event, "order", None)
		if not event_order:
			return DeliveryOutcome(OUTCOME_IGNORED)
		order = self.get_full_order(event_order)
		if not has_gpt_accounts_marker(self.order_description(order, event_order)):
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
		return self.deliver(request, config)

	def is_matching_new_order(self, event: object) -> bool:
		event_order = getattr(event, "order", None)
		if not event_order:
			return False
		order = self.get_full_order(event_order)
		if not has_gpt_accounts_marker(self.order_description(order, event_order)):
			return False
		return bool(self.order_request(order, event_order).order_id)

	def retry_order(self, order_id: str) -> DeliveryOutcome:
		with self.lock:
			record = self.storage.get_order(order_id)
			if not record:
				return DeliveryOutcome(OUTCOME_IGNORED, str(order_id))
			config = normalize_gpt_accounts_delivery_settings(self.settings_getter().get("gpt_accounts_delivery"))
			if not config["enabled"]:
				return DeliveryOutcome(OUTCOME_IGNORED, str(order_id), "Автовыдача ChatGPT выключена.")
			if record.get("status") == STATUS_SEND_FAILED and record.get("reserved_accounts"):
				return self.send_reserved(record, config)
			request = OrderReservationRequest(
				str(record.get("order_id") or order_id),
				int(record.get("requested_amount") or 1),
				str(record.get("buyer_username") or ""),
				record.get("fp_chat_id"),
			)
			return self.deliver(request, config)

	def deliver(self, request: OrderReservationRequest, config: dict[str, Any]) -> DeliveryOutcome:
		reservation = self.storage.reserve(request, config["shortage_mode"])
		if reservation.status == STATUS_WAITING_STOCK:
			self.notify_shortage_once(request.order_id, reservation.requested_amount, 0)
			return DeliveryOutcome(OUTCOME_WAITING_STOCK, request.order_id)
		if reservation.shortage:
			self.notify_shortage_once(request.order_id, reservation.requested_amount, len(reservation.accounts))
		record = self.storage.get_order(request.order_id) or {}
		return self.send_reserved(record, config)

	def send_reserved(self, record: dict[str, Any], config: dict[str, Any]) -> DeliveryOutcome:
		order_id = str(record.get("order_id") or "")
		accounts = tuple(self.storage.account(value) for value in record.get("reserved_accounts", []))
		try:
			chat_id = self.resolve_chat_id(record)
			if chat_id is None:
				raise RuntimeError("Не удалось определить чат покупателя.")
			sent = self.cardinal.send_message(
				chat_id=chat_id,
				message_text=format_delivery_message(config["message_template"], accounts),
			)
			if sent is False:
				raise RuntimeError("Cardinal не подтвердил отправку.")
		except Exception as exc:
			error = str(exc)
			self.storage.mark_send_failed(order_id, error)
			self.notify_topic(record, f"❌ Автовыдача ChatGPT #{order_id}: не удалось отправить аккаунты. Ошибка: {error}")
			return DeliveryOutcome(OUTCOME_SEND_FAILED, order_id, error)
		self.storage.mark_completed(order_id)
		return DeliveryOutcome(OUTCOME_COMPLETED, order_id)

	def notify_shortage_once(self, order_id: str, requested: int, delivered: int) -> None:
		if not self.storage.mark_shortage_notified(order_id):
			return
		record = self.storage.get_order(order_id) or {}
		text = f"⚠️ Нехватка ChatGPT-аккаунтов для заказа #{order_id}.\nТребуется: {requested}\nВыдано: {delivered}\nОсталось в стоке: {self.storage.stock_count()}"
		results = run_effects((
			lambda: self.notify_buyer(record, text),
			lambda: self.notify_topic(record, text),
			lambda: self.admin_notifier(text),
		))
		for result in results:
			if not result.succeeded:
				logger.warning(
					f"{LOGGER_PREFIX} Failed to notify about ChatGPT account shortage: {result.error}"
				)

	def notify_buyer(self, record: dict[str, Any], text: str) -> None:
		chat_id = self.resolve_chat_id(record)
		if chat_id is not None:
			self.cardinal.send_message(chat_id=chat_id, message_text=text)

	def notify_topic(self, record: dict[str, Any], text: str) -> None:
		try:
			self.topic_notifier(record, text)
		except Exception as exc:
			logger.warning(f"{LOGGER_PREFIX} Failed to notify Chat Sync about ChatGPT delivery: {exc}")

	def notify_chat_sync(self, record: dict[str, Any], text: str) -> bool:
		topic = find_chat_sync_topic(record.get("fp_chat_id"), str(record.get("buyer_username") or ""))
		cs = get_chat_sync_obj()
		bot = getattr(cs, "current_bot", None) if cs else None
		if not bot:
			telegram = getattr(self.cardinal, "telegram", None)
			bot = getattr(telegram, "bot", None) if telegram else None
		return bool(topic and bot and send_chat_sync_topic_message(bot, topic, text))

	def get_full_order(self, event_order: object) -> object:
		try:
			return self.cardinal.account.get_order(getattr(event_order, "id"))
		except Exception:
			return event_order

	def order_request(self, order: object, fallback: object) -> OrderReservationRequest:
		order_id = str(getattr(order, "id", None) or getattr(fallback, "id", "")).strip().lstrip("#")
		buyer = str(getattr(order, "buyer_username", None) or getattr(fallback, "buyer_username", "") or "")
		chat_id = getattr(order, "chat_id", None) or getattr(fallback, "chat_id", None)
		amount = getattr(order, "amount", None) or getattr(fallback, "amount", None) or 1
		try:
			requested = max(int(amount), 1)
		except (TypeError, ValueError):
			requested = 1
		return OrderReservationRequest(order_id, requested, buyer, chat_id)

	def resolve_chat_id(self, record: dict[str, Any]) -> int | str | None:
		if record.get("fp_chat_id") is not None:
			return record["fp_chat_id"]
		username = str(record.get("buyer_username") or "")
		chat = self.cardinal.account.get_chat_by_name(username, True) if username else None
		return getattr(chat, "id", None) if chat else None

	@staticmethod
	def order_description(order: object, fallback: object) -> str:
		for source in (order, fallback):
			for field in ("full_description", "description", "title"):
				value = getattr(source, field, None)
				if isinstance(value, str) and value:
					return value
		return ""


def has_gpt_accounts_marker(text: str) -> bool:
	return bool(GPT_ACCOUNTS_MARKER_PATTERN.search(text or ""))
