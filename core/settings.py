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

UPDATER_MODES = ("enabled", "disabled", "ask")

DEFAULT_UPDATER_SETTINGS = {
	"mode": "disabled",
	"check_interval_seconds": 3600,
	"skipped_version": "",
	"installed_version": "",
	"last_checked_version": "",
}

DEFAULT_SETTINGS = {
	"status": "1",
	"status_response_texts": DEFAULT_STATUS_RESPONSE_TEXTS,
	"status_auto_messages": DEFAULT_STATUS_AUTO_MESSAGES,
	"pastebin": DEFAULT_PASTEBIN_SETTINGS,
	"updater": DEFAULT_UPDATER_SETTINGS,
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
	settings["updater"] = normalize_updater_settings(data.get("updater"))
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


def normalize_updater_settings(data: Any) -> dict[str, Any]:
	settings = DEFAULT_UPDATER_SETTINGS.copy()
	if not isinstance(data, dict):
		return settings

	mode = data.get("mode")
	if mode in UPDATER_MODES:
		settings["mode"] = mode

	interval = data.get("check_interval_seconds")
	if isinstance(interval, int) and not isinstance(interval, bool) and interval > 0:
		settings["check_interval_seconds"] = interval

	for key in ("skipped_version", "installed_version", "last_checked_version"):
		value = data.get(key)
		if isinstance(value, str):
			settings[key] = value.strip()

	return settings
