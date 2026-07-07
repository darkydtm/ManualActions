from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .constants import LOGGER_NAME, LOGGER_PREFIX

if TYPE_CHECKING:
	from cardinal import Cardinal


logger = logging.getLogger(LOGGER_NAME)


def get_pending_orders_for_user(cardinal: Cardinal, username: str) -> list:
	try:
		result = []
		start_from = None
		locale = None
		subcs = None
		while True:
			start_from, sales, locale, subcs = cardinal.account.get_sales(
				buyer=username,
				start_from=start_from,
				state="paid",
				locale=locale,
				subcategories=subcs,
			)
			result.extend(sales)
			if start_from is None:
				break
		return result
	except Exception as exc:
		logger.error(f"{LOGGER_PREFIX} Failed to fetch orders for {username}: {exc}")
		return []


def refund_order(cardinal: Cardinal, order_id: str) -> None:
	cardinal.account.refund(order_id)
