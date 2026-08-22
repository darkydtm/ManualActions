from __future__ import annotations

from typing import Any


TOKEN_SPACE = 1 << 32


class CallbackPayloadCache:
	def __init__(self, limit: int = 300):
		self.limit = min(max(1, limit), TOKEN_SPACE)
		self.counter = 0
		self.payloads: dict[str, Any] = {}

	def put(self, payload: Any) -> str:
		if len(self.payloads) >= TOKEN_SPACE:
			raise RuntimeError("callback payload cache is full")
		while True:
			self.counter = (self.counter + 1) % TOKEN_SPACE
			token = format(self.counter, "x")
			if token not in self.payloads:
				break
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
