from __future__ import annotations

import unittest

from core.funpay import MessageContext, should_send_auto_status_message


class FunPayStatusTest(unittest.TestCase):
	def test_allows_incoming_participant_message_when_auto_text_enabled(self):
		self.assertTrue(should_send_auto_status_message(
			MessageContext(
				text="hello",
				chat_id=123,
				chat_name="buyer",
				author="buyer",
				is_seller=False,
			),
			{
				"status": "0",
				"status_auto_messages": {
					"0": {
						"enabled": True,
						"text": "Auto reply",
					},
				},
			},
		))

	def test_rejects_seller_message(self):
		self.assertFalse(should_send_auto_status_message(
			MessageContext(
				text="hello",
				chat_id=123,
				chat_name="buyer",
				author="seller",
				is_seller=True,
			),
			self.enabled_settings(),
		))

	def test_rejects_system_message(self):
		self.assertFalse(should_send_auto_status_message(
			MessageContext(
				text="hello",
				chat_id=123,
				chat_name="buyer",
				author=None,
				is_seller=False,
				is_system=True,
			),
			self.enabled_settings(),
		))

	def test_rejects_bot_message(self):
		self.assertFalse(should_send_auto_status_message(
			MessageContext(
				text="hello",
				chat_id=123,
				chat_name="buyer",
				author="buyer",
				is_seller=False,
				is_bot=True,
			),
			self.enabled_settings(),
		))

	def test_rejects_status_command(self):
		self.assertFalse(should_send_auto_status_message(
			MessageContext(
				text="!status",
				chat_id=123,
				chat_name="buyer",
				author="buyer",
				is_seller=False,
			),
			self.enabled_settings(),
		))

	def test_rejects_disabled_auto_text(self):
		self.assertFalse(should_send_auto_status_message(
			MessageContext(
				text="hello",
				chat_id=123,
				chat_name="buyer",
				author="buyer",
				is_seller=False,
			),
			{
				"status": "0",
				"status_auto_messages": {
					"0": {
						"enabled": False,
						"text": "Auto reply",
					},
				},
			},
		))

	def enabled_settings(self):
		return {
			"status": "0",
			"status_auto_messages": {
				"0": {
					"enabled": True,
					"text": "Auto reply",
				},
			},
		}


if __name__ == "__main__":
	unittest.main()
