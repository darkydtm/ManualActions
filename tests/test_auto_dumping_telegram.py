from __future__ import annotations

import sys
import types
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


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
	STATE_AUTO_DUMPING_KEYWORDS,
	STATE_AUTO_DUMPING_SELLERS,
)
from core.modules.auto_dumping.telegram import MAX_CALLBACK_PAGE, TelegramAutoDumpingFlow, validate_rule_input
from core.modules.auto_dumping.settings import normalize_rule


class FakeButton:
	def __init__(self, text, callback_data=None, url=None):
		self.text = text
		self.callback_data = callback_data
		self.url = url


class FakeKeyboard:
	def __init__(self, row_width=1):
		self.row_width = row_width
		self.rows = []

	def add(self, *buttons):
		for index in range(0, len(buttons), self.row_width):
			self.rows.append(list(buttons[index:index + self.row_width]))
		return self

	def row(self, *buttons):
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

	def _call(self, data, call_id="call"):
		return SimpleNamespace(
			id=call_id,
			data=data,
			from_user=SimpleNamespace(id=7),
			message=SimpleNamespace(chat=SimpleNamespace(id=1), id=2),
		)

	def _message(self, text, state_data=None):
		if state_data is not None:
			self.host.tg.states[7] = (state_data.pop("state", "unused"), state_data)
		return SimpleNamespace(chat=SimpleNamespace(id=1), from_user=SimpleNamespace(id=7), text=text)

	def _rule(self, rule_id, **changes):
		rule = {
			"id": rule_id,
			"enabled": True,
			"subcategory": "game",
			"keywords": ["gold"],
			"sellers_blacklist": [],
			"keywords_blacklist": [],
		}
		rule.update(changes)
		return rule

	def test_main_screen_has_only_top_level_sections(self):
		self.flow.show_main(1)

		labels = [button.text for row in self.host.tgbot.messages[0][2].rows for button in row]

		self.assertIn("Статус", labels)
		self.assertIn("Период", labels)
		self.assertIn("Правила", labels)
		self.assertIn("Запустить цикл", labels)
		self.assertNotIn("Общий чёрный список продавцов", labels)
		self.assertEqual(len(labels), 4)

	def test_status_buttons_set_explicit_state_idempotently(self):
		call = self._call(CBT_AUTO_DUMPING_STATUS + "page:1")
		self.flow.show_status(call)

		self.assertEqual(len(self.host.tgbot.edits[-1][3].rows), 2)
		self.flow.toggle(self._call(CBT_AUTO_DUMPING_STATUS + "1"))
		self.flow.toggle(self._call(CBT_AUTO_DUMPING_STATUS + "1"))

		self.assertTrue(self.host.settings["auto_dumping"]["enabled"])

	def test_fallback_keyboard_supports_explicit_rows(self):
		import importlib.util

		spec = importlib.util.spec_from_file_location(
			"core.modules.auto_dumping.telegram_fallback_test",
			"core/modules/auto_dumping/telegram.py",
		)
		module = importlib.util.module_from_spec(spec)
		with patch.dict(sys.modules, {"telebot": None, "telebot.types": None}):
			spec.loader.exec_module(module)

		keyboard = module.K()
		keyboard.row(module.B("left"), module.B("right"))

		self.assertEqual([[button.text for button in row] for row in keyboard.rows], [["left", "right"]])

	def test_status_page_callback_rejects_malformed_payload(self):
		self.flow.register()
		handler = next(handler for handler, predicate in self.host.tg.callbacks if predicate(SimpleNamespace(data=f"{CBT_AUTO_DUMPING_STATUS}payload")))

		handler(self._call(f"{CBT_AUTO_DUMPING_STATUS}page:not-a-page", "invalid"))

		self.assertEqual(self.host.tgbot.edits, [])
		self.assertEqual(self.host.tgbot.answers, [("invalid", "Некорректная страница.", True)])

	def test_status_page_callback_opens_status_screen(self):
		self.flow.register()
		handler = next(handler for handler, predicate in self.host.tg.callbacks if predicate(SimpleNamespace(data=f"{CBT_AUTO_DUMPING_STATUS}payload")))

		handler(self._call(f"{CBT_AUTO_DUMPING_STATUS}page:1", "valid"))

		self.assertEqual(len(self.host.tgbot.edits), 1)
		self.assertEqual(self.host.tgbot.answers, [("valid", None, False)])

	def test_period_screen_has_no_status_controls(self):
		self.flow.show_period(self._call(self.flow._page_callback(CBT_AUTO_DUMPING_PERIOD_PAGE, 1, None, 0)))

		labels = [button.text for row in self.host.tgbot.edits[-1][3].rows for button in row]

		self.assertIn("Своё значение", labels)
		self.assertNotIn("Включено", labels)
		self.assertNotIn("Выключено", labels)

	def test_period_page_callback_rejects_malformed_payload(self):
		self.flow.register()
		handler = next(handler for handler, predicate in self.host.tg.callbacks if predicate(SimpleNamespace(data=f"{CBT_AUTO_DUMPING_PERIOD_PAGE}payload")))

		handler(self._call(f"{CBT_AUTO_DUMPING_PERIOD_PAGE}not-a-page", "invalid"))

		self.assertEqual(self.host.tgbot.edits, [])
		self.assertEqual(self.host.tgbot.answers, [("invalid", "Некорректная страница.", True)])

	def test_period_page_callback_opens_period_screen(self):
		self.flow.register()
		handler = next(handler for handler, predicate in self.host.tg.callbacks if predicate(SimpleNamespace(data=f"{CBT_AUTO_DUMPING_PERIOD_PAGE}payload")))

		handler(self._call(self.flow._page_callback(CBT_AUTO_DUMPING_PERIOD_PAGE, 1, None, 0), "valid"))

		self.assertEqual(len(self.host.tgbot.edits), 1)
		self.assertEqual(self.host.tgbot.answers, [("valid", None, False)])

	def test_legacy_period_page_callback_rejects_malformed_payload(self):
		self.flow.register()
		handler = next(handler for handler, predicate in self.host.tg.callbacks if predicate(SimpleNamespace(data=f"{CBT_AUTO_DUMPING_INTERVAL}payload")))

		handler(self._call(f"{CBT_AUTO_DUMPING_INTERVAL}page:not-a-page", "invalid"))

		self.assertEqual(self.host.tgbot.edits, [])
		self.assertEqual(self.host.tgbot.answers, [("invalid", "Некорректная страница.", True)])

	def test_legacy_period_page_callback_opens_period_screen(self):
		self.flow.register()
		handler = next(handler for handler, predicate in self.host.tg.callbacks if predicate(SimpleNamespace(data=f"{CBT_AUTO_DUMPING_INTERVAL}payload")))

		handler(self._call(f"{CBT_AUTO_DUMPING_INTERVAL}page:1", "valid"))

		self.assertEqual(len(self.host.tgbot.edits), 1)
		self.assertEqual(self.host.tgbot.answers, [("valid", None, False)])

	def test_rules_screen_has_five_rules_and_four_navigation_buttons(self):
		self.host.settings["auto_dumping"]["rules"] = [
			{"id": str(index), "enabled": True, "subcategory": "game", "keywords": [str(index)]}
			for index in range(6)
		]
		call = self._call(self.flow._page_callback(CBT_AUTO_DUMPING_RULES_PAGE, 1, None, 0))

		self.flow.open_rules(call)

		keyboard = self.host.tgbot.edits[-1][3]
		navigation = keyboard.rows[-1]
		self.assertEqual(len(keyboard.rows) - 2, 5)
		self.assertEqual(len(navigation), 4)

	def test_rule_detail_keeps_originating_rules_page(self):
		self.host.settings["auto_dumping"]["rules"] = [
			{"id": str(index), "subcategory": "game", "keywords": [str(index)]}
			for index in range(6)
		]
		page = 1
		call = self._call(self.flow._page_callback(CBT_AUTO_DUMPING_RULES_PAGE, 1, None, page))
		self.flow.open_rules(call)
		rule_callback = self.host.tgbot.edits[-1][3].rows[0][0].callback_data

		self.flow.show_rule(self._call(rule_callback))

		labels = [button.text for row in self.host.tgbot.edits[-1][3].rows for button in row]
		callbacks = [button.callback_data for row in self.host.tgbot.edits[-1][3].rows for button in row]
		self.assertIn("Черный список", labels)
		self.assertIn(
			self.flow._page_callback(CBT_AUTO_DUMPING_RULES_PAGE, 1, None, page),
			callbacks,
		)

	def test_blacklist_screen_has_local_list_buttons(self):
		self.host.settings["auto_dumping"]["rules"] = [self._rule("rule")]
		self.flow.show_blacklist(self._call("blacklist-page"), 0, 0)

		labels = [button.text for row in self.host.tgbot.edits[-1][3].rows for button in row]

		self.assertEqual(labels[:2], ["Продавцы", "Ключевые слова"])
		self.assertIn("◀️ Назад", labels)

	def test_blacklist_items_are_paginated(self):
		rule = self._rule("rule", sellers_blacklist=[str(index) for index in range(6)])
		self.host.settings["auto_dumping"]["rules"] = [rule]

		self.flow.show_blacklist_items(self._call("blacklist-items:rule:sellers:0"), 0, "sellers", 0)

		keyboard = self.host.tgbot.edits[-1][3]
		self.assertEqual(len(keyboard.rows[-1]), 4)
		self.assertEqual(len(keyboard.rows) - 2, 5)
		self.assertTrue(all(row[0].callback_data.startswith(CBT_AUTO_DUMPING_BLACKLIST_DELETE) for row in keyboard.rows[:5]))
		self.assertEqual(self.flow._parse_blacklist_item_callback(keyboard.rows[0][0].callback_data, CBT_AUTO_DUMPING_BLACKLIST_DELETE)[:2], (0, "sellers"))

	def test_blacklist_add_stores_rule_reference_kind_and_page(self):
		self.host.settings["auto_dumping"]["rules"] = [self._rule("rule")]
		call = self._call(self.flow._page_callback(CBT_AUTO_DUMPING_BLACKLIST_ADD, 0, "keywords", 2))

		self.flow._add_blacklist(call)

		state = self.host.tg.get_state(1, 7)
		self.assertEqual(state["state"], STATE_AUTO_DUMPING_KEYWORDS)
		self.assertEqual(state["data"], {"rule_id": "rule", "rule_index": 0, "kind": "keywords", "page": 2})

	def test_save_rule_blacklist_deduplicates_case_insensitively(self):
		self.host.settings["auto_dumping"]["rules"] = [self._rule("rule", sellers_blacklist=["Existing"], keywords_blacklist=["Keep"])]
		message = self._message("Seller, seller, Other", {"rule_id": "rule", "rule_index": 0, "kind": "sellers", "page": 0})

		confirmation = self.flow.save_rule_blacklist(message)

		self.assertEqual(confirmation, "Черный список сохранен.")
		self.assertEqual(self.flow._find_rule("rule")["sellers_blacklist"], ["Seller", "Other"])
		self.assertEqual(self.flow._find_rule("rule")["keywords_blacklist"], ["Keep"])
		self.assertNotIn(7, self.host.tg.states)

	def test_save_rule_blacklist_accepts_rule_id_without_index(self):
		self.host.settings["auto_dumping"]["rules"] = [self._rule("rule")]
		message = self._message("Seller", {"rule_id": "rule", "kind": "sellers"})

		self.flow.save_rule_blacklist(message)

		self.assertEqual(self.flow._find_rule("rule")["sellers_blacklist"], ["Seller"])

	def test_blacklist_delete_removes_only_selected_item(self):
		self.host.settings["auto_dumping"]["rules"] = [self._rule("rule", sellers_blacklist=["one", "two"], keywords_blacklist=["keep"])]
		callback = self.flow._blacklist_item_callback(CBT_AUTO_DUMPING_BLACKLIST_DELETE, 0, "sellers", 0, 1)

		self.flow._delete_blacklist(self._call(callback))

		self.assertEqual(self.host.settings["auto_dumping"]["rules"][0]["sellers_blacklist"], ["one"])
		self.assertEqual(self.host.settings["auto_dumping"]["rules"][0]["keywords_blacklist"], ["keep"])

	def test_main_screen_uses_section_callbacks(self):
		self.flow.show_main(1)

		text, keyboard = self.host.tgbot.messages[0][1:]
		callbacks = [button.callback_data for row in keyboard.rows for button in row]
		self.assertIn(f"{CBT_AUTO_DUMPING_PERIOD_PAGE}1:AAAAAA", callbacks)
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

	def test_blacklist_page_uses_planned_callback_prefix(self):
		self.assertEqual(CBT_AUTO_DUMPING_BLACKLIST_PAGE, "ma_auto_dumping_blacklist_page:")

	def test_registers_page_callbacks_with_validation_handler(self):
		self.flow.register()
		page_prefixes = (
			CBT_AUTO_DUMPING_PERIOD_PAGE,
			CBT_AUTO_DUMPING_RULES_PAGE,
			CBT_AUTO_DUMPING_BLACKLIST_PAGE,
		)

		for prefix in page_prefixes:
			handlers = [handler for handler, predicate in self.host.tg.callbacks if predicate(SimpleNamespace(data=f"{prefix}payload"))]
			expected = {
				CBT_AUTO_DUMPING_PERIOD_PAGE: ["open_period"],
				CBT_AUTO_DUMPING_RULES_PAGE: ["open_rules"],
				CBT_AUTO_DUMPING_BLACKLIST_PAGE: ["_blacklist_page_callback"],
			}[prefix]
			self.assertEqual([handler.__name__ for handler in handlers], expected)

	def test_page_callback_handler_acknowledges_valid_and_invalid_data(self):
		self.flow.register()
		handler = next(handler for handler, predicate in self.host.tg.callbacks if predicate(SimpleNamespace(data=f"{CBT_AUTO_DUMPING_RULES_PAGE}context:0")))

		handler(self._call(f"{CBT_AUTO_DUMPING_RULES_PAGE}context:0", "valid"))
		handler(self._call(f"{CBT_AUTO_DUMPING_RULES_PAGE}not-a-page", "invalid"))

		self.assertEqual(self.host.tgbot.answers, [
			("valid", None, False),
			("invalid", "Некорректная страница.", True),
		])

	def test_page_slice_limits_items_to_five(self):
		items = list(range(12))
		self.assertEqual(self.flow._page_items(items, 1), (items[5:10], 3))

	def test_empty_page_still_has_one_total_page(self):
		self.assertEqual(self.flow._page_items([], 0), ([], 1))

	def test_page_callback_keeps_rule_reference_kind_and_page(self):
		data = self.flow._page_callback(CBT_AUTO_DUMPING_BLACKLIST_PAGE, 7, "sellers", 2)
		self.assertEqual(self.flow._parse_page_callback(data, CBT_AUTO_DUMPING_BLACKLIST_PAGE), (7, "sellers", 2))

	def test_blacklist_page_callbacks_fit_for_generated_and_arbitrary_ids(self):
		generated_id = normalize_rule({"subcategory": "game", "keywords": ["gold"]})["id"]
		rule_ids = (generated_id, "x" * 20)
		self.host.settings["auto_dumping"]["rules"] = [{"id": rule_id} for rule_id in rule_ids]

		for index, rule_id in enumerate(rule_ids):
			for page in (0, 123456789, MAX_CALLBACK_PAGE):
				with self.subTest(rule_id=rule_id, page=page):
					data = self.flow._page_callback(CBT_AUTO_DUMPING_BLACKLIST_PAGE, index, "keywords", page)

					self.assertLessEqual(len(data.encode("utf-8")), 64)
					self.assertEqual(self.flow._rule_id_from_reference(index), rule_id)
					self.assertEqual(self.flow._parse_page_callback(data, CBT_AUTO_DUMPING_BLACKLIST_PAGE), (index, "keywords", page))

	def test_blacklist_page_callback_resolves_reference_from_current_settings(self):
		rule_ids = ("0123456789abcdef" * 2, "x" * 20)
		self.host.settings["auto_dumping"]["rules"] = [{"id": rule_id} for rule_id in rule_ids]
		self.flow.register()
		handler = next(handler for handler, predicate in self.host.tg.callbacks if predicate(SimpleNamespace(data=f"{CBT_AUTO_DUMPING_BLACKLIST_PAGE}payload")))
		data = self.flow._page_callback(CBT_AUTO_DUMPING_BLACKLIST_PAGE, 1, "sellers", 99)

		handler(SimpleNamespace(id="valid", data=data))
		handler(SimpleNamespace(id="invalid", data=self.flow._page_callback(CBT_AUTO_DUMPING_BLACKLIST_PAGE, 2, "sellers", 0)))

		self.assertEqual(self.host.tgbot.answers[-2:], [
			("valid", None, False),
			("invalid", "Некорректная страница.", True),
		])

	def test_rule_callbacks_use_indexes_and_resolve_exact_long_ids(self):
		rule_ids = ("x" * 200, "second-rule")
		self.host.settings["auto_dumping"]["rules"] = [
			{"id": rule_id, "enabled": False, "subcategory": "game", "keywords": ["gold"]}
			for rule_id in rule_ids
		]
		call = SimpleNamespace(
			id="open",
			message=SimpleNamespace(chat=SimpleNamespace(id=1), id=2),
		)

		self.flow.open_rules(call)
		list_callbacks = [button.callback_data for row in self.host.tgbot.edits[0][3].rows for button in row]
		self.assertEqual(
			[self.flow._parse_page_callback(callback, "ma_auto_dumping_rule:") for callback in list_callbacks[:2]],
			[("0", None, 0), ("1", None, 0)],
		)
		self.assertTrue(all(len(callback.encode("utf-8")) <= 64 for callback in list_callbacks))

		self.flow.show_rule(SimpleNamespace(
			id="show",
			data="ma_auto_dumping_rule:0",
			message=call.message,
		))
		detail_callbacks = [button.callback_data for row in self.host.tgbot.edits[1][3].rows for button in row]
		self.assertEqual(
			[self.flow._parse_page_callback(detail_callbacks[index], prefix)[0::2] for index, prefix in ((0, "ma_auto_dumping_rule_toggle:"), (2, "ma_auto_dumping_rule_delete:"))],
			[("0", 0), ("0", 0)],
		)
		self.assertTrue(all(len(callback.encode("utf-8")) <= 64 for callback in detail_callbacks))

		self.flow.toggle_rule(SimpleNamespace(id="toggle", data=detail_callbacks[0], message=call.message))
		self.assertTrue(self.host.settings["auto_dumping"]["rules"][0]["enabled"])
		self.flow.delete_rule(SimpleNamespace(id="delete", data=detail_callbacks[2], message=call.message))
		self.assertEqual(self.host.settings["auto_dumping"]["rules"][0]["id"], "second-rule")

	def test_show_rule_uses_index_when_rule_ids_are_duplicate(self):
		self.host.settings["auto_dumping"]["rules"] = [
			{"id": "duplicate", "enabled": False, "subcategory": "first", "keywords": ["one"]},
			{"id": "duplicate", "enabled": True, "subcategory": "second", "keywords": ["two"]},
		]
		call = SimpleNamespace(
			id="show",
			data="ma_auto_dumping_rule:1",
			message=SimpleNamespace(chat=SimpleNamespace(id=1), id=2),
		)

		self.flow.show_rule(call)

		self.assertIn("Подкатегория: second", self.host.tgbot.edits[-1][0])

	def test_toggle_rule_uses_index_when_rule_ids_are_duplicate(self):
		self.host.settings["auto_dumping"]["rules"] = [
			{"id": "duplicate", "enabled": False},
			{"id": "duplicate", "enabled": False},
		]

		self.flow.toggle_rule(SimpleNamespace(id="toggle", data="ma_auto_dumping_rule_toggle:1", message=SimpleNamespace(chat=SimpleNamespace(id=1), id=2)))

		self.assertEqual([rule["enabled"] for rule in self.host.settings["auto_dumping"]["rules"]], [False, True])

	def test_delete_rule_uses_index_when_rule_ids_are_duplicate(self):
		self.host.settings["auto_dumping"]["rules"] = [
			{"id": "duplicate", "subcategory": "first", "keywords": ["one"]},
			{"id": "duplicate", "subcategory": "second", "keywords": ["two"]},
			{"id": "other", "subcategory": "third", "keywords": ["three"]},
		]

		self.flow.delete_rule(SimpleNamespace(id="delete", data="ma_auto_dumping_rule_delete:1", message=SimpleNamespace(chat=SimpleNamespace(id=1), id=2)))

		self.assertEqual(
			[(rule["id"], rule["subcategory"]) for rule in self.host.settings["auto_dumping"]["rules"]],
			[("duplicate", "first"), ("other", "third")],
		)

	def test_page_callback_rejects_pages_outside_callback_range(self):
		with self.assertRaises(ValueError):
			self.flow._page_callback(CBT_AUTO_DUMPING_BLACKLIST_PAGE, 0, "keywords", MAX_CALLBACK_PAGE + 1)
		with self.assertRaises(ValueError):
			self.flow._page_callback(CBT_AUTO_DUMPING_BLACKLIST_PAGE, 0, "keywords", -1)
		with self.assertRaises(ValueError):
			self.flow._page_callback(CBT_AUTO_DUMPING_BLACKLIST_PAGE, 0, "keywords", "not-a-page")
		with self.assertRaises(ValueError):
			self.flow._page_callback(CBT_AUTO_DUMPING_BLACKLIST_PAGE, 0, "keywords", 1.5)

	def test_page_callback_rejects_payloads_over_telegram_limit(self):
		with self.assertRaisesRegex(ValueError, "64-byte"):
			self.flow._page_callback("x" * 65, "context", None, 0)

	def test_page_callback_rejects_unknown_list_kind(self):
		with self.assertRaises(ValueError):
			self.flow._page_callback(CBT_AUTO_DUMPING_BLACKLIST_PAGE, 0, "unknown", 0)
		with self.assertRaises(ValueError):
			self.flow._page_callback(CBT_AUTO_DUMPING_BLACKLIST_PAGE, -1, "sellers", 0)

	def test_page_callback_rejects_invalid_page_input(self):
		for data in (
			f"{CBT_AUTO_DUMPING_BLACKLIST_PAGE}not-valid!!!",
			"not-a-callback",
		):
			with self.subTest(data=data), self.assertRaises(ValueError):
				self.flow._parse_page_callback(data, CBT_AUTO_DUMPING_BLACKLIST_PAGE)

	def test_page_slice_clamps_page_to_last_available_page(self):
		self.assertEqual(self.flow._page_items(list(range(6)), 99), ([5], 2))

	def test_page_slice_normalizes_non_finite_and_fractional_pages(self):
		items = list(range(12))
		for page in (float("nan"), float("inf"), float("-inf"), 1.5):
			with self.subTest(page=page):
				self.assertEqual(self.flow._page_items(items, page), (items[:5], 3))

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
