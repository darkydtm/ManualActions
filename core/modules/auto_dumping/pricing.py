from __future__ import annotations

from .models import DumpingRule


def calculate_price(competitor_price: float, rule: DumpingRule) -> float:
	if rule.price_mode == "percent":
		return competitor_price - competitor_price * rule.dumping_value / 100
	return competitor_price - rule.dumping_value


def final_price(competitor_price: float, rule: DumpingRule) -> float:
	return round(max(calculate_price(competitor_price, rule), rule.own_min_price), 2)
