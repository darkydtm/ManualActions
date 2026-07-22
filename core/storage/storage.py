from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from ..config.constants import LOGGER_NAME, LOGGER_PREFIX, SETTINGS_FILE
from ..config.settings import normalize_settings
from ..runtime.persistence import AtomicWriteError, atomic_write_json


logger = logging.getLogger(LOGGER_NAME)


class StorageError(RuntimeError):
	pass


class PluginStorage:
	def load_settings(self) -> dict[str, Any]:
		return normalize_settings(self.load_dict(SETTINGS_FILE))

	def save_settings(self, settings: dict[str, Any]) -> None:
		self.save_dict(SETTINGS_FILE, settings)

	def load_dict(self, path: str) -> dict[str, Any]:
		if not os.path.exists(path):
			return {}

		try:
			with open(path, "r", encoding="utf-8") as file:
				data = json.load(file)
		except Exception:
			logger.warning(f"{LOGGER_PREFIX} Failed to load {path}.")
			logger.debug("TRACEBACK", exc_info=True)
			return {}

		if not isinstance(data, dict):
			logger.warning(f"{LOGGER_PREFIX} Ignoring invalid JSON object in {path}.")
			return {}

		return data

	def save_dict(self, path: str, data: dict[str, Any]) -> None:
		target = Path(path)
		try:
			atomic_write_json(target, data)
		except AtomicWriteError as exc:
			logger.warning(f"{LOGGER_PREFIX} Failed to save {target}.")
			logger.debug("TRACEBACK", exc_info=True)
			raise StorageError(f"Failed to save {target}.") from exc
