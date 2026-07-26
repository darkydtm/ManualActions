from __future__ import annotations

from dataclasses import asdict, dataclass
import logging
from typing import Any

from ..config.constants import CHAT_SYNC_TOPICS_FILE, LOGGER_NAME, LOGGER_PREFIX
from ..storage.storage import PluginStorage


logger = logging.getLogger(LOGGER_NAME)


@dataclass
class TopicRecord:
	thread_id: int
	username: str = ""
	title: str = ""
	icon: str = ""
	last_message_id: int = 0


class ChatSyncStorage:
	def __init__(self, storage: PluginStorage | None = None, path: str = CHAT_SYNC_TOPICS_FILE):
		self.storage = storage or PluginStorage()
		self.path = path

	def load(self) -> dict[str, TopicRecord]:
		return normalize_topics(self.storage.load_dict(self.path).get("topics"))

	def save(self, topics: dict[str, TopicRecord]) -> None:
		payload = {"topics": {key: asdict(record) for key, record in topics.items()}}
		try:
			self.storage.save_dict(self.path, payload)
		except Exception:
			logger.warning(f"{LOGGER_PREFIX} Failed to save Chat Sync topics.")
			logger.debug("TRACEBACK", exc_info=True)


def normalize_topics(data: Any) -> dict[str, TopicRecord]:
	if not isinstance(data, dict):
		return {}

	topics: dict[str, TopicRecord] = {}
	used_threads: set[int] = set()
	for key, value in data.items():
		record = normalize_topic(value)
		if not record:
			continue

		chat_key = str(key).strip()
		if not chat_key.lstrip("-").isdigit():
			continue

		# Two FunPay chats must never share one Telegram topic - drop the duplicate.
		if record.thread_id in used_threads:
			logger.warning(f"{LOGGER_PREFIX} Dropping duplicate Chat Sync topic {record.thread_id} for chat {chat_key}.")
			continue

		used_threads.add(record.thread_id)
		topics[chat_key] = record
	return topics


def normalize_topic(value: Any) -> TopicRecord | None:
	if isinstance(value, int) and not isinstance(value, bool):
		return TopicRecord(thread_id=value)
	if not isinstance(value, dict):
		return None

	thread_id = value.get("thread_id")
	if isinstance(thread_id, bool) or not isinstance(thread_id, int):
		return None

	last_message_id = value.get("last_message_id")
	return TopicRecord(
		thread_id=thread_id,
		username=str(value.get("username") or ""),
		title=str(value.get("title") or ""),
		icon=str(value.get("icon") or ""),
		last_message_id=last_message_id if isinstance(last_message_id, int) and not isinstance(last_message_id, bool) else 0,
	)
