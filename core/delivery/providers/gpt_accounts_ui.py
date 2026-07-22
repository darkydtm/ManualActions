from __future__ import annotations

from typing import Any, Protocol

import telebot
import tg_bot.static_keyboards
from telebot.types import InlineKeyboardButton as B, InlineKeyboardMarkup as K
from tg_bot.utils import escape

from ...common.payloads import CallbackPayloadCache
from ...runtime.settings import update_host_settings
from ...config.constants import (
	CBT_AUTO_DELIVERY_PAGE,
	CBT_GPT_ACCOUNTS_ADD,
	CBT_GPT_ACCOUNTS_CLEAR,
	CBT_GPT_ACCOUNTS_DELETE,
	CBT_GPT_ACCOUNTS_EDIT_DELAY,
	CBT_GPT_ACCOUNTS_EDIT_TEMPLATE,
	CBT_GPT_ACCOUNTS_PAGE,
	CBT_GPT_ACCOUNTS_RETRY,
	CBT_GPT_ACCOUNTS_SET_SHORTAGE,
	CBT_GPT_ACCOUNTS_SHORTAGE,
	CBT_GPT_ACCOUNTS_STOCK,
	CBT_GPT_ACCOUNTS_TOGGLE,
	CBT_GPT_ACCOUNTS_WAITING,
	STATE_GPT_ACCOUNTS_ADD,
	STATE_GPT_ACCOUNTS_DELAY,
	STATE_GPT_ACCOUNTS_TEMPLATE,
)
from .gpt_accounts_service import OUTCOME_COMPLETED, OUTCOME_WAITING_STOCK
from .gpt_accounts import (
	GPT_ACCOUNTS_SHORTAGE_MODES,
	is_gpt_account_message_template,
	parse_account_batch,
)


class GptAccountsUIHost(Protocol):
	tg: object
	tgbot: telebot.TeleBot
	settings: dict[str, Any]
	gpt_accounts_storage: Any
	gpt_accounts_service: Any

	def save_settings(self) -> None:
		...


