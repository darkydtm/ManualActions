from __future__ import annotations

from html import escape
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from telebot.types import InlineKeyboardButton as B, InlineKeyboardMarkup as K

from ..config.constants import CBT_UPDATER_INSTALL, CBT_UPDATER_SKIP, LOGGER_NAME, LOGGER_PREFIX, UUID, VERSION
from ..delivery.orchestrator import DeliveryOrchestrator
from ..funpay import MessageContext, extract_message_context, should_send_auto_status_message
from ..delivery.providers.gemini_service import GeminiDeliveryService
from ..delivery.providers.gemini_storage import GeminiDeliveryStorage
from ..delivery.providers.gpt_accounts_service import GptAccountsDeliveryService
from ..delivery.providers.gpt_accounts_storage import GptAccountsDeliveryStorage
from ..config.settings import DEFAULT_SETTINGS
from ..status.status import auto_message_text, parse_funpay_status_command, response_text
from ..storage.storage import PluginStorage
from ..runtime.settings import update_settings

from ..two_factor.service import TwoFactorService
from ..two_factor.storage import TwoFactorStorage
from ..telegram.commands import TelegramCommands
from ..telegram.settings import TelegramSettingsUI
from ..application.updater import MODE_DISABLED, ManualActionsUpdater, UpdaterRelease

if TYPE_CHECKING:
	from cardinal import Cardinal


logger = logging.getLogger(LOGGER_NAME)


