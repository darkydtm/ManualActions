from __future__ import annotations

from copy import deepcopy
from typing import Any


MAX_HISTORY_DEPTH = 100
MAX_MESSAGES_PER_MINUTE = 60
MIN_MESSAGES_PER_MINUTE = 5

BOOLEAN_KEYS = (
	"enabled",
	"hide_watermark",
	"show_ads",
	"show_image_name",
	"chat_url",
	"mono",
	"buyer_viewing",
	"edit_topic",
	"self_notify",
	"tag_admins_on_reply",
	"sync_on_start",
	"import_offered",
)

DEFAULT_CHAT_SYNC_SETTINGS = {
	"enabled": True,
	"chat_id": None,
	"hide_watermark": False,
	"show_ads": True,
	"show_image_name": True,
	"chat_url": False,
	"mono": False,
	"buyer_viewing": True,
	"edit_topic": True,
	"self_notify": True,
	"tag_admins_on_reply": False,
	"sync_on_start": True,
	"import_offered": False,
	"history_depth": 25,
	"messages_per_minute": 20,
}


def normalize_chat_sync_settings(data: Any) -> dict[str, Any]:
	settings = deepcopy(DEFAULT_CHAT_SYNC_SETTINGS)
	if not isinstance(data, dict):
		return settings

	for key in BOOLEAN_KEYS:
		value = data.get(key)
		if isinstance(value, bool):
			settings[key] = value

	settings["chat_id"] = normalize_chat_id(data.get("chat_id"))
	settings["history_depth"] = clamp_int(data.get("history_depth"), 0, MAX_HISTORY_DEPTH, settings["history_depth"])
	settings["messages_per_minute"] = clamp_int(
		data.get("messages_per_minute"),
		MIN_MESSAGES_PER_MINUTE,
		MAX_MESSAGES_PER_MINUTE,
		settings["messages_per_minute"],
	)
	return settings


def normalize_chat_id(value: Any) -> int | None:
	if isinstance(value, bool):
		return None
	if isinstance(value, int):
		return value
	if isinstance(value, str):
		candidate = value.strip()
		if candidate.lstrip("-").isdigit():
			return int(candidate)
	return None


def clamp_int(value: Any, minimum: int, maximum: int, fallback: int) -> int:
	if isinstance(value, bool) or not isinstance(value, int):
		return fallback
	return max(minimum, min(maximum, value))
