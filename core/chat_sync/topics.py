from __future__ import annotations

from dataclasses import dataclass
from typing import Any


DEFAULT_TOPIC_ICON = "5417915203100613993"

TOPIC_ICONS = {
	"employee": "5377494501373780436",
	"arbitration": "5377438129928020693",
	"blacklist": "5238234236955148254",
	"paid": "5431492767249342908",
	"regular": "5357107601584693888",
	"frequent": "5309958691854754293",
	"closed": "5350452584119279096",
	"refunded": "5312424913615723286",
	"default": DEFAULT_TOPIC_ICON,
}


@dataclass(frozen=True)
class OrderStats:
	paid: int = 0
	closed: int = 0
	refunded: int = 0
	paid_sum: str = ""
	closed_sum: str = ""
	refunded_sum: str = ""

	@property
	def has_orders(self) -> bool:
		return bool(self.paid or self.closed or self.refunded)


def format_topic_name(username: str, chat_id: int | str, stats: OrderStats | None = None) -> str:
	name = str(username or "").strip() or f"chat {chat_id}"
	if stats and stats.has_orders:
		return f"{stats.paid}|{stats.closed}|{stats.refunded}👤{name} ({chat_id})"
	return f"{name} ({chat_id})"


def parse_topic_name(name: str) -> tuple[str, int] | tuple[None, None]:
	try:
		if "👤" in name:
			name = name.split("👤", 1)[1]

		parts = name.strip().rsplit(" ", 1)
		if len(parts) != 2:
			return None, None

		username = parts[0].strip()
		chat_id = int(parts[1].replace("(", "").replace(")", "").strip())
		return username, chat_id
	except (TypeError, ValueError):
		return None, None


def topic_icon(stats: OrderStats, blacklisted: bool = False, special: str = "") -> str:
	if special in TOPIC_ICONS:
		return TOPIC_ICONS[special]
	if blacklisted:
		return TOPIC_ICONS["blacklist"]
	if stats.paid:
		return TOPIC_ICONS["paid"]
	if stats.closed >= 50:
		return TOPIC_ICONS["regular"]
	if stats.closed >= 10:
		return TOPIC_ICONS["frequent"]
	if stats.closed:
		return TOPIC_ICONS["closed"]
	if stats.refunded:
		return TOPIC_ICONS["refunded"]
	return TOPIC_ICONS["default"]


def collect_order_stats(sales: Any) -> OrderStats:
	paid = closed = refunded = 0
	paid_sum: dict[str, float] = {}
	closed_sum: dict[str, float] = {}
	refunded_sum: dict[str, float] = {}

	for sale in sales or ():
		status = getattr(getattr(sale, "status", None), "name", "")
		currency = str(getattr(sale, "currency", "") or "")
		price = float(getattr(sale, "price", 0) or 0)
		if status == "REFUNDED":
			refunded += 1
			refunded_sum[currency] = refunded_sum.get(currency, 0) + price
		elif status == "PAID":
			paid += 1
			paid_sum[currency] = paid_sum.get(currency, 0) + price
		elif status == "CLOSED":
			closed += 1
			closed_sum[currency] = closed_sum.get(currency, 0) + price

	return OrderStats(
		paid=paid,
		closed=closed,
		refunded=refunded,
		paid_sum=format_sums(paid_sum),
		closed_sum=format_sums(closed_sum),
		refunded_sum=format_sums(refunded_sum),
	)


def format_sums(sums: dict[str, float]) -> str:
	return ", ".join(sorted(f"{format_amount(value)}{currency}" for currency, value in sums.items()))


def format_amount(value: float) -> str:
	rounded = round(float(value), 2)
	return str(int(rounded)) if rounded == int(rounded) else str(rounded)
