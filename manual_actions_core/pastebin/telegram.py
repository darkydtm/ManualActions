from __future__ import annotations

from html import escape as html_escape
from typing import TYPE_CHECKING, Any, Protocol

import telebot

from ..chat_sync import get_topic_context, is_in_sync_chat
from .service import create_pastebin_raw_url, pastebin_error_text, resolve_paste_title

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
		text = pastebin_text_from_message(message)
		if not text:
			self.host.tgbot.reply_to(
				message,
				"⚠️ Использование: /pastebin <текст>\n"
				"Или ответьте командой /pastebin на сообщение с текстом.",
			)
			return

		wait_message = self.host.tgbot.reply_to(message, "⏳ Создаю Pastebin...")
		try:
			username = self.chat_sync_username(message)
			title = resolve_paste_title(self.host.settings["pastebin"], username)
			raw_url = create_pastebin_raw_url(self.host.settings["pastebin"], text, title=title)
		except Exception as exc:
			self.host.tgbot.edit_message_text(
				f"❌ {html_escape(pastebin_error_text(exc))}",
				wait_message.chat.id,
				wait_message.message_id,
			)
			return

		self.host.tgbot.edit_message_text(
			f"✅ Pastebin raw-ссылка:\n{html_escape(raw_url)}",
			wait_message.chat.id,
			wait_message.message_id,
			disable_web_page_preview=True,
		)

	def chat_sync_username(self, message: telebot.types.Message) -> str | None:
		if not is_in_sync_chat(message):
			return None
		context = get_topic_context(self.host.cardinal, message)
		return context.username if context else None


def pastebin_text_from_message(message: telebot.types.Message) -> str:
	reply = getattr(message, "reply_to_message", None)
	if reply:
		reply_text = text_from_telegram_message(reply)
		if reply_text.strip():
			return reply_text

	command_text = getattr(message, "text", None) or ""
	parts = command_text.split(maxsplit=1)
	if len(parts) < 2:
		return ""
	return parts[1].strip()


def text_from_telegram_message(message: telebot.types.Message) -> str:
	for attr in ("text", "caption"):
		value = getattr(message, attr, None)
		if isinstance(value, str):
			return value
	return ""
