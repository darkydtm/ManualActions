from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import re
import struct
import time


def normalize_totp_secret(secret: str) -> str:
	return re.sub(r"\s+", "", secret or "").upper()


def decode_totp_secret(secret: str) -> bytes:
	normalized = normalize_totp_secret(secret)
	if not normalized:
		raise ValueError("empty TOTP secret")

	padding = "=" * ((8 - len(normalized) % 8) % 8)
	try:
		return base64.b32decode(normalized + padding, casefold=True)
	except (binascii.Error, ValueError) as exc:
		raise ValueError("invalid TOTP secret") from exc


def generate_totp(secret: str, timestamp: int | None = None) -> str:
	if timestamp is None:
		timestamp = int(time.time())

	key = decode_totp_secret(secret)
	counter = timestamp // 30
	digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
	offset = digest[-1] & 0x0F
	code = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
	return f"{code % 1000000:06d}"
