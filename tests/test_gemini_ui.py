from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
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
tg_bot_module.CBT = SimpleNamespace(PLUGIN_SETTINGS="plugin_settings")
tg_bot_static_keyboards_module.CLEAR_STATE_BTN = lambda: None
tg_bot_utils_module.escape = lambda value: value
sys.modules.setdefault("tg_bot", tg_bot_module)
sys.modules.setdefault("tg_bot.static_keyboards", tg_bot_static_keyboards_module)
sys.modules.setdefault("tg_bot.utils", tg_bot_utils_module)
tg_bot_module.static_keyboards = tg_bot_static_keyboards_module

from core.config.constants import (
	CBT_GEMINI_EDIT_DELAY,
	CBT_GEMINI_CLEAR_CONFIRM,
	CBT_GEMINI_DELETE,
	CBT_GEMINI_DELETE_CANCEL,
	CBT_GEMINI_DELETE_CONFIRM,
	CBT_GEMINI_LINK,
	CBT_GEMINI_RETRY,
	CBT_GEMINI_SET_SHORTAGE,
	CBT_GEMINI_STOCK,
	CBT_GIST_PAGE,
)
from core.gemini import ui as gemini_ui_module
from core.gemini.service import DeliveryOutcome, OUTCOME_COMPLETED
from core.gemini.storage import GeminiDeliveryStorage, OrderReservationRequest
from core.gemini.ui import TelegramGeminiDeliveryUI
from core.gpt_accounts import ui as gpt_accounts_ui_module
from core.gpt_accounts.storage import GptAccountsDeliveryStorage
from core.gpt_accounts.ui import TelegramGptAccountsDeliveryUI
from core.config.settings import normalize_settings


LINK_ONE = "https://one.google.com/activate-plan/subscription/new/one"
LINK_TWO = "https://serviceactivation.google.com/subscription/new/two"


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
		self.rows.append(list(buttons))
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
		self.file_content = b""

	def send_message(self, chat_id, text, reply_markup=None):
		self.messages.append((chat_id, text, reply_markup))
		return SimpleNamespace(id=len(self.messages))

	def edit_message_text(self, text, chat_id, message_id, reply_markup=None):
		self.edits.append((text, chat_id, message_id, reply_markup))

	def answer_callback_query(self, call_id, text=None, show_alert=False):
		self.answers.append((call_id, text, show_alert))

	def reply_to(self, message, text, reply_markup=None):
		self.replies.append((message, text, reply_markup))

	def get_file(self, file_id):
		return SimpleNamespace(file_path=file_id)

	def download_file(self, file_path):
		return self.file_content


class FakeTelegram:
	def __init__(self):
		self.state = {}
		self.handlers = []
		self.callbacks = []
		self.cleared = []

	def msg_handler(self, handler, **kwargs):
		self.handlers.append((handler, kwargs))

	def cbq_handler(self, handler, predicate):
		self.callbacks.append((handler, predicate))

	def check_state(self, chat_id, user_id, state_id):
		return self.state.get("state") == state_id

	def set_state(self, chat_id, message_id, user_id, state_id, data):
		self.state = {"state": state_id, "data": data}

	def get_state(self, chat_id, user_id):
		return self.state

	def clear_state(self, chat_id, user_id, del_keyboard=False):
		self.cleared.append((chat_id, user_id, del_keyboard))
		self.state = {}


