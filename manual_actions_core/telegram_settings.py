from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

import telebot
import tg_bot.static_keyboards
from telebot.types import InlineKeyboardButton as B, InlineKeyboardMarkup as K
from tg_bot import CBT
from tg_bot.utils import escape

from .blacklist import remove_user_from_blacklist
from .constants import (
	CBT_BLACKLIST_PAGE,
	CBT_BL_UNBL,
	CBT_STATUS_EDIT_AUTO,
	CBT_STATUS_EDIT_RESPONSE,
	CBT_STATUS_PAGE,
	CBT_STATUS_SET,
	CBT_STATUS_TOGGLE_AUTO,
	STATE_STATUS_AUTO,
	STATE_STATUS_RESPONSE,
	UUID,
)
from .status import STATUS_IDS, status_label

if TYPE_CHECKING:
	from cardinal import Cardinal


class SettingsHost(Protocol):
	tg: object
	tgbot: telebot.TeleBot
	cardinal: Cardinal
	settings: dict[str, Any]

	def save_settings(self) -> None:
		...


class TelegramSettingsUI:
	def __init__(self, host: SettingsHost):
		self.host = host

	def register(self) -> None:
		if not self.host.tg:
			return

		self.host.tg.msg_handler(
			self.save_response_text,
			func=lambda m: self.host.tg.check_state(m.chat.id, m.from_user.id, STATE_STATUS_RESPONSE),
		)
		self.host.tg.msg_handler(
			self.save_auto_text,
			func=lambda m: self.host.tg.check_state(m.chat.id, m.from_user.id, STATE_STATUS_AUTO),
		)
		self.host.tg.cbq_handler(
			self.open_settings,
			lambda c: f"{CBT.PLUGIN_SETTINGS}:{UUID}" in (c.data or ""),
		)
		self.host.tg.cbq_handler(
			self.open_status_page,
			lambda c: (c.data or "").startswith(CBT_STATUS_PAGE),
		)
		self.host.tg.cbq_handler(
			self.set_status,
			lambda c: (c.data or "").startswith(CBT_STATUS_SET),
		)
		self.host.tg.cbq_handler(
			self.edit_response_text,
			lambda c: (c.data or "").startswith(CBT_STATUS_EDIT_RESPONSE),
		)
		self.host.tg.cbq_handler(
			self.edit_auto_text,
			lambda c: (c.data or "").startswith(CBT_STATUS_EDIT_AUTO),
		)
		self.host.tg.cbq_handler(
			self.toggle_auto_message,
			lambda c: (c.data or "").startswith(CBT_STATUS_TOGGLE_AUTO),
		)
		self.host.tg.cbq_handler(
			self.open_blacklist_page_callback,
			lambda c: (c.data or "").startswith(CBT_BLACKLIST_PAGE),
		)
		self.host.tg.cbq_handler(
			self.unblock_user,
			lambda c: (c.data or "").startswith(CBT_BL_UNBL),
		)

	def open_settings(self, call: telebot.types.CallbackQuery) -> None:
		offset = self.get_offset(call.data)
		keyboard = K(row_width=1)
		keyboard.add(B("Статусы", callback_data=f"{CBT_STATUS_PAGE}{offset}"))
		keyboard.add(B("Чёрный список", callback_data=f"{CBT_BLACKLIST_PAGE}{offset}"))
		keyboard.add(B("◀️ Назад", callback_data=f"{CBT.EDIT_PLUGIN}:{UUID}:{offset}"))
		text = (
			"<b>Manual Actions</b>\n\n"
			f"Текущий статус: <b>{escape(status_label(self.host.settings['status']))}</b>"
		)
		self.host.tgbot.edit_message_text(
			text,
			call.message.chat.id,
			call.message.id,
			reply_markup=keyboard,
		)
		self.host.tgbot.answer_callback_query(call.id)

	def open_status_page(self, call: telebot.types.CallbackQuery) -> None:
		offset = self.get_offset(call.data)
		self.show_status_page(call.message.chat.id, call.message.id, offset=offset, edit=True)
		self.host.tgbot.answer_callback_query(call.id)

	def show_status_page(self, chat_id: int, message_id: int | None = None, offset: str = "0", edit: bool = False) -> None:
		current = self.host.settings["status"]
		lines = [f"<b>Статусы</b>\n\nТекущий: <b>{escape(status_label(current))}</b>"]
		keyboard = K(row_width=1)

		for status_id in STATUS_IDS:
			label = status_label(status_id)
			response = self.host.settings["status_response_texts"][status_id].strip() or "не задан"
			auto_config = self.host.settings["status_auto_messages"][status_id]
			auto_text = str(auto_config["text"]).strip() or "не задан"
			auto_state = "вкл" if auto_config["enabled"] else "выкл"
			marker = "✅ " if current == status_id else ""

			lines.append(
				f"\n<b>{status_id}. {escape(label)}</b>\n"
				f"!status: <code>{escape(self.preview(response))}</code>\n"
				f"Авто: <b>{auto_state}</b>, <code>{escape(self.preview(auto_text))}</code>"
			)
			keyboard.add(B(f"{marker}{status_id}. {label}", callback_data=f"{CBT_STATUS_SET}{status_id}:{offset}"))
			keyboard.add(B(f"Текст !status: {label}", callback_data=f"{CBT_STATUS_EDIT_RESPONSE}{status_id}:{offset}"))
			keyboard.add(B(f"{'🟢' if auto_config['enabled'] else '🔴'} Авто: {label}", callback_data=f"{CBT_STATUS_TOGGLE_AUTO}{status_id}:{offset}"))
			keyboard.add(B(f"Текст авто: {label}", callback_data=f"{CBT_STATUS_EDIT_AUTO}{status_id}:{offset}"))

		keyboard.add(B("◀️ Назад", callback_data=f"{CBT.PLUGIN_SETTINGS}:{UUID}:{offset}"))
		self.send_or_edit("\n".join(lines), chat_id, message_id, keyboard, edit)

	def set_status(self, call: telebot.types.CallbackQuery) -> None:
		status_id, offset = self.parse_status_callback(call.data, CBT_STATUS_SET)
		if status_id is None:
			self.host.tgbot.answer_callback_query(call.id)
			return

		self.host.settings["status"] = status_id
		self.host.save_settings()
		self.show_status_page(call.message.chat.id, call.message.id, offset=offset, edit=True)
		self.host.tgbot.answer_callback_query(call.id, f"Статус: {status_label(status_id)}")

	def edit_response_text(self, call: telebot.types.CallbackQuery) -> None:
		status_id, offset = self.parse_status_callback(call.data, CBT_STATUS_EDIT_RESPONSE)
		if status_id is None:
			self.host.tgbot.answer_callback_query(call.id)
			return

		result = self.host.tgbot.send_message(
			call.message.chat.id,
			f"Введите текст ответа !status для статуса «{status_label(status_id)}». Отправьте - чтобы очистить.",
			reply_markup=tg_bot.static_keyboards.CLEAR_STATE_BTN(),
		)
		self.host.tg.set_state(
			call.message.chat.id,
			result.id,
			call.from_user.id,
			STATE_STATUS_RESPONSE,
			{"status_id": status_id, "offset": offset},
		)
		self.host.tgbot.answer_callback_query(call.id)

	def edit_auto_text(self, call: telebot.types.CallbackQuery) -> None:
		status_id, offset = self.parse_status_callback(call.data, CBT_STATUS_EDIT_AUTO)
		if status_id is None:
			self.host.tgbot.answer_callback_query(call.id)
			return

		result = self.host.tgbot.send_message(
			call.message.chat.id,
			f"Введите автоответ для статуса «{status_label(status_id)}». Отправьте - чтобы очистить.",
			reply_markup=tg_bot.static_keyboards.CLEAR_STATE_BTN(),
		)
		self.host.tg.set_state(
			call.message.chat.id,
			result.id,
			call.from_user.id,
			STATE_STATUS_AUTO,
			{"status_id": status_id, "offset": offset},
		)
		self.host.tgbot.answer_callback_query(call.id)

	def save_response_text(self, message: telebot.types.Message) -> None:
		state = self.host.tg.get_state(message.chat.id, message.from_user.id) or {}
		data = state.get("data", {})
		status_id = data.get("status_id")
		offset = data.get("offset", "0")
		if status_id not in STATUS_IDS:
			self.host.tg.clear_state(message.chat.id, message.from_user.id, True)
			self.host.tgbot.reply_to(message, "Не удалось определить статус.")
			return

		self.host.tg.clear_state(message.chat.id, message.from_user.id, True)
		self.host.settings["status_response_texts"][status_id] = self.clean_text(message.text)
		self.host.save_settings()
		keyboard = K().row(
			B("◀️ Назад", callback_data=f"{CBT_STATUS_PAGE}{offset}"),
			B("✏️ Изменить", callback_data=f"{CBT_STATUS_EDIT_RESPONSE}{status_id}:{offset}"),
		)
		self.host.tgbot.reply_to(message, "Текст ответа !status сохранён.", reply_markup=keyboard)

	def save_auto_text(self, message: telebot.types.Message) -> None:
		state = self.host.tg.get_state(message.chat.id, message.from_user.id) or {}
		data = state.get("data", {})
		status_id = data.get("status_id")
		offset = data.get("offset", "0")
		if status_id not in STATUS_IDS:
			self.host.tg.clear_state(message.chat.id, message.from_user.id, True)
			self.host.tgbot.reply_to(message, "Не удалось определить статус.")
			return

		self.host.tg.clear_state(message.chat.id, message.from_user.id, True)
		self.host.settings["status_auto_messages"][status_id]["text"] = self.clean_text(message.text)
		self.host.save_settings()
		keyboard = K().row(
			B("◀️ Назад", callback_data=f"{CBT_STATUS_PAGE}{offset}"),
			B("✏️ Изменить", callback_data=f"{CBT_STATUS_EDIT_AUTO}{status_id}:{offset}"),
		)
		self.host.tgbot.reply_to(message, "Текст автоответа сохранён.", reply_markup=keyboard)

	def toggle_auto_message(self, call: telebot.types.CallbackQuery) -> None:
		status_id, offset = self.parse_status_callback(call.data, CBT_STATUS_TOGGLE_AUTO)
		if status_id is None:
			self.host.tgbot.answer_callback_query(call.id)
			return

		config = self.host.settings["status_auto_messages"][status_id]
		config["enabled"] = not config["enabled"]
		self.host.save_settings()
		self.show_status_page(call.message.chat.id, call.message.id, offset=offset, edit=True)
		self.host.tgbot.answer_callback_query(call.id)

	def open_blacklist_page_callback(self, call: telebot.types.CallbackQuery) -> None:
		offset = self.get_offset(call.data)
		self.show_blacklist_page(call.message.chat.id, call.message.id, offset=offset, edit=True)
		self.host.tgbot.answer_callback_query(call.id)

	def show_blacklist_page(self, chat_id: int, message_id: int | None = None, offset: str = "0", edit: bool = False) -> None:
		blacklist: list = self.host.cardinal.blacklist or []
		total = len(blacklist)
		if total == 0:
			text = "🚫 Чёрный список пуст."
		else:
			lines = [f"🚫 Чёрный список ({total} чел.):\n"]
			for username in blacklist[:30]:
				lines.append(f"• {username}")
			if total > 30:
				lines.append(f"...и ещё {total - 30}")
			text = "\n".join(lines)

		keyboard = K(row_width=1)
		for username in blacklist[:10]:
			keyboard.add(B(f"❌ Убрать {username}", callback_data=f"{CBT_BL_UNBL}{username}"))
		keyboard.add(B("◀️ Назад", callback_data=f"{CBT.PLUGIN_SETTINGS}:{UUID}:{offset}"))
		self.send_or_edit(text, chat_id, message_id, keyboard, edit)

	def unblock_user(self, call: telebot.types.CallbackQuery) -> None:
		username = call.data.replace(CBT_BL_UNBL, "", 1).strip()
		if remove_user_from_blacklist(self.host.cardinal, username):
			self.host.tgbot.answer_callback_query(call.id, f"✅ {username} убран из ЧС.")
		else:
			self.host.tgbot.answer_callback_query(call.id, f"{username} не найден в ЧС.", show_alert=True)
		self.show_blacklist_page(call.message.chat.id, call.message.id, edit=True)

	def send_or_edit(self, text: str, chat_id: int, message_id: int | None, keyboard: K, edit: bool) -> None:
		if edit and message_id:
			try:
				self.host.tgbot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard)
				return
			except Exception:
				pass
		self.host.tgbot.send_message(chat_id, text, reply_markup=keyboard)

	def parse_status_callback(self, data: str, prefix: str) -> tuple[str | None, str]:
		payload = data.replace(prefix, "", 1)
		parts = payload.split(":", 1)
		status_id = parts[0]
		offset = parts[1] if len(parts) > 1 and parts[1].isdigit() else "0"
		if status_id not in STATUS_IDS:
			return None, offset
		return status_id, offset

	def get_offset(self, data: str) -> str:
		parts = data.split(":")
		return parts[-1] if parts and parts[-1].isdigit() else "0"

	def clean_text(self, text: str | None) -> str:
		text = text or ""
		return "" if text.strip() == "-" else text

	def preview(self, text: str) -> str:
		if len(text) > 160:
			return f"{text[:160]}\n..."
		return text
