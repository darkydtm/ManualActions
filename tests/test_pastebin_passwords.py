from __future__ import annotations

import unittest

from manual_actions_core.pastebin.passwords import (
	PROTECTED_PREFIX,
	ProtectedTextError,
	decrypt_protected_text,
	generate_password,
	protect_text,
)


class PastebinPasswordsTest(unittest.TestCase):
	def test_protects_and_decrypts_text(self):
		protected = protect_text(
			"Secret body",
			"password",
			salt=b"1234567890123456",
			nonce=b"6543210987654321",
		)

		self.assertIn(PROTECTED_PREFIX, protected)
		self.assertNotIn("Secret body", protected)
		self.assertEqual(decrypt_protected_text(protected, "password"), "Secret body")

	def test_rejects_wrong_password(self):
		protected = protect_text(
			"Secret body",
			"password",
			salt=b"1234567890123456",
			nonce=b"6543210987654321",
		)

		with self.assertRaises(ProtectedTextError):
			decrypt_protected_text(protected, "wrong")

	def test_generates_password_with_requested_length(self):
		password = generate_password(32)

		self.assertEqual(len(password), 32)

	def test_clamps_generated_password_length(self):
		self.assertEqual(len(generate_password(2)), 8)
		self.assertEqual(len(generate_password(100)), 64)


if __name__ == "__main__":
	unittest.main()
