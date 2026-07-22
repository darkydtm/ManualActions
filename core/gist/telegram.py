from __future__ import annotations

from dataclasses import dataclass
from html import escape as html_escape
from secrets import token_urlsafe
from typing import TYPE_CHECKING, Any, Protocol

import telebot
from telebot.types import InlineKeyboardButton as B, InlineKeyboardMarkup as K

from ..config.constants import (
	CBT_GIST_ORDER_CANCEL,
	CBT_GIST_ORDER_SELECT,
	CBT_GIST_SEND,
	CBT_GIST_SKIP_SEND,
)
from ..funpay.chat_sync import TopicContext, get_topic_context, is_in_sync_chat
from ..funpay.orders import format_order_price, get_pending_orders_for_user
from ..runtime import ExternalResult, call_external
from .service import (
	create_gist_result,
	gist_config_errors,
	gist_error_text,
	resolve_gist_filename,
)
from .settings import normalize_gist_settings

if TYPE_CHECKING:
	from cardinal import Cardinal


class GistCommandHost(Protocol):
	tg: object
	tgbot: telebot.TeleBot
	cardinal: Cardinal
	settings: dict[str, Any]


@dataclass(frozen=True)
class PendingGistRequest:
	text: str
	context: TopicContext
	order_ids: tuple[str, ...]


@dataclass(frozen=True)
class PendingGistResult:
	url: str
	fp_chat_id: int


