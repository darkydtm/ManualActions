import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from core.delivery.providers.gpt_accounts_service import GptAccountsDeliveryService, OUTCOME_COMPLETED, has_gpt_accounts_marker
from core.delivery.providers.gpt_accounts import Account
from core.delivery.providers.gpt_accounts_storage import GptAccountsDeliveryStorage


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

	def test_uses_order_amount_as_account_quantity(self):
		self.storage.add_accounts((Account("one@example.com", "one"), Account("two@example.com", "two")))
		order = SimpleNamespace(id="ORDER-2", amount=2, chat_id=1, full_description="#gptacc", buyer_username="buyer")
		self.cardinal.account.get_order.return_value = order
		self.service.handle_new_order(SimpleNamespace(order=order))
		text = self.cardinal.send_message.call_args.kwargs["message_text"]
		self.assertIn("Email: one@example.com", text)
		self.assertIn("Email: two@example.com", text)

	def test_schedules_delivery_after_configured_delay(self):
		self.settings["gpt_accounts_delivery"]["delay_seconds"] = 15
		timer = Mock()
		self.service = GptAccountsDeliveryService(
			self.cardinal,
			lambda: self.settings,
			self.storage,
			timer_factory=lambda seconds, callback: timer,
		)
		self.storage.add_accounts((Account("one@example.com", "pass"),))
		order = SimpleNamespace(id="ORDER-1", amount=1, chat_id=1, full_description="#gptacc", buyer_username="buyer")
		self.cardinal.account.get_order.return_value = order

		self.service.handle_new_order(SimpleNamespace(order=order))

		timer.start.assert_called_once_with()
		self.cardinal.send_message.assert_not_called()

	def test_skips_delayed_delivery_when_disabled_before_execution(self):
		self.settings["gpt_accounts_delivery"]["delay_seconds"] = 15
		callbacks = []
		self.service = GptAccountsDeliveryService(
			self.cardinal,
			lambda: self.settings,
			self.storage,
			timer_factory=lambda seconds, callback: callbacks.append(callback) or Mock(),
		)
		self.storage.add_accounts((Account("one@example.com", "pass"),))
		order = SimpleNamespace(id="ORDER-1", amount=1, chat_id=1, full_description="#gptacc", buyer_username="buyer")
		self.cardinal.account.get_order.return_value = order

		self.service.handle_new_order(SimpleNamespace(order=order))
		self.settings["gpt_accounts_delivery"]["enabled"] = False
		callbacks[0]()

		self.assertEqual(self.storage.stock_count(), 1)
		self.cardinal.send_message.assert_not_called()

	def test_shortage_continues_when_buyer_notification_fails(self):
		topic_notifier = Mock()
		admin_notifier = Mock()
		self.service = GptAccountsDeliveryService(
			self.cardinal,
			lambda: self.settings,
			self.storage,
			topic_notifier=topic_notifier,
			admin_notifier=admin_notifier,
		)
		order = SimpleNamespace(
			id="ORDER-3",
			amount=1,
			chat_id=1,
			full_description="#gptacc",
			buyer_username="buyer",
		)
		self.cardinal.account.get_order.return_value = order
		self.cardinal.send_message.side_effect = RuntimeError("offline")

		self.service.handle_new_order(SimpleNamespace(order=order))

		topic_notifier.assert_called_once()
		admin_notifier.assert_called_once()