class ManualActionsPlugin:
	_instance = None

	def __new__(cls, *args, **kwargs):
		if not cls._instance:
			cls._instance = super(ManualActionsPlugin, cls).__new__(cls)
		return cls._instance

	def __init__(self, crd: Cardinal, plugin_file_path: str | None = None):
		if hasattr(self, "initialized"):
			return

		self.initialized = True
		self.cardinal = crd
		self.tg = None
		self.tgbot = None
		self.plugin_file_path = Path(plugin_file_path or __file__).resolve()
		self.storage = PluginStorage()
		self.settings: dict[str, Any] = DEFAULT_SETTINGS.copy()
		self.updater: ManualActionsUpdater | None = None
		self.gemini_storage = GeminiDeliveryStorage()
		self.gpt_accounts_storage = GptAccountsDeliveryStorage()
		self.two_factor_storage = TwoFactorStorage()
		self.two_factor_service = TwoFactorService(
			self.cardinal,
			lambda: self.settings,
			self.two_factor_storage,
		)
		self.gemini_service = GeminiDeliveryService(
			self.cardinal,
			lambda: self.settings,
			self.gemini_storage,
			admin_notifier=self.send_telegram_admin_message,
		)
		self.gpt_accounts_service = GptAccountsDeliveryService(
			self.cardinal,
			lambda: self.settings,
			self.gpt_accounts_storage,
			admin_notifier=self.send_telegram_admin_message,
		)
		self.delivery_orchestrator = DeliveryOrchestrator(
			(self.gemini_service, self.gpt_accounts_service),
			logger,
		)
		self.telegram_ui = TelegramSettingsUI(self)
		self.telegram_commands = TelegramCommands(self)

		if self.cardinal.telegram:
			self.tg = self.cardinal.telegram
			self.tgbot = self.tg.bot

		setattr(ManualActionsPlugin.message_hook, "plugin_uuid", UUID)
		setattr(ManualActionsPlugin.new_order_hook, "plugin_uuid", UUID)

	def load(self) -> None:
		self.settings = self.storage.load_settings()
		self.gemini_storage.load()
		self.gpt_accounts_storage.load()
		self.two_factor_storage.load()
		self.configure_updater()

	def save_settings(self) -> None:
		self.storage.save_settings(self.settings)

	def update_settings(self, mutation) -> None:
		update_settings(self.settings, self.save_settings, mutation)

	def register(self) -> None:
		self.telegram_ui.register()
		self.telegram_commands.register()
		self.cardinal.new_message_handlers.append(self.message_hook)
		self.cardinal.last_chat_message_changed_handlers.append(self.message_hook)
		self.cardinal.new_order_handlers.append(self.new_order_hook)
		self.refresh_updater()

	def configure_updater(self) -> None:
		self.updater = ManualActionsUpdater(
			self.settings,
			self.save_settings,
			self.plugin_file_path,
			VERSION,
			on_update_available=self.notify_update_available,
			on_update_installed=self.notify_update_installed,
			on_update_error=self.log_update_error,
		)

	def refresh_updater(self) -> None:
		if not self.updater:
			return
		if self.settings["updater"]["mode"] == MODE_DISABLED:
			self.updater.stop()
			return
		self.updater.stop()
		self.updater.start()

	def shutdown(self) -> None:
		if self.updater:
			self.updater.stop()

	def install_update_version(self, version: str) -> Path:
		if not self.updater:
			self.configure_updater()
		if not self.updater:
			raise RuntimeError("Updater is not configured.")
		return self.updater.install_latest(version, notify=False)

	def skip_update_version(self, version: str) -> None:
		if self.updater:
			self.updater.skip_version(version)
			return
		value = version.strip()
		self.update_settings(
			lambda settings: settings["updater"].__setitem__("skipped_version", value)
		)

	def check_updates_manually(self):
		if not self.updater:
			self.configure_updater()
		if not self.updater:
			raise RuntimeError("Updater is not configured.")
		return self.updater.check_manually()

	def message_hook(self, c: Cardinal, e: object) -> None:
		context = extract_message_context(c, e)
		if not context:
			return
		if self.two_factor_service.handle_code_request(context):
			return
		self.two_factor_service.handle_seller_message(context)

		if parse_funpay_status_command(context.text):
			if self.is_blacklisted(context):
				return
			self.send_funpay_message(context.chat_id, response_text(self.settings))
			return

		if should_send_auto_status_message(context, self.settings):
			if self.is_blacklisted(context):
				return
			self.send_funpay_message(context.chat_id, auto_message_text(self.settings))

	def new_order_hook(self, c: Cardinal, e: object) -> None:
		self.delivery_orchestrator.handle_new_order(e)

	def is_blacklisted(self, context: MessageContext) -> bool:
		return bool(
			context.author
			and context.author in (self.cardinal.blacklist or [])
			and getattr(self.cardinal, "bl_response_enabled", False)
		)

	def send_funpay_message(self, chat_id: int | str, text: str) -> None:
		self.cardinal.send_message(chat_id=chat_id, message_text=text)

	def notify_update_available(self, release: UpdaterRelease) -> None:
		keyboard = K(row_width=2)
		keyboard.add(
			B("✅ Обновить", callback_data=f"{CBT_UPDATER_INSTALL}{release.version}"),
			B("❌ Отказаться", callback_data=f"{CBT_UPDATER_SKIP}{release.version}"),
		)
		text = (
			"<b>Manual Actions</b>\n\n"
			f"Доступно обновление: <code>{escape(release.version)}</code>\n"
			"Нажмите «Обновить», чтобы скачать новый файл плагина."
		)
		self.send_telegram_admin_message(text, keyboard)

	def notify_update_installed(self, release: UpdaterRelease, path: Path) -> None:
		text = (
			"<b>Manual Actions</b>\n\n"
			f"✅ Обновление <code>{escape(release.version)}</code> установлено.\n"
			f"Файл: <code>{escape(str(path))}</code>\n\n"
			"Перезапустите Cardinal, чтобы загрузить новую версию."
		)
		self.send_telegram_admin_message(text)

	def log_update_error(self, exc: Exception) -> None:
		logger.warning(f"{LOGGER_PREFIX} Updater error: {exc}")
		logger.debug("TRACEBACK", exc_info=True)

	def send_telegram_admin_message(self, text: str, keyboard: K | None = None) -> None:
		if not self.tgbot:
			return

		for user_id in self.telegram_admin_ids():
			try:
				self.tgbot.send_message(user_id, text, reply_markup=keyboard)
			except Exception as exc:
				logger.warning(f"{LOGGER_PREFIX} Failed to send updater notification to {user_id}: {exc}")

	def telegram_admin_ids(self) -> list[Any]:
		if not self.tg:
			return []

		users = getattr(self.tg, "authorized_users", []) or []
		result = []
		seen = set()
		for user_id in users:
			key = str(user_id)
			if key in seen:
				continue
			seen.add(key)
			result.append(user_id)
		return result


def pre_init(c: Cardinal, plugin_file_path: str | None = None) -> None:
	plugin = ManualActionsPlugin(c, plugin_file_path)
	plugin.load()
	plugin.register()
	logger.info(f"{LOGGER_PREFIX} Plugin v{VERSION} loaded.")


def delete(c: Cardinal) -> None:
	if ManualActionsPlugin._instance:
		ManualActionsPlugin._instance.shutdown()
