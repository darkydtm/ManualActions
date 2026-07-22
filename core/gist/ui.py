from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

import telebot
import tg_bot.static_keyboards
from telebot.types import InlineKeyboardButton as B, InlineKeyboardMarkup as K
from tg_bot import CBT
from tg_bot.utils import escape

from ..config.constants import (
	CBT_GIST_EDIT_CUSTOM_FILENAME,
	CBT_GIST_EDIT_TOKEN,
	CBT_GIST_FILENAME_PAGE,
	CBT_GIST_PAGE,
	CBT_GIST_SET_FILENAME_MODE,
	CBT_GIST_SET_VISIBILITY,
	CBT_GIST_TOKEN_PAGE,
	CBT_GIST_VISIBILITY_PAGE,
	STATE_GIST_CUSTOM_FILENAME,
	STATE_GIST_TOKEN,
	UUID,
)
from ..runtime.settings import update_host_settings
from .settings import (
	GIST_FILENAME_MODES,
	GIST_VISIBILITY_OPTIONS,
	gist_filename_mode_label,
	gist_visibility_label,
)

if TYPE_CHECKING:
	from cardinal import Cardinal


class GistSettingsHost(Protocol):
	tg: object
	tgbot: telebot.TeleBot
	cardinal: Cardinal
	settings: dict[str, Any]

	def save_settings(self) -> None:
		...


