from __future__ import annotations

from types import SimpleNamespace
import unittest

from core.modules.auto_dumping.funpay import FunPayCatalogGateway, parse_price
from core.modules.auto_dumping.matching import matches_subcategory
from core.modules.auto_dumping.models import AutoDumpingConfig, DumpingRule, Lot
from core.modules.auto_dumping.scheduler import AutoDumpingScheduler
from core.modules.auto_dumping.service import AutoDumpingService


def subcategory(sub_id=7, name="Gold", sub_type="COMMON"):
	return SimpleNamespace(id=sub_id, name=name, fullname=f"Game, {name}", type=sub_type)


def raw_lot(lot_id, title, price, sub=None, seller="seller", active=True, available=True):
	return SimpleNamespace(
		id=lot_id,
		description=title,
		price=price,
		subcategory=sub if sub is not None else subcategory(),
		username=seller,
		active=active,
		available=available,
	)


def rule(rule_id="rule-1", subcategory_name="Gold", keywords=("gold",), **changes):
	data = {
		"id": rule_id,
		"enabled": True,
		"subcategory": subcategory_name,
		"keywords": keywords,
		"keyword_mode": "any",
		"competitor_min_price": 0,
		"price_mode": "fixed",
		"dumping_value": 5,
		"own_min_price": 0,
	}
	data.update(changes)
	return DumpingRule(**data)


def config(*rules):
	return AutoDumpingConfig(True, 5, tuple(rules))


class Gateway:
	def __init__(self, own, catalog):
		self.own = own
		self.catalog = catalog
		self.updated = []

	def own_lots(self):
		return self.own

	def catalog_lots(self):
		return self.catalog

	def is_owned(self, lot):
		return True

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


class Notifier:
	def __init__(self):
		self.calls = []

	def notify_detected(self, decision):
		self.calls.append(("detected", decision))

	def notify_applied(self, decision):
		self.calls.append(("applied", decision))


class ParsePriceTest(unittest.TestCase):
	def test_parses_plain_numbers(self):
		self.assertEqual(parse_price(100), 100.0)
		self.assertEqual(parse_price(10.5), 10.5)
		self.assertEqual(parse_price(True), 0.0)
		self.assertEqual(parse_price(None), 0.0)

	def test_parses_strings_with_currency_and_spaces(self):
		self.assertEqual(parse_price("1 234\u00a0\u20bd"), 1234.0)
		self.assertEqual(parse_price("99,99"), 99.99)
		self.assertEqual(parse_price("1,234.50"), 1234.5)

	def test_returns_zero_for_garbage(self):
		self.assertEqual(parse_price("free"), 0.0)
		self.assertEqual(parse_price(""), 0.0)


class MatchesSubcategoryTest(unittest.TestCase):
	def test_matches_name_case_insensitively(self):
		lot = Lot("1", "Gold fast", 10, "Gold", "a", raw=raw_lot("1", "Gold fast", 10))
		self.assertTrue(matches_subcategory(lot, "gold"))

	def test_matches_id_and_fullname(self):
		lot = Lot("1", "Gold fast", 10, "Gold", "a", raw=raw_lot("1", "Gold fast", 10))
		self.assertTrue(matches_subcategory(lot, "7"))
		self.assertTrue(matches_subcategory(lot, "game, gold"))

	def test_rejects_blank_rule_and_mismatch(self):
		lot = Lot("1", "Gold fast", 10, "Gold", "a", raw=raw_lot("1", "Gold fast", 10))
		self.assertFalse(matches_subcategory(lot, ""))
		self.assertFalse(matches_subcategory(lot, "Silver"))


