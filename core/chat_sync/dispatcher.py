from __future__ import annotations

from collections.abc import Callable
import logging
import queue
import threading
import time
from typing import Any, TypeVar

from ..config.constants import LOGGER_NAME, LOGGER_PREFIX
from ..runtime import ExternalResult
from ..runtime.logging import sanitize_message


T = TypeVar("T")

logger = logging.getLogger(LOGGER_NAME)

_STOP = object()

DEFAULT_MESSAGES_PER_MINUTE = 20
DEFAULT_MIN_INTERVAL = 0.4
DEFAULT_MAX_RETRIES = 3
MAX_RETRY_AFTER = 120


class TelegramRateLimiter:
	"""Token bucket sized for the Telegram per-group message limit."""

	def __init__(
		self,
		messages_per_minute: int = DEFAULT_MESSAGES_PER_MINUTE,
		min_interval: float = DEFAULT_MIN_INTERVAL,
		clock: Callable[[], float] = time.monotonic,
		sleeper: Callable[[float], None] = time.sleep,
	):
		self.min_interval = max(0.0, min_interval)
		self.clock = clock
		self.sleeper = sleeper
		self._lock = threading.Lock()
		self._capacity = 1.0
		self._tokens = 0.0
		self._refill_per_second = 1.0
		self._updated_at = clock()
		self._last_call_at = float("-inf")
		self.configure(messages_per_minute, fill=True)

	def configure(self, messages_per_minute: int, fill: bool = False) -> None:
		rate = max(1, int(messages_per_minute or DEFAULT_MESSAGES_PER_MINUTE))
		with self._lock:
			self._capacity = float(rate)
			self._refill_per_second = rate / 60.0
			self._tokens = self._capacity if fill else min(self._tokens, self._capacity)

	def acquire(self) -> None:
		while True:
			with self._lock:
				now = self.clock()
				elapsed = max(0.0, now - self._updated_at)
				self._updated_at = now
				self._tokens = min(self._capacity, self._tokens + elapsed * self._refill_per_second)

				delay = 0.0
				if self._tokens < 1.0:
					delay = (1.0 - self._tokens) / self._refill_per_second
				gap = self.min_interval - (now - self._last_call_at)
				if gap > delay:
					delay = gap

				if delay <= 0:
					self._tokens -= 1.0
					self._last_call_at = now
					return

			self.sleeper(delay)


class TelegramSender:
	"""Runs Telegram calls through the rate limiter and retries on 429."""

	def __init__(
		self,
		limiter: TelegramRateLimiter | None = None,
		max_retries: int = DEFAULT_MAX_RETRIES,
		sleeper: Callable[[float], None] = time.sleep,
	):
		self.limiter = limiter or TelegramRateLimiter()
		self.max_retries = max(0, max_retries)
		self.sleeper = sleeper

	def call(self, action: Callable[[], T]) -> ExternalResult:
		for attempt in range(self.max_retries + 1):
			self.limiter.acquire()
			try:
				return ExternalResult(True, action())
			except Exception as exc:
				retry_after = retry_after_seconds(exc)
				if retry_after is None or attempt >= self.max_retries:
					return ExternalResult(False, error=sanitize_message(exc))
				logger.warning(f"{LOGGER_PREFIX} Telegram rate limit hit, waiting {retry_after}s.")
				self.sleeper(retry_after)
		return ExternalResult(False, error="Telegram call exhausted retries.")


def retry_after_seconds(exc: Exception) -> float | None:
	code = getattr(exc, "error_code", None)
	result_json = getattr(exc, "result_json", None)
	parameters = result_json.get("parameters") if isinstance(result_json, dict) else None
	retry_after = parameters.get("retry_after") if isinstance(parameters, dict) else None

	if retry_after is None and code != 429:
		return None
	if not isinstance(retry_after, (int, float)) or isinstance(retry_after, bool):
		retry_after = 1 if code == 429 else None
	if retry_after is None:
		return None
	return min(MAX_RETRY_AFTER, float(retry_after) + 1)


def is_missing_thread_error(exc_or_text: Any) -> bool:
	return "message thread not found" in str(exc_or_text).lower()


class ChatSyncQueue:
	"""Single worker keeping Telegram deliveries ordered and off the event threads."""

	def __init__(self, name: str = "manual-actions-chat-sync"):
		self.name = name
		self._queue: queue.Queue = queue.Queue()
		self._thread: threading.Thread | None = None
		self._lock = threading.Lock()

	@property
	def running(self) -> bool:
		return bool(self._thread and self._thread.is_alive())

	def start(self) -> None:
		with self._lock:
			if self.running:
				return
			self._thread = threading.Thread(target=self._run, name=self.name, daemon=True)
			self._thread.start()

	def submit(self, job: Callable[[], None]) -> None:
		self.start()
		self._queue.put(job)

	def stop(self, timeout: float = 5.0) -> None:
		with self._lock:
			thread = self._thread
			self._thread = None
		if not thread:
			return
		self._queue.put(_STOP)
		thread.join(timeout)

	def join(self, timeout: float | None = None) -> None:
		self._queue.join()

	def _run(self) -> None:
		while True:
			job = self._queue.get()
			try:
				if job is _STOP:
					return
				job()
			except Exception:
				logger.error(f"{LOGGER_PREFIX} Chat Sync job failed.")
				logger.debug("TRACEBACK", exc_info=True)
			finally:
				self._queue.task_done()
