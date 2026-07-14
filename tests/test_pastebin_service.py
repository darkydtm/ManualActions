from __future__ import annotations

import unittest

from manual_actions_core.pastebin.client import PastebinError, extract_paste_key, pastebin_raw_url
from manual_actions_core.pastebin.service import (
	PastebinConfigError,
	build_paste_payload,
	resolve_paste_title,
)


class PastebinServiceTest(unittest.TestCase):
	def test_builds_payload_with_optional_user_folder_and_title(self):
		payload = build_paste_payload(
			{
				"api_dev_key": "dev",
				"api_user_key": "user",
				"expire_date": "1D",
				"folder_key": "folder",
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
		self.assertEqual(payload["api_paste_private"], "1")
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
