from __future__ import annotations

import unittest

from core.config.settings import normalize_settings
from core.modules.auto_dumping.models import DumpingRule
from core.modules.auto_dumping.settings import normalize_auto_dumping_settings, normalize_rule, parse_subcategory_id


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
				"subcategory": " 4093 ",
				"keywords": ["gold", "gold", " "],
				"keyword_mode": "all",
				"competitor_min_price": 10.5,
				"price_mode": "percent",
				"dumping_value": 5,
				"own_min_price": 3,
				"sellers_blacklist": ["bad"],
				"keywords_blacklist": ["beta"],
			}, {"subcategory": "", "keywords": []}, {"subcategory": "Game", "keywords": ["silver"]}],
		})

		self.assertNotIn("global_sellers_blacklist", settings)
		self.assertNotIn("global_keywords_blacklist", settings)
		self.assertEqual(len(settings["rules"]), 1)
		self.assertEqual(settings["rules"][0]["id"], " rule-1 ")
		self.assertEqual(settings["rules"][0]["subcategory"], 4093)
		self.assertEqual(settings["rules"][0]["sellers_blacklist"], ["bad"])
		self.assertEqual(settings["rules"][0]["keywords_blacklist"], ["beta"])
		self.assertEqual(DumpingRule.from_dict(settings["rules"][0]).keyword_mode, "all")

	def test_rejects_duplicate_rule_keywords_in_one_subcategory(self):
		settings = normalize_auto_dumping_settings({
			"rules": [
				{"id": "one", "subcategory": 4093, "keywords": ["gold"]},
				{"id": "two", "subcategory": "4093", "keywords": [" GOLD "]},
			],
		})

		self.assertEqual([rule["id"] for rule in settings["rules"]], ["one"])

	def test_preserves_rule_ids_of_any_utf8_length(self):
		rule_id = "идентификатор-" + "x" * 100
		settings = normalize_auto_dumping_settings({"rules": [{
			"id": rule_id, "subcategory": 4093, "keywords": ["gold"],
		}]})

		self.assertEqual(settings["rules"][0]["id"], rule_id)

	def test_generates_ids_for_empty_rule_ids_and_preserves_normal_ids(self):
		for rule_id in ("", "   "):
			rule = normalize_rule({"id": rule_id, "subcategory": 4093, "keywords": ["gold"]})
			self.assertRegex(rule["id"], r"^[0-9a-f]{32}$")

		rule = normalize_rule({"id": "rule-1", "subcategory": "https://funpay.com/lots/4093", "keywords": ["gold"]})
		self.assertEqual(rule["id"], "rule-1")

	def test_normalize_settings_includes_auto_dumping_section(self):
		settings = normalize_settings({"auto_dumping": {"enabled": True, "interval_minutes": 10}})

		self.assertTrue(settings["auto_dumping"]["enabled"])
		self.assertEqual(settings["auto_dumping"]["interval_minutes"], 10)

	def test_parse_subcategory_id_accepts_int_digits_and_lot_url(self):
		self.assertEqual(parse_subcategory_id(4093), 4093)
		self.assertEqual(parse_subcategory_id(" 4093 "), 4093)
		self.assertEqual(parse_subcategory_id("https://funpay.com/lots/4093"), 4093)
		self.assertEqual(parse_subcategory_id("funpay.com/lots/4093?x=1"), 4093)

	def test_parse_subcategory_id_rejects_names_and_non_positive(self):
		for value in ("Game", "", "  ", "Золото", 0, -5, True, None, 4.5, "lots/abc"):
			self.assertIsNone(parse_subcategory_id(value))

	def test_normalize_rule_drops_name_based_subcategory(self):
		self.assertIsNone(normalize_rule({"subcategory": "Game", "keywords": ["gold"], "dumping_value": 1}))


if __name__ == "__main__":
	unittest.main()
