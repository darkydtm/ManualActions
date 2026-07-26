from __future__ import annotations

import logging
import threading
from typing import Any

import tg_bot.static_keyboards
from telebot.types import InlineKeyboardButton as B, InlineKeyboardMarkup as K
from tg_bot import CBT

from ..config.constants import (
	CBT_CHAT_SYNC_CATEGORY,
	CBT_CHAT_SYNC_EDIT_DEPTH,
	CBT_CHAT_SYNC_EDIT_RATE,
	CBT_CHAT_SYNC_IMPORT,
	CBT_CHAT_SYNC_IMPORT_CONFIRM,
	CBT_CHAT_SYNC_IMPORT_SKIP,
	CBT_CHAT_SYNC_PAGE,
	CBT_CHAT_SYNC_SYNC,
	CBT_CHAT_SYNC_TOGGLE,
	CBT_CHAT_SYNC_UNBIND,
	CBT_CHAT_SYNC_UNBIND_CONFIRM,
	LOGGER_NAME,
	LOGGER_PREFIX,
	STATE_CHAT_SYNC_DEPTH,
	STATE_CHAT_SYNC_RATE,
	UUID,
)
from ..runtime.settings import update_host_settings
from .importer import ImportPlan, legacy_plugin_installed
from .settings import MAX_HISTORY_DEPTH, MAX_MESSAGES_PER_MINUTE, MIN_MESSAGES_PER_MINUTE
from .service import ChatSyncService


logger = logging.getLogger(LOGGER_NAME)

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
	"Если раньше работал плагин Chat Sync - удалите его файл из <code>plugins</code>: группу, настройки и темы "
	"можно перенести кнопкой импорта, а два одновременно работающих Chat Sync дублируют сообщения.\n\n"
	"Уведомления Cardinal для этой группы лучше отключить - иначе сообщения продублируются в «General»."
)

IMPORT_HINT = (
	"📥 Найдены данные плагина Chat Sync. Кнопка «Импорт из плагина Chat Sync» перенесёт группу, "
	"настройки и связки тем - создавать всё заново не нужно."
)

