from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from core.gemini.storage import (
	GeminiDeliveryStorage,
	OrderReservationRequest,
	STATUS_COMPLETED,
	STATUS_GIST_CREATED,
	STATUS_RESERVED,
	STATUS_RETRYABLE,
	STATUS_SEND_FAILED,
	STATUS_WAITING_STOCK,
	StorageUnavailableError,
)


LINK_ONE = "https://one.google.com/activate-plan/subscription/new/one"
LINK_TWO = "https://serviceactivation.google.com/subscription/new/two"
LINK_THREE = "https://one.google.com/activate-plan/subscription/new/three"


class GeminiDeliveryStorageTest(unittest.TestCase):
	def setUp(self):
		self.temp_dir = TemporaryDirectory()
		self.path = Path(self.temp_dir.name) / "gemini_delivery.json"
		self.clock_value = 1000.0
		self.storage = GeminiDeliveryStorage(self.path, time_func=self.clock)

	def tearDown(self):
		self.temp_dir.cleanup()

	def clock(self):
		self.clock_value += 1
		return self.clock_value

	def request(self, order_id="ORDER-1", amount=1):
		return OrderReservationRequest(
			order_id=order_id,
			requested_amount=amount,
			buyer_username="buyer",
			fp_chat_id=77,
		)

	def test_adds_unique_links_in_fifo_order(self):
		added = self.storage.add_links((LINK_ONE, LINK_TWO, LINK_ONE))

		self.assertEqual(added, 2)
		self.assertEqual(self.storage.stock_links(), (LINK_ONE, LINK_TWO))
		self.assertEqual(json.loads(self.path.read_text())["stock"], [LINK_ONE, LINK_TWO])

	def test_partial_reservation_uses_available_links(self):
		self.storage.add_links((LINK_ONE, LINK_TWO))

		result = self.storage.reserve(self.request(amount=3), "partial")

		self.assertEqual(result.status, STATUS_RESERVED)
		self.assertEqual(result.links, (LINK_ONE, LINK_TWO))
		self.assertEqual(result.requested_amount, 3)
		self.assertTrue(result.shortage)
		self.assertEqual(self.storage.stock_count(), 0)

	def test_all_or_nothing_reservation_waits_without_consuming(self):
		self.storage.add_links((LINK_ONE,))

		result = self.storage.reserve(self.request(amount=2), "all_or_nothing")

		self.assertEqual(result.status, STATUS_WAITING_STOCK)
		self.assertEqual(result.links, ())
		self.assertEqual(self.storage.stock_links(), (LINK_ONE,))

	def test_empty_partial_reservation_waits_for_stock(self):
		result = self.storage.reserve(self.request(amount=2), "partial")

		self.assertEqual(result.status, STATUS_WAITING_STOCK)
		self.assertEqual(result.links, ())

	def test_existing_reservation_does_not_consume_more_stock(self):
		self.storage.add_links((LINK_ONE, LINK_TWO))
		first = self.storage.reserve(self.request(), "partial")

		second = self.storage.reserve(self.request(), "partial")

		self.assertEqual(second.links, first.links)
		self.assertEqual(self.storage.stock_links(), (LINK_TWO,))

	def test_waiting_order_can_reserve_after_restock(self):
		self.storage.reserve(self.request(), "partial")
		self.storage.add_links((LINK_ONE,))

		result = self.storage.reserve(self.request(), "partial")

		self.assertEqual(result.status, STATUS_RESERVED)
		self.assertEqual(result.links, (LINK_ONE,))

	def test_restores_reservation_to_front_after_failure(self):
		self.storage.add_links((LINK_ONE, LINK_TWO, LINK_THREE))
		self.storage.reserve(self.request(amount=2), "partial")

		self.storage.restore_reservation("ORDER-1", "GitHub failed")

		self.assertEqual(self.storage.stock_links(), (LINK_ONE, LINK_TWO, LINK_THREE))
		order = self.storage.get_order("ORDER-1")
		self.assertEqual(order["status"], STATUS_RETRYABLE)
		self.assertEqual(order["reserved_links"], [])
		self.assertEqual(order["last_error"], "GitHub failed")

	def test_marks_gist_completed_and_send_failed(self):
		self.storage.add_links((LINK_ONE, LINK_TWO))
		self.storage.reserve(self.request(order_id="A"), "partial")
		self.storage.mark_gist_created("A", "raw-a")
		self.storage.mark_completed("A")
		self.storage.reserve(self.request(order_id="B"), "partial")
		self.storage.mark_gist_created("B", "raw-b")
		self.storage.mark_send_failed("B", "send failed")

		self.assertEqual(self.storage.get_order("A")["status"], STATUS_COMPLETED)
		self.assertEqual(self.storage.get_order("B")["status"], STATUS_SEND_FAILED)
		self.assertEqual(self.storage.get_order("B")["raw_url"], "raw-b")

	def test_gist_created_order_is_returned_without_new_reservation(self):
		self.storage.add_links((LINK_ONE, LINK_TWO))
		self.storage.reserve(self.request(), "partial")
		self.storage.mark_gist_created("ORDER-1", "raw")

		result = self.storage.reserve(self.request(), "partial")

		self.assertEqual(result.status, STATUS_GIST_CREATED)
		self.assertEqual(result.raw_url, "raw")
		self.assertEqual(self.storage.stock_links(), (LINK_TWO,))

	def test_does_not_readd_link_from_send_failed_order(self):
		self.storage.add_links((LINK_ONE,))
		self.storage.reserve(self.request(), "partial")
		self.storage.mark_gist_created("ORDER-1", "raw")
		self.storage.mark_send_failed("ORDER-1", "send failed")

		self.assertEqual(self.storage.add_links((LINK_ONE,)), 0)
		self.assertEqual(self.storage.stock_count(), 0)

	def test_removes_and_clears_available_stock(self):
		self.storage.add_links((LINK_ONE, LINK_TWO))

		self.assertEqual(self.storage.remove_stock_item(0), LINK_ONE)
		self.assertIsNone(self.storage.remove_stock_item(5))
		self.assertEqual(self.storage.clear_stock(), 1)
		self.assertEqual(self.storage.stock_count(), 0)

	def test_lists_waiting_orders(self):
		self.storage.reserve(self.request(order_id="A"), "partial")
		self.storage.reserve(self.request(order_id="B"), "partial")

		self.assertEqual(
			[order["order_id"] for order in self.storage.waiting_orders()],
			["B", "A"],
		)

	def test_tracks_shortage_notification_once(self):
		self.storage.reserve(self.request(), "partial")

		self.assertTrue(self.storage.mark_shortage_notified("ORDER-1"))
		self.assertFalse(self.storage.mark_shortage_notified("ORDER-1"))

	def test_trims_old_completed_orders_but_keeps_unfinished(self):
		storage = GeminiDeliveryStorage(self.path, completion_limit=2, time_func=self.clock)
		storage.add_links((LINK_ONE, LINK_TWO, LINK_THREE))
		for order_id in ("A", "B", "C"):
			storage.reserve(self.request(order_id=order_id), "partial")
			storage.mark_gist_created(order_id, f"raw-{order_id}")
			storage.mark_completed(order_id)
			storage.add_links((f"{LINK_ONE}-{order_id}",))
			storage.reserve(self.request(order_id=f"W-{order_id}", amount=999), "all_or_nothing")

		self.assertIsNone(storage.get_order("A"))
		self.assertEqual(storage.get_order("B")["status"], STATUS_COMPLETED)
		self.assertEqual(storage.get_order("C")["status"], STATUS_COMPLETED)
		self.assertEqual(storage.get_order("W-A")["status"], STATUS_WAITING_STOCK)

	def test_does_not_overwrite_invalid_storage(self):
		self.path.write_text("{invalid", encoding="utf-8")
		storage = GeminiDeliveryStorage(self.path)

		with self.assertRaises(StorageUnavailableError):
			storage.add_links((LINK_ONE,))

		self.assertEqual(self.path.read_text(encoding="utf-8"), "{invalid")


if __name__ == "__main__":
	unittest.main()
