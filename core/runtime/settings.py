from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from typing import Any


def update_settings(
	settings: dict[str, Any],
	save: Callable[[], None],
	mutation: Callable[[dict[str, Any]], None],
) -> None:
	previous = deepcopy(settings)
	mutation(settings)
	try:
		save()
	except Exception:
		settings.clear()
		settings.update(previous)
		raise
