from __future__ import annotations

from .models import RuleCandidate


def resolve_candidates(candidates: list[RuleCandidate]) -> RuleCandidate | None:
	if not candidates:
		return None
	best = min(candidates, key=lambda item: (-item.matched_keywords, item.final_price, item.rule.id))
	if sum(item.matched_keywords == best.matched_keywords for item in candidates) > 1:
		return RuleCandidate(
			best.rule,
			best.lot,
			best.matched_keywords,
			best.competitor_price,
			best.calculated_price,
			best.final_price,
			"equal_keyword_count",
		)
	return best
