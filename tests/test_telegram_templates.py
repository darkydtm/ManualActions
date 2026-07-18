from __future__ import annotations

import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch


telebot_types_module = SimpleNamespace(
	CallbackQuery=object,
	Message=object,
	InlineKeyboardButton=object,
	InlineKeyboardMarkup=object,
)
sys.modules.setdefault("telebot", SimpleNamespace(TeleBot=object, types=telebot_types_module))
sys.modules.setdefault("telebot.types", telebot_types_module)

from core.constants import (
	CBT_TEMPLATES_CANCEL,
	CBT_TEMPLATES_SELECT,
	CBT_TEMPLATES_SEND,
)
from core.telegram.templates import (
	PendingTemplateSelection,
	PendingTemplateSend,
	TelegramTemplatesFlow,
)


class FakeButton:
	def __init__(self, text, callback_data=None):
		self.text = text
		self.callback_data = callback_data


class FakeKeyboard:
	def __init__(self, row_width=1):
		self.row_width = row_width
		self.rows = []

	def add(self, *buttons):
		self.rows.append(list(buttons))
		return self


class FakeBot:
	def __init__(self):
		self.replies = []
		self.edits = []
		self.answers = []

	def reply_to(self, message, text, **kwargs):
		self.replies.append((message, text, kwargs))
		return SimpleNamespace(chat=message.chat, message_id=99)

	def edit_message_text(self, text, chat_id, message_id, **kwargs):
		self.edits.append((text, chat_id, message_id, kwargs))

	def answer_callback_query(self, callback_id, text=None, **kwargs):
		self.answers.append((callback_id, text, kwargs))


class FakeTelegram:
	def __init__(self):
		self.commands = []
		self.callbacks = []

	def msg_handler(self, handler, commands=None, **kwargs):
		if commands:
			self.commands.extend(commands)

	def cbq_handler(self, handler, predicate):
		self.callbacks.append((handler, predicate))


