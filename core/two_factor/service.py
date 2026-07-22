from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from ..funpay.messages import MessageContext
from ..runtime import ExternalResult, call_external
from .commands import parse_code_request
from .parser import extract_secret
from .storage import TwoFactorStorage
from .totp import generate_totp


@dataclass(frozen=True)
class TwoFactorOutcome:
	status: str
	message: str = ""

	def __bool__(self) -> bool:
		return self.status != "ignored"


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

	def handle_seller_message(self, context: MessageContext) -> TwoFactorOutcome:
		if not context.is_seller:
			return TwoFactorOutcome("ignored")

		label = self.settings_getter()["two_factor"]["label"]
		secret = extract_secret(context.text, label)
		if not secret:
			return TwoFactorOutcome("ignored")

		result = call_external(lambda: self.storage.save(context.chat_id, secret), (secret,))
		if not result.succeeded:
			return TwoFactorOutcome("unavailable", result.error)
		return TwoFactorOutcome("stored")

	def handle_code_request(self, context: MessageContext) -> TwoFactorOutcome:
		request = parse_code_request(context.text)
		if not request:
			return TwoFactorOutcome("ignored")

		chat_id = context.chat_id
		if request.order_id:
			order_result = self.order_chat_id(request.order_id)
			if not order_result.succeeded:
				self.send(context.chat_id, "❌ Не удалось получить данные заказа для 2FA-кода.")
				return TwoFactorOutcome("unavailable", order_result.error)
			chat_id = order_result.value
		record = self.storage.get_for_chat(chat_id) if chat_id is not None else None
		if not record:
			if request.order_id:
				return self.respond(context.chat_id, f"❌ Для заказа #{request.order_id} 2FA-секрет не найден.")
			else:
				return self.respond(context.chat_id, "❌ В этом чате нет сохранённого 2FA-секрета.")

		try:
			code = generate_totp(record["secret"])
		except ValueError:
			return self.respond(context.chat_id, "❌ Сохранённый 2FA-секрет некорректен.")

		label = f" для заказа #{request.order_id}" if request.order_id else ""
		return self.respond(context.chat_id, f"🔐 2FA-код{label}: {code}")

	def order_chat_id(self, order_id: str) -> ExternalResult:
		result = call_external(lambda: self.cardinal.account.get_order(order_id))
		if not result.succeeded:
			return result
		return ExternalResult(True, getattr(result.value, "chat_id", None))

	def respond(self, chat_id: int | str, text: str) -> TwoFactorOutcome:
		result = self.send(chat_id, text)
		return TwoFactorOutcome("sent" if result.succeeded else "unavailable", result.error)

	def send(self, chat_id: int | str, text: str) -> ExternalResult:
		return call_external(lambda: self.cardinal.send_message(chat_id=chat_id, message_text=text))
