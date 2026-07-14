from __future__ import annotations

import unittest
from urllib.parse import parse_qs

from manual_actions_core.pastebin.client import PastebinError, extract_paste_key, login, pastebin_url
from manual_actions_core.pastebin.service import (
	PastebinConfigError,
	build_password_paste_payload,
	build_paste_payload,
	create_pastebin,
	pastebin_config_errors,
	resolve_paste_title,
	resolve_api_user_key,
	resolve_paste_password,
)


class FakeResponse:
	def __init__(self, text: str, url: str = ""):
		self.text = text
		self.url = url

	def __enter__(self):
		return self

	def __exit__(self, exc_type, exc, traceback):
		return False

	def read(self):
		return self.text.encode("utf-8")

	def geturl(self):
		return self.url


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

	def test_does_not_build_pastebin_password_payload(self):
		payload = build_paste_payload(
			{
				"api_dev_key": "dev",
			},
			"Body",
		)

		self.assertNotIn("api_paste_password", payload)
		self.assertEqual(payload["api_paste_code"], "Body")

	def test_builds_password_paste_form_payload(self):
		payload = build_password_paste_payload(
			{
				"expire_date": "1D",
				"visibility": "1",
			},
			"Body",
			"Title",
			"secret",
		)

		self.assertEqual(payload["PostForm[text]"], "Body")
		self.assertEqual(payload["PostForm[expiration]"], "1D")
		self.assertEqual(payload["PostForm[status]"], "1")
		self.assertEqual(payload["PostForm[is_password_enabled]"], "1")
		self.assertEqual(payload["PostForm[password]"], "secret")
		self.assertEqual(payload["PostForm[name]"], "Title")

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
		self.assertEqual(requests[0][0].headers["User-agent"], "ManualActionsPastebin/1.0")

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

	def test_resolves_empty_password_by_default(self):
		password = resolve_paste_password({})

		self.assertEqual(password, "")

	def test_resolves_custom_password(self):
		password = resolve_paste_password({
			"password": {
				"mode": "custom",
				"custom": "secret",
			},
		})

		self.assertEqual(password, "secret")

	def test_reports_missing_custom_password_config(self):
		errors = pastebin_config_errors({
			"password": {
				"mode": "custom",
				"custom": "",
			},
		})

		self.assertIn("Свой пароль", errors[0])

	def test_creates_password_paste_through_form(self):
		requests = []

		def request_func(request, timeout=15):
			requests.append(request)
			if len(requests) == 1:
				return FakeResponse(
					'<input type="hidden" name="_csrf-frontend" value="csrf">',
					"https://pastebin.com/",
				)
			return FakeResponse("", "https://pastebin.com/AbCd1234")

		result = create_pastebin(
			{
				"password": {
					"mode": "custom",
					"custom": "secret",
				},
			},
			"Body",
			"Title",
			request_func=request_func,
		)
		post_body = requests[1].data.decode("utf-8")

		self.assertEqual(result.url, "https://pastebin.com/AbCd1234")
		self.assertEqual(result.password, "secret")
		self.assertTrue(result.protected)
		self.assertIn('name="PostForm[text]"', post_body)
		self.assertIn("Body", post_body)
		self.assertIn('name="PostForm[password]"', post_body)
		self.assertIn("secret", post_body)
		self.assertIn('name="_csrf-frontend"', post_body)

	def test_extracts_url_from_pastebin_response(self):
		self.assertEqual(extract_paste_key("https://pastebin.com/AbCd1234"), "AbCd1234")
		self.assertEqual(extract_paste_key("https://pastebin.com/raw/AbCd1234"), "AbCd1234")
		self.assertEqual(pastebin_url("https://pastebin.com/AbCd1234"), "https://pastebin.com/AbCd1234")

	def test_rejects_unknown_url_format(self):
		with self.assertRaises(PastebinError):
			pastebin_url("")

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

	def test_resolves_order_id_title(self):
		title = resolve_paste_title({
			"title": {
				"mode": "order_id",
				"custom": "Ignored",
			},
		}, order_id="ABC123")

		self.assertEqual(title, "ABC123")


if __name__ == "__main__":
	unittest.main()
