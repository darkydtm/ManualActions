from __future__ import annotations

import unittest

from core.status import (
	InvalidStatusCommand,
	auto_message_text,
	parse_funpay_status_command,
	parse_telegram_status_command,
	response_text,
	toggle_status,
)


class StatusTest(unittest.TestCase):
	def test_parses_funpay_status_command(self):
		self.assertTrue(parse_funpay_status_command("!status"))
		self.assertTrue(parse_funpay_status_command("  !STATUS  "))

	def test_rejects_funpay_status_with_arguments(self):
		self.assertFalse(parse_funpay_status_command("!status now"))
		self.assertFalse(parse_funpay_status_command("hello !status"))

	def test_parses_telegram_status_without_argument(self):
		self.assertIsNone(parse_telegram_status_command("/status"))

	def test_parses_telegram_status_argument(self):
		self.assertEqual(parse_telegram_status_command("/status 2"), "2")
		self.assertEqual(parse_telegram_status_command("/status@bot 1"), "1")

	def test_rejects_invalid_telegram_status_argument(self):
		with self.assertRaises(InvalidStatusCommand):
			parse_telegram_status_command("/status 3")

	def test_toggles_between_zero_and_one(self):
		self.assertEqual(toggle_status("0"), "1")
		self.assertEqual(toggle_status("1"), "0")
		self.assertEqual(toggle_status("2"), "0")

	def test_builds_response_text_with_fallback(self):
		settings = {
			"status": "0",
			"status_response_texts": {"0": ""},
		}

		self.assertEqual(response_text(settings), "Текущий статус: Недоступен")

	def test_returns_enabled_auto_message_text(self):
		settings = {
			"status": "2",
			"status_auto_messages": {
				"2": {
					"enabled": True,
					"text": "Busy",
				},
			},
		}

		self.assertEqual(auto_message_text(settings), "Busy")

	def test_ignores_disabled_auto_message_text(self):
		settings = {
			"status": "2",
			"status_auto_messages": {
				"2": {
					"enabled": False,
					"text": "Busy",
				},
			},
		}

		self.assertEqual(auto_message_text(settings), "")


if __name__ == "__main__":
	unittest.main()
