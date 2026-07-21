from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from core.funpay.messages import MessageContext
from core.two_factor.service import TwoFactorService
from core.two_factor.storage import TwoFactorStorage


class TwoFactorServiceTest(unittest.TestCase):
	def setUp(self):
		self.directory = tempfile.TemporaryDirectory()
		self.cardinal = SimpleNamespace(
			account=SimpleNamespace(get_order=Mock()),
			send_message=Mock(),
		)
		self.storage = TwoFactorStorage(str(Path(self.directory.name) / "two_factor.json"))
		self.service = TwoFactorService(
			self.cardinal,
			lambda: {"two_factor": {"label": "2FA: "}},
			self.storage,
		)

	def tearDown(self):
		self.directory.cleanup()

	def test_caches_secret_from_seller_message(self):
		self.service.handle_seller_message(self.context("Product\n2FA: JBSWY3DPEHPK3PXP", is_seller=True))

		self.assertEqual(self.storage.get_for_chat(7)["secret"], "JBSWY3DPEHPK3PXP")

	def test_sends_code_for_latest_chat_secret(self):
		self.storage.save(7, "JBSWY3DPEHPK3PXP")

		handled = self.service.handle_code_request(self.context("!code"))

		self.assertTrue(handled)
		self.assertIn("2FA-код:", self.cardinal.send_message.call_args.kwargs["message_text"])

	def test_sends_code_for_explicit_order_from_another_chat(self):
		self.storage.save(7, "JBSWY3DPEHPK3PXP")
		self.cardinal.account.get_order.return_value = SimpleNamespace(chat_id=7)

		self.service.handle_code_request(self.context("!code #ABC", chat_id=8))

		self.cardinal.send_message.assert_called_once_with(
			chat_id=8,
			message_text=unittest.mock.ANY,
		)

	def test_reports_missing_secret(self):
		self.service.handle_code_request(self.context("!code MISSING"))

		self.assertIn("не найден", self.cardinal.send_message.call_args.kwargs["message_text"])

	@staticmethod
	def context(text, chat_id=7, is_seller=False):
		return MessageContext(text, chat_id, None, None, is_seller)


if __name__ == "__main__":
	unittest.main()
