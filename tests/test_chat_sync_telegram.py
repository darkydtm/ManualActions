from __future__ import annotations

import sys
import types
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

telebot_module = types.ModuleType("telebot")
telebot_types_module = types.ModuleType("telebot.types")
telebot_types_module.CallbackQuery = object
telebot_types_module.Message = object
telebot_types_module.InlineKeyboardButton = object
telebot_types_module.InlineKeyboardMarkup = object
telebot_module.TeleBot = object
telebot_module.types = telebot_types_module
sys.modules.setdefault("telebot", telebot_module)
sys.modules.setdefault("telebot.types", telebot_types_module)

from core.chat_sync.telegram import CHAT_SYNC_COMMANDS, TelegramChatSyncFlow, is_command
from core.chat_sync.storage import TopicRecord


TELEGRAM_CHAT_ID = -1001
THREAD_ID = 55


class FakeService:
	def __init__(self, ready=True, topics=None):
		self.ready = ready
		self.telegram_chat_id = TELEGRAM_CHAT_ID
		self.topics = topics if topics is not None else {"77": TopicRecord(thread_id=THREAD_ID, username="buyer")}
		self.sent = []
		self.images = []
		self.send_result = True
		self.cardinal = SimpleNamespace(account=SimpleNamespace())
		self.bulk_sync_running = False
		self.cleared = False

	def chat_id_for_thread(self, thread_id):
		for key, record in self.topics.items():
			if record.thread_id == thread_id:
				return key
		return None

	def get_topic(self, chat_id):
		return self.topics.get(str(chat_id))

	def send_to_funpay(self, chat_id, username, text):
		self.sent.append((str(chat_id), username, text))
		return self.send_result

	def send_image_to_funpay(self, chat_id, username, payload):
		self.images.append((str(chat_id), username, payload))
		return self.send_result

	def clear_topics(self):
		self.cleared = True


class FakeBot:
	def __init__(self):
		self.replies = []
		self.messages = []

	def reply_to(self, message, text, **kwargs):
		self.replies.append(text)
		return SimpleNamespace(chat=message.chat, message_id=1)

	def send_message(self, chat_id, text, **kwargs):
		self.messages.append((chat_id, text))
		return SimpleNamespace(chat=SimpleNamespace(id=chat_id), message_id=2)


class FakeHost:
	def __init__(self, bot):
		self.tgbot = bot
		self.tg = SimpleNamespace()
		self.cardinal = SimpleNamespace(add_telegram_commands=Mock())
		self.settings = {"chat_sync": {"chat_id": TELEGRAM_CHAT_ID}}

	def update_settings(self, mutation):
		mutation(self.settings)


def make_message(text="hi", thread_id=THREAD_ID, chat_id=TELEGRAM_CHAT_ID, entities=None, **extra):
	return SimpleNamespace(
		text=text,
		caption=None,
		chat=SimpleNamespace(id=chat_id, is_forum=True),
		from_user=SimpleNamespace(id=999),
		message_thread_id=thread_id,
		message_id=7,
		entities=entities,
		photo=None,
		document=None,
		sticker=None,
		**extra,
	)


def build_flow(service=None):
	bot = FakeBot()
	host = FakeHost(bot)
	service = service or FakeService()
	return TelegramChatSyncFlow(host, service), bot, host, service


