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

from core import settings as settings_module
from core.constants import (
	CBT_GIST_FILENAME_PAGE,
	CBT_GIST_SET_FILENAME_MODE,
	CBT_GIST_SET_VISIBILITY,
	CBT_GIST_TOKEN_PAGE,
	CBT_GIST_VISIBILITY_PAGE,
)
from core.gist import ui as gist_ui_module
from core.gist.ui import TelegramGistSettingsUI


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
		self.edits = []
		self.answers = []
		self.replies = []

	def send_message(self, chat_id, text, reply_markup=None):
		self.messages.append((chat_id, text, reply_markup))
		return SimpleNamespace(id=len(self.messages))

	def edit_message_text(self, text, chat_id, message_id, reply_markup=None):
		self.edits.append((text, chat_id, message_id, reply_markup))

	def answer_callback_query(self, call_id, text=None, show_alert=False):
		self.answers.append((call_id, text, show_alert))

	def reply_to(self, message, text, reply_markup=None):
		self.replies.append((message, text, reply_markup))


class FakeTelegram:
	def __init__(self, state=None):
		self.state = state or {}
		self.cleared = []

	def get_state(self, chat_id, user_id):
		return self.state

	def clear_state(self, chat_id, user_id, del_keyboard=False):
		self.cleared.append((chat_id, user_id, del_keyboard))


class GistUITest(unittest.TestCase):
	def setUp(self):
		gist_ui_module.B = FakeButton
		gist_ui_module.K = FakeKeyboard

	def test_main_page_links_to_gist_categories(self):
		bot = FakeBot()
		host = SimpleNamespace(tgbot=bot, settings=settings_module.normalize_settings({}))
		ui = TelegramGistSettingsUI(host)

		ui.show_page(1)

		_, text, keyboard = bot.messages[0]
		callbacks = [row[0].callback_data for row in keyboard.rows]
		self.assertIn("Token: <b>не задан</b>", text)
		self.assertIn(f"{CBT_GIST_TOKEN_PAGE}0", callbacks)
		self.assertIn(f"{CBT_GIST_VISIBILITY_PAGE}0", callbacks)
		self.assertIn(f"{CBT_GIST_FILENAME_PAGE}0", callbacks)

	def test_filename_page_includes_order_id_mode(self):
		bot = FakeBot()
		host = SimpleNamespace(tgbot=bot, settings=settings_module.normalize_settings({}))
		ui = TelegramGistSettingsUI(host)

		ui.show_filename_page(1)

		keyboard = bot.messages[0][2]
		callbacks = [button.callback_data for row in keyboard.rows for button in row]
		self.assertIn(f"{CBT_GIST_SET_FILENAME_MODE}order_id:0", callbacks)

	def test_set_visibility_saves_public_value(self):
		bot = FakeBot()
		events = []
		host = SimpleNamespace(
			tgbot=bot,
			settings=settings_module.normalize_settings({}),
			save_settings=lambda: events.append("save"),
		)
		ui = TelegramGistSettingsUI(host)
		call = SimpleNamespace(
			id="call",
			data=f"{CBT_GIST_SET_VISIBILITY}public:0",
			message=SimpleNamespace(chat=SimpleNamespace(id=1), id=2),
		)

		ui.set_visibility(call)

		self.assertEqual(host.settings["gist"]["visibility"], "public")
		self.assertEqual(events, ["save"])

	def test_set_filename_mode_saves_order_id(self):
		bot = FakeBot()
		events = []
		host = SimpleNamespace(
			tgbot=bot,
			settings=settings_module.normalize_settings({}),
			save_settings=lambda: events.append("save"),
		)
		ui = TelegramGistSettingsUI(host)
		call = SimpleNamespace(
			id="call",
			data=f"{CBT_GIST_SET_FILENAME_MODE}order_id:0",
			message=SimpleNamespace(chat=SimpleNamespace(id=1), id=2),
		)

		ui.set_filename_mode(call)

		self.assertEqual(host.settings["gist"]["filename"]["mode"], "order_id")
		self.assertEqual(events, ["save"])

	def test_saves_token_without_rendering_value(self):
		bot = FakeBot()
		tg = FakeTelegram({"data": {"offset": "0", "back_page": CBT_GIST_TOKEN_PAGE}})
		host = SimpleNamespace(
			tg=tg,
			tgbot=bot,
			settings=settings_module.normalize_settings({}),
			save_settings=lambda: None,
		)
		ui = TelegramGistSettingsUI(host)
		message = SimpleNamespace(
			text=" secret-token ",
			chat=SimpleNamespace(id=1),
			from_user=SimpleNamespace(id=2),
		)

		ui.save_token(message)
		ui.show_token_page(1)

		self.assertEqual(host.settings["gist"]["token"], "secret-token")
		self.assertNotIn("secret-token", bot.messages[0][1])
		self.assertIn("Token: <b>задан</b>", bot.messages[0][1])

	def test_saves_custom_filename(self):
		bot = FakeBot()
		tg = FakeTelegram({"data": {"offset": "0", "back_page": CBT_GIST_FILENAME_PAGE}})
		host = SimpleNamespace(
			tg=tg,
			tgbot=bot,
			settings=settings_module.normalize_settings({}),
			save_settings=lambda: None,
		)
		ui = TelegramGistSettingsUI(host)
		message = SimpleNamespace(
			text=" notes.md ",
			chat=SimpleNamespace(id=1),
			from_user=SimpleNamespace(id=2),
		)

		ui.save_custom_filename(message)

		self.assertEqual(host.settings["gist"]["filename"]["custom"], "notes.md")


if __name__ == "__main__":
	unittest.main()
