from __future__ import annotations

from collections.abc import Callable
import logging
import time
from typing import Any

from .conflicts import resolve_candidates
from .matching import is_blacklisted, match_keywords
from .models import AutoDumpingConfig, DumpingRule, Lot, PriceDecision, RuleCandidate
from .pricing import calculate_price, final_price


logger = logging.getLogger("FPC.manual_actions")


class AutoDumpingService:
	def __init__(self, settings_provider: Callable[[], dict[str, Any]], gateway: Any, storage: Any, notifier: Any = None):
		self.settings_provider = settings_provider
		self.gateway = gateway
		self.storage = storage
		self.notifier = notifier

	def load(self) -> None:
		self.storage.load()

	def shutdown(self) -> None:
		return None

	def run_cycle(self) -> dict[str, Any]:
		settings = self.settings_provider()
		if not settings.get("enabled"):
			return {"status": "disabled", "updated": 0, "skipped": 0, "errors": 0}
		try:
			catalog = self.gateway.catalog_lots()
			own_lots = self.gateway.own_lots()
			if catalog is None or own_lots is None:
				raise RuntimeError("Cardinal returned no catalog.")
		except Exception:
			logger.exception("Auto-dumping catalog read failed.")
			result = {"status": "catalog_error", "updated": 0, "skipped": 0, "errors": 1}
			self.storage.record_cycle(time.time(), result)
			return result

		config = AutoDumpingConfig(
			settings.get("enabled") is True,
			int(settings.get("interval_minutes", 5)),
			tuple(settings.get("global_sellers_blacklist", [])),
			tuple(settings.get("global_keywords_blacklist", [])),
			tuple(DumpingRule.from_dict(rule) for rule in settings.get("rules", [])),
		)
		result = {"status": "ok", "updated": 0, "skipped": 0, "errors": 0, "conflicts": 0}
		for own_lot in own_lots:
			try:
				decision = self.decide(own_lot, catalog, config)
				if not decision:
					continue
				if decision.conflict:
					result["conflicts"] += 1
					self.notify_conflict(own_lot, decision, applied=False)
				if not self.gateway.is_owned(own_lot):
					result["skipped"] += 1
					continue
				if decision.candidate.final_price == own_lot.price:
					continue
				self.gateway.update_price(own_lot, decision.candidate.final_price)
				result["updated"] += 1
				self.notify_conflict(own_lot, decision, applied=True)
			except Exception:
				result["errors"] += 1
				logger.exception("Auto-dumping lot processing failed for %s.", own_lot.id)
		self.storage.record_cycle(time.time(), result)
		return result

	def decide(self, own_lot: Lot, catalog: list[Lot], config: AutoDumpingConfig) -> PriceDecision | None:
		candidates = []
		for rule in config.rules:
			if not rule.enabled or rule.subcategory.casefold() != own_lot.subcategory.casefold():
				continue
			matched_competitors = []
			for competitor in catalog:
				if competitor.id == own_lot.id or not competitor.active or not competitor.available:
					continue
				if competitor.subcategory.casefold() != rule.subcategory.casefold():
					continue
				if is_blacklisted(
					competitor.username,
					competitor.title,
					config.global_sellers_blacklist + rule.sellers_blacklist,
					config.global_keywords_blacklist + rule.keywords_blacklist,
				):
					continue
				matched = match_keywords(competitor.title, rule.keywords, rule.keyword_mode)
				if not matched or competitor.price < rule.competitor_min_price:
					continue
				matched_competitors.append((competitor, matched))
			if matched_competitors:
				competitor, matched = min(matched_competitors, key=lambda item: item[0].price)
				candidates.append(RuleCandidate(
					rule, competitor, matched, competitor.price,
					calculate_price(competitor.price, rule), final_price(competitor.price, rule),
				))
		if not candidates:
			return None
		selected = resolve_candidates(candidates)
		return PriceDecision(
			own_lot,
			selected,
			conflict=len(candidates) > 1,
			reason=selected.reason,
		)

	def notify_conflict(self, own_lot: Lot, decision: PriceDecision, applied: bool) -> None:
		if not decision.conflict or not self.notifier:
			return
		fingerprint = ":".join((own_lot.id, ",".join(candidate.rule.id for candidate in [decision.candidate]), decision.candidate.rule.id))
		if self.storage.get_conflict_fingerprint(own_lot.id) == fingerprint and not applied:
			return
		self.storage.set_conflict_fingerprint(own_lot.id, fingerprint)
		if applied:
			self.notifier.notify_applied(decision)
		else:
			self.notifier.notify_detected(decision)
