import unittest

from core.config.settings import normalize_settings
from core.gpt_accounts.settings import Account, format_accounts, parse_account_batch


class GptAccountsSettingsTest(unittest.TestCase):
	def test_parses_optional_two_factor_secret(self):
		result = parse_account_batch("one@example.com|pass\ntwo@example.com|pass2|secret", set())
		self.assertEqual(result.accounts, (
			Account("one@example.com", "pass"),
			Account("two@example.com", "pass2", "secret"),
		))

	def test_rejects_invalid_and_duplicate_rows(self):
		result = parse_account_batch("old@example.com|pass\ninvalid\nnew@example.com||key\nnew@example.com|pass", {"old@example.com"})
		self.assertEqual(result.invalid_lines, (2, 3))
		self.assertEqual(result.duplicate_count, 1)
		self.assertEqual(result.accounts, (Account("new@example.com", "pass"),))

	def test_formats_accounts(self):
		self.assertEqual(
			format_accounts((Account("one@example.com", "pass", "secret"),)),
			"Email: one@example.com\nPassword: pass\n2FA secret: secret",
		)

	def test_normalizes_plugin_settings(self):
		settings = normalize_settings({"gpt_accounts_delivery": {"quantity": 2}})
		self.assertEqual(settings["gpt_accounts_delivery"]["quantity"], 2)


if __name__ == "__main__":
	unittest.main()
