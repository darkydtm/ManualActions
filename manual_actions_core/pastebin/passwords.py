from __future__ import annotations

import secrets


PASSWORD_ALPHABET = "abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
DEFAULT_PASSWORD_LENGTH = 24
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 64


def generate_password(length: int = DEFAULT_PASSWORD_LENGTH) -> str:
	length = max(MIN_PASSWORD_LENGTH, min(MAX_PASSWORD_LENGTH, int(length)))
	return "".join(secrets.choice(PASSWORD_ALPHABET) for _ in range(length))
