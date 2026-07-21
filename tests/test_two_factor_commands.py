from __future__ import annotations

import unittest

from core.two_factor.commands import parse_code_request


class TwoFactorCommandsTest(unittest.TestCase):
	def test_parses_command_without_order(self):
		self.assertIsNone(parse_code_request(" !CODE ").order_id)

	def test_parses_command_with_order(self):
		self.assertEqual(parse_code_request("!code #ABC123").order_id, "ABC123")

	def test_rejects_non_commands_and_multiple_arguments(self):
		self.assertIsNone(parse_code_request("!codeplease"))
		self.assertIsNone(parse_code_request("!code first second"))


if __name__ == "__main__":
	unittest.main()
