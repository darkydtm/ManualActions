from __future__ import annotations

from dataclasses import dataclass
from html import escape as html_escape
from secrets import token_urlsafe
from typing import TYPE_CHECKING, Any, Protocol

import telebot
from telebot.types import InlineKeyboardButton as B, InlineKeyboardMarkup as K

from ..funpay.chat_sync import get_topic_context, is_in_sync_chat
from ..funpay.orders import get_pending_orders_for_user, format_order_price
from ..constants import CBT_PASTEBIN_ORDER_CANCEL, CBT_PASTEBIN_ORDER_SELECT
from .service import create_pastebin, pastebin_config_errors, pastebin_error_text, resolve_paste_title
from .settings import normalize_pastebin_settings

if TYPE_CHECKING:
	from cardinal import Cardinal


class PastebinCommandHost(Protocol):
	tg: object
	tgbot: telebot.TeleBot
	cardinal: Cardinal
	settings: dict[str, Any]


@dataclass(frozen=True)
class PendingPasteRequest:
	text: str
	context: Any
	order_ids: tuple[str, ...]


class TelegramPastebinFlow:
	def __init__(self, host: PastebinCommandHost):
		self.host = host
		self.pending_requests: dict[str, PendingPasteRequest] = {}

	def register(self) -> None:
		self.host.tg.msg_handler(self.cmd_pastebin, commands=["pastebin"])
		self.host.tg.cbq_handler(
			self.select_order,
			lambda c: (c.data or "").startswith(CBT_PASTEBIN_ORDER_SELECT),
		)
		self.host.tg.cbq_handler(
			self.cancel_order_selection,
			lambda c: (c.data or "").startswith(CBT_PASTEBIN_ORDER_CANCEL),
		)

	def cmd_pastebin(self, message: telebot.types.Message) -> None:
		pastebin_settings = self.host.settings.get("pastebin", {})
		config = normalize_pastebin_settings(pastebin_settings)
		request = pastebin_request_from_message(message, config["title"]["mode"] == "order_id")
		if not request.text:
			self.host.tgbot.reply_to(
				message,
				"⚠️ Использование: /pastebin <текст>\n"
				"Или ответьте командой /pastebin на сообщение с текстом.",
			)
			return

		if config["title"]["mode"] == "order_id" and not request.order_id and is_in_sync_chat(message):
			self.start_order_selection(message, pastebin_settings, request.text)
			return

		config_errors = pastebin_config_errors(pastebin_settings, request.order_id)
		if config_errors:
			self.host.tgbot.reply_to(message, self.format_config_errors(config_errors))
			return

		wait_message = self.host.tgbot.reply_to(message, "⏳ Создаю Pastebin...")
		try:
			username = self.chat_sync_username(message)
			title = resolve_paste_title(pastebin_settings, username, request.order_id)
			result = create_pastebin(pastebin_settings, request.text, title=title)
		except Exception as exc:
			self.host.tgbot.edit_message_text(
				f"❌ {html_escape(pastebin_error_text(exc))}",
				wait_message.chat.id,
				wait_message.message_id,
			)
			return

		self.host.tgbot.edit_message_text(
			self.format_result(result.url),
			wait_message.chat.id,
			wait_message.message_id,
			disable_web_page_preview=True,
		)

	def start_order_selection(
		self,
		message: telebot.types.Message,
		pastebin_settings: dict[str, Any],
		text: str,
	) -> None:
		context = get_topic_context(self.host.cardinal, message)
		if not context:
			self.host.tgbot.reply_to(message, "❌ Не удалось определить пользователя из топика.")
			return

		config_errors = pastebin_config_errors(pastebin_settings, "pending")
		if config_errors:
			self.host.tgbot.reply_to(message, self.format_config_errors(config_errors))
			return

		wait_message = self.host.tgbot.reply_to(message, f"⏳ Получаю список заказов {context.username}...")
		orders = get_pending_orders_for_user(self.host.cardinal, context.username)
		if not orders:
			self.host.tgbot.edit_message_text(
				f"ℹ️ У {html_escape(context.username)} нет неподтверждённых заказов.",
				wait_message.chat.id,
				wait_message.message_id,
			)
			return

		orders = orders[:10]
		token = token_urlsafe(8)
		self.pending_requests[token] = PendingPasteRequest(
			text=text,
			context=context,
			order_ids=tuple(str(getattr(order, "id", "")) for order in orders),
		)
		keyboard = K(row_width=1)
		for order in orders:
			order_id = str(getattr(order, "id", ""))
			keyboard.add(B(
				self.format_order_button(order),
				callback_data=f"{CBT_PASTEBIN_ORDER_SELECT}{token}:{order_id}",
			))
		keyboard.add(B("❌ Отмена", callback_data=f"{CBT_PASTEBIN_ORDER_CANCEL}{token}"))
		self.host.tgbot.edit_message_text(
			f"📝 Выберите заказ для title ({html_escape(context.username)}):",
			wait_message.chat.id,
			wait_message.message_id,
			reply_markup=keyboard,
		)

	def select_order(self, call: telebot.types.CallbackQuery) -> None:
		payload = call.data.replace(CBT_PASTEBIN_ORDER_SELECT, "", 1)
		token, separator, order_id = payload.partition(":")
		request = self.pending_requests.pop(token, None)
		self.host.tgbot.answer_callback_query(call.id)
		if not request or not separator or order_id not in request.order_ids:
			self.host.tgbot.edit_message_text(
				"❌ Запрос выбора заказа истёк.",
				call.message.chat.id,
				call.message.message_id,
				reply_markup=None,
			)
			return

		self.create_from_request(call.message, request.text, order_id)

	def cancel_order_selection(self, call: telebot.types.CallbackQuery) -> None:
		token = call.data.replace(CBT_PASTEBIN_ORDER_CANCEL, "", 1)
		self.pending_requests.pop(token, None)
		self.host.tgbot.answer_callback_query(call.id, "Отменено.")
		self.host.tgbot.edit_message_text(
			"❌ Выбор заказа отменён.",
			call.message.chat.id,
			call.message.message_id,
			reply_markup=None,
		)

	def create_from_request(self, message: telebot.types.Message, text: str, order_id: str) -> None:
		pastebin_settings = self.host.settings.get("pastebin", {})
		try:
			result = create_pastebin(pastebin_settings, text, title=order_id)
		except Exception as exc:
			self.host.tgbot.edit_message_text(
				f"❌ {html_escape(pastebin_error_text(exc))}",
				message.chat.id,
				message.message_id,
				reply_markup=None,
			)
			return

		self.host.tgbot.edit_message_text(
			self.format_result(result.url),
			message.chat.id,
			message.message_id,
			disable_web_page_preview=True,
		)

	def format_order_button(self, order: object) -> str:
		order_id = str(getattr(order, "id", ""))
		return f"#{order_id} - {format_order_price(order)}"

	def chat_sync_username(self, message: telebot.types.Message) -> str | None:
		if not is_in_sync_chat(message):
			return None
		context = get_topic_context(self.host.cardinal, message)
		return context.username if context else None

	def format_result(self, url: str) -> str:
		return f"✅ Pastebin ссылка:\n{html_escape(url)}"

	def format_config_errors(self, errors: list[str]) -> str:
		lines = ["❌ Pastebin не настроен:"]
		lines.extend(f"• {html_escape(error)}" for error in errors)
		return "\n".join(lines)


