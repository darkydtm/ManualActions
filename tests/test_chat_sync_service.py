from __future__ import annotations

import threading
import time
from types import SimpleNamespace
import unittest

from core.chat_sync.dispatcher import TelegramRateLimiter, TelegramSender
from core.chat_sync.service import ChatSyncService
from core.chat_sync.settings import DEFAULT_CHAT_SYNC_SETTINGS
from core.chat_sync.storage import TopicRecord


TELEGRAM_CHAT_ID = -1001


class FakeMessage:
	def __init__(self, message_id, text="hello", author="buyer", author_id=7, chat_id=77, chat_name="buyer", **extra):
		self.id = message_id
		self.text = text
		self.author = author
		self.author_id = author_id
		self.chat_id = chat_id
		self.chat_name = chat_name
		self.badge = None
		self.by_bot = False
		self.by_vertex = False
		self.is_autoreply = False
		self.is_employee = False
		self.is_moderation = False
		self.is_arbitration = False
		self.is_support = False
		self.i_am_buyer = False
		self.i_am_seller = True
		self.image_name = None
		self.interlocutor_id = 7
		self.type = SimpleNamespace(name="NON_SYSTEM")
		for key, value in extra.items():
			setattr(self, key, value)

	def __str__(self):
		return self.text or ""


class ApiError(Exception):
	def __init__(self, message, error_code=400, retry_after=None):
		super().__init__(message)
		self.error_code = error_code
		self.result_json = {"parameters": {"retry_after": retry_after}} if retry_after else {}


class FakeBot:
	def __init__(self, topic_delay=0.0):
		self.topic_delay = topic_delay
		self.created_topics = []
		self.sent = []
		self.edited = []
		self.send_error = None
		self._lock = threading.Lock()
		self._next_thread_id = 500

	def create_forum_topic(self, chat_id, name, icon_custom_emoji_id=None):
		time.sleep(self.topic_delay)
		with self._lock:
			self._next_thread_id += 1
			thread_id = self._next_thread_id
			self.created_topics.append((chat_id, name, thread_id))
		return SimpleNamespace(message_thread_id=thread_id)

	def send_message(self, chat_id, text, message_thread_id=None, disable_notification=False):
		if self.send_error:
			raise self.send_error
		with self._lock:
			self.sent.append((chat_id, text, message_thread_id, disable_notification))
		return SimpleNamespace(message_id=len(self.sent))

	def edit_forum_topic(self, chat_id=None, message_thread_id=None, name=None, icon_custom_emoji_id=None):
		self.edited.append((chat_id, message_thread_id, name, icon_custom_emoji_id))
		return True

	def topic_messages(self, thread_id):
		return [text for _, text, thread, _ in self.sent if thread == thread_id]


class FakeStorage:
	def __init__(self, topics=None):
		self.topics = topics or {}
		self.saves = 0

	def load(self):
		return dict(self.topics)

	def save(self, topics):
		self.saves += 1
		self.topics = {key: record for key, record in topics.items()}


class FakeAccount:
	def __init__(self, history=None, chats=None):
		self.id = 1
		self.history = history if history is not None else []
		self.chats = chats or {}
		self.last_429_err_time = 0
		self.history_calls = []

	def get_chat_history(self, chat_id, *args, **kwargs):
		self.history_calls.append((chat_id, args, kwargs))
		return list(self.history)

	def get_chats(self, update=False):
		return dict(self.chats)


class FakeHost:
	def __init__(self, bot, account, config=None):
		self.tgbot = bot
		self.tg = object()
		self.cardinal = SimpleNamespace(
			account=account,
			blacklist=[],
			old_mode_enabled=False,
			AR_CFG={},
			bl_cmd_notification_enabled=False,
			MAIN_CFG={"Other": {}},
			new_message_handlers=[],
			new_order_handlers=[],
			init_message_handlers=[],
		)
		self.settings = {"chat_sync": {**DEFAULT_CHAT_SYNC_SETTINGS, "chat_id": TELEGRAM_CHAT_ID, **(config or {})}}

	def telegram_admin_ids(self):
		return [42]

	def update_settings(self, mutation):
		mutation(self.settings)


def build_service(bot=None, account=None, config=None, storage=None):
	bot = bot or FakeBot()
	account = account or FakeAccount()
	host = FakeHost(bot, account, config)
	limiter = TelegramRateLimiter(messages_per_minute=100000, min_interval=0, sleeper=lambda _: None)
	sender = TelegramSender(limiter, sleeper=lambda _: None)
	service = ChatSyncService(host, storage=storage or FakeStorage(), sender=sender)
	service.load()
	return service, bot, host


