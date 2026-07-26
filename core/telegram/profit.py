from __future__ import annotations

from datetime import datetime
from html import escape
from typing import TYPE_CHECKING, Any, Protocol

import telebot
import tg_bot.static_keyboards
from telebot.types import InlineKeyboardButton as B, InlineKeyboardMarkup as K
from tg_bot import CBT

from ..config.constants import (
	CBT_PROFIT_CUSTOM,
	CBT_PROFIT_PAGE,
	CBT_PROFIT_PERIOD,
	CBT_PROFIT_TOGGLE_PAID,
	STATE_PROFIT_CUSTOM_PERIOD,
	UUID,
)
from ..funpay.profit import (
	InvalidProfitPeriod,
	PROFIT_PERIODS,
	PROFIT_PERIOD_LABELS,
	calculate_profit,
	format_profit_summary,
	parse_custom_period,
)
from ..runtime.settings import update_host_settings
from .ui import message_thread_id

if TYPE_CHECKING:
	from cardinal import Cardinal


class ProfitHost(Protocol):
	tg: object
	tgbot: telebot.TeleBot
	cardinal: Cardinal
	settings: dict[str, Any]


class TelegramProfitFlow:
	def __init__(self, host: ProfitHost):
		self.host = host

	def register(self) -> None:
		if not self.host.tg:
			return

		self.host.tg.cbq_handler(
			self.open_page,
			lambda c: (c.data or "").startswith(CBT_PROFIT_PAGE),
		)
		self.host.tg.cbq_handler(
			self.select_period,
			lambda c: (c.data or "").startswith(CBT_PROFIT_PERIOD),
		)
		self.host.tg.cbq_handler(
			self.ask_custom_period,
			lambda c: (c.data or "").startswith(CBT_PROFIT_CUSTOM),
		)
		self.host.tg.cbq_handler(
			self.toggle_include_paid,
			lambda c: (c.data or "").startswith(CBT_PROFIT_TOGGLE_PAID),
		)
		self.host.tg.msg_handler(
			self.save_custom_period,
			func=lambda m: self.host.tg.check_state(m.chat.id, m.from_user.id, STATE_PROFIT_CUSTOM_PERIOD),
		)
		self.host.tg.msg_handler(self.cmd_profit, commands=["profit"])

	def cmd_profit(self, message: telebot.types.Message) -> None:
		self.show_menu(message.chat.id, thread_id=message_thread_id(message))

	def open_page(self, call: telebot.types.CallbackQuery) -> None:
		offset = self.get_offset(call.data)
		self.show_menu(call.message.chat.id, call.message.id, offset, edit=True)
		self.host.tgbot.answer_callback_query(call.id)

	def show_menu(
		self,
		chat_id: int,
		message_id: int | None = None,
		offset: str = "0",
		edit: bool = False,
		thread_id: int | None = None,
	) -> None:
		include_paid = self.include_paid()
		text = (
			"💰 <b>Прибыль</b>\n\n"
			f"Учёт: <b>{'закрытые + оплаченные' if include_paid else 'только закрытые'}</b>\n\n"
			"Выберите период."
		)

		keyboard = K(row_width=2)
		keyboard.add(*[
			B(PROFIT_PERIOD_LABELS[period], callback_data=f"{CBT_PROFIT_PERIOD}{period}:{offset}")
			for period in PROFIT_PERIODS
		])
		keyboard.add(B(PROFIT_PERIOD_LABELS["custom"], callback_data=f"{CBT_PROFIT_CUSTOM}{offset}"))
		keyboard.add(B(
			"💳 Не учитывать оплаченные" if include_paid else "💳 Учитывать оплаченные",
			callback_data=f"{CBT_PROFIT_TOGGLE_PAID}{offset}",
		))
		keyboard.add(B("◀️ Назад", callback_data=f"{CBT.PLUGIN_SETTINGS}:{UUID}:{offset}"))
		self.send_or_edit(text, chat_id, message_id, keyboard, edit, thread_id)

	def select_period(self, call: telebot.types.CallbackQuery) -> None:
		period, offset = self.parse_callback(call.data, CBT_PROFIT_PERIOD)
		if period not in PROFIT_PERIODS:
			self.host.tgbot.answer_callback_query(call.id)
			return

		self.host.tgbot.answer_callback_query(call.id, "Считаю прибыль...")
		self.show_report(call.message.chat.id, call.message.id, period, offset, edit=True)

	def ask_custom_period(self, call: telebot.types.CallbackQuery) -> None:
		offset = self.get_offset(call.data)
		result = self.host.tgbot.send_message(
			call.message.chat.id,
			"Введите период: одну дату или две через пробел.\n"
			"Форматы: <code>01.07.2026</code>, <code>2026-07-01</code>.\n"
			"Пример: <code>01.07.2026 15.07.2026</code>",
			reply_markup=tg_bot.static_keyboards.CLEAR_STATE_BTN(),
		)
		self.host.tg.set_state(
			call.message.chat.id,
			result.id,
			call.from_user.id,
			STATE_PROFIT_CUSTOM_PERIOD,
			{"offset": offset},
		)
		self.host.tgbot.answer_callback_query(call.id)

	def save_custom_period(self, message: telebot.types.Message) -> None:
		state = self.host.tg.get_state(message.chat.id, message.from_user.id) or {}
		offset = state.get("data", {}).get("offset", "0")
		try:
			custom = parse_custom_period(message.text, datetime.now())
		except InvalidProfitPeriod:
			self.host.tgbot.reply_to(message, "⚠️ Не удалось разобрать период. Пример: 01.07.2026 15.07.2026")
			return

		self.host.tg.clear_state(message.chat.id, message.from_user.id, True)
		self.show_report(message.chat.id, None, "custom", offset, edit=False, custom=custom)

	def toggle_include_paid(self, call: telebot.types.CallbackQuery) -> None:
		offset = self.get_offset(call.data)
		include_paid = not self.include_paid()
		update_host_settings(
			self.host,
			lambda settings: settings["profit"].__setitem__("include_paid", include_paid),
		)
		self.show_menu(call.message.chat.id, call.message.id, offset, edit=True)
		self.host.tgbot.answer_callback_query(
			call.id,
			"Оплаченные учитываются." if include_paid else "Учитываются только закрытые.",
		)

	def show_report(
		self,
		chat_id: int,
		message_id: int | None,
		period: str,
		offset: str,
		edit: bool,
		custom: tuple[datetime, datetime] | None = None,
	) -> None:
		try:
			summary = calculate_profit(self.host.cardinal, period, self.include_paid(), custom=custom)
			text = format_profit_summary(summary)
		except InvalidProfitPeriod:
			text = "⚠️ Не удалось определить период."
		except Exception as exc:
			text = f"❌ Не удалось получить продажи:\n<code>{escape(str(exc))}</code>"

		keyboard = K(row_width=1)
		keyboard.add(B("◀️ К периодам", callback_data=f"{CBT_PROFIT_PAGE}{offset}"))
		self.send_or_edit(text, chat_id, message_id, keyboard, edit)

	def include_paid(self) -> bool:
		return bool(self.host.settings["profit"]["include_paid"])

	def send_or_edit(
		self,
		text: str,
		chat_id: int,
		message_id: int | None,
		keyboard: K,
		edit: bool,
		thread_id: int | None = None,
	) -> None:
		if edit and message_id:
			try:
				self.host.tgbot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard)
				return
			except Exception:
				pass
		kwargs = {"reply_markup": keyboard}
		if thread_id is not None:
			kwargs["message_thread_id"] = thread_id
		self.host.tgbot.send_message(chat_id, text, **kwargs)

	def parse_callback(self, data: str, prefix: str) -> tuple[str, str]:
		payload = data.replace(prefix, "", 1)
		parts = payload.split(":", 1)
		offset = parts[1] if len(parts) > 1 and parts[1].isdigit() else "0"
		return parts[0], offset

	def get_offset(self, data: str) -> str:
		parts = data.split(":")
		return parts[-1] if parts and parts[-1].isdigit() else "0"
