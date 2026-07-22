from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ProviderResult:
	provider: str
	status: str
	order_id: str = ""
	error: str = ""


class DeliveryProvider(Protocol):
	name: str

	def handle_new_order(self, event: object) -> object: ...
