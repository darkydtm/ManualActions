from __future__ import annotations

import unittest

from core.chat_sync.settings import (
	DEFAULT_CHAT_SYNC_SETTINGS,
	MAX_HISTORY_DEPTH,
	MAX_MESSAGES_PER_MINUTE,
	MIN_MESSAGES_PER_MINUTE,
	normalize_chat_sync_settings,
)
from core.chat_sync.storage import TopicRecord, normalize_topics
from core.chat_sync.topics import OrderStats, collect_order_stats, format_topic_name, parse_topic_name, topic_icon
from core.config.settings import normalize_settings


class SettingsNormalizerTest(unittest.TestCase):
	def test_returns_defaults_for_garbage(self):
		self.assertEqual(normalize_chat_sync_settings(None), DEFAULT_CHAT_SYNC_SETTINGS)
		self.assertEqual(normalize_chat_sync_settings("nope"), DEFAULT_CHAT_SYNC_SETTINGS)

	def test_keeps_known_booleans(self):
		settings = normalize_chat_sync_settings({"enabled": False, "mono": True})

		self.assertFalse(settings["enabled"])
		self.assertTrue(settings["mono"])

	def test_ignores_non_boolean_flags(self):
		self.assertTrue(normalize_chat_sync_settings({"enabled": "yes"})["enabled"])

	def test_accepts_numeric_chat_id_as_string(self):
		self.assertEqual(normalize_chat_sync_settings({"chat_id": "-1001"})["chat_id"], -1001)

	def test_rejects_invalid_chat_id(self):
		self.assertIsNone(normalize_chat_sync_settings({"chat_id": "group"})["chat_id"])
		self.assertIsNone(normalize_chat_sync_settings({"chat_id": True})["chat_id"])

	def test_clamps_history_depth(self):
		self.assertEqual(normalize_chat_sync_settings({"history_depth": -5})["history_depth"], 0)
		self.assertEqual(normalize_chat_sync_settings({"history_depth": 5000})["history_depth"], MAX_HISTORY_DEPTH)

	def test_clamps_message_rate(self):
		self.assertEqual(normalize_chat_sync_settings({"messages_per_minute": 1})["messages_per_minute"], MIN_MESSAGES_PER_MINUTE)
		self.assertEqual(
			normalize_chat_sync_settings({"messages_per_minute": 9999})["messages_per_minute"],
			MAX_MESSAGES_PER_MINUTE,
		)

	def test_plugin_settings_include_chat_sync_section(self):
		settings = normalize_settings({"chat_sync": {"chat_id": -42, "mono": True}})

		self.assertEqual(settings["chat_sync"]["chat_id"], -42)
		self.assertTrue(settings["chat_sync"]["mono"])

	def test_plugin_settings_default_chat_sync_section(self):
		self.assertEqual(normalize_settings({})["chat_sync"], DEFAULT_CHAT_SYNC_SETTINGS)


class TopicStorageTest(unittest.TestCase):
	def test_reads_records(self):
		topics = normalize_topics({"77": {"thread_id": 5, "username": "buyer", "last_message_id": 9}})

		self.assertEqual(topics["77"], TopicRecord(thread_id=5, username="buyer", last_message_id=9))

	def test_accepts_legacy_flat_mapping(self):
		self.assertEqual(normalize_topics({"77": 5})["77"].thread_id, 5)

	def test_drops_duplicate_thread_ids(self):
		topics = normalize_topics({"77": {"thread_id": 5}, "88": {"thread_id": 5}})

		self.assertEqual(list(topics), ["77"])

	def test_skips_malformed_entries(self):
		topics = normalize_topics({
			"77": {"thread_id": "five"},
			"buyer": {"thread_id": 6},
			"88": {"thread_id": 7},
		})

		self.assertEqual(list(topics), ["88"])

	def test_returns_empty_for_garbage(self):
		self.assertEqual(normalize_topics(None), {})


class TopicNameTest(unittest.TestCase):
	def test_formats_plain_name(self):
		self.assertEqual(format_topic_name("buyer", 77), "buyer (77)")

	def test_formats_name_with_stats(self):
		name = format_topic_name("buyer", 77, OrderStats(paid=1, closed=2, refunded=3))

		self.assertEqual(name, "1|2|3👤buyer (77)")

	def test_round_trips_through_the_parser(self):
		name = format_topic_name("buyer", 77, OrderStats(paid=1, closed=2, refunded=3))

		self.assertEqual(parse_topic_name(name), ("buyer", 77))

	def test_parses_plain_name(self):
		self.assertEqual(parse_topic_name("buyer (77)"), ("buyer", 77))

	def test_rejects_invalid_name(self):
		self.assertEqual(parse_topic_name("buyer (abc)"), (None, None))

	def test_falls_back_when_username_is_blank(self):
		self.assertEqual(format_topic_name("", 77), "chat 77 (77)")


class OrderStatsTest(unittest.TestCase):
	def test_counts_orders_by_status(self):
		sales = [
			sale("PAID", 100, "₽"),
			sale("CLOSED", 50, "₽"),
			sale("CLOSED", 25, "₽"),
			sale("REFUNDED", 10, "$"),
		]

		stats = collect_order_stats(sales)

		self.assertEqual((stats.paid, stats.closed, stats.refunded), (1, 2, 1))
		self.assertEqual(stats.closed_sum, "75₽")
		self.assertEqual(stats.refunded_sum, "10$")

	def test_handles_empty_input(self):
		self.assertFalse(collect_order_stats(None).has_orders)

	def test_picks_icon_by_activity(self):
		self.assertEqual(topic_icon(OrderStats(paid=1)), topic_icon(OrderStats(paid=5)))
		self.assertNotEqual(topic_icon(OrderStats(closed=1)), topic_icon(OrderStats(closed=60)))
		self.assertNotEqual(topic_icon(OrderStats(), blacklisted=True), topic_icon(OrderStats()))

	def test_special_icon_wins(self):
		self.assertNotEqual(topic_icon(OrderStats(paid=1), special="arbitration"), topic_icon(OrderStats(paid=1)))


def sale(status, price, currency):
	class Sale:
		pass

	item = Sale()
	item.status = type("Status", (), {"name": status})()
	item.price = price
	item.currency = currency
	return item


if __name__ == "__main__":
	unittest.main()
