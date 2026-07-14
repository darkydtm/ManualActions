from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .client import PastebinError, create_paste, login
from .settings import normalize_pastebin_settings


PASTEBIN_VISIBILITY_PRIVATE = "2"


class PastebinConfigError(Exception):
	pass


@dataclass(frozen=True)
class PastebinResult:
	url: str


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


def resolve_paste_title(
	settings: dict[str, Any],
	chat_sync_username: str | None = None,
	order_id: str | None = None,
) -> str:
	config = normalize_pastebin_settings(settings)
	title = config["title"]
	mode = title["mode"]

	if mode == "custom":
		return title["custom"].strip()
	if mode == "chat_sync" and chat_sync_username:
		return chat_sync_username.strip()
	if mode == "order_id" and order_id:
		return order_id.strip().lstrip("#")
	return ""


def pastebin_config_errors(settings: dict[str, Any], order_id: str = "") -> list[str]:
	config = normalize_pastebin_settings(settings)
	errors = []
	has_dev_key = bool(config["api_dev_key"].strip())
	has_user_key = bool(config["api_user_key"].strip())
	has_username = bool(config["username"].strip())
	has_login_password = bool(config["login_password"])
	has_login_pair = has_username and has_login_password
	has_user_auth = has_user_key or has_login_pair

	if not has_dev_key:
		errors.append("API dev key не задан - Pastebin > Аккаунт и API.")
	if (has_username or has_login_password) and not has_login_pair:
		errors.append("Для входа нужны логин и пароль аккаунта - Pastebin > Аккаунт и API.")
	if config["visibility"] == PASTEBIN_VISIBILITY_PRIVATE and not has_user_auth:
		errors.append("Для приватной публикации нужен API user key или логин с паролем - Pastebin > Аккаунт и API.")
	if config["folder_key"].strip() and not has_user_auth:
		errors.append("Для папки нужен API user key или логин с паролем - Pastebin > Аккаунт и API.")
	if config["title"]["mode"] == "order_id" and not order_id.strip():
		errors.append("Для title по заказу укажите номер заказа: /pastebin #ORDER_ID <текст>.")

	return errors


def create_pastebin_url(
	settings: dict[str, Any],
	text: str,
	title: str = "",
	request_func: Any | None = None,
	login_request_func: Any | None = None,
) -> str:
	return create_pastebin(settings, text, title, request_func, login_request_func).url


def create_pastebin(
	settings: dict[str, Any],
	text: str,
	title: str = "",
	request_func: Any | None = None,
	login_request_func: Any | None = None,
) -> PastebinResult:
	api_user_key = resolve_api_user_key(settings, login_request_func)
	payload = build_paste_payload(settings, text, title, api_user_key)
	if request_func is None:
		url = create_paste(payload)
	else:
		url = create_paste(payload, request_func=request_func)
	return PastebinResult(url=url)


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
