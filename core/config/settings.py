from __future__ import annotations

from copy import deepcopy
from typing import Any

from ..gemini.settings import DEFAULT_GEMINI_DELIVERY_SETTINGS, normalize_gemini_delivery_settings
from ..gist.settings import DEFAULT_GIST_SETTINGS, normalize_gist_settings
from ..status.status import STATUS_IDS, normalize_status_id


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
	"notified_version": "",
}

DEFAULT_TWO_FACTOR_SETTINGS = {
	"label": "2FA: ",
}

DEFAULT_SETTINGS = {
	"status": "1",
	"status_response_texts": DEFAULT_STATUS_RESPONSE_TEXTS,
	"status_auto_messages": DEFAULT_STATUS_AUTO_MESSAGES,
	"templates": [],
	"gemini_delivery": DEFAULT_GEMINI_DELIVERY_SETTINGS,
	"gist": DEFAULT_GIST_SETTINGS,
	"updater": DEFAULT_UPDATER_SETTINGS,
	"two_factor": DEFAULT_TWO_FACTOR_SETTINGS,
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
	settings["templates"] = normalize_templates(data.get("templates"))
	settings["gemini_delivery"] = normalize_gemini_delivery_settings(data.get("gemini_delivery"))
	settings["gist"] = normalize_gist_settings(data.get("gist"))
	settings["updater"] = normalize_updater_settings(data.get("updater"))
	settings["two_factor"] = normalize_two_factor_settings(data.get("two_factor"))
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


def normalize_templates(data: Any) -> list[dict[str, str]]:
	if not isinstance(data, list):
		return []

	templates = []
	seen_ids = set()
	for item in data:
		if not isinstance(item, dict):
			continue

		template_id = item.get("id")
		title = item.get("title")
		text = item.get("text")
		if not isinstance(template_id, str) or not isinstance(title, str) or not isinstance(text, str):
			continue

		template_id = template_id.strip()
		title = title.strip()
		if not template_id or not title or template_id in seen_ids:
			continue

		seen_ids.add(template_id)
		templates.append({
			"id": template_id,
			"title": title,
			"text": text,
		})

	return templates


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

	for key in ("skipped_version", "installed_version", "last_checked_version", "notified_version"):
		value = data.get(key)
		if isinstance(value, str):
			settings[key] = value.strip()

	return settings


def normalize_two_factor_settings(data: Any) -> dict[str, str]:
	settings = DEFAULT_TWO_FACTOR_SETTINGS.copy()
	if not isinstance(data, dict):
		return settings

	label = data.get("label")
	if isinstance(label, str) and label.strip():
		settings["label"] = label.strip()
	return settings