class GeminiDeliveryUITest(unittest.TestCase):
	def setUp(self):
		gemini_ui_module.B = FakeButton
		gemini_ui_module.K = FakeKeyboard
		self.temp_dir = TemporaryDirectory()
		self.storage = GeminiDeliveryStorage(Path(self.temp_dir.name) / "delivery.json")
		self.bot = FakeBot()
		self.tg = FakeTelegram()
		self.saved = []
		self.service = Mock()
		self.host = SimpleNamespace(
			tg=self.tg,
			tgbot=self.bot,
			settings=normalize_settings({}),
			save_settings=lambda: self.saved.append("save"),
			gemini_storage=self.storage,
			gemini_service=self.service,
		)
		self.ui = TelegramGeminiDeliveryUI(self.host)

	def tearDown(self):
		self.temp_dir.cleanup()

	def call(self, data):
		return SimpleNamespace(
			id="call",
			data=data,
			from_user=SimpleNamespace(id=3),
			message=SimpleNamespace(chat=SimpleNamespace(id=1), id=2),
		)

	def message(self, text="", document=None):
		return SimpleNamespace(
			text=text,
			document=document,
			chat=SimpleNamespace(id=1),
			from_user=SimpleNamespace(id=3),
		)

	def callbacks(self, keyboard):
		return [button.callback_data for row in keyboard.rows for button in row]

	def test_registers_states_and_callbacks(self):
		self.ui.register()

		self.assertEqual(len(self.tg.handlers), 3)
		self.assertGreaterEqual(len(self.tg.callbacks), 10)

	def test_main_page_shows_stock_and_gist_navigation(self):
		self.storage.add_links((LINK_ONE,))

		self.ui.show_page(1)

		_, text, keyboard = self.bot.messages[0]
		self.assertIn("В стоке: <b>1</b>", text)
		self.assertIn(f"{CBT_GIST_PAGE}0", self.callbacks(keyboard))

	def test_toggle_enabled_saves_setting(self):
		self.ui.toggle_enabled(self.call("ma_gemini_toggle:0"))

		self.assertTrue(self.host.settings["gemini_delivery"]["enabled"])
		self.assertEqual(self.saved, ["save"])

	def test_saves_gemini_delay(self):
		self.ui.ask_delay(self.call(f"{CBT_GEMINI_EDIT_DELAY}0"))

		self.ui.save_delay(self.message("15"))

		self.assertEqual(self.host.settings["gemini_delivery"]["delay_seconds"], 15)
		self.assertEqual(self.saved, ["save"])

	def test_rejects_invalid_gemini_delay(self):
		self.host.settings["gemini_delivery"]["delay_seconds"] = 10

		self.ui.save_delay(self.message("-1"))

		self.assertEqual(self.host.settings["gemini_delivery"]["delay_seconds"], 10)
		self.assertIn("целое число", self.bot.replies[0][1])

	def test_saves_gpt_delay(self):
		gpt_accounts_ui_module.B = FakeButton
		gpt_accounts_ui_module.K = FakeKeyboard
		gpt_storage = GptAccountsDeliveryStorage(Path(self.temp_dir.name) / "accounts.json")
		gpt_host = SimpleNamespace(
			tg=self.tg,
			tgbot=self.bot,
			settings=self.host.settings,
			save_settings=lambda: self.saved.append("save"),
			gpt_accounts_storage=gpt_storage,
			gpt_accounts_service=Mock(),
		)
		ui = TelegramGptAccountsDeliveryUI(gpt_host)

		ui.ask_delay(self.call("ma_gpt_accounts_edit_delay:0"))
		ui.save_delay(self.message("20"))

		self.assertEqual(self.host.settings["gpt_accounts_delivery"]["delay_seconds"], 20)
		self.assertEqual(self.saved, ["save"])

	def test_adds_valid_links_and_reports_invalid_and_duplicates(self):
		self.storage.add_links((LINK_TWO,))

		self.ui.save_stock(self.message(f"{LINK_ONE}\ninvalid\n{LINK_ONE}\n{LINK_TWO}"))

		self.assertEqual(self.storage.stock_links(), (LINK_TWO, LINK_ONE))
		text = self.bot.replies[0][1]
		self.assertIn("Добавлено: 1", text)
		self.assertIn("Неверные строки: 2", text)
		self.assertIn("Дубликаты: 2", text)

	def test_imports_links_from_text_document(self):
		self.bot.file_content = f"{LINK_ONE}\n{LINK_TWO}".encode()

		self.ui.save_stock(self.message(document=SimpleNamespace(file_name="links.txt", file_id="file")))

		self.assertEqual(self.storage.stock_links(), (LINK_ONE, LINK_TWO))

	def test_rejects_non_text_document(self):
		self.ui.save_stock(self.message(document=SimpleNamespace(file_name="links.csv", file_id="file")))

		self.assertEqual(self.storage.stock_links(), ())
		self.assertIn(".txt", self.bot.replies[0][1])

	def test_stock_page_uses_compact_link_payloads(self):
		self.storage.add_links((LINK_ONE, LINK_TWO))

		self.ui.show_stock_page(1)

		keyboard = self.bot.messages[0][2]
		callbacks = self.callbacks(keyboard)
		link_callbacks = [value for value in callbacks if value.startswith(CBT_GEMINI_LINK)]
		self.assertEqual(len(link_callbacks), 2)
		self.assertTrue(all(len(value) < 64 for value in link_callbacks))

	def test_opens_full_stock_link(self):
		self.storage.add_links((LINK_ONE, LINK_TWO))
		token = self.ui.stock_payloads.put(LINK_ONE)

		self.ui.show_stock_link(self.call(f"{CBT_GEMINI_LINK}{token}:0:0"))

		text, _, _, keyboard = self.bot.edits[0]
		self.assertIn(LINK_ONE, text)
		self.assertIn(f"{CBT_GEMINI_DELETE}{token}:0:0", self.callbacks(keyboard))

	def test_cancels_stock_link_deletion(self):
		self.storage.add_links((LINK_ONE, LINK_TWO))
		token = self.ui.stock_payloads.put(LINK_ONE)

		self.ui.cancel_delete_stock_item(self.call(f"{CBT_GEMINI_DELETE_CANCEL}{token}:0:0"))

		self.assertEqual(self.storage.stock_links(), (LINK_ONE, LINK_TWO))

	def test_confirms_stock_link_deletion(self):
		self.storage.add_links((LINK_ONE, LINK_TWO))
		token = self.ui.stock_payloads.put(LINK_ONE)

		self.ui.confirm_delete_stock_item(self.call(f"{CBT_GEMINI_DELETE}{token}:0:0"))

		self.assertEqual(self.storage.stock_links(), (LINK_ONE, LINK_TWO))
		self.ui.delete_stock_item(self.call(f"{CBT_GEMINI_DELETE_CONFIRM}{token}:0:0"))

		self.assertEqual(self.storage.stock_links(), (LINK_TWO,))

	def test_clear_confirmation_removes_available_stock(self):
		self.storage.add_links((LINK_ONE, LINK_TWO))

		self.ui.confirm_clear_stock(self.call(f"{CBT_GEMINI_CLEAR_CONFIRM}0"))

		self.assertEqual(self.storage.stock_count(), 0)

	def test_sets_shortage_mode(self):
		self.ui.set_shortage_mode(self.call(f"{CBT_GEMINI_SET_SHORTAGE}all_or_nothing:0"))

		self.assertEqual(
			self.host.settings["gemini_delivery"]["shortage_mode"],
			"all_or_nothing",
		)
		self.assertEqual(self.saved, ["save"])

	def test_rejects_template_without_placeholder(self):
		self.ui.save_message_template(self.message("Delivery text"))

		self.assertIn("{link}", self.bot.replies[0][1])
		self.assertEqual(self.saved, [])
		self.assertEqual(self.tg.cleared, [])

	def test_saves_template_with_placeholder(self):
		self.ui.save_message_template(self.message("Delivery: {link}"))

		self.assertEqual(
			self.host.settings["gemini_delivery"]["message_template"],
			"Delivery: {link}",
		)
		self.assertEqual(self.saved, ["save"])
		self.assertEqual(len(self.tg.cleared), 1)

	def test_lists_and_retries_waiting_order(self):
		self.storage.reserve(OrderReservationRequest("ORDER-1", 2, "buyer", 77), "partial")
		self.ui.show_waiting_page(1)
		keyboard = self.bot.messages[0][2]
		retry_callback = next(
			value
			for value in self.callbacks(keyboard)
			if value.startswith(CBT_GEMINI_RETRY)
		)
		self.service.retry_order.return_value = DeliveryOutcome(OUTCOME_COMPLETED, "ORDER-1")

		self.ui.retry_order(self.call(retry_callback))

		self.service.retry_order.assert_called_once_with("ORDER-1")
		self.assertIn("выдан", self.bot.answers[-1][1])

	def test_stock_navigation_keeps_page_and_offset(self):
		self.storage.add_links((LINK_ONE,))

		self.ui.open_stock_page(self.call(f"{CBT_GEMINI_STOCK}0:4"))

		self.assertTrue(self.bot.edits)


if __name__ == "__main__":
	unittest.main()
