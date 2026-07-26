from __future__ import annotations

from types import SimpleNamespace
import unittest

from core.chat_sync.importer import (
	SYNC_PLUGIN_SETTINGS_FILE,
	SYNC_PLUGIN_THREADS_FILE,
	LegacySnapshot,
	build_import_plan,
	convert_settings,
	convert_threads,
	read_legacy_snapshot,
)
from core.chat_sync.storage import TopicRecord

from test_chat_sync_service import FakeAccount, FakeStorage, build_service


LEGACY_SETTINGS = {
	"chat_id": -1001,
	"watermark_is_hidden": True,
	"ad": False,
	"image_name": False,
	"chat_url": True,
	"mono": True,
	"buyer_viewing": False,
	"edit_topic": False,
	"self_notify": False,
	"tag_admins_on_reply": True,
	"templates": True,
}

LEGACY_THREADS = {"77": 5, "88": 6}


class FakePluginStorage:
	def __init__(self, settings=None, threads=None):
		self.files = {
			SYNC_PLUGIN_SETTINGS_FILE: settings if settings is not None else {},
			SYNC_PLUGIN_THREADS_FILE: threads if threads is not None else {},
		}

	def load_dict(self, path):
		return dict(self.files.get(path, {}))


class LegacySnapshotTest(unittest.TestCase):
	def test_reads_settings_and_threads(self):
		snapshot = read_legacy_snapshot(FakePluginStorage(LEGACY_SETTINGS, LEGACY_THREADS))

		self.assertTrue(snapshot.available)
		self.assertEqual(snapshot.chat_id, -1001)
		self.assertEqual(snapshot.threads, {"77": 5, "88": 6})

	def test_is_unavailable_without_files(self):
		self.assertFalse(read_legacy_snapshot(FakePluginStorage()).available)

	def test_maps_setting_names(self):
		settings = convert_settings(LEGACY_SETTINGS)

		self.assertTrue(settings["hide_watermark"])
		self.assertFalse(settings["show_ads"])
		self.assertFalse(settings["show_image_name"])
		self.assertTrue(settings["tag_admins_on_reply"])

	def test_ignores_unknown_and_non_boolean_settings(self):
		settings = convert_settings({"templates": True, "mono": "yes", "chat_id": -1})

		self.assertEqual(settings, {})

	def test_skips_malformed_threads(self):
		threads = convert_threads({"77": 5, "buyer": 6, "88": "seven", "99": True})

		self.assertEqual(threads, {"77": 5})

	def test_drops_duplicate_thread_ids(self):
		self.assertEqual(convert_threads({"77": 5, "88": 5}), {"77": 5})

	def test_ignores_garbage(self):
		self.assertEqual(convert_settings(None), {})
		self.assertEqual(convert_threads("nope"), {})


