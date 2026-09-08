from __future__ import annotations

import logging
from threading import Event, Lock, Thread, current_thread
import time
from typing import Any, Callable


logger = logging.getLogger("FPC.manual_actions")


class AutoDumpingScheduler:
	def __init__(
		self,
		service: Any,
		interval_minutes: int,
		time_func: Callable[[], float] = time.monotonic,
		sleep_func: Callable[[float], None] = time.sleep,
	):
		self.service = service
		self.interval_minutes = 5
		self.set_interval(interval_minutes)
		self.time_func = time_func
		self.sleep_func = sleep_func
		self._stop = Event()
		self._cycle_lock = Lock()
		self._thread: Thread | None = None

	@property
	def running(self) -> bool:
		return bool(self._thread and self._thread.is_alive())

	def set_interval(self, interval_minutes: int) -> None:
		try:
			value = int(interval_minutes)
		except (TypeError, ValueError, OverflowError):
			logger.warning(
				"Auto-dumping interval %r is invalid, keeping %s.",
				interval_minutes,
				self.interval_minutes,
			)
			return
		self.interval_minutes = max(value, 1)

	def start(self) -> None:
		if self.running:
			return
		self._stop.clear()
		self._thread = Thread(target=self._run, name="manual-actions-auto-dumping", daemon=True)
		self._thread.start()

	def stop(self) -> None:
		self._stop.set()
		if self._thread and self._thread is not current_thread():
			self._thread.join(timeout=2)
		self._thread = None

	def run_once(self) -> bool:
		if not self._cycle_lock.acquire(blocking=False):
			return False
		try:
			try:
				self.service.run_cycle()
			except Exception:
				logger.exception("Auto-dumping cycle failed.")
		finally:
			self._cycle_lock.release()
		return True

	def _run(self) -> None:
		while not self._stop.wait(self.interval_minutes * 60):
			self.run_once()