class OutgoingMessageTest(unittest.TestCase):
	def test_forwards_topic_message_to_funpay(self):
		flow, _, _, service = build_flow()

		flow.forward_message(make_message("привет"))

		self.assertEqual(service.sent, [("77", "buyer", "привет")])

	def test_recognises_outgoing_messages(self):
		flow, _, _, _ = build_flow()

		self.assertTrue(flow.is_outgoing_message(make_message()))

	def test_ignores_messages_outside_the_sync_group(self):
		flow, _, _, service = build_flow()

		self.assertFalse(flow.is_outgoing_message(make_message(chat_id=-2002)))
		flow.forward_message(make_message(chat_id=-2002))
		self.assertEqual(service.sent, [])

	def test_ignores_unknown_topics(self):
		flow, _, _, service = build_flow()

		self.assertFalse(flow.is_outgoing_message(make_message(thread_id=999)))

	def test_ignores_commands(self):
		command = make_message("/refund", entities=[SimpleNamespace(type="bot_command", offset=0)])

		flow, _, _, _ = build_flow()

		self.assertFalse(flow.is_outgoing_message(command))

	def test_allows_replies_inside_a_topic(self):
		flow, _, _, service = build_flow()
		reply = make_message("ответ", reply_to_message=SimpleNamespace(message_id=3))

		flow.forward_message(reply)

		self.assertEqual(service.sent, [("77", "buyer", "ответ")])

	def test_ignores_blank_messages(self):
		flow, _, _, service = build_flow()

		flow.forward_message(make_message("   "))

		self.assertEqual(service.sent, [])

	def test_reports_failed_delivery(self):
		flow, bot, _, service = build_flow()
		service.send_result = False

		flow.forward_message(make_message("привет"))

		self.assertTrue(bot.replies)
		self.assertIn("Не удалось отправить", bot.replies[0])

	def test_does_nothing_when_service_is_not_ready(self):
		flow, _, _, service = build_flow(FakeService(ready=False))

		self.assertFalse(flow.is_outgoing_message(make_message()))


class SetupCommandTest(unittest.TestCase):
	def test_binds_the_group(self):
		flow, bot, host, _ = build_flow()
		host.settings["chat_sync"]["chat_id"] = None
		flow.service.telegram_chat_id = None

		flow.cmd_setup_sync_chat(make_message("/setup_sync_chat"))

		self.assertEqual(host.settings["chat_sync"]["chat_id"], TELEGRAM_CHAT_ID)

	def test_rejects_private_chats(self):
		flow, bot, host, _ = build_flow()
		message = make_message("/setup_sync_chat", chat_id=999)

		flow.cmd_setup_sync_chat(message)

		self.assertIn("в группе", bot.replies[0])

	def test_rejects_groups_without_topics(self):
		flow, bot, host, _ = build_flow()
		message = make_message("/setup_sync_chat")
		message.chat.is_forum = False

		flow.cmd_setup_sync_chat(message)

		self.assertIn("режим тем", bot.replies[0])

	def test_replacing_the_group_resets_topics(self):
		flow, bot, host, service = build_flow()
		message = make_message("/setup_sync_chat", chat_id=-3003)

		flow.cmd_setup_sync_chat(message)

		self.assertEqual(host.settings["chat_sync"]["chat_id"], -3003)
		self.assertTrue(service.cleared)

	def test_unbinds_the_group(self):
		flow, bot, host, service = build_flow()

		flow.cmd_delete_sync_chat(make_message("/delete_sync_chat"))

		self.assertIsNone(host.settings["chat_sync"]["chat_id"])
		self.assertTrue(service.cleared)

	def test_unbind_without_group_reports_it(self):
		flow, bot, host, service = build_flow()
		service.telegram_chat_id = None

		flow.cmd_delete_sync_chat(make_message("/delete_sync_chat"))

		self.assertIn("не привязана", bot.replies[0])


class TopicCommandTest(unittest.TestCase):
	def test_requires_a_topic(self):
		flow, bot, _, _ = build_flow()

		self.assertIsNone(flow.require_topic(make_message(thread_id=404)))
		self.assertIn("в теме", bot.replies[0])

	def test_resolves_username_from_the_record(self):
		flow, _, _, _ = build_flow()

		self.assertEqual(flow.topic_username("77"), "buyer")

	def test_registers_every_advertised_command(self):
		handled = []
		flow, _, host, _ = build_flow()
		host.tg = SimpleNamespace(
			msg_handler=lambda handler, commands=None, **kwargs: handled.extend(commands or ()),
			cbq_handler=lambda *args, **kwargs: None,
		)

		flow.register()

		self.assertEqual({command[0] for command in CHAT_SYNC_COMMANDS} - set(handled), set())
		host.cardinal.add_telegram_commands.assert_called_once()


class HelpersTest(unittest.TestCase):
	def test_detects_bot_commands(self):
		self.assertTrue(is_command(make_message("/x", entities=[SimpleNamespace(type="bot_command", offset=0)])))
		self.assertFalse(is_command(make_message("text")))
		self.assertFalse(is_command(make_message("a /x", entities=[SimpleNamespace(type="bot_command", offset=2)])))


if __name__ == "__main__":
	unittest.main()
