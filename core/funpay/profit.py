from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from html import escape
from typing import TYPE_CHECKING

from ..config.constants import LOGGER_NAME, LOGGER_PREFIX
from .orders import get_sales_page, order_status_key

if TYPE_CHECKING:
	from cardinal import Cardinal


logger = logging.getLogger(LOGGER_NAME)


PROFIT_PERIODS = ("day", "week", "month", "all")

PROFIT_PERIOD_LABELS = {
	"day": "📅 День",
	"week": "🗓 Неделя",
	"month": "📆 Месяц",
	"all": "♾ Всё время",
	"custom": "✏️ Свой период",
}

MAX_SALES_PAGES = 50

DATE_FORMATS = ("%d.%m.%Y", "%Y-%m-%d", "%d.%m.%y")

DATE_PATTERN = re.compile(r"\d{1,4}[./-]\d{1,2}(?:[./-]\d{1,4})?")
SHORT_DATE_PATTERN = re.compile(r"\d{1,2}\.\d{1,2}")


class InvalidProfitPeriod(Exception):
	pass


@dataclass
class CurrencyStats:
	currency: str
	closed_total: float = 0.0
	closed_count: int = 0
	paid_total: float = 0.0
	paid_count: int = 0
	refunded_total: float = 0.0
	refunded_count: int = 0

	def total(self, include_paid: bool) -> float:
		return self.closed_total + (self.paid_total if include_paid else 0.0)

	def count(self, include_paid: bool) -> int:
		return self.closed_count + (self.paid_count if include_paid else 0)

	def average(self, include_paid: bool) -> float:
		count = self.count(include_paid)
		return self.total(include_paid) / count if count else 0.0


@dataclass
class ProfitSummary:
	label: str
	start: datetime | None
	end: datetime | None
	include_paid: bool
	scanned: int = 0
	stats: list[CurrencyStats] = field(default_factory=list)
	partial: bool = False


def resolve_period(period: str, now: datetime, custom: tuple[datetime, datetime] | None = None) -> tuple[datetime | None, datetime | None, str]:
	if period == "custom":
		if not custom:
			raise InvalidProfitPeriod("custom period requires dates")
		start, end = custom
		return start, end, f"{format_date(start)} - {format_date(end - timedelta(days=1))}"

	if period == "all":
		return None, None, "всё время"

	today = now.replace(hour=0, minute=0, second=0, microsecond=0)
	if period == "day":
		return today, None, f"сегодня, {format_date(today)}"
	if period == "week":
		start = today - timedelta(days=today.weekday())
		return start, None, f"неделя с {format_date(start)}"
	if period == "month":
		start = today.replace(day=1)
		return start, None, f"месяц с {format_date(start)}"

	raise InvalidProfitPeriod(period)


def parse_custom_period(text: str | None, now: datetime) -> tuple[datetime, datetime]:
	parts = DATE_PATTERN.findall(text or "")
	if not parts or len(parts) > 2:
		raise InvalidProfitPeriod("expected one or two dates")

	start = parse_date(parts[0], now)
	end = parse_date(parts[1], now) if len(parts) > 1 else start
	if end < start:
		start, end = end, start
	return start, end + timedelta(days=1)


def parse_date(value: str, now: datetime) -> datetime:
	if SHORT_DATE_PATTERN.fullmatch(value):
		value = f"{value}.{now.year}"

	for date_format in DATE_FORMATS:
		try:
			parsed = datetime.strptime(value, date_format)
		except ValueError:
			continue
		return parsed.replace(hour=0, minute=0, second=0, microsecond=0)
	raise InvalidProfitPeriod(value)


def collect_sales(cardinal: Cardinal, start: datetime | None) -> tuple[list, bool]:
	orders = []
	start_from = None
	locale = None
	subcs = None
	for _ in range(MAX_SALES_PAGES):
		start_from, sales, locale, subcs = get_sales_page(cardinal, None, None, start_from, locale, subcs)
		orders.extend(sales)
		if start_from is None:
			return orders, False
		if start and reached_period_start(sales, start):
			return orders, False
	return orders, True


