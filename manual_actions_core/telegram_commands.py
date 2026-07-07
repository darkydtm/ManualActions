from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Protocol

import telebot
from telebot.types import InlineKeyboardButton as B, InlineKeyboardMarkup as K

from .blacklist import add_user_to_blacklist, remove_user_from_blacklist
from .chat_sync import get_topic_context, is_in_sync_chat
from .constants import CBT_REFUND_CANCEL, CBT_REFUND_CNF, LOGGER_NAME, LOGGER_PREFIX, UUID
from .orders import get_pending_orders_for_user, refund_order
from .status import InvalidStatusCommand, parse_telegram_status_command, status_label, toggle_status

if TYPE_CHECKING:
	from cardinal import Cardinal
	from .telegram_settings import TelegramSettingsUI


logger = logging.getLogger(LOGGER_NAME)


class CommandHost(Protocol):
	tg: object
	tgbot: telebot.TeleBot
	cardinal: Cardinal
	settings: dict[str, Any]
	telegram_ui: TelegramSettingsUI

	def save_settings(self) -> None:
		...


class TelegramCommands:
	def __init__(self, host: CommandHost):
		self.host = host

	def register(self) -> None:
		if not self.host.tg:
			return

		self.host.tg.cbq_handler(
			self.confirm_refund,
			lambda c: (c.data or "").startswith(CBT_REFUND_CNF),
		)
		self.host.tg.cbq_handler(
			self.cancel_refund,
			lambda c: (c.data or "").startswith(CBT_REFUND_CANCEL),
		)
		self.host.cardinal.add_telegram_commands(UUID, [
			("refund", "Возврат: /refund [ID] или в топике без ID", True),
			("bl", "В ЧС: /bl [ник] или в топике без ника", True),
			("unbl", "Из ЧС: /unbl [ник] или в топике без ника", True),
			("bl_list", "Показать чёрный список", True),
			("status", "Статус: /status [0/1/2]", True),
		])
		self.host.tg.msg_handler(self.cmd_refund, commands=["refund"])
		self.host.tg.msg_handler(self.cmd_bl, commands=["bl"])
		self.host.tg.msg_handler(self.cmd_unbl, commands=["unbl"])
		self.host.tg.msg_handler(self.cmd_bl_list, commands=["bl_list"])
		self.host.tg.msg_handler(self.cmd_status, commands=["status"])

	def cmd_refund(self, message: telebot.types.Message) -> None:
		args = (message.text or "").split()
		if len(args) == 1 and is_in_sync_chat(message):
			context = get_topic_context(self.host.cardinal, message)
			if not context:
				self.host.tgbot.reply_to(message, "❌ Не удалось определить пользователя из топика.")
				return

			wait_message = self.host.tgbot.reply_to(message, f"⏳ Получаю список заказов {context.username}...")
			orders = get_pending_orders_for_user(self.host.cardinal, context.username)
			if not orders:
				self.host.tgbot.edit_message_text(
					f"ℹ️ У {context.username} нет неподтверждённых заказов.",
					wait_message.chat.id,
					wait_message.message_id,
				)
				return

			keyboard = K(row_width=1)
			for order in orders[:10]:
				keyboard.add(B(
					f"#{order.id} - {order.price} {order.currency}",
					callback_data=f"{CBT_REFUND_CNF}{order.id}",
				))
			keyboard.add(B("❌ Отмена", callback_data=f"{CBT_REFUND_CANCEL}menu"))
			self.host.tgbot.edit_message_text(
				f"💸 Выберите заказ для возврата ({context.username}):",
				wait_message.chat.id,
				wait_message.message_id,
				reply_markup=keyboard,
			)
			return

		if len(args) < 2:
			self.host.tgbot.reply_to(
				message,
				"⚠️ Использование: /refund <ID заказа>\n"
				"Или введите /refund в топике Chat Sync для выбора заказа.",
			)
			return

		self.ask_refund_confirm(message.chat.id, args[1].lstrip("#"), reply_to=message)

	def ask_refund_confirm(
		self,
		chat_id: int,
		order_id: str,
		reply_to: telebot.types.Message | None = None,
		edit_msg: telebot.types.Message | None = None,
	) -> None:
		keyboard = K(row_width=2)
		keyboard.add(
			B("✅ Да, вернуть", callback_data=f"{CBT_REFUND_CNF}{order_id}"),
			B("❌ Отмена", callback_data=f"{CBT_REFUND_CANCEL}{order_id}"),
		)
		text = (
			f"⚠️ Подтвердите возврат по заказу #{order_id}\n\n"
			"Это действие необратимо. Деньги будут возвращены покупателю."
		)
		if edit_msg:
			self.host.tgbot.edit_message_text(text, edit_msg.chat.id, edit_msg.message_id, reply_markup=keyboard)
		elif reply_to:
			self.host.tgbot.reply_to(reply_to, text, reply_markup=keyboard)
		else:
			self.host.tgbot.send_message(chat_id, text, reply_markup=keyboard)

	def confirm_refund(self, call: telebot.types.CallbackQuery) -> None:
		order_id = call.data.replace(CBT_REFUND_CNF, "", 1)
		self.host.tgbot.answer_callback_query(call.id)
		try:
			refund_order(self.host.cardinal, order_id)
			self.host.tgbot.edit_message_text(
				f"✅ Возврат по заказу #{order_id} выполнен успешно.",
				call.message.chat.id,
				call.message.id,
				reply_markup=None,
			)
			logger.info(f"{LOGGER_PREFIX} Refund completed for order {order_id}.")
		except Exception as exc:
			self.host.tgbot.edit_message_text(
				f"❌ Ошибка при возврате #{order_id}:\n{exc}",
				call.message.chat.id,
				call.message.id,
				reply_markup=None,
			)
			logger.error(f"{LOGGER_PREFIX} Failed to refund order {order_id}: {exc}")

	def cancel_refund(self, call: telebot.types.CallbackQuery) -> None:
		order_id = call.data.replace(CBT_REFUND_CANCEL, "", 1)
		self.host.tgbot.answer_callback_query(call.id, "Отменено.")
		text = "❌ Возврат отменён." if order_id == "menu" else f"❌ Возврат по заказу #{order_id} отменён."
		self.host.tgbot.edit_message_text(text, call.message.chat.id, call.message.id, reply_markup=None)

	def cmd_bl(self, message: telebot.types.Message) -> None:
		args = (message.text or "").split()
		if len(args) == 1 and is_in_sync_chat(message):
			context = get_topic_context(self.host.cardinal, message)
			if not context:
				self.host.tgbot.reply_to(message, "❌ Не удалось определить пользователя из топика.")
				return
			self.add_blacklist_user(message, context.username)
			return

		if len(args) < 2:
			self.host.tgbot.reply_to(
				message,
				"⚠️ Использование: /bl <ник>\n"
				"Или введите /bl в топике Chat Sync - ник возьмётся из темы.",
			)
			return

		self.add_blacklist_user(message, args[1].lstrip("@"))

	def add_blacklist_user(self, message: telebot.types.Message, username: str) -> None:
		try:
			if not add_user_to_blacklist(self.host.cardinal, username):
				self.host.tgbot.reply_to(message, f"ℹ️ {username} уже в чёрном списке.")
				return
			self.host.tgbot.reply_to(message, f"🚫 {username} добавлен в чёрный список.")
			logger.info(f"{LOGGER_PREFIX} Added {username} to blacklist.")
		except Exception as exc:
			self.host.tgbot.reply_to(message, f"❌ Ошибка: {exc}")

	def cmd_unbl(self, message: telebot.types.Message) -> None:
		args = (message.text or "").split()
		if len(args) == 1 and is_in_sync_chat(message):
			context = get_topic_context(self.host.cardinal, message)
			if not context:
				self.host.tgbot.reply_to(message, "❌ Не удалось определить пользователя из топика.")
				return
			self.remove_blacklist_user(message, context.username)
			return

		if len(args) < 2:
			self.host.tgbot.reply_to(
				message,
				"⚠️ Использование: /unbl <ник>\n"
				"Или введите /unbl в топике Chat Sync.",
			)
			return

		self.remove_blacklist_user(message, args[1].lstrip("@"))

	def remove_blacklist_user(self, message: telebot.types.Message, username: str) -> None:
		try:
			if not remove_user_from_blacklist(self.host.cardinal, username):
				self.host.tgbot.reply_to(message, f"ℹ️ {username} не найден в чёрном списке.")
				return
			self.host.tgbot.reply_to(message, f"✅ {username} убран из чёрного списка.")
			logger.info(f"{LOGGER_PREFIX} Removed {username} from blacklist.")
		except Exception as exc:
			self.host.tgbot.reply_to(message, f"❌ Ошибка: {exc}")

	def cmd_bl_list(self, message: telebot.types.Message) -> None:
		self.host.telegram_ui.show_blacklist_page(message.chat.id)

	def cmd_status(self, message: telebot.types.Message) -> None:
		try:
			requested_status = parse_telegram_status_command(message.text)
		except InvalidStatusCommand:
			self.host.tgbot.reply_to(message, "⚠️ Использование: /status [0/1/2]")
			return

		status_id = toggle_status(self.host.settings["status"]) if requested_status is None else requested_status
		self.host.settings["status"] = status_id
		self.host.save_settings()
		self.host.tgbot.reply_to(message, f"✅ Статус: {status_label(status_id)}")
