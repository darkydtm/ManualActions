from __future__ import annotations

import unittest
import sys
import types
from types import SimpleNamespace

utils = types.ModuleType("Utils")
utils.cardinal_tools = SimpleNamespace(cache_blacklist=lambda blacklist: None)
sys.modules.setdefault("Utils", utils)

from core.funpay.blacklist import toggle_action_for_user
from core.payloads import parse_blacklist_payload


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


if __name__ == "__main__":
	unittest.main()
