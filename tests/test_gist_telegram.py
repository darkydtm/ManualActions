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

from core.constants import (
	CBT_GIST_ORDER_CANCEL,
	CBT_GIST_ORDER_SELECT,
	CBT_GIST_SEND,
	CBT_GIST_SKIP_SEND,
)
from core.gist.telegram import (
	TelegramGistFlow,
	gist_request_from_message,
	gist_text_from_message,
)


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


class FakeTelegram:
	def __init__(self):
		self.commands = []
		self.callbacks = []

	def msg_handler(self, handler, commands=None, **kwargs):
		if commands:
			self.commands.extend(commands)

	def cbq_handler(self, handler, predicate):
		self.callbacks.append((handler, predicate))


class GistTelegramTest(unittest.TestCase):
	def setUp(self):
		from core.gist import telegram as telegram_module

		telegram_module.B = FakeButton
		telegram_module.K = FakeKeyboard

	def test_registers_only_gist_command(self):
		tg = FakeTelegram()
		host = SimpleNamespace(tg=tg)

		TelegramGistFlow(host).register()

		self.assertEqual(tg.commands, ["gist"])
		self.assertNotIn("pastebin", tg.commands)

	def test_uses_command_argument_text(self):
		message = SimpleNamespace(text="/gist Body text", reply_to_message=None)

		self.assertEqual(gist_text_from_message(message), "Body text")

	def test_uses_reply_text_before_command_argument(self):
		reply = SimpleNamespace(text="Reply body", caption=None)
		message = SimpleNamespace(text="/gist Ignored", reply_to_message=reply)

		self.assertEqual(gist_text_from_message(message), "Reply body")

	def test_uses_reply_caption(self):
		reply = SimpleNamespace(text=None, caption="Caption body")
		message = SimpleNamespace(text="/gist", reply_to_message=reply)

		self.assertEqual(gist_text_from_message(message), "Caption body")

	def test_extracts_order_id_from_command_prefix(self):
		message = SimpleNamespace(text="/gist #ABC123 Body text", reply_to_message=None)

		request = gist_request_from_message(message, True)

		self.assertEqual(request.text, "Body text")
		self.assertEqual(request.order_id, "ABC123")

	def test_creates_gist_from_command_text(self):
		bot = FakeBot()
		host = SimpleNamespace(
			tgbot=bot,
			cardinal=SimpleNamespace(),
			settings={"gist": {"token": "token"}},
		)
		message = SimpleNamespace(
			text="/gist Body text",
			reply_to_message=None,
			chat=SimpleNamespace(id=1),
			is_topic_message=False,
			message_thread_id=None,
		)
		result = SimpleNamespace(url="https://gist.github.com/user/id")

		with patch("core.gist.telegram.create_gist_result", return_value=result) as create:
			TelegramGistFlow(host).cmd_gist(message)

		create.assert_called_once_with(host.settings["gist"], "Body text", filename="manual-actions.txt")
		self.assertEqual(bot.replies[0][1], "⏳ Создаю GitHub Gist...")
		self.assertIn("https://gist.github.com/user/id", bot.edits[0][0])
		self.assertIsNone(bot.edits[0][3]["reply_markup"])

	def test_creates_gist_with_order_id_filename(self):
		bot = FakeBot()
		host = SimpleNamespace(
			tgbot=bot,
			cardinal=SimpleNamespace(),
			settings={"gist": {"token": "token", "filename": {"mode": "order_id"}}},
		)
		message = SimpleNamespace(
			text="/gist #ABC123 Body text",
			reply_to_message=None,
			chat=SimpleNamespace(id=1),
			is_topic_message=False,
			message_thread_id=None,
		)

		with patch("core.gist.telegram.create_gist_result", return_value=SimpleNamespace(url="https://gist.github.com/u/id")) as create:
			TelegramGistFlow(host).cmd_gist(message)

		create.assert_called_once_with(host.settings["gist"], "Body text", filename="ABC123.txt")

	def test_selects_chat_sync_order_before_creating_gist(self):
		bot = FakeBot()
		host = SimpleNamespace(
			tgbot=bot,
			cardinal=SimpleNamespace(),
			settings={"gist": {"token": "token", "filename": {"mode": "order_id"}}},
		)
		message = SimpleNamespace(
			text="/gist Body text",
			reply_to_message=None,
			chat=SimpleNamespace(id=1),
			is_topic_message=True,
			message_thread_id=2,
		)
		context = SimpleNamespace(username="buyer", fp_chat_id=3, thread_id=2)
		orders = [SimpleNamespace(id="ABC123", price=100, currency="RUB")]
		flow = TelegramGistFlow(host)

		with (
			patch("core.gist.telegram.is_in_sync_chat", return_value=True),
			patch("core.gist.telegram.get_topic_context", return_value=context),
			patch("core.gist.telegram.get_pending_orders_for_user", return_value=orders),
			patch("core.gist.telegram.create_gist_result") as create,
		):
			flow.cmd_gist(message)

		create.assert_not_called()
		self.assertEqual(len(flow.pending_requests), 1)
		callbacks = [
			button.callback_data
			for row in bot.edits[0][3]["reply_markup"].rows
			for button in row
			if button.callback_data
		]
		self.assertTrue(any(data.startswith(CBT_GIST_ORDER_SELECT) for data in callbacks))
		self.assertTrue(any(data.startswith(CBT_GIST_ORDER_CANCEL) for data in callbacks))

	def test_creates_gist_after_selecting_order(self):
		bot = FakeBot()
		host = SimpleNamespace(
			tgbot=bot,
			cardinal=SimpleNamespace(),
			settings={"gist": {"token": "token", "filename": {"mode": "order_id"}}},
		)
		flow = TelegramGistFlow(host)
		flow.pending_requests["token"] = SimpleNamespace(
			text="Body text",
			context=SimpleNamespace(username="buyer", fp_chat_id=3),
			order_ids=("ABC123",),
		)
		call = SimpleNamespace(
			id="callback-id",
			data=f"{CBT_GIST_ORDER_SELECT}token:ABC123",
			message=SimpleNamespace(chat=SimpleNamespace(id=1), message_id=99),
		)
		result = SimpleNamespace(url="https://gist.github.com/user/id")

		with patch("core.gist.telegram.create_gist_result", return_value=result) as create:
			flow.select_order(call)

		create.assert_called_once_with(host.settings["gist"], "Body text", filename="ABC123.txt")
		callbacks = [
			button.callback_data
			for row in bot.edits[0][3]["reply_markup"].rows
			for button in row
		]
		self.assertTrue(any(data.startswith(CBT_GIST_SEND) for data in callbacks))
		self.assertTrue(any(data.startswith(CBT_GIST_SKIP_SEND) for data in callbacks))

	def test_sends_generated_link_to_funpay_chat(self):
		bot = FakeBot()
		cardinal = SimpleNamespace(send_message=lambda **kwargs: True)
		host = SimpleNamespace(tgbot=bot, cardinal=cardinal, settings={})
		flow = TelegramGistFlow(host)
		flow.pending_results["token"] = SimpleNamespace(url="https://gist.github.com/user/id", fp_chat_id=3)
		call = SimpleNamespace(
			id="callback-id",
			data=f"{CBT_GIST_SEND}token",
			message=SimpleNamespace(chat=SimpleNamespace(id=1), message_id=99, text="GitHub Gist"),
		)

		with patch.object(cardinal, "send_message", return_value=True) as send:
			flow.send_result(call)

		send.assert_called_once_with(chat_id=3, message_text="https://gist.github.com/user/id")
		self.assertIn("отправлена", bot.edits[0][0])

	def test_skips_generated_link_delivery(self):
		bot = FakeBot()
		host = SimpleNamespace(tgbot=bot, cardinal=SimpleNamespace(), settings={})
		flow = TelegramGistFlow(host)
		flow.pending_results["token"] = SimpleNamespace(url="https://gist.github.com/user/id", fp_chat_id=3)
		call = SimpleNamespace(
			id="callback-id",
			data=f"{CBT_GIST_SKIP_SEND}token",
			message=SimpleNamespace(chat=SimpleNamespace(id=1), message_id=99, text="GitHub Gist"),
		)

		flow.skip_result(call)

		self.assertIn("не отправлена", bot.edits[0][0])

	def test_reports_missing_gist_settings(self):
		bot = FakeBot()
		host = SimpleNamespace(tgbot=bot, cardinal=SimpleNamespace(), settings={})
		message = SimpleNamespace(text="/gist Body text", reply_to_message=None, chat=SimpleNamespace(id=1))

		TelegramGistFlow(host).cmd_gist(message)

		self.assertIn("GitHub Gists не настроен", bot.replies[0][1])
		self.assertIn("GitHub token", bot.replies[0][1])

	def test_reports_missing_order_id_argument(self):
		bot = FakeBot()
		host = SimpleNamespace(
			tgbot=bot,
			cardinal=SimpleNamespace(),
			settings={"gist": {"token": "token", "filename": {"mode": "order_id"}}},
		)
		message = SimpleNamespace(text="/gist Body text", reply_to_message=None, chat=SimpleNamespace(id=1))

		TelegramGistFlow(host).cmd_gist(message)

		self.assertIn("/gist #ORDER_ID", bot.replies[0][1])


if __name__ == "__main__":
	unittest.main()
