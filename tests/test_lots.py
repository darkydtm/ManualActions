from __future__ import annotations

import unittest
from types import SimpleNamespace

from core.lots import extract_lot_id, format_lot_details, format_lot_section


class LotsTest(unittest.TestCase):
	def test_extracts_lot_id_from_funpay_link(self):
		self.assertEqual(extract_lot_id("https://funpay.com/lots/offer?id=12345"), "12345")
		self.assertEqual(extract_lot_id("https://funpay.com/chips/offer?id=abc"), "abc")

	def test_formats_lot_details(self):
		lot = SimpleNamespace(
			id=123,
			description="Test lot",
			price=10.5,
			currency=SimpleNamespace(code="₽"),
			amount=7,
			server="Server",
			side=None,
			subcategory=SimpleNamespace(name="Section", category=SimpleNamespace(name="Game")),
			full_description="Full lot description",
			public_link="https://funpay.com/lots/offer?id=123",
		)

		text = format_lot_details(lot)

		self.assertIn("ID: <code>123</code>", text)
		self.assertIn("Название: <b>Test lot</b>", text)
		self.assertIn("Цена: <b>10.5 ₽</b>", text)
		self.assertIn("Категория: Game, Section", text)
		self.assertIn("Описание: Full lot description", text)

	def test_formats_lot_description_section(self):
		lot = SimpleNamespace(
			id=123,
			description="Test lot",
			full_description="Full lot description",
		)

		text = format_lot_section(lot, "description")

		self.assertIn("<b>Описание лота</b>", text)
		self.assertIn("Full lot description", text)

	def test_formats_missing_viewed_lot(self):
		text = format_lot_details(None, "Viewed lot", "https://funpay.com/lots/offer?id=123")

		self.assertIn("Покупатель смотрит: <b>Viewed lot</b>", text)
		self.assertIn("Лот не найден", text)


if __name__ == "__main__":
	unittest.main()
