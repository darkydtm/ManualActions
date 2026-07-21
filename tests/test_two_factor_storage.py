from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.two_factor.storage import TwoFactorStorage


class TwoFactorStorageTest(unittest.TestCase):
	def test_persists_and_selects_latest_record_for_chat(self):
		with tempfile.TemporaryDirectory() as directory:
			path = str(Path(directory) / "two_factor.json")
			storage = TwoFactorStorage(path)
			storage.save("#first", 7, "FIRST")
			storage.save("second", 7, "SECOND")

			reloaded = TwoFactorStorage(path)
			reloaded.load()
			self.assertEqual(reloaded.get("first")["secret"], "FIRST")
			self.assertEqual(reloaded.latest_for_chat(7)["order_id"], "second")

	def test_ignores_malformed_records(self):
		self.assertEqual(TwoFactorStorage.normalize_orders({"A": {"secret": "x"}}), {})


if __name__ == "__main__":
	unittest.main()
