from __future__ import annotations

from dataclasses import dataclass
import logging
import unittest

from core.delivery import DeliveryOrchestrator


@dataclass(frozen=True)
class FakeOutcome:
	status: str
	order_id: str = ""
	error: str = ""


class FakeProvider:
	def __init__(self, name: str, outcome: FakeOutcome | None = None, error: Exception | None = None):
		self.name = name
		self.outcome = outcome or FakeOutcome("ignored")
		self.error = error
		self.events = []

	def handle_new_order(self, event: object) -> FakeOutcome:
		self.events.append(event)
		if self.error:
			raise self.error
		return self.outcome


class DeliveryOrchestratorTest(unittest.TestCase):
	def test_provider_exception_isolated_and_next_provider_runs(self):
		event = object()
		broken = FakeProvider("broken", error=RuntimeError("boom"))
		working = FakeProvider("working", FakeOutcome("completed", "42"))

		results = DeliveryOrchestrator((broken, working), logging.getLogger("test.delivery")).handle_new_order(event)

		self.assertEqual([result.provider for result in results], ["broken", "working"])
		self.assertEqual(results[0].status, "ignored")
		self.assertEqual(working.events, [event])

	def test_result_preserves_provider_outcome(self):
		provider = FakeProvider("gemini", FakeOutcome("completed", "ORDER-1"))

		results = DeliveryOrchestrator((provider,), logging.getLogger("test.delivery")).handle_new_order(object())

		self.assertEqual(results[0].status, "completed")
		self.assertEqual(results[0].order_id, "ORDER-1")


if __name__ == "__main__":
	unittest.main()
