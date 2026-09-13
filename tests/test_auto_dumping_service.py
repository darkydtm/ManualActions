from __future__ import annotations

from types import SimpleNamespace
import unittest

from core.modules.auto_dumping.models import AutoDumpingConfig, DumpingRule, Lot
from core.modules.auto_dumping.service import AutoDumpingService


def raw_lot(lot_id, title, price, username, subcategory_id=7, owner=False):
	return Lot(lot_id, title, price, f"sub-{subcategory_id}", username, subcategory_id=subcategory_id, raw=SimpleNamespace(owner=owner))


def service_config(settings):
	return AutoDumpingConfig(
		settings["enabled"],
		settings["interval_minutes"],
		tuple(DumpingRule.from_dict(rule) for rule in settings["rules"]),
	)


class Gateway:
	def __init__(self, own, catalog, owned=True):
		self.own = own
		self.catalog = catalog
		self.owned = owned
		self.updated = []

	def own_lots(self):
		return self.own

	def catalog_lots(self):
		return self.catalog

	def is_owned(self, lot):
		return self.owned

	def update_price(self, lot, price):
		self.updated.append((lot.id, price))


class Storage:
	def __init__(self):
		self.fingerprints = {}
		self.cycles = []

	def get_conflict_fingerprint(self, lot_id):
		return self.fingerprints.get(lot_id, "")

	def set_conflict_fingerprint(self, lot_id, value):
		self.fingerprints[lot_id] = value

	def record_cycle(self, timestamp, result):
		self.cycles.append((timestamp, result))


class AutoDumpingServiceTest(unittest.TestCase):
	def config(self):
		return {
			"enabled": True,
			"interval_minutes": 5,
			"rules": [{
				"id": "rule-1", "enabled": True, "subcategory": 7, "keywords": ["gold"],
				"keyword_mode": "any", "competitor_min_price": 0, "price_mode": "fixed",
				"dumping_value": 5, "own_min_price": 10,
			}],
		}

	def test_updates_owned_lot_from_cheapest_matching_competitor(self):
		own = raw_lot("own", "My gold", 100, "me", owner=True)
		gateway = Gateway([own], [own, raw_lot("high", "Gold", 80, "a"), raw_lot("low", "Gold", 50, "b")])
		storage = Storage()
		service = AutoDumpingService(lambda: self.config(), gateway, storage)

		result = service.run_cycle()

		self.assertEqual(gateway.updated, [("own", 45.0)])
		self.assertEqual(result["updated"], 1)

	def test_catalog_failure_does_not_update_any_lot(self):
		own = raw_lot("own", "My gold", 100, "me", owner=True)
		gateway = Gateway([own], None)
		service = AutoDumpingService(lambda: self.config(), gateway, Storage())

		result = service.run_cycle()

		self.assertEqual(gateway.updated, [])
		self.assertEqual(result["status"], "catalog_error")

	def test_ownership_is_checked_before_update(self):
		own = raw_lot("own", "My gold", 100, "me", owner=True)
		gateway = Gateway([own], [own, raw_lot("competitor", "Gold", 50, "other")], owned=False)
		service = AutoDumpingService(lambda: self.config(), gateway, Storage())

		result = service.run_cycle()

		self.assertEqual(gateway.updated, [])
		self.assertEqual(result["skipped"], 1)

	def test_skips_competitor_blocked_by_rule_local_blacklist(self):
		own = raw_lot("own", "My gold", 100, "me", owner=True)
		catalog = [own, raw_lot("blocked", "Gold", 50, "blocked-seller")]
		config = self.config()
		config["rules"][0]["sellers_blacklist"] = ["blocked-seller"]
		service = AutoDumpingService(lambda: config, Gateway([own], catalog), Storage())

		self.assertIsNone(service.decide(own, catalog, service_config(config)))

	def test_run_cycle_counts_skipped_when_no_rule_matches(self):
		own = raw_lot("own", "My silver", 100, "me", subcategory_id=8, owner=True)
		gateway = Gateway([own], [raw_lot("c", "Gold", 50, "other")])
		service = AutoDumpingService(lambda: self.config(), gateway, Storage())

		result = service.run_cycle()

		self.assertEqual(gateway.updated, [])
		self.assertEqual(result["updated"], 0)
		self.assertEqual(result["skipped"], 1)

	def test_run_cycle_counts_skipped_when_price_already_at_target(self):
		own = raw_lot("own", "My gold", 45.0, "me", owner=True)
		gateway = Gateway([own], [raw_lot("c", "Gold", 50, "other")])
		service = AutoDumpingService(lambda: self.config(), gateway, Storage())

		result = service.run_cycle()

		self.assertEqual(gateway.updated, [])
		self.assertEqual(result["updated"], 0)
		self.assertEqual(result["skipped"], 1)

	def test_describe_miss_distinguishes_rule_and_competitor_miss(self):
		config = service_config(self.config())
		service = AutoDumpingService(lambda: self.config(), Gateway([], []), Storage())

		silver = raw_lot("s", "Silver", 100, "me", subcategory_id=8, owner=True)
		self.assertIn("subcategory", service.describe_miss(silver, config))

		gold = raw_lot("g", "My gold", 100, "me", owner=True)
		self.assertIn("competitors", service.describe_miss(gold, config))

		disabled = service_config({"enabled": True, "interval_minutes": 5, "rules": [dict(self.config()["rules"][0], enabled=False)]})
		self.assertIn("no enabled rules", service.describe_miss(gold, disabled))


if __name__ == "__main__":
	unittest.main()