@dataclass(frozen=True)
class PastebinRequest:
	text: str
	order_id: str = ""


def pastebin_text_from_message(message: telebot.types.Message) -> str:
	return pastebin_request_from_message(message, False).text


def pastebin_request_from_message(message: telebot.types.Message, extract_order_id: bool = False) -> PastebinRequest:
	reply = getattr(message, "reply_to_message", None)
	command_text = getattr(message, "text", None) or ""
	command_args = command_text.split(maxsplit=1)
	command_body = command_args[1].strip() if len(command_args) > 1 else ""
	order_id = ""

	if extract_order_id and command_body:
		order_id, command_body = split_order_id_prefix(command_body)

	if reply:
		reply_text = text_from_telegram_message(reply)
		if reply_text.strip():
			return PastebinRequest(reply_text, order_id)

	return PastebinRequest(command_body, order_id)


def split_order_id_prefix(text: str) -> tuple[str, str]:
	parts = text.split(maxsplit=1)
	if not parts:
		return "", ""

	if not parts[0].startswith("#"):
		return "", text.strip()

	candidate = parts[0].lstrip("#").strip()
	if not is_order_id(candidate):
		return "", text.strip()
	rest = parts[1].strip() if len(parts) > 1 else ""
	return candidate, rest


def is_order_id(value: str) -> bool:
	return bool(value) and value.isalnum()


def text_from_telegram_message(message: telebot.types.Message) -> str:
	for attr in ("text", "caption"):
		value = getattr(message, attr, None)
		if isinstance(value, str):
			return value
	return ""
