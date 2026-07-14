from __future__ import annotations

from copy import deepcopy
from typing import Any

from .pastebin.settings import DEFAULT_PASTEBIN_SETTINGS, normalize_pastebin_settings
from .status import STATUS_IDS, normalize_status_id


DEFAULT_STATUS_RESPONSE_TEXTS = {
	"0": "Сейчас я недоступен. Отвечу позже.",
	"1": "Сейчас я доступен.",
	"2": "Сейчас сильная загруженность. Ответ может занять больше времени.",
}

DEFAULT_STATUS_AUTO_MESSAGES = {
	"0": {
		"enabled": False,
		"text": "Сейчас я недоступен. Отвечу позже.",
	},
	"1": {
		"enabled": False,
		"text": "",
	},
	"2": {
		"enabled": False,
		"text": "Сейчас сильная загруженность. Ответ может занять больше времени.",
	},
}

DEFAULT_SETTINGS = {
	"status": "1",
	"status_response_texts": DEFAULT_STATUS_RESPONSE_TEXTS,
	"status_auto_messages": DEFAULT_STATUS_AUTO_MESSAGES,
	"pastebin": DEFAULT_PASTEBIN_SETTINGS,
}


def normalize_settings(data: dict[str, Any] | None) -> dict[str, Any]:
	settings = deepcopy(DEFAULT_SETTINGS)
	if not isinstance(data, dict):
		return settings

	settings["status"] = normalize_status_id(data.get("status", settings["status"]))
	settings["status_response_texts"] = normalize_text_map(
		data.get("status_response_texts"),
		DEFAULT_STATUS_RESPONSE_TEXTS,
	)
	settings["status_auto_messages"] = normalize_auto_messages(data.get("status_auto_messages"))
	settings["pastebin"] = normalize_pastebin_settings(data.get("pastebin"))
	return settings


def normalize_text_map(data: Any, defaults: dict[str, str]) -> dict[str, str]:
	texts = defaults.copy()
	if not isinstance(data, dict):
		return texts

	for status_id in STATUS_IDS:
		value = data.get(status_id)
		if isinstance(value, str):
			texts[status_id] = value

	return texts


def normalize_auto_messages(data: Any) -> dict[str, dict[str, bool | str]]:
	messages = deepcopy(DEFAULT_STATUS_AUTO_MESSAGES)
	if not isinstance(data, dict):
		return messages

	for status_id in STATUS_IDS:
		value = data.get(status_id)
		if not isinstance(value, dict):
			continue

		enabled = value.get("enabled")
		text = value.get("text")
		if isinstance(enabled, bool):
			messages[status_id]["enabled"] = enabled
		if isinstance(text, str):
			messages[status_id]["text"] = text

	return messages
