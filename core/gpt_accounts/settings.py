from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Iterable


GPT_ACCOUNTS_SHORTAGE_MODES = ("partial", "all_or_nothing")
DEFAULT_GPT_ACCOUNTS_MESSAGE_TEMPLATE = "Спасибо за покупку!\n\n{accounts}"
DEFAULT_GPT_ACCOUNTS_DELIVERY_SETTINGS = {
	"enabled": False,
	"shortage_mode": "partial",
	"quantity": 1,
	"delay_seconds": 0,
	"message_template": DEFAULT_GPT_ACCOUNTS_MESSAGE_TEMPLATE,
}


@dataclass(frozen=True)
class Account:
	email: str
	password: str
	two_factor_secret: str = ""


@dataclass(frozen=True)
class AccountBatchResult:
	accounts: tuple[Account, ...]
	invalid_lines: tuple[int, ...]
	duplicate_count: int


def normalize_gpt_accounts_delivery_settings(data: Any) -> dict[str, Any]:
	settings = deepcopy(DEFAULT_GPT_ACCOUNTS_DELIVERY_SETTINGS)
	if not isinstance(data, dict):
		return settings

	for key in ("enabled",):
		if isinstance(data.get(key), bool):
			settings[key] = data[key]
	shortage_mode = data.get("shortage_mode")
	if shortage_mode in GPT_ACCOUNTS_SHORTAGE_MODES:
		settings["shortage_mode"] = shortage_mode
	for key in ("quantity", "delay_seconds"):
		value = data.get(key)
		if isinstance(value, int) and not isinstance(value, bool) and value >= (1 if key == "quantity" else 0):
			settings[key] = value
	message_template = data.get("message_template")
	if isinstance(message_template, str) and "{accounts}" in message_template:
		settings["message_template"] = message_template
	return settings


def parse_account_batch(text: str, existing_emails: set[str]) -> AccountBatchResult:
	accounts = []
	invalid_lines = []
	duplicate_count = 0
	seen = {email.casefold() for email in existing_emails}
	for number, line in enumerate(text.splitlines(), start=1):
		value = line.strip()
		if not value:
			continue
		parts = [part.strip() for part in value.split("|")]
		if len(parts) not in (2, 3) or not parts[0] or not parts[1]:
			invalid_lines.append(number)
			continue
		key = parts[0].casefold()
		if key in seen:
			duplicate_count += 1
			continue
		seen.add(key)
		accounts.append(Account(parts[0], parts[1], parts[2] if len(parts) == 3 else ""))
	return AccountBatchResult(tuple(accounts), tuple(invalid_lines), duplicate_count)


def format_accounts(accounts: Iterable[Account]) -> str:
	items = []
	for account in accounts:
		text = f"Email: {account.email}\nPassword: {account.password}"
		if account.two_factor_secret:
			text += f"\n2FA secret: {account.two_factor_secret}"
		items.append(text)
	return "\n\n".join(items)
