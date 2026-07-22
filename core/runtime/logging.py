from __future__ import annotations

import logging
from collections.abc import Iterable


def sanitize_message(value: object, secrets: Iterable[object] = ()) -> str:
	message = str(value)
	for secret in secrets:
		text = str(secret)
		if text:
			message = message.replace(text, "***")
	return message


def log_failure(
	logger: logging.Logger,
	domain: str,
	operation_id: str,
	phase: str,
	category: str,
	error: object,
	secrets: Iterable[object] = (),
) -> None:
	logger.warning(
		"Operation failed: domain=%s operation_id=%s phase=%s category=%s error=%s",
		domain,
		operation_id,
		phase,
		category,
		sanitize_message(error, secrets),
	)
