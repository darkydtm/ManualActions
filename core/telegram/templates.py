from __future__ import annotations

from dataclasses import dataclass
from html import escape
from typing import TYPE_CHECKING, Any, Protocol

import telebot
from telebot.types import InlineKeyboardButton as B, InlineKeyboardMarkup as K

from ..constants import CBT_TEMPLATES_CANCEL, CBT_TEMPLATES_SELECT, CBT_TEMPLATES_SEND
from ..funpay.chat_sync import get_topic_context, is_in_sync_chat
from ..payloads import CallbackPayloadCache

if TYPE_CHECKING:
	from cardinal import Cardinal


class TemplatesHost(Protocol):
	tg: object
	tgbot: telebot.TeleBot
	cardinal: Cardinal
	settings: dict[str, Any]


@dataclass(frozen=True)
class PendingTemplateSelection:
	template_id: str
	fp_chat_id: int


@dataclass(frozen=True)
class PendingTemplateSend:
	title: str
	text: str
	fp_chat_id: int


class TelegramTemplatesFlow:
	def __init__(self, host: TemplatesHost):
		self.host = host
		self.selection_payloads = CallbackPayloadCache()
		self.pending_sends = CallbackPayloadCache()

	def register(self) -> None:
		self.host.tg.msg_handler(self.cmd_templates, commands=["templates"])
		self.host.tg.cbq_handler(
			self.select_template,
			lambda c: (c.data or "").startswith(CBT_TEMPLATES_SELECT),
		)
		self.host.tg.cbq_handler(
			self.confirm_send,
			lambda c: (c.data or "").startswith(CBT_TEMPLATES_SEND),
		)
		self.host.tg.cbq_handler(
			self.cancel_send,
			lambda c: (c.data or "").startswith(CBT_TEMPLATES_CANCEL),
		)

	def cmd_templates(self, message: telebot.types.Message) -> None:
		if not is_in_sync_chat(message):
			self.host.tgbot.reply_to(
				message,
				"⚠️ Команда /templates доступна только в топике Chat Sync.",
			)
			return

		context = get_topic_context(self.host.cardinal, message)
		if not context:
			self.host.tgbot.reply_to(message, "❌ Не удалось определить пользователя из топика.")
			return

		templates = self.host.settings.get("templates", [])
		if not templates:
			self.host.tgbot.reply_to(message, "ℹ️ Заготовки сообщений не созданы.")
			return

		keyboard = K(row_width=1)
		for template in templates:
			token = self.selection_payloads.put(PendingTemplateSelection(
				template_id=template["id"],
				fp_chat_id=context.fp_chat_id,
			))
			keyboard.add(B(
				template["title"][:64],
				callback_data=f"{CBT_TEMPLATES_SELECT}{token}",
			))
		keyboard.add(B("❌ Закрыть", callback_data=f"{CBT_TEMPLATES_CANCEL}menu"))
		self.host.tgbot.reply_to(
			message,
			"<b>Заготовки сообщений</b>\n\n"
			f"Покупатель: <code>{escape(context.username)}</code>\n"
			"Выберите сообщение:",
			reply_markup=keyboard,
		)

	def select_template(self, call: telebot.types.CallbackQuery) -> None:
		token = call.data.replace(CBT_TEMPLATES_SELECT, "", 1)
		selection = self.selection_payloads.pop(token)
		self.host.tgbot.answer_callback_query(call.id)
		if not isinstance(selection, PendingTemplateSelection):
			self.expire_action(call)
			return

		template = self.find_template(selection.template_id)
		if not template:
			self.expire_action(call)
			return
		if not template["text"].strip():
			self.host.tgbot.edit_message_text(
				f"⚠️ Текст заготовки «{escape(template['title'])}» не заполнен.",
				call.message.chat.id,
				call.message.message_id,
				reply_markup=None,
			)
			return

		send_token = self.pending_sends.put(PendingTemplateSend(
			title=template["title"],
			text=template["text"],
			fp_chat_id=selection.fp_chat_id,
		))
		keyboard = K(row_width=2)
		keyboard.add(
			B("✅ Отправить", callback_data=f"{CBT_TEMPLATES_SEND}{send_token}"),
			B("❌ Отмена", callback_data=f"{CBT_TEMPLATES_CANCEL}{send_token}"),
		)
		self.host.tgbot.edit_message_text(
			f"<b>{escape(template['title'])}</b>\n\n"
			f"{escape(template['text'])}\n\n"
			"Отправить это сообщение покупателю?",
			call.message.chat.id,
			call.message.message_id,
			reply_markup=keyboard,
		)

	def confirm_send(self, call: telebot.types.CallbackQuery) -> None:
		token = call.data.replace(CBT_TEMPLATES_SEND, "", 1)
		pending = self.pending_sends.pop(token)
		self.host.tgbot.answer_callback_query(call.id)
		if not isinstance(pending, PendingTemplateSend):
			self.expire_action(call)
			return

		try:
			sent = self.host.cardinal.send_message(
				chat_id=pending.fp_chat_id,
				message_text=pending.text,
			)
			if sent is False:
				raise RuntimeError("Cardinal не подтвердил отправку.")
		except Exception as exc:
			self.host.tgbot.edit_message_text(
				f"<b>{escape(pending.title)}</b>\n\n"
				f"❌ Не удалось отправить сообщение:\n{escape(str(exc))}",
				call.message.chat.id,
				call.message.message_id,
				reply_markup=None,
			)
			return

		self.host.tgbot.edit_message_text(
			f"<b>{escape(pending.title)}</b>\n\n✅ Сообщение отправлено в чат.",
			call.message.chat.id,
			call.message.message_id,
			reply_markup=None,
		)

	def cancel_send(self, call: telebot.types.CallbackQuery) -> None:
		token = call.data.replace(CBT_TEMPLATES_CANCEL, "", 1)
		self.host.tgbot.answer_callback_query(call.id, "Отменено.")
		if token == "menu":
			self.host.tgbot.edit_message_text(
				"❌ Меню заготовок закрыто.",
				call.message.chat.id,
				call.message.message_id,
				reply_markup=None,
			)
			return

		pending = self.pending_sends.pop(token)
		if not isinstance(pending, PendingTemplateSend):
			self.expire_action(call)
			return

		self.host.tgbot.edit_message_text(
			f"<b>{escape(pending.title)}</b>\n\n❌ Отправка отменена.",
			call.message.chat.id,
			call.message.message_id,
			reply_markup=None,
		)

	def expire_action(self, call: telebot.types.CallbackQuery) -> None:
		self.host.tgbot.edit_message_text(
			"❌ Действие истекло. Откройте /templates заново.",
			call.message.chat.id,
			call.message.message_id,
			reply_markup=None,
		)

	def find_template(self, template_id: str) -> dict[str, str] | None:
		return next(
			(template for template in self.host.settings.get("templates", []) if template["id"] == template_id),
			None,
		)
