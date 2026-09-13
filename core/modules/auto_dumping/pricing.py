from __future__ import annotations

from .models import DumpingRule


def commission_coefficient(rule: DumpingRule) -> float:
	return 1.0 + max(float(rule.commission_percent), 0.0) / 100.0


def seller_price(buyer_price: float, rule: DumpingRule) -> float:
	return buyer_price / commission_coefficient(rule)


def calculate_price(competitor_price: float, rule: DumpingRule) -> float:
	net = seller_price(competitor_price, rule)
	if rule.price_mode == "percent":
		return net - net * rule.dumping_value / 100
	return net - rule.dumping_value


def final_price(competitor_price: float, rule: DumpingRule) -> float:
	return round(max(calculate_price(competitor_price, rule), rule.own_min_price), 2)
