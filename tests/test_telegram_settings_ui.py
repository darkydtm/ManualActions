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
if not hasattr(sys.modules["tg_bot"].CBT, "EDIT_PLUGIN"):
	sys.modules["tg_bot"].CBT.EDIT_PLUGIN = "edit_plugin"

utils_module = types.ModuleType("Utils")
utils_module.cardinal_tools = SimpleNamespace(cache_blacklist=lambda blacklist: None)
sys.modules.setdefault("Utils", utils_module)

from core import settings as settings_module
from core.constants import CBT_UPDATER_CUSTOM_INTERVAL, CBT_UPDATER_INTERVAL, CBT_UPDATER_MODE, CBT_UPDATER_PAGE
from core import telegram_settings as telegram_settings_module
from core.telegram_settings import TelegramSettingsUI
from core.updater import MODE_ASK


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
		self.set_states = []

	def check_state(self, chat_id, user_id, state_id):
		return self.state.get("state") == state_id

	def get_state(self, chat_id, user_id):
		return self.state

	def clear_state(self, chat_id, user_id, del_keyboard=False):
		self.cleared.append((chat_id, user_id, del_keyboard))
		self.state = {}

	def set_state(self, chat_id, message_id, user_id, state_id, data):
		self.set_states.append((chat_id, message_id, user_id, state_id, data))
		self.state = {"state": state_id, "data": data}


