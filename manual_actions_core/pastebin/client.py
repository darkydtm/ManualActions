from __future__ import annotations

import http.cookiejar
import secrets
from html.parser import HTMLParser
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import HTTPCookieProcessor, Request, build_opener, urlopen


PASTEBIN_API_URL = "https://pastebin.com/api/api_post.php"
PASTEBIN_LOGIN_URL = "https://pastebin.com/api/api_login.php"
PASTEBIN_HOME_URL = "https://pastebin.com/"
PASTEBIN_URL = "https://pastebin.com/{key}"
USER_AGENT = "ManualActionsPastebin/1.0"


class PastebinError(Exception):
	pass


def create_paste(payload: dict[str, str], request_func: Callable[..., Any] = urlopen, timeout: int = 15) -> str:
	body = post_form(PASTEBIN_API_URL, payload, request_func, timeout, "создать paste")
	if body.startswith("Bad API request"):
		raise PastebinError(body)
	if not body:
		raise PastebinError("Pastebin вернул пустой ответ.")

	return pastebin_url(body)


def create_password_paste(
	payload: dict[str, str],
	request_func: Callable[..., Any] | None = None,
	timeout: int = 15,
) -> str:
	if request_func is None:
		cookie_jar = http.cookiejar.CookieJar()
		request_func = build_opener(HTTPCookieProcessor(cookie_jar)).open

	try:
		with request_func(form_request(), timeout=timeout) as response:
			form_html = response.read().decode("utf-8", errors="replace")
		csrf_token = extract_csrf_token(form_html)
		if not csrf_token:
			raise PastebinError("Не удалось получить CSRF token Pastebin.")

		body, content_type = encode_multipart_form({
			"_csrf-frontend": csrf_token,
			**payload,
		})
		with request_func(form_request(body, content_type), timeout=timeout) as response:
			response_body = response.read().decode("utf-8", errors="replace")
			response_url = response.geturl() if hasattr(response, "geturl") else getattr(response, "url", "")
	except HTTPError as exc:
		raise PastebinError(f"Pastebin вернул HTTP {exc.code}.") from exc
	except URLError as exc:
		raise PastebinError(f"Не удалось подключиться к Pastebin: {exc.reason}") from exc
	except PastebinError:
		raise
	except Exception as exc:
		raise PastebinError(f"Не удалось создать paste через форму Pastebin: {exc}") from exc

	key = extract_paste_key(response_url) or extract_created_paste_key(response_body)
	if not key:
		raise PastebinError("Pastebin не вернул ссылку на публикацию.")
	return PASTEBIN_URL.format(key=key)


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
		headers={
			"Content-Type": "application/x-www-form-urlencoded",
			"User-Agent": USER_AGENT,
		},
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


def pastebin_url(url: str) -> str:
	key = extract_paste_key(url)
	if not key:
		raise PastebinError("Pastebin вернул ссылку в неизвестном формате.")
	return PASTEBIN_URL.format(key=key)


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


def form_request(body: bytes | None = None, content_type: str = "") -> Request:
	headers = {
		"User-Agent": USER_AGENT,
		"Referer": PASTEBIN_HOME_URL,
		"Origin": "https://pastebin.com",
	}
	if content_type:
		headers["Content-Type"] = content_type
	return Request(PASTEBIN_HOME_URL, data=body, headers=headers)


class CsrfTokenParser(HTMLParser):
	def __init__(self):
		super().__init__()
		self.token = ""

	def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
		if self.token or tag != "input":
			return
		values = dict(attrs)
		if values.get("name") == "_csrf-frontend":
			self.token = values.get("value") or ""


class PasteUrlParser(HTMLParser):
	def __init__(self):
		super().__init__()
		self.key = ""

	def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
		if self.key or tag != "link":
			return
		values = dict(attrs)
		if values.get("rel") != "canonical":
			return
		self.key = extract_paste_key(values.get("href") or "")


def extract_csrf_token(html: str) -> str:
	parser = CsrfTokenParser()
	parser.feed(html)
	return parser.token


def extract_created_paste_key(html: str) -> str:
	parser = PasteUrlParser()
	parser.feed(html)
	return parser.key


def encode_multipart_form(payload: dict[str, str]) -> tuple[bytes, str]:
	boundary = f"----manualactions{secrets.token_hex(16)}"
	lines = []
	for name, value in payload.items():
		lines.extend([
			f"--{boundary}",
			f'Content-Disposition: form-data; name="{name}"',
			"",
			str(value),
		])
	lines.append(f"--{boundary}--")
	lines.append("")
	body = "\r\n".join(lines).encode("utf-8")
	return body, f"multipart/form-data; boundary={boundary}"
