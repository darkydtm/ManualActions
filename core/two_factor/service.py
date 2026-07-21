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

	def handle_seller_message(self, context: MessageContext) -> None:
		if not context.is_seller:
			return

		label = self.settings_getter()["two_factor"]["label"]
		secret = extract_secret(context.text, label)
		if secret:
			self.storage.save(context.chat_id, secret)

	def handle_code_request(self, context: MessageContext) -> bool:
		request = parse_code_request(context.text)
		if not request:
			return False

		chat_id = context.chat_id
		if request.order_id:
			chat_id = self.order_chat_id(request.order_id)
		record = self.storage.get_for_chat(chat_id) if chat_id is not None else None
		if not record:
			if request.order_id:
				self.send(context.chat_id, f"❌ Для заказа #{request.order_id} 2FA-секрет не найден.")
			else:
				self.send(context.chat_id, "❌ В этом чате нет сохранённого 2FA-секрета.")
			return True

		try:
			code = generate_totp(record["secret"])
		except ValueError:
			self.send(context.chat_id, "❌ Сохранённый 2FA-секрет некорректен.")
			return True

		label = f" для заказа #{request.order_id}" if request.order_id else ""
		self.send(context.chat_id, f"🔐 2FA-код{label}: {code}")
		return True

	def order_chat_id(self, order_id: str) -> int | str | None:
		try:
			order = self.cardinal.account.get_order(order_id)
		except Exception:
			return None
		return getattr(order, "chat_id", None)

	def send(self, chat_id: int | str, text: str) -> None:
		self.cardinal.send_message(chat_id=chat_id, message_text=text)
