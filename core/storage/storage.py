from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import tempfile
from typing import Any

from ..config.constants import LOGGER_NAME, LOGGER_PREFIX, SETTINGS_FILE
from ..config.settings import normalize_settings


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
		temporary_path = None
		try:
			target.parent.mkdir(parents=True, exist_ok=True)
			with tempfile.NamedTemporaryFile(
				"w",
				encoding="utf-8",
				dir=target.parent,
				prefix=f".{target.name}.",
				delete=False,
			) as file:
				temporary_path = Path(file.name)
				json.dump(data, file, indent=4, ensure_ascii=False)
				file.write("\n")
				file.flush()
				os.fsync(file.fileno())
			os.replace(temporary_path, target)
		except Exception as exc:
			if temporary_path:
				temporary_path.unlink(missing_ok=True)
			logger.warning(f"{LOGGER_PREFIX} Failed to save {target}.")
			logger.debug("TRACEBACK", exc_info=True)
			raise StorageError(f"Failed to save {target}.") from exc
