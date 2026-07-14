from __future__ import annotations

import logging
from html import escape
from typing import TYPE_CHECKING, Any, Protocol

import telebot
from telebot.types import InlineKeyboardButton as B, InlineKeyboardMarkup as K

from ..funpay.blacklist import block_user, list_blocked_users, toggle_action_for_user, unblock_user
from ..funpay.chat_sync import get_topic_context, is_in_sync_chat
from ..constants import (
	CBT_BL_CANCEL,
	CBT_BL_CONFIRM,
	CBT_BL_LIST,
	CBT_BL_UNBLOCK,
	CBT_BL_USER,
	LOGGER_NAME,
	LOGGER_PREFIX,
)
from ..payloads import parse_blacklist_payload
from .ui import delete_controlled_message, message_thread_id, send_menu

if TYPE_CHECKING:
	from cardinal import Cardinal


logger = logging.getLogger(LOGGER_NAME)


class BlacklistHost(Protocol):
	tg: object
	tgbot: telebot.TeleBot
	cardinal: Cardinal
	settings: dict[str, Any]


class TelegramBlacklistFlow:
	def __init__(self, host: BlacklistHost):
		self.host = host

	def register(self) -> None:
		self.host.tg.cbq_handler(
			self.confirm_action,
			lambda c: (c.data or "").startswith(CBT_BL_CONFIRM),
		)
		self.host.tg.cbq_handler(
			self.cancel_action,
			lambda c: (c.data or "").startswith(CBT_BL_CANCEL),
		)
		self.host.tg.cbq_handler(
			self.open_list_callback,
			lambda c: (c.data or "").startswith(CBT_BL_LIST),
		)
		self.host.tg.cbq_handler(
			self.open_user_callback,
			lambda c: (c.data or "").startswith(CBT_BL_USER),
		)
		self.host.tg.cbq_handler(
			self.unblock_user_callback,
			lambda c: (c.data or "").startswith(CBT_BL_UNBLOCK),
		)
		self.host.tg.msg_handler(self.cmd_bl, commands=["bl"])
		self.host.tg.msg_handler(self.cmd_bl_list, commands=["bl_list"])

	def cmd_bl(self, message: telebot.types.Message) -> None:
		args = (message.text or "").split()
		if len(args) == 1 and is_in_sync_chat(message):
			context = get_topic_context(self.host.cardinal, message)
			if not context:
				self.host.tgbot.reply_to(message, "❌ Не удалось определить пользователя из топика.")
				return
			self.ask_confirm(message, toggle_action_for_user(self.host.cardinal, context.username), context.username, context.fp_chat_id)
			return

		if len(args) < 2:
			self.host.tgbot.reply_to(
				message,
				"⚠️ Использование: /bl <ник>\n"
				"Или введите /bl в топике Chat Sync - ник возьмётся из темы.\n"
				"Команда блокирует или разблокирует пользователя.",
			)
			return

		username = args[1].lstrip("@")
		self.ask_confirm(message, toggle_action_for_user(self.host.cardinal, username), username, None)

	def ask_confirm(
		self,
		message: telebot.types.Message,
		action: str,
		username: str,
		chat_id: int | str | None,
	) -> None:
		label = "заблокировать" if action == "block" else "разблокировать"
		button = "🚫 Заблокировать" if action == "block" else "✅ Разблокировать"
		keyboard = K(row_width=2)
		keyboard.add(
			B(button, callback_data=f"{CBT_BL_CONFIRM}{action}|{username}|{chat_id or ''}"),
			B("❌ Отмена", callback_data=f"{CBT_BL_CANCEL}{username}"),
		)
		self.host.tgbot.reply_to(
			message,
			f"Подтвердите действие: {label} <code>{escape(username)}</code> на FunPay.",
			reply_markup=keyboard,
		)

	def confirm_action(self, call: telebot.types.CallbackQuery) -> None:
		action, username, chat_id = parse_blacklist_payload(call.data.replace(CBT_BL_CONFIRM, "", 1))
		self.host.tgbot.answer_callback_query(call.id)
		try:
			if action == "block":
				changed = block_user(self.host.cardinal, username, chat_id=chat_id)
				text = "🚫 Пользователь заблокирован на FunPay." if changed else "🚫 Блокировка FunPay обновлена."
				logger.info(f"{LOGGER_PREFIX} Blocked {username}.")
			else:
				changed = unblock_user(self.host.cardinal, username, chat_id=chat_id)
				text = "✅ Пользователь разблокирован на FunPay." if changed else "✅ Разблокировка FunPay обновлена."
				logger.info(f"{LOGGER_PREFIX} Unblocked {username}.")
			self.host.tgbot.edit_message_text(
				f"{text}\n\nПользователь: <code>{escape(username)}</code>",
				call.message.chat.id,
				call.message.id,
				reply_markup=None,
			)
		except Exception as exc:
			self.host.tgbot.edit_message_text(
				f"❌ Ошибка при работе с ЧС FunPay:\n{escape(str(exc))}",
				call.message.chat.id,
				call.message.id,
				reply_markup=None,
			)

	def cancel_action(self, call: telebot.types.CallbackQuery) -> None:
		self.host.tgbot.answer_callback_query(call.id, "Отменено.")
		self.host.tgbot.edit_message_text("❌ Действие отменено.", call.message.chat.id, call.message.id, reply_markup=None)

	def cmd_bl_list(self, message: telebot.types.Message) -> None:
		self.show_list(message.chat.id, message_thread_id(message))

	def open_list_callback(self, call: telebot.types.CallbackQuery) -> None:
		self.host.tgbot.answer_callback_query(call.id)
		delete_controlled_message(self.host.tgbot, call.message)
		self.show_list(call.message.chat.id, message_thread_id(call.message))

	def show_list(self, chat_id: int, thread_id: int | None = None) -> None:
		users = list_blocked_users(self.host.cardinal)
		keyboard = K(row_width=1)
		if not users:
			send_menu(self.host.tgbot, chat_id, "🚫 Чёрный список пуст.", keyboard, thread_id)
			return

		for username in users[:30]:
			keyboard.add(B(username, callback_data=f"{CBT_BL_USER}{username}"))
		text = f"🚫 <b>Чёрный список</b>\n\nВсего: <b>{len(users)}</b>"
		if len(users) > 30:
			text += "\nПоказаны первые 30 пользователей."
		send_menu(self.host.tgbot, chat_id, text, keyboard, thread_id)

	def open_user_callback(self, call: telebot.types.CallbackQuery) -> None:
		username = call.data.replace(CBT_BL_USER, "", 1).strip()
		self.host.tgbot.answer_callback_query(call.id)
		delete_controlled_message(self.host.tgbot, call.message)
		keyboard = K(row_width=1)
		keyboard.add(B("✅ Разблокировать", callback_data=f"{CBT_BL_UNBLOCK}{username}"))
		keyboard.add(B("◀️ Назад", callback_data=CBT_BL_LIST))
		send_menu(
			self.host.tgbot,
			call.message.chat.id,
			f"🚫 <b>Пользователь в ЧС</b>\n\nНик: <code>{escape(username)}</code>",
			keyboard,
			message_thread_id(call.message),
		)

	def unblock_user_callback(self, call: telebot.types.CallbackQuery) -> None:
		username = call.data.replace(CBT_BL_UNBLOCK, "", 1).strip()
		self.host.tgbot.answer_callback_query(call.id)
		try:
			unblock_user(self.host.cardinal, username)
			delete_controlled_message(self.host.tgbot, call.message)
			keyboard = K(row_width=1)
			keyboard.add(B("◀️ К списку", callback_data=CBT_BL_LIST))
			send_menu(
				self.host.tgbot,
				call.message.chat.id,
				f"✅ <code>{escape(username)}</code> разблокирован на FunPay.",
				keyboard,
				message_thread_id(call.message),
			)
		except Exception as exc:
			self.host.tgbot.edit_message_text(
				f"❌ Ошибка при разблокировке:\n{escape(str(exc))}",
				call.message.chat.id,
				call.message.id,
				reply_markup=None,
			)
