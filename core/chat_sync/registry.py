from __future__ import annotations

from typing import Any


_active_service: Any = None


def set_active_service(service: Any) -> None:
	global _active_service
	_active_service = service


def get_active_service() -> Any:
	return _active_service
