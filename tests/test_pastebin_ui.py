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

from manual_actions_core import settings as settings_module
from manual_actions_core.constants import (
	CBT_PASTEBIN_ACCOUNT_PAGE,
	CBT_PASTEBIN_PASSWORD_PAGE,
	CBT_PASTEBIN_PUBLISH_PAGE,
	CBT_PASTEBIN_SET_TITLE_MODE,
	CBT_PASTEBIN_TITLE_PAGE,
)
from manual_actions_core.pastebin import ui as pastebin_ui_module
from manual_actions_core.pastebin.ui import TelegramPastebinSettingsUI


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
		for button in buttons:
			self.rows.append([button])
		return self

	def row(self, *buttons):
		self.rows.append(list(buttons))
		return self


class FakeBot:
	def __init__(self):
		self.messages = []

	def send_message(self, chat_id, text, reply_markup=None):
		self.messages.append((chat_id, text, reply_markup))


class PastebinUITest(unittest.TestCase):
	def setUp(self):
		pastebin_ui_module.B = FakeButton
		pastebin_ui_module.K = FakeKeyboard

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

	def test_main_page_links_to_pastebin_categories(self):
		bot = FakeBot()
		host = SimpleNamespace(tgbot=bot, settings=settings_module.normalize_settings({}))
		ui = TelegramPastebinSettingsUI(host)

		ui.show_page(1)

		keyboard = bot.messages[0][2]
		callbacks = [row[0].callback_data for row in keyboard.rows]
		self.assertIn(f"{CBT_PASTEBIN_ACCOUNT_PAGE}0", callbacks)
		self.assertIn(f"{CBT_PASTEBIN_PUBLISH_PAGE}0", callbacks)
		self.assertIn(f"{CBT_PASTEBIN_TITLE_PAGE}0", callbacks)
		self.assertIn(f"{CBT_PASTEBIN_PASSWORD_PAGE}0", callbacks)

	def test_title_page_includes_order_id_mode(self):
		bot = FakeBot()
		host = SimpleNamespace(tgbot=bot, settings=settings_module.normalize_settings({}))
		ui = TelegramPastebinSettingsUI(host)

		ui.show_title_page(1)

		keyboard = bot.messages[0][2]
		callbacks = [button.callback_data for row in keyboard.rows for button in row]
		self.assertIn(f"{CBT_PASTEBIN_SET_TITLE_MODE}order_id:0", callbacks)


if __name__ == "__main__":
	unittest.main()
