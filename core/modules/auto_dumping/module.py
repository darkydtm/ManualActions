from __future__ import annotations

from typing import Any

from .funpay import FunPayCatalogGateway
from .notifications import ConflictNotifier
from .scheduler import AutoDumpingScheduler
from .service import AutoDumpingService
from .settings import DEFAULT_AUTO_DUMPING_SETTINGS, normalize_auto_dumping_settings
from .storage import AutoDumpingStorage
from .telegram import TelegramAutoDumpingFlow
from ..contracts import ModuleDefinition, SettingsSection
from ..registry import register_module


def create_services(host: Any) -> dict[str, Any]:
	storage = AutoDumpingStorage()
	notifier = ConflictNotifier(host.send_telegram_admin_message)
	service = AutoDumpingService(lambda: host.settings["auto_dumping"], FunPayCatalogGateway(host.cardinal), storage, notifier)
	scheduler = AutoDumpingScheduler(service, host.settings.get("auto_dumping", {}).get("interval_minutes", 5))
	return {
		"auto_dumping_storage": storage,
		"auto_dumping_service": service,
		"auto_dumping_scheduler": scheduler,
		"auto_dumping_flow": TelegramAutoDumpingFlow(host, service, scheduler),
	}


def load(host: Any) -> None:
	service = host.services["auto_dumping_service"]
	scheduler = host.services["auto_dumping_scheduler"]
	service.load()
	scheduler.interval_minutes = host.settings["auto_dumping"]["interval_minutes"]
	if host.settings["auto_dumping"]["enabled"]:
		scheduler.start()


def register_telegram(host: Any) -> None:
	host.services["auto_dumping_flow"].register()


def shutdown(host: Any) -> None:
	host.services["auto_dumping_scheduler"].stop()


MODULE = register_module(ModuleDefinition(
	"auto_dumping",
	settings_sections=(SettingsSection("auto_dumping", DEFAULT_AUTO_DUMPING_SETTINGS, normalize_auto_dumping_settings),),
	create_services=create_services,
	load=load,
	register_telegram=register_telegram,
	shutdown=shutdown,
))
