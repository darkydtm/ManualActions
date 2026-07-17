from __future__ import annotations

import io
import json
import unittest
from urllib.error import HTTPError, URLError

from core.gist.client import GistError, create_gist
from core.gist.service import (
	GistConfigError,
	build_gist_payload,
	create_gist_result,
	gist_config_errors,
	normalize_gist_filename,
	resolve_gist_filename,
)


class FakeResponse:
	def __init__(self, text: str):
		self.text = text

	def __enter__(self):
		return self

	def __exit__(self, exc_type, exc, traceback):
		return False

	def read(self):
		return self.text.encode("utf-8")


class GistServiceTest(unittest.TestCase):
	def test_builds_secret_gist_payload(self):
		payload = build_gist_payload(
			{"visibility": "secret"},
			"Body",
		)

		self.assertEqual(payload["description"], "Created by Manual Actions")
		self.assertIs(payload["public"], False)
		self.assertEqual(payload["files"], {"manual-actions.txt": {"content": "Body"}})

	def test_builds_public_gist_payload_with_filename(self):
		payload = build_gist_payload(
			{"visibility": "public"},
			"Body",
			"notes.md",
		)

		self.assertIs(payload["public"], True)
		self.assertEqual(payload["files"], {"notes.md": {"content": "Body"}})

	def test_requires_token_before_creation(self):
		with self.assertRaisesRegex(GistConfigError, "GitHub token"):
			create_gist_result({}, "Body")

	def test_creates_gist_through_api(self):
		requests = []

		def request_func(request, timeout=15):
			requests.append((request, timeout))
			return FakeResponse(json.dumps({
				"html_url": "https://gist.github.com/user/id",
				"files": {
					"notes.txt": {
						"raw_url": "https://gist.githubusercontent.com/user/id/raw/revision/notes.txt",
					},
				},
			}))

		result = create_gist_result(
			{"token": "token", "visibility": "secret"},
			"Текст",
			"notes",
			request_func=request_func,
		)
		request, timeout = requests[0]
		body = json.loads(request.data.decode("utf-8"))

		self.assertEqual(
			result.url,
			"https://gist.githubusercontent.com/user/id/raw/revision/notes.txt",
		)
		self.assertEqual(request.full_url, "https://api.github.com/gists")
		self.assertEqual(request.get_method(), "POST")
		self.assertEqual(request.get_header("Authorization"), "Bearer token")
		self.assertEqual(request.get_header("Accept"), "application/vnd.github+json")
		self.assertEqual(request.get_header("X-github-api-version"), "2022-11-28")
		self.assertEqual(request.get_header("User-agent"), "ManualActionsGist/1.0")
		self.assertEqual(body["files"], {"notes.txt": {"content": "Текст"}})
		self.assertEqual(timeout, 15)

	def test_rejects_missing_raw_url(self):
		with self.assertRaisesRegex(GistError, "raw-ссылку"):
			create_gist({}, "token", lambda request, timeout=15: FakeResponse("{}"))

	def test_rejects_invalid_raw_url(self):
		response = json.dumps({"files": {"notes.txt": {"raw_url": ""}}})

		with self.assertRaisesRegex(GistError, "raw-ссылку"):
			create_gist({}, "token", lambda request, timeout=15: FakeResponse(response))

	def test_rejects_malformed_json(self):
		with self.assertRaisesRegex(GistError, "некорректный JSON"):
			create_gist({}, "token", lambda request, timeout=15: FakeResponse("invalid"))

	def test_preserves_github_http_error_message(self):
		def request_func(request, timeout=15):
			raise HTTPError(
				request.full_url,
				422,
				"Unprocessable Entity",
				None,
				io.BytesIO(b'{"message":"Validation Failed"}'),
			)

		with self.assertRaisesRegex(GistError, "GitHub: Validation Failed"):
			create_gist({}, "token", request_func)

	def test_falls_back_to_http_status_for_empty_error_body(self):
		def request_func(request, timeout=15):
			raise HTTPError(request.full_url, 500, "Server Error", None, io.BytesIO(b""))

		with self.assertRaisesRegex(GistError, "GitHub вернул HTTP 500\\."):
			create_gist({}, "token", request_func)

	def test_reports_connection_error(self):
		def request_func(request, timeout=15):
			raise URLError("offline")

		with self.assertRaisesRegex(GistError, "подключиться к GitHub"):
			create_gist({}, "token", request_func)

	def test_resolves_default_filename(self):
		self.assertEqual(resolve_gist_filename({}), "manual-actions.txt")

	def test_resolves_custom_filename(self):
		filename = resolve_gist_filename({
			"filename": {
				"mode": "custom",
				"custom": "notes.md",
			},
		})

		self.assertEqual(filename, "notes.md")

	def test_resolves_chat_sync_filename(self):
		filename = resolve_gist_filename({
			"filename": {
				"mode": "chat_sync",
			},
		}, "buyer")

		self.assertEqual(filename, "buyer.txt")

	def test_resolves_order_id_filename(self):
		filename = resolve_gist_filename({
			"filename": {
				"mode": "order_id",
			},
		}, order_id="#ABC123")

		self.assertEqual(filename, "ABC123.txt")

	def test_sanitizes_filename(self):
		self.assertEqual(normalize_gist_filename(" ../buyer/name\n"), "buyer-name.txt")

	def test_reports_missing_configuration(self):
		errors = gist_config_errors({
			"filename": {
				"mode": "custom",
				"custom": "",
			},
		})

		self.assertEqual(len(errors), 2)
		self.assertIn("GitHub token", errors[0])
		self.assertIn("имя файла", errors[1])

	def test_reports_missing_order_id(self):
		errors = gist_config_errors({
			"token": "token",
			"filename": {
				"mode": "order_id",
			},
		})

		self.assertEqual(errors, ["Для имени файла по заказу укажите номер заказа: /gist #ORDER_ID <текст>."])


if __name__ == "__main__":
	unittest.main()
