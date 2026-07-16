from __future__ import annotations

import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

telebot_types_module = SimpleNamespace(
	Message=object,
	InlineKeyboardButton=object,
	InlineKeyboardMarkup=object,
)
sys.modules.setdefault("telebot", SimpleNamespace(types=telebot_types_module))
sys.modules.setdefault("telebot.types", telebot_types_module)

from core.pastebin.telegram import (
	TelegramPastebinFlow,
	pastebin_request_from_message,
	pastebin_text_from_message,
)
from core.constants import CBT_PASTEBIN_ORDER_CANCEL, CBT_PASTEBIN_ORDER_SELECT


class FakeButton:
	def __init__(self, text, callback_data=None):
		self.text = text
		self.callback_data = callback_data


class FakeKeyboard:
	def __init__(self, row_width=1):
		self.row_width = row_width
		self.rows = []

	def add(self, *buttons):
		self.rows.append(list(buttons))
		return self


class FakeBot:
	def __init__(self):
		self.replies = []
		self.edits = []
		self.callback_answers = []

	def reply_to(self, message, text, **kwargs):
		self.replies.append((message, text, kwargs))
		return SimpleNamespace(chat=message.chat, message_id=99)

	def edit_message_text(self, text, chat_id, message_id, **kwargs):
		self.edits.append((text, chat_id, message_id, kwargs))

	def answer_callback_query(self, callback_id, text=None, **kwargs):
		self.callback_answers.append((callback_id, text, kwargs))


