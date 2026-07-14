from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

import telebot
import tg_bot.static_keyboards
from telebot.types import InlineKeyboardButton as B, InlineKeyboardMarkup as K
from tg_bot import CBT
from tg_bot.utils import escape

from ..constants import (
	CBT_PASTEBIN_EDIT_CUSTOM_TITLE,
	CBT_PASTEBIN_EDIT_CUSTOM_PASSWORD,
	CBT_PASTEBIN_EDIT_DEV_KEY,
	CBT_PASTEBIN_EDIT_FOLDER,
	CBT_PASTEBIN_EDIT_LOGIN_PASSWORD,
	CBT_PASTEBIN_EDIT_USERNAME,
	CBT_PASTEBIN_EDIT_USER_KEY,
	CBT_PASTEBIN_EXPIRE_PAGE,
	CBT_PASTEBIN_FETCH_USER_KEY,
	CBT_PASTEBIN_PAGE,
	CBT_PASTEBIN_SET_PASSWORD_MODE,
	CBT_PASTEBIN_SET_EXPIRE,
	CBT_PASTEBIN_SET_TITLE_MODE,
	CBT_PASTEBIN_SET_VISIBILITY,
	CBT_PASTEBIN_VISIBILITY_PAGE,
	STATE_PASTEBIN_CUSTOM_PASSWORD,
	STATE_PASTEBIN_CUSTOM_TITLE,
	STATE_PASTEBIN_DEV_KEY,
	STATE_PASTEBIN_FOLDER,
	STATE_PASTEBIN_LOGIN_PASSWORD,
	STATE_PASTEBIN_USERNAME,
	STATE_PASTEBIN_USER_KEY,
	UUID,
)
from .client import login
from .service import pastebin_error_text
from .settings import (
	PASTEBIN_EXPIRATION_OPTIONS,
	PASTEBIN_PASSWORD_MODES,
	PASTEBIN_TITLE_MODES,
	PASTEBIN_VISIBILITY_OPTIONS,
	pastebin_expiration_label,
	pastebin_password_mode_label,
	pastebin_title_mode_label,
	pastebin_visibility_label,
)

if TYPE_CHECKING:
	from cardinal import Cardinal


class PastebinSettingsHost(Protocol):
	tg: object
	tgbot: telebot.TeleBot
	cardinal: Cardinal
	settings: dict[str, Any]

	def save_settings(self) -> None:
		...