class TelegramGistSettingsUI:
	def __init__(self, host: GistSettingsHost):
		self.host = host

	def register(self) -> None:
		self.host.tg.msg_handler(
			self.save_token,
			func=lambda m: self.host.tg.check_state(m.chat.id, m.from_user.id, STATE_GIST_TOKEN),
		)
		self.host.tg.msg_handler(
			self.save_custom_filename,
			func=lambda m: self.host.tg.check_state(m.chat.id, m.from_user.id, STATE_GIST_CUSTOM_FILENAME),
		)
		self.host.tg.cbq_handler(
			self.open_page_callback,
			lambda c: (c.data or "").startswith(CBT_GIST_PAGE),
		)
		self.host.tg.cbq_handler(
			self.open_token_page_callback,
			lambda c: (c.data or "").startswith(CBT_GIST_TOKEN_PAGE),
		)
		self.host.tg.cbq_handler(
			self.open_filename_page_callback,
			lambda c: (c.data or "").startswith(CBT_GIST_FILENAME_PAGE),
		)
		self.host.tg.cbq_handler(
			self.open_visibility_page_callback,
			lambda c: (c.data or "").startswith(CBT_GIST_VISIBILITY_PAGE),
		)
		self.host.tg.cbq_handler(
			self.set_filename_mode,
			lambda c: (c.data or "").startswith(CBT_GIST_SET_FILENAME_MODE),
		)
		self.host.tg.cbq_handler(
			self.set_visibility,
			lambda c: (c.data or "").startswith(CBT_GIST_SET_VISIBILITY),
		)
		self.host.tg.cbq_handler(
			self.edit_token,
			lambda c: (c.data or "").startswith(CBT_GIST_EDIT_TOKEN),
		)
		self.host.tg.cbq_handler(
			self.edit_custom_filename,
			lambda c: (c.data or "").startswith(CBT_GIST_EDIT_CUSTOM_FILENAME),
		)

	def open_page_callback(self, call: telebot.types.CallbackQuery) -> None:
		offset = self.get_offset(call.data)
		self.show_page(call.message.chat.id, call.message.id, offset=offset, edit=True)
		self.host.tgbot.answer_callback_query(call.id)

	def show_page(self, chat_id: int, message_id: int | None = None, offset: str = "0", edit: bool = False) -> None:
		config = self.host.settings["gist"]
		filename = config["filename"]
		token_state = "задан" if config["token"] else "не задан"
		text = (
			"<b>GitHub Gists</b>\n\n"
			f"Token: <b>{token_state}</b>\n"
			f"Видимость: <b>{gist_visibility_label(config['visibility'])}</b>\n"
			f"Имя файла: <b>{gist_filename_mode_label(filename['mode'])}</b>"
		)

		keyboard = K(row_width=1)
		keyboard.add(B("🔑 GitHub token", callback_data=f"{CBT_GIST_TOKEN_PAGE}{offset}"))
		keyboard.add(B("👁 Видимость", callback_data=f"{CBT_GIST_VISIBILITY_PAGE}{offset}"))
		keyboard.add(B("📄 Имя файла", callback_data=f"{CBT_GIST_FILENAME_PAGE}{offset}"))
		keyboard.add(B("◀️ Назад", callback_data=f"{CBT.PLUGIN_SETTINGS}:{UUID}:{offset}"))
		self.send_or_edit(text, chat_id, message_id, keyboard, edit)

	def open_token_page_callback(self, call: telebot.types.CallbackQuery) -> None:
		offset = self.get_offset(call.data)
		self.show_token_page(call.message.chat.id, call.message.id, offset=offset, edit=True)
		self.host.tgbot.answer_callback_query(call.id)

	def show_token_page(
		self,
		chat_id: int,
		message_id: int | None = None,
		offset: str = "0",
		edit: bool = False,
	) -> None:
		token_state = "задан" if self.host.settings["gist"]["token"] else "не задан"
		text = (
			"<b>GitHub Gists - token</b>\n\n"
			f"Token: <b>{token_state}</b>"
		)
		keyboard = K(row_width=1)
		keyboard.add(B("✏️ Изменить token", callback_data=f"{CBT_GIST_EDIT_TOKEN}{offset}"))
		keyboard.add(B("◀️ К GitHub Gists", callback_data=f"{CBT_GIST_PAGE}{offset}"))
		self.send_or_edit(text, chat_id, message_id, keyboard, edit)

	def open_filename_page_callback(self, call: telebot.types.CallbackQuery) -> None:
		offset = self.get_offset(call.data)
		self.show_filename_page(call.message.chat.id, call.message.id, offset=offset, edit=True)
		self.host.tgbot.answer_callback_query(call.id)

	def show_filename_page(
		self,
		chat_id: int,
		message_id: int | None = None,
		offset: str = "0",
		edit: bool = False,
	) -> None:
		filename = self.host.settings["gist"]["filename"]
		custom = filename["custom"] or "не задано"
		text = (
			"<b>GitHub Gists - имя файла</b>\n\n"
			f"Режим: <b>{gist_filename_mode_label(filename['mode'])}</b>\n"
			f"Своё имя: <code>{escape(custom)}</code>"
		)

		keyboard = K(row_width=1)
		keyboard.row(
			B(
				self.filename_mode_button("off", filename["mode"]),
				callback_data=f"{CBT_GIST_SET_FILENAME_MODE}off:{offset}",
			),
			B(
				self.filename_mode_button("custom", filename["mode"]),
				callback_data=f"{CBT_GIST_SET_FILENAME_MODE}custom:{offset}",
			),
		)
		keyboard.row(
			B(
				self.filename_mode_button("chat_sync", filename["mode"]),
				callback_data=f"{CBT_GIST_SET_FILENAME_MODE}chat_sync:{offset}",
			),
			B(
				self.filename_mode_button("order_id", filename["mode"]),
				callback_data=f"{CBT_GIST_SET_FILENAME_MODE}order_id:{offset}",
			),
		)
		keyboard.add(B("✏️ Своё имя файла", callback_data=f"{CBT_GIST_EDIT_CUSTOM_FILENAME}{offset}"))
		keyboard.add(B("◀️ К GitHub Gists", callback_data=f"{CBT_GIST_PAGE}{offset}"))
		self.send_or_edit(text, chat_id, message_id, keyboard, edit)

	def open_visibility_page_callback(self, call: telebot.types.CallbackQuery) -> None:
		offset = self.get_offset(call.data)
		self.show_visibility_page(call.message.chat.id, call.message.id, offset=offset, edit=True)
		self.host.tgbot.answer_callback_query(call.id)

	def show_visibility_page(
		self,
		chat_id: int,
		message_id: int | None = None,
		offset: str = "0",
		edit: bool = False,
	) -> None:
		current = self.host.settings["gist"]["visibility"]
		keyboard = K(row_width=1)
		for value, label in GIST_VISIBILITY_OPTIONS.items():
			marker = "✅ " if current == value else ""
			keyboard.add(B(f"{marker}{label}", callback_data=f"{CBT_GIST_SET_VISIBILITY}{value}:{offset}"))
		keyboard.add(B("◀️ К GitHub Gists", callback_data=f"{CBT_GIST_PAGE}{offset}"))
		self.send_or_edit("<b>GitHub Gists - видимость</b>", chat_id, message_id, keyboard, edit)

	def set_filename_mode(self, call: telebot.types.CallbackQuery) -> None:
		mode, offset = self.parse_two_part_callback(call.data, CBT_GIST_SET_FILENAME_MODE)
		if mode not in GIST_FILENAME_MODES:
			self.host.tgbot.answer_callback_query(call.id)
			return

		update_host_settings(self.host, lambda settings: settings["gist"]["filename"].__setitem__("mode", mode))
		self.show_filename_page(call.message.chat.id, call.message.id, offset=offset, edit=True)
		self.host.tgbot.answer_callback_query(call.id, gist_filename_mode_label(mode))

	def set_visibility(self, call: telebot.types.CallbackQuery) -> None:
		value, offset = self.parse_two_part_callback(call.data, CBT_GIST_SET_VISIBILITY)
		if value not in GIST_VISIBILITY_OPTIONS:
			self.host.tgbot.answer_callback_query(call.id)
			return

		update_host_settings(self.host, lambda settings: settings["gist"].__setitem__("visibility", value))
		self.show_visibility_page(call.message.chat.id, call.message.id, offset=offset, edit=True)
		self.host.tgbot.answer_callback_query(call.id, gist_visibility_label(value))

	def edit_token(self, call: telebot.types.CallbackQuery) -> None:
		self.ask_text(
			call,
			STATE_GIST_TOKEN,
			"Введите GitHub token. Отправьте - чтобы очистить.",
			CBT_GIST_TOKEN_PAGE,
		)

	def edit_custom_filename(self, call: telebot.types.CallbackQuery) -> None:
		self.ask_text(
			call,
			STATE_GIST_CUSTOM_FILENAME,
			"Введите имя файла gist. Отправьте - чтобы очистить.",
			CBT_GIST_FILENAME_PAGE,
		)

	def save_token(self, message: telebot.types.Message) -> None:
		self.save_text_value(message, ("token",), "GitHub token сохранён.")

	def save_custom_filename(self, message: telebot.types.Message) -> None:
		self.save_text_value(message, ("filename", "custom"), "Имя файла gist сохранено.")

	def ask_text(self, call: telebot.types.CallbackQuery, state: str, prompt: str, back_page: str) -> None:
		offset = self.get_offset(call.data)
		result = self.host.tgbot.send_message(
			call.message.chat.id,
			prompt,
			reply_markup=tg_bot.static_keyboards.CLEAR_STATE_BTN(),
		)
		self.host.tg.set_state(
			call.message.chat.id,
			result.id,
			call.from_user.id,
			state,
			{"offset": offset, "back_page": back_page},
		)
		self.host.tgbot.answer_callback_query(call.id)

	def save_text_value(self, message: telebot.types.Message, path: tuple[str, ...], success: str) -> None:
		state = self.host.tg.get_state(message.chat.id, message.from_user.id) or {}
		data = state.get("data", {})
		offset = data.get("offset", "0")
		back_page = data.get("back_page", CBT_GIST_PAGE)
		self.host.tg.clear_state(message.chat.id, message.from_user.id, True)

		value = self.clean_text(message.text).strip()
		def mutate(settings):
			target = settings["gist"]
			for key in path[:-1]:
				target = target[key]
			target[path[-1]] = value
		update_host_settings(self.host, mutate)

		keyboard = K(row_width=1)
		keyboard.add(B("◀️ Назад", callback_data=f"{back_page}{offset}"))
		self.host.tgbot.reply_to(message, success, reply_markup=keyboard)

	def send_or_edit(self, text: str, chat_id: int, message_id: int | None, keyboard: K, edit: bool) -> None:
		if edit and message_id:
			try:
				self.host.tgbot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard)
				return
			except Exception:
				pass
		self.host.tgbot.send_message(chat_id, text, reply_markup=keyboard)

	def parse_two_part_callback(self, data: str, prefix: str) -> tuple[str, str]:
		payload = data.replace(prefix, "", 1)
		parts = payload.split(":", 1)
		value = parts[0]
		offset = parts[1] if len(parts) > 1 and parts[1].isdigit() else "0"
		return value, offset

	def get_offset(self, data: str) -> str:
		parts = data.split(":")
		return parts[-1] if parts and parts[-1].isdigit() else "0"

	def clean_text(self, text: str | None) -> str:
		text = text or ""
		return "" if text.strip() == "-" else text

	def filename_mode_button(self, mode: str, current: str) -> str:
		marker = "✅ " if mode == current else ""
		return f"{marker}{gist_filename_mode_label(mode)}"
