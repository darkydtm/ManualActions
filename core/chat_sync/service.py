from __future__ import annotations

from collections.abc import Callable, Sequence
import logging
import threading
import time
from typing import TYPE_CHECKING, Any

from ..config.constants import LOGGER_NAME, LOGGER_PREFIX, UUID
from ..runtime import KeyedLockRegistry, call_external
from .dispatcher import ChatSyncQueue, TelegramRateLimiter, TelegramSender, is_missing_thread_error
from .formatting import (
	RenderOptions,
	RenderedChunk,
	SPECIAL_SYMBOL,
	admin_tags,
	escape,
	render_messages,
)
from .registry import set_active_service
from .settings import DEFAULT_CHAT_SYNC_SETTINGS
from .storage import ChatSyncStorage, TopicRecord
from .topics import DEFAULT_TOPIC_ICON, OrderStats, collect_order_stats, format_topic_name, topic_icon

if TYPE_CHECKING:
	from cardinal import Cardinal


logger = logging.getLogger(LOGGER_NAME)

ORDER_EVENT_TYPES = frozenset({
	"REFUND",
	"REFUND_BY_ADMIN",
	"PARTIAL_REFUND",
	"ORDER_PURCHASED",
	"ORDER_CONFIRMED",
	"ORDER_CONFIRMED_BY_ADMIN",
	"ORDER_REOPENED",
})

ARBITRATION_WORDS = ("арбитраж", "арбітраж", "arbitration")

BUYER_VIEWING_INTERVAL = 24 * 3600
RATE_LIMIT_COOLDOWN = 5 * 60


class BulkSyncAlreadyRunning(RuntimeError):
	pass


def message_type_name(message: Any) -> str:
	return str(getattr(getattr(message, "type", None), "name", "") or "")


def is_order_event(message: Any) -> bool:
	return message_type_name(message) in ORDER_EVENT_TYPES


def stack_events(event: Any) -> list[Any]:
	stack = getattr(event, "stack", None)
	getter = getattr(stack, "get_stack", None)
	if callable(getter):
		try:
			events = list(getter() or ())
		except Exception:
			events = []
		if events:
			return events
	return [event]


def group_by_chat(messages: Sequence[Any]) -> list[tuple[str, str, list[Any]]]:
	grouped: dict[str, tuple[str, list[Any]]] = {}
	for message in messages:
		chat_id = getattr(message, "chat_id", None)
		if chat_id is None:
			continue
		name, batch = grouped.setdefault(str(chat_id), (getattr(message, "chat_name", "") or "", []))
		batch.append(message)
	return [(chat_id, name, batch) for chat_id, (name, batch) in grouped.items()]


def stack_identifier(event: Any) -> str:
	identifier = getattr(getattr(event, "stack", None), "id", None)
	if not callable(identifier):
		return ""
	try:
		return str(identifier())
	except Exception:
		return ""


