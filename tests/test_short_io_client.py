from __future__ import annotations

import io
import json
import unittest
from urllib.error import HTTPError, URLError

from core.short_io.client import ShortIoError, create_short_link


LONG_URL = "https://serviceactivation.google.com/subscription/new/token"


class FakeResponse:
	def __init__(self, data):
		self.data = data

	def __enter__(self):
		return self

	def __exit__(self, exc_type, exc, traceback):
		return False

	def read(self):
		if isinstance(self.data, bytes):
			return self.data
		return json.dumps(self.data).encode("utf-8")


class ShortIoClientTest(unittest.TestCase):
	def test_creates_short_link_with_expected_request(self):
		requests = []

		def request_func(request, timeout=15):
			requests.append((request, timeout))
			return FakeResponse({
				"secureShortURL": "https://redirectlink.s.gy/abc",
				"duplicate": True,
			})

		result = create_short_link(
			"secret",
			"redirectlink.s.gy",
			LONG_URL,
			request_func=request_func,
		)

		request, timeout = requests[0]
		payload = json.loads(request.data.decode("utf-8"))
		self.assertEqual(request.full_url, "https://api.short.io/links")
		self.assertEqual(request.get_method(), "POST")
		self.assertEqual(request.get_header("Authorization"), "secret")
		self.assertEqual(request.get_header("Accept"), "application/json")
		self.assertEqual(request.get_header("Content-type"), "application/json")
		self.assertEqual(request.get_header("User-agent"), "ManualActionsShortIo/1.0")
		self.assertEqual(payload, {
			"allowDuplicates": False,
			"originalURL": LONG_URL,
			"domain": "redirectlink.s.gy",
		})
		self.assertEqual(timeout, 15)
		self.assertEqual(result.url, "https://redirectlink.s.gy/abc")
		self.assertTrue(result.duplicate)

	def test_falls_back_to_short_url(self):
		result = create_short_link(
			"secret",
			"redirectlink.s.gy",
			LONG_URL,
			request_func=lambda request, timeout=15: FakeResponse({
				"shortURL": "http://redirectlink.s.gy/abc",
				"duplicate": False,
			}),
		)

		self.assertEqual(result.url, "http://redirectlink.s.gy/abc")
		self.assertFalse(result.duplicate)

	def test_rejects_missing_short_url(self):
		with self.assertRaisesRegex(ShortIoError, "не вернул короткую ссылку"):
			create_short_link(
				"secret",
				"redirectlink.s.gy",
				LONG_URL,
				request_func=lambda request, timeout=15: FakeResponse({"success": True}),
			)

	def test_rejects_malformed_json(self):
		with self.assertRaisesRegex(ShortIoError, "некорректный JSON"):
			create_short_link(
				"secret",
				"redirectlink.s.gy",
				LONG_URL,
				request_func=lambda request, timeout=15: FakeResponse(b"invalid"),
			)

	def test_rejects_non_object_json(self):
		with self.assertRaisesRegex(ShortIoError, "некорректный ответ"):
			create_short_link(
				"secret",
				"redirectlink.s.gy",
				LONG_URL,
				request_func=lambda request, timeout=15: FakeResponse([]),
			)

	def test_preserves_short_io_http_error_message(self):
		def request_func(request, timeout=15):
			raise HTTPError(
				request.full_url,
				400,
				"Bad Request",
				None,
				io.BytesIO(b'{"error":"Domain is invalid"}'),
			)

		with self.assertRaisesRegex(ShortIoError, "Short.io: Domain is invalid"):
			create_short_link("secret", "invalid", LONG_URL, request_func=request_func)

	def test_falls_back_to_http_status_for_empty_error_body(self):
		def request_func(request, timeout=15):
			raise HTTPError(request.full_url, 500, "Server Error", None, io.BytesIO(b""))

		with self.assertRaisesRegex(ShortIoError, "Short.io вернул HTTP 500\\."):
			create_short_link("secret", "redirectlink.s.gy", LONG_URL, request_func=request_func)

	def test_reports_connection_error(self):
		def request_func(request, timeout=15):
			raise URLError("offline")

		with self.assertRaisesRegex(ShortIoError, "подключиться к Short.io"):
			create_short_link("secret", "redirectlink.s.gy", LONG_URL, request_func=request_func)


if __name__ == "__main__":
	unittest.main()
