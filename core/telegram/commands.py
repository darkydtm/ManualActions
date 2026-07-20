from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Protocol

import telebot
from telebot.types import InlineKeyboardButton as B, InlineKeyboardMarkup as K

from ..funpay.chat_sync import get_topic_context, is_in_sync_chat
from ..gist.telegram import TelegramGistFlow
from ..constants import (
	CBT_UPDATER_CHECK,
	CBT_REFUND_CANCEL,
	CBT_REFUND_CNF,
	LOGGER_NAME,
	LOGGER_PREFIX,
	UUID,
)
from ..funpay.orders import get_pending_orders_for_user, refund_order
from ..status import InvalidStatusCommand, parse_telegram_status_command, status_label, toggle_status
from ..updater import ReleaseCheckResult
from .blacklist import TelegramBlacklistFlow
from .lots import TelegramLotsFlow
from .orders import TelegramOrdersFlow
from .templates import TelegramTemplatesFlow

if TYPE_CHECKING:
	from cardinal import Cardinal
	from .settings import TelegramSettingsUI


logger = logging.getLogger(LOGGER_NAME)


class CommandHost(Protocol):
	tg: object
	tgbot: telebot.TeleBot
	cardinal: Cardinal
	settings: dict[str, Any]
	telegram_ui: TelegramSettingsUI

	def save_settings(self) -> None:
		...

	def check_updates_manually(self) -> ReleaseCheckResult:
		...


class TelegramCommands:
	COMMANDS = [
		("refund", "Возврат: /refund [ID] или в топике без ID", True),
		("bl", "Переключить ЧС: /bl [ник] или в топике без ника", True),
		("bl_list", "Показать чёрный список", True),
		("lot", "Информация о лоте: /lot [ID] или в топике", True),
		("orders", "Заказы пользователя: /orders [ник] или в топике", True),
		("gist", "Создать GitHub Gist: /gist &lt;текст&gt; или reply", True),
		("templates", "Отправить заготовку в топике Chat Sync", True),
		("status", "Статус: /status [0/1/2]", True),
		("update", "Проверить обновления Manual Actions", True),
	]

	def __init__(self, host: CommandHost):
		self.host = host
		self.blacklist_flow = TelegramBlacklistFlow(host)
		self.lots_flow = TelegramLotsFlow(host)
		self.orders_flow = TelegramOrdersFlow(host, self.ask_refund_confirm)
		self.gist_flow = TelegramGistFlow(host)
		self.templates_flow = TelegramTemplatesFlow(host)

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
		self.blacklist_flow.register()
		self.lots_flow.register()
		self.orders_flow.register()
		self.gist_flow.register()
		self.templates_flow.register()
		self.host.cardinal.add_telegram_commands(UUID, self.COMMANDS)
		self.host.tg.msg_handler(self.cmd_refund, commands=["refund"])
		self.host.tg.msg_handler(self.cmd_status, commands=["status"])
		self.host.tg.msg_handler(self.cmd_update, commands=["update"])

	def cmd_update(self, message: telebot.types.Message) -> None:
		try:
			result = self.host.check_updates_manually()
			if result.message == "not_new":
				text = "✅ Новых обновлений нет."
			elif result.message == "available" and result.release:
				text = f"🆕 Доступно обновление: <code>{result.release.version}</code>."
			elif result.message == "installed" and result.release:
				text = f"✅ Обновление <code>{result.release.version}</code> установлено. Перезапустите Cardinal."
			else:
				text = "ℹ️ Проверка обновлений завершена."
		except Exception as exc:
			text = f"❌ Не удалось проверить обновления:\n<code>{exc}</code>"
		self.host.tgbot.reply_to(message, text)

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
