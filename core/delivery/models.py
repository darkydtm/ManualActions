from __future__ import annotations

from dataclasses import dataclass


OUTCOME_IGNORED = "ignored"
OUTCOME_WAITING_STOCK = "waiting_stock"
OUTCOME_COMPLETED = "completed"
OUTCOME_SEND_FAILED = "send_failed"


@dataclass(frozen=True)
class DeliveryOutcome:
	status: str
	order_id: str = ""
	error: str = ""


@dataclass(frozen=True)
class OrderRequest:
	order_id: str
	requested_amount: int
	buyer_username: str = ""
	fp_chat_id: int | str | None = None
