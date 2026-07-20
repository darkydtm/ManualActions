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

from core.plugin import ManualActionsPlugin
from core.updater import MODE_ASK, MODE_DISABLED


class FakeUpdater:
	def __init__(self):
		self.calls = []

	def stop(self):
		self.calls.append("stop")

	def start(self):
		self.calls.append("start")

	def check_manually(self):
		self.calls.append("check")
		return "result"


class PluginUpdaterTest(unittest.TestCase):
	def test_refresh_updater_restarts_active_updater(self):
		updater = FakeUpdater()
		plugin = SimpleNamespace(updater=updater, settings={"updater": {"mode": MODE_ASK}})

		ManualActionsPlugin.refresh_updater(plugin)

		self.assertEqual(updater.calls, ["stop", "start"])

	def test_refresh_updater_stops_disabled_updater(self):
		updater = FakeUpdater()
		plugin = SimpleNamespace(updater=updater, settings={"updater": {"mode": MODE_DISABLED}})

		ManualActionsPlugin.refresh_updater(plugin)

		self.assertEqual(updater.calls, ["stop"])

	def test_manual_update_check_uses_configured_updater(self):
		updater = FakeUpdater()
		plugin = SimpleNamespace(updater=updater)

		result = ManualActionsPlugin.check_updates_manually(plugin)

		self.assertEqual(result, "result")
		self.assertEqual(updater.calls, ["check"])


if __name__ == "__main__":
	unittest.main()
