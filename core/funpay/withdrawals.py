from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
import json
import re
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
		self.badge_balance_depth = 0
		self.badge_balance_text: list[str] = []
		self.withdrawal_data = ""

	def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
		attributes = {name: value or "" for name, value in attrs}
		if tag == "form" and "/account/login" in attributes.get("action", ""):
			self.is_login_page = True

		if tag == "input" and attributes.get("name") == "login":
			self.is_login_page = True
		if "badge-balance" in attributes.get("class", "").split():
			self.badge_balance_depth = 1
		if "withdraw-box" in attributes.get("class", "").split():
			self.withdrawal_data = attributes.get("data-data", "")

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

	def handle_endtag(self, tag: str) -> None:
		if self.badge_balance_depth and tag == "span":
			self.badge_balance_depth = 0

	def handle_data(self, data: str) -> None:
		if self.badge_balance_depth:
			self.badge_balance_text.append(data)


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
	balance_value, currency = balance_data(parser)
	if not balance_value or not currency:
		raise WithdrawalParsingError("Balance data is missing.")

	available_amount = parse_amount(balance_value)
	if available_amount < 0:
		raise WithdrawalParsingError("Balance amount cannot be negative.")

	methods = tuple(parse_method(item) for item in parser.methods)
	if not methods and parser.withdrawal_data:
		methods = parse_withdrawal_data(parser.withdrawal_data)
	if not methods:
		raise WithdrawalParsingError("Withdrawal methods are missing.")
	if len({method.code for method in methods}) != len(methods):
		raise WithdrawalParsingError("Withdrawal method codes must be unique.")
	return WithdrawalBalance(available_amount, currency.strip(), methods)


def balance_data(parser: BalancePageParser) -> tuple[str, str]:
	if parser.balance_value and parser.currency:
		return parser.balance_value, parser.currency

	text = " ".join(parser.badge_balance_text).strip()
	match = re.fullmatch(r"(.+?)\s+(\S+)", text)
	if not match:
		return "", ""
	return match.group(1), match.group(2)


def parse_withdrawal_data(value: str) -> tuple[WithdrawalMethod, ...]:
	try:
		data = json.loads(value)
	except json.JSONDecodeError as exc:
		raise WithdrawalParsingError("Withdrawal data is invalid.") from exc

	currencies = data.get("currencies") if isinstance(data, dict) else None
	if isinstance(currencies, dict):
		currency_data = currencies.values()
	elif isinstance(currencies, list):
		currency_data = currencies
	else:
		raise WithdrawalParsingError("Withdrawal currencies are missing.")

	methods = []
	for currency in currency_data:
		if not isinstance(currency, dict):
			continue
		channels = currency.get("channels")
		if not isinstance(channels, list):
			continue
		for channel in channels:
			if not isinstance(channel, dict):
				continue
			code = str(channel.get("extCurrency") or "").strip()
			label = str(channel.get("name") or "").strip()
			if not code or not label:
				raise WithdrawalParsingError("Withdrawal method data is incomplete.")
			fixed_fee, percentage_fee = parse_fee_info(str(channel.get("feeInfo") or ""))
			methods.append(WithdrawalMethod(code, label, fixed_fee, percentage_fee))
	return tuple(methods)


def parse_fee_info(value: str) -> tuple[Decimal, Decimal]:
	percentage_match = re.search(r"(\d+(?:[.,]\d+)?)\s*%", value)
	percentage_fee = parse_amount(percentage_match.group(1)) if percentage_match else Decimal("0")
	currency_amounts = re.findall(r"(\d+(?:[.,]\d+)?)\s*(?:₽|руб(?:\.|лей)?|\$|€)", value, flags=re.IGNORECASE)
	if not currency_amounts and not percentage_match:
		raise WithdrawalParsingError("Withdrawal fee data is missing.")
	fixed_fee = parse_amount(currency_amounts[-1]) if currency_amounts else Decimal("0")
	return fixed_fee, percentage_fee


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
