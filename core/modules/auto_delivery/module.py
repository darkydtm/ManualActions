from __future__ import annotations

import logging
from typing import Any

from ...delivery.orchestrator import DeliveryOrchestrator
from ...delivery.providers.gemini_service import GeminiDeliveryService
from ...delivery.providers.gemini_storage import GeminiDeliveryStorage
from ...delivery.providers.gpt_accounts_service import GptAccountsDeliveryService
from ...delivery.providers.gpt_accounts_storage import GptAccountsDeliveryStorage
from ..contracts import ModuleDefinition
from ..registry import register_module


def create_services(host: Any) -> dict[str, Any]:
	gemini_storage = GeminiDeliveryStorage()
	gpt_accounts_storage = GptAccountsDeliveryStorage()
	gemini_service = GeminiDeliveryService(
		host.cardinal,
		lambda: host.settings,
		gemini_storage,
		admin_notifier=host.send_telegram_admin_message,
	)
	gpt_accounts_service = GptAccountsDeliveryService(
		host.cardinal,
		lambda: host.settings,
		gpt_accounts_storage,
		admin_notifier=host.send_telegram_admin_message,
	)
	return {
		"gemini_storage": gemini_storage,
		"gpt_accounts_storage": gpt_accounts_storage,
		"gemini_service": gemini_service,
		"gpt_accounts_service": gpt_accounts_service,
		"delivery_orchestrator": DeliveryOrchestrator((gemini_service, gpt_accounts_service), logging.getLogger("manual_actions")),
	}


def load(host: Any) -> None:
	host.services["gemini_storage"].load()
	host.services["gpt_accounts_storage"].load()


MODULE = register_module(ModuleDefinition("auto_delivery", create_services=create_services, load=load))
