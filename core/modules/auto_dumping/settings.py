from __future__ import annotations

from copy import deepcopy
import re
from typing import Any
from uuid import uuid4


DEFAULT_AUTO_DUMPING_SETTINGS = {
	"enabled": False,
	"interval_minutes": 5,
	"rules": [],
}

INTERVAL_PRESETS = (1, 3, 5, 10, 30)


def normalize_auto_dumping_settings(data: Any) -> dict[str, Any]:
	settings = deepcopy(DEFAULT_AUTO_DUMPING_SETTINGS)
	if not isinstance(data, dict):
		return settings
	if isinstance(data.get("enabled"), bool):
		settings["enabled"] = data["enabled"]
	interval = data.get("interval_minutes")
	if isinstance(interval, int) and not isinstance(interval, bool) and interval > 0:
		settings["interval_minutes"] = interval
	seen: set[tuple[int, tuple[str, ...]]] = set()
	for item in data.get("rules", []):
		rule = normalize_rule(item)
		if not rule:
			continue
		key = (rule["subcategory"], tuple(word.casefold() for word in rule["keywords"]))
		if key in seen:
			continue
		seen.add(key)
		settings["rules"].append(rule)
	return settings


def normalize_rule(data: Any) -> dict[str, Any] | None:
	if not isinstance(data, dict):
		return None
	rule_id = str(data.get("id") or "")
	if not rule_id.strip():
		rule_id = uuid4().hex
	subcategory = parse_subcategory_id(data.get("subcategory"))
	keywords = normalize_words(data.get("keywords"))
	if subcategory is None or not keywords:
		return None
	keyword_mode = data.get("keyword_mode", "any")
	if keyword_mode not in ("any", "all"):
		keyword_mode = "any"
	price_mode = data.get("price_mode", "fixed")
	if price_mode not in ("fixed", "percent"):
		price_mode = "fixed"
	competitor_min_price = nonnegative_number(data.get("competitor_min_price"), 0.0)
	dumping_value = positive_number(data.get("dumping_value", 1))
	if dumping_value is None:
		return None
	return {
		"id": rule_id,
		"enabled": data.get("enabled") is not False,
		"subcategory": subcategory,
		"keywords": keywords,
		"keyword_mode": keyword_mode,
		"competitor_min_price": competitor_min_price,
		"price_mode": price_mode,
		"dumping_value": dumping_value,
		"own_min_price": nonnegative_number(data.get("own_min_price"), 0.0),
		"sellers_blacklist": normalize_words(data.get("sellers_blacklist")),
		"keywords_blacklist": normalize_words(data.get("keywords_blacklist")),
	}


SUBCATEGORY_URL_RE = re.compile(r"/lots/(\d+)")


def parse_subcategory_id(value: Any) -> int | None:
	if isinstance(value, bool):
		return None
	if isinstance(value, int):
		return value if value > 0 else None
	if isinstance(value, float):
		return int(value) if value.is_integer() and value > 0 else None
	if isinstance(value, str):
		text = value.strip()
		if re.fullmatch(r"\d+", text):
			result = int(text)
			return result if result > 0 else None
		match = SUBCATEGORY_URL_RE.search(text)
		if match:
			return int(match.group(1))
	return None


def normalize_words(value: Any) -> list[str]:
	if not isinstance(value, (list, tuple)):
		return []
	result = []
	seen = set()
	for item in value:
		if not isinstance(item, str):
			continue
		word = item.strip()
		key = word.casefold()
		if not word or key in seen:
			continue
		seen.add(key)
		result.append(word)
	return result


def nonnegative_number(value: Any, fallback: float) -> float:
	if isinstance(value, bool):
		return fallback
	try:
		result = float(value) if value is not None else fallback
	except (TypeError, ValueError):
		return fallback
	return result if result >= 0 else fallback


def positive_number(value: Any) -> float | None:
	if isinstance(value, bool):
		return None
	try:
		result = float(value)
	except (TypeError, ValueError):
		return None
	return result if result > 0 else None
