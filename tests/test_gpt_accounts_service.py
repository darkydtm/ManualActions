import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from core.gpt_accounts.service import GptAccountsDeliveryService, OUTCOME_COMPLETED, has_gpt_accounts_marker
from core.gpt_accounts.settings import Account
from core.gpt_accounts.storage import GptAccountsDeliveryStorage


class GptAccountsServiceTest(unittest.TestCase):
	def setUp(self):
		self.directory = tempfile.TemporaryDirectory()
		self.cardinal = Mock()
		self.cardinal.send_message.return_value = True
		self.storage = GptAccountsDeliveryStorage(Path(self.directory.name) / "accounts.json")
		self.settings = {"gpt_accounts_delivery": {"enabled": True}}
		self.service = GptAccountsDeliveryService(self.cardinal, lambda: self.settings, self.storage)

	def tearDown(self):
		self.directory.cleanup()

	def test_detects_marker(self):
		self.assertTrue(has_gpt_accounts_marker("Offer #GPTACC"))
		self.assertFalse(has_gpt_accounts_marker("Offer #gptaccounts"))

	def test_delivers_account(self):
		self.storage.add_accounts((Account("one@example.com", "pass", "secret"),))
		order = SimpleNamespace(id="ORDER-1", amount=1, chat_id=1, full_description="#gptacc", buyer_username="buyer")
		self.cardinal.account.get_order.return_value = order
		outcome = self.service.handle_new_order(SimpleNamespace(order=order))
		self.assertEqual(outcome.status, OUTCOME_COMPLETED)
		self.assertIn("Email: one@example.com", self.cardinal.send_message.call_args.kwargs["message_text"])
