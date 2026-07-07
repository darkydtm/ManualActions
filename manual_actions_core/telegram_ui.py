from __future__ import annotations

from typing import Any


def delete_controlled_message(bot: Any, message: Any) -> None:
	if not message:
		return
	try:
		bot.delete_message(message.chat.id, message.id)
	except Exception:
		pass


def message_thread_id(source: Any) -> int | None:
	thread_id = getattr(source, "message_thread_id", None)
	if thread_id is not None:
		return thread_id
	message = getattr(source, "message", None)
	return getattr(message, "message_thread_id", None)


def send_menu(bot: Any, chat_id: int, text: str, keyboard: Any, thread_id: int | None = None) -> Any:
	kwargs = {"reply_markup": keyboard}
	if thread_id is not None:
		kwargs["message_thread_id"] = thread_id
	return bot.send_message(chat_id, text, **kwargs)
