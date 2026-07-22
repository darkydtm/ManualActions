from __future__ import annotations

from copy import deepcopy
from threading import RLock
import time
from typing import Any

from ..config.constants import TWO_FACTOR_FILE
from ..storage.storage import PluginStorage


class TwoFactorStorage:
	def __init__(self, path: str = TWO_FACTOR_FILE, storage: PluginStorage | None = None):
		self.path = path
		self.storage = storage or PluginStorage()
		self.lock = RLock()
		self.chats: dict[str, dict[str, Any]] = {}

	def load(self) -> None:
		with self.lock:
			self.chats = self.normalize_chats(self.storage.load_dict(self.path).get("chats"))

	def save(self, chat_id: int | str, secret: str) -> None:
		if chat_id is None or not secret.strip():
			return

		with self.lock:
			chats = deepcopy(self.chats)
			chats[str(chat_id)] = {
				"chat_id": chat_id,
				"secret": secret.strip(),
				"updated_at": time.time(),
			}
			self.storage.save_dict(self.path, {"chats": chats})
			self.chats = chats

	def get_for_chat(self, chat_id: int | str) -> dict[str, Any] | None:
		with self.lock:
			record = self.chats.get(str(chat_id))
			return deepcopy(record) if record else None

	@classmethod
	def normalize_chats(cls, data: object) -> dict[str, dict[str, Any]]:
		if not isinstance(data, dict):
			return {}

		chats = {}
		for chat_key, record in data.items():
			if not isinstance(record, dict):
				continue
			secret = record.get("secret")
			chat_id = record.get("chat_id")
			updated_at = record.get("updated_at")
			if str(chat_key) != str(chat_id) or not isinstance(secret, str) or not secret.strip() or chat_id is None:
				continue
			if not isinstance(updated_at, (int, float)) or isinstance(updated_at, bool):
				continue
			chats[str(chat_id)] = {
				"chat_id": chat_id,
				"secret": secret.strip(),
				"updated_at": updated_at,
			}
		return chats

	@staticmethod
	def normalize_order_id(order_id: object) -> str:
		return str(order_id or "").strip().lstrip("#")
