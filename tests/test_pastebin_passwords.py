from __future__ import annotations

import unittest

from manual_actions_core.pastebin.passwords import generate_password


class PastebinPasswordsTest(unittest.TestCase):
	def test_generates_password_with_requested_length(self):
		password = generate_password(32)

		self.assertEqual(len(password), 32)

	def test_clamps_generated_password_length(self):
		self.assertEqual(len(generate_password(2)), 8)
		self.assertEqual(len(generate_password(100)), 64)


if __name__ == "__main__":
	unittest.main()
