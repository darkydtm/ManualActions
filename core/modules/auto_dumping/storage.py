from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from threading import RLock
from typing import Any

from ...config.constants import AUTO_DUMPING_STATE_FILE
from ...runtime.persistence import atomic_write_json


class AutoDumpingStorage:
	def __init__(self, path: str | Path = AUTO_DUMPING_STATE_FILE):
		self.path = Path(path)
		self.lock = RLock()
		self.state = self.load()

	def load(self) -> dict[str, Any]:
		with self.lock:
			try:
				data = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}
			except Exception:
				data = {}
			self.state = self.normalize(data)
			return deepcopy(self.state)

	def save(self) -> None:
		with self.lock:
			atomic_write_json(self.path, self.state)

	def record_cycle(self, timestamp: float, result: dict[str, Any]) -> None:
		with self.lock:
			self.state["last_cycle_at"] = timestamp
			self.state["last_result"] = deepcopy(result)
			self.save()

	def get_conflict_fingerprint(self, lot_id: str) -> str:
		with self.lock:
			return self.state["conflicts"].get(str(lot_id), "")

	def set_conflict_fingerprint(self, lot_id: str, fingerprint: str) -> None:
		with self.lock:
			self.state["conflicts"][str(lot_id)] = str(fingerprint)
			self.save()

	@staticmethod
	def normalize(data: Any) -> dict[str, Any]:
		if not isinstance(data, dict):
			data = {}
		result = {
			"last_cycle_at": data.get("last_cycle_at") if isinstance(data.get("last_cycle_at"), (int, float)) else None,
			"last_result": data.get("last_result") if isinstance(data.get("last_result"), dict) else {},
			"conflicts": data.get("conflicts") if isinstance(data.get("conflicts"), dict) else {},
		}
		return result
