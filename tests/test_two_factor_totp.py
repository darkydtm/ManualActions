from __future__ import annotations

import unittest

from core.two_factor.totp import generate_totp


class TwoFactorTotpTest(unittest.TestCase):
	def test_generates_rfc_6238_six_digit_code(self):
		self.assertEqual(generate_totp("GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ", 59), "287082")

	def test_rejects_invalid_secret(self):
		with self.assertRaises(ValueError):
			generate_totp("not-a-valid-key")


if __name__ == "__main__":
	unittest.main()
