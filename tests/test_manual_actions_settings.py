from __future__ import annotations

import unittest

from core.settings import normalize_settings


class ManualActionsSettingsTest(unittest.TestCase):
	def test_uses_defaults_for_missing_settings(self):
		settings = normalize_settings({})

		self.assertEqual(settings["status"], "1")
		self.assertIn("0", settings["status_response_texts"])
		self.assertIn("2", settings["status_auto_messages"])

	def test_keeps_valid_status_values(self):
		settings = normalize_settings({
			"status": "2",
			"status_response_texts": {
				"2": "Custom response",
			},
			"status_auto_messages": {
				"2": {
					"enabled": True,
					"text": "Custom auto",
				},
			},
		})

		self.assertEqual(settings["status"], "2")
		self.assertEqual(settings["status_response_texts"]["2"], "Custom response")
		self.assertTrue(settings["status_auto_messages"]["2"]["enabled"])
		self.assertEqual(settings["status_auto_messages"]["2"]["text"], "Custom auto")

	def test_rejects_invalid_status_values(self):
		settings = normalize_settings({
			"status": "9",
			"status_response_texts": {
				"1": 123,
			},
			"status_auto_messages": {
				"1": {
					"enabled": "yes",
					"text": 123,
				},
			},
		})

		self.assertEqual(settings["status"], "1")
		self.assertEqual(settings["status_response_texts"]["1"], "Сейчас я доступен.")
		self.assertFalse(settings["status_auto_messages"]["1"]["enabled"])
		self.assertEqual(settings["status_auto_messages"]["1"]["text"], "")


if __name__ == "__main__":
	unittest.main()
