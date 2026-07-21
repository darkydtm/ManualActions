from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CodeRequest:
	order_id: str | None


def parse_code_request(text: str) -> CodeRequest | None:
	parts = (text or "").strip().split()
	if not parts or parts[0].lower() != "!code" or len(parts) > 2:
		return None
	if len(parts) == 1:
		return CodeRequest(None)

	order_id = parts[1].strip().lstrip("#")
	return CodeRequest(order_id or None)
