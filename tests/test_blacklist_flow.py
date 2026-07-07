from __future__ import annotations

import unittest

from manual_actions_core.payloads import parse_blacklist_payload


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


if __name__ == "__main__":
	unittest.main()
