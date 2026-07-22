import tempfile
import unittest
from pathlib import Path

from core.delivery.providers.gpt_accounts import Account
from core.delivery.providers.gpt_accounts_storage import GptAccountsDeliveryStorage, OrderReservationRequest, STATUS_WAITING_STOCK


class GptAccountsStorageTest(unittest.TestCase):
	def setUp(self):
		self.directory = tempfile.TemporaryDirectory()
		self.storage = GptAccountsDeliveryStorage(Path(self.directory.name) / "accounts.json")

	def tearDown(self):
		self.directory.cleanup()

	def test_reserves_accounts(self):
		self.storage.add_accounts((Account("one@example.com", "one"), Account("two@example.com", "two")))
		result = self.storage.reserve(OrderReservationRequest("ORDER-1", 2), "partial")
		self.assertEqual(len(result.accounts), 2)
		self.assertEqual(self.storage.stock_count(), 0)

	def test_all_or_nothing_keeps_stock(self):
		self.storage.add_accounts((Account("one@example.com", "one"),))
		result = self.storage.reserve(OrderReservationRequest("ORDER-1", 2), "all_or_nothing")
		self.assertEqual(result.status, STATUS_WAITING_STOCK)
		self.assertEqual(self.storage.stock_count(), 1)

	def test_restores_reservation(self):
		self.storage.add_accounts((Account("one@example.com", "one"),))
		self.storage.reserve(OrderReservationRequest("ORDER-1", 1), "partial")
		self.storage.restore_reservation("ORDER-1", "failed")
		self.assertEqual(self.storage.stock_count(), 1)
