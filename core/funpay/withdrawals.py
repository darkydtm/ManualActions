from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


BALANCE_URL = "https://funpay.com/account/balance"


class WithdrawalError(Exception):
	pass


class WithdrawalAuthenticationError(WithdrawalError):
	pass


class WithdrawalParsingError(WithdrawalError):
	pass


@dataclass(frozen=True)
class WithdrawalMethod:
	code: str
	label: str
	fixed_fee: Decimal
	percentage_fee: Decimal


@dataclass(frozen=True)
class WithdrawalBalance:
	available_amount: Decimal
	currency: str
	methods: tuple[WithdrawalMethod, ...]


@dataclass(frozen=True)
class WithdrawalCalculation:
	method: WithdrawalMethod
	percentage_amount: Decimal
	total_fee: Decimal
	net_amount: Decimal


class BalancePageParser(HTMLParser):
	def __init__(self) -> None:
		super().__init__()
		self.balance_value = ""
		self.currency = ""
		self.methods: list[dict[str, str]] = []
		self.is_login_page = False

	def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
		attributes = {name: value or "" for name, value in attrs}
		if tag == "form" and "/account/login" in attributes.get("action", ""):
			self.is_login_page = True

		if tag == "input" and attributes.get("name") == "login":
			self.is_login_page = True

		if "data-withdrawal-balance" in attributes:
			self.balance_value = attributes["data-withdrawal-balance"]
			self.currency = attributes.get("data-currency", "")

		if "data-withdrawal-method" in attributes:
			self.methods.append({
				"code": attributes["data-withdrawal-method"],
				"label": attributes.get("data-withdrawal-label", ""),
				"fixed_fee": attributes.get("data-fixed-fee", ""),
				"percentage_fee": attributes.get("data-percent-fee", ""),
			})


def fetch_withdrawal_balance(
	golden_key: str,
	request_func: Callable[..., Any] = urlopen,
	timeout: int = 15,
) -> WithdrawalBalance:
	key = golden_key.strip()
	if not key:
		raise WithdrawalAuthenticationError("Missing account key.")

	request = Request(BALANCE_URL, headers={"Cookie": f"golden_key={key}"})
	try:
		with request_func(request, timeout=timeout) as response:
			html = response.read().decode("utf-8")
	except (HTTPError, URLError, UnicodeDecodeError) as exc:
		raise WithdrawalError("Failed to request balance page.") from exc
	except Exception as exc:
		raise WithdrawalError("Failed to request balance page.") from exc

	return parse_balance_page(html)


def parse_balance_page(html: str) -> WithdrawalBalance:
	parser = BalancePageParser()
	try:
		parser.feed(html)
		parser.close()
	except Exception as exc:
		raise WithdrawalParsingError("Failed to parse balance page.") from exc

	if parser.is_login_page:
		raise WithdrawalAuthenticationError("FunPay session is not authenticated.")
	if not parser.balance_value or not parser.currency:
		raise WithdrawalParsingError("Balance data is missing.")

	available_amount = parse_amount(parser.balance_value)
	if available_amount < 0:
		raise WithdrawalParsingError("Balance amount cannot be negative.")

	methods = tuple(parse_method(item) for item in parser.methods)
	if not methods:
		raise WithdrawalParsingError("Withdrawal methods are missing.")
	if len({method.code for method in methods}) != len(methods):
		raise WithdrawalParsingError("Withdrawal method codes must be unique.")
	return WithdrawalBalance(available_amount, parser.currency.strip(), methods)


def parse_method(data: dict[str, str]) -> WithdrawalMethod:
	code = data["code"].strip()
	label = data["label"].strip()
	if not code or not label:
		raise WithdrawalParsingError("Withdrawal method data is incomplete.")

	fixed_fee = parse_amount(data["fixed_fee"])
	percentage_fee = parse_amount(data["percentage_fee"])
	if fixed_fee < 0 or percentage_fee < 0:
		raise WithdrawalParsingError("Withdrawal fees cannot be negative.")
	return WithdrawalMethod(code, label, fixed_fee, percentage_fee)


def parse_amount(value: str) -> Decimal:
	text = value.replace("\xa0", "").replace(" ", "").replace(",", ".").strip()
	if not text:
		raise WithdrawalParsingError("Amount is missing.")
	try:
		return Decimal(text)
	except InvalidOperation as exc:
		raise WithdrawalParsingError("Amount is invalid.") from exc


def calculate_withdrawal(balance: WithdrawalBalance, method: WithdrawalMethod) -> WithdrawalCalculation:
	percentage_amount = balance.available_amount * method.percentage_fee / Decimal("100")
	total_fee = method.fixed_fee + percentage_amount
	return WithdrawalCalculation(method, percentage_amount, total_fee, balance.available_amount - total_fee)