class TopicCreationTest(unittest.TestCase):
	def test_concurrent_events_create_only_one_topic(self):
		service, bot, _ = build_service(bot=FakeBot(topic_delay=0.02))
		results = []
		barrier = threading.Barrier(8)

		def worker():
			barrier.wait()
			results.append(service.ensure_topic(77, "buyer", backfill=False))

		threads = [threading.Thread(target=worker) for _ in range(8)]
		for thread in threads:
			thread.start()
		for thread in threads:
			thread.join()

		self.assertEqual(len(bot.created_topics), 1)
		self.assertEqual({record.thread_id for record in results}, {bot.created_topics[0][2]})

	def test_topic_is_reused_for_known_chat(self):
		service, bot, _ = build_service()

		first = service.ensure_topic(77, "buyer", backfill=False)
		second = service.ensure_topic("77", "buyer", backfill=False)

		self.assertEqual(first.thread_id, second.thread_id)
		self.assertEqual(len(bot.created_topics), 1)

	def test_topic_is_persisted_immediately(self):
		storage = FakeStorage()
		service, bot, _ = build_service(storage=storage)

		record = service.ensure_topic(77, "buyer", backfill=False)

		self.assertEqual(storage.topics["77"].thread_id, record.thread_id)

	def test_missing_thread_unlinks_topic(self):
		service, bot, _ = build_service()
		record = service.ensure_topic(77, "buyer", backfill=False)
		bot.send_error = ApiError("Bad Request: message thread not found")

		service.send_text("77", record.thread_id, "text")

		self.assertIsNone(service.get_topic(77))

	def test_new_order_is_ignored_when_topic_exists_for_username(self):
		service, bot, _ = build_service()
		service.ensure_topic(77, "buyer", backfill=False)
		created_before = len(bot.created_topics)

		service.handle_new_order(service.cardinal, SimpleNamespace(order=SimpleNamespace(buyer_username="buyer")))
		service.queue.stop()

		self.assertEqual(len(bot.created_topics), created_before)


class HistoryBackfillTest(unittest.TestCase):
	def test_new_topic_receives_existing_chat_history(self):
		account = FakeAccount(history=[FakeMessage(1, "first"), FakeMessage(2, "second")])
		service, bot, _ = build_service(account=account)

		record = service.ensure_topic(77, "buyer")

		posted = " ".join(bot.topic_messages(record.thread_id))
		self.assertIn("first", posted)
		self.assertIn("second", posted)
		self.assertEqual(service.get_topic(77).last_message_id, 2)

	def test_history_depth_limits_backfill(self):
		history = [FakeMessage(index, f"message {index}") for index in range(1, 11)]
		service, bot, _ = build_service(account=FakeAccount(history=history), config={"history_depth": 3})

		record = service.ensure_topic(77, "buyer")

		posted = " ".join(bot.topic_messages(record.thread_id))
		self.assertNotIn("message 7", posted)
		for index in (8, 9, 10):
			self.assertIn(f"message {index}", posted)

	def test_history_backfill_can_be_disabled(self):
		account = FakeAccount(history=[FakeMessage(1, "first")])
		service, bot, _ = build_service(account=account, config={"history_depth": 0})

		record = service.ensure_topic(77, "buyer")

		self.assertNotIn("first", " ".join(bot.topic_messages(record.thread_id)))

	def test_backfilled_messages_are_not_delivered_twice(self):
		account = FakeAccount(history=[FakeMessage(1, "old"), FakeMessage(2, "recent")])
		service, bot, _ = build_service(account=account)

		service.deliver(77, "buyer", [FakeMessage(2, "recent"), FakeMessage(3, "brand new")])

		posted = " ".join(bot.topic_messages(service.get_topic(77).thread_id))
		self.assertEqual(posted.count("recent"), 1)
		self.assertIn("brand new", posted)

	def test_delivery_updates_last_message_id(self):
		service, _, _ = build_service(config={"history_depth": 0})

		service.deliver(77, "buyer", [FakeMessage(5, "hi")])

		self.assertEqual(service.get_topic(77).last_message_id, 5)

	def test_messages_without_ids_are_always_delivered(self):
		service, bot, _ = build_service(config={"history_depth": 0})
		service.ensure_topic(77, "buyer", backfill=False)

		service.deliver(77, "buyer", [FakeMessage(None, "no id")])

		self.assertIn("no id", " ".join(bot.topic_messages(service.get_topic(77).thread_id)))


