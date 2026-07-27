from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from html import escape
from typing import Any, Callable, Protocol
from uuid import uuid4

import telebot
from telebot.types import InlineKeyboardButton as B, InlineKeyboardMarkup as K
from tg_bot import CBT

from ..config.constants import CBT_WITHDRAWAL_METHOD, CBT_WITHDRAWAL_PAGE, UUID
from ..funpay.withdrawals import (
	WithdrawalBalance,
	WithdrawalError,
	calculate_withdrawal,
	fetch_withdrawal_balance,
)


class WithdrawalHost(Protocol):
	tg: object
	tgbot: telebot.TeleBot
	cardinal: object


@dataclass(frozen=True)
class WithdrawalSession:
	user_id: int
	balance: WithdrawalBalance
	offset: str


class TelegramWithdrawalFlow:
	def __init__(
		self,
		host: WithdrawalHost,
		fetcher: Callable[[str], WithdrawalBalance] = fetch_withdrawal_balance,
	):
		self.host = host
		self.fetcher = fetcher
		self.sessions: dict[str, WithdrawalSession] = {}

	def register(self) -> None:
		if not self.host.tg:
			return

		self.host.tg.cbq_handler(
			self.open_calculator,
			lambda call: (call.data or "").startswith(CBT_WITHDRAWAL_PAGE),
		)
		self.host.tg.cbq_handler(
			self.select_method,
			lambda call: (call.data or "").startswith(CBT_WITHDRAWAL_METHOD),
		)

	def open_calculator(self, call: telebot.types.CallbackQuery) -> None:
		self.host.tgbot.answer_callback_query(call.id, "Получаю данные баланса...")
		key = str(getattr(getattr(self.host.cardinal, "account", None), "golden_key", "")).strip()
		try:
			balance = self.fetcher(key)
		except WithdrawalError:
			self.show_error(call, "❌ Не удалось получить данные для вывода. Попробуйте ещё раз.")
			return

		token = uuid4().hex
		offset = self.get_offset(call.data or "")
		self.sessions[token] = WithdrawalSession(call.from_user.id, balance, offset)
		keyboard = K(row_width=1)
		for index, method in enumerate(balance.methods):
			keyboard.add(B(
				method.label,
				callback_data=f"{CBT_WITHDRAWAL_METHOD}{token}:{index}",
			))
		keyboard.add(B("◀️ Назад", callback_data=f"{CBT.PLUGIN_SETTINGS}:{UUID}:{offset}"))
		self.host.tgbot.edit_message_text(
			"💸 <b>Калькулятор вывода</b>\n\nВыберите способ вывода.",
			call.message.chat.id,
			call.message.id,
			reply_markup=keyboard,
		)

	def select_method(self, call: telebot.types.CallbackQuery) -> None:
		self.host.tgbot.answer_callback_query(call.id)
		parsed = self.parse_method_callback(call.data or "")
		if not parsed:
			self.show_error(call, "⚠️ Данные калькулятора устарели. Откройте его ещё раз.")
			return

		token, index = parsed
		session = self.sessions.get(token)
		if not session or session.user_id != call.from_user.id or index >= len(session.balance.methods):
			self.show_error(call, "⚠️ Данные калькулятора устарели. Откройте его ещё раз.")
			return

		self.sessions.pop(token, None)
		calculation = calculate_withdrawal(session.balance, session.balance.methods[index])
		currency = escape(session.balance.currency)
		method = escape(calculation.method.label)
		text = (
			f"💸 <b>Вывод через {method}</b>\n\n"
			f"Доступно к выводу: <b>{format_amount(session.balance.available_amount)} {currency}</b>\n"
			f"Фиксированная комиссия: <b>{format_amount(calculation.method.fixed_fee)} {currency}</b>\n"
			f"Процентная комиссия: <b>{format_amount(calculation.percentage_amount)} {currency}</b>\n"
			f"Общая комиссия: <b>{format_amount(calculation.total_fee)} {currency}</b>\n"
			f"Итог к получению: <b>{format_amount(calculation.net_amount)} {currency}</b>"
		)
		keyboard = K(row_width=1)
		keyboard.add(B("◀️ К способам", callback_data=f"{CBT_WITHDRAWAL_PAGE}{session.offset}"))
		self.host.tgbot.edit_message_text(
			text,
			call.message.chat.id,
			call.message.id,
			reply_markup=keyboard,
		)

	def show_error(self, call: telebot.types.CallbackQuery, text: str) -> None:
		offset = self.get_offset(call.data or "")
		keyboard = K(row_width=1)
		keyboard.add(B("◀️ Назад", callback_data=f"{CBT.PLUGIN_SETTINGS}:{UUID}:{offset}"))
		self.host.tgbot.edit_message_text(
			text,
			call.message.chat.id,
			call.message.id,
			reply_markup=keyboard,
		)

	def parse_method_callback(self, data: str) -> tuple[str, int] | None:
		payload = data.removeprefix(CBT_WITHDRAWAL_METHOD)
		token, separator, index_text = payload.partition(":")
		if not token or not separator or not index_text.isdigit():
			return None
		return token, int(index_text)

	def get_offset(self, data: str) -> str:
		value = data.rsplit(":", 1)[-1]
		return value if value.isdigit() else "0"


def format_amount(value: Decimal) -> str:
	text = format(value, "f")
	if "." not in text:
		return text
	return text.rstrip("0").rstrip(".") or "0"