class TelegramGptAccountsDeliveryUI:
	def __init__(self, host: GptAccountsUIHost):
		self.host = host
		self.payloads = CallbackPayloadCache()

	def register(self) -> None:
		self.host.tg.msg_handler(self.save_stock, func=lambda m: self.host.tg.check_state(m.chat.id, m.from_user.id, STATE_GPT_ACCOUNTS_ADD))
		self.host.tg.msg_handler(self.save_template, func=lambda m: self.host.tg.check_state(m.chat.id, m.from_user.id, STATE_GPT_ACCOUNTS_TEMPLATE))
		self.host.tg.msg_handler(self.save_delay, func=lambda m: self.host.tg.check_state(m.chat.id, m.from_user.id, STATE_GPT_ACCOUNTS_DELAY))
		for handler, prefix in (
			(self.open_page, CBT_GPT_ACCOUNTS_PAGE), (self.toggle, CBT_GPT_ACCOUNTS_TOGGLE),
			(self.ask_stock, CBT_GPT_ACCOUNTS_ADD), (self.open_stock, CBT_GPT_ACCOUNTS_STOCK),
			(self.delete_account, CBT_GPT_ACCOUNTS_DELETE), (self.clear_stock, CBT_GPT_ACCOUNTS_CLEAR),
			(self.open_shortage, CBT_GPT_ACCOUNTS_SHORTAGE), (self.set_shortage, CBT_GPT_ACCOUNTS_SET_SHORTAGE),
			(self.ask_delay, CBT_GPT_ACCOUNTS_EDIT_DELAY),
			(self.ask_template, CBT_GPT_ACCOUNTS_EDIT_TEMPLATE), (self.open_waiting, CBT_GPT_ACCOUNTS_WAITING),
			(self.retry, CBT_GPT_ACCOUNTS_RETRY),
		):
			self.host.tg.cbq_handler(handler, lambda c, value=prefix: (c.data or "").startswith(value))

	def open_page(self, call):
		self.show(call.message.chat.id, call.message.id, self.offset(call.data), True)
		self.host.tgbot.answer_callback_query(call.id)

	def show(self, chat_id, message_id=None, offset="0", edit=False):
		config = self.host.settings["gpt_accounts_delivery"]
		text = "<b>ChatGPT автовыдача</b>\n\n"
		text += f"Автовыдача: <b>{'включена' if config['enabled'] else 'выключена'}</b>\n"
		text += f"В стоке: <b>{self.host.gpt_accounts_storage.stock_count()}</b>\n"
		text += f"Нехватка: <b>{'выдать остаток' if config['shortage_mode'] == 'partial' else 'не выдавать'}</b>\n"
		text += f"Задержка: <b>{config['delay_seconds']} сек.</b>"
		keyboard = K(row_width=1)
		keyboard.add(B("🟢 Включено" if config["enabled"] else "🔴 Выключено", callback_data=f"{CBT_GPT_ACCOUNTS_TOGGLE}{offset}"))
		keyboard.add(B("➕ Добавить аккаунты", callback_data=f"{CBT_GPT_ACCOUNTS_ADD}{offset}"))
		keyboard.add(B("📦 Открыть сток", callback_data=f"{CBT_GPT_ACCOUNTS_STOCK}{offset}"))
		if self.host.gpt_accounts_storage.stock_count():
			keyboard.add(B("🧹 Очистить сток", callback_data=f"{CBT_GPT_ACCOUNTS_CLEAR}{offset}"))
		keyboard.add(B("⚖️ Режим нехватки", callback_data=f"{CBT_GPT_ACCOUNTS_SHORTAGE}{offset}"))
		keyboard.add(B("⏱ Задержка", callback_data=f"{CBT_GPT_ACCOUNTS_EDIT_DELAY}{offset}"))
		keyboard.add(B("✏️ Текст выдачи", callback_data=f"{CBT_GPT_ACCOUNTS_EDIT_TEMPLATE}{offset}"))
		keyboard.add(B("⏳ Ожидающие заказы", callback_data=f"{CBT_GPT_ACCOUNTS_WAITING}{offset}"))
		keyboard.add(B("◀️ К автовыдаче", callback_data=f"{CBT_AUTO_DELIVERY_PAGE}{offset}"))
		self.send_or_edit(text, chat_id, message_id, keyboard, edit)

	def toggle(self, call):
		config = self.host.settings["gpt_accounts_delivery"]
		update_host_settings(self.host, lambda settings: settings["gpt_accounts_delivery"].__setitem__("enabled", not config["enabled"]))
		self.show(call.message.chat.id, call.message.id, self.offset(call.data), True)
		self.host.tgbot.answer_callback_query(call.id)

	def ask_stock(self, call):
		offset = self.offset(call.data)
		message = self.host.tgbot.send_message(call.message.chat.id, "Отправьте аккаунты по одному на строку: email|pass или email|pass|2fa. Можно прикрепить файл .txt.", reply_markup=tg_bot.static_keyboards.CLEAR_STATE_BTN())
		self.host.tg.set_state(call.message.chat.id, message.id, call.from_user.id, STATE_GPT_ACCOUNTS_ADD, {"offset": offset})
		self.host.tgbot.answer_callback_query(call.id)

	def save_stock(self, message):
		text = self.stock_text(message)
		if text is None:
			return
		if not text.strip():
			self.host.tgbot.reply_to(message, "Отправьте текст с аккаунтами.")
			return
		result = parse_account_batch(text, self.host.gpt_accounts_storage.existing_active_emails())
		added = self.host.gpt_accounts_storage.add_accounts(result.accounts)
		self.host.tg.clear_state(message.chat.id, message.from_user.id, True)
		lines = [f"Добавлено: {added}"]
		if result.invalid_lines:
			lines.append(f"Неверные строки: {', '.join(map(str, result.invalid_lines))}")
		if result.duplicate_count:
			lines.append(f"Дубликаты: {result.duplicate_count}")
		self.host.tgbot.reply_to(message, "\n".join(lines))

	def stock_text(self, message):
		text = message.text or ""
		if text.strip():
			return text
		document = getattr(message, "document", None)
		if not document or not str(getattr(document, "file_name", "")).lower().endswith(".txt"):
			self.host.tgbot.reply_to(message, "Отправьте аккаунты текстом или файлом .txt.")
			return None
		try:
			file_info = self.host.tgbot.get_file(document.file_id)
			text = self.host.tgbot.download_file(file_info.file_path).decode("utf-8")
		except Exception:
			self.host.tgbot.reply_to(message, "Не удалось прочитать файл .txt.")
			return None
		if not text.strip():
			self.host.tgbot.reply_to(message, "Файл .txt пуст.")
			return None
		return text

	def open_stock(self, call):
		offset = self.offset(call.data)
		accounts = self.host.gpt_accounts_storage.stock_accounts()
		keyboard = K(row_width=1)
		for account in accounts:
			token = self.payloads.put(account.email)
			keyboard.add(B(f"🗑 {escape(account.email[:48])}", callback_data=f"{CBT_GPT_ACCOUNTS_DELETE}{token}:{offset}"))
		keyboard.add(B("◀️ К автовыдаче", callback_data=f"{CBT_GPT_ACCOUNTS_PAGE}{offset}"))
		text = f"<b>ChatGPT сток</b>\n\nВсего: <b>{len(accounts)}</b>"
		if not accounts:
			text += "\n\nСток пуст."
		self.send_or_edit(text, call.message.chat.id, call.message.id, keyboard, True)
		self.host.tgbot.answer_callback_query(call.id)

	def delete_account(self, call):
		token, _, offset = call.data.replace(CBT_GPT_ACCOUNTS_DELETE, "", 1).partition(":")
		email = self.payloads.pop(token)
		answer = "Аккаунт удалён." if isinstance(email, str) and self.host.gpt_accounts_storage.remove_stock_account(email) else "Действие истекло."
		self.open_stock(type("Call", (), {"data": f"{CBT_GPT_ACCOUNTS_STOCK}{offset}", "message": call.message, "id": call.id})())
		self.host.tgbot.answer_callback_query(call.id, answer)

	def clear_stock(self, call):
		count = self.host.gpt_accounts_storage.clear_stock()
		self.show(call.message.chat.id, call.message.id, self.offset(call.data), True)
		self.host.tgbot.answer_callback_query(call.id, f"Удалено: {count}")

	def open_shortage(self, call):
		offset = self.offset(call.data)
		current = self.host.settings["gpt_accounts_delivery"]["shortage_mode"]
		keyboard = K(row_width=1)
		for mode in GPT_ACCOUNTS_SHORTAGE_MODES:
			label = "Выдать остаток" if mode == "partial" else "Не выдавать"
			keyboard.add(B(("✅ " if current == mode else "") + label, callback_data=f"{CBT_GPT_ACCOUNTS_SET_SHORTAGE}{mode}:{offset}"))
		keyboard.add(B("◀️ К автовыдаче", callback_data=f"{CBT_GPT_ACCOUNTS_PAGE}{offset}"))
		self.send_or_edit("<b>Поведение при нехватке аккаунтов</b>", call.message.chat.id, call.message.id, keyboard, True)
		self.host.tgbot.answer_callback_query(call.id)

	def set_shortage(self, call):
		mode, _, offset = call.data.replace(CBT_GPT_ACCOUNTS_SET_SHORTAGE, "", 1).partition(":")
		if mode in GPT_ACCOUNTS_SHORTAGE_MODES:
			update_host_settings(self.host, lambda settings: settings["gpt_accounts_delivery"].__setitem__("shortage_mode", mode))
		self.show(call.message.chat.id, call.message.id, offset, True)
		self.host.tgbot.answer_callback_query(call.id)

	def ask_template(self, call):
		offset = self.offset(call.data)
		message = self.host.tgbot.send_message(call.message.chat.id, "Введите текст выдачи. Используйте {accounts} или {mail}, {pass}, {2fa}.", reply_markup=tg_bot.static_keyboards.CLEAR_STATE_BTN())
		self.host.tg.set_state(call.message.chat.id, message.id, call.from_user.id, STATE_GPT_ACCOUNTS_TEMPLATE, {"offset": offset})
		self.host.tgbot.answer_callback_query(call.id)

	def save_template(self, message):
		if not is_gpt_account_message_template(message.text or ""):
			self.host.tgbot.reply_to(message, "Текст должен содержать {accounts} или {mail}, {pass}, {2fa}.")
			return
		update_host_settings(self.host, lambda settings: settings["gpt_accounts_delivery"].__setitem__("message_template", message.text))
		self.host.tg.clear_state(message.chat.id, message.from_user.id, True)
		self.host.tgbot.reply_to(message, "Текст выдачи сохранён.")

	def ask_delay(self, call):
		offset = self.offset(call.data)
		message = self.host.tgbot.send_message(
			call.message.chat.id,
			"Введите задержку в секундах. 0 - выдать сразу.",
			reply_markup=tg_bot.static_keyboards.CLEAR_STATE_BTN(),
		)
		self.host.tg.set_state(call.message.chat.id, message.id, call.from_user.id, STATE_GPT_ACCOUNTS_DELAY, {"offset": offset})
		self.host.tgbot.answer_callback_query(call.id)

	def save_delay(self, message):
		try:
			delay_seconds = int((message.text or "").strip())
		except ValueError:
			delay_seconds = -1
		if delay_seconds < 0:
			self.host.tgbot.reply_to(message, "Введите целое число секунд от 0.")
			return
		state = self.host.tg.get_state(message.chat.id, message.from_user.id) or {}
		offset = state.get("data", {}).get("offset", "0")
		update_host_settings(self.host, lambda settings: settings["gpt_accounts_delivery"].__setitem__("delay_seconds", delay_seconds))
		self.host.tg.clear_state(message.chat.id, message.from_user.id, True)
		keyboard = K(row_width=1)
		keyboard.add(B("◀️ К автовыдаче", callback_data=f"{CBT_GPT_ACCOUNTS_PAGE}{offset}"))
		self.host.tgbot.reply_to(message, "Задержка сохранена.", reply_markup=keyboard)

	def open_waiting(self, call):
		offset = self.offset(call.data)
		orders = self.host.gpt_accounts_storage.waiting_orders()
		keyboard = K(row_width=1)
		for order in orders:
			token = self.payloads.put(order["order_id"])
			keyboard.add(B(f"🔄 #{order['order_id']}", callback_data=f"{CBT_GPT_ACCOUNTS_RETRY}{token}:{offset}"))
		keyboard.add(B("◀️ К автовыдаче", callback_data=f"{CBT_GPT_ACCOUNTS_PAGE}{offset}"))
		self.send_or_edit(f"<b>Ожидающие заказы</b>\n\nВсего: <b>{len(orders)}</b>", call.message.chat.id, call.message.id, keyboard, True)
		self.host.tgbot.answer_callback_query(call.id)

	def retry(self, call):
		token, _, offset = call.data.replace(CBT_GPT_ACCOUNTS_RETRY, "", 1).partition(":")
		order_id = self.payloads.pop(token)
		outcome = self.host.gpt_accounts_service.retry_order(order_id) if isinstance(order_id, str) else None
		answer = "Заказ выдан." if outcome and outcome.status == OUTCOME_COMPLETED else "Аккаунтов всё ещё недостаточно." if outcome and outcome.status == OUTCOME_WAITING_STOCK else "Выдача не выполнена."
		self.open_waiting(type("Call", (), {"data": f"{CBT_GPT_ACCOUNTS_WAITING}{offset}", "message": call.message, "id": call.id})())
		self.host.tgbot.answer_callback_query(call.id, answer)

	def send_or_edit(self, text, chat_id, message_id, keyboard, edit):
		if edit and message_id:
			try:
				self.host.tgbot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard)
				return
			except Exception:
				pass
		self.host.tgbot.send_message(chat_id, text, reply_markup=keyboard)

	@staticmethod
	def offset(data):
		value = (data or "").split(":")[-1]
		return value if value.isdigit() else "0"
