from __future__ import annotations

import unittest

from core.config.settings import normalize_settings


class GistSettingsTest(unittest.TestCase):
	def test_uses_defaults_for_missing_gist_settings(self):
		settings = normalize_settings({})

		self.assertEqual(settings["gist"]["token"], "")
		self.assertEqual(settings["gist"]["visibility"], "secret")
		self.assertEqual(settings["gist"]["filename"]["mode"], "off")
		self.assertEqual(settings["gist"]["filename"]["custom"], "")

	def test_keeps_valid_gist_settings(self):
		settings = normalize_settings({
			"gist": {
				"token": " token ",
				"visibility": "public",
				"filename": {
					"mode": "custom",
					"custom": " notes.md ",
				},
			},
		})

		self.assertEqual(settings["gist"]["token"], "token")
		self.assertEqual(settings["gist"]["visibility"], "public")
		self.assertEqual(settings["gist"]["filename"]["mode"], "custom")
		self.assertEqual(settings["gist"]["filename"]["custom"], "notes.md")

	def test_keeps_order_id_filename_mode(self):
		settings = normalize_settings({
			"gist": {
				"filename": {
					"mode": "order_id",
					"custom": "Ignored",
				},
			},
		})

		self.assertEqual(settings["gist"]["filename"]["mode"], "order_id")

	def test_rejects_invalid_gist_settings(self):
		settings = normalize_settings({
			"gist": {
				"token": 123,
				"visibility": "private",
				"filename": {
					"mode": "bad",
					"custom": 123,
				},
			},
		})

		self.assertEqual(settings["gist"]["token"], "")
		self.assertEqual(settings["gist"]["visibility"], "secret")
		self.assertEqual(settings["gist"]["filename"]["mode"], "off")
		self.assertEqual(settings["gist"]["filename"]["custom"], "")

	def test_ignores_unknown_legacy_settings(self):
		settings = normalize_settings({
			"legacy": {
				"token": "old",
			},
		})

		self.assertEqual(settings["gist"]["token"], "")
		self.assertNotIn("legacy", settings)

	def test_returns_independent_default_objects(self):
		first = normalize_settings({})
		second = normalize_settings({})

		first["gist"]["filename"]["custom"] = "changed.txt"

		self.assertEqual(second["gist"]["filename"]["custom"], "")


if __name__ == "__main__":
	unittest.main()
