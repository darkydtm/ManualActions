from __future__ import annotations

from decimal import Decimal
from urllib.error import URLError
import unittest

from core.funpay.withdrawals import (
	WithdrawalAuthenticationError,
	WithdrawalError,
	WithdrawalMethod,
	WithdrawalParsingError,
	calculate_withdrawal,
	fetch_withdrawal_balance,
	parse_balance_page,
)


BALANCE_PAGE = """
<div data-withdrawal-balance="1234,56" data-currency="₽"></div>
<button data-withdrawal-method="sbp" data-withdrawal-label="СБП"
	data-fixed-fee="15" data-percent-fee="2,5"></button>
<button data-withdrawal-method="card" data-withdrawal-label="Банковская карта"
	data-fixed-fee="0" data-percent-fee="3"></button>
"""


class FakeResponse:
	def __init__(self, data: str):
		self.data = data.encode("utf-8")

	def __enter__(self):
		return self

	def __exit__(self, exc_type, exc_value, traceback):
		return False

	def read(self) -> bytes:
		return self.data


class WithdrawalParserTest(unittest.TestCase):
	def test_extracts_balance_currency_and_methods(self):
		result = parse_balance_page(BALANCE_PAGE)

		self.assertEqual(result.available_amount, Decimal("1234.56"))
		self.assertEqual(result.currency, "₽")
		self.assertEqual(result.methods, (
			WithdrawalMethod("sbp", "СБП", Decimal("15"), Decimal("2.5")),
			WithdrawalMethod("card", "Банковская карта", Decimal("0"), Decimal("3")),
		))

	def test_extracts_funpay_withdraw_box_data(self):
		page = """
			<span class="badge badge-balance">1 234,56 ₽</span>
			<div class="withdraw-box" data-data='{"currencies":{"rub":{"name":"Рубли","channels":[{"extCurrency":"sbp","name":"СБП","feeInfo":"Комиссия: 2,5% + 15 ₽"}]}}}'></div>
		"""

		result = parse_balance_page(page)

		self.assertEqual(result.available_amount, Decimal("1234.56"))
		self.assertEqual(result.currency, "₽")
		self.assertEqual(result.methods, (
			WithdrawalMethod("sbp", "СБП", Decimal("15"), Decimal("2.5")),
		))

	def test_rejects_login_page(self):
		with self.assertRaises(WithdrawalAuthenticationError):
			parse_balance_page('<form action="/account/login"><input name="login"></form>')

	def test_rejects_page_without_balance(self):
		with self.assertRaises(WithdrawalParsingError):
			parse_balance_page('<button data-withdrawal-method="sbp"></button>')

	def test_rejects_method_without_fee(self):
		page = '<div data-withdrawal-balance="100" data-currency="₽"></div><button data-withdrawal-method="sbp" data-withdrawal-label="СБП" data-fixed-fee="10"></button>'
		with self.assertRaises(WithdrawalParsingError):
			parse_balance_page(page)


class WithdrawalCalculationTest(unittest.TestCase):
	def test_calculates_fixed_and_percentage_fees(self):
		balance = parse_balance_page(BALANCE_PAGE)

		result = calculate_withdrawal(balance, balance.methods[0])

		self.assertEqual(result.percentage_amount, Decimal("30.864"))
		self.assertEqual(result.total_fee, Decimal("45.864"))
		self.assertEqual(result.net_amount, Decimal("1188.696"))


class WithdrawalRequestTest(unittest.TestCase):
	def test_requests_balance_with_cardinal_key_cookie(self):
		requests = []

		def request_func(request, timeout):
			requests.append((request, timeout))
			return FakeResponse(BALANCE_PAGE)

		result = fetch_withdrawal_balance("key-value", request_func)

		self.assertEqual(result.available_amount, Decimal("1234.56"))
		self.assertEqual(requests[0][0].full_url, "https://funpay.com/account/balance")
		self.assertEqual(requests[0][0].get_header("Cookie"), "golden_key=key-value")
		self.assertEqual(requests[0][1], 15)

	def test_does_not_leak_key_in_request_error(self):
		def request_func(request, timeout):
			raise URLError("offline")

		with self.assertRaises(WithdrawalError) as context:
			fetch_withdrawal_balance("key-value", request_func)

		self.assertNotIn("key-value", str(context.exception))

	def test_rejects_blank_key(self):
		with self.assertRaises(WithdrawalAuthenticationError):
			fetch_withdrawal_balance(" ")


if __name__ == "__main__":
	unittest.main()
