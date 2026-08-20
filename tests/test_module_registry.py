from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from core.modules.contracts import ModuleDefinition, SettingsSection
from core.modules import registry as registry_module
from core.modules.registry import ModuleRegistry


class ModuleRegistryTests(unittest.TestCase):
	def test_runs_lifecycle_hooks_in_name_order(self):
		calls = []
		registry = ModuleRegistry((
			ModuleDefinition("second", load=lambda host: calls.append("second")),
			ModuleDefinition("first", load=lambda host: calls.append("first")),
		))

		registry.load(object())

		self.assertEqual(calls, ["first", "second"])

	def test_rejects_duplicate_setting_keys(self):
		section = SettingsSection("shared", {}, lambda value: value)

		with self.assertRaisesRegex(ValueError, "Settings section keys"):
			ModuleRegistry((
				ModuleDefinition("first", (section,)),
				ModuleDefinition("second", (section,)),
			))

	def test_collects_created_services(self):
		registry = ModuleRegistry((
			ModuleDefinition("first", create_services=lambda host: {"first": 1}),
			ModuleDefinition("second", create_services=lambda host: {"second": 2}),
		))

		self.assertEqual(registry.create_services(object()), {"first": 1, "second": 2})

	def test_discover_imports_modules_even_when_one_was_already_registered(self):
		with patch.object(registry_module, "REGISTERED_MODULES", [ModuleDefinition("already_loaded")]):
			with patch.object(registry_module.pkgutil, "iter_modules", return_value=[
				SimpleNamespace(ispkg=True, name="first"),
			]):
				package = unittest.mock.Mock(__path__=["core/modules"])
				with patch.object(registry_module.importlib, "import_module", return_value=package) as import_module:
					ModuleRegistry.discover()

			import_module.assert_any_call("core.modules.first.module")
