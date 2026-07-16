from __future__ import annotations

import json
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


GITHUB_GISTS_API_URL = "https://api.github.com/gists"
USER_AGENT = "ManualActionsGist/1.0"


class GistError(Exception):
	pass


def create_gist(
	payload: dict[str, Any],
	token: str,
	request_func: Callable[..., Any] = urlopen,
	timeout: int = 15,
) -> str:
	request = Request(
		GITHUB_GISTS_API_URL,
		data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
		headers={
			"Accept": "application/vnd.github+json",
			"Authorization": f"Bearer {token}",
			"Content-Type": "application/json",
			"User-Agent": USER_AGENT,
			"X-GitHub-Api-Version": "2022-11-28",
		},
		method="POST",
	)
	try:
		with request_func(request, timeout=timeout) as response:
			body = response.read().decode("utf-8", errors="replace")
	except HTTPError as exc:
		raise GistError(http_error_message(exc)) from exc
	except URLError as exc:
		raise GistError(f"Не удалось подключиться к GitHub: {exc.reason}") from exc
	except Exception as exc:
		raise GistError(f"Не удалось создать gist: {exc}") from exc

	try:
		data = json.loads(body)
	except json.JSONDecodeError as exc:
		raise GistError("GitHub вернул некорректный JSON.") from exc

	if not isinstance(data, dict):
		raise GistError("GitHub вернул некорректный ответ.")

	url = data.get("html_url")
	if not isinstance(url, str) or not url.strip():
		raise GistError("GitHub не вернул ссылку на gist.")
	return url.strip()


def http_error_message(exc: HTTPError) -> str:
	try:
		body = exc.read().decode("utf-8", errors="replace").strip()
		if body:
			try:
				data = json.loads(body)
			except json.JSONDecodeError:
				return body
			if isinstance(data, dict):
				message = data.get("message")
				if isinstance(message, str) and message.strip():
					return f"GitHub: {message.strip()}"
			return body
		return f"GitHub вернул HTTP {exc.code}."
	finally:
		exc.close()
