from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tools.validate_project import ValidationError, validate_generated_source, validate_local_imports


class ProjectValidationTest(unittest.TestCase):
	def test_rejects_missing_relative_module(self):
		with TemporaryDirectory() as directory:
			core = Path(directory) / "core"
			core.mkdir()
			(core / "feature.py").write_text("from .missing import value\n", encoding="utf-8")

			with self.assertRaises(ValidationError):
				validate_local_imports(core)

	def test_generated_source_is_valid_without_local_imports(self):
		validate_generated_source()

	def test_ui_settings_writes_use_transaction_helper(self):
		for path in Path("core").rglob("*.py"):
			if path.name in {"plugin.py", "updater.py"}:
				continue
			source = path.read_text(encoding="utf-8")
			self.assertNotIn("self.host.save_settings()", source, path)


if __name__ == "__main__":
	unittest.main()
