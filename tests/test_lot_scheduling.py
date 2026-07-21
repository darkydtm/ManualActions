from __future__ import annotations

from datetime import datetime
import unittest
from zoneinfo import ZoneInfo

from core.lots.scheduling import due_action, normalize_lot_scheduling_settings


class LotSchedulingTest(unittest.TestCase):
	def test_defaults_to_disabled_moscow_timezone(self):
		settings = normalize_lot_scheduling_settings({})
		self.assertFalse(settings["enabled"])
		self.assertEqual(settings["timezone"], "Europe/Moscow")

	def test_daily_window_has_start_and_end_actions(self):
		settings = normalize_lot_scheduling_settings({
			"rules": [{
				"target": {"kind": "all"},
				"schedule": {"kind": "daily", "start": "12:00", "end": "15:00"},
			}],
		})
		rule = settings["rules"][0]
		zone = ZoneInfo("Europe/Moscow")
		self.assertEqual(due_action(rule, datetime(2026, 7, 21, 12, 0, tzinfo=zone)), "deactivate")
		self.assertEqual(due_action(rule, datetime(2026, 7, 21, 15, 0, tzinfo=zone)), "restore")


if __name__ == "__main__":
	unittest.main()
