from __future__ import annotations

import re
from typing import Any


def match_keywords(title: str, keywords: tuple[str, ...], mode: str) -> int:
	text = title.casefold()
	matches = sum(1 for keyword in keywords if keyword.casefold() in text)
	if mode == "all" and matches != len(keywords):
		return 0
	return matches


def is_blacklisted(
	username: str,
	title: str,
	sellers: tuple[str, ...],
	keywords: tuple[str, ...],
) -> bool:
	if username.casefold() in {seller.casefold() for seller in sellers}:
		return True
	words = {word.casefold() for word in re.findall(r"\w+", title, flags=re.UNICODE)}
	return any(keyword.casefold() in words for keyword in keywords)


def matches_subcategory(lot: Any, subcategory_id: int) -> bool:
	if isinstance(subcategory_id, bool):
		return False
	try:
		wanted = int(subcategory_id)
	except (TypeError, ValueError):
		return False
	actual = getattr(lot, "subcategory_id", None)
	if isinstance(actual, bool):
		return False
	try:
		return int(actual) == wanted
	except (TypeError, ValueError):
		return False
