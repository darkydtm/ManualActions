from __future__ import annotations


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