REMOVE_PLUGIN_WARNING = (
	"⚠️ Плагин Chat Sync (<code>745ed27e-3196-47c3-9483-e382c09fd2d8</code>) установлен. "
	"Удалите его файл из <code>plugins</code> и перезапустите Cardinal, иначе каждое сообщение "
	"придёт в тему дважды - от встроенного Chat Sync и от плагина."
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
		tg.cbq_handler(self.ask_import, lambda c: (c.data or "").startswith(CBT_CHAT_SYNC_IMPORT))
		tg.cbq_handler(self.confirm_import, lambda c: (c.data or "").startswith(CBT_CHAT_SYNC_IMPORT_CONFIRM))
		tg.cbq_handler(self.skip_import, lambda c: (c.data or "").startswith(CBT_CHAT_SYNC_IMPORT_SKIP))
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
		plan = self.service.preview_import()

		text = (
			"<b>Chat Sync</b>\n\n"
			f"Состояние: <b>{state}</b>\n"
			f"Группа: <code>{bound if bound else 'не привязана'}</code>\n"
			f"Тем создано: <b>{len(self.service.topics)}</b>\n"
			f"История в новой теме: <b>{config.get('history_depth')}</b> сообщений\n"
			f"Лимит отправки: <b>{config.get('messages_per_minute')}</b> сообщений/мин\n\n"
			f"{self.warning()}{self.hint(plan)}"
		)

		keyboard = K(row_width=1)
		for key, title in CATEGORY_TITLES.items():
			keyboard.add(B(f"⚙️ {title}", callback_data=f"{CBT_CHAT_SYNC_CATEGORY}{key}:{offset}"))
		keyboard.add(B("📜 История в новой теме", callback_data=f"{CBT_CHAT_SYNC_EDIT_DEPTH}{offset}"))
		keyboard.add(B("🐢 Лимит отправки", callback_data=f"{CBT_CHAT_SYNC_EDIT_RATE}{offset}"))
		if bound:
			keyboard.add(B("🔄 Синхронизировать чаты", callback_data=f"{CBT_CHAT_SYNC_SYNC}{offset}"))
		if plan.available:
			keyboard.add(B("📥 Импорт из плагина Chat Sync", callback_data=f"{CBT_CHAT_SYNC_IMPORT}{offset}"))
		if bound:
			keyboard.add(B("🗑 Отвязать группу", callback_data=f"{CBT_CHAT_SYNC_UNBIND}{offset}"))
		keyboard.add(B("◀️ Назад", callback_data=f"{CBT.PLUGIN_SETTINGS}:{UUID}:{offset}"))
		self.send_or_edit(text, chat_id, message_id, keyboard, edit)

	def warning(self) -> str:
		return f"{REMOVE_PLUGIN_WARNING}\n\n" if legacy_plugin_installed() else ""

	def hint(self, plan: ImportPlan) -> str:
		if not self.service.telegram_chat_id:
			return f"{SETUP_GUIDE}\n\n{IMPORT_HINT}" if plan.available else SETUP_GUIDE
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

	# Startup announcement

	def announce_legacy_plugin(self) -> None:
		threading.Thread(
			target=self.send_legacy_announcement,
			name="manual-actions-chat-sync-notice",
			daemon=True,
		).start()

	def send_legacy_announcement(self) -> None:
		installed = legacy_plugin_installed()
		plan = self.service.preview_import()
		offer = bool(plan.available and plan.changes and not self.service.config.get("import_offered"))
		if not installed and not offer:
			return

		lines = ["<b>Chat Sync</b>\n"]
		keyboard = None
		if installed:
			logger.warning(f"{LOGGER_PREFIX} The standalone Chat Sync plugin is installed, messages may be duplicated.")
			lines.append(REMOVE_PLUGIN_WARNING)
		if offer:
			lines.append(
				f"\n📥 Найдены данные плагина: группа <code>{plan.chat_id or 'не найдена'}</code>, "
				f"тем для переноса - <b>{plan.added}</b>.\n"
				"Импорт перенесёт группу, настройки и связки тем, создавать их заново не нужно."
			)
			keyboard = K(row_width=2)
			keyboard.add(
				B("📥 Импортировать", callback_data=f"{CBT_CHAT_SYNC_IMPORT_CONFIRM}0"),
				B("❌ Не сейчас", callback_data=f"{CBT_CHAT_SYNC_IMPORT_SKIP}0"),
			)
			self.mark_import_offered()

		self.host.send_telegram_admin_message("\n".join(lines), keyboard)

	def mark_import_offered(self) -> None:
		if self.service.config.get("import_offered"):
			return
		update_host_settings(self.host, lambda settings: settings["chat_sync"].__setitem__("import_offered", True))

	# Import from the standalone plugin

	def ask_import(self, call: Any) -> None:
		offset = self.get_offset(call.data)
		plan = self.service.preview_import()
		if not plan.available:
			self.host.tgbot.answer_callback_query(call.id, "Данные плагина Chat Sync не найдены.", show_alert=True)
			return

		keyboard = K(row_width=2)
		if plan.changes:
			keyboard.add(
				B("📥 Импортировать", callback_data=f"{CBT_CHAT_SYNC_IMPORT_CONFIRM}{offset}"),
				B("◀️ Отмена", callback_data=f"{CBT_CHAT_SYNC_PAGE}{offset}"),
			)
		else:
			keyboard.add(B("◀️ Назад", callback_data=f"{CBT_CHAT_SYNC_PAGE}{offset}"))
		self.host.tgbot.edit_message_text(
			self.import_preview_text(plan),
			call.message.chat.id,
			call.message.id,
			reply_markup=keyboard,
		)
		self.host.tgbot.answer_callback_query(call.id)

	def import_preview_text(self, plan: ImportPlan) -> str:
		lines = [
			"<b>Импорт из плагина Chat Sync</b>\n",
			f"Группа: <code>{plan.chat_id if plan.chat_id else 'не найдена'}</code>",
			f"Новых тем: <b>{plan.added}</b>",
		]
		if plan.skipped:
			lines.append(f"Уже связано: <b>{plan.skipped}</b>")
		if plan.settings:
			lines.append(f"Настроек: <b>{len(plan.settings)}</b>")
		if plan.replaces_group:
			lines.append(
				f"\n⚠️ Текущая группа будет заменена, "
				f"а её связки тем (<b>{plan.dropped}</b>) сброшены."
			)
		if not plan.changes:
			lines.append("\nИмпортировать нечего - всё уже перенесено.")
		else:
			lines.append("\nБоты и токены плагина не переносятся - встроенный Chat Sync работает на боте Cardinal.")
		return "\n".join(lines)

	def confirm_import(self, call: Any) -> None:
		offset = self.get_offset(call.data)
		self.host.tgbot.answer_callback_query(call.id, "Импортирую...")
		chat_id, message_id = call.message.chat.id, call.message.id
		threading.Thread(target=self.run_import, args=(chat_id, message_id, offset), daemon=True).start()

	def skip_import(self, call: Any) -> None:
		offset = self.get_offset(call.data)
		self.mark_import_offered()
		keyboard = K(row_width=1)
		keyboard.add(B("◀️ К Chat Sync", callback_data=f"{CBT_CHAT_SYNC_PAGE}{offset}"))
		self.send_or_edit(
			"Импорт отложен. Запустить его можно в настройках Chat Sync.",
			call.message.chat.id,
			call.message.id,
			keyboard,
			True,
		)
		self.host.tgbot.answer_callback_query(call.id)

	def run_import(self, chat_id: int, message_id: int, offset: str) -> None:
		try:
			plan = self.service.import_legacy()
			self.mark_import_offered()
			text = self.import_result_text(plan)
		except Exception as exc:
			logger.error(f"{LOGGER_PREFIX} Chat Sync import failed: {exc}")
			logger.debug("TRACEBACK", exc_info=True)
			text = "❌ Не удалось импортировать данные плагина Chat Sync."

		keyboard = K(row_width=1)
		keyboard.add(B("◀️ К Chat Sync", callback_data=f"{CBT_CHAT_SYNC_PAGE}{offset}"))
		self.send_or_edit(text, chat_id, message_id, keyboard, True)

	def import_result_text(self, plan: ImportPlan) -> str:
		lines = [
			"<b>✅ Импорт завершён</b>\n",
			f"Перенесено тем: <b>{plan.added}</b>",
		]
		if plan.skipped:
			lines.append(f"Пропущено (уже связаны): <b>{plan.skipped}</b>")
		if plan.settings:
			lines.append(f"Перенесено настроек: <b>{len(plan.settings)}</b>")
		if plan.chat_id:
			lines.append(f"Группа: <code>{plan.chat_id}</code>")
		lines.append(
			"\n⚠️ Удалите плагин Chat Sync из <code>plugins</code> и перезапустите Cardinal - "
			"пока он работает, каждое сообщение приходит в тему дважды.\n"
			"Бот Cardinal должен быть администратором группы с правом «Управление темами»."
		)
		return "\n".join(lines)

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
