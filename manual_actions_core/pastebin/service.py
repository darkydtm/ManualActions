from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .client import PastebinError, create_paste, login
from .passwords import ProtectedText, generate_password, protect_text
from .settings import normalize_pastebin_settings


PASTEBIN_VISIBILITY_PRIVATE = "2"


class PastebinConfigError(Exception):
	pass


@dataclass(frozen=True)
class PastebinResult:
	raw_url: str
	password: str
	protected: bool


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


def prepare_paste_text(settings: dict[str, Any], text: str) -> ProtectedText:
	config = normalize_pastebin_settings(settings)
	password_settings = config["password"]
	mode = password_settings["mode"]

	if mode == "off":
		return ProtectedText(text=text, password="", protected=False)

	if mode == "custom":
		password = password_settings["custom"].strip()
		if not password:
			raise PastebinConfigError("Свой пароль Pastebin не задан.")
	else:
		password = generate_password(password_settings["length"])

	return ProtectedText(text=protect_text(text, password), password=password, protected=True)


def create_pastebin_raw_url(
	settings: dict[str, Any],
	text: str,
	title: str = "",
	request_func: Any | None = None,
	login_request_func: Any | None = None,
) -> str:
	return create_pastebin(settings, text, title, request_func, login_request_func).raw_url


def create_pastebin(
	settings: dict[str, Any],
	text: str,
	title: str = "",
	request_func: Any | None = None,
	login_request_func: Any | None = None,
) -> PastebinResult:
	prepared = prepare_paste_text(settings, text)
	api_user_key = resolve_api_user_key(settings, login_request_func)
	payload = build_paste_payload(settings, prepared.text, title, api_user_key)
	if request_func is None:
		raw_url = create_paste(payload)
	else:
		raw_url = create_paste(payload, request_func=request_func)
	return PastebinResult(raw_url=raw_url, password=prepared.password, protected=prepared.protected)


def resolve_api_user_key(settings: dict[str, Any], request_func: Any | None = None) -> str:
	config = normalize_pastebin_settings(settings)
	if config["api_user_key"]:
		return config["api_user_key"]
	if not config["username"] and not config["login_password"]:
		return ""
	if not config["api_dev_key"]:
		raise PastebinConfigError("API dev key Pastebin не задан.")
	if not config["username"] or not config["login_password"]:
		raise PastebinConfigError("Для входа Pastebin нужны логин и пароль.")
	if request_func is None:
		return login(config["api_dev_key"], config["username"], config["login_password"])
	return login(config["api_dev_key"], config["username"], config["login_password"], request_func=request_func)


def pastebin_error_text(exc: Exception) -> str:
	if isinstance(exc, (PastebinConfigError, PastebinError)):
		return str(exc)
	return f"Не удалось создать paste: {exc}"
