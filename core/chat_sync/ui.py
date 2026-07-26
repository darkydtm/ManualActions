from __future__ import annotations

import threading
from typing import Any

import tg_bot.static_keyboards
from telebot.types import InlineKeyboardButton as B, InlineKeyboardMarkup as K
from tg_bot import CBT

from ..config.constants import (
	CBT_CHAT_SYNC_CATEGORY,
	CBT_CHAT_SYNC_EDIT_DEPTH,
	CBT_CHAT_SYNC_EDIT_RATE,
	CBT_CHAT_SYNC_PAGE,
	CBT_CHAT_SYNC_SYNC,
	CBT_CHAT_SYNC_TOGGLE,
	CBT_CHAT_SYNC_UNBIND,
	CBT_CHAT_SYNC_UNBIND_CONFIRM,
	STATE_CHAT_SYNC_DEPTH,
	STATE_CHAT_SYNC_RATE,
	UUID,
)
from ..runtime.settings import update_host_settings
from .settings import MAX_HISTORY_DEPTH, MAX_MESSAGES_PER_MINUTE, MIN_MESSAGES_PER_MINUTE
from .service import ChatSyncService


TOGGLE_LABELS = {
	"enabled": "Синхронизация",
	"sync_on_start": "Синхронизировать при запуске",
	"edit_topic": "Менять название и иконку темы",
	"buyer_viewing": "Показывать «Смотрит»",
	"self_notify": "Уведомлять о своих сообщениях",
	"tag_admins_on_reply": "Упоминать админов при ответе",
	"show_ads": "Рекламные сообщения FunPay",
	"show_image_name": "Показывать имя файла",
	"hide_watermark": "Скрывать вотермарку",
	"mono": "Моноширинный шрифт",
	"chat_url": "Ссылка на чат в имени автора",
}

CATEGORY_TOGGLES = {
	"general": ("enabled", "sync_on_start", "edit_topic", "buyer_viewing"),
	"notifications": ("self_notify", "tag_admins_on_reply"),
	"format": ("show_ads", "show_image_name", "hide_watermark", "mono", "chat_url"),
}

CATEGORY_TITLES = {
	"general": "Основное",
	"notifications": "Уведомления",
	"format": "Оформление",
}

SETUP_GUIDE = (
	"<b>Как подключить</b>\n"
	"1. Создайте группу и включите в ней режим тем (Topics).\n"
	"2. Добавьте этого бота в группу и сделайте администратором с правом «Управление темами».\n"
	"3. Отправьте в группе <code>/setup_sync_chat</code>.\n"
	"4. Отправьте <code>/sync_chats</code>, чтобы создать темы для существующих чатов.\n\n"
	"Уведомления Cardinal для этой группы лучше отключить - иначе сообщения продублируются в «General»."
)


