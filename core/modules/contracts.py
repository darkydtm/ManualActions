from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


SettingsNormalizer = Callable[[Any], Any]
ModuleHook = Callable[[Any], None]
ServiceFactory = Callable[[Any], dict[str, Any]]


@dataclass(frozen=True)
class SettingsSection:
	key: str
	default: Any
	normalize: SettingsNormalizer


@dataclass(frozen=True)
class ModuleDefinition:
	name: str
	settings_sections: tuple[SettingsSection, ...] = ()
	create_services: ServiceFactory | None = None
	load: ModuleHook | None = None
	register_funpay: ModuleHook | None = None
	register_telegram: ModuleHook | None = None
	shutdown: ModuleHook | None = None
	dependencies: tuple[str, ...] = field(default_factory=tuple)
