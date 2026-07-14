from __future__ import annotations

from typing import Any

from .client import PastebinError, create_paste, login
from .settings import normalize_pastebin_settings


PASTEBIN_VISIBILITY_PRIVATE = "2"


class PastebinConfigError(Exception):
	pass


def build_paste_payload(
	settings: dict[str, Any],
	text: str,
	title: str = "",
	api_user_key: str = "",
) -> dict[str, str]:
	config = normalize_pastebin_settings(settings)
	api_dev_key = config["api_dev_key"].strip()
	if not api_dev_key:
		raise PastebinConfigError("API dev key Pastebin не задан.")

	payload = {
		"api_dev_key": api_dev_key,
		"api_option": "paste",
		"api_paste_code": text,
		"api_paste_private": config["visibility"],
		"api_paste_expire_date": config["expire_date"],
	}

	resolved_user_key = api_user_key.strip() or config["api_user_key"].strip()
	if resolved_user_key:
		payload["api_user_key"] = resolved_user_key

	if config["visibility"] == PASTEBIN_VISIBILITY_PRIVATE and not resolved_user_key:
		raise PastebinConfigError("Для приватного Pastebin нужен API user key.")

	folder_key = config["folder_key"].strip()
	if folder_key:
		if not resolved_user_key:
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
	login_request_func: Any | None = None,
) -> str:
	api_user_key = resolve_api_user_key(settings, login_request_func)
	payload = build_paste_payload(settings, text, title, api_user_key)
	if request_func is None:
		return create_paste(payload)
	return create_paste(payload, request_func=request_func)


def resolve_api_user_key(settings: dict[str, Any], request_func: Any | None = None) -> str:
	config = normalize_pastebin_settings(settings)
	if config["api_user_key"]:
		return config["api_user_key"]
	if not config["username"] and not config["password"]:
		return ""
	if not config["api_dev_key"]:
		raise PastebinConfigError("API dev key Pastebin не задан.")
	if not config["username"] or not config["password"]:
		raise PastebinConfigError("Для входа Pastebin нужны логин и пароль.")
	if request_func is None:
		return login(config["api_dev_key"], config["username"], config["password"])
	return login(config["api_dev_key"], config["username"], config["password"], request_func=request_func)


def pastebin_error_text(exc: Exception) -> str:
	if isinstance(exc, (PastebinConfigError, PastebinError)):
		return str(exc)
	return f"Не удалось создать paste: {exc}"