class TelegramGistFlow:
	def __init__(self, host: GistCommandHost):
		self.host = host
		self.pending_requests: dict[str, PendingGistRequest] = {}
		self.pending_results: dict[str, PendingGistResult] = {}

	def register(self) -> None:
		self.host.tg.msg_handler(self.cmd_gist, commands=["gist"])
		self.host.tg.cbq_handler(
			self.select_order,
			lambda c: (c.data or "").startswith(CBT_GIST_ORDER_SELECT),
		)
		self.host.tg.cbq_handler(
			self.cancel_order_selection,
			lambda c: (c.data or "").startswith(CBT_GIST_ORDER_CANCEL),
		)
		self.host.tg.cbq_handler(
			self.send_result,
			lambda c: (c.data or "").startswith(CBT_GIST_SEND),
		)
		self.host.tg.cbq_handler(
			self.skip_result,
			lambda c: (c.data or "").startswith(CBT_GIST_SKIP_SEND),
		)

	def cmd_gist(self, message: telebot.types.Message) -> None:
		gist_settings = self.host.settings.get("gist", {})
		config = normalize_gist_settings(gist_settings)
		request = gist_request_from_message(message, config["filename"]["mode"] == "order_id")
		if not request.text:
			self.host.tgbot.reply_to(
				message,
				"⚠️ Использование: /gist <текст>\n"
				"Или ответьте командой /gist на сообщение с текстом.",
			)
			return

		if config["filename"]["mode"] == "order_id" and not request.order_id and is_in_sync_chat(message):
			self.start_order_selection(message, gist_settings, request.text)
			return

		config_errors = gist_config_errors(gist_settings, request.order_id)
		if config_errors:
			self.host.tgbot.reply_to(message, self.format_config_errors(config_errors))
			return

		wait_message = self.host.tgbot.reply_to(message, "⏳ Создаю GitHub Gist...")
		try:
			context = self.chat_sync_context(message)
			username = context.username if context else None
			filename = resolve_gist_filename(gist_settings, username, request.order_id)
			result = create_gist_result(gist_settings, request.text, filename=filename)
		except Exception as exc:
			self.edit_message(
				f"❌ {html_escape(gist_error_text(exc))}",
				wait_message.chat.id,
				wait_message.message_id,
			)
			return

		self.show_result(wait_message, result.url, context)

	def start_order_selection(
		self,
		message: telebot.types.Message,
		gist_settings: dict[str, Any],
		text: str,
	) -> None:
		context = get_topic_context(self.host.cardinal, message)
		if not context:
			self.host.tgbot.reply_to(message, "❌ Не удалось определить пользователя из топика.")
			return

		config_errors = gist_config_errors(gist_settings, "pending")
		if config_errors:
			self.host.tgbot.reply_to(message, self.format_config_errors(config_errors))
			return

		wait_message = self.host.tgbot.reply_to(message, f"⏳ Получаю список заказов {context.username}...")
		orders = get_pending_orders_for_user(self.host.cardinal, context.username)
		if not orders:
			self.edit_message(
				f"ℹ️ У {html_escape(context.username)} нет неподтверждённых заказов.",
				wait_message.chat.id,
				wait_message.message_id,
			)
			return

		orders = orders[:10]
		token = token_urlsafe(8)
		self.pending_requests[token] = PendingGistRequest(
			text=text,
			context=context,
			order_ids=tuple(str(getattr(order, "id", "")) for order in orders),
		)
		keyboard = K(row_width=1)
		for order in orders:
			order_id = str(getattr(order, "id", ""))
			keyboard.add(B(
				self.format_order_button(order),
				callback_data=f"{CBT_GIST_ORDER_SELECT}{token}:{order_id}",
			))
		keyboard.add(B("❌ Отмена", callback_data=f"{CBT_GIST_ORDER_CANCEL}{token}"))
		self.edit_message(
			f"📝 Выберите заказ для имени файла ({html_escape(context.username)}):",
			wait_message.chat.id,
			wait_message.message_id,
			reply_markup=keyboard,
		)

	def select_order(self, call: telebot.types.CallbackQuery) -> None:
		payload = call.data.replace(CBT_GIST_ORDER_SELECT, "", 1)
		token, separator, order_id = payload.partition(":")
		request = self.pending_requests.pop(token, None)
		self.host.tgbot.answer_callback_query(call.id)
		if not request or not separator or order_id not in request.order_ids:
			self.edit_message(
				"❌ Запрос выбора заказа истёк.",
				call.message.chat.id,
				call.message.message_id,
				reply_markup=None,
			)
			return

		self.create_from_request(call.message, request, order_id)

	def cancel_order_selection(self, call: telebot.types.CallbackQuery) -> None:
		token = call.data.replace(CBT_GIST_ORDER_CANCEL, "", 1)
		self.pending_requests.pop(token, None)
		self.host.tgbot.answer_callback_query(call.id, "Отменено.")
		self.edit_message(
			"❌ Выбор заказа отменён.",
			call.message.chat.id,
			call.message.message_id,
			reply_markup=None,
		)

	def create_from_request(
		self,
		message: telebot.types.Message,
		request: PendingGistRequest,
		order_id: str,
	) -> None:
		gist_settings = self.host.settings.get("gist", {})
		try:
			filename = resolve_gist_filename(gist_settings, order_id=order_id)
			result = create_gist_result(gist_settings, request.text, filename=filename)
		except Exception as exc:
			self.edit_message(
				f"❌ {html_escape(gist_error_text(exc))}",
				message.chat.id,
				message.message_id,
				reply_markup=None,
			)
			return

		self.show_result(message, result.url, request.context)

	def show_result(
		self,
		message: telebot.types.Message,
		url: str,
		context: TopicContext | None = None,
	) -> None:
		keyboard = None
		if context:
			token = token_urlsafe(8)
			self.pending_results[token] = PendingGistResult(url=url, fp_chat_id=context.fp_chat_id)
			keyboard = K(row_width=2)
			keyboard.add(
				B("📤 Отправить в чат", callback_data=f"{CBT_GIST_SEND}{token}"),
				B("❌ Не отправлять", callback_data=f"{CBT_GIST_SKIP_SEND}{token}"),
			)

		self.edit_message(
			self.format_result(url),
			message.chat.id,
			message.message_id,
			disable_web_page_preview=True,
			reply_markup=keyboard,
		)

	def send_result(self, call: telebot.types.CallbackQuery) -> None:
		token = call.data.replace(CBT_GIST_SEND, "", 1)
		result = self.pending_results.pop(token, None)
		self.host.tgbot.answer_callback_query(call.id)
		if not result:
			self.expire_result(call)
			return

		send_result = call_external(
			lambda: self.host.cardinal.send_message(chat_id=result.fp_chat_id, message_text=result.url),
		)
		if send_result.succeeded and send_result.value is False:
			send_result = ExternalResult(False, error="Cardinal не подтвердил отправку.")
		if not send_result.succeeded:
			self.edit_message(
				f"{self.format_result(result.url)}\n\n❌ Не удалось отправить ссылку в чат: {html_escape(send_result.error)}",
				call.message.chat.id,
				call.message.message_id,
				disable_web_page_preview=True,
				reply_markup=None,
			)
			return

		self.edit_message(
			f"{self.format_result(result.url)}\n\n✅ Ссылка отправлена в чат.",
			call.message.chat.id,
			call.message.message_id,
			disable_web_page_preview=True,
			reply_markup=None,
		)

	def skip_result(self, call: telebot.types.CallbackQuery) -> None:
		token = call.data.replace(CBT_GIST_SKIP_SEND, "", 1)
		result = self.pending_results.pop(token, None)
		self.host.tgbot.answer_callback_query(call.id, "Не отправлено.")
		if not result:
			self.expire_result(call)
			return

		self.edit_message(
			f"{self.format_result(result.url)}\n\nℹ️ Ссылка не отправлена.",
			call.message.chat.id,
			call.message.message_id,
			disable_web_page_preview=True,
			reply_markup=None,
		)

	def expire_result(self, call: telebot.types.CallbackQuery) -> None:
		text = getattr(call.message, "text", None) or "✅ GitHub Gist создан."
		self.edit_message(
			f"{text}\n\n❌ Действие истекло.",
			call.message.chat.id,
			call.message.message_id,
			reply_markup=None,
		)

	def format_order_button(self, order: object) -> str:
		order_id = str(getattr(order, "id", ""))
		return f"#{order_id} - {format_order_price(order)}"

	def edit_message(self, *args, **kwargs) -> None:
		call_external(lambda: self.host.tgbot.edit_message_text(*args, **kwargs))

	def chat_sync_context(self, message: telebot.types.Message) -> TopicContext | None:
		if not is_in_sync_chat(message):
			return None
		return get_topic_context(self.host.cardinal, message)

	def format_result(self, url: str) -> str:
		return f"✅ GitHub Gist:\n{html_escape(url)}"

	def format_config_errors(self, errors: list[str]) -> str:
		lines = ["❌ GitHub Gists не настроен:"]
		lines.extend(f"• {html_escape(error)}" for error in errors)
		return "\n".join(lines)


