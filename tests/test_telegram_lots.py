from __future__ import annotations

import sys
import types
import unittest
from types import SimpleNamespace


telebot_module = types.ModuleType("telebot")
telebot_types_module = types.ModuleType("telebot.types")
telebot_types_module.CallbackQuery = object
telebot_types_module.Message = object
telebot_types_module.InlineKeyboardButton = object
telebot_types_module.InlineKeyboardMarkup = object
telebot_module.TeleBot = object
telebot_module.types = telebot_types_module
sys.modules.setdefault("telebot", telebot_module)
sys.modules.setdefault("telebot.types", telebot_types_module)

tg_bot_module = types.ModuleType("tg_bot")
tg_bot_module.CBT = SimpleNamespace(PLUGIN_SETTINGS="plugin_settings", EDIT_PLUGIN="edit_plugin")
sys.modules.setdefault("tg_bot", tg_bot_module)

from core.config.constants import CBT_LOTS_CONFIRM
from core.lots.bulk import ACTION_OFF, ACTION_ON, BulkLotsProgress, BulkLotsResult
from core.telegram import lots as lots_module
from core.telegram.lots import TelegramLotsFlow


class FakeButton:
	def __init__(self, text, callback_data=None, url=None):
		self.text = text
		self.callback_data = callback_data
		self.url = url


class FakeKeyboard:
	def __init__(self, row_width=1):
		self.rows = []

	def add(self, *buttons):
		for button in buttons:
			self.rows.append([button])
		return self


class FakeBot:
	def __init__(self):
		self.messages = []
		self.edits = []
		self.answers = []
		self.replies = []

	def send_message(self, chat_id, text, reply_markup=None, message_thread_id=None):
		self.messages.append((chat_id, text, reply_markup, message_thread_id))
		return SimpleNamespace(id=len(self.messages), chat=SimpleNamespace(id=chat_id), message_thread_id=message_thread_id)

	def edit_message_text(self, text, chat_id, message_id, reply_markup=None):
		self.edits.append((text, chat_id, message_id, reply_markup))

	def answer_callback_query(self, call_id, text=None, show_alert=False):
		self.answers.append((call_id, text, show_alert))

	def reply_to(self, message, text, reply_markup=None):
		self.replies.append((message, text, reply_markup))


class FakeTelegram:
	def __init__(self):
		self.handlers = []

	def cbq_handler(self, handler, func):
		self.handlers.append(("callback", handler))

	def msg_handler(self, handler, commands=None, **kwargs):
		self.handlers.append(("message", handler, tuple(commands or ())))


class FakeBulkLotsService:
	def __init__(self):
		self.started = []
		self.start_result = True
		self.counts = {ACTION_ON: 2, ACTION_OFF: 2}

	def preview_count(self, action):
		return self.counts[action]

	def start(self, action, on_progress, on_complete):
		if not self.start_result:
			return False
		self.started.append(action)
		on_progress(BulkLotsProgress(action, 2, 1, 1, 0, 0))
		on_complete(BulkLotsResult(action, 2, 2, 2, 0, 0, ()))
		return True


def message(text):
	return SimpleNamespace(chat=SimpleNamespace(id=1), text=text, message_thread_id=None)


def callback(data):
	return SimpleNamespace(
		data=data,
		id="callback-1",
		message=SimpleNamespace(chat=SimpleNamespace(id=1), id=2, message_thread_id=None),
	)


def callbacks(keyboard):
	return [row[0].callback_data for row in keyboard.rows]


class TelegramLotsFlowTest(unittest.TestCase):
	def setUp(self):
		lots_module.B = FakeButton
		lots_module.K = FakeKeyboard
		self.bot = FakeBot()
		self.host = SimpleNamespace(
			tg=FakeTelegram(),
			tgbot=self.bot,
			cardinal=SimpleNamespace(),
			settings={"bulk_lots": {"disabled_lot_ids": []}},
			save_settings=lambda: None,
		)
		self.flow = TelegramLotsFlow(self.host)
		self.host.bulk_lots_service = FakeBulkLotsService()
		self.flow.bulk_lots_service = self.host.bulk_lots_service

	def test_lots_command_shows_confirmation(self):
		self.flow.cmd_lots(message("/lots off"))

		_, text, keyboard, _ = self.bot.messages[-1]
		self.assertIn("Выключить лоты: <b>2</b>", text)
		self.assertIn(f"{CBT_LOTS_CONFIRM}{ACTION_OFF}|all", callbacks(keyboard))

	def test_confirmation_starts_operation_and_writes_final_result(self):
		self.flow.confirm_bulk_action(callback(f"{CBT_LOTS_CONFIRM}{ACTION_ON}|all"))

		self.assertEqual(self.host.bulk_lots_service.started, [ACTION_ON])
		self.assertIn("Включение лотов завершено", self.bot.edits[-1][0])
		self.assertIn("Успешно: <b>2</b>", self.bot.edits[-1][0])

	def test_second_confirmation_reports_running_operation(self):
		self.host.bulk_lots_service.start_result = False

		self.flow.confirm_bulk_action(callback(f"{CBT_LOTS_CONFIRM}{ACTION_OFF}|all"))

		self.assertEqual(self.bot.answers[-1][1], "Операция с лотами уже выполняется.")

	def test_invalid_lots_command_shows_usage(self):
		self.flow.cmd_lots(message("/lots"))

		self.assertEqual(self.bot.replies[-1][1], "⚠️ Использование: /lots on или /lots off")


if __name__ == "__main__":
	unittest.main()
