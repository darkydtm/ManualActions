from __future__ import annotations


STATUS_IDS = ("0", "1", "2")
STATUS_LABELS = {
	"0": "Недоступен",
	"1": "Доступен",
	"2": "Сильная загруженность",
}


class InvalidStatusCommand(ValueError):
	pass


def parse_funpay_status_command(text: str | None) -> bool:
	if not text:
		return False

	parts = text.strip().split()
	return len(parts) == 1 and parts[0].lower() == "!status"


def parse_telegram_status_command(text: str | None) -> str | None:
	if not text:
		raise InvalidStatusCommand("empty status command")

	parts = text.strip().split(maxsplit=1)
	if not parts:
		raise InvalidStatusCommand("empty status command")

	command = parts[0].split("@", 1)[0].lower()
	if command != "/status":
		raise InvalidStatusCommand("not a status command")

	if len(parts) == 1:
		return None

	status_id = parts[1].strip()
	if status_id not in STATUS_IDS:
		raise InvalidStatusCommand("invalid status id")

	return status_id


def normalize_status_id(value: object) -> str:
	value = str(value)
	return value if value in STATUS_IDS else "1"


def toggle_status(current: object) -> str:
	return "1" if normalize_status_id(current) == "0" else "0"


def status_label(status_id: object) -> str:
	return STATUS_LABELS[normalize_status_id(status_id)]


def response_text(settings: dict) -> str:
	status_id = normalize_status_id(settings.get("status"))
	texts = settings.get("status_response_texts")
	text = ""
	if isinstance(texts, dict):
		text = str(texts.get(status_id, "")).strip()
	return text or f"Текущий статус: {STATUS_LABELS[status_id]}"


def auto_message_text(settings: dict) -> str:
	status_id = normalize_status_id(settings.get("status"))
	messages = settings.get("status_auto_messages")
	if not isinstance(messages, dict):
		return ""

	config = messages.get(status_id)
	if not isinstance(config, dict) or not config.get("enabled"):
		return ""

	return str(config.get("text", "")).strip()
