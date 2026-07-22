from __future__ import annotations

import unittest
import sys
import types
from types import SimpleNamespace

utils = types.ModuleType("Utils")
utils.cardinal_tools = SimpleNamespace(cache_blacklist=lambda blacklist: None)
sys.modules.setdefault("Utils", utils)

from core.funpay.blacklist import block_user, toggle_action_for_user
from core.common.payloads import parse_blacklist_payload


class BlacklistFlowTest(unittest.TestCase):
	def test_parses_payload_with_numeric_chat_id(self):
		self.assertEqual(
			parse_blacklist_payload("block|buyer|265883181"),
			("block", "buyer", 265883181),
		)

	def test_parses_payload_without_chat_id(self):
		self.assertEqual(
			parse_blacklist_payload("unblock|buyer|"),
			("unblock", "buyer", None),
		)

	def test_toggle_action_blocks_missing_user(self):
		cardinal = SimpleNamespace(blacklist=["blocked"])

		self.assertEqual(toggle_action_for_user(cardinal, "buyer"), "block")

	def test_toggle_action_unblocks_existing_user(self):
		cardinal = SimpleNamespace(blacklist=["buyer"])

		self.assertEqual(toggle_action_for_user(cardinal, "buyer"), "unblock")

	def test_cache_is_unchanged_when_remote_block_fails(self):
		account = SimpleNamespace(csrf_token="token", get_chat_history=lambda *args, **kwargs: [])
		account.method = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("offline"))
		cardinal = SimpleNamespace(account=account, blacklist=[])

		with self.assertRaisesRegex(RuntimeError, "offline"):
			block_user(cardinal, "buyer", chat_id=1)

		self.assertNotIn("buyer", cardinal.blacklist)


if __name__ == "__main__":
	unittest.main()
