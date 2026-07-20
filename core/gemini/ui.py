from __future__ import annotations

from math import ceil
from typing import Any, Protocol

import telebot
import tg_bot.static_keyboards
from telebot.types import InlineKeyboardButton as B, InlineKeyboardMarkup as K
from tg_bot import CBT
from tg_bot.utils import escape

from ..constants import (
	CBT_GEMINI_ADD,
	CBT_GEMINI_CLEAR,
	CBT_GEMINI_CLEAR_CONFIRM,
	CBT_GEMINI_DELETE,
	CBT_GEMINI_EDIT_TEMPLATE,
	CBT_GEMINI_PAGE,
	CBT_GEMINI_RETRY,
	CBT_GEMINI_SET_SHORTAGE,
	CBT_GEMINI_SHORTAGE,
	CBT_GEMINI_STOCK,
	CBT_GEMINI_TOGGLE,
	CBT_GEMINI_WAITING,
	CBT_GIST_PAGE,
	STATE_GEMINI_ADD,
	STATE_GEMINI_TEMPLATE,
	UUID,
)
from ..payloads import CallbackPayloadCache
from .service import OUTCOME_COMPLETED, OUTCOME_SEND_FAILED, OUTCOME_WAITING_STOCK
from .settings import (
	GEMINI_SHORTAGE_MODES,
	parse_gemini_link_batch,
)


PAGE_SIZE = 8

SHORTAGE_MODE_LABELS = {
	"partial": "Выдать остаток",
	"all_or_nothing": "Не выдавать",
}


class GeminiDeliveryUIHost(Protocol):
	tg: object
	tgbot: telebot.TeleBot
	settings: dict[str, Any]
	gemini_storage: Any
	gemini_service: Any

	def save_settings(self) -> None:
		...


