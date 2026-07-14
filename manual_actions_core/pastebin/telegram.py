from __future__ import annotations

from dataclasses import dataclass
from html import escape as html_escape
from typing import TYPE_CHECKING, Any, Protocol

import telebot

from ..chat_sync import get_topic_context, is_in_sync_chat
from .service import create_pastebin, pastebin_error_text, resolve_paste_title
from .settings import normalize_pastebin_settings

if TYPE_CHECKING:
	from cardinal import Cardinal


class PastebinCommandHost(Protocol):
	tg: object
	tgbot: telebot.TeleBot
	cardinal: Cardinal
	settings: dict[str, Any]


class TelegramPastebinFlow:
	def __init__(self, host: PastebinCommandHost):
		self.host = host

	def register(self) -> None:
		self.host.tg.msg_handler(self.cmd_pastebin, commands=["pastebin"])

	def cmd_pastebin(self, message: telebot.types.Message) -> None:
		config = normalize_pastebin_settings(self.host.settings["pastebin"])
		request = pastebin_request_from_message(message, config["title"]["mode"] == "order_id")
		if not request.text:
			self.host.tgbot.reply_to(
				message,
				"⚠️ Использование: /pastebin <текст>\n"
				"Или ответьте командой /pastebin на сообщение с текстом.",
			)
			return

		wait_message = self.host.tgbot.reply_to(message, "⏳ Создаю Pastebin...")
		try:
			username = self.chat_sync_username(message)
			title = resolve_paste_title(self.host.settings["pastebin"], username, request.order_id)
			result = create_pastebin(self.host.settings["pastebin"], request.text, title=title)
		except Exception as exc:
			self.host.tgbot.edit_message_text(
				f"❌ {html_escape(pastebin_error_text(exc))}",
				wait_message.chat.id,
				wait_message.message_id,
			)
			return

		self.host.tgbot.edit_message_text(
			self.format_result(result.url, result.password),
			wait_message.chat.id,
			wait_message.message_id,
			disable_web_page_preview=True,
		)

	def chat_sync_username(self, message: telebot.types.Message) -> str | None:
		if not is_in_sync_chat(message):
			return None
		context = get_topic_context(self.host.cardinal, message)
		return context.username if context else None

	def format_result(self, url: str, password: str = "") -> str:
		text = f"✅ Pastebin ссылка:\n{html_escape(url)}"
		if password:
			text += f"\n\n🔒 Пароль:\n<code>{html_escape(password)}</code>"
		return text


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
