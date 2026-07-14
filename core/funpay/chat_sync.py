from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..constants import SYNC_PLUGIN_UUID

if TYPE_CHECKING:
	import telebot
	from cardinal import Cardinal


@dataclass(frozen=True)
class TopicContext:
	username: str
	fp_chat_id: int
	thread_id: int


def get_chat_sync_obj():
	try:
		for mod in list(sys.modules.values()):
			if hasattr(mod, "cs_obj") and getattr(mod, "UUID", None) == SYNC_PLUGIN_UUID:
				return mod.cs_obj
	except Exception:
		return None
	return None


def parse_topic_name(name: str) -> tuple[str, int] | tuple[None, None]:
	try:
		if "👤" in name:
			name = name.split("👤", 1)[1]

		parts = name.strip().rsplit(" ", 1)
		if len(parts) != 2:
			return None, None

		username = parts[0].strip()
		chat_id = int(parts[1].replace("(", "").replace(")", "").strip())
		return username, chat_id
	except Exception:
		return None, None


def is_in_sync_chat(message: telebot.types.Message) -> bool:
	cs = get_chat_sync_obj()
	if not cs or not getattr(cs, "ready", False):
		return False

	settings = getattr(cs, "settings", {}) or {}
	return (
		message.chat.id == settings.get("chat_id")
		and bool(getattr(message, "is_topic_message", False))
		and getattr(message, "message_thread_id", None) is not None
	)


def get_topic_context(cardinal: Cardinal, message: telebot.types.Message) -> TopicContext | None:
	cs = get_chat_sync_obj()
	if not cs or not getattr(cs, "ready", False):
		return None
	if not is_in_sync_chat(message):
		return None

	thread_id = message.message_thread_id
	reversed_threads = getattr(cs, "_ChatSync__reversed_threads", {}) or {}
	fp_chat_id_str = reversed_threads.get(thread_id)
	if not fp_chat_id_str:
		return None

	try:
		fp_chat_id = int(fp_chat_id_str)
	except Exception:
		return None

	threads_info = getattr(cs, "threads_info", {}) or {}
	topic_info = threads_info.get(thread_id)
	if topic_info:
		_, topic_name = topic_info
		username, _ = parse_topic_name(topic_name)
		if username:
			return TopicContext(username=username, fp_chat_id=fp_chat_id, thread_id=thread_id)

	try:
		source_cardinal = getattr(cs, "cardinal", cardinal)
		chat = source_cardinal.account.get_chat(fp_chat_id, with_history=False)
		return TopicContext(username=chat.name, fp_chat_id=fp_chat_id, thread_id=thread_id)
	except Exception:
		return None
