from __future__ import annotations

from threading import Event, Lock, Thread, current_thread
import time
from typing import Any, Callable


class AutoDumpingScheduler:
	def __init__(
		self,
		service: Any,
		interval_minutes: int,
		time_func: Callable[[], float] = time.monotonic,
		sleep_func: Callable[[float], None] = time.sleep,
	):
		self.service = service
		self.interval_minutes = max(int(interval_minutes), 1)
		self.time_func = time_func
		self.sleep_func = sleep_func
		self._stop = Event()
		self._cycle_lock = Lock()
		self._thread: Thread | None = None

	@property
	def running(self) -> bool:
		return bool(self._thread and self._thread.is_alive())

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
			self.service.run_cycle()
		finally:
			self._cycle_lock.release()
		return True

	def _run(self) -> None:
		while not self._stop.wait(self.interval_minutes * 60):
			self.run_once()