def reached_period_start(sales: list, start: datetime) -> bool:
	dates = [order_date(order) for order in sales]
	return any(date is not None and date < start for date in dates)


def summarize_orders(orders: list, start: datetime | None, end: datetime | None, include_paid: bool, label: str, partial: bool = False) -> ProfitSummary:
	summary = ProfitSummary(label=label, start=start, end=end, include_paid=include_paid, partial=partial)
	stats: dict[str, CurrencyStats] = {}
	for order in orders:
		date = order_date(order)
		if start and (date is None or date < start):
			continue
		if end and (date is None or date >= end):
			continue

		status = order_status_key(order)
		if status not in ("closed", "paid", "refunded"):
			continue

		summary.scanned += 1
		currency = order_currency(order)
		entry = stats.setdefault(currency, CurrencyStats(currency=currency))
		price = order_price(order)
		if status == "closed":
			entry.closed_total += price
			entry.closed_count += 1
		elif status == "paid":
			entry.paid_total += price
			entry.paid_count += 1
		else:
			entry.refunded_total += price
			entry.refunded_count += 1

	summary.stats = sorted(stats.values(), key=lambda item: item.total(include_paid), reverse=True)
	return summary


def calculate_profit(
	cardinal: Cardinal,
	period: str,
	include_paid: bool,
	now: datetime | None = None,
	custom: tuple[datetime, datetime] | None = None,
) -> ProfitSummary:
	now = now or datetime.now()
	start, end, label = resolve_period(period, now, custom)
	try:
		orders, partial = collect_sales(cardinal, start)
	except Exception as exc:
		logger.error(f"{LOGGER_PREFIX} Failed to fetch sales for profit: {exc}")
		raise

	return summarize_orders(orders, start, end, include_paid, label, partial)


def order_date(order: object) -> datetime | None:
	date = getattr(order, "date", None)
	if isinstance(date, datetime):
		return date
	if isinstance(date, str):
		for date_format in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
			try:
				return datetime.strptime(date, date_format)
			except ValueError:
				continue
	return None


def order_price(order: object) -> float:
	price = getattr(order, "price", None)
	if price is None:
		price = getattr(order, "sum", None)
	try:
		return float(price)
	except (TypeError, ValueError):
		return 0.0


def order_currency(order: object) -> str:
	currency = getattr(order, "currency", None)
	if currency is None:
		return ""
	return str(getattr(currency, "code", None) or getattr(currency, "name", None) or currency)


def format_date(value: datetime) -> str:
	return value.strftime("%d.%m.%Y")


def format_amount(value: float) -> str:
	return f"{value:,.2f}".replace(",", " ").replace(".00", "")


def format_profit_summary(summary: ProfitSummary) -> str:
	mode = "закрытые + оплаченные" if summary.include_paid else "только закрытые"
	lines = [
		"💰 <b>Прибыль</b>",
		"",
		f"Период: <b>{escape(summary.label)}</b>",
		f"Учёт: <b>{mode}</b>",
	]

	if not summary.stats:
		lines.append("\nЗаказов за период не найдено.")
		return "\n".join(lines)

	for entry in summary.stats:
		currency = escape(entry.currency)
		lines.append("")
		lines.append(f"<b>{format_amount(entry.total(summary.include_paid))} {currency}</b>")
		lines.append(f"Заказов: <b>{entry.count(summary.include_paid)}</b>")
		lines.append(f"Средний чек: <b>{format_amount(entry.average(summary.include_paid))} {currency}</b>")
		lines.append(f"✅ Закрытые: {format_amount(entry.closed_total)} {currency} ({entry.closed_count})")
		lines.append(f"💳 Оплаченные: {format_amount(entry.paid_total)} {currency} ({entry.paid_count})")
		lines.append(f"💸 Возвраты: {format_amount(entry.refunded_total)} {currency} ({entry.refunded_count})")

	if summary.partial:
		lines.append("")
		lines.append("⚠️ Просмотрены не все страницы продаж, данные могут быть неполными.")

	return "\n".join(lines)
