from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, Protocol

import telebot
from telebot.types import InlineKeyboardButton as B, InlineKeyboardMarkup as K
from tg_bot import CBT

from ..funpay.chat_sync import TopicContext, get_topic_context, is_in_sync_chat
from ..config.constants import (
	CBT_LOT_REFRESH,
	CBT_LOT_SECTION,
	CBT_LOT_VIEWED,
	CBT_LOTS_CANCEL,
	CBT_LOTS_CONFIRM,
	CBT_LOTS_PAGE,
	CBT_LOTS_REQUEST,
	UUID,
)
from ..funpay.lots import (
	LOT_SECTION_LABELS,
	extract_lot_id,
	find_lot,
	format_lot_menu,
	format_lot_section,
	get_viewed_lot,
	lot_public_link,
)
from ..lots.bulk import ACTION_OFF, ACTION_ON, BulkLotsProgress, BulkLotsResult, BulkLotsService
from ..common.payloads import parse_three_part_payload, parse_two_part_payload
from .ui import delete_controlled_message, message_thread_id, send_menu

if TYPE_CHECKING:
	from cardinal import Cardinal


class LotsHost(Protocol):
	tg: object
	tgbot: telebot.TeleBot
	cardinal: Cardinal
	settings: dict[str, Any]

	def save_settings(self) -> None:
		...


