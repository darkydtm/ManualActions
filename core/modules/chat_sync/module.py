from __future__ import annotations

from typing import Any

from ...chat_sync.service import ChatSyncService
from ...chat_sync.settings import DEFAULT_CHAT_SYNC_SETTINGS, normalize_chat_sync_settings
from ...chat_sync.telegram import TelegramChatSyncFlow
from ...chat_sync.ui import TelegramChatSyncSettingsUI
from ..contracts import ModuleDefinition, SettingsSection
from ..registry import register_module


def create_services(host: Any) -> dict[str, Any]:
	service = ChatSyncService(host)
	return {
		"chat_sync_service": service,
		"chat_sync_flow": TelegramChatSyncFlow(host, service),
		"chat_sync_ui": TelegramChatSyncSettingsUI(host, service),
	}


def load(host: Any) -> None:
	host.services["chat_sync_service"].load()


def register_funpay(host: Any) -> None:
	host.services["chat_sync_service"].register_funpay()


def register_telegram(host: Any) -> None:
	host.services["chat_sync_ui"].register()
	host.services["chat_sync_flow"].register()


def shutdown(host: Any) -> None:
	host.services["chat_sync_service"].shutdown()


MODULE = register_module(ModuleDefinition(
	"chat_sync",
	settings_sections=(SettingsSection("chat_sync", DEFAULT_CHAT_SYNC_SETTINGS, normalize_chat_sync_settings),),
	create_services=create_services,
	load=load,
	register_funpay=register_funpay,
	register_telegram=register_telegram,
	shutdown=shutdown,
))
