from __future__ import annotations

import sys
import types
from types import SimpleNamespace
import unittest
from unittest.mock import Mock


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
tg_bot_static_keyboards_module = types.ModuleType("tg_bot.static_keyboards")
tg_bot_utils_module = types.ModuleType("tg_bot.utils")
tg_bot_module.CBT = SimpleNamespace(PLUGIN_SETTINGS="plugin_settings")
tg_bot_static_keyboards_module.CLEAR_STATE_BTN = lambda: None
tg_bot_utils_module.escape = lambda value: value
sys.modules.setdefault("tg_bot", tg_bot_module)
sys.modules.setdefault("tg_bot.static_keyboards", tg_bot_static_keyboards_module)
sys.modules.setdefault("tg_bot.utils", tg_bot_utils_module)

from core.config.constants import (
	CBT_AUTO_DUMPING_BLACKLIST_ADD,
	CBT_AUTO_DUMPING_BLACKLIST_DELETE,
	CBT_AUTO_DUMPING_BLACKLIST_PAGE,
	CBT_AUTO_DUMPING_INTERVAL,
	CBT_AUTO_DUMPING_PERIOD_PAGE,
	CBT_AUTO_DUMPING_RULES_PAGE,
	CBT_AUTO_DUMPING_STATUS,
)
from core.modules.auto_dumping.telegram import TelegramAutoDumpingFlow, validate_rule_input


class FakeButton:
	def __init__(self, text, callback_data=None, url=None):
		self.text = text
		self.callback_data = callback_data
		self.url = url


class FakeKeyboard:
	def __init__(self, row_width=1):
		self.rows = []

	def add(self, *buttons):
		self.rows.append(list(buttons))
		return self


class FakeBot:
	def __init__(self):
		self.messages = []
		self.edits = []
		self.answers = []

	def send_message(self, chat_id, text, reply_markup=None, **kwargs):
		self.messages.append((chat_id, text, reply_markup))
		return SimpleNamespace(id=len(self.messages))

	def edit_message_text(self, text, chat_id, message_id, reply_markup=None):
		self.edits.append((text, chat_id, message_id, reply_markup))

	def answer_callback_query(self, call_id, text=None, show_alert=False):
		self.answers.append((call_id, text, show_alert))


class FakeTelegram:
	def __init__(self):
		self.callbacks = []
		self.messages = []
		self.states = {}

	def cbq_handler(self, handler, predicate):
		self.callbacks.append((handler, predicate))

	def msg_handler(self, handler, **kwargs):
		self.messages.append((handler, kwargs))

	def set_state(self, *args):
		self.states[args[2]] = (args[3], args[4])

	def get_state(self, chat_id, user_id):
		state = self.states.get(user_id)
		return {"state": state[0], "data": state[1]} if state else None

	def clear_state(self, chat_id, user_id, *args):
		self.states.pop(user_id, None)


