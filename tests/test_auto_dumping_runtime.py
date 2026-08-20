from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from core.modules.auto_dumping.scheduler import AutoDumpingScheduler
from core.modules.auto_dumping.storage import AutoDumpingStorage


class AutoDumpingRuntimeTest(unittest.TestCase):
	def test_storage_persists_cycle_and_conflict_state(self):
		with tempfile.TemporaryDirectory() as directory:
			path = Path(directory) / "state.json"
			storage = AutoDumpingStorage(path)
			storage.record_cycle(12.5, {"updated": 2})
			storage.set_conflict_fingerprint("lot-1", "rules|one")

			reloaded = AutoDumpingStorage(path)
			self.assertEqual(reloaded.state["last_cycle_at"], 12.5)
			self.assertEqual(reloaded.state["last_result"], {"updated": 2})
			self.assertEqual(reloaded.get_conflict_fingerprint("lot-1"), "rules|one")

	def test_scheduler_does_not_overlap_cycles(self):
		class Service:
			def __init__(self):
				self.active = 0
				self.maximum = 0

			def run_cycle(self):
				self.active += 1
				self.maximum = max(self.maximum, self.active)
				time.sleep(0.02)
				self.active -= 1

		service = Service()
		scheduler = AutoDumpingScheduler(service, 1)
		scheduler.run_once()
		scheduler.run_once()
		self.assertEqual(service.maximum, 1)

	def test_scheduler_stop_ends_worker(self):
		class Service:
			def run_cycle(self):
				return None

		scheduler = AutoDumpingScheduler(Service(), 1)
		scheduler.start()
		self.assertTrue(scheduler.running)
		scheduler.stop()
		self.assertFalse(scheduler.running)


if __name__ == "__main__":
	unittest.main()
