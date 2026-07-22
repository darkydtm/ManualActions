from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from core.storage.storage import PluginStorage, StorageError
from core.two_factor.storage import TwoFactorStorage


class PluginStorageTest(unittest.TestCase):
	def setUp(self):
		self.directory = TemporaryDirectory()
		self.path = Path(self.directory.name) / "nested" / "settings.json"
		self.storage = PluginStorage()

	def tearDown(self):
		self.directory.cleanup()

	def test_save_dict_creates_valid_json(self):
		self.storage.save_dict(str(self.path), {"status": "1"})

		self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")), {"status": "1"})

	def test_failed_save_preserves_previous_file(self):
		self.path.parent.mkdir(parents=True)
		self.path.write_text('{"status": "1"}\n', encoding="utf-8")

		with self.assertRaises(StorageError):
			self.storage.save_dict(str(self.path), {"invalid": object()})

		self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")), {"status": "1"})

	def test_two_factor_memory_changes_only_after_successful_save(self):
		storage = TwoFactorStorage(str(self.path), self.storage)
		self.storage.save_dict = lambda path, data: (_ for _ in ()).throw(StorageError("offline"))

		with self.assertRaises(StorageError):
			storage.save(42, "secret")

		self.assertIsNone(storage.get_for_chat(42))


if __name__ == "__main__":
	unittest.main()
