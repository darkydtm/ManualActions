from __future__ import annotations

import unittest

from core.two_factor.parser import extract_secret


class TwoFactorParserTest(unittest.TestCase):
	def test_extracts_first_matching_label(self):
		self.assertEqual(
			extract_secret("Name: demo\n2FA: JBSW Y3DP\n2FA: ignored", "2FA: "),
			"JBSW Y3DP",
		)

	def test_ignores_non_matching_or_empty_value(self):
		self.assertIsNone(extract_secret(" 2FA: key", "2FA: "))
		self.assertIsNone(extract_secret("2FA:   ", "2FA: "))


if __name__ == "__main__":
	unittest.main()
