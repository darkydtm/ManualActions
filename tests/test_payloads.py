from __future__ import annotations

import unittest

from core.common.payloads import CallbackPayloadCache


class PayloadsTest(unittest.TestCase):
	def test_callback_payload_cache_keeps_long_payload_behind_short_token(self):
		cache = CallbackPayloadCache(limit=10)
		payload = ("buyer_with_a_very_long_funpay_name", "refunded", "ORDER-2026-000000123456")

		token = cache.put(payload)

		self.assertLess(len(f"ma_orders_detail:{token}"), 64)
		self.assertEqual(cache.get(token), payload)

	def test_callback_payload_cache_evicts_oldest_payload(self):
		cache = CallbackPayloadCache(limit=1)
		first = cache.put(("first",))
		second = cache.put(("second",))

		self.assertIsNone(cache.get(first))
		self.assertEqual(cache.get(second), ("second",))

	def test_callback_payload_cache_pops_payload_once(self):
		cache = CallbackPayloadCache()
		token = cache.put(("template", "chat"))

		self.assertEqual(cache.pop(token), ("template", "chat"))
		self.assertIsNone(cache.pop(token))


if __name__ == "__main__":
	unittest.main()
