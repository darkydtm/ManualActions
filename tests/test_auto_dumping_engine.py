from __future__ import annotations

import unittest

from core.modules.auto_dumping.conflicts import resolve_candidates
from core.modules.auto_dumping.matching import is_blacklisted, match_keywords
from core.modules.auto_dumping.models import DumpingRule, Lot, RuleCandidate
from core.modules.auto_dumping.pricing import calculate_price


def rule(**changes):
	data = {
		"id": "rule",
		"enabled": True,
		"subcategory": "game",
		"keywords": ("gold", "fast"),
		"keyword_mode": "any",
		"competitor_min_price": 0,
		"price_mode": "fixed",
		"dumping_value": 5,
		"own_min_price": 10,
	}
	data.update(changes)
	return DumpingRule(**data)


class AutoDumpingEngineTest(unittest.TestCase):
	def test_matches_any_and_all_keywords_case_insensitively(self):
		self.assertEqual(match_keywords("Fast GOLD delivery", ("gold", "fast"), "any"), 2)
		self.assertEqual(match_keywords("Fast delivery", ("gold", "fast"), "all"), 0)
		self.assertEqual(match_keywords("Fast GOLD delivery", ("gold", "fast"), "all"), 2)

	def test_blacklist_uses_exact_sellers_and_whole_words(self):
		self.assertTrue(is_blacklisted("BadSeller", "Gold beta", ("badseller",), ("beta",)))
		self.assertFalse(is_blacklisted("GoodSeller", "alphabet soup", (), ("alpha",)))

	def test_calculates_fixed_and_percentage_prices_without_rounding(self):
		self.assertEqual(calculate_price(100.25, rule(price_mode="fixed", dumping_value=5)), 95.25)
		self.assertEqual(calculate_price(100.25, rule(price_mode="percent", dumping_value=10)), 90.225)

	def test_resolves_by_keyword_count_then_final_price_and_marks_tie(self):
		lot = Lot("competitor", "Gold", 20, "game", "seller")
		first = RuleCandidate(rule(id="one"), lot, 1, 20, 15, 15)
		second = RuleCandidate(rule(id="two"), lot, 2, 30, 25, 25)
		self.assertIs(resolve_candidates([first, second]), second)

		tie = resolve_candidates([
			RuleCandidate(rule(id="one"), lot, 1, 20, 15, 15),
			RuleCandidate(rule(id="two"), lot, 1, 20, 12, 12),
		])
		self.assertEqual(tie.rule.id, "two")
		self.assertEqual(tie.reason, "equal_keyword_count")


if __name__ == "__main__":
	unittest.main()
