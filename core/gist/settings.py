from __future__ import annotations

from copy import deepcopy
from typing import Any


GIST_FILENAME_MODES = ("off", "custom", "chat_sync", "order_id")
GIST_VISIBILITY_OPTIONS = {
	"secret": "по ссылке",
	"public": "публичный",
}

DEFAULT_GIST_SETTINGS = {
	"token": "",
	"visibility": "secret",
	"filename": {
		"mode": "off",
		"custom": "",
	},
}


def normalize_gist_settings(data: Any) -> dict[str, Any]:
	settings = deepcopy(DEFAULT_GIST_SETTINGS)
	if not isinstance(data, dict):
		return settings

	token = data.get("token")
	if isinstance(token, str):
		settings["token"] = token.strip()

	visibility = data.get("visibility")
	if isinstance(visibility, str) and visibility in GIST_VISIBILITY_OPTIONS:
		settings["visibility"] = visibility

	settings["filename"] = normalize_gist_filename_settings(data.get("filename"))
	return settings


def normalize_gist_filename_settings(data: Any) -> dict[str, str]:
	settings = deepcopy(DEFAULT_GIST_SETTINGS["filename"])
	if not isinstance(data, dict):
		return settings

	mode = data.get("mode")
	if isinstance(mode, str) and mode in GIST_FILENAME_MODES:
		settings["mode"] = mode

	custom = data.get("custom")
	if isinstance(custom, str):
		settings["custom"] = custom.strip()

	return settings


def gist_filename_mode_label(value: str) -> str:
	return {
		"off": "по умолчанию",
		"custom": "своё",
		"chat_sync": "клиент из Chat Sync",
		"order_id": "номер заказа",
	}.get(value, "по умолчанию")


def gist_visibility_label(value: str) -> str:
	return GIST_VISIBILITY_OPTIONS.get(value, GIST_VISIBILITY_OPTIONS["secret"])
