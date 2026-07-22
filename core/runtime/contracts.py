from __future__ import annotations

from dataclasses import dataclass


PHASE_RECEIVED = "received"
PHASE_PREPARED = "prepared"
PHASE_RESERVED = "reserved"
PHASE_EXTERNAL_WORK = "external_work"
PHASE_READY_TO_SEND = "ready_to_send"
PHASE_COMPLETED = "completed"

FAILURE_VALIDATION = "validation"
FAILURE_STORAGE = "storage"
FAILURE_RESERVATION = "reservation"
FAILURE_EXTERNAL_SERVICE = "external_service"
FAILURE_BUYER_SEND = "buyer_send"
FAILURE_NOTIFICATION = "notification"
FAILURE_UNEXPECTED = "unexpected"


@dataclass(frozen=True)
class Failure:
	category: str
	message: str


@dataclass(frozen=True)
class OperationOutcome:
	status: str
	operation_id: str = ""
	phase: str = ""
	failure: Failure | None = None


@dataclass(frozen=True)
class EffectResult:
	succeeded: bool
	error: str = ""
