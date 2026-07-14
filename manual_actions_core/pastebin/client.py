from __future__ import annotations

from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen


PASTEBIN_API_URL = "https://pastebin.com/api/api_post.php"
PASTEBIN_LOGIN_URL = "https://pastebin.com/api/api_login.php"
PASTEBIN_RAW_URL = "https://pastebin.com/raw/{key}"


class PastebinError(Exception):
	pass


def create_paste(payload: dict[str, str], request_func: Callable[..., Any] = urlopen, timeout: int = 15) -> str:
	body = post_form(PASTEBIN_API_URL, payload, request_func, timeout, "создать paste")
	if body.startswith("Bad API request"):
		raise PastebinError(body)
	if not body:
		raise PastebinError("Pastebin вернул пустой ответ.")

	return pastebin_raw_url(body)


def login(
	api_dev_key: str,
	username: str,
	password: str,
	request_func: Callable[..., Any] = urlopen,
	timeout: int = 15,
) -> str:
	body = post_form(
		PASTEBIN_LOGIN_URL,
		{
			"api_dev_key": api_dev_key,
			"api_user_name": username,
			"api_user_password": password,
		},
		request_func,
		timeout,
		"получить API user key",
	)
	if body.startswith("Bad API request"):
		raise PastebinError(body)
	if not body:
		raise PastebinError("Pastebin вернул пустой API user key.")
	return body


def post_form(
	url: str,
	payload: dict[str, str],
	request_func: Callable[..., Any],
	timeout: int,
	action: str,
) -> str:
	request = Request(
		url,
		data=urlencode(payload).encode("utf-8"),
		headers={"Content-Type": "application/x-www-form-urlencoded"},
	)
	try:
		with request_func(request, timeout=timeout) as response:
			return response.read().decode("utf-8", errors="replace").strip()
	except HTTPError as exc:
		raise PastebinError(f"Pastebin вернул HTTP {exc.code}.") from exc
	except URLError as exc:
		raise PastebinError(f"Не удалось подключиться к Pastebin: {exc.reason}") from exc
	except Exception as exc:
		raise PastebinError(f"Не удалось {action}: {exc}") from exc


def pastebin_raw_url(url: str) -> str:
	key = extract_paste_key(url)
	if not key:
		raise PastebinError("Pastebin вернул ссылку в неизвестном формате.")
	return PASTEBIN_RAW_URL.format(key=key)


def extract_paste_key(url: str) -> str:
	value = url.strip()
	if not value:
		return ""

	parsed = urlparse(value)
	if parsed.netloc:
		path = parsed.path.strip("/")
		if path.startswith("raw/"):
			return path.split("/", 1)[1].strip()
		return path.split("/", 1)[0].strip()

	return value
