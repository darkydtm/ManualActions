from __future__ import annotations

import logging
from html import escape
from typing import TYPE_CHECKING

from ..config.constants import LOGGER_NAME, LOGGER_PREFIX

if TYPE_CHECKING:
	from cardinal import Cardinal


logger = logging.getLogger(LOGGER_NAME)


ORDER_FILTERS = {
	"all": None,
	"paid": "paid",
	"closed": "closed",
	"refunded": "refunded",
}

ORDER_FILTER_LABELS = {
	"all": "📦 Все",
	"paid": "💳 Оплаченные",
	"closed": "✅ Закрытые",
	"refunded": "💸 Возвраты",
}


def get_pending_orders_for_user(cardinal: Cardinal, username: str) -> list:
	return get_orders_for_user(cardinal, username, state="paid")


def get_orders_for_user(cardinal: Cardinal, username: str, state: str | None = None, limit: int = 50) -> list:
	try:
		result = []
		start_from = None
		locale = None
		subcs = None
		while True:
			start_from, sales, locale, subcs = get_sales_page(cardinal, username, state, start_from, locale, subcs)
			result.extend(sales)
			if start_from is None or len(result) >= limit:
				break
		return result[:limit]
	except Exception as exc:
		logger.error(f"{LOGGER_PREFIX} Failed to fetch orders for {username}: {exc}")
		return []


def get_sales_page(
	cardinal: Cardinal,
	username: str,
	state: str | None,
	start_from: str | None,
	locale: object,
	subcategories: object,
) -> tuple[str | None, list, object, object]:
	get_sales = getattr(cardinal.account, "get_sales", None)
	if get_sales:
		try:
			result = get_sales(
				buyer=username,
				start_from=start_from,
				state=state,
				locale=locale,
				subcategories=subcategories,
			)
		except TypeError:
			result = get_sales(buyer=username, start_from=start_from, state=state)
		return normalize_sales_result(result, locale, subcategories)

	start_from, sales = cardinal.account.get_sells(buyer=username, start_from=start_from, state=state)
	return start_from, sales, locale, subcategories


def normalize_sales_result(result: tuple, locale: object, subcategories: object) -> tuple[str | None, list, object, object]:
	if len(result) >= 4:
		return result[0], result[1], result[2], result[3]
	return result[0], result[1], locale, subcategories


def refund_order(cardinal: Cardinal, order_id: str) -> None:
	cardinal.account.refund(order_id)


def order_status_key(order: object) -> str:
	status = getattr(order, "status", "")
	value = getattr(status, "value", None) or getattr(status, "name", None) or str(status)
	value = value.lower()
	if "paid" in value or "оплач" in value:
		return "paid"
	if "closed" in value or "закры" in value:
		return "closed"
	if "refund" in value or "возв" in value:
		return "refunded"
	return value


def order_status_label(order: object) -> str:
	status = order_status_key(order)
	return {
		"paid": "Оплачен",
		"closed": "Закрыт",
		"refunded": "Возврат",
	}.get(status, status or "неизвестно")


def format_order_summary(order: object) -> str:
	order_id = getattr(order, "id", "")
	price = format_order_price(order)
	status = order_status_label(order)
	return f"#{order_id} - {price} - {status}"


def format_order_details(order: object) -> str:
	lines = ["<b>Информация о заказе</b>"]
	order_id = getattr(order, "id", None)
	if order_id:
		lines.append(f"\nID: <code>{escape(str(order_id))}</code>")

	description = getattr(order, "description", None) or getattr(order, "short_description", None) or getattr(order, "title", None)
	if description:
		lines.append(f"Лот: <b>{escape(str(description))}</b>")

	lines.append(f"Статус: <b>{escape(order_status_label(order))}</b>")
	price = format_order_price(order)
	if price:
		lines.append(f"Сумма: <b>{escape(price)}</b>")

	amount = getattr(order, "amount", None)
	if amount is not None:
		lines.append(f"Количество: <b>{escape(str(amount))}</b>")

	buyer = getattr(order, "buyer_username", None)
	if buyer:
		lines.append(f"Покупатель: <code>{escape(str(buyer))}</code>")

	category = getattr(order, "subcategory_name", None)
	if category:
		lines.append(f"Категория: {escape(str(category))}")

	date = getattr(order, "date", None)
	if date:
		lines.append(f"Дата: {escape(str(date))}")

	if order_id:
		lines.append(f"Ссылка: https://funpay.com/orders/{escape(str(order_id))}/")

	return "\n".join(lines)


def format_order_price(order: object) -> str:
	price = getattr(order, "price", None)
	if price is None:
		price = getattr(order, "sum", None)
	if price is None:
		return ""

	currency = getattr(order, "currency", None)
	currency_text = ""
	if currency is not None:
		currency_text = getattr(currency, "code", None) or getattr(currency, "name", None) or str(currency)
	return f"{price:g} {currency_text}".strip() if isinstance(price, float) else f"{price} {currency_text}".strip()
