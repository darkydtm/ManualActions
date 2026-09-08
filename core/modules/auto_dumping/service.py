from __future__ import annotations

from collections.abc import Callable
import logging
import time
from typing import Any

from .conflicts import resolve_candidates
from .matching import is_blacklisted, match_keywords, matches_subcategory
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
		try:
			config = AutoDumpingConfig(
				settings.get("enabled") is True,
				int(settings.get("interval_minutes", 5)),
				tuple(DumpingRule.from_dict(rule) for rule in settings.get("rules", [])),
			)
		except Exception:
			logger.exception("Auto-dumping settings are invalid.")
			result = {"status": "config_error", "updated": 0, "skipped": 0, "errors": 1}
			self.storage.record_cycle(time.time(), result)
			return result
		own_ids = {lot.id for lot in own_lots}
		result = {"status": "ok", "updated": 0, "skipped": 0, "errors": 0, "conflicts": 0}
		for own_lot in own_lots:
			try:
				if not self.gateway.is_owned(own_lot):
					result["skipped"] += 1
					continue
				decision = self.decide(own_lot, catalog, config, own_ids)
				if not decision:
					continue
				applied = False
				target = decision.candidate.final_price
				if target <= 0:
					result["skipped"] += 1
				elif abs(target - own_lot.price) >= 0.005:
					self.gateway.update_price(own_lot, target)
					result["updated"] += 1
					applied = True
				if decision.conflict:
					result["conflicts"] += 1
					self.notify_conflict(own_lot, decision, applied=applied)
			except Exception:
				result["errors"] += 1
				logger.exception("Auto-dumping lot processing failed for %s.", own_lot.id)
		self.storage.record_cycle(time.time(), result)
		return result

	def decide(
		self,
		own_lot: Lot,
		catalog: list[Lot],
		config: AutoDumpingConfig,
		own_ids: frozenset[str] | set[str] = frozenset(),
	) -> PriceDecision | None:
		candidates = []
		for rule in config.rules:
			if not rule.enabled or not matches_subcategory(own_lot, rule.subcategory):
				continue
			matched_competitors = []
			for competitor in catalog:
				if competitor.id == own_lot.id or competitor.id in own_ids:
					continue
				if not competitor.active or not competitor.available:
					continue
				if not matches_subcategory(competitor, rule.subcategory):
					continue
				if is_blacklisted(
					competitor.username,
					competitor.title,
					rule.sellers_blacklist,
					rule.keywords_blacklist,
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
		fingerprint = "|".join((
			own_lot.id,
			decision.candidate.rule.id,
			f"{decision.candidate.final_price:.2f}",
			decision.candidate.lot.id,
		))
		if self.storage.get_conflict_fingerprint(own_lot.id) == fingerprint and not applied:
			return
		self.storage.set_conflict_fingerprint(own_lot.id, fingerprint)
		if applied:
			self.notifier.notify_applied(decision)
		else:
			self.notifier.notify_detected(decision)
