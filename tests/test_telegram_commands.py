from __future__ import annotations

from types import SimpleNamespace
import sys
import types
import unittest


telebot_module = types.ModuleType("telebot")
telebot_types_module = types.ModuleType("telebot.types")
telebot_types_module.CallbackQuery = object
telebot_types_module.Message = object
telebot_types_module.InlineKeyboardButton = object
telebot_types_module.InlineKeyboardMarkup = object
telebot_module.TeleBot = object
telebot_module.types = telebot_types_module
sys.modules.setdefault("telebot", telebot_module)
sys.modules.setdefault("telebot.types", telebot_types_module)

tg_bot_module = types.ModuleType("tg_bot")
tg_bot_static_keyboards_module = types.ModuleType("tg_bot.static_keyboards")
tg_bot_utils_module = types.ModuleType("tg_bot.utils")
tg_bot_module.CBT = SimpleNamespace(PLUGIN_SETTINGS="plugin_settings", EDIT_PLUGIN="edit_plugin")
tg_bot_static_keyboards_module.CLEAR_STATE_BTN = lambda: None
tg_bot_utils_module.escape = lambda value: value
sys.modules.setdefault("tg_bot", tg_bot_module)
sys.modules.setdefault("tg_bot.static_keyboards", tg_bot_static_keyboards_module)
sys.modules.setdefault("tg_bot.utils", tg_bot_utils_module)
sys.modules["tg_bot"].static_keyboards = sys.modules["tg_bot.static_keyboards"]

utils_module = types.ModuleType("Utils")
utils_module.cardinal_tools = SimpleNamespace(cache_blacklist=lambda blacklist: None)
sys.modules.setdefault("Utils", utils_module)

from core.telegram.commands import TelegramCommands


class FakeTelegram:
	def __init__(self):
		self.handlers = []

	def cbq_handler(self, handler, func):
		self.handlers.append(("callback", handler))

	def msg_handler(self, handler, commands=None, **kwargs):
		self.handlers.append(("message", handler, tuple(commands or ())))


class FakeCardinal:
	def __init__(self):
		self.commands = []

	def add_telegram_commands(self, uuid, commands):
		self.commands.extend(commands)


class TelegramCommandsTest(unittest.TestCase):
	def test_escapes_gist_placeholder_in_menu_description(self):
		command = next(command for command in TelegramCommands.COMMANDS if command[0] == "gist")
		self.assertIn("/gist &lt;текст&gt;", command[1])
		self.assertNotIn("/gist <текст>", command[1])

	def test_registers_all_menu_commands_and_update_handler(self):
		tg = FakeTelegram()
		cardinal = FakeCardinal()
		host = SimpleNamespace(tg=tg, tgbot=SimpleNamespace(), cardinal=cardinal)
		TelegramCommands(host).register()

		menu_commands = {command[0] for command in cardinal.commands}
		handled_commands = {
		command
		for kind, *data in tg.handlers
		if kind == "message"
		for command in data[1]
	}
		self.assertIn("update", menu_commands)
		self.assertIn("update", handled_commands)
		self.assertEqual(menu_commands - handled_commands, set())


if __name__ == "__main__":
	unittest.main()
