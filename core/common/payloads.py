from __future__ import annotations

from typing import Any


class CallbackPayloadCache:
	def __init__(self, limit: int = 300):
		self.limit = max(1, limit)
		self.counter = 0
		self.payloads: dict[str, Any] = {}

	def put(self, payload: Any) -> str:
		self.counter += 1
		token = format(self.counter, "x")
		self.payloads[token] = payload
		while len(self.payloads) > self.limit:
			self.payloads.pop(next(iter(self.payloads)))
		return token

	def get(self, token: str) -> Any | None:
		return self.payloads.get(token)

	def pop(self, token: str) -> Any | None:
		return self.payloads.pop(token, None)


def parse_blacklist_payload(payload: str) -> tuple[str, str, int | str | None]:
	parts = payload.split("|", 2)
	action = parts[0] if parts else ""
	username = parts[1] if len(parts) > 1 else ""
	chat_id = parts[2] if len(parts) > 2 and parts[2] else None
	if chat_id and str(chat_id).isdigit():
		chat_id = int(chat_id)
	return action, username, chat_id


def parse_two_part_payload(payload: str) -> tuple[str, str]:
	first, _, second = payload.partition("|")
	return first, second or "all"


def parse_three_part_payload(payload: str) -> tuple[str, str, str]:
	first, _, tail = payload.partition("|")
	second, _, third = tail.partition("|")
	return first, second or "all", third
