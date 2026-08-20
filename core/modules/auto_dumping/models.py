from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Lot:
	id: str
	title: str
	price: float
	subcategory: str
	username: str
	active: bool = True
	available: bool = True
	raw: Any = None


@dataclass(frozen=True)
class DumpingRule:
	id: str
	enabled: bool
	subcategory: str
	keywords: tuple[str, ...]
	keyword_mode: str
	competitor_min_price: float
	price_mode: str
	dumping_value: float
	own_min_price: float
	sellers_blacklist: tuple[str, ...] = ()
	keywords_blacklist: tuple[str, ...] = ()

	@classmethod
	def from_dict(cls, data: dict[str, Any]) -> "DumpingRule":
		return cls(
			id=str(data["id"]),
			enabled=bool(data["enabled"]),
			subcategory=str(data["subcategory"]),
			keywords=tuple(data["keywords"]),
			keyword_mode=str(data["keyword_mode"]),
			competitor_min_price=float(data["competitor_min_price"]),
			price_mode=str(data["price_mode"]),
			dumping_value=float(data["dumping_value"]),
			own_min_price=float(data["own_min_price"]),
			sellers_blacklist=tuple(data.get("sellers_blacklist", ())),
			keywords_blacklist=tuple(data.get("keywords_blacklist", ())),
		)


@dataclass(frozen=True)
class RuleCandidate:
	rule: DumpingRule
	lot: Lot
	matched_keywords: int
	competitor_price: float
	calculated_price: float
	final_price: float
	reason: str = ""


@dataclass(frozen=True)
class PriceDecision:
	own_lot: Lot
	candidate: RuleCandidate
	conflict: bool = False
	reason: str = ""


@dataclass(frozen=True)
class AutoDumpingConfig:
	enabled: bool
	interval_minutes: int
	global_sellers_blacklist: tuple[str, ...]
	global_keywords_blacklist: tuple[str, ...]
	rules: tuple[DumpingRule, ...]