class PastebinTelegramTest(unittest.TestCase):
	def setUp(self):
		from core.pastebin import telegram as telegram_module

		telegram_module.B = FakeButton
		telegram_module.K = FakeKeyboard

	def test_uses_command_argument_text(self):
		message = SimpleNamespace(text="/pastebin Body text", reply_to_message=None)

		self.assertEqual(pastebin_text_from_message(message), "Body text")

	def test_uses_reply_text_before_command_argument(self):
		reply = SimpleNamespace(text="Reply body", caption=None)
		message = SimpleNamespace(text="/pastebin Ignored", reply_to_message=reply)

		self.assertEqual(pastebin_text_from_message(message), "Reply body")

	def test_uses_reply_caption(self):
		reply = SimpleNamespace(text=None, caption="Caption body")
		message = SimpleNamespace(text="/pastebin", reply_to_message=reply)

		self.assertEqual(pastebin_text_from_message(message), "Caption body")

	def test_extracts_order_id_from_command_prefix(self):
		message = SimpleNamespace(text="/pastebin #ABC123 Body text", reply_to_message=None)

		request = pastebin_request_from_message(message, True)

		self.assertEqual(request.text, "Body text")
		self.assertEqual(request.order_id, "ABC123")

	def test_extracts_order_id_from_reply_command_argument(self):
		reply = SimpleNamespace(text="Reply body", caption=None)
		message = SimpleNamespace(text="/pastebin #ABC123", reply_to_message=reply)

		request = pastebin_request_from_message(message, True)

		self.assertEqual(request.text, "Reply body")
		self.assertEqual(request.order_id, "ABC123")

	def test_does_not_extract_order_id_without_marker(self):
		message = SimpleNamespace(text="/pastebin ABC123 Body text", reply_to_message=None)

		request = pastebin_request_from_message(message, True)

		self.assertEqual(request.text, "ABC123 Body text")
		self.assertEqual(request.order_id, "")

	def test_keeps_command_text_without_order_title_mode(self):
		message = SimpleNamespace(text="/pastebin #ABC123 Body text", reply_to_message=None)

		request = pastebin_request_from_message(message, False)

		self.assertEqual(request.text, "#ABC123 Body text")
		self.assertEqual(request.order_id, "")

	def test_creates_pastebin_from_command_text(self):
		bot = FakeBot()
		host = SimpleNamespace(
			tgbot=bot,
			cardinal=SimpleNamespace(),
			settings={"pastebin": {"api_dev_key": "dev"}},
		)
		message = SimpleNamespace(
			text="/pastebin Body text",
			reply_to_message=None,
			chat=SimpleNamespace(id=1),
			is_topic_message=False,
			message_thread_id=None,
		)

		result = SimpleNamespace(url="https://pastebin.com/key")
		with patch("core.pastebin.telegram.create_pastebin", return_value=result) as create:
			TelegramPastebinFlow(host).cmd_pastebin(message)

		create.assert_called_once_with(host.settings["pastebin"], "Body text", title="")
		self.assertEqual(bot.replies[0][1], "⏳ Создаю Pastebin...")
		self.assertIn("Pastebin ссылка", bot.edits[0][0])
		self.assertIn("https://pastebin.com/key", bot.edits[0][0])

	def test_creates_pastebin_with_order_id_title(self):
		bot = FakeBot()
		host = SimpleNamespace(
			tgbot=bot,
			cardinal=SimpleNamespace(),
			settings={"pastebin": {"api_dev_key": "dev", "title": {"mode": "order_id"}}},
		)
		message = SimpleNamespace(
			text="/pastebin #ABC123 Body text",
			reply_to_message=None,
			chat=SimpleNamespace(id=1),
			is_topic_message=False,
			message_thread_id=None,
		)

		result = SimpleNamespace(url="https://pastebin.com/key")
		with patch("core.pastebin.telegram.create_pastebin", return_value=result) as create:
			TelegramPastebinFlow(host).cmd_pastebin(message)

		create.assert_called_once_with(host.settings["pastebin"], "Body text", title="ABC123")

	def test_selects_chat_sync_order_before_creating_pastebin(self):
		bot = FakeBot()
		host = SimpleNamespace(
			tgbot=bot,
			cardinal=SimpleNamespace(),
			settings={"pastebin": {"api_dev_key": "dev", "title": {"mode": "order_id"}}},
		)
		message = SimpleNamespace(
			text="/pastebin Body text",
			reply_to_message=None,
			chat=SimpleNamespace(id=1),
			is_topic_message=True,
			message_thread_id=2,
		)
		context = SimpleNamespace(username="buyer", fp_chat_id=3, thread_id=2)
		orders = [
			SimpleNamespace(id="ABC123", price=100, currency="RUB"),
			SimpleNamespace(id="DEF456", price=200, currency="RUB"),
		]
		flow = TelegramPastebinFlow(host)

		with (
			patch("core.pastebin.telegram.is_in_sync_chat", return_value=True),
			patch("core.pastebin.telegram.get_topic_context", return_value=context),
			patch("core.pastebin.telegram.get_pending_orders_for_user", return_value=orders) as get_orders,
			patch("core.pastebin.telegram.create_pastebin") as create,
		):
			flow.cmd_pastebin(message)

		get_orders.assert_called_once_with(host.cardinal, "buyer")
		create.assert_not_called()
		self.assertEqual(len(flow.pending_requests), 1)
		self.assertIn("Выберите заказ", bot.edits[0][0])
		keyboard = bot.edits[0][3]["reply_markup"]
		callbacks = [button.callback_data for row in keyboard.rows for button in row if button.callback_data]
		self.assertTrue(any(data.startswith(CBT_PASTEBIN_ORDER_SELECT) for data in callbacks))
		self.assertIn(CBT_PASTEBIN_ORDER_CANCEL + next(iter(flow.pending_requests)), callbacks)
		self.assertNotIn("ABC123", callbacks)

	def test_cancels_pending_chat_sync_order_selection(self):
		bot = FakeBot()
		host = SimpleNamespace(tgbot=bot, cardinal=SimpleNamespace(), settings={})
		flow = TelegramPastebinFlow(host)
		flow.pending_requests["token"] = SimpleNamespace(text="Body text", context=SimpleNamespace(username="buyer"), order_ids=("ABC123",))
		call = SimpleNamespace(
			id="callback-id",
			data=f"{CBT_PASTEBIN_ORDER_CANCEL}token",
			message=SimpleNamespace(chat=SimpleNamespace(id=1), message_id=99),
		)

		flow.cancel_order_selection(call)

		self.assertNotIn("token", flow.pending_requests)
		self.assertEqual(bot.callback_answers[0][1], "Отменено.")
		self.assertIn("отменён", bot.edits[0][0])

	def test_creates_pastebin_after_selecting_order(self):
		bot = FakeBot()
		host = SimpleNamespace(
			tgbot=bot,
			cardinal=SimpleNamespace(),
			settings={"pastebin": {"api_dev_key": "dev", "title": {"mode": "order_id"}}},
		)
		flow = TelegramPastebinFlow(host)
		flow.pending_requests["token"] = SimpleNamespace(
			text="Body text",
			context=SimpleNamespace(username="buyer", fp_chat_id=3),
			order_ids=("ABC123",),
		)
		call = SimpleNamespace(
			id="callback-id",
			data=f"{CBT_PASTEBIN_ORDER_SELECT}token:ABC123",
			message=SimpleNamespace(chat=SimpleNamespace(id=1), message_id=99),
		)
		result = SimpleNamespace(url="https://pastebin.com/raw/key")

		with patch("core.pastebin.telegram.create_pastebin", return_value=result) as create:
			flow.select_order(call)

		create.assert_called_once_with(host.settings["pastebin"], "Body text", title="ABC123")
		self.assertNotIn("token", flow.pending_requests)
		self.assertIn(result.url, bot.edits[0][0])

	def test_reports_expired_order_selection(self):
		bot = FakeBot()
		host = SimpleNamespace(tgbot=bot, cardinal=SimpleNamespace(), settings={})
		flow = TelegramPastebinFlow(host)
		call = SimpleNamespace(
			id="callback-id",
			data=f"{CBT_PASTEBIN_ORDER_SELECT}missing:ABC123",
			message=SimpleNamespace(chat=SimpleNamespace(id=1), message_id=99),
		)

		flow.select_order(call)

		self.assertIn("истёк", bot.edits[0][0])

	def test_reports_missing_chat_sync_context_for_automatic_order_selection(self):
		bot = FakeBot()
		host = SimpleNamespace(
			tgbot=bot,
			cardinal=SimpleNamespace(),
			settings={"pastebin": {"api_dev_key": "dev", "title": {"mode": "order_id"}}},
		)
		message = SimpleNamespace(
			text="/pastebin Body text",
			reply_to_message=None,
			chat=SimpleNamespace(id=1),
			is_topic_message=True,
			message_thread_id=2,
		)

		with (
			patch("core.pastebin.telegram.is_in_sync_chat", return_value=True),
			patch("core.pastebin.telegram.get_topic_context", return_value=None),
		):
			TelegramPastebinFlow(host).cmd_pastebin(message)

		self.assertIn("определить пользователя", bot.replies[0][1])

	def test_reports_usage_without_text(self):
		bot = FakeBot()
		host = SimpleNamespace(tgbot=bot, cardinal=SimpleNamespace(), settings={"pastebin": {}})
		message = SimpleNamespace(text="/pastebin", reply_to_message=None, chat=SimpleNamespace(id=1))

		TelegramPastebinFlow(host).cmd_pastebin(message)

		self.assertIn("Использование", bot.replies[0][1])
		self.assertEqual(bot.edits, [])

	def test_reports_usage_with_missing_pastebin_settings(self):
		bot = FakeBot()
		host = SimpleNamespace(tgbot=bot, cardinal=SimpleNamespace(), settings={})
		message = SimpleNamespace(text="/pastebin", reply_to_message=None, chat=SimpleNamespace(id=1))

		TelegramPastebinFlow(host).cmd_pastebin(message)

		self.assertIn("Использование", bot.replies[0][1])
		self.assertEqual(bot.edits, [])

	def test_reports_missing_pastebin_settings_before_creating_paste(self):
		bot = FakeBot()
		host = SimpleNamespace(tgbot=bot, cardinal=SimpleNamespace(), settings={})
		message = SimpleNamespace(text="/pastebin Body text", reply_to_message=None, chat=SimpleNamespace(id=1))

		TelegramPastebinFlow(host).cmd_pastebin(message)

		self.assertIn("Pastebin не настроен", bot.replies[0][1])
		self.assertIn("API dev key", bot.replies[0][1])
		self.assertEqual(bot.edits, [])

	def test_reports_missing_order_id_title_argument(self):
		bot = FakeBot()
		host = SimpleNamespace(
			tgbot=bot,
			cardinal=SimpleNamespace(),
			settings={"pastebin": {"api_dev_key": "dev", "title": {"mode": "order_id"}}},
		)
		message = SimpleNamespace(text="/pastebin Body text", reply_to_message=None, chat=SimpleNamespace(id=1))

		TelegramPastebinFlow(host).cmd_pastebin(message)

		self.assertIn("номер заказа", bot.replies[0][1])
		self.assertIn("/pastebin #ORDER_ID", bot.replies[0][1])
		self.assertEqual(bot.edits, [])


if __name__ == "__main__":
	unittest.main()
