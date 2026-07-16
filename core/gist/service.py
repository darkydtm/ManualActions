from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePath
import re
from typing import Any

from .client import GistError, create_gist
from .settings import normalize_gist_settings


DEFAULT_GIST_FILENAME = "manual-actions.txt"


class GistConfigError(Exception):
	pass


@dataclass(frozen=True)
class GistResult:
	url: str


def build_gist_payload(
	settings: dict[str, Any],
	text: str,
	filename: str = "",
) -> dict[str, Any]:
	config = normalize_gist_settings(settings)
	resolved_filename = normalize_gist_filename(filename or DEFAULT_GIST_FILENAME)
	return {
		"description": "Created by Manual Actions",
		"public": config["visibility"] == "public",
		"files": {
			resolved_filename: {
				"content": text,
			},
		},
	}


def resolve_gist_filename(
	settings: dict[str, Any],
	chat_sync_username: str | None = None,
	order_id: str | None = None,
) -> str:
	config = normalize_gist_settings(settings)
	filename = config["filename"]
	mode = filename["mode"]

	if mode == "custom":
		value = filename["custom"]
	elif mode == "chat_sync":
		value = chat_sync_username or ""
	elif mode == "order_id":
		value = (order_id or "").lstrip("#")
	else:
		value = DEFAULT_GIST_FILENAME

	return normalize_gist_filename(value)


def normalize_gist_filename(value: str) -> str:
	filename = re.sub(r"[\\/\x00-\x1f\x7f]+", "-", value).strip(" .-")
	if not filename:
		return DEFAULT_GIST_FILENAME
	if not PurePath(filename).suffix:
		filename = f"{filename}.txt"
	return filename


def gist_config_errors(settings: dict[str, Any], order_id: str = "") -> list[str]:
	config = normalize_gist_settings(settings)
	errors = []
	mode = config["filename"]["mode"]

	if not config["token"]:
		errors.append("GitHub token не задан - GitHub Gists > Token.")
	if mode == "custom" and not config["filename"]["custom"]:
		errors.append("Укажите своё имя файла - GitHub Gists > Имя файла.")
	if mode == "order_id" and not order_id.strip():
		errors.append("Для имени файла по заказу укажите номер заказа: /gist #ORDER_ID <текст>.")

	return errors


def create_gist_result(
	settings: dict[str, Any],
	text: str,
	filename: str = "",
	request_func: Any | None = None,
) -> GistResult:
	config = normalize_gist_settings(settings)
	token = config["token"]
	if not token:
		raise GistConfigError("GitHub token не задан.")

	payload = build_gist_payload(config, text, filename)
	if request_func is None:
		url = create_gist(payload, token)
	else:
		url = create_gist(payload, token, request_func=request_func)
	return GistResult(url=url)


def gist_error_text(exc: Exception) -> str:
	if isinstance(exc, (GistConfigError, GistError)):
		return str(exc)
	return f"Не удалось создать gist: {exc}"
