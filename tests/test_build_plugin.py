from __future__ import annotations

import ast
import unittest

import build_plugin


class BuildPluginTest(unittest.TestCase):
	def test_build_source_is_valid_python(self):
		ast.parse(build_plugin.build_source())

	def test_moves_imports_to_header(self):
		tree = ast.parse(build_plugin.build_source())
		first_body_index = next(
			index
			for index, statement in enumerate(tree.body)
			if not self.is_import_header_statement(statement)
		)

		for statement in tree.body[first_body_index:]:
			self.assertFalse(self.is_import_header_statement(statement))

	def test_removes_local_imports(self):
		source = build_plugin.build_source()

		self.assertNotIn("from core.", source)
		self.assertNotIn("from .", source)

	def test_deduplicates_imports(self):
		lines = build_plugin.build_source().splitlines()

		self.assertEqual(lines.count("import logging"), 1)
		self.assertEqual(lines.count("from dataclasses import dataclass"), 1)
		self.assertEqual(
			[line for line in lines if line.startswith("from typing import ")],
			["from typing import TYPE_CHECKING, Any, Callable, Iterable, Protocol"],
		)
		self.assertNotIn("\timport telebot", lines)

	def test_includes_templates_flow_before_command_registration(self):
		templates_index = build_plugin.PACKAGE_MODULES.index("telegram/templates")
		commands_index = build_plugin.PACKAGE_MODULES.index("telegram/commands")

		self.assertLess(templates_index, commands_index)
		self.assertIn("class TelegramTemplatesFlow", build_plugin.build_source())

	def test_includes_gemini_modules_in_dependency_order(self):
		settings_index = build_plugin.PACKAGE_MODULES.index("gemini/settings")
		storage_index = build_plugin.PACKAGE_MODULES.index("gemini/storage")
		service_index = build_plugin.PACKAGE_MODULES.index("gemini/service")
		ui_index = build_plugin.PACKAGE_MODULES.index("gemini/ui")
		plugin_index = build_plugin.PACKAGE_MODULES.index("application/plugin")

		self.assertLess(settings_index, storage_index)
		self.assertLess(storage_index, service_index)
		self.assertLess(service_index, ui_index)
		self.assertLess(ui_index, plugin_index)
		source = build_plugin.build_source()
		self.assertIn("class GeminiDeliveryStorage", source)
		self.assertIn("class GeminiDeliveryService", source)
		self.assertIn("class TelegramGeminiDeliveryUI", source)

	def test_includes_two_factor_modules_before_plugin(self):
		service_index = build_plugin.PACKAGE_MODULES.index("two_factor/service")
		plugin_index = build_plugin.PACKAGE_MODULES.index("application/plugin")

		self.assertLess(service_index, plugin_index)
		self.assertIn("class TwoFactorService", build_plugin.build_source())

	def test_includes_lot_scheduling_before_settings(self):
		scheduling_index = build_plugin.PACKAGE_MODULES.index("lots/scheduling")
		settings_index = build_plugin.PACKAGE_MODULES.index("config/settings")

		self.assertLess(scheduling_index, settings_index)
		self.assertIn("DEFAULT_LOT_SCHEDULING_SETTINGS", build_plugin.build_source())

	@staticmethod
	def is_import_header_statement(statement: ast.stmt) -> bool:
		if isinstance(statement, (ast.Import, ast.ImportFrom)):
			return True
		if BuildPluginTest.is_type_checking_block(statement):
			return True
		return BuildPluginTest.is_optional_import_block(statement)

	@staticmethod
	def is_type_checking_block(statement: ast.stmt) -> bool:
		return (
			isinstance(statement, ast.If)
			and isinstance(statement.test, ast.Name)
			and statement.test.id == "TYPE_CHECKING"
		)

	@staticmethod
	def is_optional_import_block(statement: ast.stmt) -> bool:
		return (
			isinstance(statement, ast.Try)
			and any(isinstance(item, (ast.Import, ast.ImportFrom)) for item in statement.body)
		)


if __name__ == "__main__":
	unittest.main()