@dataclass(frozen=True)
class GistRequest:
	text: str
	order_id: str = ""


def gist_text_from_message(message: telebot.types.Message) -> str:
	return gist_request_from_message(message, False).text


def gist_request_from_message(message: telebot.types.Message, extract_order_id: bool = False) -> GistRequest:
	reply = getattr(message, "reply_to_message", None)
	command_text = getattr(message, "text", None) or ""
	command_args = command_text.split(maxsplit=1)
	command_body = command_args[1].strip() if len(command_args) > 1 else ""
	order_id = ""

	if extract_order_id and command_body:
		order_id, command_body = split_order_id_prefix(command_body)

	if reply:
		reply_text = text_from_telegram_message(reply)
		if reply_text.strip():
			return GistRequest(reply_text, order_id)

	return GistRequest(command_body, order_id)


def split_order_id_prefix(text: str) -> tuple[str, str]:
	parts = text.split(maxsplit=1)
	if not parts:
		return "", ""

	if not parts[0].startswith("#"):
		return "", text.strip()

	candidate = parts[0].lstrip("#").strip()
	if not is_order_id(candidate):
		return "", text.strip()
	rest = parts[1].strip() if len(parts) > 1 else ""
	return candidate, rest


def is_order_id(value: str) -> bool:
	return bool(value) and value.isalnum()


def text_from_telegram_message(message: telebot.types.Message) -> str:
	for attr in ("text", "caption"):
		value = getattr(message, attr, None)
		if isinstance(value, str):
			return value
	return ""
