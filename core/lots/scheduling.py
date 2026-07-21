from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


DEFAULT_LOT_SCHEDULING_SETTINGS = {
	"enabled": False,
	"timezone": "Europe/Moscow",
	"rules": [],
}


def normalize_lot_scheduling_settings(data: Any) -> dict[str, Any]:
	settings = deepcopy(DEFAULT_LOT_SCHEDULING_SETTINGS)
	if not isinstance(data, dict):
		return settings
	if isinstance(data.get("enabled"), bool):
		settings["enabled"] = data["enabled"]
	if valid_timezone(data.get("timezone")):
		settings["timezone"] = data["timezone"]
	if isinstance(data.get("rules"), list):
		settings["rules"] = [rule for item in data["rules"] if (rule := normalize_rule(item))]
	return settings


def normalize_rule(data: Any) -> dict[str, Any] | None:
	if not isinstance(data, dict):
		return None
	target = normalize_target(data.get("target"))
	schedule = normalize_schedule(data.get("schedule"))
	if not target or not schedule:
		return None
	return {
		"id": str(data.get("id") or uuid4().hex),
		"enabled": bool(data.get("enabled", True)),
		"target": target,
		"schedule": schedule,
		"active_lot_ids": normalize_ids(data.get("active_lot_ids")),
		"last_action": str(data.get("last_action") or ""),
	}


def normalize_target(data: Any) -> dict[str, Any] | None:
	if not isinstance(data, dict):
		return None
	kind = data.get("kind")
	if kind == "all":
		return {"kind": "all"}
	if kind == "category" and isinstance(data.get("value"), str) and data["value"].strip():
		return {"kind": "category", "value": data["value"].strip()}
	if kind == "lots":
		ids = normalize_ids(data.get("ids"))
		return {"kind": "lots", "ids": ids} if ids else None
	return None


def normalize_schedule(data: Any) -> dict[str, Any] | None:
	if not isinstance(data, dict):
		return None
	if data.get("kind") == "duration" and isinstance(data.get("minutes"), int) and data["minutes"] > 0:
		return {"kind": "duration", "minutes": data["minutes"], "started_at": str(data.get("started_at") or "")}
	if data.get("kind") == "daily" and valid_clock(data.get("start")) and valid_clock(data.get("end")):
		return {"kind": "daily", "start": data["start"], "end": data["end"]}
	return None


def due_action(rule: dict[str, Any], now: datetime) -> str | None:
	if not rule.get("enabled"):
		return None
	schedule = rule["schedule"]
	if schedule["kind"] == "duration":
		started = parse_datetime(schedule.get("started_at"))
		if not started:
			return "deactivate"
		return "restore" if now >= started + timedelta(minutes=schedule["minutes"]) else None
	if now.strftime("%H:%M") == schedule["start"]:
		return "deactivate"
	if now.strftime("%H:%M") == schedule["end"]:
		return "restore"
	return None


def valid_timezone(value: Any) -> bool:
	if not isinstance(value, str) or not value:
		return False
	try:
		ZoneInfo(value)
		return True
	except ZoneInfoNotFoundError:
		return False


def valid_clock(value: Any) -> bool:
	if not isinstance(value, str):
		return False
	try:
		datetime.strptime(value, "%H:%M")
		return True
	except ValueError:
		return False


def normalize_ids(value: Any) -> list[str]:
	if not isinstance(value, list):
		return []
	return list(dict.fromkeys(str(item).strip() for item in value if str(item).strip()))


def parse_datetime(value: Any) -> datetime | None:
	if not isinstance(value, str) or not value:
		return None
	try:
		return datetime.fromisoformat(value)
	except ValueError:
		return None
