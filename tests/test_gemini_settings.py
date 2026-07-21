from __future__ import annotations

import unittest

from core.gemini.settings import (
	DEFAULT_GEMINI_MESSAGE_TEMPLATE,
	parse_gemini_link_batch,
	normalize_gemini_delivery_settings,
	validate_gemini_link,
)
from core.config.settings import normalize_settings


VALID_ONE = "https://one.google.com/activate-plan/subscription/new/token?x=1"
VALID_TWO = "https://serviceactivation.google.com/subscription/new/value#fragment"


class GeminiSettingsTest(unittest.TestCase):
	def test_normalizes_quantity_and_delay(self):
		settings = normalize_gemini_delivery_settings({"quantity": 3, "delay_seconds": 15})
		self.assertEqual(settings["quantity"], 3)
		self.assertEqual(settings["delay_seconds"], 15)

	def test_uses_defaults_for_missing_settings(self):
		settings = normalize_gemini_delivery_settings({})

		self.assertFalse(settings["enabled"])
		self.assertEqual(settings["shortage_mode"], "partial")
		self.assertEqual(settings["message_template"], DEFAULT_GEMINI_MESSAGE_TEMPLATE)

	def test_keeps_valid_settings(self):
		settings = normalize_gemini_delivery_settings({
			"enabled": True,
			"shortage_mode": "all_or_nothing",
			"message_template": "Delivery: {link}",
		})

		self.assertTrue(settings["enabled"])
		self.assertEqual(settings["shortage_mode"], "all_or_nothing")
		self.assertEqual(settings["message_template"], "Delivery: {link}")

	def test_rejects_invalid_settings(self):
		settings = normalize_gemini_delivery_settings({
			"enabled": "yes",
			"shortage_mode": "invalid",
			"message_template": "Missing placeholder",
		})

		self.assertFalse(settings["enabled"])
		self.assertEqual(settings["shortage_mode"], "partial")
		self.assertEqual(settings["message_template"], DEFAULT_GEMINI_MESSAGE_TEMPLATE)

	def test_adds_gemini_settings_to_plugin_settings(self):
		settings = normalize_settings({
			"gemini_delivery": {
				"enabled": True,
				"message_template": "Link: {link}",
			},
		})

		self.assertTrue(settings["gemini_delivery"]["enabled"])
		self.assertEqual(settings["gemini_delivery"]["message_template"], "Link: {link}")

	def test_accepts_supported_activation_urls(self):
		self.assertTrue(validate_gemini_link(VALID_ONE))
		self.assertTrue(validate_gemini_link(VALID_TWO))

	def test_requires_non_empty_suffix(self):
		self.assertFalse(validate_gemini_link(
			"https://one.google.com/activate-plan/subscription/new/",
		))
		self.assertFalse(validate_gemini_link(
			"https://serviceactivation.google.com/subscription/new/",
		))

	def test_rejects_wrong_scheme_domain_and_path(self):
		self.assertFalse(validate_gemini_link(
			"http://one.google.com/activate-plan/subscription/new/token",
		))
		self.assertFalse(validate_gemini_link(
			"https://example.com/activate-plan/subscription/new/token",
		))
		self.assertFalse(validate_gemini_link(
			"https://one.google.com/subscription/new/token",
		))

	def test_parses_batch_and_reports_invalid_lines(self):
		result = parse_gemini_link_batch(
			"\n".join((f" {VALID_ONE} ", "invalid", VALID_ONE, VALID_TWO)),
			{VALID_TWO},
		)

		self.assertEqual(result.links, (VALID_ONE,))
		self.assertEqual(result.invalid_lines, (2,))
		self.assertEqual(result.duplicate_count, 2)

	def test_ignores_blank_lines(self):
		result = parse_gemini_link_batch(f"\n{VALID_ONE}\n\n", set())

		self.assertEqual(result.links, (VALID_ONE,))
		self.assertEqual(result.invalid_lines, ())
		self.assertEqual(result.duplicate_count, 0)


if __name__ == "__main__":
	unittest.main()
