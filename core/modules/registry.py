from __future__ import annotations

from collections.abc import Iterable
import importlib
import pkgutil
from typing import Any

from .contracts import ModuleDefinition, SettingsSection


REGISTERED_MODULES: list[ModuleDefinition] = []


def register_module(definition: ModuleDefinition) -> ModuleDefinition:
	if definition.name not in {item.name for item in REGISTERED_MODULES}:
		REGISTERED_MODULES.append(definition)
	return definition


class ModuleRegistry:
	def __init__(self, definitions: Iterable[ModuleDefinition]):
		self.definitions = tuple(sorted(definitions, key=lambda item: item.name))
		self._validate()

	@classmethod
	def discover(cls) -> "ModuleRegistry":
		if REGISTERED_MODULES:
			return cls(REGISTERED_MODULES)
		package = importlib.import_module("core.modules")
		for item in pkgutil.iter_modules(package.__path__):
			if not item.ispkg or item.name.startswith("_"):
				continue
			importlib.import_module(f"core.modules.{item.name}.module")
		return cls(REGISTERED_MODULES)

	@property
	def settings_sections(self) -> tuple[SettingsSection, ...]:
		return tuple(
			section
			for definition in self.definitions
			for section in definition.settings_sections
		)

	def create_services(self, host: Any) -> dict[str, Any]:
		services: dict[str, Any] = {}
		for definition in self.definitions:
			if definition.create_services:
				services.update(definition.create_services(host))
		return services

	def load(self, host: Any) -> None:
		self._run("load", host)

	def register_funpay(self, host: Any) -> None:
		self._run("register_funpay", host)

	def register_telegram(self, host: Any) -> None:
		self._run("register_telegram", host)

	def shutdown(self, host: Any) -> None:
		for definition in reversed(self.definitions):
			hook = definition.shutdown
			if hook:
				hook(host)

	def _run(self, name: str, host: Any) -> None:
		for definition in self.definitions:
			hook = getattr(definition, name)
			if hook:
				hook(host)

	def _validate(self) -> None:
		names = [definition.name for definition in self.definitions]
		if len(names) != len(set(names)):
			raise ValueError("Module names must be unique.")

		keys = [section.key for section in self.settings_sections]
		if len(keys) != len(set(keys)):
			raise ValueError("Settings section keys must be unique.")

		known = set(names)
		for definition in self.definitions:
			missing = set(definition.dependencies) - known
			if missing:
				raise ValueError(f"Module {definition.name} has unknown dependencies: {sorted(missing)}.")
