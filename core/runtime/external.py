from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import TypeVar

from .logging import sanitize_message


T = TypeVar("T")


@dataclass(frozen=True)
class ExternalResult:
	succeeded: bool
	value: object | None = None
	error: str = ""


def call_external(action: Callable[[], T], secrets: Iterable[object] = ()) -> ExternalResult:
	try:
		return ExternalResult(True, action())
	except Exception as exc:
		return ExternalResult(False, error=sanitize_message(exc, secrets))