class FunPayGatewayTest(unittest.TestCase):
	def test_own_lots_skips_inactive_and_empty_ids(self):
		profile = SimpleNamespace(get_lots=lambda: [
			raw_lot("1", "Gold", 100),
			raw_lot("2", "Silver", 50, active=False),
			SimpleNamespace(id=None, lot_id="", description="No id", price=10, subcategory="Gold", active=True),
		])
		gateway = FunPayCatalogGateway(SimpleNamespace(profile=profile, account=None))

		lots = gateway.own_lots()

		self.assertEqual([lot.id for lot in lots], ["1"])
		self.assertEqual(gateway._own_ids, {"1"})

	def test_is_owned_uses_cache_without_refetch(self):
		profile = SimpleNamespace(get_lots=lambda: [raw_lot("1", "Gold", 100)])
		gateway = FunPayCatalogGateway(SimpleNamespace(profile=profile, account=None))
		gateway.own_lots()
		calls = []
		profile.get_lots = lambda: calls.append(1) or []

		self.assertTrue(gateway.is_owned(Lot("1", "Gold", 100, "Gold", "me")))

		self.assertEqual(calls, [])

	def test_catalog_lots_reads_public_lots_per_subcategory(self):
		seen = []

		def fetch(sub_type, sub_id):
			seen.append((sub_type, sub_id))
			return [raw_lot("9", "Cheap Gold", 40, seller="other")]

		cardinal = SimpleNamespace(
			profile=SimpleNamespace(get_lots=lambda: [raw_lot("1", "My Gold", 100)]),
			account=SimpleNamespace(get_subcategory_public_lots=fetch),
		)
		lots = FunPayCatalogGateway(cardinal).catalog_lots()

		self.assertEqual(seen, [("COMMON", 7)])
		self.assertEqual([(lot.id, lot.price) for lot in lots], [("9", 40.0)])

	def test_catalog_lots_raises_when_api_missing(self):
		gateway = FunPayCatalogGateway(SimpleNamespace(profile=SimpleNamespace(), account=SimpleNamespace()))

		with self.assertRaises(RuntimeError):
			gateway.catalog_lots()

	def test_update_price_uses_lot_fields(self):
		saved = {}

		class Fields:
			def __init__(self):
				self.price = 100.0

			def renew_fields(self):
				return {"price": self.price}

		fields = Fields()
		account = SimpleNamespace(
			get_lot_fields=lambda lot_id: fields,
			save_lot=lambda payload: saved.update(payload),
		)
		gateway = FunPayCatalogGateway(SimpleNamespace(profile=None, account=account))
		lot = Lot("1", "Gold", 100, "Gold", "me", raw=raw_lot("1", "Gold", 100))

		gateway.update_price(lot, 45.678)

		self.assertEqual(saved, {"price": 45.68})

	def test_update_price_rejects_non_positive(self):
		gateway = FunPayCatalogGateway(SimpleNamespace(profile=None, account=SimpleNamespace()))
		lot = Lot("1", "Gold", 100, "Gold", "me", raw=raw_lot("1", "Gold", 100))

		with self.assertRaises(ValueError):
			gateway.update_price(lot, 0)


class SelfCompetitionTest(unittest.TestCase):
	def test_ignores_other_own_lots_as_competitors(self):
		own_a = Lot("a", "My gold", 100, "Gold", "me")
		own_b = Lot("b", "My gold", 10, "Gold", "me")
		alien = Lot("c", "Cheap gold", 50, "Gold", "other")
		service = AutoDumpingService(lambda: {}, Gateway([own_a, own_b], []), Storage())

		decision = service.decide(own_a, [own_a, own_b, alien], config(rule()), {"a", "b"})

		self.assertEqual(decision.candidate.lot.id, "c")
		self.assertEqual(decision.candidate.final_price, 45.0)


