from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from .constants import LOGGER_NAME, LOGGER_PREFIX, UUID, VERSION
from .funpay import MessageContext, extract_message_context, should_send_auto_status_message
from .settings import DEFAULT_SETTINGS
from .status import auto_message_text, parse_funpay_status_command, response_text
from .storage import PluginStorage
from .telegram_commands import TelegramCommands
from .telegram_settings import TelegramSettingsUI

if TYPE_CHECKING:
	from cardinal import Cardinal


logger = logging.getLogger(LOGGER_NAME)


class ManualActionsPlugin:
	_instance = None

	def __new__(cls, *args, **kwargs):
		if not cls._instance:
			cls._instance = super(ManualActionsPlugin, cls).__new__(cls)
		return cls._instance

	def __init__(self, crd: Cardinal):
		if hasattr(self, "initialized"):
			return

		self.initialized = True
		self.cardinal = crd
		self.tg = None
		self.tgbot = None
		self.storage = PluginStorage()
		self.settings: dict[str, Any] = DEFAULT_SETTINGS.copy()
		self.telegram_ui = TelegramSettingsUI(self)
		self.telegram_commands = TelegramCommands(self)

		if self.cardinal.telegram:
			self.tg = self.cardinal.telegram
			self.tgbot = self.tg.bot

		setattr(ManualActionsPlugin.message_hook, "plugin_uuid", UUID)

	def load(self) -> None:
		self.settings = self.storage.load_settings()

	def save_settings(self) -> None:
		self.storage.save_settings(self.settings)

	def register(self) -> None:
		self.telegram_ui.register()
		self.telegram_commands.register()
		self.cardinal.new_message_handlers.append(self.message_hook)
		self.cardinal.last_chat_message_changed_handlers.append(self.message_hook)

	def message_hook(self, c: Cardinal, e: object) -> None:
		context = extract_message_context(c, e)
		if not context:
			return

		if parse_funpay_status_command(context.text):
			if self.is_blacklisted(context):
				return
			self.send_funpay_message(context.chat_id, response_text(self.settings))
			return

		if should_send_auto_status_message(context, self.settings):
			if self.is_blacklisted(context):
				return
			self.send_funpay_message(context.chat_id, auto_message_text(self.settings))

	def is_blacklisted(self, context: MessageContext) -> bool:
		return bool(
			context.author
			and context.author in (self.cardinal.blacklist or [])
			and getattr(self.cardinal, "bl_response_enabled", False)
		)

	def send_funpay_message(self, chat_id: int | str, text: str) -> None:
		self.cardinal.send_message(chat_id=chat_id, message_text=text)


def pre_init(c: Cardinal) -> None:
	plugin = ManualActionsPlugin(c)
	plugin.load()
	plugin.register()
	logger.info(f"{LOGGER_PREFIX} Plugin v{VERSION} loaded.")
