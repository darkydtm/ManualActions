from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from core.funpay.chat_sync import (
	ChatSyncTopic,
	find_chat_sync_topic,
	parse_topic_name,
	send_chat_sync_topic_message,
)


class ChatSyncBackgroundLookupTest(unittest.TestCase):
	def test_finds_topic_by_funpay_chat_id(self):
		cs = SimpleNamespace(
			ready=True,
			settings={"chat_id": -1001},
			threads={"77": 12},
			threads_info={},
		)

		with patch("core.funpay.chat_sync.get_chat_sync_obj", return_value=cs):
			topic = find_chat_sync_topic(77)

		self.assertEqual(topic, ChatSyncTopic(-1001, 12))

	def test_falls_back_to_username(self):
		cs = SimpleNamespace(
			ready=True,
			settings={"chat_id": -1001},
			threads={},
			threads_info={
				15: ("icon", "👤 buyer (88)"),
				16: ("icon", "other (99)"),
			},
		)

		with patch("core.funpay.chat_sync.get_chat_sync_obj", return_value=cs):
			topic = find_chat_sync_topic(None, "buyer")

		self.assertEqual(topic, ChatSyncTopic(-1001, 15))

	def test_username_fallback_is_case_insensitive(self):
		cs = SimpleNamespace(
			ready=True,
			settings={"chat_id": -1001},
			threads={},
			threads_info={15: ("icon", "Buyer (88)")},
		)

		with patch("core.funpay.chat_sync.get_chat_sync_obj", return_value=cs):
			topic = find_chat_sync_topic(None, "buyer")

		self.assertEqual(topic, ChatSyncTopic(-1001, 15))

	def test_returns_none_when_chat_sync_is_unavailable(self):
		with patch("core.funpay.chat_sync.get_chat_sync_obj", return_value=None):
			self.assertIsNone(find_chat_sync_topic(77, "buyer"))

	def test_returns_none_for_malformed_state(self):
		cs = SimpleNamespace(
			ready=True,
			settings={"chat_id": None},
			threads={"77": "bad"},
			threads_info={},
		)

		with patch("core.funpay.chat_sync.get_chat_sync_obj", return_value=cs):
			self.assertIsNone(find_chat_sync_topic(77, "buyer"))

	def test_sends_message_to_topic(self):
		bot = Mock()

		result = send_chat_sync_topic_message(bot, ChatSyncTopic(-1001, 12), "Warning")

		self.assertTrue(result)
		bot.send_message.assert_called_once_with(-1001, "Warning", message_thread_id=12)

	def test_reports_send_failure(self):
		bot = Mock()
		bot.send_message.side_effect = RuntimeError("offline")

		result = send_chat_sync_topic_message(bot, ChatSyncTopic(-1001, 12), "Warning")

		self.assertFalse(result)

	def test_rejects_invalid_topic_chat_id(self):
		self.assertEqual(parse_topic_name("buyer (not-a-number)"), (None, None))


if __name__ == "__main__":
	unittest.main()