class TelegramSettingsUITest(unittest.TestCase):
	def setUp(self):
		telegram_settings_module.B = FakeButton
		telegram_settings_module.K = FakeKeyboard

	def test_settings_page_links_to_updater_page(self):
		bot = FakeBot()
		host = SimpleNamespace(tgbot=bot, settings=settings_module.normalize_settings({}))
		ui = TelegramSettingsUI(host)
		call = SimpleNamespace(
			data="plugin_settings:uuid:0",
			id="call-1",
			message=SimpleNamespace(chat=SimpleNamespace(id=1), id=2),
		)

		ui.open_settings(call)

		keyboard = bot.edits[0][3]
		callbacks = [row[0].callback_data for row in keyboard.rows]
		self.assertIn(f"{CBT_UPDATER_PAGE}0", callbacks)

	def test_set_updater_mode_saves_and_refreshes_updater(self):
		bot = FakeBot()
		events = []
		host = SimpleNamespace(
			tgbot=bot,
			settings=settings_module.normalize_settings({}),
			save_settings=lambda: events.append("save"),
			refresh_updater=lambda: events.append("refresh"),
		)
		ui = TelegramSettingsUI(host)
		call = SimpleNamespace(
			data=f"{CBT_UPDATER_MODE}{MODE_ASK}:0",
			id="call-1",
			message=SimpleNamespace(chat=SimpleNamespace(id=1), id=2),
		)

		ui.set_updater_mode(call)

		self.assertEqual(host.settings["updater"]["mode"], MODE_ASK)
		self.assertEqual(events, ["save", "refresh"])
		self.assertTrue(bot.edits)

	def test_updater_page_shows_interval_controls(self):
		bot = FakeBot()
		host = SimpleNamespace(tgbot=bot, settings=settings_module.normalize_settings({}))
		ui = TelegramSettingsUI(host)

		ui.show_updater_page(1, 2, edit=True)

		text, _, _, keyboard = bot.edits[0]
		callbacks = [row[0].callback_data for row in keyboard.rows]
		self.assertIn("<b>Интервал проверки обновлений</b>", text)
		self.assertIn("Текущий: <b>Час</b>", text)
		self.assertIn(f"{CBT_UPDATER_INTERVAL}60:0", callbacks)
		self.assertIn(f"{CBT_UPDATER_INTERVAL}1800:0", callbacks)
		self.assertIn(f"{CBT_UPDATER_INTERVAL}3600:0", callbacks)
		self.assertIn(f"{CBT_UPDATER_INTERVAL}86400:0", callbacks)
		self.assertIn(f"{CBT_UPDATER_INTERVAL}604800:0", callbacks)
		self.assertIn(f"{CBT_UPDATER_CUSTOM_INTERVAL}0", callbacks)

	def test_set_updater_interval_saves_and_refreshes_updater(self):
		bot = FakeBot()
		events = []
		host = SimpleNamespace(
			tgbot=bot,
			settings=settings_module.normalize_settings({}),
			save_settings=lambda: events.append("save"),
			refresh_updater=lambda: events.append("refresh"),
		)
		ui = TelegramSettingsUI(host)
		call = SimpleNamespace(
			data=f"{CBT_UPDATER_INTERVAL}1800:0",
			id="call-1",
			message=SimpleNamespace(chat=SimpleNamespace(id=1), id=2),
		)

		ui.set_updater_interval(call)

		self.assertEqual(host.settings["updater"]["check_interval_seconds"], 1800)
		self.assertEqual(events, ["save", "refresh"])
		self.assertEqual(bot.answers[-1], ("call-1", "Полчаса", False))
		self.assertTrue(bot.edits)

	def test_edit_custom_updater_interval_sets_state(self):
		bot = FakeBot()
		tg = FakeTelegram()
		host = SimpleNamespace(tg=tg, tgbot=bot, settings=settings_module.normalize_settings({}))
		ui = TelegramSettingsUI(host)
		call = SimpleNamespace(
			data=f"{CBT_UPDATER_CUSTOM_INTERVAL}0",
			id="call-1",
			from_user=SimpleNamespace(id=3),
			message=SimpleNamespace(chat=SimpleNamespace(id=1), id=2),
		)

		ui.edit_custom_updater_interval(call)

		self.assertEqual(tg.set_states[0][3], "ma_updater_custom_interval")
		self.assertEqual(tg.set_states[0][4], {"offset": "0"})
		self.assertIn("Введите интервал проверки обновлений", bot.messages[0][1])
		self.assertEqual(bot.answers[-1], ("call-1", None, False))

	def test_save_custom_updater_interval_saves_minutes(self):
		bot = FakeBot()
		tg = FakeTelegram({"data": {"offset": "0"}})
		events = []
		host = SimpleNamespace(
			tg=tg,
			tgbot=bot,
			settings=settings_module.normalize_settings({}),
			save_settings=lambda: events.append("save"),
			refresh_updater=lambda: events.append("refresh"),
		)
		ui = TelegramSettingsUI(host)
		message = SimpleNamespace(
			text="15",
			chat=SimpleNamespace(id=1),
			from_user=SimpleNamespace(id=3),
		)

		ui.save_custom_updater_interval(message)

		self.assertEqual(host.settings["updater"]["check_interval_seconds"], 900)
		self.assertEqual(events, ["save", "refresh"])
		self.assertEqual(tg.cleared, [(1, 3, True)])
		self.assertIn("15 мин.", bot.replies[0][1])

	def test_save_custom_updater_interval_rejects_invalid_minutes(self):
		bot = FakeBot()
		tg = FakeTelegram({"data": {"offset": "0"}})
		events = []
		host = SimpleNamespace(
			tg=tg,
			tgbot=bot,
			settings=settings_module.normalize_settings({}),
			save_settings=lambda: events.append("save"),
			refresh_updater=lambda: events.append("refresh"),
		)
		ui = TelegramSettingsUI(host)
		message = SimpleNamespace(
			text="0",
			chat=SimpleNamespace(id=1),
			from_user=SimpleNamespace(id=3),
		)

		ui.save_custom_updater_interval(message)

		self.assertEqual(host.settings["updater"]["check_interval_seconds"], 3600)
		self.assertEqual(events, [])
		self.assertEqual(tg.cleared, [])
		self.assertEqual(bot.replies[0][1], "Введите положительное число минут.")


if __name__ == "__main__":
	unittest.main()
