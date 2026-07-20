from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any


GEMINI_LINK_PREFIXES = (
	"https://one.google.com/activate-plan/subscription/new/",
	"https://serviceactivation.google.com/subscription/new/",
)
GEMINI_SHORTAGE_MODES = ("partial", "all_or_nothing")

DEFAULT_GEMINI_MESSAGE_TEMPLATE = "Спасибо за покупку!\nВаша ссылка: {link}"

DEFAULT_GEMINI_DELIVERY_SETTINGS = {
	"enabled": False,
	"shortage_mode": "partial",
	"message_template": DEFAULT_GEMINI_MESSAGE_TEMPLATE,
}


@dataclass(frozen=True)
class LinkBatchResult:
	links: tuple[str, ...]
	invalid_lines: tuple[int, ...]
	duplicate_count: int


def normalize_gemini_delivery_settings(data: Any) -> dict[str, Any]:
	settings = deepcopy(DEFAULT_GEMINI_DELIVERY_SETTINGS)
	if not isinstance(data, dict):
		return settings

	enabled = data.get("enabled")
	if isinstance(enabled, bool):
		settings["enabled"] = enabled

	shortage_mode = data.get("shortage_mode")
	if shortage_mode in GEMINI_SHORTAGE_MODES:
		settings["shortage_mode"] = shortage_mode

	message_template = data.get("message_template")
	if isinstance(message_template, str) and "{link}" in message_template:
		settings["message_template"] = message_template

	return settings


def validate_gemini_link(value: str) -> bool:
	return any(
		value.startswith(prefix) and len(value) > len(prefix)
		for prefix in GEMINI_LINK_PREFIXES
	)


def parse_gemini_link_batch(text: str, existing: set[str]) -> LinkBatchResult:
	links = []
	invalid_lines = []
	duplicate_count = 0
	seen = set(existing)

	for line_number, line in enumerate(text.splitlines(), start=1):
		value = line.strip()
		if not value:
			continue
		if not validate_gemini_link(value):
			invalid_lines.append(line_number)
			continue
		if value in seen:
			duplicate_count += 1
			continue
		seen.add(value)
		links.append(value)

	return LinkBatchResult(
		links=tuple(links),
		invalid_lines=tuple(invalid_lines),
		duplicate_count=duplicate_count,
	)
