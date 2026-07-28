from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.lots.bulk import ACTION_OFF, ACTION_ON, BulkLotsService


class FakeLotFields:
	def __init__(self, lot_id: str, active: bool):
		self.lot_id = lot_id
		self.active = active


class FakeAccount:
	def __init__(self, states: dict[str, bool], failing_ids: set[str] | None = None):
		self.states = states
		self.failing_ids = failing_ids or set()
		self.saved: list[str] = []

	def get_lot_fields(self, lot_id: int) -> FakeLotFields:
		lot_key = str(lot_id)
		return FakeLotFields(lot_key, self.states[lot_key])

	def save_lot(self, fields: FakeLotFields) -> None:
		if fields.lot_id in self.failing_ids:
			raise RuntimeError("save failed")
		self.states[fields.lot_id] = fields.active
		self.saved.append(fields.lot_id)


class FakeThread:
	def __init__(self, target, args, name, daemon):
		self.target = target
		self.args = args
		self.name = name
		self.daemon = daemon
		self.started = False

	def start(self) -> None:
		self.started = True


def fake_cardinal(
	states: dict[str, bool],
	failing_ids: set[str] | None = None,
	include_active: bool = True,
) -> SimpleNamespace:
	account = FakeAccount(states, failing_ids)
	def get_lots():
		return [
			SimpleNamespace(id=lot_id, **({"active": active} if include_active else {}))
			for lot_id, active in states.items()
		]

	profile = SimpleNamespace(
		get_lots=get_lots,
	)
	return SimpleNamespace(account=account, profile=profile)


class BulkLotsServiceTest(unittest.TestCase):
	def test_off_selects_only_active_lots_and_records_successful_ids(self):
		settings = {"bulk_lots": {"disabled_lot_ids": []}}
		service = BulkLotsService(fake_cardinal({"1": True, "2": True, "3": False}, {"2"}), settings, lambda: None)

		result = service.execute(ACTION_OFF)

		self.assertEqual((result.total, result.succeeded, result.failed), (2, 1, 1))
		self.assertEqual(settings["bulk_lots"]["disabled_lot_ids"], ["1"])

	def test_on_selects_all_inactive_lots(self):
		settings = {"bulk_lots": {"disabled_lot_ids": []}}
		cardinal = fake_cardinal({"1": False, "2": True})

		result = BulkLotsService(cardinal, settings, lambda: None).execute(ACTION_ON)

		self.assertEqual((result.total, result.succeeded, result.skipped), (1, 1, 0))
		self.assertEqual(cardinal.account.saved, ["1"])
		self.assertEqual(cardinal.account.states, {"1": True, "2": True})

	def test_on_uses_lot_fields_when_list_items_have_no_active_state(self):
		settings = {"bulk_lots": {"disabled_lot_ids": []}}
		cardinal = fake_cardinal({"1": False, "2": True}, include_active=False)

		result = BulkLotsService(cardinal, settings, lambda: None).execute(ACTION_ON)

		self.assertEqual((result.total, result.succeeded, result.skipped), (1, 1, 0))
		self.assertEqual(cardinal.account.saved, ["1"])

	def test_on_retains_failed_ids_and_removes_completed_ids(self):
		settings = {"bulk_lots": {"disabled_lot_ids": ["1", "2"]}}
		service = BulkLotsService(fake_cardinal({"1": False, "2": False}, {"2"}), settings, lambda: None)

		result = service.execute(ACTION_ON)

		self.assertEqual((result.succeeded, result.failed), (1, 1))
		self.assertEqual(settings["bulk_lots"]["disabled_lot_ids"], ["2"])

	def test_on_ignores_active_lots_and_removes_stale_disabled_ids(self):
		settings = {"bulk_lots": {"disabled_lot_ids": ["1"]}}
		cardinal = fake_cardinal({"1": True})

		result = BulkLotsService(cardinal, settings, lambda: None).execute(ACTION_ON)

		self.assertEqual((result.total, result.succeeded, result.skipped), (0, 0, 0))
		self.assertEqual(cardinal.account.saved, [])
		self.assertEqual(settings["bulk_lots"]["disabled_lot_ids"], [])

	def test_start_rejects_a_second_operation_until_the_first_completes(self):
		service = BulkLotsService(fake_cardinal({"1": True}), {"bulk_lots": {"disabled_lot_ids": []}}, lambda: None)

		with patch("core.lots.bulk.threading.Thread", FakeThread):
			self.assertTrue(service.start(ACTION_OFF, lambda progress: None, lambda result: None))
			self.assertFalse(service.start(ACTION_OFF, lambda progress: None, lambda result: None))


if __name__ == "__main__":
	unittest.main()
