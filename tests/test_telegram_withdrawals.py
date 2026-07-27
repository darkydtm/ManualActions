from __future__ import annotations

from decimal import Decimal
import sys
import types
import unittest
from types import SimpleNamespace


telebot_module = types.ModuleType("telebot")
telebot_types_module = types.ModuleType("telebot.types")
telebot_types_module.CallbackQuery = object
telebot_types_module.InlineKeyboardButton = object
telebot_types_module.InlineKeyboardMarkup = object
telebot_types_module.Message = object
telebot_module.TeleBot = object
telebot_module.types = telebot_types_module
sys.modules.setdefault("telebot", telebot_module)
sys.modules.setdefault("telebot.types", telebot_types_module)

tg_bot_module = types.ModuleType("tg_bot")
tg_bot_module.CBT = SimpleNamespace(PLUGIN_SETTINGS="plugin_settings")
sys.modules.setdefault("tg_bot", tg_bot_module)

from core.funpay.withdrawals import WithdrawalBalance, WithdrawalError, WithdrawalMethod
from core.telegram import withdrawals as withdrawals_module
from core.telegram.withdrawals import TelegramWithdrawalFlow


class FakeButton:
	def __init__(self, text, callback_data=None):
		self.text = text
		self.callback_data = callback_data


class FakeKeyboard:
	def __init__(self, row_width=1):
		self.rows = []

	def add(self, *buttons):
		for button in buttons:
			self.rows.append([button])
		return self


class FakeBot:
	def __init__(self):
		self.edits = []
		self.answers = []

	def edit_message_text(self, text, chat_id, message_id, reply_markup=None):
		self.edits.append((text, chat_id, message_id, reply_markup))

	def answer_callback_query(self, call_id, text=None, show_alert=False):
		self.answers.append((call_id, text, show_alert))


class FakeTelegram:
	def __init__(self):
		self.handlers = []

	def cbq_handler(self, handler, func):
		self.handlers.append((handler, func))


def sample_balance():
	return WithdrawalBalance(
		Decimal("1234.56"),
		"₽",
		(WithdrawalMethod("sbp", "СБП", Decimal("15"), Decimal("2.5")),),
	)


def sample_call(data="ma_withdrawal_page:0", user_id=3):
	return SimpleNamespace(
		data=data,
		id="call-1",
		from_user=SimpleNamespace(id=user_id),
		message=SimpleNamespace(chat=SimpleNamespace(id=1), id=2),
	)


class TelegramWithdrawalFlowTest(unittest.TestCase):
	def setUp(self):
		withdrawals_module.B = FakeButton
		withdrawals_module.K = FakeKeyboard

	def make_host(self, golden_key="secret-key"):
		return SimpleNamespace(
			tg=FakeTelegram(),
			tgbot=FakeBot(),
			cardinal=SimpleNamespace(account=SimpleNamespace(golden_key=golden_key)),
		)

	def test_open_calculator_fetches_balance_and_lists_methods(self):
		keys = []
		host = self.make_host()
		flow = TelegramWithdrawalFlow(host, fetcher=lambda key: keys.append(key) or sample_balance())

		flow.open_calculator(sample_call())

		text, _, _, keyboard = host.tgbot.edits[-1]
		self.assertEqual(keys, ["secret-key"])
		self.assertIn("Выберите способ вывода", text)
		self.assertNotIn("secret-key", text)
		self.assertNotIn("secret-key", keyboard.rows[0][0].callback_data)
		self.assertEqual(host.tgbot.answers[-1][1], "Получаю данные баланса...")

	def test_select_method_renders_all_fee_values(self):
		host = self.make_host()
		flow = TelegramWithdrawalFlow(host, fetcher=lambda key: sample_balance())
		flow.open_calculator(sample_call())
		payload = host.tgbot.edits[-1][3].rows[0][0].callback_data

		flow.select_method(sample_call(payload))

		text = host.tgbot.edits[-1][0]
		for label in (
			"Доступно к выводу",
			"Фиксированная комиссия",
			"Процентная комиссия",
			"Общая комиссия",
			"Итог к получению",
		):
			self.assertIn(label, text)
		self.assertNotIn("secret-key", text)

	def test_shows_safe_error_when_balance_request_fails(self):
		host = self.make_host()
		flow = TelegramWithdrawalFlow(host, fetcher=lambda key: (_ for _ in ()).throw(WithdrawalError("secret-key")))

		flow.open_calculator(sample_call())

		self.assertIn("Не удалось получить данные", host.tgbot.edits[-1][0])
		self.assertNotIn("secret-key", host.tgbot.edits[-1][0])

	def test_rejects_expired_or_foreign_callback(self):
		host = self.make_host()
		flow = TelegramWithdrawalFlow(host, fetcher=lambda key: sample_balance())
		flow.select_method(sample_call("ma_withdrawal_method:unknown:0", user_id=99))

		self.assertIn("устарели", host.tgbot.edits[-1][0])
		self.assertEqual(host.tgbot.answers[-1][0], "call-1")


if __name__ == "__main__":
	unittest.main()
