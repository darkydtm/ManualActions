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


def update_host_settings(host: Any, mutation: Callable[[dict[str, Any]], None]) -> None:
	update_settings(host.settings, host.save_settings, mutation)
