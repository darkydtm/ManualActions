from __future__ import annotations

import threading
import unittest

from core.chat_sync.dispatcher import (
	ChatSyncQueue,
	TelegramRateLimiter,
	TelegramSender,
	is_missing_thread_error,
	retry_after_seconds,
)


class FakeClock:
	def __init__(self):
		self.now = 0.0
		self.slept = []

	def time(self):
		return self.now

	def sleep(self, seconds):
		self.slept.append(seconds)
		self.now += seconds


class ApiError(Exception):
	def __init__(self, message="Too Many Requests", error_code=429, retry_after=None):
		super().__init__(message)
		self.error_code = error_code
		self.result_json = {"parameters": {"retry_after": retry_after}} if retry_after is not None else {}


class RateLimiterTest(unittest.TestCase):
	def test_allows_a_full_burst_without_waiting(self):
		clock = FakeClock()
		limiter = TelegramRateLimiter(messages_per_minute=20, min_interval=0, clock=clock.time, sleeper=clock.sleep)

		for _ in range(20):
			limiter.acquire()

		self.assertEqual(clock.slept, [])

	def test_throttles_once_the_bucket_is_empty(self):
		clock = FakeClock()
		limiter = TelegramRateLimiter(messages_per_minute=20, min_interval=0, clock=clock.time, sleeper=clock.sleep)
		for _ in range(20):
			limiter.acquire()

		limiter.acquire()

		self.assertEqual(len(clock.slept), 1)
		self.assertAlmostEqual(clock.slept[0], 3.0, places=3)

	def test_enforces_minimum_gap_between_calls(self):
		clock = FakeClock()
		limiter = TelegramRateLimiter(messages_per_minute=600, min_interval=0.5, clock=clock.time, sleeper=clock.sleep)

		limiter.acquire()
		limiter.acquire()

		self.assertAlmostEqual(clock.slept[0], 0.5, places=3)

	def test_configure_updates_the_rate(self):
		clock = FakeClock()
		limiter = TelegramRateLimiter(messages_per_minute=20, min_interval=0, clock=clock.time, sleeper=clock.sleep)
		limiter.configure(60)
		for _ in range(20):
			limiter.acquire()

		clock.now += 1
		limiter.acquire()

		self.assertEqual(clock.slept, [])


class RetryAfterTest(unittest.TestCase):
	def test_reads_retry_after_from_telegram_payload(self):
		self.assertEqual(retry_after_seconds(ApiError(retry_after=5)), 6.0)

	def test_defaults_to_one_second_for_429_without_payload(self):
		self.assertEqual(retry_after_seconds(ApiError()), 2.0)

	def test_returns_none_for_other_errors(self):
		self.assertIsNone(retry_after_seconds(ApiError(error_code=400)))
		self.assertIsNone(retry_after_seconds(RuntimeError("offline")))

	def test_caps_absurd_retry_after(self):
		self.assertEqual(retry_after_seconds(ApiError(retry_after=100000)), 120)

	def test_detects_missing_thread_errors(self):
		self.assertTrue(is_missing_thread_error("Bad Request: message thread not found"))
		self.assertFalse(is_missing_thread_error("Bad Request: chat not found"))


class SenderTest(unittest.TestCase):
	def setUp(self):
		self.clock = FakeClock()
		self.limiter = TelegramRateLimiter(
			messages_per_minute=100000,
			min_interval=0,
			clock=self.clock.time,
			sleeper=self.clock.sleep,
		)

	def test_returns_the_value_on_success(self):
		sender = TelegramSender(self.limiter, sleeper=self.clock.sleep)

		result = sender.call(lambda: "ok")

		self.assertTrue(result.succeeded)
		self.assertEqual(result.value, "ok")

	def test_retries_after_rate_limit_and_succeeds(self):
		attempts = []
		sender = TelegramSender(self.limiter, sleeper=self.clock.sleep)

		def action():
			attempts.append(1)
			if len(attempts) < 3:
				raise ApiError(retry_after=2)
			return "delivered"

		result = sender.call(action)

		self.assertTrue(result.succeeded)
		self.assertEqual(result.value, "delivered")
		self.assertEqual(self.clock.slept, [3.0, 3.0])

	def test_gives_up_after_max_retries(self):
		sender = TelegramSender(self.limiter, max_retries=1, sleeper=self.clock.sleep)

		result = sender.call(lambda: (_ for _ in ()).throw(ApiError(retry_after=1)))

		self.assertFalse(result.succeeded)

	def test_does_not_retry_other_errors(self):
		attempts = []
		sender = TelegramSender(self.limiter, sleeper=self.clock.sleep)

		def action():
			attempts.append(1)
			raise RuntimeError("offline")

		result = sender.call(action)

		self.assertFalse(result.succeeded)
		self.assertEqual(len(attempts), 1)


class QueueTest(unittest.TestCase):
	def test_runs_jobs_in_order(self):
		queue = ChatSyncQueue()
		done = threading.Event()
		order = []

		for index in range(5):
			queue.submit(lambda index=index: order.append(index))
		queue.submit(done.set)
		done.wait(5)
		queue.stop()

		self.assertEqual(order, [0, 1, 2, 3, 4])

	def test_failing_job_does_not_stop_the_worker(self):
		queue = ChatSyncQueue()
		done = threading.Event()

		queue.submit(lambda: (_ for _ in ()).throw(RuntimeError("boom")))
		queue.submit(done.set)
		self.assertTrue(done.wait(5))
		queue.stop()

	def test_stop_is_safe_without_a_worker(self):
		ChatSyncQueue().stop()


if __name__ == "__main__":
	unittest.main()
