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

		self.assertNotIn("from manual_actions_core.", source)
		self.assertNotIn("from .", source)

	def test_deduplicates_imports(self):
		lines = build_plugin.build_source().splitlines()

		self.assertEqual(lines.count("import logging"), 1)
		self.assertEqual(lines.count("from dataclasses import dataclass"), 1)
		self.assertEqual(
			[line for line in lines if line.startswith("from typing import ")],
			["from typing import TYPE_CHECKING, Any, Callable, Protocol"],
		)
		self.assertNotIn("\timport telebot", lines)

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