class ImportPlanTest(unittest.TestCase):
	def test_adds_legacy_threads_to_empty_state(self):
		snapshot = LegacySnapshot(chat_id=-1001, settings={"mono": True}, threads=LEGACY_THREADS)

		plan = build_import_plan(snapshot, {}, None)

		self.assertEqual(plan.added, 2)
		self.assertEqual(plan.skipped, 0)
		self.assertFalse(plan.replaces_group)
		self.assertEqual(plan.topics["77"].thread_id, 5)

	def test_keeps_existing_topics_of_the_same_group(self):
		snapshot = LegacySnapshot(chat_id=-1001, threads=LEGACY_THREADS)
		current = {"99": TopicRecord(thread_id=9, username="buyer")}

		plan = build_import_plan(snapshot, current, -1001)

		self.assertEqual(plan.added, 2)
		self.assertEqual(plan.dropped, 0)
		self.assertEqual(set(plan.topics), {"77", "88", "99"})

	def test_skips_chats_that_already_have_a_topic(self):
		snapshot = LegacySnapshot(chat_id=-1001, threads=LEGACY_THREADS)
		current = {"77": TopicRecord(thread_id=9, username="buyer")}

		plan = build_import_plan(snapshot, current, -1001)

		self.assertEqual((plan.added, plan.skipped), (1, 1))
		self.assertEqual(plan.topics["77"].thread_id, 9)

	def test_skips_threads_already_used_by_another_chat(self):
		snapshot = LegacySnapshot(chat_id=-1001, threads={"77": 5})
		current = {"88": TopicRecord(thread_id=5)}

		plan = build_import_plan(snapshot, current, -1001)

		self.assertEqual((plan.added, plan.skipped), (0, 1))

	def test_replacing_the_group_drops_current_topics(self):
		snapshot = LegacySnapshot(chat_id=-1001, threads=LEGACY_THREADS)
		current = {"99": TopicRecord(thread_id=9)}

		plan = build_import_plan(snapshot, current, -2002)

		self.assertTrue(plan.replaces_group)
		self.assertEqual(plan.dropped, 1)
		self.assertEqual(set(plan.topics), {"77", "88"})

	def test_fills_usernames_when_they_are_known(self):
		snapshot = LegacySnapshot(chat_id=-1001, threads=LEGACY_THREADS)

		plan = build_import_plan(snapshot, {}, None, {"77": "buyer"})

		self.assertEqual(plan.topics["77"], TopicRecord(thread_id=5, username="buyer", title="buyer (77)"))
		self.assertEqual(plan.topics["88"].username, "")

	def test_reports_only_settings_that_differ(self):
		snapshot = LegacySnapshot(chat_id=-1001, settings={"mono": True, "show_ads": True})

		plan = build_import_plan(snapshot, {}, -1001, current_settings={"mono": True, "show_ads": False})

		self.assertEqual(plan.settings, {"show_ads": True})

	def test_binding_the_first_group_is_a_change(self):
		plan = build_import_plan(LegacySnapshot(chat_id=-1001), {}, None)

		self.assertTrue(plan.binds_group)
		self.assertFalse(plan.replaces_group)
		self.assertTrue(plan.changes)

	def test_reports_nothing_to_do(self):
		snapshot = LegacySnapshot(chat_id=-1001, threads={"77": 5})
		current = {"77": TopicRecord(thread_id=5)}

		plan = build_import_plan(snapshot, current, -1001, current_settings={})

		self.assertTrue(plan.available)
		self.assertFalse(plan.changes)


class ServiceImportTest(unittest.TestCase):
	def test_import_applies_settings_and_topics(self):
		storage = FakeStorage()
		chats = {77: SimpleNamespace(id=77, name="buyer")}
		service, _, host = build_service(account=FakeAccount(chats=chats), storage=storage)

		plan = service.import_legacy(LegacySnapshot(chat_id=-1001, settings={"mono": True}, threads=LEGACY_THREADS))

		self.assertEqual(plan.added, 2)
		self.assertEqual(host.settings["chat_sync"]["chat_id"], -1001)
		self.assertTrue(host.settings["chat_sync"]["mono"])
		self.assertEqual(service.threads, {"77": 5, "88": 6})
		self.assertEqual(service.reversed_threads, {5: "77", 6: "88"})
		self.assertEqual(storage.topics["77"].username, "buyer")

	def test_import_replaces_a_different_group(self):
		storage = FakeStorage({"99": TopicRecord(thread_id=9)})
		service, _, host = build_service(storage=storage)

		service.import_legacy(LegacySnapshot(chat_id=-2002, threads={"77": 5}))

		self.assertEqual(host.settings["chat_sync"]["chat_id"], -2002)
		self.assertEqual(service.threads, {"77": 5})

	def test_import_without_legacy_data_changes_nothing(self):
		service, _, host = build_service()
		before = dict(host.settings["chat_sync"])

		plan = service.import_legacy(LegacySnapshot())

		self.assertFalse(plan.available)
		self.assertEqual(host.settings["chat_sync"], before)
		self.assertEqual(service.threads, {})

	def test_preview_does_not_change_anything(self):
		service, _, host = build_service()
		snapshot = LegacySnapshot(chat_id=-2002, threads={"77": 5})

		plan = service.preview_import(snapshot)

		self.assertEqual(plan.added, 1)
		self.assertEqual(service.threads, {})
		self.assertNotEqual(host.settings["chat_sync"]["chat_id"], -2002)

	def test_imported_topic_learns_its_username_from_a_message(self):
		service, _, _ = build_service(config={"history_depth": 0})
		service.import_legacy(LegacySnapshot(chat_id=-1001, threads={"77": 5}))

		service.ensure_topic(77, "buyer", backfill=False)

		self.assertEqual(service.get_topic(77).username, "buyer")


if __name__ == "__main__":
	unittest.main()
