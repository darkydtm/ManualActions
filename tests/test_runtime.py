from __future__ import annotations

import logging
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from core.runtime import KeyedLockRegistry, log_failure, run_effects
from core.runtime.persistence import AtomicWriteError, atomic_write_json


class RuntimeTest(unittest.TestCase):
	def test_same_key_reuses_lock_and_different_keys_do_not(self):
		registry = KeyedLockRegistry()

		self.assertIs(registry.lock_for("gemini:42"), registry.lock_for("gemini:42"))
		self.assertIsNot(registry.lock_for("gemini:42"), registry.lock_for("gpt_accounts:42"))

	def test_effect_failure_does_not_stop_following_effect(self):
		calls = []

		def fail():
			raise RuntimeError("failed")

		results = run_effects((fail, lambda: calls.append("next")))

		self.assertEqual(calls, ["next"])
		self.assertFalse(results[0].succeeded)
		self.assertEqual(results[0].error, "failed")
		self.assertTrue(results[1].succeeded)

	def test_log_failure_redacts_supplied_secrets(self):
		logger = logging.getLogger("test.runtime")

		with self.assertLogs(logger, level="WARNING") as logs:
			log_failure(
				logger,
				"delivery",
				"ORDER-1",
				"reserved",
				"external_service",
				"token=secret-token",
				("secret-token",),
			)

		self.assertIn("token=***", logs.output[0])
		self.assertNotIn("secret-token", logs.output[0])

	def test_atomic_write_preserves_previous_file_on_json_error(self):
		with TemporaryDirectory() as directory:
			path = Path(directory) / "state.json"
			path.write_text('{"state": "old"}\n', encoding="utf-8")

			with self.assertRaises(AtomicWriteError):
				atomic_write_json(path, {"invalid": object()})

			self.assertEqual(path.read_text(encoding="utf-8"), '{"state": "old"}\n')


if __name__ == "__main__":
	unittest.main()
