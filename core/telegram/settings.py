from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol
from uuid import uuid4

import telebot
import tg_bot.static_keyboards
from telebot.types import InlineKeyboardButton as B, InlineKeyboardMarkup as K
from tg_bot import CBT
from tg_bot.utils import escape

from ..funpay.blacklist import unblock_user
from ..config.constants import (
	CBT_BLACKLIST_PAGE,
	CBT_BL_UNBL,
	CBT_GEMINI_PAGE,
	CBT_GIST_PAGE,
	CBT_STATUS_DETAIL,
	CBT_STATUS_EDIT_AUTO,
	CBT_STATUS_EDIT_RESPONSE,
	CBT_STATUS_PAGE,
	CBT_STATUS_SET,
	CBT_STATUS_TOGGLE_AUTO,
	CBT_TEMPLATE_ADD,
	CBT_TEMPLATE_DELETE,
	CBT_TEMPLATE_DELETE_CANCEL,
	CBT_TEMPLATE_DELETE_CONFIRM,
	CBT_TEMPLATE_DETAIL,
	CBT_TEMPLATE_EDIT_TEXT,
	CBT_TEMPLATE_EDIT_TITLE,
	CBT_TEMPLATES_PAGE,
	CBT_UPDATER_CUSTOM_INTERVAL,
	CBT_UPDATER_CHECK,
	CBT_UPDATER_INTERVAL_PAGE,
	CBT_UPDATER_INSTALL,
	CBT_UPDATER_INTERVAL,
	CBT_UPDATER_MODE_PAGE,
	CBT_UPDATER_MODE,
	CBT_UPDATER_PAGE,
	CBT_UPDATER_SKIP,
	STATE_STATUS_AUTO,
	STATE_STATUS_RESPONSE,
	STATE_TEMPLATE_CREATE_TEXT,
	STATE_TEMPLATE_CREATE_TITLE,
	STATE_TEMPLATE_EDIT_TEXT,
	STATE_TEMPLATE_EDIT_TITLE,
	STATE_UPDATER_CUSTOM_INTERVAL,
	UUID,
	VERSION,
)
from ..gemini.ui import TelegramGeminiDeliveryUI
from ..gist.ui import TelegramGistSettingsUI
from ..status.status import STATUS_IDS, status_label
from ..application.updater import MODE_ASK, MODE_DISABLED, MODE_ENABLED, ReleaseCheckResult

if TYPE_CHECKING:
	from cardinal import Cardinal


UPDATER_MODE_LABELS = {
	MODE_ENABLED: "Включить",
	MODE_DISABLED: "Выключить",
	MODE_ASK: "Спрашивать каждый раз",
}

UPDATER_INTERVAL_PRESETS = (
	(60, "Минута"),
	(1800, "Полчаса"),
	(3600, "Час"),
	(86400, "Сутки"),
	(604800, "Неделя"),
)

UPDATER_INTERVAL_LABELS = dict(UPDATER_INTERVAL_PRESETS)


class SettingsHost(Protocol):
	tg: object
	tgbot: telebot.TeleBot
	cardinal: Cardinal
	settings: dict[str, Any]

	def save_settings(self) -> None:
		...

	def refresh_updater(self) -> None:
		...

	def install_update_version(self, version: str) -> Any:
		...

	def skip_update_version(self, version: str) -> None:
		...

	def check_updates_manually(self) -> ReleaseCheckResult:
		...


