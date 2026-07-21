from __future__ import annotations

from typing import Any, Callable

from ..funpay.messages import MessageContext
from .commands import parse_code_request
from .parser import extract_secret
from .storage import TwoFactorStorage
from .totp import generate_totp


class TwoFactorService:
	def __init__(
		self,
		cardinal,
		settings_getter: Callable[[], dict[str, Any]],
		storage: TwoFactorStorage,
	):
		self.cardinal = cardinal
		self.settings_getter = settings_getter
		self.storage = storage

	def handle_new_order(self, event: object) -> None:
		event_order = getattr(event, "order", None)
		if not event_order:
			return

		order = self.get_full_order(event_order)
		order_id = self.order_id(order, event_order)
		chat_id = self.chat_id(order, event_order)
		label = self.settings_getter()["two_factor"]["label"]
		secret = extract_secret(self.order_description(order, event_order), label)
		if order_id and chat_id is not None and secret:
			self.storage.save(order_id, chat_id, secret)

	def handle_code_request(self, context: MessageContext) -> bool:
		request = parse_code_request(context.text)
		if not request:
			return False

		record = self.storage.get(request.order_id) if request.order_id else self.storage.latest_for_chat(context.chat_id)
		if not record:
			if request.order_id:
				self.send(context.chat_id, f"❌ Для заказа #{request.order_id} 2FA-секрет не найден.")
			else:
				self.send(context.chat_id, "❌ В этом чате нет сохранённого 2FA-секрета.")
			return True

		try:
			code = generate_totp(record["secret"])
		except ValueError:
			self.send(context.chat_id, f"❌ 2FA-секрет заказа #{record['order_id']} некорректен.")
			return True

		self.send(context.chat_id, f"🔐 2FA-код для заказа #{record['order_id']}: {code}")
		return True

	def get_full_order(self, event_order: object) -> object:
		try:
			return self.cardinal.account.get_order(getattr(event_order, "id"))
		except Exception:
			return event_order

	def send(self, chat_id: int | str, text: str) -> None:
		self.cardinal.send_message(chat_id=chat_id, message_text=text)

	@staticmethod
	def order_id(order: object, fallback_order: object) -> str:
		return TwoFactorStorage.normalize_order_id(
			getattr(order, "id", None) or getattr(fallback_order, "id", "")
		)

	@staticmethod
	def chat_id(order: object, fallback_order: object) -> int | str | None:
		chat_id = getattr(order, "chat_id", None)
		return chat_id if chat_id is not None else getattr(fallback_order, "chat_id", None)

	@staticmethod
	def order_description(order: object, fallback_order: object) -> str:
		for source in (order, fallback_order):
			for field in ("full_description", "description", "title"):
				value = getattr(source, field, None)
				if isinstance(value, str) and value:
					return value
		return ""
