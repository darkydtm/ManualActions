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
PASTEBIN_PASSWORD_MODES = ("off", "custom", "random")
PASTEBIN_VISIBILITY_OPTIONS = {
	"0": "публичный",
	"1": "по ссылке",
	"2": "приватный",
}

DEFAULT_PASTEBIN_SETTINGS = {
	"api_dev_key": "",
	"api_user_key": "",
	"username": "",
	"login_password": "",
	"expire_date": "N",
	"folder_key": "",
	"visibility": "1",
	"title": {
		"mode": "off",
		"custom": "",
	},
	"password": {
		"mode": "off",
		"custom": "",
		"length": 24,
	},
}


def normalize_pastebin_settings(data: Any) -> dict[str, Any]:
	settings = deepcopy(DEFAULT_PASTEBIN_SETTINGS)
	if not isinstance(data, dict):
		return settings

	for key in ("api_dev_key", "api_user_key", "username", "folder_key"):
		value = data.get(key)
		if isinstance(value, str):
			settings[key] = value.strip()

	login_password = data.get("login_password")
	if isinstance(login_password, str):
		settings["login_password"] = login_password

	expire_date = data.get("expire_date")
	if isinstance(expire_date, str) and expire_date in PASTEBIN_EXPIRATION_OPTIONS:
		settings["expire_date"] = expire_date

	visibility = data.get("visibility")
	if isinstance(visibility, str) and visibility in PASTEBIN_VISIBILITY_OPTIONS:
		settings["visibility"] = visibility

	settings["title"] = normalize_pastebin_title_settings(data.get("title"))
	settings["password"] = normalize_pastebin_password_settings(data.get("password"))
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


def normalize_pastebin_password_settings(data: Any) -> dict[str, Any]:
	settings = deepcopy(DEFAULT_PASTEBIN_SETTINGS["password"])
	if not isinstance(data, dict):
		return settings

	mode = data.get("mode")
	if isinstance(mode, str) and mode in PASTEBIN_PASSWORD_MODES:
		settings["mode"] = mode

	custom = data.get("custom")
	if isinstance(custom, str):
		settings["custom"] = custom

	length = data.get("length")
	if isinstance(length, int):
		settings["length"] = max(8, min(64, length))

	return settings


def pastebin_expiration_label(value: str) -> str:
	return PASTEBIN_EXPIRATION_OPTIONS.get(value, PASTEBIN_EXPIRATION_OPTIONS["N"])


def pastebin_title_mode_label(value: str) -> str:
	return {
		"off": "выключен",
		"custom": "свой",
		"chat_sync": "клиент из Chat Sync",
	}.get(value, "выключен")


def pastebin_visibility_label(value: str) -> str:
	return PASTEBIN_VISIBILITY_OPTIONS.get(value, PASTEBIN_VISIBILITY_OPTIONS["1"])


def pastebin_password_mode_label(value: str) -> str:
	return {
		"off": "выключен",
		"custom": "свой",
		"random": "случайный",
	}.get(value, "выключен")
