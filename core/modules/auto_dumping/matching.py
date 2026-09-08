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


def matches_subcategory(lot: Any, rule_subcategory: str) -> bool:
	wanted = str(rule_subcategory or "").strip().casefold()
	if not wanted:
		return False
	aliases = {str(getattr(lot, "subcategory", "") or "").strip().casefold()}
	raw_subcategory = getattr(getattr(lot, "raw", None), "subcategory", None)
	if isinstance(raw_subcategory, (str, int, float)):
		aliases.add(str(raw_subcategory).strip().casefold())
	elif raw_subcategory is not None:
		for attr in ("id", "name", "fullname"):
			value = getattr(raw_subcategory, attr, None)
			if value is not None and str(value).strip():
				aliases.add(str(value).strip().casefold())
	aliases.discard("")
	return wanted in aliases
