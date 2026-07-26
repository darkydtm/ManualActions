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

from core.chat_sync import ui as chat_sync_ui_module
from core.chat_sync.ui import TelegramChatSyncSettingsUI
from core.config.constants import (
	CBT_CHAT_SYNC_IMPORT,
	CBT_CHAT_SYNC_IMPORT_CONFIRM,
	CBT_CHAT_SYNC_IMPORT_SKIP,
)

from test_chat_sync_import import LEGACY_SETTINGS, LEGACY_THREADS, FakePluginStorage
from test_chat_sync_service import FakeAccount, FakeStorage, build_service


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

	def send_message(self, chat_id, text, reply_markup=None):
		self.messages.append((chat_id, text, reply_markup))
		return SimpleNamespace(id=len(self.messages))

	def edit_message_text(self, text, chat_id, message_id, reply_markup=None):
		self.edits.append((text, chat_id, message_id, reply_markup))

	def answer_callback_query(self, call_id, text=None, show_alert=False):
		self.answers.append((call_id, text, show_alert))


def callbacks_of(keyboard):
	return [button.callback_data for row in keyboard.rows for button in row]


def build_ui(legacy=True, config=None):
	storage = FakeStorage()
	storage.storage = FakePluginStorage(LEGACY_SETTINGS, LEGACY_THREADS) if legacy else FakePluginStorage()
	account = FakeAccount(chats={77: SimpleNamespace(id=77, name="buyer")})
	service, _, host = build_service(account=account, storage=storage, config=config)
	bot = FakeBot()
	host.tgbot = bot
	host.save_settings = lambda: None
	host.announcements = []
	host.send_telegram_admin_message = lambda text, keyboard=None: host.announcements.append((text, keyboard))
	return TelegramChatSyncSettingsUI(host, service), service, bot, host


def call_for(data):
	return SimpleNamespace(
		id="call",
		data=data,
		message=SimpleNamespace(chat=SimpleNamespace(id=1), id=2),
		from_user=SimpleNamespace(id=3),
	)


class ImportUITest(unittest.TestCase):
	def setUp(self):
		chat_sync_ui_module.B = FakeButton
		chat_sync_ui_module.K = FakeKeyboard

	def test_page_offers_import_when_legacy_data_exists(self):
		ui, _, bot, _ = build_ui(config={"chat_id": None})

		ui.show_page(1, None, "0", False)

		_, text, keyboard = bot.messages[0]
		self.assertIn(f"{CBT_CHAT_SYNC_IMPORT}0", callbacks_of(keyboard))
		self.assertIn("Найдены данные плагина Chat Sync", text)

	def test_page_hides_import_without_legacy_data(self):
		ui, _, bot, _ = build_ui(legacy=False)

		ui.show_page(1, None, "0", False)

		self.assertNotIn(f"{CBT_CHAT_SYNC_IMPORT}0", callbacks_of(bot.messages[0][2]))

	def test_import_asks_for_confirmation(self):
		ui, _, bot, _ = build_ui()

		ui.ask_import(call_for(f"{CBT_CHAT_SYNC_IMPORT}0"))

		text, _, _, keyboard = bot.edits[-1]
		self.assertIn("Новых тем: <b>2</b>", text)
		self.assertIn(f"{CBT_CHAT_SYNC_IMPORT_CONFIRM}0", callbacks_of(keyboard))

	def test_import_reports_when_there_is_nothing_to_do(self):
		ui, service, bot, _ = build_ui()
		service.import_legacy()
		bot.edits.clear()

		ui.ask_import(call_for(f"{CBT_CHAT_SYNC_IMPORT}0"))

		text, _, _, keyboard = bot.edits[-1]
		self.assertIn("Импортировать нечего", text)
		self.assertNotIn(f"{CBT_CHAT_SYNC_IMPORT_CONFIRM}0", callbacks_of(keyboard))

	def test_import_applies_legacy_data(self):
		ui, service, bot, host = build_ui()

		ui.run_import(1, 2, "0")

		self.assertEqual(service.threads, {"77": 5, "88": 6})
		self.assertTrue(host.settings["chat_sync"]["mono"])
		self.assertIn("Импорт завершён", bot.edits[-1][0])

	def test_failed_import_is_reported(self):
		ui, service, bot, _ = build_ui()
		service.import_legacy = broken

		ui.run_import(1, 2, "0")

		self.assertIn("❌", bot.edits[-1][0])


class LegacyAnnouncementTest(unittest.TestCase):
	def setUp(self):
		chat_sync_ui_module.B = FakeButton
		chat_sync_ui_module.K = FakeKeyboard
		self.addCleanup(
			setattr,
			chat_sync_ui_module,
			"legacy_plugin_installed",
			chat_sync_ui_module.legacy_plugin_installed,
		)

	def test_offers_the_import_only_once(self):
		ui, service, _, host = build_ui()
		chat_sync_ui_module.legacy_plugin_installed = lambda: False

		ui.send_legacy_announcement()
		ui.send_legacy_announcement()

		self.assertEqual(len(host.announcements), 1)
		text, keyboard = host.announcements[0]
		self.assertIn("Найдены данные плагина", text)
		self.assertIn(f"{CBT_CHAT_SYNC_IMPORT_CONFIRM}0", callbacks_of(keyboard))
		self.assertTrue(service.config["import_offered"])

	def test_warns_about_the_installed_plugin(self):
		ui, _, _, host = build_ui(legacy=False)
		chat_sync_ui_module.legacy_plugin_installed = lambda: True

		ui.send_legacy_announcement()

		text, keyboard = host.announcements[0]
		self.assertIn("Удалите его файл", text)
		self.assertIsNone(keyboard)

	def test_stays_quiet_when_nothing_is_found(self):
		ui, _, _, host = build_ui(legacy=False)
		chat_sync_ui_module.legacy_plugin_installed = lambda: False

		ui.send_legacy_announcement()

		self.assertEqual(host.announcements, [])

	def test_page_repeats_the_removal_warning(self):
		ui, _, bot, _ = build_ui(legacy=False)
		chat_sync_ui_module.legacy_plugin_installed = lambda: True

		ui.show_page(1, None, "0", False)

		self.assertIn("Удалите его файл", bot.messages[0][1])

	def test_skipping_the_offer_stops_further_offers(self):
		ui, service, bot, host = build_ui()

		ui.skip_import(call_for(f"{CBT_CHAT_SYNC_IMPORT_SKIP}0"))

		self.assertTrue(service.config["import_offered"])
		self.assertIn("Импорт отложен", bot.edits[-1][0])


def broken():
	raise RuntimeError("boom")


if __name__ == "__main__":
	unittest.main()
