from __future__ import annotations

import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.modules.setdefault("telebot", SimpleNamespace(types=SimpleNamespace(Message=object)))

from core.pastebin.telegram import (
	TelegramPastebinFlow,
	pastebin_request_from_message,
	pastebin_text_from_message,
)


class FakeBot:
	def __init__(self):
		self.replies = []
		self.edits = []

	def reply_to(self, message, text, **kwargs):
		self.replies.append((message, text, kwargs))
		return SimpleNamespace(chat=message.chat, message_id=99)

	def edit_message_text(self, text, chat_id, message_id, **kwargs):
		self.edits.append((text, chat_id, message_id, kwargs))


class PastebinTelegramTest(unittest.TestCase):
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
