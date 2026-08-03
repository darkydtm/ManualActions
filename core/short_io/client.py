from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


SHORT_IO_LINKS_API_URL = "https://api.short.io/links"
USER_AGENT = "ManualActionsShortIo/1.0"


@dataclass(frozen=True)
class ShortLinkResult:
	url: str
	duplicate: bool


class ShortIoError(Exception):
	pass


def create_short_link(
	api_key: str,
	domain: str,
	original_url: str,
	request_func: Callable[..., Any] = urlopen,
	timeout: int = 15,
) -> ShortLinkResult:
	payload = {
		"allowDuplicates": False,
		"originalURL": original_url,
		"domain": domain,
	}
	request = Request(
		SHORT_IO_LINKS_API_URL,
		data=json.dumps(payload).encode("utf-8"),
		headers={
			"Accept": "application/json",
			"Authorization": api_key,
			"Content-Type": "application/json",
			"User-Agent": USER_AGENT,
		},
		method="POST",
	)
	data = read_short_io_response(request, request_func, timeout)
	url = data.get("secureShortURL") or data.get("shortURL")
	if not isinstance(url, str) or not url.strip():
		raise ShortIoError("Short.io не вернул короткую ссылку.")
	return ShortLinkResult(url.strip(), data.get("duplicate") is True)


def read_short_io_response(
	request: Request,
	request_func: Callable[..., Any],
	timeout: int,
) -> dict[str, Any]:
	try:
		with request_func(request, timeout=timeout) as response:
			body = response.read().decode("utf-8", errors="replace")
	except HTTPError as exc:
		raise ShortIoError(http_error_message(exc)) from exc
	except URLError as exc:
		raise ShortIoError(f"Не удалось подключиться к Short.io: {exc.reason}") from exc
	except Exception as exc:
		raise ShortIoError(f"Не удалось создать короткую ссылку: {exc}") from exc

	try:
		data = json.loads(body)
	except json.JSONDecodeError as exc:
		raise ShortIoError("Short.io вернул некорректный JSON.") from exc
	if not isinstance(data, dict):
		raise ShortIoError("Short.io вернул некорректный ответ.")
	return data


def http_error_message(exc: HTTPError) -> str:
	try:
		body = exc.read().decode("utf-8", errors="replace").strip()
		if not body:
			return f"Short.io вернул HTTP {exc.code}."
		try:
			data = json.loads(body)
		except json.JSONDecodeError:
			return body
		if isinstance(data, dict):
			for field in ("error", "message"):
				message = data.get(field)
				if isinstance(message, str) and message.strip():
					return f"Short.io: {message.strip()}"
		return body
	finally:
		exc.close()
