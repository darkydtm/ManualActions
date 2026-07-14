from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from typing import Any


PROTECTED_PREFIX = "MA-PROTECTED:"
PROTECTED_TEXT_HEADER = (
	"Защищенный paste Manual Actions\n\n"
	"Для чтения нужен пароль, который вернул Telegram-бот.\n\n"
)
PASSWORD_ALPHABET = "abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
DEFAULT_PASSWORD_LENGTH = 24
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 64
KDF_ITERATIONS = 200_000


@dataclass(frozen=True)
class ProtectedText:
	text: str
	password: str
	protected: bool


class ProtectedTextError(Exception):
	pass


def generate_password(length: int = DEFAULT_PASSWORD_LENGTH) -> str:
	length = max(MIN_PASSWORD_LENGTH, min(MAX_PASSWORD_LENGTH, int(length)))
	return "".join(secrets.choice(PASSWORD_ALPHABET) for _ in range(length))


def protect_text(text: str, password: str, salt: bytes | None = None, nonce: bytes | None = None) -> str:
	if not password:
		raise ProtectedTextError("Пароль Pastebin не задан.")

	salt = salt or secrets.token_bytes(16)
	nonce = nonce or secrets.token_bytes(16)
	plain = text.encode("utf-8")
	enc_key, mac_key = derive_keys(password, salt)
	cipher = xor_bytes(plain, key_stream(enc_key, nonce, len(plain)))
	tag = hmac.new(mac_key, tag_payload(salt, nonce, cipher), hashlib.sha256).digest()
	payload = {
		"v": 1,
		"kdf": "pbkdf2_sha256",
		"iter": KDF_ITERATIONS,
		"salt": encode_bytes(salt),
		"nonce": encode_bytes(nonce),
		"data": encode_bytes(cipher),
		"tag": encode_bytes(tag),
	}
	encoded = encode_bytes(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
	return f"{PROTECTED_TEXT_HEADER}{PROTECTED_PREFIX}{encoded}"


def decrypt_protected_text(protected_text: str, password: str) -> str:
	payload_text = protected_text.strip()
	if PROTECTED_PREFIX in payload_text:
		payload_text = payload_text.split(PROTECTED_PREFIX, 1)[1].strip()

	try:
		payload: dict[str, Any] = json.loads(decode_bytes(payload_text).decode("utf-8"))
		salt = decode_bytes(str(payload["salt"]))
		nonce = decode_bytes(str(payload["nonce"]))
		cipher = decode_bytes(str(payload["data"]))
		tag = decode_bytes(str(payload["tag"]))
	except Exception as exc:
		raise ProtectedTextError("Защищенный paste имеет неверный формат.") from exc

	enc_key, mac_key = derive_keys(password, salt)
	expected_tag = hmac.new(mac_key, tag_payload(salt, nonce, cipher), hashlib.sha256).digest()
	if not hmac.compare_digest(tag, expected_tag):
		raise ProtectedTextError("Неверный пароль Pastebin.")

	return xor_bytes(cipher, key_stream(enc_key, nonce, len(cipher))).decode("utf-8")


def derive_keys(password: str, salt: bytes) -> tuple[bytes, bytes]:
	material = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, KDF_ITERATIONS, dklen=64)
	return material[:32], material[32:]


def key_stream(key: bytes, nonce: bytes, length: int) -> bytes:
	blocks = []
	counter = 0
	while len(b"".join(blocks)) < length:
		counter_bytes = counter.to_bytes(8, "big")
		blocks.append(hmac.new(key, nonce + counter_bytes, hashlib.sha256).digest())
		counter += 1
	return b"".join(blocks)[:length]


def xor_bytes(left: bytes, right: bytes) -> bytes:
	return bytes(first ^ second for first, second in zip(left, right))


def tag_payload(salt: bytes, nonce: bytes, cipher: bytes) -> bytes:
	return b"manual-actions-pastebin-v1" + salt + nonce + cipher


def encode_bytes(value: bytes) -> str:
	return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def decode_bytes(value: str) -> bytes:
	padding = "=" * ((4 - len(value) % 4) % 4)
	return base64.urlsafe_b64decode((value + padding).encode("ascii"))
