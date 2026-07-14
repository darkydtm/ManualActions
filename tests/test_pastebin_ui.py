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
tg_bot_module.CBT = SimpleNamespace(PLUGIN_SETTINGS="plugin_settings")
tg_bot_static_keyboards_module.CLEAR_STATE_BTN = lambda: None
tg_bot_utils_module.escape = lambda value: value
sys.modules.setdefault("tg_bot", tg_bot_module)
sys.modules.setdefault("tg_bot.static_keyboards", tg_bot_static_keyboards_module)
sys.modules.setdefault("tg_bot.utils", tg_bot_utils_module)

from manual_actions_core.pastebin.ui import TelegramPastebinSettingsUI


class PastebinUITest(unittest.TestCase):
	def test_preserves_account_password_spaces(self):
		ui = TelegramPastebinSettingsUI(SimpleNamespace())

		self.assertEqual(ui.clean_setting_text(" pass ", ("login_password",)), " pass ")

	def test_preserves_custom_paste_password_spaces(self):
		ui = TelegramPastebinSettingsUI(SimpleNamespace())

		self.assertEqual(ui.clean_setting_text(" secret ", ("password", "custom")), " secret ")

	def test_strips_non_password_settings(self):
		ui = TelegramPastebinSettingsUI(SimpleNamespace())

		self.assertEqual(ui.clean_setting_text(" dev ", ("api_dev_key",)), "dev")
		self.assertEqual(ui.clean_setting_text(" title ", ("title", "custom")), "title")

	def test_clear_marker_clears_password(self):
		ui = TelegramPastebinSettingsUI(SimpleNamespace())

		self.assertEqual(ui.clean_setting_text("-", ("login_password",)), "")

	def test_limits_alert_text_length(self):
		ui = TelegramPastebinSettingsUI(SimpleNamespace())

		self.assertEqual(len(ui.alert_text("x" * 220)), 180)


if __name__ == "__main__":
	unittest.main()
