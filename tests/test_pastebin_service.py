from __future__ import annotations

import unittest
from urllib.parse import parse_qs

from manual_actions_core.pastebin.client import PastebinError, extract_paste_key, login, pastebin_raw_url
from manual_actions_core.pastebin.service import (
	PastebinConfigError,
	build_paste_payload,
	prepare_paste_text,
	resolve_paste_title,
	resolve_api_user_key,
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


class PastebinServiceTest(unittest.TestCase):
	def test_builds_payload_with_optional_user_folder_and_title(self):
		payload = build_paste_payload(
			{
				"api_dev_key": "dev",
				"api_user_key": "user",
				"expire_date": "1D",
				"folder_key": "folder",
				"visibility": "2",
				"title": {"mode": "off", "custom": ""},
			},
			"Body",
			"Title",
		)

		self.assertEqual(payload["api_dev_key"], "dev")
		self.assertEqual(payload["api_user_key"], "user")
		self.assertEqual(payload["api_folder_key"], "folder")
		self.assertEqual(payload["api_paste_expire_date"], "1D")
		self.assertEqual(payload["api_paste_name"], "Title")
		self.assertEqual(payload["api_paste_private"], "2")
		self.assertEqual(payload["api_paste_code"], "Body")

	def test_requires_dev_key(self):
		with self.assertRaises(PastebinConfigError):
			build_paste_payload({}, "Body")

	def test_requires_user_key_for_folder(self):
		with self.assertRaises(PastebinConfigError):
			build_paste_payload(
				{
					"api_dev_key": "dev",
					"folder_key": "folder",
				},
				"Body",
			)

	def test_requires_user_key_for_private_visibility(self):
		with self.assertRaises(PastebinConfigError):
			build_paste_payload(
				{
					"api_dev_key": "dev",
					"visibility": "2",
				},
				"Body",
			)

	def test_logs_in_with_credentials(self):
		requests = []

		def request_func(request, timeout=15):
			requests.append((request, timeout))
			return FakeResponse("user-key")

		key = login("dev", "login", "pass", request_func=request_func)
		body = parse_qs(requests[0][0].data.decode("utf-8"))

		self.assertEqual(key, "user-key")
		self.assertEqual(requests[0][0].full_url, "https://pastebin.com/api/api_login.php")
		self.assertEqual(body["api_dev_key"], ["dev"])
		self.assertEqual(body["api_user_name"], ["login"])
		self.assertEqual(body["api_user_password"], ["pass"])

	def test_rejects_bad_login_response(self):
		def request_func(request, timeout=15):
			return FakeResponse("Bad API request, invalid login")

		with self.assertRaises(PastebinError):
			login("dev", "login", "bad", request_func=request_func)

	def test_resolves_user_key_from_login_when_manual_key_is_empty(self):
		def request_func(request, timeout=15):
			return FakeResponse("generated-key")

		key = resolve_api_user_key({
			"api_dev_key": "dev",
			"username": "login",
			"login_password": "pass",
		}, request_func=request_func)

		self.assertEqual(key, "generated-key")

	def test_prefers_manual_user_key_before_login(self):
		key = resolve_api_user_key({
			"api_dev_key": "dev",
			"api_user_key": "manual",
			"username": "login",
			"login_password": "pass",
		}, request_func=lambda request, timeout=15: FakeResponse("generated"))

		self.assertEqual(key, "manual")

	def test_prepares_unprotected_text_by_default(self):
		prepared = prepare_paste_text({}, "Body")

		self.assertEqual(prepared.text, "Body")
		self.assertEqual(prepared.password, "")
		self.assertFalse(prepared.protected)

	def test_requires_custom_password_when_enabled(self):
		with self.assertRaises(PastebinConfigError):
			prepare_paste_text({
				"password": {
					"mode": "custom",
					"custom": "",
				},
			}, "Body")

	def test_extracts_raw_url_from_pastebin_response(self):
		self.assertEqual(extract_paste_key("https://pastebin.com/AbCd1234"), "AbCd1234")
		self.assertEqual(extract_paste_key("https://pastebin.com/raw/AbCd1234"), "AbCd1234")
		self.assertEqual(pastebin_raw_url("https://pastebin.com/AbCd1234"), "https://pastebin.com/raw/AbCd1234")

	def test_rejects_unknown_raw_url_format(self):
		with self.assertRaises(PastebinError):
			pastebin_raw_url("")

	def test_resolves_custom_title(self):
		title = resolve_paste_title({
			"title": {
				"mode": "custom",
				"custom": "Client title",
			},
		})

		self.assertEqual(title, "Client title")

	def test_resolves_chat_sync_title(self):
		title = resolve_paste_title({
			"title": {
				"mode": "chat_sync",
				"custom": "Ignored",
			},
		}, "buyer")

		self.assertEqual(title, "buyer")


if __name__ == "__main__":
	unittest.main()