class AutoDumpingTelegramTest(unittest.TestCase):
	def setUp(self):
		import core.modules.auto_dumping.telegram as module
		module.B = FakeButton
		module.K = FakeKeyboard
		self.host = SimpleNamespace(
			tg=FakeTelegram(),
			tgbot=FakeBot(),
			settings={"auto_dumping": {
				"enabled": True,
				"interval_minutes": 5,
				"rules": [],
			}},
			save_settings=Mock(),
		)
		self.scheduler = Mock()
		self.flow = TelegramAutoDumpingFlow(self.host, Mock(), self.scheduler)

	def test_main_screen_contains_interval_and_enable_controls(self):
		self.flow.show_main(1)

		text, keyboard = self.host.tgbot.messages[0][1:]
		callbacks = [button.callback_data for row in keyboard.rows for button in row]
		self.assertIn(f"{CBT_AUTO_DUMPING_INTERVAL}1", callbacks)
		self.assertFalse(any("чёрный список" in button.text for row in keyboard.rows for button in row))
		self.assertIn("Автодемпинг", text)

	def test_register_does_not_expose_global_blacklist_handlers(self):
		self.flow.register()

		callback_handlers = [handler.__name__ for handler, _ in self.host.tg.callbacks]
		message_handlers = [handler.__name__ for handler, _ in self.host.tg.messages]
		self.assertNotIn("edit_sellers", callback_handlers)
		self.assertNotIn("edit_keywords", callback_handlers)
		self.assertNotIn("save_sellers", message_handlers)
		self.assertNotIn("save_keywords", message_handlers)

	def test_registers_new_auto_dumping_callback_prefixes(self):
		self.flow.register()
		prefixes = (
			CBT_AUTO_DUMPING_STATUS,
			CBT_AUTO_DUMPING_PERIOD_PAGE,
			CBT_AUTO_DUMPING_RULES_PAGE,
			CBT_AUTO_DUMPING_BLACKLIST_PAGE,
			CBT_AUTO_DUMPING_BLACKLIST_DELETE,
			CBT_AUTO_DUMPING_BLACKLIST_ADD,
		)

		predicates = [predicate for _, predicate in self.host.tg.callbacks]
		for prefix in prefixes:
			self.assertTrue(any(predicate(SimpleNamespace(data=f"{prefix}payload")) for predicate in predicates))

	def test_page_slice_limits_items_to_five(self):
		items = list(range(12))
		self.assertEqual(self.flow._page_items(items, 1), (items[5:10], 3))

	def test_empty_page_still_has_one_total_page(self):
		self.assertEqual(self.flow._page_items([], 0), ([], 1))

	def test_page_callback_keeps_context_and_zero_based_page(self):
		data = self.flow._page_callback(CBT_AUTO_DUMPING_BLACKLIST_PAGE, "rule:sellers", 2)
		self.assertEqual(self.flow._parse_page_callback(data, CBT_AUTO_DUMPING_BLACKLIST_PAGE), ("rule:sellers", 2))

	def test_blacklist_page_callback_compacts_arbitrary_rule_context(self):
		rule_id = "rule-id-with-hyphens-0123456789ab"
		data = self.flow._page_callback(CBT_AUTO_DUMPING_BLACKLIST_PAGE, f"{rule_id}:keywords", 0)

		self.assertLessEqual(len(data.encode("utf-8")), 64)
		self.assertEqual(self.flow._parse_page_callback(data, CBT_AUTO_DUMPING_BLACKLIST_PAGE), (f"{rule_id}:keywords", 0))

	def test_blacklist_page_callback_preserves_uppercase_rule_id(self):
		rule_id = "ABCDEF0123456789ABCDEF0123456789"
		data = self.flow._page_callback(CBT_AUTO_DUMPING_BLACKLIST_PAGE, f"{rule_id}:sellers", 0)

		self.assertLessEqual(len(data.encode("utf-8")), 64)
		self.assertEqual(self.flow._parse_page_callback(data, CBT_AUTO_DUMPING_BLACKLIST_PAGE), (f"{rule_id}:sellers", 0))

	def test_page_callback_handles_malformed_and_negative_pages(self):
		self.assertEqual(self.flow._parse_page_callback(f"{CBT_AUTO_DUMPING_BLACKLIST_PAGE}rule:sellers:-2", CBT_AUTO_DUMPING_BLACKLIST_PAGE), ("rule:sellers", 0))
		self.assertEqual(self.flow._parse_page_callback("not-a-callback", CBT_AUTO_DUMPING_BLACKLIST_PAGE), ("", 0))
		self.assertEqual(
			self.flow._parse_page_callback(f"{CBT_AUTO_DUMPING_BLACKLIST_PAGE}~not-valid!!!:keywords:0", CBT_AUTO_DUMPING_BLACKLIST_PAGE),
			("~not-valid!!!:keywords", 0),
		)

	def test_page_slice_clamps_page_to_last_available_page(self):
		self.assertEqual(self.flow._page_items(list(range(6)), 99), ([5], 2))

	def test_interval_callback_accepts_positive_custom_value(self):
		call = SimpleNamespace(
			id="call",
			data=f"{CBT_AUTO_DUMPING_INTERVAL}10",
			message=SimpleNamespace(chat=SimpleNamespace(id=1), id=2),
		)

		self.flow.set_interval(call)

		self.assertEqual(self.host.settings["auto_dumping"]["interval_minutes"], 10)
		self.scheduler.stop.assert_called_once()
		self.scheduler.start.assert_called_once()

	def test_rule_validation_rejects_empty_keywords_and_nonpositive_dumping(self):
		with self.assertRaises(ValueError):
			validate_rule_input({"subcategory": "game", "keywords": [], "dumping_value": 1})
		with self.assertRaises(ValueError):
			validate_rule_input({"subcategory": "game", "keywords": ["gold"], "dumping_value": 0})


if __name__ == "__main__":
	unittest.main()
