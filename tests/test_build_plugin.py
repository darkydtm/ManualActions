from __future__ import annotations

import ast
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import types
import unittest
from unittest.mock import patch

import build_plugin


class BuildPluginTest(unittest.TestCase):
	def test_build_source_is_valid_python(self):
		ast.parse(build_plugin.build_source())

	def test_generated_source_keeps_gemini_reservation_result(self):
		module = types.ModuleType("manual_actions_generated")
		dependencies = self.build_dependencies()
		dependencies[module.__name__] = module
		with TemporaryDirectory() as directory, patch.dict(sys.modules, dependencies):
			exec(build_plugin.build_source(), module.__dict__)
			link = "https://one.google.com/activate-plan/subscription/new/link"
			storage = module.GeminiDeliveryStorage(Path(directory) / "gemini_delivery.json")
			storage.add_links((link,))

			result = storage.reserve(
				module.OrderReservationRequest("ORDER-1", 1),
				"partial",
			)

		self.assertIsInstance(result, module.GeminiReservationResult)
		self.assertEqual(result.links, (link,))

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
		self.assertEqual(sum(line.startswith("from dataclasses import ") for line in lines), 1)
		self.assertEqual(len([line for line in lines if line.startswith("from typing import ")]), 1)
		self.assertNotIn("\timport telebot", lines)

	def test_includes_templates_flow_before_command_registration(self):
		modules = build_plugin.discover_package_modules()
		templates_index = modules.index("telegram/templates")
		commands_index = modules.index("telegram/commands")

		self.assertLess(templates_index, commands_index)
		self.assertIn("class TelegramTemplatesFlow", build_plugin.build_source())

	def test_includes_gemini_modules_in_dependency_order(self):
		modules = build_plugin.discover_package_modules()
		settings_index = modules.index("delivery/providers/gemini")
		storage_index = modules.index("delivery/providers/gemini_storage")
		service_index = modules.index("delivery/providers/gemini_service")
		ui_index = modules.index("delivery/providers/gemini_ui")
		plugin_index = modules.index("application/plugin")

		self.assertLess(settings_index, storage_index)
		self.assertLess(storage_index, service_index)
		self.assertLess(service_index, ui_index)
		self.assertLess(ui_index, plugin_index)
		source = build_plugin.build_source()
		self.assertIn("class GeminiDeliveryStorage", source)
		self.assertIn("class GeminiDeliveryService", source)
		self.assertIn("class TelegramGeminiDeliveryUI", source)

	def test_includes_gpt_account_modules_in_dependency_order(self):
		modules = build_plugin.discover_package_modules()
		settings_index = modules.index("delivery/providers/gpt_accounts")
		storage_index = modules.index("delivery/providers/gpt_accounts_storage")
		service_index = modules.index("delivery/providers/gpt_accounts_service")
		ui_index = modules.index("delivery/providers/gpt_accounts_ui")
		plugin_index = modules.index("application/plugin")

		self.assertLess(settings_index, storage_index)
		self.assertLess(storage_index, service_index)
		self.assertLess(service_index, ui_index)
		self.assertLess(ui_index, plugin_index)
		self.assertIn("class GptAccountsDeliveryService", build_plugin.build_source())

	def test_includes_two_factor_modules_before_plugin(self):
		modules = build_plugin.discover_package_modules()
		service_index = modules.index("two_factor/service")
		plugin_index = modules.index("application/plugin")

		self.assertLess(service_index, plugin_index)
		self.assertIn("class TwoFactorService", build_plugin.build_source())

	def test_includes_lot_scheduling_before_settings(self):
		modules = build_plugin.discover_package_modules()
		scheduling_index = modules.index("lots/scheduling")
		settings_index = modules.index("config/settings")

		self.assertLess(scheduling_index, settings_index)
		self.assertIn("DEFAULT_LOT_SCHEDULING_SETTINGS", build_plugin.build_source())

	@staticmethod
	def build_dependencies():
		telebot = types.ModuleType("telebot")
		telebot_types = types.ModuleType("telebot.types")
		telebot_types.CallbackQuery = object
		telebot_types.InlineKeyboardButton = object
		telebot_types.InlineKeyboardMarkup = object
		telebot_types.Message = object
		telebot.TeleBot = object
		telebot.types = telebot_types

		tg_bot = types.ModuleType("tg_bot")
		tg_bot.CBT = types.SimpleNamespace()
		tg_bot_static_keyboards = types.ModuleType("tg_bot.static_keyboards")
		tg_bot_utils = types.ModuleType("tg_bot.utils")
		tg_bot_utils.escape = lambda value: value
		tg_bot.static_keyboards = tg_bot_static_keyboards

		utils = types.ModuleType("Utils")
		utils.cardinal_tools = types.SimpleNamespace(cache_blacklist=lambda blacklist: None)
		return {
			"Utils": utils,
			"telebot": telebot,
			"telebot.types": telebot_types,
			"tg_bot": tg_bot,
			"tg_bot.static_keyboards": tg_bot_static_keyboards,
			"tg_bot.utils": tg_bot_utils,
		}

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
