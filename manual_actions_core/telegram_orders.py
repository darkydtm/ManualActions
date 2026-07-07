from __future__ import annotations

from html import escape
from typing import TYPE_CHECKING, Any, Callable, Protocol

import telebot
from telebot.types import InlineKeyboardButton as B, InlineKeyboardMarkup as K

from .chat_sync import get_topic_context, is_in_sync_chat
from .constants import CBT_ORDERS_DETAIL, CBT_ORDERS_FILTER, CBT_ORDERS_REFUND
from .orders import (
	ORDER_FILTER_LABELS,
	ORDER_FILTERS,
	format_order_details,
	format_order_summary,
	get_orders_for_user,
	order_status_key,
)
from .telegram_ui import delete_controlled_message, message_thread_id, send_menu

if TYPE_CHECKING:
	from cardinal import Cardinal


class OrdersHost(Protocol):
	tg: object
	tgbot: telebot.TeleBot
	cardinal: Cardinal
	settings: dict[str, Any]


class TelegramOrdersFlow:
	def __init__(self, host: OrdersHost, ask_refund_confirm: Callable[[int, str], None]):
		self.host = host
		self.ask_refund_confirm = ask_refund_confirm

	def register(self) -> None:
		self.host.tg.cbq_handler(
			self.filter_callback,
			lambda c: (c.data or "").startswith(CBT_ORDERS_FILTER),
		)
		self.host.tg.cbq_handler(
			self.detail_callback,
			lambda c: (c.data or "").startswith(CBT_ORDERS_DETAIL),
		)
		self.host.tg.cbq_handler(
			self.refund_callback,
			lambda c: (c.data or "").startswith(CBT_ORDERS_REFUND),
		)
		self.host.tg.msg_handler(self.cmd_orders, commands=["orders"])

	def cmd_orders(self, message: telebot.types.Message) -> None:
		args = (message.text or "").split(maxsplit=1)
		if len(args) > 1:
			self.show_filters(message.chat.id, args[1].strip().lstrip("@"), message_thread_id(message))
			return

		if is_in_sync_chat(message):
			context = get_topic_context(self.host.cardinal, message)
			if not context:
				self.host.tgbot.reply_to(message, "❌ Не удалось определить пользователя из топика.")
				return
			self.show_filters(message.chat.id, context.username, message_thread_id(message))
			return

		self.host.tgbot.reply_to(message, "⚠️ Использование: /orders <ник>\nИли /orders в топике Chat Sync.")

	def show_filters(self, chat_id: int, username: str, thread_id: int | None = None) -> None:
		keyboard = K(row_width=2)
		buttons = [
			B(label, callback_data=f"{CBT_ORDERS_FILTER}{username}|{key}")
			for key, label in ORDER_FILTER_LABELS.items()
		]
		keyboard.add(*buttons)
		send_menu(
			self.host.tgbot,
			chat_id,
			f"📦 <b>Заказы пользователя</b>\n\nПокупатель: <code>{escape(username)}</code>\nВыберите категорию:",
			keyboard,
			thread_id,
		)

	def filter_callback(self, call: telebot.types.CallbackQuery) -> None:
		username, filter_key = parse_two_part_payload(call.data.replace(CBT_ORDERS_FILTER, "", 1))
		self.host.tgbot.answer_callback_query(call.id)
		delete_controlled_message(self.host.tgbot, call.message)
		if filter_key == "menu":
			self.show_filters(call.message.chat.id, username, message_thread_id(call.message))
			return
		self.show_list(call.message.chat.id, username, filter_key, message_thread_id(call.message))

	def show_list(self, chat_id: int, username: str, filter_key: str, thread_id: int | None = None) -> None:
		state = ORDER_FILTERS.get(filter_key)
		orders = get_orders_for_user(self.host.cardinal, username, state=state)
		keyboard = K(row_width=1)
		keyboard.add(B("◀️ Категории", callback_data=f"{CBT_ORDERS_FILTER}{username}|menu"))
		if not orders:
			send_menu(
				self.host.tgbot,
				chat_id,
				f"📦 Заказы не найдены.\n\nПокупатель: <code>{escape(username)}</code>",
				keyboard,
				thread_id,
			)
			return

		keyboard = K(row_width=1)
		for order in orders[:20]:
			keyboard.add(B(
				format_order_summary(order)[:64],
				callback_data=f"{CBT_ORDERS_DETAIL}{username}|{filter_key}|{getattr(order, 'id', '')}",
			))
		keyboard.add(B("◀️ Категории", callback_data=f"{CBT_ORDERS_FILTER}{username}|menu"))
		text = (
			f"📦 <b>{escape(ORDER_FILTER_LABELS.get(filter_key, 'Заказы'))}</b>\n\n"
			f"Покупатель: <code>{escape(username)}</code>\n"
			f"Найдено: <b>{len(orders)}</b>"
		)
		send_menu(self.host.tgbot, chat_id, text, keyboard, thread_id)

	def detail_callback(self, call: telebot.types.CallbackQuery) -> None:
		username, filter_key, order_id = parse_three_part_payload(call.data.replace(CBT_ORDERS_DETAIL, "", 1))
		self.host.tgbot.answer_callback_query(call.id)
		delete_controlled_message(self.host.tgbot, call.message)
		order = self.find_order(username, filter_key, order_id)
		keyboard = K(row_width=1)
		if order and order_status_key(order) == "paid":
			keyboard.add(B("💸 Вернуть деньги", callback_data=f"{CBT_ORDERS_REFUND}{order_id}"))
		if order_id:
			keyboard.add(B("🔗 Открыть заказ", url=f"https://funpay.com/orders/{order_id}/"))
		keyboard.add(B("◀️ К заказам", callback_data=f"{CBT_ORDERS_FILTER}{username}|{filter_key}"))
		text = format_order_details(order) if order else "❌ Заказ не найден."
		send_menu(self.host.tgbot, call.message.chat.id, text, keyboard, message_thread_id(call.message))

	def refund_callback(self, call: telebot.types.CallbackQuery) -> None:
		order_id = call.data.replace(CBT_ORDERS_REFUND, "", 1)
		self.host.tgbot.answer_callback_query(call.id)
		delete_controlled_message(self.host.tgbot, call.message)
		self.ask_refund_confirm(call.message.chat.id, order_id)

	def find_order(self, username: str, filter_key: str, order_id: str) -> object | None:
		state = ORDER_FILTERS.get(filter_key)
		orders = get_orders_for_user(self.host.cardinal, username, state=state)
		return next((order for order in orders if str(getattr(order, "id", "")) == str(order_id)), None)


def parse_two_part_payload(payload: str) -> tuple[str, str]:
	first, _, second = payload.partition("|")
	return first, second or "all"


def parse_three_part_payload(payload: str) -> tuple[str, str, str]:
	first, _, tail = payload.partition("|")
	second, _, third = tail.partition("|")
	return first, second or "all", third
