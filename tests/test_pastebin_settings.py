from __future__ import annotations

import unittest

from manual_actions_core.settings import normalize_settings


class PastebinSettingsTest(unittest.TestCase):
	def test_uses_defaults_for_missing_pastebin_settings(self):
		settings = normalize_settings({})

		self.assertEqual(settings["pastebin"]["api_dev_key"], "")
		self.assertEqual(settings["pastebin"]["api_user_key"], "")
		self.assertEqual(settings["pastebin"]["expire_date"], "N")
		self.assertEqual(settings["pastebin"]["folder_key"], "")
		self.assertEqual(settings["pastebin"]["title"]["mode"], "off")
		self.assertEqual(settings["pastebin"]["title"]["custom"], "")

	def test_keeps_valid_pastebin_settings(self):
		settings = normalize_settings({
			"pastebin": {
				"api_dev_key": " dev ",
				"api_user_key": " user ",
				"expire_date": "1W",
				"folder_key": " folder ",
				"title": {
					"mode": "custom",
					"custom": " Client title ",
				},
			},
		})

		self.assertEqual(settings["pastebin"]["api_dev_key"], "dev")
		self.assertEqual(settings["pastebin"]["api_user_key"], "user")
		self.assertEqual(settings["pastebin"]["expire_date"], "1W")
		self.assertEqual(settings["pastebin"]["folder_key"], "folder")
		self.assertEqual(settings["pastebin"]["title"]["mode"], "custom")
		self.assertEqual(settings["pastebin"]["title"]["custom"], "Client title")

	def test_rejects_invalid_pastebin_settings(self):
		settings = normalize_settings({
			"pastebin": {
				"api_dev_key": 123,
				"api_user_key": None,
				"expire_date": "bad",
				"folder_key": [],
				"title": {
					"mode": "bad",
					"custom": 123,
				},
			},
		})

		self.assertEqual(settings["pastebin"]["api_dev_key"], "")
		self.assertEqual(settings["pastebin"]["api_user_key"], "")
		self.assertEqual(settings["pastebin"]["expire_date"], "N")
		self.assertEqual(settings["pastebin"]["folder_key"], "")
		self.assertEqual(settings["pastebin"]["title"]["mode"], "off")
		self.assertEqual(settings["pastebin"]["title"]["custom"], "")


if __name__ == "__main__":
	unittest.main()

