from __future__ import annotations

import unittest

from core.settings import normalize_settings


class ManualActionsSettingsTest(unittest.TestCase):
	def test_uses_defaults_for_missing_settings(self):
		settings = normalize_settings({})

		self.assertEqual(settings["status"], "1")
		self.assertEqual(settings["templates"], [])
		self.assertIn("0", settings["status_response_texts"])
		self.assertIn("2", settings["status_auto_messages"])
		self.assertEqual(settings["updater"]["mode"], "disabled")
		self.assertEqual(settings["updater"]["check_interval_seconds"], 3600)
		self.assertEqual(settings["updater"]["skipped_version"], "")
		self.assertEqual(settings["updater"]["installed_version"], "")
		self.assertEqual(settings["updater"]["last_checked_version"], "")

	def test_normalizes_message_templates(self):
		settings = normalize_settings({
			"templates": [
				{"id": " first ", "title": " Greeting ", "text": "Hello"},
				{"id": "first", "title": "Duplicate", "text": "Ignored"},
				{"id": "draft", "title": "Draft", "text": ""},
				{"id": "", "title": "Missing ID", "text": "Body"},
				{"id": "missing-title", "title": " ", "text": "Body"},
				{"id": "missing-text", "title": "Title"},
				"invalid",
			],
		})

		self.assertEqual(settings["templates"], [
			{"id": "first", "title": "Greeting", "text": "Hello"},
			{"id": "draft", "title": "Draft", "text": ""},
		])

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

	def test_keeps_valid_updater_settings(self):
		settings = normalize_settings({
			"updater": {
				"mode": "ask",
				"check_interval_seconds": 1800,
				"skipped_version": " 1.2.3 ",
				"installed_version": " 1.2.2 ",
				"last_checked_version": " 1.2.1 ",
			},
		})

		self.assertEqual(settings["updater"]["mode"], "ask")
		self.assertEqual(settings["updater"]["check_interval_seconds"], 1800)
		self.assertEqual(settings["updater"]["skipped_version"], "1.2.3")
		self.assertEqual(settings["updater"]["installed_version"], "1.2.2")
		self.assertEqual(settings["updater"]["last_checked_version"], "1.2.1")

	def test_rejects_invalid_updater_settings(self):
		settings = normalize_settings({
			"updater": {
				"mode": "bad",
				"check_interval_seconds": 0,
				"skipped_version": 123,
				"installed_version": None,
				"last_checked_version": [],
			},
		})

		self.assertEqual(settings["updater"]["mode"], "disabled")
		self.assertEqual(settings["updater"]["check_interval_seconds"], 3600)
		self.assertEqual(settings["updater"]["skipped_version"], "")
		self.assertEqual(settings["updater"]["installed_version"], "")
		self.assertEqual(settings["updater"]["last_checked_version"], "")


if __name__ == "__main__":
	unittest.main()