class BulkSyncTest(unittest.TestCase):
	def test_creates_topics_for_untracked_chats(self):
		chats = {
			77: SimpleNamespace(id=77, name="buyer"),
			88: SimpleNamespace(id=88, name="other"),
		}
		service, bot, _ = build_service(account=FakeAccount(chats=chats), config={"history_depth": 0})

		created = service.run_bulk_sync()

		self.assertEqual(created, 2)
		self.assertEqual(set(service.threads), {"77", "88"})

	def test_skips_chats_that_already_have_topics(self):
		chats = {77: SimpleNamespace(id=77, name="buyer")}
		storage = FakeStorage({"77": TopicRecord(thread_id=9, username="buyer")})
		service, bot, _ = build_service(account=FakeAccount(chats=chats), storage=storage, config={"history_depth": 0})

		created = service.run_bulk_sync()

		self.assertEqual(created, 0)
		self.assertEqual(bot.created_topics, [])


class ReadinessTest(unittest.TestCase):
	def test_not_ready_without_group(self):
		service, _, host = build_service()
		host.settings["chat_sync"]["chat_id"] = None

		self.assertFalse(service.ready)

	def test_not_ready_when_disabled(self):
		service, _, host = build_service()
		host.settings["chat_sync"]["enabled"] = False

		self.assertFalse(service.ready)

	def test_not_ready_in_old_mode(self):
		service, _, host = build_service()
		host.cardinal.old_mode_enabled = True

		self.assertFalse(service.ready)

	def test_exposes_topic_lookup_tables(self):
		service, _, _ = build_service()
		record = service.ensure_topic(77, "buyer", backfill=False)

		self.assertEqual(service.threads, {"77": record.thread_id})
		self.assertEqual(service.reversed_threads, {record.thread_id: "77"})
		self.assertEqual(service.threads_info[record.thread_id][1], "buyer (77)")


class OutgoingMarkerTest(unittest.TestCase):
	def test_strips_marker_and_flags_own_messages(self):
		service, _, _ = build_service()
		own = SimpleNamespace(message=FakeMessage(1, "⁢mine", author_id=1))
		theirs = SimpleNamespace(message=FakeMessage(2, "⁢theirs", author_id=7))
		event = SimpleNamespace(stack=SimpleNamespace(id=lambda: "s1", get_stack=lambda: [own, theirs]))

		service.mark_own_messages(service.cardinal, event)

		self.assertEqual(own.message.text, "mine")
		self.assertTrue(getattr(own, "sync_ignore", False))
		self.assertEqual(theirs.message.text, "theirs")
		self.assertFalse(getattr(theirs, "sync_ignore", False))

	def test_ignored_events_are_not_delivered(self):
		service, bot, _ = build_service(config={"history_depth": 0})
		ignored = SimpleNamespace(message=FakeMessage(1, "echo"), sync_ignore=True)
		event = SimpleNamespace(
			message=FakeMessage(1, "echo"),
			stack=SimpleNamespace(id=lambda: "s2", get_stack=lambda: [ignored]),
		)

		service.handle_new_message(service.cardinal, event)
		service.queue.stop()

		self.assertEqual(bot.sent, [])

	def test_messages_are_grouped_per_chat(self):
		service, bot, _ = build_service(config={"history_depth": 0})
		mine = FakeMessage(1, "for me", chat_id=77, chat_name="buyer")
		other = FakeMessage(2, "for them", chat_id=88, chat_name="other")
		event = SimpleNamespace(
			message=mine,
			stack=SimpleNamespace(
				id=lambda: "mixed",
				get_stack=lambda: [SimpleNamespace(message=mine), SimpleNamespace(message=other)],
			),
		)

		service.handle_new_message(service.cardinal, event)
		service.queue.join()
		service.queue.stop()

		first = service.get_topic(77)
		second = service.get_topic(88)
		self.assertIn("for me", " ".join(bot.topic_messages(first.thread_id)))
		self.assertNotIn("for them", " ".join(bot.topic_messages(first.thread_id)))
		self.assertIn("for them", " ".join(bot.topic_messages(second.thread_id)))

	def test_repeated_stack_is_processed_once(self):
		service, _, _ = build_service(config={"history_depth": 0})
		submitted = []
		service.queue.submit = submitted.append
		event = SimpleNamespace(
			message=FakeMessage(1, "hi"),
			stack=SimpleNamespace(id=lambda: "same", get_stack=lambda: [SimpleNamespace(message=FakeMessage(1, "hi"))]),
		)

		service.handle_new_message(service.cardinal, event)
		service.handle_new_message(service.cardinal, event)

		self.assertEqual(len(submitted), 1)


if __name__ == "__main__":
	unittest.main()
