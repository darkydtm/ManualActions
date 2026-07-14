from __future__ import annotations

from copy import deepcopy
from typing import Any


PASTEBIN_EXPIRATION_OPTIONS = {
	"N": "Никогда",
	"10M": "10 минут",
	"1H": "1 час",
	"1D": "1 день",
	"1W": "1 неделя",
	"2W": "2 недели",
	"1M": "1 месяц",
	"6M": "6 месяцев",
	"1Y": "1 год",
}

PASTEBIN_TITLE_MODES = ("off", "custom", "chat_sync")

DEFAULT_PASTEBIN_SETTINGS = {
	"api_dev_key": "",
	"api_user_key": "",
	"expire_date": "N",
	"folder_key": "",
	"title": {
		"mode": "off",
		"custom": "",
	},
}


def normalize_pastebin_settings(data: Any) -> dict[str, Any]:
	settings = deepcopy(DEFAULT_PASTEBIN_SETTINGS)
	if not isinstance(data, dict):
		return settings

	for key in ("api_dev_key", "api_user_key", "folder_key"):
		value = data.get(key)
		if isinstance(value, str):
			settings[key] = value.strip()

	expire_date = data.get("expire_date")
	if isinstance(expire_date, str) and expire_date in PASTEBIN_EXPIRATION_OPTIONS:
		settings["expire_date"] = expire_date

	settings["title"] = normalize_pastebin_title_settings(data.get("title"))
	return settings


def normalize_pastebin_title_settings(data: Any) -> dict[str, str]:
	settings = deepcopy(DEFAULT_PASTEBIN_SETTINGS["title"])
	if not isinstance(data, dict):
		return settings

	mode = data.get("mode")
	if isinstance(mode, str) and mode in PASTEBIN_TITLE_MODES:
		settings["mode"] = mode

	custom = data.get("custom")
	if isinstance(custom, str):
		settings["custom"] = custom.strip()

	return settings


def pastebin_expiration_label(value: str) -> str:
	return PASTEBIN_EXPIRATION_OPTIONS.get(value, PASTEBIN_EXPIRATION_OPTIONS["N"])


def pastebin_title_mode_label(value: str) -> str:
	return {
		"off": "выключен",
		"custom": "свой",
		"chat_sync": "клиент из Chat Sync",
	}.get(value, "выключен")

