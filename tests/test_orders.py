from __future__ import annotations

import unittest
from types import SimpleNamespace

from manual_actions_core.orders import format_order_details, format_order_summary, order_status_key


class OrdersTest(unittest.TestCase):
	def test_detects_paid_status_from_enum_name(self):
		order = SimpleNamespace(status=SimpleNamespace(name="PAID"))

		self.assertEqual(order_status_key(order), "paid")

	def test_formats_order_summary(self):
		order = SimpleNamespace(id="ABC123", price=12.0, currency="₽", status=SimpleNamespace(name="CLOSED"))

		self.assertEqual(format_order_summary(order), "#ABC123 - 12 ₽ - Закрыт")

	def test_formats_order_details(self):
		order = SimpleNamespace(
			id="ABC123",
			description="Test order",
			price=12.0,
			currency="₽",
			amount=2,
			buyer_username="buyer",
			subcategory_name="Game, Section",
			date="2026-07-08 12:00",
			status=SimpleNamespace(name="REFUNDED"),
		)

		text = format_order_details(order)

		self.assertIn("ID: <code>ABC123</code>", text)
		self.assertIn("Лот: <b>Test order</b>", text)
		self.assertIn("Статус: <b>Возврат</b>", text)
		self.assertIn("Сумма: <b>12 ₽</b>", text)
		self.assertIn("https://funpay.com/orders/ABC123/", text)


if __name__ == "__main__":
	unittest.main()
