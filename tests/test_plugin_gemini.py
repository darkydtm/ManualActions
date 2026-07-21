from __future__ import annotations

import sys
import types
import unittest
from types import SimpleNamespace
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
tg_bot_module.CBT = SimpleNamespace(PLUGIN_SETTINGS="plugin_settings", EDIT_PLUGIN="edit_plugin")
tg_bot_static_keyboards_module.CLEAR_STATE_BTN = lambda: None
tg_bot_utils_module.escape = lambda value: value
sys.modules.setdefault("tg_bot", tg_bot_module)
sys.modules.setdefault("tg_bot.static_keyboards", tg_bot_static_keyboards_module)
sys.modules.setdefault("tg_bot.utils", tg_bot_utils_module)
sys.modules["tg_bot"].static_keyboards = sys.modules["tg_bot.static_keyboards"]

utils_module = types.ModuleType("Utils")
utils_module.cardinal_tools = SimpleNamespace(cache_blacklist=lambda blacklist: None)
sys.modules.setdefault("Utils", utils_module)

from core.constants import UUID
from core.plugin import ManualActionsPlugin


class PluginGeminiIntegrationTest(unittest.TestCase):
	def setUp(self):
		ManualActionsPlugin._instance = None
		self.cardinal = SimpleNamespace(
			telegram=None,
			new_message_handlers=[],
			last_chat_message_changed_handlers=[],
			new_order_handlers=[],
		)

	def tearDown(self):
		ManualActionsPlugin._instance = None

	def test_constructs_gemini_components_before_telegram_ui(self):
		plugin = ManualActionsPlugin(self.cardinal)

		self.assertIsNotNone(plugin.gemini_storage)
		self.assertIsNotNone(plugin.gemini_service)
		self.assertIs(plugin.telegram_ui.gemini_ui.host, plugin)
		self.assertIsNotNone(plugin.two_factor_storage)
		self.assertIsNotNone(plugin.two_factor_service)

	def test_registers_new_order_hook(self):
		plugin = ManualActionsPlugin(self.cardinal)

		plugin.register()

		self.assertEqual(self.cardinal.new_order_handlers, [plugin.new_order_hook])
		self.assertEqual(getattr(ManualActionsPlugin.new_order_hook, "plugin_uuid"), UUID)

	def test_new_order_hook_delegates_to_service(self):
		plugin = ManualActionsPlugin(self.cardinal)
		plugin.gemini_service = Mock()
		plugin.two_factor_service = Mock()
		event = object()

		plugin.new_order_hook(self.cardinal, event)

		plugin.gemini_service.handle_new_order.assert_called_once_with(event)
		plugin.two_factor_service.handle_new_order.assert_not_called()

	def test_new_order_hook_logs_unexpected_error_without_raising(self):
		plugin = ManualActionsPlugin(self.cardinal)
		plugin.gemini_service = Mock()
		plugin.two_factor_service = Mock()
		plugin.gemini_service.handle_new_order.side_effect = RuntimeError("failed")

		plugin.new_order_hook(self.cardinal, object())


if __name__ == "__main__":
	unittest.main()
