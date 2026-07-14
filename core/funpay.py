from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .status import auto_message_text, parse_funpay_status_command

try:
	from FunPayAPI.types import MessageTypes
	from FunPayAPI.updater.events import LastChatMessageChangedEvent
except Exception:
	MessageTypes = None
	LastChatMessageChangedEvent = None

if TYPE_CHECKING:
	from cardinal import Cardinal


@dataclass(frozen=True)
class MessageContext:
	text: str
	chat_id: int | str
	chat_name: str | None
	author: str | None
	is_seller: bool
	is_bot: bool = False
	is_system: bool = False


def extract_message_context(c: Cardinal, e: object) -> MessageContext | None:
	if not c.old_mode_enabled:
		if LastChatMessageChangedEvent is not None and isinstance(e, LastChatMessageChangedEvent):
			return None

		message = e.message
		if not is_non_system(getattr(message, "type", None)):
			return None

		text = getattr(message, "text", None)
		if text is None:
			return None

		author_id = getattr(message, "author_id", None)
		is_seller = str(author_id) == str(c.account.id) and getattr(message, "badge", None) is None

		return MessageContext(
			text=text,
			chat_id=message.chat_id,
			chat_name=getattr(message, "chat_name", None),
			author=getattr(message, "author", None),
			is_seller=is_seller,
			is_bot=bool(getattr(message, "by_bot", False)),
		)

	chat = e.chat
	if not is_non_system(getattr(chat, "last_message_type", None)):
		return None

	text = getattr(chat, "last_message_text", None)
	if text is None:
		return None

	return MessageContext(
		text=text,
		chat_id=chat.id,
		chat_name=getattr(chat, "name", None),
		author=getattr(chat, "name", None),
		is_seller=not getattr(chat, "unread", False),
	)


def is_non_system(message_type: object) -> bool:
	if MessageTypes is None:
		return True
	return message_type == MessageTypes.NON_SYSTEM


def should_send_auto_status_message(context: MessageContext, settings: dict) -> bool:
	if context.is_system or context.is_seller or context.is_bot:
		return False
	if parse_funpay_status_command(context.text):
		return False
	return bool(auto_message_text(settings))
