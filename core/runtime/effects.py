from __future__ import annotations

from collections.abc import Callable, Iterable

from .contracts import EffectResult


def run_effects(effects: Iterable[Callable[[], object]]) -> tuple[EffectResult, ...]:
	results = []
	for effect in effects:
		try:
			effect()
		except Exception as exc:
			results.append(EffectResult(False, str(exc)))
		else:
			results.append(EffectResult(True))
	return tuple(results)