class TelegramSettingsUI:
	def __init__(self, host: SettingsHost):
		self.host = host
		self.gemini_ui = TelegramGeminiDeliveryUI(host)
		self.gist_ui = TelegramGistSettingsUI(host)

	def register(self) -> None:
		if not self.host.tg:
			return

		self.gemini_ui.register()
		self.gist_ui.register()
		self.host.tg.msg_handler(
			self.save_response_text,
			func=lambda m: self.host.tg.check_state(m.chat.id, m.from_user.id, STATE_STATUS_RESPONSE),
		)
		self.host.tg.msg_handler(
			self.save_auto_text,
			func=lambda m: self.host.tg.check_state(m.chat.id, m.from_user.id, STATE_STATUS_AUTO),
		)
		self.host.tg.msg_handler(
			self.save_template_create_title,
			func=lambda m: self.host.tg.check_state(m.chat.id, m.from_user.id, STATE_TEMPLATE_CREATE_TITLE),
		)
		self.host.tg.msg_handler(
			self.save_template_create_text,
			func=lambda m: self.host.tg.check_state(m.chat.id, m.from_user.id, STATE_TEMPLATE_CREATE_TEXT),
		)
		self.host.tg.msg_handler(
			self.save_template_title,
			func=lambda m: self.host.tg.check_state(m.chat.id, m.from_user.id, STATE_TEMPLATE_EDIT_TITLE),
		)
		self.host.tg.msg_handler(
			self.save_template_text,
			func=lambda m: self.host.tg.check_state(m.chat.id, m.from_user.id, STATE_TEMPLATE_EDIT_TEXT),
		)
		self.host.tg.msg_handler(
			self.save_custom_updater_interval,
			func=lambda m: self.host.tg.check_state(m.chat.id, m.from_user.id, STATE_UPDATER_CUSTOM_INTERVAL),
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
			self.open_status_detail,
			lambda c: (c.data or "").startswith(CBT_STATUS_DETAIL),
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
			self.open_templates_page,
			lambda c: (c.data or "").startswith(CBT_TEMPLATES_PAGE),
		)
		self.host.tg.cbq_handler(
			self.open_template_detail,
			lambda c: (c.data or "").startswith(CBT_TEMPLATE_DETAIL),
		)
		self.host.tg.cbq_handler(
			self.start_template_create,
			lambda c: (c.data or "").startswith(CBT_TEMPLATE_ADD),
		)
		self.host.tg.cbq_handler(
			self.edit_template_title,
			lambda c: (c.data or "").startswith(CBT_TEMPLATE_EDIT_TITLE),
		)
		self.host.tg.cbq_handler(
			self.edit_template_text,
			lambda c: (c.data or "").startswith(CBT_TEMPLATE_EDIT_TEXT),
		)
		self.host.tg.cbq_handler(
			self.delete_template,
			lambda c: (c.data or "").startswith(CBT_TEMPLATE_DELETE),
		)
		self.host.tg.cbq_handler(
			self.confirm_template_delete,
			lambda c: (c.data or "").startswith(CBT_TEMPLATE_DELETE_CONFIRM),
		)
		self.host.tg.cbq_handler(
			self.cancel_template_delete,
			lambda c: (c.data or "").startswith(CBT_TEMPLATE_DELETE_CANCEL),
		)
		self.host.tg.cbq_handler(
			self.open_updater_page,
			lambda c: (c.data or "").startswith(CBT_UPDATER_PAGE),
		)
		self.host.tg.cbq_handler(
			self.open_updater_mode_page,
			lambda c: (c.data or "").startswith(CBT_UPDATER_MODE_PAGE),
		)
		self.host.tg.cbq_handler(
			self.open_updater_interval_page,
			lambda c: (c.data or "").startswith(CBT_UPDATER_INTERVAL_PAGE),
		)
		self.host.tg.cbq_handler(
			self.set_updater_mode,
			lambda c: (c.data or "").startswith(CBT_UPDATER_MODE),
		)
		self.host.tg.cbq_handler(
			self.set_updater_interval,
			lambda c: (c.data or "").startswith(CBT_UPDATER_INTERVAL),
		)
		self.host.tg.cbq_handler(
			self.edit_custom_updater_interval,
			lambda c: (c.data or "").startswith(CBT_UPDATER_CUSTOM_INTERVAL),
		)
		self.host.tg.cbq_handler(
			self.check_updates,
			lambda c: (c.data or "").startswith(CBT_UPDATER_CHECK),
		)
		self.host.tg.cbq_handler(
			self.install_update,
			lambda c: (c.data or "").startswith(CBT_UPDATER_INSTALL),
		)
		self.host.tg.cbq_handler(
			self.skip_update,
			lambda c: (c.data or "").startswith(CBT_UPDATER_SKIP),
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
		keyboard.add(B("📊 Статусы", callback_data=f"{CBT_STATUS_PAGE}{offset}"))
		keyboard.add(B("📝 Заготовки сообщений", callback_data=f"{CBT_TEMPLATES_PAGE}{offset}"))
		keyboard.add(B("🤖 Gemini автовыдача", callback_data=f"{CBT_GEMINI_PAGE}{offset}"))
		keyboard.add(B("🔑 GitHub Gists", callback_data=f"{CBT_GIST_PAGE}{offset}"))
		keyboard.add(B("🔄 Автообновление", callback_data=f"{CBT_UPDATER_PAGE}{offset}"))
		keyboard.add(B("🚫 Чёрный список", callback_data=f"{CBT_BLACKLIST_PAGE}{offset}"))
		keyboard.add(B("◀️ Назад", callback_data=f"{CBT.EDIT_PLUGIN}:{UUID}:{offset}"))
		text = (
			"<b>Manual Actions</b>\n\n"
			f"Текущий статус: <b>{escape(status_label(self.host.settings['status']))}</b>\n"
			f"Версия: <code>{escape(VERSION)}</code>\n"
			f"Последняя проверка обновлений: <code>{escape(self.host.settings['updater']['last_checked_version'] or 'не было')}</code>"
		)
		self.host.tgbot.edit_message_text(
			text,
			call.message.chat.id,
			call.message.id,
			reply_markup=keyboard,
		)
		self.host.tgbot.answer_callback_query(call.id)

	def open_templates_page(self, call: telebot.types.CallbackQuery) -> None:
		offset = self.get_offset(call.data)
		self.show_templates_page(call.message.chat.id, call.message.id, offset=offset, edit=True)
		self.host.tgbot.answer_callback_query(call.id)

	def show_templates_page(
		self,
		chat_id: int,
		message_id: int | None = None,
		offset: str = "0",
		edit: bool = False,
	) -> None:
		templates = self.host.settings["templates"]
		text = f"<b>Заготовки сообщений</b>\n\nВсего: <b>{len(templates)}</b>"
		if not templates:
			text += "\n\nСоздайте первую заготовку."

		keyboard = K(row_width=1)
		keyboard.add(B("➕ Добавить заготовку", callback_data=f"{CBT_TEMPLATE_ADD}{offset}"))
		for template in templates:
			keyboard.add(B(
				template["title"][:64],
				callback_data=f"{CBT_TEMPLATE_DETAIL}{template['id']}:{offset}",
			))
		keyboard.add(B("◀️ Назад", callback_data=f"{CBT.PLUGIN_SETTINGS}:{UUID}:{offset}"))
		self.send_or_edit(text, chat_id, message_id, keyboard, edit)

	def open_template_detail(self, call: telebot.types.CallbackQuery) -> None:
		template_id, offset = self.parse_two_part_callback(call.data, CBT_TEMPLATE_DETAIL)
		if not self.find_template(template_id):
			self.host.tgbot.answer_callback_query(call.id, "Заготовка не найдена.", show_alert=True)
			return
		self.show_template_detail(call.message.chat.id, call.message.id, template_id, offset=offset, edit=True)
		self.host.tgbot.answer_callback_query(call.id)

	def show_template_detail(
		self,
		chat_id: int,
		message_id: int | None,
		template_id: str,
		offset: str = "0",
		edit: bool = False,
	) -> None:
		template = self.find_template(template_id)
		if not template:
			self.show_templates_page(chat_id, message_id, offset=offset, edit=edit)
			return

		text = (
			f"<b>{escape(template['title'])}</b>\n\n"
			f"<code>{escape(self.preview(template['text'].strip() or 'не задан'))}</code>"
		)
		keyboard = K(row_width=1)
		keyboard.add(B(
			"✏️ Изменить название",
			callback_data=f"{CBT_TEMPLATE_EDIT_TITLE}{template_id}:{offset}",
		))
		keyboard.add(B(
			"✏️ Изменить текст",
			callback_data=f"{CBT_TEMPLATE_EDIT_TEXT}{template_id}:{offset}",
		))
		keyboard.add(B(
			"🗑 Удалить",
			callback_data=f"{CBT_TEMPLATE_DELETE}{template_id}:{offset}",
		))
		keyboard.add(B("◀️ К заготовкам", callback_data=f"{CBT_TEMPLATES_PAGE}{offset}"))
		self.send_or_edit(text, chat_id, message_id, keyboard, edit)

	def start_template_create(self, call: telebot.types.CallbackQuery) -> None:
		offset = self.get_offset(call.data)
		result = self.host.tgbot.send_message(
			call.message.chat.id,
			"Введите название заготовки.",
			reply_markup=tg_bot.static_keyboards.CLEAR_STATE_BTN(),
		)
		self.host.tg.set_state(
			call.message.chat.id,
			result.id,
			call.from_user.id,
			STATE_TEMPLATE_CREATE_TITLE,
			{"offset": offset},
		)
		self.host.tgbot.answer_callback_query(call.id)

	def save_template_create_title(self, message: telebot.types.Message) -> None:
		state = self.host.tg.get_state(message.chat.id, message.from_user.id) or {}
		data = state.get("data", {})
		offset = data.get("offset", "0")
		title = (message.text or "").strip()
		if not title:
			self.host.tgbot.reply_to(message, "Название не может быть пустым.")
			return

		self.host.tg.clear_state(message.chat.id, message.from_user.id, True)
		result = self.host.tgbot.send_message(
			message.chat.id,
			f"Введите текст заготовки «{escape(title)}». Отправьте - чтобы сохранить пустой текст.",
			reply_markup=tg_bot.static_keyboards.CLEAR_STATE_BTN(),
		)
		self.host.tg.set_state(
			message.chat.id,
			result.id,
			message.from_user.id,
			STATE_TEMPLATE_CREATE_TEXT,
			{"title": title, "offset": offset},
		)

	def save_template_create_text(self, message: telebot.types.Message) -> None:
		state = self.host.tg.get_state(message.chat.id, message.from_user.id) or {}
		data = state.get("data", {})
		title = str(data.get("title", "")).strip()
		offset = data.get("offset", "0")
		if not title:
			self.host.tg.clear_state(message.chat.id, message.from_user.id, True)
			self.host.tgbot.reply_to(message, "Не удалось определить название заготовки.")
			return

		template = {
			"id": uuid4().hex,
			"title": title,
			"text": self.clean_text(message.text),
		}
		self.host.settings["templates"].append(template)
		self.host.save_settings()
		self.host.tg.clear_state(message.chat.id, message.from_user.id, True)
		keyboard = K().row(
			B("◀️ К заготовке", callback_data=f"{CBT_TEMPLATE_DETAIL}{template['id']}:{offset}"),
			B("✏️ Изменить текст", callback_data=f"{CBT_TEMPLATE_EDIT_TEXT}{template['id']}:{offset}"),
		)
		self.host.tgbot.reply_to(message, "Заготовка сохранена.", reply_markup=keyboard)

	def edit_template_title(self, call: telebot.types.CallbackQuery) -> None:
		template_id, offset = self.parse_two_part_callback(call.data, CBT_TEMPLATE_EDIT_TITLE)
		template = self.find_template(template_id)
		if not template:
			self.host.tgbot.answer_callback_query(call.id, "Заготовка не найдена.", show_alert=True)
			return

		result = self.host.tgbot.send_message(
			call.message.chat.id,
			f"Введите новое название для «{escape(template['title'])}».",
			reply_markup=tg_bot.static_keyboards.CLEAR_STATE_BTN(),
		)
		self.host.tg.set_state(
			call.message.chat.id,
			result.id,
			call.from_user.id,
			STATE_TEMPLATE_EDIT_TITLE,
			{"template_id": template_id, "offset": offset},
		)
		self.host.tgbot.answer_callback_query(call.id)

	def save_template_title(self, message: telebot.types.Message) -> None:
		state = self.host.tg.get_state(message.chat.id, message.from_user.id) or {}
		data = state.get("data", {})
		template_id = data.get("template_id", "")
		offset = data.get("offset", "0")
		title = (message.text or "").strip()
		if not title:
			self.host.tgbot.reply_to(message, "Название не может быть пустым.")
			return

		template = self.find_template(template_id)
		if not template:
			self.host.tg.clear_state(message.chat.id, message.from_user.id, True)
			self.host.tgbot.reply_to(message, "Заготовка не найдена.")
			return

		template["title"] = title
		self.host.save_settings()
		self.host.tg.clear_state(message.chat.id, message.from_user.id, True)
		keyboard = K().row(
			B("◀️ К заготовке", callback_data=f"{CBT_TEMPLATE_DETAIL}{template_id}:{offset}"),
			B("✏️ Изменить", callback_data=f"{CBT_TEMPLATE_EDIT_TITLE}{template_id}:{offset}"),
		)
		self.host.tgbot.reply_to(message, "Название заготовки сохранено.", reply_markup=keyboard)

	def edit_template_text(self, call: telebot.types.CallbackQuery) -> None:
		template_id, offset = self.parse_two_part_callback(call.data, CBT_TEMPLATE_EDIT_TEXT)
		template = self.find_template(template_id)
		if not template:
			self.host.tgbot.answer_callback_query(call.id, "Заготовка не найдена.", show_alert=True)
			return

		result = self.host.tgbot.send_message(
			call.message.chat.id,
			f"Введите новый текст для «{escape(template['title'])}». Отправьте - чтобы очистить.",
			reply_markup=tg_bot.static_keyboards.CLEAR_STATE_BTN(),
		)
		self.host.tg.set_state(
			call.message.chat.id,
			result.id,
			call.from_user.id,
			STATE_TEMPLATE_EDIT_TEXT,
			{"template_id": template_id, "offset": offset},
		)
		self.host.tgbot.answer_callback_query(call.id)

	def save_template_text(self, message: telebot.types.Message) -> None:
		state = self.host.tg.get_state(message.chat.id, message.from_user.id) or {}
		data = state.get("data", {})
		template_id = data.get("template_id", "")
		offset = data.get("offset", "0")
		template = self.find_template(template_id)
		if not template:
			self.host.tg.clear_state(message.chat.id, message.from_user.id, True)
			self.host.tgbot.reply_to(message, "Заготовка не найдена.")
			return

		template["text"] = self.clean_text(message.text)
		self.host.save_settings()
		self.host.tg.clear_state(message.chat.id, message.from_user.id, True)
		keyboard = K().row(
			B("◀️ К заготовке", callback_data=f"{CBT_TEMPLATE_DETAIL}{template_id}:{offset}"),
			B("✏️ Изменить", callback_data=f"{CBT_TEMPLATE_EDIT_TEXT}{template_id}:{offset}"),
		)
		self.host.tgbot.reply_to(message, "Текст заготовки сохранён.", reply_markup=keyboard)

	def delete_template(self, call: telebot.types.CallbackQuery) -> None:
		template_id, offset = self.parse_two_part_callback(call.data, CBT_TEMPLATE_DELETE)
		template = self.find_template(template_id)
		if not template:
			self.host.tgbot.answer_callback_query(call.id, "Заготовка не найдена.", show_alert=True)
			return

		keyboard = K(row_width=2)
		keyboard.add(
			B("🗑 Удалить", callback_data=f"{CBT_TEMPLATE_DELETE_CONFIRM}{template_id}:{offset}"),
			B("❌ Отмена", callback_data=f"{CBT_TEMPLATE_DELETE_CANCEL}{template_id}:{offset}"),
		)
		self.host.tgbot.edit_message_text(
			f"Удалить заготовку «{escape(template['title'])}»?",
			call.message.chat.id,
			call.message.id,
			reply_markup=keyboard,
		)
		self.host.tgbot.answer_callback_query(call.id)

	def confirm_template_delete(self, call: telebot.types.CallbackQuery) -> None:
		template_id, offset = self.parse_two_part_callback(call.data, CBT_TEMPLATE_DELETE_CONFIRM)
		template = self.find_template(template_id)
		if not template:
			self.host.tgbot.answer_callback_query(call.id, "Заготовка не найдена.", show_alert=True)
			return

		self.host.settings["templates"].remove(template)
		self.host.save_settings()
		self.show_templates_page(call.message.chat.id, call.message.id, offset=offset, edit=True)
		self.host.tgbot.answer_callback_query(call.id, "Заготовка удалена.")

	def cancel_template_delete(self, call: telebot.types.CallbackQuery) -> None:
		template_id, offset = self.parse_two_part_callback(call.data, CBT_TEMPLATE_DELETE_CANCEL)
		if not self.find_template(template_id):
			self.host.tgbot.answer_callback_query(call.id, "Заготовка не найдена.", show_alert=True)
			return
		self.show_template_detail(call.message.chat.id, call.message.id, template_id, offset=offset, edit=True)
		self.host.tgbot.answer_callback_query(call.id, "Удаление отменено.")

	def find_template(self, template_id: str) -> dict[str, str] | None:
		return next(
			(template for template in self.host.settings["templates"] if template["id"] == template_id),
			None,
		)

	def open_status_page(self, call: telebot.types.CallbackQuery) -> None:
		offset = self.get_offset(call.data)
		self.show_status_page(call.message.chat.id, call.message.id, offset=offset, edit=True)
		self.host.tgbot.answer_callback_query(call.id)

	def show_status_page(self, chat_id: int, message_id: int | None = None, offset: str = "0", edit: bool = False) -> None:
		current = self.host.settings["status"]
		lines = [f"<b>Статусы</b>\n\nТекущий: <b>{escape(status_label(current))}</b>\n\nВыберите статус для настройки:"]
		keyboard = K(row_width=1)

		for status_id in STATUS_IDS:
			label = status_label(status_id)
			auto_config = self.host.settings["status_auto_messages"][status_id]
			auto_state = "авто вкл" if auto_config["enabled"] else "авто выкл"
			marker = "✅ " if current == status_id else ""
			keyboard.add(B(
				f"{marker}📊 {status_id}. {label} - {auto_state}",
				callback_data=f"{CBT_STATUS_DETAIL}{status_id}:{offset}",
			))

		keyboard.add(B("◀️ Назад", callback_data=f"{CBT.PLUGIN_SETTINGS}:{UUID}:{offset}"))
		self.send_or_edit("\n".join(lines), chat_id, message_id, keyboard, edit)

	def open_status_detail(self, call: telebot.types.CallbackQuery) -> None:
		status_id, offset = self.parse_status_callback(call.data, CBT_STATUS_DETAIL)
		if status_id is None:
			self.host.tgbot.answer_callback_query(call.id)
			return

		self.show_status_detail(call.message.chat.id, call.message.id, status_id, offset=offset, edit=True)
		self.host.tgbot.answer_callback_query(call.id)

	def show_status_detail(
		self,
		chat_id: int,
		message_id: int | None,
		status_id: str,
		offset: str = "0",
		edit: bool = False,
	) -> None:
		current = self.host.settings["status"]
		label = status_label(status_id)
		response = self.host.settings["status_response_texts"][status_id].strip() or "не задан"
		auto_config = self.host.settings["status_auto_messages"][status_id]
		auto_text = str(auto_config["text"]).strip() or "не задан"
		auto_state = "включён" if auto_config["enabled"] else "выключен"
		current_state = "да" if current == status_id else "нет"
		text = (
			f"<b>{status_id}. {escape(label)}</b>\n\n"
			f"Текущий: <b>{current_state}</b>\n"
			f"Автоответ: <b>{auto_state}</b>\n\n"
			f"<b>Ответ !status</b>\n<code>{escape(self.preview(response))}</code>\n\n"
			f"<b>Автоответ</b>\n<code>{escape(self.preview(auto_text))}</code>"
		)

		keyboard = K(row_width=1)
		if current != status_id:
			keyboard.add(B("✅ Сделать текущим", callback_data=f"{CBT_STATUS_SET}{status_id}:{offset}"))
		keyboard.add(B("✏️ Текст !status", callback_data=f"{CBT_STATUS_EDIT_RESPONSE}{status_id}:{offset}"))
		keyboard.add(B(
			"🟢 Выключить автоответ" if auto_config["enabled"] else "🔴 Включить автоответ",
			callback_data=f"{CBT_STATUS_TOGGLE_AUTO}{status_id}:{offset}",
		))
		keyboard.add(B("✏️ Текст автоответа", callback_data=f"{CBT_STATUS_EDIT_AUTO}{status_id}:{offset}"))
		keyboard.add(B("◀️ К статусам", callback_data=f"{CBT_STATUS_PAGE}{offset}"))
		self.send_or_edit(text, chat_id, message_id, keyboard, edit)

	def set_status(self, call: telebot.types.CallbackQuery) -> None:
		status_id, offset = self.parse_status_callback(call.data, CBT_STATUS_SET)
		if status_id is None:
			self.host.tgbot.answer_callback_query(call.id)
			return

		self.host.settings["status"] = status_id
		self.host.save_settings()
		self.show_status_detail(call.message.chat.id, call.message.id, status_id, offset=offset, edit=True)
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
			B("◀️ Назад", callback_data=f"{CBT_STATUS_DETAIL}{status_id}:{offset}"),
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
			B("◀️ Назад", callback_data=f"{CBT_STATUS_DETAIL}{status_id}:{offset}"),
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
		self.show_status_detail(call.message.chat.id, call.message.id, status_id, offset=offset, edit=True)
		self.host.tgbot.answer_callback_query(call.id)

	def open_updater_page(self, call: telebot.types.CallbackQuery) -> None:
		offset = self.get_offset(call.data)
		self.show_updater_page(call.message.chat.id, call.message.id, offset=offset, edit=True)
		self.host.tgbot.answer_callback_query(call.id)

	def open_updater_mode_page(self, call: telebot.types.CallbackQuery) -> None:
		offset = self.get_offset(call.data)
		self.show_updater_mode_page(call.message.chat.id, call.message.id, offset=offset, edit=True)
		self.host.tgbot.answer_callback_query(call.id)

	def open_updater_interval_page(self, call: telebot.types.CallbackQuery) -> None:
		offset = self.get_offset(call.data)
		self.show_updater_interval_page(call.message.chat.id, call.message.id, offset=offset, edit=True)
		self.host.tgbot.answer_callback_query(call.id)

	def show_updater_page(self, chat_id: int, message_id: int | None = None, offset: str = "0", edit: bool = False) -> None:
		config = self.host.settings["updater"]
		text = (
			"<b>Автообновление</b>\n\n"
			f"Режим: <b>{escape(self.updater_mode_label(config['mode']))}</b>\n"
			f"Установленный релиз: <code>{escape(config['installed_version'] or 'не задан')}</code>\n"
			f"Пропущенный релиз: <code>{escape(config['skipped_version'] or 'не задан')}</code>"
		)

		keyboard = K(row_width=1)
		keyboard.add(B("🔄 Проверить обновления", callback_data=f"{CBT_UPDATER_CHECK}{offset}"))
		keyboard.add(B("Режим обновления", callback_data=f"{CBT_UPDATER_MODE_PAGE}{offset}"))
		keyboard.add(B("Интервал проверки", callback_data=f"{CBT_UPDATER_INTERVAL_PAGE}{offset}"))
		keyboard.add(B("◀️ Назад", callback_data=f"{CBT.PLUGIN_SETTINGS}:{UUID}:{offset}"))
		self.send_or_edit(text, chat_id, message_id, keyboard, edit)

	def check_updates(self, call: telebot.types.CallbackQuery) -> None:
		offset = self.get_offset(call.data)
		try:
			result = self.host.check_updates_manually()
			if result.message == "not_new":
				notice = "✅ Новых обновлений нет."
			elif result.message == "available" and result.release:
				notice = f"🆕 Доступно обновление: <code>{escape(result.release.version)}</code>."
			elif result.message == "installed" and result.release:
				notice = f"✅ Обновление <code>{escape(result.release.version)}</code> установлено. Перезапустите Cardinal."
			else:
				notice = "ℹ️ Проверка обновлений завершена."
		except Exception as exc:
			notice = f"❌ Не удалось проверить обновления: <code>{escape(str(exc))}</code>"
		self.show_updater_page(call.message.chat.id, call.message.id, offset=offset, edit=True)
		self.host.tgbot.answer_callback_query(call.id, notice, show_alert=True)

	def show_updater_mode_page(self, chat_id: int, message_id: int | None = None, offset: str = "0", edit: bool = False) -> None:
		config = self.host.settings["updater"]
		text = (
			"<b>Режим обновления</b>\n\n"
			f"Текущий: <b>{escape(self.updater_mode_label(config['mode']))}</b>"
		)

		keyboard = K(row_width=1)
		for mode in (MODE_ENABLED, MODE_DISABLED, MODE_ASK):
			marker = "✅ " if config["mode"] == mode else ""
			keyboard.add(B(
				f"{marker}{self.updater_mode_label(mode)}",
				callback_data=f"{CBT_UPDATER_MODE}{mode}:{offset}",
			))
		keyboard.add(B("◀️ Назад", callback_data=f"{CBT_UPDATER_PAGE}{offset}"))
		self.send_or_edit(text, chat_id, message_id, keyboard, edit)

	def show_updater_interval_page(self, chat_id: int, message_id: int | None = None, offset: str = "0", edit: bool = False) -> None:
		config = self.host.settings["updater"]
		text = (
			"<b>Интервал проверки</b>\n\n"
			f"Текущий: <b>{escape(self.updater_interval_label(config['check_interval_seconds']))}</b>"
		)

		keyboard = K(row_width=1)
		text += (
			"\n\nВыберите интервал проверки обновлений."
		)
		for interval, label in UPDATER_INTERVAL_PRESETS:
			marker = "✅ " if config["check_interval_seconds"] == interval else ""
			keyboard.add(B(
				f"{marker}{label}",
				callback_data=f"{CBT_UPDATER_INTERVAL}{interval}:{offset}",
			))
		keyboard.add(B("✏️ Свой интервал", callback_data=f"{CBT_UPDATER_CUSTOM_INTERVAL}{offset}"))
		keyboard.add(B("◀️ Назад", callback_data=f"{CBT_UPDATER_PAGE}{offset}"))
		self.send_or_edit(text, chat_id, message_id, keyboard, edit)

	def set_updater_mode(self, call: telebot.types.CallbackQuery) -> None:
		mode, offset = self.parse_two_part_callback(call.data, CBT_UPDATER_MODE)
		if mode not in UPDATER_MODE_LABELS:
			self.host.tgbot.answer_callback_query(call.id)
			return

		self.host.settings["updater"]["mode"] = mode
		self.host.save_settings()
		self.host.refresh_updater()
		self.show_updater_page(call.message.chat.id, call.message.id, offset=offset, edit=True)
		self.host.tgbot.answer_callback_query(call.id, self.updater_mode_label(mode))

	def set_updater_interval(self, call: telebot.types.CallbackQuery) -> None:
		value, offset = self.parse_two_part_callback(call.data, CBT_UPDATER_INTERVAL)
		interval = self.parse_positive_int(value)
		if interval is None:
			self.host.tgbot.answer_callback_query(call.id)
			return

		self.save_updater_interval(interval)
		self.show_updater_page(call.message.chat.id, call.message.id, offset=offset, edit=True)
		self.host.tgbot.answer_callback_query(call.id, self.updater_interval_label(interval))

	def edit_custom_updater_interval(self, call: telebot.types.CallbackQuery) -> None:
		offset = self.get_offset(call.data)
		result = self.host.tgbot.send_message(
			call.message.chat.id,
			"Введите интервал проверки обновлений в минутах. Минимум - 1.",
			reply_markup=tg_bot.static_keyboards.CLEAR_STATE_BTN(),
		)
		self.host.tg.set_state(
			call.message.chat.id,
			result.id,
			call.from_user.id,
			STATE_UPDATER_CUSTOM_INTERVAL,
			{"offset": offset},
		)
		self.host.tgbot.answer_callback_query(call.id)

	def save_custom_updater_interval(self, message: telebot.types.Message) -> None:
		state = self.host.tg.get_state(message.chat.id, message.from_user.id) or {}
		data = state.get("data", {})
		offset = data.get("offset", "0")
		minutes = self.parse_positive_int(message.text)
		if minutes is None:
			self.host.tgbot.reply_to(message, "Введите положительное число минут.")
			return

		self.host.tg.clear_state(message.chat.id, message.from_user.id, True)
		interval = minutes * 60
		self.save_updater_interval(interval)
		keyboard = K().row(
			B("◀️ Назад", callback_data=f"{CBT_UPDATER_PAGE}{offset}"),
			B("✏️ Изменить", callback_data=f"{CBT_UPDATER_CUSTOM_INTERVAL}{offset}"),
		)
		self.host.tgbot.reply_to(
			message,
			f"Интервал проверки обновлений сохранён: {self.updater_interval_label(interval)}.",
			reply_markup=keyboard,
		)

	def save_updater_interval(self, interval: int) -> None:
		self.host.settings["updater"]["check_interval_seconds"] = interval
		self.host.save_settings()
		self.host.refresh_updater()

	def install_update(self, call: telebot.types.CallbackQuery) -> None:
		version = call.data.replace(CBT_UPDATER_INSTALL, "", 1).strip()
		if not version:
			self.host.tgbot.answer_callback_query(call.id)
			return

		self.host.tgbot.answer_callback_query(call.id, "Обновляю...")
		try:
			path = self.host.install_update_version(version)
			text = (
				"<b>Manual Actions</b>\n\n"
				f"✅ Обновление <code>{escape(version)}</code> установлено.\n"
				f"Файл: <code>{escape(str(path))}</code>\n\n"
				"Перезапустите Cardinal, чтобы загрузить новую версию."
			)
			self.host.tgbot.edit_message_text(text, call.message.chat.id, call.message.id, reply_markup=None)
		except Exception as exc:
			self.host.tgbot.edit_message_text(
				f"❌ Не удалось установить обновление:\n<code>{escape(str(exc))}</code>",
				call.message.chat.id,
				call.message.id,
				reply_markup=None,
			)

	def skip_update(self, call: telebot.types.CallbackQuery) -> None:
		version = call.data.replace(CBT_UPDATER_SKIP, "", 1).strip()
		if not version:
			self.host.tgbot.answer_callback_query(call.id)
			return

		self.host.skip_update_version(version)
		self.host.tgbot.answer_callback_query(call.id, "Обновление пропущено.")
		self.host.tgbot.edit_message_text(
			f"❌ Обновление <code>{escape(version)}</code> пропущено.",
			call.message.chat.id,
			call.message.id,
			reply_markup=None,
		)

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
			keyboard.add(B(f"✅ Разблокировать {username}", callback_data=f"{CBT_BL_UNBL}{username}"))
		keyboard.add(B("◀️ Назад", callback_data=f"{CBT.PLUGIN_SETTINGS}:{UUID}:{offset}"))
		self.send_or_edit(text, chat_id, message_id, keyboard, edit)

	def unblock_user(self, call: telebot.types.CallbackQuery) -> None:
		username = call.data.replace(CBT_BL_UNBL, "", 1).strip()
		if unblock_user(self.host.cardinal, username):
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

	def parse_positive_int(self, value: Any) -> int | None:
		try:
			number = int(str(value).strip())
		except (TypeError, ValueError):
			return None
		return number if number > 0 else None

	def preview(self, text: str) -> str:
		if len(text) > 160:
			return f"{text[:160]}\n..."
		return text

	def updater_mode_label(self, mode: str) -> str:
		return UPDATER_MODE_LABELS.get(mode, mode)

	def updater_interval_label(self, interval: Any) -> str:
		seconds = self.parse_positive_int(interval)
		if seconds is None:
			seconds = 3600
		label = UPDATER_INTERVAL_LABELS.get(seconds)
		if label:
			return label
		if seconds % 604800 == 0:
			return f"{seconds // 604800} нед."
		if seconds % 86400 == 0:
			return f"{seconds // 86400} сут."
		if seconds % 3600 == 0:
			return f"{seconds // 3600} ч."
		if seconds % 60 == 0:
			return f"{seconds // 60} мин."
		return f"{seconds} сек."