class SingleNotifyTest(unittest.TestCase):
	def test_conflict_notifies_exactly_once(self):
		own = Lot("own", "My gold", 100, "Gold", "me")
		alien = Lot("c", "Gold fast", 50, "Gold", "other")
		settings = {
			"enabled": True,
			"interval_minutes": 5,
			"rules": [
				{"id": "one", "enabled": True, "subcategory": "Gold", "keywords": ["gold"],
					"keyword_mode": "any", "competitor_min_price": 0, "price_mode": "fixed",
					"dumping_value": 5, "own_min_price": 0},
				{"id": "two", "enabled": True, "subcategory": "Gold", "keywords": ["fast"],
					"keyword_mode": "any", "competitor_min_price": 0, "price_mode": "fixed",
					"dumping_value": 1, "own_min_price": 0},
			],
		}
		notifier = Notifier()
		service = AutoDumpingService(lambda: settings, Gateway([own], [alien]), Storage(), notifier)

		result = service.run_cycle()

		self.assertEqual(result["conflicts"], 1)
		self.assertEqual(len(notifier.calls), 1)

	def test_repeated_cycle_does_not_renotify_detected(self):
		own = Lot("own", "My gold", 49.0, "Gold", "me")
		alien = Lot("c", "Gold fast", 50, "Gold", "other")
		settings = {
			"enabled": True,
			"interval_minutes": 5,
			"rules": [
				{"id": "one", "enabled": True, "subcategory": "Gold", "keywords": ["gold"],
					"keyword_mode": "any", "competitor_min_price": 0, "price_mode": "fixed",
					"dumping_value": 1, "own_min_price": 0},
				{"id": "two", "enabled": True, "subcategory": "Gold", "keywords": ["fast"],
					"keyword_mode": "any", "competitor_min_price": 0, "price_mode": "fixed",
					"dumping_value": 1, "own_min_price": 0},
			],
		}
		notifier = Notifier()
		storage = Storage()
		service = AutoDumpingService(lambda: settings, Gateway([own], [alien]), storage, notifier)

		service.run_cycle()
		service.run_cycle()

		self.assertEqual([call[0] for call in notifier.calls], ["detected"])


class PriceGuardTest(unittest.TestCase):
	def test_skips_dust_difference(self):
		own = Lot("own", "My gold", 45.0, "Gold", "me")
		alien = Lot("c", "Gold", 50, "Gold", "other")
		service = AutoDumpingService(lambda: {}, Gateway([own], [alien]), Storage())

		decision = service.decide(own, [alien], config(rule()), {"own"})

		self.assertEqual(decision.candidate.final_price, 45.0)

	def test_run_cycle_skips_dust_and_zero_target(self):
		own = Lot("own", "My gold", 45.0, "Gold", "me")
		alien = Lot("c", "Gold", 50, "Gold", "other")
		settings = {
			"enabled": True,
			"interval_minutes": 5,
			"rules": [{
				"id": "one", "enabled": True, "subcategory": "Gold", "keywords": ["gold"],
				"keyword_mode": "any", "competitor_min_price": 0, "price_mode": "fixed",
				"dumping_value": 5, "own_min_price": 0,
			}],
		}
		gateway = Gateway([own], [alien])
		service = AutoDumpingService(lambda: settings, gateway, Storage())

		result = service.run_cycle()

		self.assertEqual(gateway.updated, [])
		self.assertEqual(result["updated"], 0)

	def test_run_cycle_skips_non_positive_target(self):
		own = Lot("own", "My gold", 100, "Gold", "me")
		alien = Lot("c", "Gold", 3, "Gold", "other")
		settings = {
			"enabled": True,
			"interval_minutes": 5,
			"rules": [{
				"id": "one", "enabled": True, "subcategory": "Gold", "keywords": ["gold"],
				"keyword_mode": "any", "competitor_min_price": 0, "price_mode": "fixed",
				"dumping_value": 5, "own_min_price": 0,
			}],
		}
		gateway = Gateway([own], [alien])
		service = AutoDumpingService(lambda: settings, gateway, Storage())

		result = service.run_cycle()

		self.assertEqual(gateway.updated, [])
		self.assertEqual(result["skipped"], 1)


class SchedulerResilienceTest(unittest.TestCase):
	def test_run_once_survives_service_error(self):
		class Broken:
			def __init__(self):
				self.calls = 0

			def run_cycle(self):
				self.calls += 1
				raise RuntimeError("boom")

		service = Broken()
		scheduler = AutoDumpingScheduler(service, 5)

		self.assertTrue(scheduler.run_once())
		self.assertTrue(scheduler.run_once())
		self.assertEqual(service.calls, 2)

	def test_set_interval_rejects_garbage(self):
		scheduler = AutoDumpingScheduler(SimpleNamespace(run_cycle=lambda: None), 5)
		scheduler.set_interval("abc")

		self.assertEqual(scheduler.interval_minutes, 5)

		scheduler.set_interval(0)

		self.assertEqual(scheduler.interval_minutes, 1)


if __name__ == "__main__":
	unittest.main()