class ChatSyncService:
	def __init__(self, host: Any, storage: ChatSyncStorage | None = None, sender: TelegramSender | None = None):
		self.host = host
		self.cardinal = host.cardinal
		self.storage = storage or ChatSyncStorage()
		self.limiter = TelegramRateLimiter()
		self.sender = sender or TelegramSender(self.limiter)
		self.queue = ChatSyncQueue()
		self.locks = KeyedLockRegistry()

		self.topics: dict[str, TopicRecord] = {}
		self._reversed: dict[int, str] = {}
		self._topics_lock = threading.RLock()
		self._last_stack_id = ""
		self._last_attribution_id = ""
		self._initial_sync_done = False
		self._bulk_sync_running = False
		self._viewing_seen: dict[str, float] = {}
		self._refreshing: set[str] = set()

		setattr(ChatSyncService.handle_new_message, "plugin_uuid", UUID)
		setattr(ChatSyncService.handle_new_order, "plugin_uuid", UUID)
		setattr(ChatSyncService.handle_initial_chat, "plugin_uuid", UUID)
		setattr(ChatSyncService.mark_own_messages, "plugin_uuid", UUID)

	# Lifecycle

	def load(self) -> None:
		self.topics = self.storage.load()
		self._reversed = {record.thread_id: key for key, record in self.topics.items()}
		self.limiter.configure(self.config.get("messages_per_minute", 20))
		set_active_service(self)
		logger.info(f"{LOGGER_PREFIX} Chat Sync loaded {len(self.topics)} topics.")

	def register_funpay(self) -> None:
		self.cardinal.new_message_handlers.insert(0, self.mark_own_messages)
		self.cardinal.new_message_handlers.append(self.handle_new_message)
		self.cardinal.new_order_handlers.append(self.handle_new_order)
		init_handlers = getattr(self.cardinal, "init_message_handlers", None)
		if isinstance(init_handlers, list):
			init_handlers.append(self.handle_initial_chat)

	def shutdown(self) -> None:
		self.queue.stop()
		set_active_service(None)

	# Configuration

	@property
	def config(self) -> dict[str, Any]:
		config = self.host.settings.get("chat_sync")
		return config if isinstance(config, dict) else dict(DEFAULT_CHAT_SYNC_SETTINGS)

	@property
	def settings(self) -> dict[str, Any]:
		return self.config

	@property
	def bot(self) -> Any:
		return getattr(self.host, "tgbot", None)

	@property
	def telegram_chat_id(self) -> int | None:
		chat_id = self.config.get("chat_id")
		return chat_id if isinstance(chat_id, int) else None

	@property
	def ready(self) -> bool:
		return bool(
			self.config.get("enabled")
			and self.telegram_chat_id
			and self.bot
			and not getattr(self.cardinal, "old_mode_enabled", False)
		)

	@property
	def threads(self) -> dict[str, int]:
		with self._topics_lock:
			return {key: record.thread_id for key, record in self.topics.items()}

	@property
	def reversed_threads(self) -> dict[int, str]:
		with self._topics_lock:
			return dict(self._reversed)

	@property
	def threads_info(self) -> dict[int, tuple[str, str]]:
		with self._topics_lock:
			return {
				record.thread_id: (record.icon, record.title or format_topic_name(record.username, key))
				for key, record in self.topics.items()
			}

	def render_options(self) -> RenderOptions:
		config = self.config
		return RenderOptions(
			account_id=getattr(getattr(self.cardinal, "account", None), "id", None),
			blacklist=tuple(getattr(self.cardinal, "blacklist", None) or ()),
			chat_url=bool(config.get("chat_url")),
			mono=bool(config.get("mono")),
			show_ads=bool(config.get("show_ads")),
			show_image_name=bool(config.get("show_image_name")),
			hide_watermark=bool(config.get("hide_watermark")),
			watermark=self.watermark(),
		)

	def watermark(self) -> str:
		try:
			return self.cardinal.MAIN_CFG["Other"].get("watermark", "") or ""
		except Exception:
			return ""

	def admin_ids(self) -> list[Any]:
		getter = getattr(self.host, "telegram_admin_ids", None)
		if callable(getter):
			return list(getter() or ())
		return []

	# Topics

	def get_topic(self, chat_id: int | str) -> TopicRecord | None:
		with self._topics_lock:
			return self.topics.get(str(chat_id))

	def chat_id_for_thread(self, thread_id: int) -> str | None:
		with self._topics_lock:
			return self._reversed.get(thread_id)

	def ensure_topic(self, chat_id: int | str, username: str = "", backfill: bool = True) -> TopicRecord | None:
		if not self.ready:
			return None

		key = str(chat_id)
		record = self.get_topic(key)
		if record:
			return record

		# Serialize per chat so concurrent events cannot create two topics for one chat.
		with self.locks.lock_for(key):
			record = self.get_topic(key)
			if record:
				return record
			return self.create_topic(key, username, backfill)

	def create_topic(self, key: str, username: str, backfill: bool) -> TopicRecord | None:
		bot = self.bot
		chat_id = self.telegram_chat_id
		if not bot or not chat_id:
			return None

		title = format_topic_name(username, key)
		result = self.sender.call(lambda: bot.create_forum_topic(
			chat_id,
			title,
			icon_custom_emoji_id=DEFAULT_TOPIC_ICON,
		))
		if not result.succeeded:
			logger.error(f"{LOGGER_PREFIX} Failed to create topic for chat {key}: {result.error}")
			return None

		thread_id = getattr(result.value, "message_thread_id", None)
		if not isinstance(thread_id, int):
			logger.error(f"{LOGGER_PREFIX} Telegram returned no thread id for chat {key}.")
			return None

		record = TopicRecord(thread_id=thread_id, username=str(username or ""), title=title, icon=DEFAULT_TOPIC_ICON)
		with self._topics_lock:
			self.topics[key] = record
			self._reversed[thread_id] = key
		self.save_topics()
		logger.info(f"{LOGGER_PREFIX} Linked FunPay chat {username} ({key}) to topic {thread_id}.")

		self.send_topic_header(key, record)
		if backfill:
			self.backfill_history(key, record)
		return record

	def drop_topic(self, chat_id: int | str) -> None:
		key = str(chat_id)
		with self._topics_lock:
			record = self.topics.pop(key, None)
			if record:
				self._reversed.pop(record.thread_id, None)
		if record:
			logger.warning(f"{LOGGER_PREFIX} Topic {record.thread_id} for chat {key} is gone, unlinked.")
			self.save_topics()

	def clear_topics(self) -> None:
		with self._topics_lock:
			self.topics.clear()
			self._reversed.clear()
		self.save_topics()

	def save_topics(self) -> None:
		with self._topics_lock:
			snapshot = dict(self.topics)
		self.storage.save(snapshot)

	def send_topic_header(self, key: str, record: TopicRecord) -> None:
		username = record.username or key
		text = (
			f"<a href='https://funpay.com/chat/?node={key}'>{escape(username)}</a>\n\n"
			f"<a href='https://funpay.com/orders/trade?buyer={escape(username)}'>Продажи</a> | "
			f"<a href='https://funpay.com/orders/?seller={escape(username)}'>Покупки</a>"
		)
		self.send_text(key, record.thread_id, text, disable_notification=True)

	# Sending

	def send_text(self, key: str, thread_id: int, text: str, disable_notification: bool = False) -> bool:
		bot = self.bot
		chat_id = self.telegram_chat_id
		if not bot or not chat_id or not text:
			return False

		result = self.sender.call(lambda: bot.send_message(
			chat_id,
			text,
			message_thread_id=thread_id,
			disable_notification=disable_notification,
		))
		if result.succeeded:
			return True

		logger.error(f"{LOGGER_PREFIX} Failed to send message to topic {thread_id}: {result.error}")
		if is_missing_thread_error(result.error):
			self.drop_topic(key)
		return False

	def send_chunk(self, key: str, thread_id: int, chunk: RenderedChunk) -> bool:
		text = chunk.text
		if chunk.tag_admins:
			text += admin_tags(self.admin_ids())
		silent = bool(chunk.only_self and not self.config.get("self_notify", True))
		return self.send_text(key, thread_id, text, disable_notification=silent)

	# FunPay handlers

	def mark_own_messages(self, c: Cardinal, e: Any) -> None:
		"""Strip the outgoing marker and flag messages this plugin sent from Telegram."""
		identifier = stack_identifier(e)
		if identifier and identifier == self._last_attribution_id:
			return
		self._last_attribution_id = identifier

		account_id = getattr(getattr(c, "account", None), "id", None)
		for event in stack_events(e):
			message = getattr(event, "message", None)
			text = getattr(message, "text", None)
			if not text or not text.startswith(SPECIAL_SYMBOL):
				continue
			message.text = text.replace(SPECIAL_SYMBOL, "")
			if account_id is not None and str(getattr(message, "author_id", None)) == str(account_id):
				setattr(event, "sync_ignore", True)

	def handle_new_message(self, c: Cardinal, e: Any) -> None:
		if not self.ready:
			return

		identifier = stack_identifier(e)
		if identifier and identifier == self._last_stack_id:
			return
		self._last_stack_id = identifier

		messages = [
			event.message
			for event in stack_events(e)
			if getattr(event, "message", None) is not None and not getattr(event, "sync_ignore", False)
		]
		# A stack is normally one chat, but never mirror one buyer's messages into another buyer's topic.
		for chat_id, chat_name, chat_messages in group_by_chat(messages):
			self.queue.submit(
				lambda key=chat_id, name=chat_name, batch=chat_messages: self.deliver(key, name, batch)
			)

	def handle_new_order(self, c: Cardinal, e: Any) -> None:
		if not self.ready:
			return

		buyer = getattr(getattr(e, "order", None), "buyer_username", "") or ""
		if not buyer:
			return
		if self.find_topic_by_username(buyer):
			return

		self.queue.submit(lambda: self.ensure_topic_for_username(buyer))

	def handle_initial_chat(self, c: Cardinal, e: Any) -> None:
		if self._initial_sync_done or not self.ready or not self.config.get("sync_on_start"):
			return
		self._initial_sync_done = True
		threading.Thread(target=self.run_bulk_sync, name="manual-actions-chat-sync-init", daemon=True).start()

	def ensure_topic_for_username(self, username: str) -> TopicRecord | None:
		result = call_external(lambda: self.cardinal.account.get_chat_by_name(username, True))
		chat = result.value if result.succeeded else None
		chat_id = getattr(chat, "id", None)
		if chat_id is None:
			logger.warning(f"{LOGGER_PREFIX} Could not resolve FunPay chat for {username}.")
			return None
		return self.ensure_topic(chat_id, getattr(chat, "name", username) or username)

	def find_topic_by_username(self, username: str) -> TopicRecord | None:
		target = str(username or "").strip().casefold()
		if not target:
			return None
		with self._topics_lock:
			for record in self.topics.values():
				if record.username.casefold() == target:
					return record
		return None

	# Delivery

	def deliver(self, chat_id: int | str, chat_name: str, messages: Sequence[Any]) -> None:
		key = str(chat_id)
		record = self.ensure_topic(key, chat_name)
		if not record:
			return

		fresh = [message for message in messages if self.is_new_message(record, message)]
		if not fresh:
			return

		chunks = render_messages(
			fresh,
			self.render_options(),
			tag_admins=self.should_tag_admins(fresh),
			prefix=self.buyer_viewing_prefix(fresh[0]),
		)
		for chunk in chunks:
			self.send_chunk(key, record.thread_id, chunk)

		self.remember_last_message(key, fresh)
		self.schedule_topic_refresh(key, chat_name, fresh)

	def is_new_message(self, record: TopicRecord, message: Any) -> bool:
		message_id = getattr(message, "id", None)
		if isinstance(message_id, bool) or not isinstance(message_id, int):
			return True
		return message_id > record.last_message_id

	def remember_last_message(self, key: str, messages: Sequence[Any]) -> None:
		ids = [
			getattr(message, "id", None)
			for message in messages
			if isinstance(getattr(message, "id", None), int) and not isinstance(getattr(message, "id", None), bool)
		]
		if not ids:
			return

		newest = max(ids)
		with self._topics_lock:
			record = self.topics.get(key)
			if not record or record.last_message_id >= newest:
				return
			record.last_message_id = newest
		self.save_topics()

	def should_tag_admins(self, messages: Sequence[Any]) -> bool:
		config = self.config
		for message in messages:
			if getattr(message, "is_employee", False) and (
				getattr(message, "author_id", None) != 500
				or getattr(message, "interlocutor_id", None) == 500
			):
				return True
			if self.is_notifying_command(message):
				return True
			if config.get("tag_admins_on_reply") and self.is_interlocutor_message(message):
				return True
		return False

	def is_interlocutor_message(self, message: Any) -> bool:
		if getattr(message, "is_autoreply", False):
			return False
		author_id = getattr(message, "author_id", None)
		if author_id is not None and author_id == getattr(message, "interlocutor_id", None):
			return True
		return bool(
			author_id == 0
			and message_type_name(message) == "ORDER_PURCHASED"
			and getattr(message, "i_am_seller", False)
		)

	def is_notifying_command(self, message: Any) -> bool:
		commands = getattr(self.cardinal, "AR_CFG", None)
		text = getattr(message, "text", None)
		if not commands or not text:
			return False

		command = text.strip().lower()
		if command not in commands:
			return False
		if getattr(self.cardinal, "bl_cmd_notification_enabled", False) and getattr(message, "author", None) in (
			getattr(self.cardinal, "blacklist", None) or ()
		):
			return False
		try:
			return bool(commands[command].getboolean("telegramNotification"))
		except Exception:
			return False

	def buyer_viewing_prefix(self, message: Any) -> str:
		if not self.config.get("buyer_viewing"):
			return ""

		key = str(getattr(message, "chat_id", ""))
		now = time.time()
		if now - self._viewing_seen.get(key, 0) < BUYER_VIEWING_INTERVAL or self.is_rate_limited():
			return ""
		self._viewing_seen[key] = now

		interlocutor_id = getattr(message, "interlocutor_id", None)
		if interlocutor_id is None:
			return ""

		result = call_external(lambda: self.cardinal.account.get_buyer_viewing(interlocutor_id))
		if not result.succeeded:
			logger.debug(f"{LOGGER_PREFIX} Failed to read buyer viewing for chat {key}: {result.error}")
			return ""

		text = getattr(result.value, "text", "") or ""
		link = getattr(result.value, "link", "") or ""
		if not text or not link:
			return ""
		return f'<b><i>Смотрит: </i></b> <a href="{link}">{escape(text)}</a>\n\n'

	def is_rate_limited(self) -> bool:
		last_error = getattr(getattr(self.cardinal, "account", None), "last_429_err_time", 0) or 0
		return (time.time() - last_error) < RATE_LIMIT_COOLDOWN

	# History

	def backfill_history(self, key: str, record: TopicRecord) -> None:
		depth = int(self.config.get("history_depth") or 0)
		if depth <= 0:
			return

		history = self.load_history(key, record.username, depth)
		if not history:
			return

		chunks = render_messages(
			history,
			self.render_options(),
			prefix=f"<b><i>📜 История чата ({len(history)})</i></b>\n\n",
		)
		for chunk in chunks:
			self.send_text(key, record.thread_id, chunk.text, disable_notification=True)
		self.remember_last_message(key, history)

	def load_history(self, chat_id: int | str, username: str, depth: int) -> list[Any]:
		result = call_external(lambda: self.cardinal.account.get_chat_history(
			int(chat_id),
			interlocutor_username=username or None,
		))
		if not result.succeeded:
			logger.warning(f"{LOGGER_PREFIX} Failed to load history for chat {chat_id}: {result.error}")
			return []
		history = list(result.value or ())
		return history[-depth:] if depth > 0 else history

	def load_full_history(self, chat_id: int | str, username: str, pause: float = 0.2) -> list[Any]:
		collected: list[Any] = []
		seen: set[Any] = set()
		cursor: Any = None

		while True:
			result = call_external(lambda: self.cardinal.account.get_chat_history(
				int(chat_id),
				cursor,
				username or None,
			))
			if not result.succeeded:
				logger.warning(f"{LOGGER_PREFIX} Failed to load full history for chat {chat_id}: {result.error}")
				break

			page = list(result.value or ())
			page = [message for message in page if getattr(message, "id", None) not in seen]
			if not page:
				break

			seen.update(getattr(message, "id", None) for message in page)
			collected = page + collected
			cursor = getattr(page[0], "id", None)
			if cursor is None:
				break
			time.sleep(pause)

		return collected

	# Bulk sync

	@property
	def bulk_sync_running(self) -> bool:
		return self._bulk_sync_running

	def run_bulk_sync(self, progress: Callable[[int, int], None] | None = None) -> int:
		if not self.ready:
			return 0
		if self._bulk_sync_running:
			raise BulkSyncAlreadyRunning("Chat Sync bulk sync is already running.")

		self._bulk_sync_running = True
		try:
			result = call_external(lambda: self.cardinal.account.get_chats(update=True))
			if not result.succeeded:
				logger.error(f"{LOGGER_PREFIX} Failed to load FunPay chats: {result.error}")
				return 0

			chats = dict(result.value or {})
			pending = [
				(getattr(chat, "id", chat_id), getattr(chat, "name", "") or "")
				for chat_id, chat in chats.items()
				if str(chat_id) not in self.threads
			]

			created = 0
			for chat_id, name in pending:
				if self.ensure_topic(chat_id, name):
					created += 1
				if progress:
					progress(created, len(pending))
			logger.info(f"{LOGGER_PREFIX} Bulk sync created {created} topics.")
			return created
		finally:
			self._bulk_sync_running = False

	# Topic decoration

	def schedule_topic_refresh(self, key: str, chat_name: str, messages: Sequence[Any]) -> None:
		if not self.config.get("edit_topic") or not chat_name:
			return
		if not any(self.should_refresh_topic(message) for message in messages):
			return
		with self._topics_lock:
			if key in self._refreshing:
				return
			self._refreshing.add(key)

		threading.Thread(
			target=self.refresh_topic,
			args=(key, chat_name, list(messages)),
			name=f"manual-actions-topic-{key}",
			daemon=True,
		).start()

	def should_refresh_topic(self, message: Any) -> bool:
		if getattr(message, "is_employee", False):
			return not (
				getattr(message, "author_id", None) == 500
				and getattr(message, "chat_name", None) != getattr(message, "author", None)
			)
		return is_order_event(message) and not getattr(message, "i_am_buyer", False)

	def refresh_topic(self, key: str, chat_name: str, messages: Sequence[Any]) -> None:
		try:
			if self.is_rate_limited():
				return

			record = self.get_topic(key)
			if not record:
				return

			stats = self.collect_stats(chat_name)
			if stats is None:
				return

			trigger = next((message for message in messages if self.should_refresh_topic(message)), None)
			icon = topic_icon(
				stats,
				blacklisted=chat_name in (getattr(self.cardinal, "blacklist", None) or ()),
				special=self.special_icon(trigger, stats),
			)
			title = format_topic_name(chat_name, key, stats)
			if record.icon == icon and record.title == title:
				return

			bot = self.bot
			chat_id = self.telegram_chat_id
			if not bot or not chat_id:
				return

			result = self.sender.call(lambda: bot.edit_forum_topic(
				chat_id=chat_id,
				message_thread_id=record.thread_id,
				name=title,
				icon_custom_emoji_id=icon,
			))
			if not result.succeeded:
				logger.warning(f"{LOGGER_PREFIX} Failed to update topic {record.thread_id}: {result.error}")
				if is_missing_thread_error(result.error):
					self.drop_topic(key)
				return

			with self._topics_lock:
				stored = self.topics.get(key)
				if stored:
					stored.icon = icon
					stored.title = title
			self.save_topics()
			self.send_stats_message(key, record.thread_id, chat_name, stats, trigger)
		finally:
			with self._topics_lock:
				self._refreshing.discard(key)

	def special_icon(self, message: Any, stats: OrderStats) -> str:
		if message is None:
			return ""
		if getattr(message, "is_employee", False) and getattr(message, "chat_name", None) == getattr(message, "author", None):
			return "employee"

		text = str(getattr(message, "text", "") or "").lower()
		arbitration = (
			message_type_name(message) == "ORDER_REOPENED"
			or getattr(message, "is_moderation", False)
			or getattr(message, "is_arbitration", False)
			or (getattr(message, "is_support", False) and any(word in text for word in ARBITRATION_WORDS))
		)
		return "arbitration" if arbitration and stats.paid else ""

	def collect_stats(self, chat_name: str) -> OrderStats | None:
		sales: list[Any] = []
		start_from = None
		locale = None
		subcategories = None

		while True:
			result = call_external(lambda: self.cardinal.account.get_sales(
				buyer=chat_name,
				start_from=start_from,
				locale=locale,
				sudcategories=subcategories,
			))
			if not result.succeeded:
				logger.debug(f"{LOGGER_PREFIX} Failed to load sales for {chat_name}: {result.error}")
				return None

			start_from, page, locale, subcategories = result.value
			sales.extend(page or ())
			if start_from is None:
				break
			time.sleep(1)

		return collect_order_stats(sales)

	def send_stats_message(self, key: str, thread_id: int, chat_name: str, stats: OrderStats, trigger: Any) -> None:
		if trigger is None or getattr(trigger, "author_id", None) != 0:
			return

		text = (
			f"Статистика по пользователю <b>{escape(chat_name)}</b>\n\n"
			f"<b>🛒 Оплачен:</b> <code>{stats.paid}</code>"
			f"{f' (<code>{stats.paid_sum}</code>)' if stats.paid_sum else ''}\n"
			f"<b>🏁 Закрыт:</b> <code>{stats.closed}</code>"
			f"{f' (<code>{stats.closed_sum}</code>)' if stats.closed_sum else ''}\n"
			f"<b>🔙 Возврат:</b> <code>{stats.refunded}</code>"
			f"{f' (<code>{stats.refunded_sum}</code>)' if stats.refunded_sum else ''}"
		)
		self.send_text(key, thread_id, text, disable_notification=True)

	# Outgoing

	def send_to_funpay(self, chat_id: int | str, username: str, text: str) -> bool:
		result = call_external(lambda: self.cardinal.send_message(
			chat_id,
			f"{SPECIAL_SYMBOL}{text}",
			username or None,
			watermark=False,
		))
		if not result.succeeded:
			logger.error(f"{LOGGER_PREFIX} Failed to send FunPay message to {chat_id}: {result.error}")
			return False
		return bool(result.value)

	def send_image_to_funpay(self, chat_id: int | str, username: str, image: bytes) -> bool:
		result = call_external(lambda: self.cardinal.account.send_image(
			chat_id,
			image,
			username or None,
			True,
			update_last_saved_message=getattr(self.cardinal, "old_mode_enabled", False),
		))
		if not result.succeeded:
			logger.error(f"{LOGGER_PREFIX} Failed to send FunPay image to {chat_id}: {result.error}")
			return False
		return bool(result.value)
