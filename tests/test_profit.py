from __future__ import annotations

import unittest
from datetime import datetime
from types import SimpleNamespace

from core.funpay.profit import (
	InvalidProfitPeriod,
	format_profit_summary,
	parse_custom_period,
	resolve_period,
	summarize_orders,
)


NOW = datetime(2026, 7, 15, 18, 30)


def order(price: float, status: str, date: datetime, currency: str = "₽") -> SimpleNamespace:
	return SimpleNamespace(price=price, currency=currency, date=date, status=SimpleNamespace(name=status))


class ProfitPeriodTest(unittest.TestCase):
	def test_day_starts_at_midnight(self):
		start, end, _ = resolve_period("day", NOW)

		self.assertEqual(start, datetime(2026, 7, 15))
		self.assertIsNone(end)

	def test_week_starts_on_monday(self):
		start, _, _ = resolve_period("week", NOW)

		self.assertEqual(start, datetime(2026, 7, 13))

	def test_month_starts_on_first_day(self):
		start, _, _ = resolve_period("month", NOW)

		self.assertEqual(start, datetime(2026, 7, 1))

	def test_all_period_has_no_bounds(self):
		start, end, label = resolve_period("all", NOW)

		self.assertIsNone(start)
		self.assertIsNone(end)
		self.assertEqual(label, "всё время")

	def test_custom_period_ends_after_last_day(self):
		start, end = parse_custom_period("01.07.2026 05.07.2026", NOW)

		self.assertEqual(start, datetime(2026, 7, 1))
		self.assertEqual(end, datetime(2026, 7, 6))

	def test_custom_period_accepts_single_date(self):
		start, end = parse_custom_period("2026-07-01", NOW)

		self.assertEqual(start, datetime(2026, 7, 1))
		self.assertEqual(end, datetime(2026, 7, 2))

	def test_custom_period_swaps_reversed_dates(self):
		start, end = parse_custom_period("05.07.2026 01.07.2026", NOW)

		self.assertEqual(start, datetime(2026, 7, 1))
		self.assertEqual(end, datetime(2026, 7, 6))

	def test_rejects_unparsable_period(self):
		with self.assertRaises(InvalidProfitPeriod):
			parse_custom_period("вчера", NOW)


class ProfitSummaryTest(unittest.TestCase):
	def setUp(self):
		self.orders = [
			order(100.0, "CLOSED", datetime(2026, 7, 15, 10)),
			order(50.0, "PAID", datetime(2026, 7, 15, 12)),
			order(30.0, "REFUNDED", datetime(2026, 7, 15, 13)),
			order(999.0, "CLOSED", datetime(2026, 7, 14, 10)),
			order(7.0, "CLOSED", datetime(2026, 7, 15, 11), currency="$"),
		]

	def summarize(self, include_paid: bool):
		return summarize_orders(self.orders, datetime(2026, 7, 15), None, include_paid, "сегодня")

	def test_counts_closed_only(self):
		stats = self.summarize(False).stats
		rubles = next(entry for entry in stats if entry.currency == "₽")

		self.assertEqual(rubles.total(False), 100.0)
		self.assertEqual(rubles.count(False), 1)
		self.assertEqual(rubles.refunded_total, 30.0)

	def test_counts_closed_and_paid(self):
		rubles = next(entry for entry in self.summarize(True).stats if entry.currency == "₽")

		self.assertEqual(rubles.total(True), 150.0)
		self.assertEqual(rubles.count(True), 2)
		self.assertEqual(rubles.average(True), 75.0)

	def test_splits_currencies(self):
		currencies = {entry.currency for entry in self.summarize(True).stats}

		self.assertEqual(currencies, {"₽", "$"})

	def test_ignores_orders_outside_period(self):
		summary = self.summarize(True)

		self.assertEqual(summary.scanned, 4)

	def test_formats_empty_summary(self):
		summary = summarize_orders([], datetime(2026, 7, 15), None, True, "сегодня")

		self.assertIn("Заказов за период не найдено", format_profit_summary(summary))

	def test_formats_summary_with_totals(self):
		text = format_profit_summary(self.summarize(True))

		self.assertIn("<b>150 ₽</b>", text)
		self.assertIn("💸 Возвраты: 30 ₽ (1)", text)


if __name__ == "__main__":
	unittest.main()
