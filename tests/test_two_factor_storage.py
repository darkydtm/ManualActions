from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.two_factor.storage import TwoFactorStorage


class TwoFactorStorageTest(unittest.TestCase):
	def test_persists_record_for_chat(self):
		with tempfile.TemporaryDirectory() as directory:
			path = str(Path(directory) / "two_factor.json")
			storage = TwoFactorStorage(path)
			storage.save(7, "FIRST")
			storage.save(7, "SECOND")

			reloaded = TwoFactorStorage(path)
			reloaded.load()
			self.assertEqual(reloaded.get_for_chat(7)["secret"], "SECOND")

	def test_ignores_malformed_records(self):
		self.assertEqual(TwoFactorStorage.normalize_chats({"A": {"secret": "x"}}), {})


if __name__ == "__main__":
	unittest.main()
