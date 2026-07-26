from __future__ import annotations

import io
import logging
import threading
from typing import Any

from ..config.constants import LOGGER_NAME, LOGGER_PREFIX, UUID
from ..runtime import call_external
from .formatting import escape, render_messages
from .service import BulkSyncAlreadyRunning, ChatSyncService
from .topics import parse_topic_name

try:
	from PIL import Image
except Exception:
	Image = None


logger = logging.getLogger(LOGGER_NAME)

MAX_UPLOAD_SIZE = 20 * 1024 * 1024
HISTORY_PREVIEW_DEPTH = 25

CHAT_SYNC_COMMANDS = [
	("setup_sync_chat", "Chat Sync: привязать группу-форум", True),
	("delete_sync_chat", "Chat Sync: отвязать группу", True),
	("sync_chats", "Chat Sync: создать темы для всех чатов", True),
	("watch", "Chat Sync: что смотрит собеседник", True),
	("history", "Chat Sync: последние сообщения чата", True),
	("full_history", "Chat Sync: полная история чата", True),
]


class TelegramChatSyncFlow:
	def __init__(self, host: Any, service: ChatSyncService):
		self.host = host
		self.service = service
		self._full_history_running = False

	@property
	def bot(self) -> Any:
		return self.host.tgbot

	def register(self) -> None:
		if not self.host.tg:
			return

		tg = self.host.tg
		self.host.cardinal.add_telegram_commands(UUID, CHAT_SYNC_COMMANDS)
		tg.msg_handler(self.cmd_setup_sync_chat, commands=["setup_sync_chat"])
		tg.msg_handler(self.cmd_delete_sync_chat, commands=["delete_sync_chat"])
		tg.msg_handler(self.cmd_sync_chats, commands=["sync_chats"])
		tg.msg_handler(self.cmd_watch, commands=["watch"])
		tg.msg_handler(self.cmd_history, commands=["history"])
		tg.msg_handler(self.cmd_full_history, commands=["full_history"])
		tg.msg_handler(
			self.forward_attachment,
			content_types=["photo", "document", "sticker"],
			func=self.is_outgoing_message,
		)
		tg.msg_handler(self.forward_message, func=self.is_outgoing_message)

	# Topic resolution

	def topic_chat_id(self, message: Any) -> str | None:
		service = self.service
		if not service.ready:
			return None
		if getattr(message.chat, "id", None) != service.telegram_chat_id:
			return None

		thread_id = getattr(message, "message_thread_id", None)
		if not isinstance(thread_id, int):
			return None
		return service.chat_id_for_thread(thread_id)

	def topic_username(self, chat_id: str) -> str:
		record = self.service.get_topic(chat_id)
		if record and record.username:
			return record.username
		if record and record.title:
			username, _ = parse_topic_name(record.title)
			if username:
				return username

		result = call_external(lambda: self.service.cardinal.account.get_chat(int(chat_id), with_history=False))
		return getattr(result.value, "name", "") or "" if result.succeeded else ""

	def is_outgoing_message(self, message: Any) -> bool:
		if is_command(message):
			return False
		return self.topic_chat_id(message) is not None

	def require_topic(self, message: Any) -> str | None:
		chat_id = self.topic_chat_id(message)
		if not chat_id:
			self.bot.reply_to(message, "❌ Эту команду нужно вводить в теме синхронизированного чата.")
			return None
		return chat_id

	# Outgoing messages

	def forward_message(self, message: Any) -> None:
		chat_id = self.topic_chat_id(message)
		if not chat_id:
			return

		text = message.text or message.caption or ""
		if not text.strip():
			return

		username = self.topic_username(chat_id)
		if not self.service.send_to_funpay(chat_id, username, text):
			self.bot.reply_to(
				message,
				f"❌ Не удалось отправить сообщение в чат "
				f"<a href='https://funpay.com/chat/?node={chat_id}'>{escape(username or chat_id)}</a>.",
			)

	def forward_attachment(self, message: Any) -> None:
		chat_id = self.topic_chat_id(message)
		if not chat_id:
			return

		username = self.topic_username(chat_id)
		if message.caption:
			self.service.send_to_funpay(chat_id, username, message.caption)

		attachment = self.pick_attachment(message)
		if attachment is None:
			return
		if (getattr(attachment, "file_size", 0) or 0) >= MAX_UPLOAD_SIZE:
			self.bot.reply_to(message, "❌ Размер файла не должен превышать 20 МБ.")
			return

		payload = self.download(attachment)
		if payload is None:
			self.bot.reply_to(message, "❌ Не удалось скачать файл из Telegram.")
			return

		if not self.service.send_image_to_funpay(chat_id, username, payload):
			self.bot.reply_to(
				message,
				f"❌ Не удалось отправить изображение в чат "
				f"<a href='https://funpay.com/chat/?node={chat_id}'>{escape(username or chat_id)}</a>.",
			)

	def pick_attachment(self, message: Any) -> Any:
		if getattr(message, "photo", None):
			return message.photo[-1]
		return getattr(message, "document", None) or getattr(message, "sticker", None)

	def download(self, attachment: Any) -> bytes | None:
		result = call_external(lambda: self.bot.get_file(attachment.file_id))
		if not result.succeeded:
			logger.warning(f"{LOGGER_PREFIX} Failed to resolve Telegram file: {result.error}")
			return None

		file_path = getattr(result.value, "file_path", "") or ""
		downloaded = call_external(lambda: self.bot.download_file(file_path))
		if not downloaded.succeeded:
			logger.warning(f"{LOGGER_PREFIX} Failed to download Telegram file: {downloaded.error}")
			return None

		payload = downloaded.value
		return convert_webp(payload) if file_path.endswith(".webp") else payload

	# Commands

	def cmd_setup_sync_chat(self, message: Any) -> None:
		chat = message.chat
		if getattr(chat, "id", None) == getattr(message.from_user, "id", None):
			self.bot.reply_to(message, "❌ Эту команду нужно вводить в группе, а не в личных сообщениях.")
			return
		if not getattr(chat, "is_forum", False):
			self.bot.reply_to(message, "❌ Группа должна быть переведена в режим тем (Topics).")
			return

		previous = self.service.telegram_chat_id
		self.set_chat_id(chat.id)
		if previous and previous != chat.id:
			self.reset_topics()
			self.bot.send_message(chat.id, "✅ Группа заменена. Прежние связки тем сброшены.")
			return

		self.bot.send_message(
			chat.id,
			"✅ Группа для синхронизации FunPay чатов установлена.\n\n"
			"Дальше: /sync_chats - создать темы для существующих чатов.",
		)

	def cmd_delete_sync_chat(self, message: Any) -> None:
		if not self.service.telegram_chat_id:
			self.bot.reply_to(message, "❌ Группа для синхронизации не привязана.")
			return

		self.set_chat_id(None)
		self.reset_topics()
		self.bot.reply_to(message, "✅ Группа отвязана, связки тем сброшены.")

	def cmd_sync_chats(self, message: Any) -> None:
		if not self.service.ready:
			self.bot.reply_to(message, "❌ Chat Sync не готов. Проверьте настройки плагина.")
			return
		if self.service.bulk_sync_running:
			self.bot.reply_to(message, "❌ Синхронизация уже запущена, дождитесь окончания.")
			return

		notice = self.bot.reply_to(message, "⏳ Синхронизирую чаты...")
		threading.Thread(target=self.run_sync, args=(notice,), daemon=True).start()

	def run_sync(self, notice: Any) -> None:
		try:
			created = self.service.run_bulk_sync()
			text = f"✅ Синхронизация завершена. Создано тем: <b>{created}</b>."
		except BulkSyncAlreadyRunning:
			text = "❌ Синхронизация уже запущена."
		except Exception as exc:
			logger.error(f"{LOGGER_PREFIX} Bulk sync failed: {exc}")
			logger.debug("TRACEBACK", exc_info=True)
			text = "❌ Синхронизация завершилась с ошибкой."
		self.edit(notice, text)

	def cmd_watch(self, message: Any) -> None:
		chat_id = self.require_topic(message)
		if not chat_id:
			return
		threading.Thread(target=self.show_watch, args=(message, chat_id), daemon=True).start()

	def show_watch(self, message: Any, chat_id: str) -> None:
		username = self.topic_username(chat_id)
		result = call_external(lambda: self.service.cardinal.account.get_chat(int(chat_id), with_history=False))
		if not result.succeeded:
			self.bot.reply_to(message, f"❌ Не удалось получить данные чата с {escape(username or chat_id)}.")
			return

		text = getattr(result.value, "looking_text", "") or ""
		link = getattr(result.value, "looking_link", "") or ""
		if text and link:
			self.bot.reply_to(message, f'<b><i>Смотрит: </i></b> <a href="{link}">{escape(text)}</a>')
			return
		self.bot.reply_to(message, f"<b>Пользователь <code>{escape(username or chat_id)}</code> ничего не смотрит.</b>")

	def cmd_history(self, message: Any) -> None:
		chat_id = self.require_topic(message)
		if not chat_id:
			return
		threading.Thread(target=self.show_history, args=(message, chat_id), daemon=True).start()

	def show_history(self, message: Any, chat_id: str) -> None:
		username = self.topic_username(chat_id)
		history = self.service.load_history(chat_id, username, HISTORY_PREVIEW_DEPTH)
		if not history:
			self.bot.reply_to(message, f"ℹ️ История чата с {escape(username or chat_id)} пуста.")
			return
		self.post_history(message, chat_id, history)

	def cmd_full_history(self, message: Any) -> None:
		chat_id = self.require_topic(message)
		if not chat_id:
			return
		if self._full_history_running:
			self.bot.reply_to(message, "❌ Получение истории уже запущено, дождитесь окончания.")
			return
		threading.Thread(target=self.show_full_history, args=(message, chat_id), daemon=True).start()

	def show_full_history(self, message: Any, chat_id: str) -> None:
		self._full_history_running = True
		try:
			username = self.topic_username(chat_id)
			notice = self.bot.reply_to(message, "⏳ Читаю полную историю чата, это может занять время...")
			history = self.service.load_full_history(chat_id, username)
			if not history:
				self.edit(notice, f"ℹ️ История чата с {escape(username or chat_id)} пуста.")
				return

			self.post_history(message, chat_id, history)
			self.edit(notice, f"✅ Готово. Сообщений: <b>{len(history)}</b>.")
		finally:
			self._full_history_running = False

	def post_history(self, message: Any, chat_id: str, history: list[Any]) -> None:
		record = self.service.get_topic(chat_id)
		if not record:
			return
		for chunk in render_messages(history, self.service.render_options()):
			self.service.send_text(chat_id, record.thread_id, chunk.text, disable_notification=True)

	# Settings helpers

	def set_chat_id(self, chat_id: int | None) -> None:
		self.host.update_settings(lambda settings: settings["chat_sync"].__setitem__("chat_id", chat_id))

	def reset_topics(self) -> None:
		self.service.clear_topics()

	def edit(self, notice: Any, text: str) -> None:
		if not notice:
			return
		call_external(lambda: self.bot.edit_message_text(text, notice.chat.id, notice.message_id))


def is_command(message: Any) -> bool:
	for entity in getattr(message, "entities", None) or ():
		if getattr(entity, "type", "") == "bot_command" and getattr(entity, "offset", None) == 0:
			return True
	return False


def convert_webp(payload: bytes) -> bytes:
	if Image is None:
		return payload
	try:
		source = Image.open(io.BytesIO(payload))
		target = Image.new("RGB", source.size, (255, 255, 255))
		target.paste(source, (0, 0), mask=source.convert("RGBA").split()[3])
		buffer = io.BytesIO()
		target.save(buffer, format="JPEG")
		return buffer.getvalue()
	except Exception:
		logger.debug("TRACEBACK", exc_info=True)
		return payload
