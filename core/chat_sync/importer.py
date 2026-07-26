from __future__ import annotations

from dataclasses import dataclass, field
import os
import sys
from typing import Any

from ..config.constants import SYNC_PLUGIN_UUID
from ..storage.storage import PluginStorage
from .settings import normalize_chat_id
from .storage import TopicRecord
from .topics import format_topic_name


SYNC_PLUGIN_FOLDER = os.path.join("storage", "plugins", SYNC_PLUGIN_UUID)
SYNC_PLUGIN_SETTINGS_FILE = os.path.join(SYNC_PLUGIN_FOLDER, "settings.json")
SYNC_PLUGIN_THREADS_FILE = os.path.join(SYNC_PLUGIN_FOLDER, "threads.json")

SETTINGS_MAP = {
	"watermark_is_hidden": "hide_watermark",
	"ad": "show_ads",
	"image_name": "show_image_name",
	"chat_url": "chat_url",
	"mono": "mono",
	"buyer_viewing": "buyer_viewing",
	"edit_topic": "edit_topic",
	"self_notify": "self_notify",
	"tag_admins_on_reply": "tag_admins_on_reply",
}


@dataclass(frozen=True)
class LegacySnapshot:
	chat_id: int | None = None
	settings: dict[str, bool] = field(default_factory=dict)
	threads: dict[str, int] = field(default_factory=dict)

	@property
	def available(self) -> bool:
		return bool(self.chat_id or self.threads)


@dataclass(frozen=True)
class ImportPlan:
	chat_id: int | None = None
	settings: dict[str, bool] = field(default_factory=dict)
	topics: dict[str, TopicRecord] = field(default_factory=dict)
	added: int = 0
	skipped: int = 0
	dropped: int = 0
	binds_group: bool = False
	replaces_group: bool = False

	@property
	def available(self) -> bool:
		return bool(self.chat_id or self.added or self.skipped)

	@property
	def changes(self) -> bool:
		return bool(self.added or self.dropped or self.settings or self.binds_group)


def legacy_plugin_installed() -> bool:
	"""The standalone plugin is loaded in this Cardinal process."""
	try:
		return any(getattr(module, "UUID", None) == SYNC_PLUGIN_UUID for module in list(sys.modules.values()))
	except Exception:
		return False


def read_legacy_snapshot(storage: PluginStorage | None = None) -> LegacySnapshot:
	source = storage or PluginStorage()
	settings = source.load_dict(SYNC_PLUGIN_SETTINGS_FILE)
	threads = source.load_dict(SYNC_PLUGIN_THREADS_FILE)
	return LegacySnapshot(
		chat_id=normalize_chat_id(settings.get("chat_id")),
		settings=convert_settings(settings),
		threads=convert_threads(threads),
	)


def convert_settings(data: Any) -> dict[str, bool]:
	if not isinstance(data, dict):
		return {}
	return {
		target: data[source]
		for source, target in SETTINGS_MAP.items()
		if isinstance(data.get(source), bool)
	}


def convert_threads(data: Any) -> dict[str, int]:
	if not isinstance(data, dict):
		return {}

	threads: dict[str, int] = {}
	used: set[int] = set()
	for key, value in data.items():
		chat_key = str(key).strip()
		if not chat_key.lstrip("-").isdigit():
			continue
		if isinstance(value, bool) or not isinstance(value, int) or value in used:
			continue
		used.add(value)
		threads[chat_key] = value
	return threads


def build_import_plan(
	snapshot: LegacySnapshot,
	current_topics: dict[str, TopicRecord],
	current_chat_id: int | None,
	usernames: dict[str, str] | None = None,
	current_settings: dict[str, Any] | None = None,
) -> ImportPlan:
	"""Merge legacy threads into the current topics without touching anything on disk."""
	binds_group = bool(snapshot.chat_id and snapshot.chat_id != current_chat_id)
	replaces_group = binds_group and bool(current_chat_id)
	kept = {} if replaces_group else dict(current_topics)
	dropped = len(current_topics) - len(kept)

	topics = dict(kept)
	used = {record.thread_id for record in topics.values()}
	added = 0
	skipped = 0
	names = usernames or {}
	for chat_key, thread_id in snapshot.threads.items():
		if chat_key in topics or thread_id in used:
			skipped += 1
			continue

		used.add(thread_id)
		username = str(names.get(chat_key, "") or "")
		topics[chat_key] = TopicRecord(
			thread_id=thread_id,
			username=username,
			title=format_topic_name(username, chat_key) if username else "",
		)
		added += 1

	return ImportPlan(
		chat_id=snapshot.chat_id,
		settings=pending_settings(snapshot.settings, current_settings),
		topics=topics,
		added=added,
		skipped=skipped,
		dropped=dropped,
		binds_group=binds_group,
		replaces_group=replaces_group,
	)


def pending_settings(settings: dict[str, bool], current: dict[str, Any] | None) -> dict[str, bool]:
	if current is None:
		return dict(settings)
	return {key: value for key, value in settings.items() if current.get(key) != value}
