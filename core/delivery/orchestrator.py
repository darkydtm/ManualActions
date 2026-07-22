from __future__ import annotations

import logging
from collections.abc import Iterable

from ..runtime import log_failure
from .contracts import DeliveryProvider, ProviderResult


class DeliveryOrchestrator:
	def __init__(self, providers: Iterable[DeliveryProvider], logger: logging.Logger):
		self.providers = tuple(providers)
		self.logger = logger

	def handle_new_order(self, event: object) -> tuple[ProviderResult, ...]:
		results = []
		for provider in self.providers:
			try:
				outcome = provider.handle_new_order(event)
			except Exception as exc:
				log_failure(
					self.logger,
					provider.name,
					"",
					"received",
					"unexpected",
					exc,
				)
				results.append(ProviderResult(provider.name, "ignored", error="Provider failed."))
				continue
			results.append(
				ProviderResult(
					provider.name,
					str(getattr(outcome, "status", "ignored")),
					str(getattr(outcome, "order_id", "")),
					str(getattr(outcome, "error", "")),
				)
			)
		return tuple(results)
