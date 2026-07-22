from __future__ import annotations

from threading import RLock


class KeyedLockRegistry:
	def __init__(self):
		self._registry_lock = RLock()
		self._locks: dict[str, RLock] = {}

	def lock_for(self, key: str) -> RLock:
		with self._registry_lock:
			return self._locks.setdefault(str(key), RLock())