class TelegramTemplatesFlowTest(unittest.TestCase):
	def setUp(self):
		from core.telegram import templates as templates_module

		templates_module.B = FakeButton
		templates_module.K = FakeKeyboard

	def test_registers_templates_command(self):
		tg = FakeTelegram()

		TelegramTemplatesFlow(SimpleNamespace(tg=tg)).register()

		self.assertEqual(tg.commands, ["templates"])
		self.assertEqual(len(tg.callbacks), 3)

	def test_rejects_command_outside_chat_sync(self):
		bot = FakeBot()
		flow = TelegramTemplatesFlow(SimpleNamespace(
			tgbot=bot,
			cardinal=SimpleNamespace(),
			settings={"templates": []},
		))
		message = SimpleNamespace(chat=SimpleNamespace(id=1))

		with patch("core.telegram.templates.is_in_sync_chat", return_value=False):
			flow.cmd_templates(message)

		self.assertIn("только в топике Chat Sync", bot.replies[0][1])

	def test_reports_unresolved_chat_sync_topic(self):
		bot = FakeBot()
		flow = TelegramTemplatesFlow(SimpleNamespace(
			tgbot=bot,
			cardinal=SimpleNamespace(),
			settings={"templates": []},
		))
		message = SimpleNamespace(chat=SimpleNamespace(id=1))

		with (
			patch("core.telegram.templates.is_in_sync_chat", return_value=True),
			patch("core.telegram.templates.get_topic_context", return_value=None),
		):
			flow.cmd_templates(message)

		self.assertIn("Не удалось определить пользователя", bot.replies[0][1])

	def test_reports_empty_template_list(self):
		bot = FakeBot()
		flow = TelegramTemplatesFlow(SimpleNamespace(
			tgbot=bot,
			cardinal=SimpleNamespace(),
			settings={"templates": []},
		))
		message = SimpleNamespace(chat=SimpleNamespace(id=1))
		context = SimpleNamespace(username="buyer", fp_chat_id=7)

		with (
			patch("core.telegram.templates.is_in_sync_chat", return_value=True),
			patch("core.telegram.templates.get_topic_context", return_value=context),
		):
			flow.cmd_templates(message)

		self.assertIn("не созданы", bot.replies[0][1])

	def test_shows_template_title_buttons(self):
		bot = FakeBot()
		flow = TelegramTemplatesFlow(SimpleNamespace(
			tgbot=bot,
			cardinal=SimpleNamespace(),
			settings={
				"templates": [
					{"id": "one", "title": "Greeting", "text": "Hello"},
					{"id": "two", "title": "Thanks", "text": "Thank you"},
				],
			},
		))
		message = SimpleNamespace(chat=SimpleNamespace(id=1))
		context = SimpleNamespace(username="<buyer>", fp_chat_id=7)

		with (
			patch("core.telegram.templates.is_in_sync_chat", return_value=True),
			patch("core.telegram.templates.get_topic_context", return_value=context),
		):
			flow.cmd_templates(message)

		text = bot.replies[0][1]
		keyboard = bot.replies[0][2]["reply_markup"]
		self.assertIn("&lt;buyer&gt;", text)
		self.assertEqual([row[0].text for row in keyboard.rows[:2]], ["Greeting", "Thanks"])
		self.assertTrue(all(row[0].callback_data.startswith(CBT_TEMPLATES_SELECT) for row in keyboard.rows[:2]))

	def test_selecting_template_shows_send_confirmation(self):
		bot = FakeBot()
		cardinal = SimpleNamespace(send_message=lambda **kwargs: True)
		flow = TelegramTemplatesFlow(SimpleNamespace(
			tgbot=bot,
			cardinal=cardinal,
			settings={"templates": [{"id": "one", "title": "<Greeting>", "text": "<Hello>"}]},
		))
		token = flow.selection_payloads.put(PendingTemplateSelection("one", 7))
		call = self.callback(f"{CBT_TEMPLATES_SELECT}{token}")

		flow.select_template(call)

		text, _, _, kwargs = bot.edits[0]
		callbacks = [button.callback_data for row in kwargs["reply_markup"].rows for button in row]
		self.assertIn("&lt;Greeting&gt;", text)
		self.assertIn("&lt;Hello&gt;", text)
		self.assertTrue(any(value.startswith(CBT_TEMPLATES_SEND) for value in callbacks))
		self.assertTrue(any(value.startswith(CBT_TEMPLATES_CANCEL) for value in callbacks))

	def test_empty_template_text_cannot_be_sent(self):
		bot = FakeBot()
		cardinal = SimpleNamespace(send_message=lambda **kwargs: True)
		flow = TelegramTemplatesFlow(SimpleNamespace(
			tgbot=bot,
			cardinal=cardinal,
			settings={"templates": [{"id": "one", "title": "Draft", "text": ""}]},
		))
		token = flow.selection_payloads.put(PendingTemplateSelection("one", 7))

		with patch.object(cardinal, "send_message") as send:
			flow.select_template(self.callback(f"{CBT_TEMPLATES_SELECT}{token}"))

		send.assert_not_called()
		self.assertIn("не заполнен", bot.edits[0][0])
		self.assertIsNone(bot.edits[0][3]["reply_markup"])

	def test_confirmed_template_is_sent_once(self):
		bot = FakeBot()
		cardinal = SimpleNamespace(send_message=lambda **kwargs: True)
		flow = TelegramTemplatesFlow(SimpleNamespace(
			tgbot=bot,
			cardinal=cardinal,
			settings={"templates": []},
		))
		token = flow.pending_sends.put(PendingTemplateSend("Greeting", "Hello", 7))
		call = self.callback(f"{CBT_TEMPLATES_SEND}{token}")

		with patch.object(cardinal, "send_message", return_value=True) as send:
			flow.confirm_send(call)
			flow.confirm_send(call)

		send.assert_called_once_with(chat_id=7, message_text="Hello")
		self.assertIn("отправлено", bot.edits[0][0])
		self.assertIn("истекло", bot.edits[1][0])

	def test_failed_funpay_send_is_reported(self):
		bot = FakeBot()
		cardinal = SimpleNamespace(send_message=lambda **kwargs: False)
		flow = TelegramTemplatesFlow(SimpleNamespace(
			tgbot=bot,
			cardinal=cardinal,
			settings={"templates": []},
		))
		token = flow.pending_sends.put(PendingTemplateSend("Greeting", "Hello", 7))

		flow.confirm_send(self.callback(f"{CBT_TEMPLATES_SEND}{token}"))

		self.assertIn("Не удалось отправить", bot.edits[0][0])
		self.assertIsNone(bot.edits[0][3]["reply_markup"])

	def test_cancels_pending_send(self):
		bot = FakeBot()
		cardinal = SimpleNamespace(send_message=lambda **kwargs: True)
		flow = TelegramTemplatesFlow(SimpleNamespace(
			tgbot=bot,
			cardinal=cardinal,
			settings={"templates": []},
		))
		token = flow.pending_sends.put(PendingTemplateSend("Greeting", "Hello", 7))

		with patch.object(cardinal, "send_message") as send:
			flow.cancel_send(self.callback(f"{CBT_TEMPLATES_CANCEL}{token}"))

		send.assert_not_called()
		self.assertIn("отменена", bot.edits[0][0])
		self.assertIsNone(flow.pending_sends.get(token))

	def test_expired_selection_does_not_send(self):
		bot = FakeBot()
		cardinal = SimpleNamespace(send_message=lambda **kwargs: True)
		flow = TelegramTemplatesFlow(SimpleNamespace(
			tgbot=bot,
			cardinal=cardinal,
			settings={"templates": []},
		))

		with patch.object(cardinal, "send_message") as send:
			flow.select_template(self.callback(f"{CBT_TEMPLATES_SELECT}missing"))

		send.assert_not_called()
		self.assertIn("истекло", bot.edits[0][0])

	def callback(self, data):
		return SimpleNamespace(
			id="call-id",
			data=data,
			message=SimpleNamespace(
				chat=SimpleNamespace(id=1),
				message_id=2,
				text="Template menu",
			),
		)


if __name__ == "__main__":
	unittest.main()
