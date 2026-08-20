from __future__ import annotations

import unittest

from core.config.settings import normalize_settings
from core.modules.auto_dumping.models import DumpingRule
from core.modules.auto_dumping.settings import normalize_auto_dumping_settings


class AutoDumpingSettingsTest(unittest.TestCase):
	def test_defaults_to_disabled_five_minutes_and_no_rules(self):
		settings = normalize_auto_dumping_settings({})

		self.assertFalse(settings["enabled"])
		self.assertEqual(settings["interval_minutes"], 5)
		self.assertEqual(settings["rules"], [])

	def test_normalizes_valid_rule_and_drops_invalid_rules(self):
		settings = normalize_auto_dumping_settings({
			"enabled": True,
			"interval_minutes": 3,
			"global_sellers_blacklist": [" Seller ", "seller", 42],
			"global_keywords_blacklist": ["beta", "Beta", ""],
			"rules": [{
				"id": " rule-1 ",
				"subcategory": " Game ",
				"keywords": ["gold", "gold", " "],
				"keyword_mode": "all",
				"competitor_min_price": 10.5,
				"price_mode": "percent",
				"dumping_value": 5,
				"own_min_price": 3,
				"sellers_blacklist": ["bad"],
				"keywords_blacklist": ["beta"],
			}, {"subcategory": "", "keywords": []}],
		})

		self.assertEqual(settings["global_sellers_blacklist"], ["Seller"])
		self.assertEqual(settings["global_keywords_blacklist"], ["beta"])
		self.assertEqual(len(settings["rules"]), 1)
		self.assertEqual(settings["rules"][0]["id"], "rule-1")
		self.assertEqual(DumpingRule.from_dict(settings["rules"][0]).keyword_mode, "all")

	def test_rejects_duplicate_rule_keywords_in_one_subcategory(self):
		settings = normalize_auto_dumping_settings({
			"rules": [
				{"id": "one", "subcategory": "game", "keywords": ["gold"]},
				{"id": "two", "subcategory": "game", "keywords": [" GOLD "]},
			],
		})

		self.assertEqual([rule["id"] for rule in settings["rules"]], ["one"])

	def test_normalize_settings_includes_auto_dumping_section(self):
		settings = normalize_settings({"auto_dumping": {"enabled": True, "interval_minutes": 10}})

		self.assertTrue(settings["auto_dumping"]["enabled"])
		self.assertEqual(settings["auto_dumping"]["interval_minutes"], 10)


if __name__ == "__main__":
	unittest.main()