class TelegramChatSyncSettingsUI:
	def __init__(self, host: Any, service: ChatSyncService):
		self.host = host
		self.service = service

	def register(self) -> None:
		if not self.host.tg:
			return

		tg = self.host.tg
		tg.cbq_handler(self.open_page, lambda c: (c.data or "").startswith(CBT_CHAT_SYNC_PAGE))
		tg.cbq_handler(self.open_category, lambda c: (c.data or "").startswith(CBT_CHAT_SYNC_CATEGORY))
		tg.cbq_handler(self.toggle, lambda c: (c.data or "").startswith(CBT_CHAT_SYNC_TOGGLE))
		tg.cbq_handler(self.start_sync, lambda c: (c.data or "").startswith(CBT_CHAT_SYNC_SYNC))
		tg.cbq_handler(self.ask_unbind, lambda c: (c.data or "").startswith(CBT_CHAT_SYNC_UNBIND))
		tg.cbq_handler(self.confirm_unbind, lambda c: (c.data or "").startswith(CBT_CHAT_SYNC_UNBIND_CONFIRM))
		tg.cbq_handler(self.edit_depth, lambda c: (c.data or "").startswith(CBT_CHAT_SYNC_EDIT_DEPTH))
		tg.cbq_handler(self.edit_rate, lambda c: (c.data or "").startswith(CBT_CHAT_SYNC_EDIT_RATE))
		tg.msg_handler(
			self.save_depth,
			func=lambda m: self.host.tg.check_state(m.chat.id, m.from_user.id, STATE_CHAT_SYNC_DEPTH),
		)
		tg.msg_handler(
			self.save_rate,
			func=lambda m: self.host.tg.check_state(m.chat.id, m.from_user.id, STATE_CHAT_SYNC_RATE),
		)

	# Pages

	def open_page(self, call: Any) -> None:
		offset = self.get_offset(call.data)
		self.show_page(call.message.chat.id, call.message.id, offset, True)
		self.host.tgbot.answer_callback_query(call.id)

	def show_page(self, chat_id: int, message_id: int | None, offset: str, edit: bool) -> None:
		config = self.service.config
		bound = self.service.telegram_chat_id
		state = "✅ работает" if self.service.ready else "❌ не работает"

		text = (
			"<b>Chat Sync</b>\n\n"
			f"Состояние: <b>{state}</b>\n"
			f"Группа: <code>{bound if bound else 'не привязана'}</code>\n"
			f"Тем создано: <b>{len(self.service.topics)}</b>\n"
			f"История в новой теме: <b>{config.get('history_depth')}</b> сообщений\n"
			f"Лимит отправки: <b>{config.get('messages_per_minute')}</b> сообщений/мин\n\n"
			f"{self.hint()}"
		)

		keyboard = K(row_width=1)
		for key, title in CATEGORY_TITLES.items():
			keyboard.add(B(f"⚙️ {title}", callback_data=f"{CBT_CHAT_SYNC_CATEGORY}{key}:{offset}"))
		keyboard.add(B("📜 История в новой теме", callback_data=f"{CBT_CHAT_SYNC_EDIT_DEPTH}{offset}"))
		keyboard.add(B("🐢 Лимит отправки", callback_data=f"{CBT_CHAT_SYNC_EDIT_RATE}{offset}"))
		if bound:
			keyboard.add(B("🔄 Синхронизировать чаты", callback_data=f"{CBT_CHAT_SYNC_SYNC}{offset}"))
			keyboard.add(B("🗑 Отвязать группу", callback_data=f"{CBT_CHAT_SYNC_UNBIND}{offset}"))
		keyboard.add(B("◀️ Назад", callback_data=f"{CBT.PLUGIN_SETTINGS}:{UUID}:{offset}"))
		self.send_or_edit(text, chat_id, message_id, keyboard, edit)

	def hint(self) -> str:
		if not self.service.telegram_chat_id:
			return SETUP_GUIDE
		if getattr(self.service.cardinal, "old_mode_enabled", False):
			return "⚠️ Chat Sync не работает со старым режимом получения сообщений. Отключите его в /menu."
		if not self.service.config.get("enabled"):
			return "⚠️ Синхронизация выключена в разделе «Основное»."
		return "Всё готово. Пишите в темы - сообщения уйдут в FunPay."

	def open_category(self, call: Any) -> None:
		category, offset = self.parse(call.data, CBT_CHAT_SYNC_CATEGORY)
		self.show_category(call.message.chat.id, call.message.id, category, offset, True)
		self.host.tgbot.answer_callback_query(call.id)

	def show_category(self, chat_id: int, message_id: int | None, category: str, offset: str, edit: bool) -> None:
		toggles = CATEGORY_TOGGLES.get(category)
		if not toggles:
			self.show_page(chat_id, message_id, offset, edit)
			return

		config = self.service.config
		keyboard = K(row_width=1)
		for key in toggles:
			marker = "🟢" if config.get(key) else "🔴"
			keyboard.add(B(f"{marker} {TOGGLE_LABELS[key]}", callback_data=f"{CBT_CHAT_SYNC_TOGGLE}{key}|{category}:{offset}"))
		keyboard.add(B("◀️ К Chat Sync", callback_data=f"{CBT_CHAT_SYNC_PAGE}{offset}"))
		self.send_or_edit(f"<b>Chat Sync - {CATEGORY_TITLES[category]}</b>", chat_id, message_id, keyboard, edit)

	def toggle(self, call: Any) -> None:
		payload, offset = self.parse(call.data, CBT_CHAT_SYNC_TOGGLE)
		key, _, category = payload.partition("|")
		if key not in TOGGLE_LABELS or category not in CATEGORY_TOGGLES:
			self.host.tgbot.answer_callback_query(call.id)
			return

		value = not self.service.config.get(key)
		update_host_settings(self.host, lambda settings: settings["chat_sync"].__setitem__(key, value))
		self.show_category(call.message.chat.id, call.message.id, category, offset, True)
		self.host.tgbot.answer_callback_query(call.id, "Включено." if value else "Выключено.")

	# Actions

	def start_sync(self, call: Any) -> None:
		offset = self.get_offset(call.data)
		if not self.service.ready:
			self.host.tgbot.answer_callback_query(call.id, "Chat Sync не готов.", show_alert=True)
			return
		if self.service.bulk_sync_running:
			self.host.tgbot.answer_callback_query(call.id, "Синхронизация уже идёт.", show_alert=True)
			return

		threading.Thread(target=self.service.run_bulk_sync, daemon=True).start()
		self.show_page(call.message.chat.id, call.message.id, offset, True)
		self.host.tgbot.answer_callback_query(call.id, "Синхронизация запущена.")

	def ask_unbind(self, call: Any) -> None:
		offset = self.get_offset(call.data)
		keyboard = K(row_width=2)
		keyboard.add(
			B("🗑 Отвязать", callback_data=f"{CBT_CHAT_SYNC_UNBIND_CONFIRM}{offset}"),
			B("◀️ Отмена", callback_data=f"{CBT_CHAT_SYNC_PAGE}{offset}"),
		)
		self.host.tgbot.edit_message_text(
			"Отвязать группу?\n\nСвязки <code>тема - FunPay чат</code> будут сброшены.",
			call.message.chat.id,
			call.message.id,
			reply_markup=keyboard,
		)
		self.host.tgbot.answer_callback_query(call.id)

	def confirm_unbind(self, call: Any) -> None:
		offset = self.get_offset(call.data)
		update_host_settings(self.host, lambda settings: settings["chat_sync"].__setitem__("chat_id", None))
		self.service.clear_topics()
		self.show_page(call.message.chat.id, call.message.id, offset, True)
		self.host.tgbot.answer_callback_query(call.id, "Группа отвязана.")

	# Numeric settings

	def edit_depth(self, call: Any) -> None:
		self.ask_number(
			call,
			STATE_CHAT_SYNC_DEPTH,
			f"Сколько последних сообщений выгружать в новую тему? От 0 до {MAX_HISTORY_DEPTH}. 0 - не выгружать.",
		)

	def edit_rate(self, call: Any) -> None:
		self.ask_number(
			call,
			STATE_CHAT_SYNC_RATE,
			f"Сколько сообщений в минуту разрешено отправлять боту? "
			f"От {MIN_MESSAGES_PER_MINUTE} до {MAX_MESSAGES_PER_MINUTE}. Telegram обычно допускает 20.",
		)

	def ask_number(self, call: Any, state: str, prompt: str) -> None:
		offset = self.get_offset(call.data)
		result = self.host.tgbot.send_message(
			call.message.chat.id,
			prompt,
			reply_markup=tg_bot.static_keyboards.CLEAR_STATE_BTN(),
		)
		self.host.tg.set_state(call.message.chat.id, result.id, call.from_user.id, state, {"offset": offset})
		self.host.tgbot.answer_callback_query(call.id)

	def save_depth(self, message: Any) -> None:
		offset = self.state_offset(message)
		value = self.parse_int(message.text, 0, MAX_HISTORY_DEPTH)
		if value is None:
			self.host.tgbot.reply_to(message, f"Введите число от 0 до {MAX_HISTORY_DEPTH}.")
			return

		self.host.tg.clear_state(message.chat.id, message.from_user.id, True)
		update_host_settings(self.host, lambda settings: settings["chat_sync"].__setitem__("history_depth", value))
		self.host.tgbot.reply_to(
			message,
			f"Глубина истории: <b>{value}</b>.",
			reply_markup=K().add(B("◀️ К Chat Sync", callback_data=f"{CBT_CHAT_SYNC_PAGE}{offset}")),
		)

	def save_rate(self, message: Any) -> None:
		offset = self.state_offset(message)
		value = self.parse_int(message.text, MIN_MESSAGES_PER_MINUTE, MAX_MESSAGES_PER_MINUTE)
		if value is None:
			self.host.tgbot.reply_to(
				message,
				f"Введите число от {MIN_MESSAGES_PER_MINUTE} до {MAX_MESSAGES_PER_MINUTE}.",
			)
			return

		self.host.tg.clear_state(message.chat.id, message.from_user.id, True)
		update_host_settings(self.host, lambda settings: settings["chat_sync"].__setitem__("messages_per_minute", value))
		self.service.limiter.configure(value)
		self.host.tgbot.reply_to(
			message,
			f"Лимит отправки: <b>{value}</b> сообщений/мин.",
			reply_markup=K().add(B("◀️ К Chat Sync", callback_data=f"{CBT_CHAT_SYNC_PAGE}{offset}")),
		)

	# Helpers

	def state_offset(self, message: Any) -> str:
		state = self.host.tg.get_state(message.chat.id, message.from_user.id) or {}
		return state.get("data", {}).get("offset", "0")

	def parse_int(self, value: Any, minimum: int, maximum: int) -> int | None:
		try:
			number = int(str(value).strip())
		except (TypeError, ValueError):
			return None
		return number if minimum <= number <= maximum else None

	def parse(self, data: str, prefix: str) -> tuple[str, str]:
		payload = (data or "").replace(prefix, "", 1)
		parts = payload.split(":", 1)
		offset = parts[1] if len(parts) > 1 and parts[1].isdigit() else "0"
		return parts[0], offset

	def get_offset(self, data: str) -> str:
		parts = (data or "").split(":")
		return parts[-1] if parts and parts[-1].isdigit() else "0"

	def send_or_edit(self, text: str, chat_id: int, message_id: int | None, keyboard: K, edit: bool) -> None:
		if edit and message_id:
			try:
				self.host.tgbot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard)
				return
			except Exception:
				pass
		self.host.tgbot.send_message(chat_id, text, reply_markup=keyboard)