class TelegramPastebinSettingsUI:
	def __init__(self, host: PastebinSettingsHost):
		self.host = host

	def register(self) -> None:
		self.host.tg.msg_handler(
			self.save_dev_key,
			func=lambda m: self.host.tg.check_state(m.chat.id, m.from_user.id, STATE_PASTEBIN_DEV_KEY),
		)
		self.host.tg.msg_handler(
			self.save_user_key,
			func=lambda m: self.host.tg.check_state(m.chat.id, m.from_user.id, STATE_PASTEBIN_USER_KEY),
		)
		self.host.tg.msg_handler(
			self.save_username,
			func=lambda m: self.host.tg.check_state(m.chat.id, m.from_user.id, STATE_PASTEBIN_USERNAME),
		)
		self.host.tg.msg_handler(
			self.save_login_password,
			func=lambda m: self.host.tg.check_state(m.chat.id, m.from_user.id, STATE_PASTEBIN_LOGIN_PASSWORD),
		)
		self.host.tg.msg_handler(
			self.save_folder,
			func=lambda m: self.host.tg.check_state(m.chat.id, m.from_user.id, STATE_PASTEBIN_FOLDER),
		)
		self.host.tg.msg_handler(
			self.save_custom_title,
			func=lambda m: self.host.tg.check_state(m.chat.id, m.from_user.id, STATE_PASTEBIN_CUSTOM_TITLE),
		)
		self.host.tg.msg_handler(
			self.save_custom_password,
			func=lambda m: self.host.tg.check_state(m.chat.id, m.from_user.id, STATE_PASTEBIN_CUSTOM_PASSWORD),
		)
		self.host.tg.cbq_handler(
			self.open_page_callback,
			lambda c: (c.data or "").startswith(CBT_PASTEBIN_PAGE),
		)
		self.host.tg.cbq_handler(
			self.open_expire_page_callback,
			lambda c: (c.data or "").startswith(CBT_PASTEBIN_EXPIRE_PAGE),
		)
		self.host.tg.cbq_handler(
			self.open_visibility_page_callback,
			lambda c: (c.data or "").startswith(CBT_PASTEBIN_VISIBILITY_PAGE),
		)
		self.host.tg.cbq_handler(
			self.set_expire,
			lambda c: (c.data or "").startswith(CBT_PASTEBIN_SET_EXPIRE),
		)
		self.host.tg.cbq_handler(
			self.set_visibility,
			lambda c: (c.data or "").startswith(CBT_PASTEBIN_SET_VISIBILITY),
		)
		self.host.tg.cbq_handler(
			self.set_title_mode,
			lambda c: (c.data or "").startswith(CBT_PASTEBIN_SET_TITLE_MODE),
		)
		self.host.tg.cbq_handler(
			self.set_password_mode,
			lambda c: (c.data or "").startswith(CBT_PASTEBIN_SET_PASSWORD_MODE),
		)
		self.host.tg.cbq_handler(
			self.edit_dev_key,
			lambda c: (c.data or "").startswith(CBT_PASTEBIN_EDIT_DEV_KEY),
		)
		self.host.tg.cbq_handler(
			self.edit_user_key,
			lambda c: (c.data or "").startswith(CBT_PASTEBIN_EDIT_USER_KEY),
		)
		self.host.tg.cbq_handler(
			self.edit_username,
			lambda c: (c.data or "").startswith(CBT_PASTEBIN_EDIT_USERNAME),
		)
		self.host.tg.cbq_handler(
			self.edit_login_password,
			lambda c: (c.data or "").startswith(CBT_PASTEBIN_EDIT_LOGIN_PASSWORD),
		)
		self.host.tg.cbq_handler(
			self.fetch_user_key,
			lambda c: (c.data or "").startswith(CBT_PASTEBIN_FETCH_USER_KEY),
		)
		self.host.tg.cbq_handler(
			self.edit_folder,
			lambda c: (c.data or "").startswith(CBT_PASTEBIN_EDIT_FOLDER),
		)
		self.host.tg.cbq_handler(
			self.edit_custom_title,
			lambda c: (c.data or "").startswith(CBT_PASTEBIN_EDIT_CUSTOM_TITLE),
		)
		self.host.tg.cbq_handler(
			self.edit_custom_password,
			lambda c: (c.data or "").startswith(CBT_PASTEBIN_EDIT_CUSTOM_PASSWORD),
		)

	def open_page_callback(self, call: telebot.types.CallbackQuery) -> None:
		offset = self.get_offset(call.data)
		self.show_page(call.message.chat.id, call.message.id, offset=offset, edit=True)
		self.host.tgbot.answer_callback_query(call.id)

	def show_page(self, chat_id: int, message_id: int | None = None, offset: str = "0", edit: bool = False) -> None:
		config = self.host.settings["pastebin"]
		title = config["title"]
		password = config["password"]
		dev_key_state = "задан" if config["api_dev_key"] else "не задан"
		user_key_state = "задан" if config["api_user_key"] else "не задан"
		username = config["username"] or "не задан"
		login_password_state = "задан" if config["login_password"] else "не задан"
		folder = config["folder_key"] or "не задана"
		custom_title = title["custom"] or "не задан"
		custom_password_state = "задан" if password["custom"] else "не задан"
		text = (
			"<b>Pastebin</b>\n\n"
			f"API dev key: <b>{dev_key_state}</b>\n"
			f"API user key: <b>{user_key_state}</b>\n"
			f"Логин: <code>{escape(username)}</code>\n"
			f"Пароль аккаунта: <b>{login_password_state}</b>\n"
			f"Видимость: <b>{pastebin_visibility_label(config['visibility'])}</b>\n"
			f"Срок: <b>{pastebin_expiration_label(config['expire_date'])}</b>\n"
			f"Папка: <code>{escape(folder)}</code>\n"
			f"Title: <b>{pastebin_title_mode_label(title['mode'])}</b>\n"
			f"Свой title: <code>{escape(custom_title)}</code>\n"
			f"Пароль paste: <b>{pastebin_password_mode_label(password['mode'])}</b>\n"
			f"Свой пароль paste: <b>{custom_password_state}</b>"
		)

		keyboard = K(row_width=1)
		keyboard.add(B("🔑 API dev key", callback_data=f"{CBT_PASTEBIN_EDIT_DEV_KEY}{offset}"))
		keyboard.add(B("👤 API user key", callback_data=f"{CBT_PASTEBIN_EDIT_USER_KEY}{offset}"))
		keyboard.add(B("👤 Логин Pastebin", callback_data=f"{CBT_PASTEBIN_EDIT_USERNAME}{offset}"))
		keyboard.add(B("🔒 Пароль аккаунта", callback_data=f"{CBT_PASTEBIN_EDIT_LOGIN_PASSWORD}{offset}"))
		keyboard.add(B("🔄 Получить API user key", callback_data=f"{CBT_PASTEBIN_FETCH_USER_KEY}{offset}"))
		keyboard.add(B("👁 Видимость", callback_data=f"{CBT_PASTEBIN_VISIBILITY_PAGE}{offset}"))
		keyboard.add(B("⏳ Срок истечения", callback_data=f"{CBT_PASTEBIN_EXPIRE_PAGE}{offset}"))
		keyboard.add(B("📁 Папка", callback_data=f"{CBT_PASTEBIN_EDIT_FOLDER}{offset}"))
		keyboard.row(
			B(self.title_mode_button("off", title["mode"]), callback_data=f"{CBT_PASTEBIN_SET_TITLE_MODE}off:{offset}"),
			B(self.title_mode_button("custom", title["mode"]), callback_data=f"{CBT_PASTEBIN_SET_TITLE_MODE}custom:{offset}"),
		)
		keyboard.add(B(
			self.title_mode_button("chat_sync", title["mode"]),
			callback_data=f"{CBT_PASTEBIN_SET_TITLE_MODE}chat_sync:{offset}",
		))
		keyboard.add(B("✏️ Свой title", callback_data=f"{CBT_PASTEBIN_EDIT_CUSTOM_TITLE}{offset}"))
		keyboard.row(
			B(self.password_mode_button("off", password["mode"]), callback_data=f"{CBT_PASTEBIN_SET_PASSWORD_MODE}off:{offset}"),
			B(self.password_mode_button("custom", password["mode"]), callback_data=f"{CBT_PASTEBIN_SET_PASSWORD_MODE}custom:{offset}"),
		)
		keyboard.add(B(
			self.password_mode_button("random", password["mode"]),
			callback_data=f"{CBT_PASTEBIN_SET_PASSWORD_MODE}random:{offset}",
		))
		keyboard.add(B("✏️ Свой пароль paste", callback_data=f"{CBT_PASTEBIN_EDIT_CUSTOM_PASSWORD}{offset}"))
		keyboard.add(B("◀️ Назад", callback_data=f"{CBT.PLUGIN_SETTINGS}:{UUID}:{offset}"))
		self.send_or_edit(text, chat_id, message_id, keyboard, edit)

	def open_expire_page_callback(self, call: telebot.types.CallbackQuery) -> None:
		offset = self.get_offset(call.data)
		self.show_expire_page(call.message.chat.id, call.message.id, offset=offset, edit=True)
		self.host.tgbot.answer_callback_query(call.id)

	def show_expire_page(self, chat_id: int, message_id: int | None = None, offset: str = "0", edit: bool = False) -> None:
		current = self.host.settings["pastebin"]["expire_date"]
		keyboard = K(row_width=1)
		for value, label in PASTEBIN_EXPIRATION_OPTIONS.items():
			marker = "✅ " if current == value else ""
			keyboard.add(B(f"{marker}{label}", callback_data=f"{CBT_PASTEBIN_SET_EXPIRE}{value}:{offset}"))
		keyboard.add(B("◀️ К Pastebin", callback_data=f"{CBT_PASTEBIN_PAGE}{offset}"))
		self.send_or_edit("<b>Срок истечения Pastebin</b>", chat_id, message_id, keyboard, edit)

	def open_visibility_page_callback(self, call: telebot.types.CallbackQuery) -> None:
		offset = self.get_offset(call.data)
		self.show_visibility_page(call.message.chat.id, call.message.id, offset=offset, edit=True)
		self.host.tgbot.answer_callback_query(call.id)

	def show_visibility_page(self, chat_id: int, message_id: int | None = None, offset: str = "0", edit: bool = False) -> None:
		current = self.host.settings["pastebin"]["visibility"]
		keyboard = K(row_width=1)
		for value, label in PASTEBIN_VISIBILITY_OPTIONS.items():
			marker = "✅ " if current == value else ""
			keyboard.add(B(f"{marker}{label}", callback_data=f"{CBT_PASTEBIN_SET_VISIBILITY}{value}:{offset}"))
		keyboard.add(B("◀️ К Pastebin", callback_data=f"{CBT_PASTEBIN_PAGE}{offset}"))
		self.send_or_edit("<b>Видимость Pastebin</b>", chat_id, message_id, keyboard, edit)

	def set_expire(self, call: telebot.types.CallbackQuery) -> None:
		value, offset = self.parse_two_part_callback(call.data, CBT_PASTEBIN_SET_EXPIRE)
		if value not in PASTEBIN_EXPIRATION_OPTIONS:
			self.host.tgbot.answer_callback_query(call.id)
			return

		self.host.settings["pastebin"]["expire_date"] = value
		self.host.save_settings()
		self.show_page(call.message.chat.id, call.message.id, offset=offset, edit=True)
		self.host.tgbot.answer_callback_query(call.id, pastebin_expiration_label(value))

	def set_visibility(self, call: telebot.types.CallbackQuery) -> None:
		value, offset = self.parse_two_part_callback(call.data, CBT_PASTEBIN_SET_VISIBILITY)
		if value not in PASTEBIN_VISIBILITY_OPTIONS:
			self.host.tgbot.answer_callback_query(call.id)
			return

		self.host.settings["pastebin"]["visibility"] = value
		self.host.save_settings()
		self.show_page(call.message.chat.id, call.message.id, offset=offset, edit=True)
		self.host.tgbot.answer_callback_query(call.id, pastebin_visibility_label(value))

	def set_title_mode(self, call: telebot.types.CallbackQuery) -> None:
		mode, offset = self.parse_two_part_callback(call.data, CBT_PASTEBIN_SET_TITLE_MODE)
		if mode not in PASTEBIN_TITLE_MODES:
			self.host.tgbot.answer_callback_query(call.id)
			return

		self.host.settings["pastebin"]["title"]["mode"] = mode
		self.host.save_settings()
		self.show_page(call.message.chat.id, call.message.id, offset=offset, edit=True)
		self.host.tgbot.answer_callback_query(call.id, pastebin_title_mode_label(mode))

	def set_password_mode(self, call: telebot.types.CallbackQuery) -> None:
		mode, offset = self.parse_two_part_callback(call.data, CBT_PASTEBIN_SET_PASSWORD_MODE)
		if mode not in PASTEBIN_PASSWORD_MODES:
			self.host.tgbot.answer_callback_query(call.id)
			return

		self.host.settings["pastebin"]["password"]["mode"] = mode
		self.host.save_settings()
		self.show_page(call.message.chat.id, call.message.id, offset=offset, edit=True)
		self.host.tgbot.answer_callback_query(call.id, pastebin_password_mode_label(mode))

	def edit_dev_key(self, call: telebot.types.CallbackQuery) -> None:
		self.ask_text(call, STATE_PASTEBIN_DEV_KEY, "Введите API dev key Pastebin. Отправьте - чтобы очистить.")

	def edit_user_key(self, call: telebot.types.CallbackQuery) -> None:
		self.ask_text(call, STATE_PASTEBIN_USER_KEY, "Введите API user key Pastebin. Отправьте - чтобы очистить.")

	def edit_username(self, call: telebot.types.CallbackQuery) -> None:
		self.ask_text(call, STATE_PASTEBIN_USERNAME, "Введите логин Pastebin. Отправьте - чтобы очистить.")

	def edit_login_password(self, call: telebot.types.CallbackQuery) -> None:
		self.ask_text(call, STATE_PASTEBIN_LOGIN_PASSWORD, "Введите пароль аккаунта Pastebin. Отправьте - чтобы очистить.")

	def fetch_user_key(self, call: telebot.types.CallbackQuery) -> None:
		offset = self.get_offset(call.data)
		config = self.host.settings["pastebin"]
		if not config["api_dev_key"] or not config["username"] or not config["login_password"]:
			self.host.tgbot.answer_callback_query(call.id, "Укажите API dev key, логин и пароль аккаунта.", show_alert=True)
			return

		try:
			config["api_user_key"] = login(config["api_dev_key"], config["username"], config["login_password"])
			self.host.save_settings()
			self.show_page(call.message.chat.id, call.message.id, offset=offset, edit=True)
			self.host.tgbot.answer_callback_query(call.id, "API user key сохранён.")
		except Exception as exc:
			error = pastebin_error_text(exc)
			self.host.tgbot.answer_callback_query(call.id, self.alert_text(error), show_alert=True)
			self.host.tgbot.send_message(
				call.message.chat.id,
				f"❌ Не удалось получить API user key Pastebin:\n<code>{escape(error)}</code>",
			)

	def edit_folder(self, call: telebot.types.CallbackQuery) -> None:
		self.ask_text(call, STATE_PASTEBIN_FOLDER, "Введите folder key Pastebin. Отправьте - чтобы очистить.")

	def edit_custom_title(self, call: telebot.types.CallbackQuery) -> None:
		self.ask_text(call, STATE_PASTEBIN_CUSTOM_TITLE, "Введите свой title Pastebin. Отправьте - чтобы очистить.")

	def edit_custom_password(self, call: telebot.types.CallbackQuery) -> None:
		self.ask_text(call, STATE_PASTEBIN_CUSTOM_PASSWORD, "Введите свой пароль paste. Отправьте - чтобы очистить.")

	def save_dev_key(self, message: telebot.types.Message) -> None:
		self.save_text_value(message, ("api_dev_key",), "API dev key Pastebin сохранён.")

	def save_user_key(self, message: telebot.types.Message) -> None:
		self.save_text_value(message, ("api_user_key",), "API user key Pastebin сохранён.")

	def save_username(self, message: telebot.types.Message) -> None:
		self.save_text_value(message, ("username",), "Логин Pastebin сохранён.")

	def save_login_password(self, message: telebot.types.Message) -> None:
		self.save_text_value(message, ("login_password",), "Пароль аккаунта Pastebin сохранён.")

	def save_folder(self, message: telebot.types.Message) -> None:
		self.save_text_value(message, ("folder_key",), "Папка Pastebin сохранена.")

	def save_custom_title(self, message: telebot.types.Message) -> None:
		self.save_text_value(message, ("title", "custom"), "Свой title Pastebin сохранён.")

	def save_custom_password(self, message: telebot.types.Message) -> None:
		self.save_text_value(message, ("password", "custom"), "Свой пароль paste сохранён.")

	def ask_text(self, call: telebot.types.CallbackQuery, state: str, prompt: str) -> None:
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
			{"offset": offset},
		)
		self.host.tgbot.answer_callback_query(call.id)

	def save_text_value(self, message: telebot.types.Message, path: tuple[str, ...], success: str) -> None:
		state = self.host.tg.get_state(message.chat.id, message.from_user.id) or {}
		offset = state.get("data", {}).get("offset", "0")
		self.host.tg.clear_state(message.chat.id, message.from_user.id, True)

		target = self.host.settings["pastebin"]
		for key in path[:-1]:
			target = target[key]
		target[path[-1]] = self.clean_setting_text(message.text, path)
		self.host.save_settings()

		keyboard = K(row_width=1)
		keyboard.add(B("◀️ К Pastebin", callback_data=f"{CBT_PASTEBIN_PAGE}{offset}"))
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

	def clean_setting_text(self, text: str | None, path: tuple[str, ...]) -> str:
		value = self.clean_text(text)
		if path in (("login_password",), ("password", "custom")):
			return value
		return value.strip()

	def title_mode_button(self, mode: str, current: str) -> str:
		marker = "✅ " if mode == current else ""
		return f"{marker}{pastebin_title_mode_label(mode)}"

	def password_mode_button(self, mode: str, current: str) -> str:
		marker = "✅ " if mode == current else ""
		return f"{marker}{pastebin_password_mode_label(mode)}"

	def alert_text(self, text: str) -> str:
		if len(text) <= 180:
			return text
		return f"{text[:177]}..."
