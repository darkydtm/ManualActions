from __future__ import annotations

import unittest

from core.modules.contracts import ModuleDefinition, SettingsSection
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
