from __future__ import annotations

import re
from dataclasses import dataclass
from html import escape
from typing import TYPE_CHECKING, Any

from .constants import LOGGER_NAME, LOGGER_PREFIX

import logging

if TYPE_CHECKING:
	from cardinal import Cardinal
	from .chat_sync import TopicContext


logger = logging.getLogger(LOGGER_NAME)


LOT_URL_ID_RE = re.compile(r"(?:[?&](?:id|offer)=|/offer/)([A-Za-z0-9_-]+)")


@dataclass(frozen=True)
class ViewedLot:
	text: str | None
	link: str | None
	lot: Any | None


def extract_lot_id(value: str | None) -> str | None:
	value = (value or "").strip()
	if not value:
		return None

	match = LOT_URL_ID_RE.search(value)
	if match:
		return match.group(1)

	if value.startswith("#"):
		value = value[1:]
	if value.isalnum() or "_" in value or "-" in value:
		return value
	return None


def get_profile_lots(cardinal: Cardinal) -> list[Any]:
	profile = getattr(cardinal, "profile", None)
	if profile and hasattr(profile, "get_lots"):
		return list(profile.get_lots() or [])

	account = getattr(cardinal, "account", None)
	account_id = getattr(account, "id", None)
	if account and account_id and hasattr(account, "get_user"):
		try:
			user = account.get_user(account_id)
			return list(user.get_lots() or [])
		except Exception as exc:
			logger.error(f"{LOGGER_PREFIX} Failed to load profile lots: {exc}")
	return []


def find_lot(cardinal: Cardinal, query: str | None) -> Any | None:
	lot_id = extract_lot_id(query)
	if not lot_id:
		return None

	for lot in get_profile_lots(cardinal):
		if str(getattr(lot, "id", "")) == str(lot_id):
			return lot
		if str(getattr(lot, "lot_id", "")) == str(lot_id):
			return lot
	return None


def get_viewed_lot(cardinal: Cardinal, context: TopicContext) -> ViewedLot:
	try:
		try:
			chat = cardinal.account.get_chat(context.fp_chat_id, with_history=False)
		except TypeError:
			chat = cardinal.account.get_chat(context.fp_chat_id)
	except Exception as exc:
		logger.error(f"{LOGGER_PREFIX} Failed to load viewed lot for {context.username}: {exc}")
		return ViewedLot(None, None, None)

	link = getattr(chat, "looking_link", None)
	text = getattr(chat, "looking_text", None)
	return ViewedLot(text, link, find_lot(cardinal, link))


def lot_public_link(lot: Any, fallback: str | None = None) -> str | None:
	return getattr(lot, "public_link", None) or fallback


def format_lot_details(lot: Any | None, viewed_text: str | None = None, viewed_link: str | None = None) -> str:
	if lot is None:
		lines = ["<b>Информация о лоте</b>"]
		if viewed_text:
			lines.append(f"\nПокупатель смотрит: <b>{escape(viewed_text)}</b>")
		if viewed_link:
			lines.append(f"Ссылка: {escape(viewed_link)}")
		lines.append("\nЛот не найден среди ваших активных лотов.")
		return "\n".join(lines)

	lines = ["<b>Информация о лоте</b>"]
	lot_id = getattr(lot, "id", None) or getattr(lot, "lot_id", None)
	if lot_id is not None:
		lines.append(f"\nID: <code>{escape(str(lot_id))}</code>")

	title = getattr(lot, "description", None) or getattr(lot, "title", None) or viewed_text
	if title:
		lines.append(f"Название: <b>{escape(str(title))}</b>")

	price = getattr(lot, "price", None)
	if price is not None:
		lines.append(f"Цена: <b>{escape(format_price(price, getattr(lot, 'currency', None)))}</b>")

	amount = getattr(lot, "amount", None)
	if amount is not None:
		lines.append(f"Количество: <b>{escape(str(amount))}</b>")

	server = getattr(lot, "server", None)
	if server:
		lines.append(f"Сервер: {escape(str(server))}")

	side = getattr(lot, "side", None)
	if side:
		lines.append(f"Сторона: {escape(str(side))}")

	subcategory = getattr(lot, "subcategory", None)
	category_text = format_subcategory(subcategory)
	if category_text:
		lines.append(f"Категория: {escape(category_text)}")

	link = lot_public_link(lot, viewed_link)
	if link:
		lines.append(f"Ссылка: {escape(str(link))}")

	return "\n".join(lines)


def format_price(price: Any, currency: Any = None) -> str:
	currency_text = ""
	if currency is not None:
		currency_text = getattr(currency, "code", None) or getattr(currency, "name", None) or str(currency)
	return f"{price:g} {currency_text}".strip() if isinstance(price, float) else f"{price} {currency_text}".strip()


def format_subcategory(subcategory: Any) -> str:
	if not subcategory:
		return ""

	name = getattr(subcategory, "name", None)
	category = getattr(subcategory, "category", None)
	category_name = getattr(category, "name", None)
	if category_name and name:
		return f"{category_name}, {name}"
	return str(name or category_name or "")