class TelegramGeminiDeliveryUI:
	def __init__(self, host: GeminiDeliveryUIHost):
		self.host = host
		self.stock_payloads = CallbackPayloadCache()
		self.order_payloads = CallbackPayloadCache()

	def register(self) -> None:
		self.host.tg.msg_handler(
			self.save_stock,
			func=lambda m: self.host.tg.check_state(m.chat.id, m.from_user.id, STATE_GEMINI_ADD),
		)
		self.host.tg.msg_handler(
			self.save_message_template,
			func=lambda m: self.host.tg.check_state(m.chat.id, m.from_user.id, STATE_GEMINI_TEMPLATE),
		)
		callbacks = (
			(self.open_page, CBT_GEMINI_PAGE),
			(self.toggle_enabled, CBT_GEMINI_TOGGLE),
			(self.ask_stock, CBT_GEMINI_ADD),
			(self.open_stock_page, CBT_GEMINI_STOCK),
			(self.delete_stock_item, CBT_GEMINI_DELETE),
			(self.confirm_clear_page, CBT_GEMINI_CLEAR),
			(self.confirm_clear_stock, CBT_GEMINI_CLEAR_CONFIRM),
			(self.open_shortage_page, CBT_GEMINI_SHORTAGE),
			(self.set_shortage_mode, CBT_GEMINI_SET_SHORTAGE),
			(self.edit_message_template, CBT_GEMINI_EDIT_TEMPLATE),
			(self.open_waiting_page, CBT_GEMINI_WAITING),
			(self.retry_order, CBT_GEMINI_RETRY),
		)
		for handler, prefix in callbacks:
			self.host.tg.cbq_handler(
				handler,
				lambda c, value=prefix: (c.data or "").startswith(value),
			)

	def open_page(self, call: telebot.types.CallbackQuery) -> None:
		offset = self.get_offset(call.data)
		self.show_page(call.message.chat.id, call.message.id, offset=offset, edit=True)
		self.host.tgbot.answer_callback_query(call.id)

	def show_page(
		self,
		chat_id: int,
		message_id: int | None = None,
		offset: str = "0",
		edit: bool = False,
	) -> None:
		config = self.host.settings["gemini_delivery"]
		enabled = "включена" if config["enabled"] else "выключена"
		token = "задан" if self.host.settings["gist"]["token"] else "не задан"
		template = self.preview(config["message_template"])
		text = (
			"<b>Gemini автовыдача</b>\n\n"
			f"Автовыдача: <b>{enabled}</b>\n"
			f"В стоке: <b>{self.host.gemini_storage.stock_count()}</b>\n"
			f"Нехватка: <b>{SHORTAGE_MODE_LABELS[config['shortage_mode']]}</b>\n"
			f"GitHub token: <b>{token}</b>\n\n"
			f"<b>Сообщение покупателю</b>\n<code>{escape(template)}</code>"
		)
		keyboard = K(row_width=1)
		keyboard.add(B(
			"🟢 Выключить" if config["enabled"] else "🔴 Включить",
			callback_data=f"{CBT_GEMINI_TOGGLE}{offset}",
		))
		keyboard.add(B("➕ Добавить ссылки", callback_data=f"{CBT_GEMINI_ADD}{offset}"))
		keyboard.add(B("📦 Открыть сток", callback_data=f"{CBT_GEMINI_STOCK}0:{offset}"))
		if self.host.gemini_storage.stock_count():
			keyboard.add(B("🧹 Очистить сток", callback_data=f"{CBT_GEMINI_CLEAR}{offset}"))
		keyboard.add(B("⚖️ Режим нехватки", callback_data=f"{CBT_GEMINI_SHORTAGE}{offset}"))
		keyboard.add(B("✏️ Текст выдачи", callback_data=f"{CBT_GEMINI_EDIT_TEMPLATE}{offset}"))
		keyboard.add(B("⏳ Ожидающие заказы", callback_data=f"{CBT_GEMINI_WAITING}0:{offset}"))
		keyboard.add(B("🔑 GitHub Gists", callback_data=f"{CBT_GIST_PAGE}{offset}"))
		keyboard.add(B("◀️ Назад", callback_data=f"{CBT.PLUGIN_SETTINGS}:{UUID}:{offset}"))
		self.send_or_edit(text, chat_id, message_id, keyboard, edit)

	def toggle_enabled(self, call: telebot.types.CallbackQuery) -> None:
		offset = self.get_offset(call.data)
		config = self.host.settings["gemini_delivery"]
		config["enabled"] = not config["enabled"]
		self.host.save_settings()
		self.show_page(call.message.chat.id, call.message.id, offset=offset, edit=True)
		self.host.tgbot.answer_callback_query(
			call.id,
			"Автовыдача включена." if config["enabled"] else "Автовыдача выключена.",
		)

	def ask_stock(self, call: telebot.types.CallbackQuery) -> None:
		offset = self.get_offset(call.data)
		result = self.host.tgbot.send_message(
			call.message.chat.id,
			"Отправьте Gemini-ссылки, по одной на строку.",
			reply_markup=tg_bot.static_keyboards.CLEAR_STATE_BTN(),
		)
		self.host.tg.set_state(
			call.message.chat.id,
			result.id,
			call.from_user.id,
			STATE_GEMINI_ADD,
			{"offset": offset},
		)
		self.host.tgbot.answer_callback_query(call.id)

	def save_stock(self, message: telebot.types.Message) -> None:
		state = self.host.tg.get_state(message.chat.id, message.from_user.id) or {}
		offset = state.get("data", {}).get("offset", "0")
		result = parse_gemini_link_batch(
			message.text or "",
			self.host.gemini_storage.existing_active_links(),
		)
		added = self.host.gemini_storage.add_links(result.links)
		self.host.tg.clear_state(message.chat.id, message.from_user.id, True)
		lines = [f"Добавлено: {added}"]
		if result.invalid_lines:
			lines.append(f"Неверные строки: {', '.join(map(str, result.invalid_lines))}")
		if result.duplicate_count:
			lines.append(f"Дубликаты: {result.duplicate_count}")
		keyboard = K(row_width=1)
		keyboard.add(B("◀️ К автовыдаче", callback_data=f"{CBT_GEMINI_PAGE}{offset}"))
		self.host.tgbot.reply_to(message, "\n".join(lines), reply_markup=keyboard)

	def open_stock_page(self, call: telebot.types.CallbackQuery) -> None:
		page, offset = self.parse_page_callback(call.data, CBT_GEMINI_STOCK)
		self.show_stock_page(call.message.chat.id, call.message.id, page, offset, edit=True)
		self.host.tgbot.answer_callback_query(call.id)

	def show_stock_page(
		self,
		chat_id: int,
		message_id: int | None = None,
		page: int = 0,
		offset: str = "0",
		edit: bool = False,
	) -> None:
		links = self.host.gemini_storage.stock_links()
		page, pages = self.normalize_page(page, len(links))
		start = page * PAGE_SIZE
		items = links[start:start + PAGE_SIZE]
		text = f"<b>Gemini сток</b>\n\nВсего: <b>{len(links)}</b>\nСтраница: <b>{page + 1}/{pages}</b>"
		if not items:
			text += "\n\nСток пуст."
		keyboard = K(row_width=1)
		for index, link in enumerate(items, start=start + 1):
			token = self.stock_payloads.put(link)
			keyboard.add(B(
				f"🗑 {index}. {self.preview(link, 42)}",
				callback_data=f"{CBT_GEMINI_DELETE}{token}:{page}:{offset}",
			))
		self.add_pagination(
			keyboard,
			CBT_GEMINI_STOCK,
			page,
			pages,
			offset,
		)
		keyboard.add(B("➕ Добавить ссылки", callback_data=f"{CBT_GEMINI_ADD}{offset}"))
		keyboard.add(B("◀️ К автовыдаче", callback_data=f"{CBT_GEMINI_PAGE}{offset}"))
		self.send_or_edit(text, chat_id, message_id, keyboard, edit)

	def delete_stock_item(self, call: telebot.types.CallbackQuery) -> None:
		payload = call.data.replace(CBT_GEMINI_DELETE, "", 1)
		token, page, offset = self.parse_three_parts(payload)
		link = self.stock_payloads.pop(token)
		if isinstance(link, str) and self.host.gemini_storage.remove_stock_link(link):
			answer = "Ссылка удалена."
		else:
			answer = "Ссылка уже отсутствует."
		self.show_stock_page(
			call.message.chat.id,
			call.message.id,
			self.to_non_negative_int(page),
			offset,
			edit=True,
		)
		self.host.tgbot.answer_callback_query(call.id, answer)

	def confirm_clear_page(self, call: telebot.types.CallbackQuery) -> None:
		offset = self.get_offset(call.data)
		keyboard = K(row_width=2)
		keyboard.add(
			B("✅ Очистить", callback_data=f"{CBT_GEMINI_CLEAR_CONFIRM}{offset}"),
			B("❌ Отмена", callback_data=f"{CBT_GEMINI_PAGE}{offset}"),
		)
		self.send_or_edit(
			"Удалить все доступные Gemini-ссылки из стока?",
			call.message.chat.id,
			call.message.id,
			keyboard,
			True,
		)
		self.host.tgbot.answer_callback_query(call.id)

	def confirm_clear_stock(self, call: telebot.types.CallbackQuery) -> None:
		offset = self.get_offset(call.data)
		count = self.host.gemini_storage.clear_stock()
		self.show_page(call.message.chat.id, call.message.id, offset=offset, edit=True)
		self.host.tgbot.answer_callback_query(call.id, f"Удалено: {count}")

	def open_shortage_page(self, call: telebot.types.CallbackQuery) -> None:
		offset = self.get_offset(call.data)
		current = self.host.settings["gemini_delivery"]["shortage_mode"]
		keyboard = K(row_width=1)
		for mode in GEMINI_SHORTAGE_MODES:
			marker = "✅ " if current == mode else ""
			keyboard.add(B(
				f"{marker}{SHORTAGE_MODE_LABELS[mode]}",
				callback_data=f"{CBT_GEMINI_SET_SHORTAGE}{mode}:{offset}",
			))
		keyboard.add(B("◀️ К автовыдаче", callback_data=f"{CBT_GEMINI_PAGE}{offset}"))
		self.send_or_edit(
			"<b>Поведение при нехватке ссылок</b>",
			call.message.chat.id,
			call.message.id,
			keyboard,
			True,
		)
		self.host.tgbot.answer_callback_query(call.id)

	def set_shortage_mode(self, call: telebot.types.CallbackQuery) -> None:
		mode, offset = self.parse_value_callback(call.data, CBT_GEMINI_SET_SHORTAGE)
		if mode not in GEMINI_SHORTAGE_MODES:
			self.host.tgbot.answer_callback_query(call.id)
			return
		self.host.settings["gemini_delivery"]["shortage_mode"] = mode
		self.host.save_settings()
		self.show_page(call.message.chat.id, call.message.id, offset=offset, edit=True)
		self.host.tgbot.answer_callback_query(call.id, SHORTAGE_MODE_LABELS[mode])

	def edit_message_template(self, call: telebot.types.CallbackQuery) -> None:
		offset = self.get_offset(call.data)
		result = self.host.tgbot.send_message(
			call.message.chat.id,
			"Введите текст выдачи. Обязательно оставьте {link}.",
			reply_markup=tg_bot.static_keyboards.CLEAR_STATE_BTN(),
		)
		self.host.tg.set_state(
			call.message.chat.id,
			result.id,
			call.from_user.id,
			STATE_GEMINI_TEMPLATE,
			{"offset": offset},
		)
		self.host.tgbot.answer_callback_query(call.id)

	def save_message_template(self, message: telebot.types.Message) -> None:
		text = message.text or ""
		if "{link}" not in text:
			self.host.tgbot.reply_to(message, "Текст должен содержать {link}.")
			return
		state = self.host.tg.get_state(message.chat.id, message.from_user.id) or {}
		offset = state.get("data", {}).get("offset", "0")
		self.host.settings["gemini_delivery"]["message_template"] = text
		self.host.save_settings()
		self.host.tg.clear_state(message.chat.id, message.from_user.id, True)
		keyboard = K(row_width=1)
		keyboard.add(B("◀️ К автовыдаче", callback_data=f"{CBT_GEMINI_PAGE}{offset}"))
		self.host.tgbot.reply_to(message, "Текст выдачи сохранён.", reply_markup=keyboard)

	def open_waiting_page(self, call: telebot.types.CallbackQuery) -> None:
		page, offset = self.parse_page_callback(call.data, CBT_GEMINI_WAITING)
		self.show_waiting_page(call.message.chat.id, call.message.id, page, offset, edit=True)
		self.host.tgbot.answer_callback_query(call.id)

	def show_waiting_page(
		self,
		chat_id: int,
		message_id: int | None = None,
		page: int = 0,
		offset: str = "0",
		edit: bool = False,
	) -> None:
		orders = self.host.gemini_storage.waiting_orders()
		page, pages = self.normalize_page(page, len(orders))
		start = page * PAGE_SIZE
		items = orders[start:start + PAGE_SIZE]
		text = f"<b>Ожидающие заказы</b>\n\nВсего: <b>{len(orders)}</b>"
		if not items:
			text += "\n\nОжидающих заказов нет."
		keyboard = K(row_width=1)
		for order in items:
			token = self.order_payloads.put(order["order_id"])
			keyboard.add(B(
				f"🔄 #{self.preview(order['order_id'], 28)} - {order['requested_amount']} шт.",
				callback_data=f"{CBT_GEMINI_RETRY}{token}:{offset}",
			))
		self.add_pagination(keyboard, CBT_GEMINI_WAITING, page, pages, offset)
		keyboard.add(B("◀️ К автовыдаче", callback_data=f"{CBT_GEMINI_PAGE}{offset}"))
		self.send_or_edit(text, chat_id, message_id, keyboard, edit)

	def retry_order(self, call: telebot.types.CallbackQuery) -> None:
		payload = call.data.replace(CBT_GEMINI_RETRY, "", 1)
		token, _, offset = payload.partition(":")
		order_id = self.order_payloads.pop(token)
		if not isinstance(order_id, str):
			self.host.tgbot.answer_callback_query(call.id, "Действие истекло.", show_alert=True)
			return

		outcome = self.host.gemini_service.retry_order(order_id)
		answer = {
			OUTCOME_COMPLETED: "Заказ выдан.",
			OUTCOME_WAITING_STOCK: "Ссылок всё ещё недостаточно.",
			OUTCOME_SEND_FAILED: "Gist создан, отправка покупателю не удалась.",
		}.get(outcome.status, outcome.error or "Выдача не выполнена.")
		self.show_waiting_page(call.message.chat.id, call.message.id, offset=offset or "0", edit=True)
		self.host.tgbot.answer_callback_query(
			call.id,
			answer,
			show_alert=outcome.status != OUTCOME_COMPLETED,
		)

	def send_or_edit(self, text: str, chat_id: int, message_id: int | None, keyboard: K, edit: bool) -> None:
		if edit and message_id:
			try:
				self.host.tgbot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard)
				return
			except Exception:
				pass
		self.host.tgbot.send_message(chat_id, text, reply_markup=keyboard)

	@staticmethod
	def add_pagination(keyboard: K, prefix: str, page: int, pages: int, offset: str) -> None:
		buttons = []
		if page > 0:
			buttons.append(B("◀️", callback_data=f"{prefix}{page - 1}:{offset}"))
		if page + 1 < pages:
			buttons.append(B("▶️", callback_data=f"{prefix}{page + 1}:{offset}"))
		if buttons:
			keyboard.row(*buttons)

	@staticmethod
	def normalize_page(page: int, total: int) -> tuple[int, int]:
		pages = max(1, ceil(total / PAGE_SIZE))
		return min(max(page, 0), pages - 1), pages

	@staticmethod
	def parse_page_callback(data: str, prefix: str) -> tuple[int, str]:
		payload = data.replace(prefix, "", 1)
		page, _, offset = payload.partition(":")
		return TelegramGeminiDeliveryUI.to_non_negative_int(page), offset if offset.isdigit() else "0"

	@staticmethod
	def parse_value_callback(data: str, prefix: str) -> tuple[str, str]:
		payload = data.replace(prefix, "", 1)
		value, _, offset = payload.partition(":")
		return value, offset if offset.isdigit() else "0"

	@staticmethod
	def parse_three_parts(payload: str) -> tuple[str, str, str]:
		parts = payload.split(":", 2)
		token = parts[0]
		page = parts[1] if len(parts) > 1 else "0"
		offset = parts[2] if len(parts) > 2 and parts[2].isdigit() else "0"
		return token, page, offset

	@staticmethod
	def get_offset(data: str) -> str:
		parts = data.split(":")
		return parts[-1] if parts and parts[-1].isdigit() else "0"

	@staticmethod
	def to_non_negative_int(value: Any) -> int:
		try:
			return max(int(value), 0)
		except (TypeError, ValueError):
			return 0

	@staticmethod
	def preview(value: Any, limit: int = 160) -> str:
		text = str(value)
		if len(text) <= limit:
			return text
		return f"{text[:limit - 3]}..."
