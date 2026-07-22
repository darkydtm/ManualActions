from __future__ import annotations

from threading import RLock, Timer
from typing import Any, Callable

from .models import (
	DeliveryOutcome,
	OUTCOME_COMPLETED,
	OUTCOME_IGNORED,
	OUTCOME_SEND_FAILED,
	OUTCOME_WAITING_STOCK,
	OrderRequest,
)


class AutoDeliveryService:
	name = ""
	settings_key = ""

	def __init__(
		self,
		cardinal: Any,
		settings_getter: Callable[[], dict[str, Any]],
		storage: Any,
		config_normalizer: Callable[[Any], dict[str, Any]],
		matches: Callable[[str], bool],
		timer_factory: Callable[[int, Callable[[], None]], Any] = Timer,
	):
		self.cardinal = cardinal
		self.settings_getter = settings_getter
		self.storage = storage
		self.config_normalizer = config_normalizer
		self.matches = matches
		self.timer_factory = timer_factory
		self.lock = RLock()

	def config(self) -> dict[str, Any]:
		return self.config_normalizer(self.settings_getter().get(self.settings_key))

	def handle_new_order(self, event: object) -> DeliveryOutcome:
		with self.lock:
			config = self.config()
			if not config["enabled"]:
				return DeliveryOutcome(OUTCOME_IGNORED)
			if config["delay_seconds"] <= 0:
				return self.handle_new_order_locked(event)
			if not self.is_matching_new_order(event):
				return DeliveryOutcome(OUTCOME_IGNORED)
			timer = self.timer_factory(config["delay_seconds"], lambda: self.handle_delayed_new_order(event))
			timer.daemon = True
			timer.start()
			return DeliveryOutcome(OUTCOME_IGNORED)

	def handle_delayed_new_order(self, event: object) -> DeliveryOutcome:
		with self.lock:
			return self.handle_new_order_locked(event)

	def handle_new_order_locked(self, event: object) -> DeliveryOutcome:
		config = self.config()
		if not config["enabled"]:
			return DeliveryOutcome(OUTCOME_IGNORED)
		event_order = getattr(event, "order", None)
		if not event_order:
			return DeliveryOutcome(OUTCOME_IGNORED)
		order = self.get_full_order(event_order)
		if not self.matches(self.order_description(order, event_order)):
			return DeliveryOutcome(OUTCOME_IGNORED)
		request = self.order_request(order, event_order)
		if not request.order_id:
			return DeliveryOutcome(OUTCOME_IGNORED)
		existing = self.storage.get_order(request.order_id)
		if existing:
			status = existing.get("status")
			if status == "completed":
				return DeliveryOutcome(OUTCOME_COMPLETED, request.order_id)
			if status == "send_failed":
				return DeliveryOutcome(OUTCOME_SEND_FAILED, request.order_id, existing.get("last_error", ""))
			if status == "waiting_stock":
				return DeliveryOutcome(OUTCOME_WAITING_STOCK, request.order_id)
		return self.deliver(request, config)

	def is_matching_new_order(self, event: object) -> bool:
		event_order = getattr(event, "order", None)
		if not event_order:
			return False
		order = self.get_full_order(event_order)
		return self.matches(self.order_description(order, event_order)) and bool(self.order_request(order, event_order).order_id)

	def get_full_order(self, event_order: object) -> object:
		try:
			return self.cardinal.account.get_order(getattr(event_order, "id"))
		except Exception:
			return event_order

	@staticmethod
	def order_request(order: object, fallback: object) -> OrderRequest:
		order_id = str(getattr(order, "id", None) or getattr(fallback, "id", "")).strip().lstrip("#")
		buyer = str(getattr(order, "buyer_username", None) or getattr(fallback, "buyer_username", "") or "")
		chat_id = getattr(order, "chat_id", None) or getattr(fallback, "chat_id", None)
		try:
			amount = max(int(getattr(order, "amount", None) or getattr(fallback, "amount", None) or 1), 1)
		except (TypeError, ValueError):
			amount = 1
		return OrderRequest(order_id, amount, buyer, chat_id)

	@staticmethod
	def order_description(order: object, fallback: object) -> str:
		for source in (order, fallback):
			for field in ("full_description", "description", "title"):
				value = getattr(source, field, None)
				if isinstance(value, str) and value:
					return value
		return ""

	def deliver(self, request: OrderRequest, config: dict[str, Any]) -> DeliveryOutcome:
		raise NotImplementedError
