from __future__ import annotations

from copy import deepcopy
from threading import RLock
import time
from typing import Any

from ..constants import TWO_FACTOR_FILE
from ..storage import PluginStorage


class TwoFactorStorage:
	def __init__(self, path: str = TWO_FACTOR_FILE, storage: PluginStorage | None = None):
		self.path = path
		self.storage = storage or PluginStorage()
		self.lock = RLock()
		self.orders: dict[str, dict[str, Any]] = {}

	def load(self) -> None:
		with self.lock:
			self.orders = self.normalize_orders(self.storage.load_dict(self.path).get("orders"))

	def save(self, order_id: str, chat_id: int | str, secret: str) -> None:
		order_id = self.normalize_order_id(order_id)
		if not order_id or chat_id is None or not secret.strip():
			return

		with self.lock:
			self.orders[order_id] = {
				"order_id": order_id,
				"chat_id": chat_id,
				"secret": secret.strip(),
				"updated_at": time.time(),
			}
			self.storage.save_dict(self.path, {"orders": self.orders})

	def get(self, order_id: str) -> dict[str, Any] | None:
		with self.lock:
			record = self.orders.get(self.normalize_order_id(order_id))
			return deepcopy(record) if record else None

	def latest_for_chat(self, chat_id: int | str) -> dict[str, Any] | None:
		with self.lock:
			records = [record for record in self.orders.values() if str(record["chat_id"]) == str(chat_id)]
			if not records:
				return None
			return deepcopy(max(records, key=lambda record: record["updated_at"]))

	@classmethod
	def normalize_orders(cls, data: object) -> dict[str, dict[str, Any]]:
		if not isinstance(data, dict):
			return {}

		orders = {}
		for order_id, record in data.items():
			if not isinstance(record, dict):
				continue
			normalized_id = cls.normalize_order_id(order_id)
			secret = record.get("secret")
			chat_id = record.get("chat_id")
			updated_at = record.get("updated_at")
			if not normalized_id or not isinstance(secret, str) or not secret.strip() or chat_id is None:
				continue
			if not isinstance(updated_at, (int, float)) or isinstance(updated_at, bool):
				continue
			orders[normalized_id] = {
				"order_id": normalized_id,
				"chat_id": chat_id,
				"secret": secret.strip(),
				"updated_at": updated_at,
			}
		return orders

	@staticmethod
	def normalize_order_id(order_id: object) -> str:
		return str(order_id or "").strip().lstrip("#")
