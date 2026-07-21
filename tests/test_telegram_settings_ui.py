from __future__ import annotations

from html import escape as html_escape
import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import patch


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
tg_bot_utils_module.escape = html_escape
sys.modules.setdefault("tg_bot", tg_bot_module)
sys.modules.setdefault("tg_bot.static_keyboards", tg_bot_static_keyboards_module)
sys.modules.setdefault("tg_bot.utils", tg_bot_utils_module)
sys.modules["tg_bot"].static_keyboards = sys.modules["tg_bot.static_keyboards"]
if not hasattr(sys.modules["tg_bot"].CBT, "EDIT_PLUGIN"):
	sys.modules["tg_bot"].CBT.EDIT_PLUGIN = "edit_plugin"

utils_module = types.ModuleType("Utils")
utils_module.cardinal_tools = SimpleNamespace(cache_blacklist=lambda blacklist: None)
sys.modules.setdefault("Utils", utils_module)

from core.config import settings as settings_module
from core.config.constants import (
	CBT_GIST_PAGE,
	CBT_TEMPLATE_ADD,
	CBT_TEMPLATE_DELETE,
	CBT_TEMPLATE_DELETE_CANCEL,
	CBT_TEMPLATE_DELETE_CONFIRM,
	CBT_TEMPLATE_DETAIL,
	CBT_TEMPLATE_EDIT_TEXT,
	CBT_TEMPLATE_EDIT_TITLE,
	CBT_TEMPLATES_PAGE,
	CBT_UPDATER_CUSTOM_INTERVAL,
	CBT_UPDATER_CHECK,
	CBT_UPDATER_INTERVAL_PAGE,
	CBT_UPDATER_INTERVAL,
	CBT_UPDATER_MODE_PAGE,
	CBT_UPDATER_MODE,
	CBT_UPDATER_PAGE,
	STATE_TEMPLATE_CREATE_TEXT,
	VERSION,
)
from core.telegram import settings as telegram_settings_module
from core.telegram.settings import TelegramSettingsUI
from core.application.updater import MODE_ASK


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
		telegram_settings_module.escape = html_escape

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
		self.assertIn(f"{CBT_GIST_PAGE}0", callbacks)
		self.assertIn(f"{CBT_TEMPLATES_PAGE}0", callbacks)

	def test_settings_page_shows_version_and_last_checked_release(self):
		bot = FakeBot()
		host = SimpleNamespace(
			tgbot=bot,
			settings=settings_module.normalize_settings({
				"updater": {"last_checked_version": "1.5.0"},
			}),
		)
		ui = TelegramSettingsUI(host)
		call = SimpleNamespace(
			data="plugin_settings:uuid:0",
			id="call-1",
			message=SimpleNamespace(chat=SimpleNamespace(id=1), id=2),
		)

		ui.open_settings(call)

		text = bot.edits[0][0]
		self.assertIn(f"Версия: <code>{VERSION}</code>", text)
		self.assertIn("Последняя проверка обновлений: <code>1.5.0</code>", text)

	def test_templates_page_lists_saved_titles(self):
		bot = FakeBot()
		host = SimpleNamespace(
			tgbot=bot,
			settings=settings_module.normalize_settings({
				"templates": [{"id": "one", "title": "Greeting", "text": "Hello"}],
			}),
		)
		ui = TelegramSettingsUI(host)

		ui.show_templates_page(1, 2, edit=True)

		text, _, _, keyboard = bot.edits[0]
		self.assertIn("Всего: <b>1</b>", text)
		self.assertEqual(keyboard.rows[1][0].text, "Greeting")
		self.assertEqual(keyboard.rows[1][0].callback_data, f"{CBT_TEMPLATE_DETAIL}one:0")

	def test_template_detail_escapes_and_previews_content(self):
		bot = FakeBot()
		host = SimpleNamespace(
			tgbot=bot,
			settings=settings_module.normalize_settings({
				"templates": [{"id": "one", "title": "<Title>", "text": "<Body>"}],
			}),
		)
		ui = TelegramSettingsUI(host)

		ui.show_template_detail(1, 2, "one", edit=True)

		text, _, _, keyboard = bot.edits[0]
		callbacks = [row[0].callback_data for row in keyboard.rows]
		self.assertIn("&lt;Title&gt;", text)
		self.assertIn("&lt;Body&gt;", text)
		self.assertIn(f"{CBT_TEMPLATE_EDIT_TITLE}one:0", callbacks)
		self.assertIn(f"{CBT_TEMPLATE_EDIT_TEXT}one:0", callbacks)
		self.assertIn(f"{CBT_TEMPLATE_DELETE}one:0", callbacks)

	def test_create_template_collects_title_then_text(self):
		bot = FakeBot()
		tg = FakeTelegram({"data": {"offset": "0"}})
		host = SimpleNamespace(
			tg=tg,
			tgbot=bot,
			settings=settings_module.normalize_settings({}),
		)
		ui = TelegramSettingsUI(host)
		message = SimpleNamespace(
			text=" Greeting ",
			chat=SimpleNamespace(id=1),
			from_user=SimpleNamespace(id=3),
		)

		ui.save_template_create_title(message)

		self.assertEqual(tg.set_states[-1][3], STATE_TEMPLATE_CREATE_TEXT)
		self.assertEqual(tg.set_states[-1][4], {"title": "Greeting", "offset": "0"})

	def test_create_template_saves_title_and_text(self):
		bot = FakeBot()
		tg = FakeTelegram({"data": {"title": "Greeting", "offset": "0"}})
		events = []
		host = SimpleNamespace(
			tg=tg,
			tgbot=bot,
			settings=settings_module.normalize_settings({}),
			save_settings=lambda: events.append("save"),
		)
		ui = TelegramSettingsUI(host)
		message = SimpleNamespace(
			text="Hello buyer",
			chat=SimpleNamespace(id=1),
			from_user=SimpleNamespace(id=3),
		)

		with patch("core.telegram.settings.uuid4") as uuid4:
			uuid4.return_value.hex = "new-template"
			ui.save_template_create_text(message)

		self.assertEqual(host.settings["templates"], [{
			"id": "new-template",
			"title": "Greeting",
			"text": "Hello buyer",
		}])
		self.assertEqual(events, ["save"])

	def test_rejects_empty_template_title_without_clearing_state(self):
		bot = FakeBot()
		tg = FakeTelegram({"data": {"offset": "0"}})
		host = SimpleNamespace(tg=tg, tgbot=bot, settings=settings_module.normalize_settings({}))
		ui = TelegramSettingsUI(host)
		message = SimpleNamespace(text=" ", chat=SimpleNamespace(id=1), from_user=SimpleNamespace(id=3))

		ui.save_template_create_title(message)

		self.assertEqual(tg.cleared, [])
		self.assertEqual(tg.set_states, [])
		self.assertIn("не может быть пустым", bot.replies[0][1])

	def test_edits_template_title(self):
		bot = FakeBot()
		tg = FakeTelegram({"data": {"template_id": "one", "offset": "0"}})
		events = []
		host = SimpleNamespace(
			tg=tg,
			tgbot=bot,
			settings=settings_module.normalize_settings({
				"templates": [{"id": "one", "title": "Old", "text": "Body"}],
			}),
			save_settings=lambda: events.append("save"),
		)
		ui = TelegramSettingsUI(host)
		message = SimpleNamespace(text=" New ", chat=SimpleNamespace(id=1), from_user=SimpleNamespace(id=3))

		ui.save_template_title(message)

		self.assertEqual(host.settings["templates"][0]["title"], "New")
		self.assertEqual(events, ["save"])

	def test_edits_template_text_and_allows_clearing(self):
		bot = FakeBot()
		tg = FakeTelegram({"data": {"template_id": "one", "offset": "0"}})
		events = []
		host = SimpleNamespace(
			tg=tg,
			tgbot=bot,
			settings=settings_module.normalize_settings({
				"templates": [{"id": "one", "title": "Title", "text": "Body"}],
			}),
			save_settings=lambda: events.append("save"),
		)
		ui = TelegramSettingsUI(host)
		message = SimpleNamespace(text="-", chat=SimpleNamespace(id=1), from_user=SimpleNamespace(id=3))

		ui.save_template_text(message)

		self.assertEqual(host.settings["templates"][0]["text"], "")
		self.assertEqual(events, ["save"])

	def test_delete_template_requires_confirmation(self):
		bot = FakeBot()
		host = SimpleNamespace(
			tgbot=bot,
			settings=settings_module.normalize_settings({
				"templates": [{"id": "one", "title": "Greeting", "text": "Body"}],
			}),
		)
		ui = TelegramSettingsUI(host)
		call = SimpleNamespace(
			data=f"{CBT_TEMPLATE_DELETE}one:0",
			id="call-1",
			message=SimpleNamespace(chat=SimpleNamespace(id=1), id=2),
		)

		ui.delete_template(call)

		callbacks = [button.callback_data for row in bot.edits[0][3].rows for button in row]
		self.assertIn(f"{CBT_TEMPLATE_DELETE_CONFIRM}one:0", callbacks)
		self.assertIn(f"{CBT_TEMPLATE_DELETE_CANCEL}one:0", callbacks)

	def test_confirms_template_deletion(self):
		bot = FakeBot()
		events = []
		host = SimpleNamespace(
			tgbot=bot,
			settings=settings_module.normalize_settings({
				"templates": [{"id": "one", "title": "Greeting", "text": "Body"}],
			}),
			save_settings=lambda: events.append("save"),
		)
		ui = TelegramSettingsUI(host)
		call = SimpleNamespace(
			data=f"{CBT_TEMPLATE_DELETE_CONFIRM}one:0",
			id="call-1",
			message=SimpleNamespace(chat=SimpleNamespace(id=1), id=2),
		)

		ui.confirm_template_delete(call)

		self.assertEqual(host.settings["templates"], [])
		self.assertEqual(events, ["save"])

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
		self.assertIn("<b>Автообновление</b>", text)
		self.assertIn(f"{CBT_UPDATER_MODE_PAGE}0", callbacks)
		self.assertIn(f"{CBT_UPDATER_INTERVAL_PAGE}0", callbacks)
		self.assertIn(f"{CBT_UPDATER_CHECK}0", callbacks)
		self.assertNotIn("Текущая версия", text)

	def test_manual_update_check_shows_result(self):
		bot = FakeBot()
		host = SimpleNamespace(
			tgbot=bot,
			settings=settings_module.normalize_settings({}),
			check_updates_manually=lambda: SimpleNamespace(
				message="not_new",
				release=None,
			),
		)
		ui = TelegramSettingsUI(host)
		call = SimpleNamespace(
			data=f"{CBT_UPDATER_CHECK}0",
			id="call-1",
			message=SimpleNamespace(chat=SimpleNamespace(id=1), id=2),
		)

		ui.check_updates(call)

		self.assertEqual(bot.answers[-1], ("call-1", "✅ Новых обновлений нет.", True))

	def test_updater_mode_page_shows_mode_controls(self):
		bot = FakeBot()
		host = SimpleNamespace(tgbot=bot, settings=settings_module.normalize_settings({}))
		ui = TelegramSettingsUI(host)

		ui.show_updater_mode_page(1, 2, edit=True)

		text, _, _, keyboard = bot.edits[0]
		callbacks = [row[0].callback_data for row in keyboard.rows]
		self.assertIn("<b>Режим обновления</b>", text)
		self.assertIn(f"{CBT_UPDATER_MODE}enabled:0", callbacks)
		self.assertIn(f"{CBT_UPDATER_MODE}disabled:0", callbacks)
		self.assertIn(f"{CBT_UPDATER_MODE}ask:0", callbacks)
		self.assertIn(f"{CBT_UPDATER_PAGE}0", callbacks)

	def test_updater_interval_page_shows_interval_controls(self):
		bot = FakeBot()
		host = SimpleNamespace(tgbot=bot, settings=settings_module.normalize_settings({}))
		ui = TelegramSettingsUI(host)

		ui.show_updater_interval_page(1, 2, edit=True)

		text, _, _, keyboard = bot.edits[0]
		callbacks = [row[0].callback_data for row in keyboard.rows]
		self.assertIn("<b>Интервал проверки</b>", text)
		self.assertIn("Текущий: <b>Час</b>", text)
		self.assertIn(f"{CBT_UPDATER_INTERVAL}60:0", callbacks)
		self.assertIn(f"{CBT_UPDATER_INTERVAL}1800:0", callbacks)
		self.assertIn(f"{CBT_UPDATER_INTERVAL}3600:0", callbacks)
		self.assertIn(f"{CBT_UPDATER_INTERVAL}86400:0", callbacks)
		self.assertIn(f"{CBT_UPDATER_INTERVAL}604800:0", callbacks)
		self.assertIn(f"{CBT_UPDATER_CUSTOM_INTERVAL}0", callbacks)
		self.assertIn(f"{CBT_UPDATER_PAGE}0", callbacks)

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