class TelegramLotsFlow:
	def __init__(self, host: LotsHost):
		self.host = host
		self.bulk_lots_service = BulkLotsService(host.cardinal, host.settings, host.save_settings)

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
		self.host.tg.cbq_handler(
			self.open_bulk_lots_page,
			lambda c: (c.data or "").startswith(CBT_LOTS_PAGE),
		)
		self.host.tg.cbq_handler(
			self.request_bulk_action,
			lambda c: (c.data or "").startswith(CBT_LOTS_REQUEST),
		)
		self.host.tg.cbq_handler(
			self.confirm_bulk_action,
			lambda c: (c.data or "").startswith(CBT_LOTS_CONFIRM),
		)
		self.host.tg.cbq_handler(
			self.cancel_bulk_action,
			lambda c: (c.data or "").startswith(CBT_LOTS_CANCEL),
		)
		self.host.tg.msg_handler(self.cmd_lot, commands=["lot"])
		self.host.tg.msg_handler(self.cmd_lots, commands=["lots"])

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

	def cmd_lots(self, message: telebot.types.Message) -> None:
		parts = (message.text or "").split(maxsplit=1)
		action = parts[1].strip().lower() if len(parts) > 1 else ""
		if action not in (ACTION_ON, ACTION_OFF):
			self.host.tgbot.reply_to(message, "⚠️ Использование: /lots on или /lots off")
			return
		self.show_bulk_confirmation(message.chat.id, action, "all", message_thread_id(message))

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

	def open_bulk_lots_page(self, call: telebot.types.CallbackQuery) -> None:
		offset = call.data.replace(CBT_LOTS_PAGE, "", 1) or "0"
		self.host.tgbot.answer_callback_query(call.id)
		self.show_bulk_lots_page(call.message.chat.id, call.message.id, offset)

	def request_bulk_action(self, call: telebot.types.CallbackQuery) -> None:
		action, offset = parse_two_part_payload(call.data.replace(CBT_LOTS_REQUEST, "", 1))
		self.host.tgbot.answer_callback_query(call.id)
		self.show_bulk_confirmation(
			call.message.chat.id,
			action,
			offset,
			message_thread_id(call.message),
			call.message.id,
		)

	def confirm_bulk_action(self, call: telebot.types.CallbackQuery) -> None:
		action, _ = parse_two_part_payload(call.data.replace(CBT_LOTS_CONFIRM, "", 1))
		if action not in (ACTION_ON, ACTION_OFF):
			self.host.tgbot.answer_callback_query(call.id, "Действие устарело.")
			return

		if not self.bulk_lots_service.start(
			action,
			self.progress_callback(call.message),
			self.complete_callback(call.message),
		):
			self.host.tgbot.answer_callback_query(call.id, "Операция с лотами уже выполняется.")
			return
		self.host.tgbot.answer_callback_query(call.id, "Запускаю...")

	def cancel_bulk_action(self, call: telebot.types.CallbackQuery) -> None:
		_, offset = parse_two_part_payload(call.data.replace(CBT_LOTS_CANCEL, "", 1))
		self.host.tgbot.answer_callback_query(call.id, "Отменено.")
		self.show_bulk_lots_page(call.message.chat.id, call.message.id, offset)

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

	def show_bulk_lots_page(self, chat_id: int, message_id: int, offset: str) -> None:
		disabled_ids = self.host.settings["bulk_lots"]["disabled_lot_ids"]
		keyboard = K(row_width=1)
		keyboard.add(B("🔴 Выключить все активные", callback_data=f"{CBT_LOTS_REQUEST}{ACTION_OFF}|{offset}"))
		keyboard.add(B("🟢 Включить выключенные", callback_data=f"{CBT_LOTS_REQUEST}{ACTION_ON}|{offset}"))
		keyboard.add(B("◀️ Назад", callback_data=f"{CBT.PLUGIN_SETTINGS}:{UUID}:{offset}"))
		self.host.tgbot.edit_message_text(
			"<b>Управление лотами</b>\n\n"
			f"Выключено этой функцией: <b>{len(disabled_ids)}</b>",
			chat_id,
			message_id,
			reply_markup=keyboard,
		)

	def show_bulk_confirmation(
		self,
		chat_id: int,
		action: str,
		offset: str,
		thread_id: int | None,
		message_id: int | None = None,
	) -> None:
		if action not in (ACTION_ON, ACTION_OFF):
			self.send_bulk_error(chat_id, thread_id, message_id)
			return

		try:
			count = self.bulk_lots_service.preview_count(action)
		except Exception:
			self.send_bulk_error(chat_id, thread_id, message_id)
			return

		if count == 0:
			text = "ℹ️ Нет лотов для включения." if action == ACTION_ON else "ℹ️ Нет активных лотов для выключения."
			self.send_or_edit_bulk_message(chat_id, text, None, thread_id, message_id)
			return

		keyboard = K(row_width=1)
		keyboard.add(B("✅ Подтвердить", callback_data=f"{CBT_LOTS_CONFIRM}{action}|{offset}"))
		keyboard.add(B("❌ Отмена", callback_data=f"{CBT_LOTS_CANCEL}{action}|{offset}"))
		text = f"{self.action_label(action, True)} лоты: <b>{count}</b>?"
		self.send_or_edit_bulk_message(chat_id, text, keyboard, thread_id, message_id)

	def progress_callback(self, message: Any):
		last_edit = 0.0

		def update(progress: BulkLotsProgress) -> None:
			nonlocal last_edit
			now = time.monotonic()
			if progress.processed != 1 and now - last_edit < 1:
				return
			last_edit = now
			self.host.tgbot.edit_message_text(
				self.format_bulk_progress(progress),
				message.chat.id,
				message.id,
				reply_markup=None,
			)

		return update

	def complete_callback(self, message: Any):
		def complete(result: BulkLotsResult) -> None:
			self.host.tgbot.edit_message_text(
				self.format_bulk_progress(result, complete=True),
				message.chat.id,
				message.id,
				reply_markup=None,
			)

		return complete

	def format_bulk_progress(self, progress: BulkLotsProgress, complete: bool = False) -> str:
		if progress.total == 0:
			return "ℹ️ Нет лотов для включения." if progress.action == ACTION_ON else "ℹ️ Нет активных лотов для выключения."

		label = self.action_label(progress.action)
		headline = f"✅ {label} лотов завершено" if complete else f"⏳ {label} лотов: <b>{progress.processed} из {progress.total}</b>"
		return (
			f"{headline}\n\n"
			f"✅ Успешно: <b>{progress.succeeded}</b>\n"
			f"⏭ Пропущено: <b>{progress.skipped}</b>\n"
			f"❌ Ошибки: <b>{progress.failed}</b>"
		)

	def send_bulk_error(self, chat_id: int, thread_id: int | None, message_id: int | None) -> None:
		self.send_or_edit_bulk_message(chat_id, "❌ Не удалось получить список лотов.", None, thread_id, message_id)

	def send_or_edit_bulk_message(
		self,
		chat_id: int,
		text: str,
		keyboard: K | None,
		thread_id: int | None,
		message_id: int | None,
	) -> None:
		if message_id is not None:
			self.host.tgbot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard)
			return
		send_menu(self.host.tgbot, chat_id, text, keyboard or K(), thread_id)

	@staticmethod
	def action_label(action: str, imperative: bool = False) -> str:
		if action == ACTION_ON:
			return "Включить" if imperative else "Включение"
		return "Выключить" if imperative else "Выключение"

	def refresh_callback_data(self, mode: str, target: str) -> str:
		if mode == "viewed":
			return f"{CBT_LOT_VIEWED}{target}"
		return f"{CBT_LOT_REFRESH}{target}"
