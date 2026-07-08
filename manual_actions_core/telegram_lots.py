from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

import telebot
from telebot.types import InlineKeyboardButton as B, InlineKeyboardMarkup as K

from .chat_sync import TopicContext, get_topic_context, is_in_sync_chat
from .constants import CBT_LOT_REFRESH, CBT_LOT_SECTION, CBT_LOT_VIEWED
from .lots import (
	LOT_SECTION_LABELS,
	extract_lot_id,
	find_lot,
	format_lot_menu,
	format_lot_section,
	get_viewed_lot,
	lot_public_link,
)
from .payloads import parse_three_part_payload
from .telegram_ui import delete_controlled_message, message_thread_id, send_menu

if TYPE_CHECKING:
	from cardinal import Cardinal


class LotsHost(Protocol):
	tg: object
	tgbot: telebot.TeleBot
	cardinal: Cardinal
	settings: dict[str, Any]


class TelegramLotsFlow:
	def __init__(self, host: LotsHost):
		self.host = host

	def register(self) -> None:
		self.host.tg.cbq_handler(
			self.refresh_callback,
			lambda c: (c.data or "").startswith(CBT_LOT_REFRESH),
		)
		self.host.tg.cbq_handler(
			self.show_viewed_callback,
			lambda c: (c.data or "").startswith(CBT_LOT_VIEWED),
		)
		self.host.tg.cbq_handler(
			self.section_callback,
			lambda c: (c.data or "").startswith(CBT_LOT_SECTION),
		)
		self.host.tg.msg_handler(self.cmd_lot, commands=["lot"])

	def cmd_lot(self, message: telebot.types.Message) -> None:
		args = (message.text or "").split(maxsplit=1)
		if len(args) > 1:
			self.show_by_query(message.chat.id, args[1].strip(), message_thread_id(message))
			return

		if is_in_sync_chat(message):
			context = get_topic_context(self.host.cardinal, message)
			if not context:
				self.host.tgbot.reply_to(message, "❌ Не удалось определить пользователя из топика.")
				return
			self.show_viewed(message.chat.id, context.fp_chat_id, message_thread_id(message))
			return

		self.host.tgbot.reply_to(message, "⚠️ Использование: /lot <ID лота>\nИли /lot в топике Chat Sync.")

	def show_by_query(self, chat_id: int, query: str, thread_id: int | None = None) -> None:
		lot = find_lot(self.host.cardinal, query)
		lot_id = extract_lot_id(query) or query
		link = lot_public_link(lot)
		keyboard = self.build_menu_keyboard("lot", lot_id, link)
		send_menu(self.host.tgbot, chat_id, format_lot_menu(lot), keyboard, thread_id)

	def show_viewed(self, chat_id: int, fp_chat_id: int, thread_id: int | None = None) -> None:
		context = TopicContext(username="", fp_chat_id=fp_chat_id, thread_id=thread_id or 0)
		viewed = get_viewed_lot(self.host.cardinal, context)
		keyboard = self.build_menu_keyboard("viewed", str(fp_chat_id), viewed.link)
		text = format_lot_menu(viewed.lot, viewed.text, viewed.link)
		send_menu(self.host.tgbot, chat_id, text, keyboard, thread_id)

	def show_by_query_section(self, chat_id: int, query: str, section: str, thread_id: int | None = None) -> None:
		lot = find_lot(self.host.cardinal, query)
		lot_id = extract_lot_id(query) or query
		link = lot_public_link(lot)
		keyboard = self.build_section_keyboard("lot", lot_id, link)
		send_menu(self.host.tgbot, chat_id, format_lot_section(lot, section), keyboard, thread_id)

	def show_viewed_section(self, chat_id: int, fp_chat_id: int, section: str, thread_id: int | None = None) -> None:
		context = TopicContext(username="", fp_chat_id=fp_chat_id, thread_id=thread_id or 0)
		viewed = get_viewed_lot(self.host.cardinal, context)
		keyboard = self.build_section_keyboard("viewed", str(fp_chat_id), viewed.link)
		text = format_lot_section(viewed.lot, section, viewed.text, viewed.link)
		send_menu(self.host.tgbot, chat_id, text, keyboard, thread_id)

	def refresh_callback(self, call: telebot.types.CallbackQuery) -> None:
		query = call.data.replace(CBT_LOT_REFRESH, "", 1)
		self.host.tgbot.answer_callback_query(call.id)
		delete_controlled_message(self.host.tgbot, call.message)
		self.show_by_query(call.message.chat.id, query, message_thread_id(call.message))

	def show_viewed_callback(self, call: telebot.types.CallbackQuery) -> None:
		chat_id = int(call.data.replace(CBT_LOT_VIEWED, "", 1))
		self.host.tgbot.answer_callback_query(call.id)
		delete_controlled_message(self.host.tgbot, call.message)
		self.show_viewed(call.message.chat.id, chat_id, message_thread_id(call.message))

	def section_callback(self, call: telebot.types.CallbackQuery) -> None:
		mode, target, section = parse_three_part_payload(call.data.replace(CBT_LOT_SECTION, "", 1))
		self.host.tgbot.answer_callback_query(call.id)
		delete_controlled_message(self.host.tgbot, call.message)
		if mode == "viewed":
			self.show_viewed_section(call.message.chat.id, int(target), section, message_thread_id(call.message))
			return
		self.show_by_query_section(call.message.chat.id, target, section, message_thread_id(call.message))

	def build_menu_keyboard(self, mode: str, target: str, link: str | None = None) -> K:
		keyboard = K(row_width=1)
		for section, label in LOT_SECTION_LABELS.items():
			keyboard.add(B(label, callback_data=f"{CBT_LOT_SECTION}{mode}|{target}|{section}"))
		if link:
			keyboard.add(B("🔗 Открыть лот", url=link))
		keyboard.add(B("🔄 Обновить", callback_data=self.refresh_callback_data(mode, target)))
		return keyboard

	def build_section_keyboard(self, mode: str, target: str, link: str | None = None) -> K:
		keyboard = K(row_width=1)
		if link:
			keyboard.add(B("🔗 Открыть лот", url=link))
		keyboard.add(B("◀️ Назад", callback_data=self.refresh_callback_data(mode, target)))
		return keyboard

	def refresh_callback_data(self, mode: str, target: str) -> str:
		if mode == "viewed":
			return f"{CBT_LOT_VIEWED}{target}"
		return f"{CBT_LOT_REFRESH}{target}"
