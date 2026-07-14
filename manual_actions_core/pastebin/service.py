from __future__ import annotations

from typing import Any

from .client import PastebinError, create_paste
from .settings import normalize_pastebin_settings


PASTEBIN_PRIVATE_UNLISTED = "1"


class PastebinConfigError(Exception):
	pass


def build_paste_payload(settings: dict[str, Any], text: str, title: str = "") -> dict[str, str]:
	config = normalize_pastebin_settings(settings)
	api_dev_key = config["api_dev_key"].strip()
	if not api_dev_key:
		raise PastebinConfigError("API dev key Pastebin не задан.")

	payload = {
		"api_dev_key": api_dev_key,
		"api_option": "paste",
		"api_paste_code": text,
		"api_paste_private": PASTEBIN_PRIVATE_UNLISTED,
		"api_paste_expire_date": config["expire_date"],
	}

	api_user_key = config["api_user_key"].strip()
	if api_user_key:
		payload["api_user_key"] = api_user_key

	folder_key = config["folder_key"].strip()
	if folder_key:
		if not api_user_key:
			raise PastebinConfigError("Для папки Pastebin нужен API user key.")
		payload["api_folder_key"] = folder_key

	title = title.strip()
	if title:
		payload["api_paste_name"] = title

	return payload


def resolve_paste_title(settings: dict[str, Any], chat_sync_username: str | None = None) -> str:
	config = normalize_pastebin_settings(settings)
	title = config["title"]
	mode = title["mode"]

	if mode == "custom":
		return title["custom"].strip()
	if mode == "chat_sync" and chat_sync_username:
		return chat_sync_username.strip()
	return ""


def create_pastebin_raw_url(
	settings: dict[str, Any],
	text: str,
	title: str = "",
	request_func: Any | None = None,
) -> str:
	payload = build_paste_payload(settings, text, title)
	if request_func is None:
		return create_paste(payload)
	return create_paste(payload, request_func=request_func)


def pastebin_error_text(exc: Exception) -> str:
	if isinstance(exc, (PastebinConfigError, PastebinError)):
		return str(exc)
	return f"Не удалось создать paste: {exc}"
