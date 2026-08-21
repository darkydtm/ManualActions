from __future__ import annotations

from base64 import urlsafe_b64decode, urlsafe_b64encode
from binascii import Error as Base64Error
from html import escape
from math import ceil, isfinite
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

try:
	from telebot.types import InlineKeyboardButton as B, InlineKeyboardMarkup as K
except ModuleNotFoundError:
	class B:
		def __init__(self, text: str, callback_data: str | None = None, url: str | None = None):
			self.text = text
			self.callback_data = callback_data
			self.url = url

	class K:
		def __init__(self, row_width: int = 1):
			self.rows = []

		def add(self, *buttons: B) -> "K":
			self.rows.append(list(buttons))
			return self

		def row(self, *buttons: B) -> "K":
			self.rows.append(list(buttons))
			return self


from ...config.constants import (
	CBT_AUTO_DUMPING_BLACKLIST_ADD,
	CBT_AUTO_DUMPING_BLACKLIST_DELETE,
	CBT_AUTO_DUMPING_BLACKLIST_PAGE,
	CBT_AUTO_DUMPING_INTERVAL,
	CBT_AUTO_DUMPING_PAGE,
	CBT_AUTO_DUMPING_PERIOD_PAGE,
	CBT_AUTO_DUMPING_RULE,
	CBT_AUTO_DUMPING_RULE_ADD,
	CBT_AUTO_DUMPING_RULE_DELETE,
	CBT_AUTO_DUMPING_RULE_TOGGLE,
	CBT_AUTO_DUMPING_RULES,
	CBT_AUTO_DUMPING_RULES_PAGE,
	CBT_AUTO_DUMPING_RUN,
	CBT_AUTO_DUMPING_STATUS,
	CBT_AUTO_DUMPING_TOGGLE,
	STATE_AUTO_DUMPING_INTERVAL,
	STATE_AUTO_DUMPING_KEYWORDS,
	STATE_AUTO_DUMPING_RULE,
	STATE_AUTO_DUMPING_SELLERS,
)
from ...common.payloads import CallbackPayloadCache
from ...runtime.settings import update_host_settings
from .settings import INTERVAL_PRESETS, normalize_rule, normalize_words


PAGE_SIZE = 5
PAGE_TOKEN_BYTES = 4
MAX_CALLBACK_PAGE = (1 << (PAGE_TOKEN_BYTES * 8)) - 1
MAX_RULE_REFERENCE = (1 << (PAGE_TOKEN_BYTES * 8)) - 1


def validate_rule_input(data: dict[str, Any]) -> dict[str, Any]:
	rule = normalize_rule(data)
	if not rule:
		raise ValueError("Укажите одну подкатегорию, ключевые слова и положительное значение демпинга.")
	if rule["competitor_min_price"] < 0 or rule["own_min_price"] < 0:
		raise ValueError("Минимальные цены не могут быть отрицательными.")
	return rule


class TelegramAutoDumpingFlow:
	def __init__(self, host: Any, service: Any, scheduler: Any):
		self.host = host
		self.service = service
		self.scheduler = scheduler
		self._blacklist_payloads = CallbackPayloadCache()

	def register(self) -> None:
		if not self.host.tg:
			return
		self.host.tg.cbq_handler(self.open_page, lambda c: (c.data or "").startswith(CBT_AUTO_DUMPING_PAGE))
		self.host.tg.cbq_handler(self._status_callback, lambda c: (c.data or "").startswith(CBT_AUTO_DUMPING_STATUS))
		self.host.tg.cbq_handler(self.toggle, lambda c: (c.data or "").startswith(CBT_AUTO_DUMPING_TOGGLE))
		self.host.tg.cbq_handler(self.set_interval, lambda c: (c.data or "").startswith(CBT_AUTO_DUMPING_INTERVAL))
		self.host.tg.cbq_handler(self.run_now, lambda c: (c.data or "").startswith(CBT_AUTO_DUMPING_RUN))
		self.host.tg.cbq_handler(self.open_rules, lambda c: (c.data or "").startswith(CBT_AUTO_DUMPING_RULES))
		self.host.tg.cbq_handler(self.show_rule, lambda c: (c.data or "").startswith(CBT_AUTO_DUMPING_RULE))
		self.host.tg.cbq_handler(self.toggle_rule, lambda c: (c.data or "").startswith(CBT_AUTO_DUMPING_RULE_TOGGLE))
		self.host.tg.cbq_handler(self.delete_rule, lambda c: (c.data or "").startswith(CBT_AUTO_DUMPING_RULE_DELETE))
		self.host.tg.cbq_handler(self.add_rule, lambda c: (c.data or "").startswith(CBT_AUTO_DUMPING_RULE_ADD))
		self.host.tg.cbq_handler(self.open_period, lambda c: (c.data or "").startswith(CBT_AUTO_DUMPING_PERIOD_PAGE))
		self.host.tg.cbq_handler(self.open_rules, lambda c: (c.data or "").startswith(CBT_AUTO_DUMPING_RULES_PAGE))
		self.host.tg.cbq_handler(self._blacklist_page_callback, lambda c: (c.data or "").startswith(CBT_AUTO_DUMPING_BLACKLIST_PAGE))
		self.host.tg.cbq_handler(self._add_blacklist, lambda c: (c.data or "").startswith(CBT_AUTO_DUMPING_BLACKLIST_ADD))
		self.host.tg.cbq_handler(self._delete_blacklist, lambda c: (c.data or "").startswith(CBT_AUTO_DUMPING_BLACKLIST_DELETE))
		self.host.tg.msg_handler(self.save_interval, func=lambda m: self.host.tg.check_state(m.chat.id, m.from_user.id, STATE_AUTO_DUMPING_INTERVAL))
		self.host.tg.msg_handler(self.save_rule, func=lambda m: self.host.tg.check_state(m.chat.id, m.from_user.id, STATE_AUTO_DUMPING_RULE))
		self.host.tg.msg_handler(self.save_rule_blacklist, func=lambda m: self.host.tg.check_state(m.chat.id, m.from_user.id, STATE_AUTO_DUMPING_SELLERS))
		self.host.tg.msg_handler(self.save_rule_blacklist, func=lambda m: self.host.tg.check_state(m.chat.id, m.from_user.id, STATE_AUTO_DUMPING_KEYWORDS))

	@staticmethod
	def _page_items(items: list[Any], page: int) -> tuple[list[Any], int]:
		pages = max(1, ceil(len(items) / PAGE_SIZE))
		page = TelegramAutoDumpingFlow._display_page(page, pages)
		start = page * PAGE_SIZE
		return items[start:start + PAGE_SIZE], pages

	@staticmethod
	def _display_page(page: Any, pages: int) -> int:
		try:
			if isinstance(page, float) and (not isfinite(page) or not page.is_integer()):
				raise ValueError
			page = max(int(page), 0)
		except (TypeError, ValueError, OverflowError):
			page = 0
		return min(page, pages - 1)

	@staticmethod
	def _page_callback(prefix: str, context: int | str | None, list_kind: str | None, page: int) -> str:
		page = TelegramAutoDumpingFlow._validate_callback_page(page)
		if list_kind is not None:
			if list_kind not in ("sellers", "keywords"):
				raise ValueError("invalid callback list kind")
			rule_index = TelegramAutoDumpingFlow._validate_rule_reference(context)
			kind = 0 if list_kind == "sellers" else 1
			payload = rule_index.to_bytes(PAGE_TOKEN_BYTES, "big") + bytes((kind,)) + page.to_bytes(PAGE_TOKEN_BYTES, "big")
			callback = f"{prefix}~{urlsafe_b64encode(payload).decode().rstrip('=')}"
		else:
			context = "" if context is None else str(context)
			page_token = urlsafe_b64encode(page.to_bytes(PAGE_TOKEN_BYTES, "big")).decode().rstrip("=")
			callback = f"{prefix}{context}:{page_token}"
		if len(callback.encode("utf-8")) > 64:
			raise ValueError("callback data exceeds Telegram's 64-byte limit")
		return callback

	@staticmethod
	def _parse_page_callback(data: str, prefix: str) -> tuple[int | str, str | None, int]:
		if not isinstance(data, str) or not data.startswith(prefix):
			raise ValueError("invalid page callback")
		payload = data[len(prefix):]
		if payload.startswith("~"):
			compact = TelegramAutoDumpingFlow._decode_compact_page(payload[1:])
			if compact is None:
				raise ValueError("invalid page callback")
			return compact
		context, separator, page = payload.rpartition(":")
		if not separator:
			raise ValueError("invalid page callback")
		try:
			page_bytes = urlsafe_b64decode(page + "=" * (-len(page) % 4))
			if len(page_bytes) != PAGE_TOKEN_BYTES:
				raise ValueError
			page = int.from_bytes(page_bytes, "big")
		except (Base64Error, TypeError, ValueError):
			try:
				page = int(page)
			except (TypeError, ValueError):
				raise ValueError("invalid callback page") from None
		return context, None, TelegramAutoDumpingFlow._validate_callback_page(page)

	@staticmethod
	def _validate_callback_page(page: Any) -> int:
		if isinstance(page, bool):
			raise ValueError("invalid callback page")
		try:
			value = int(page)
		except (TypeError, ValueError, OverflowError):
			raise ValueError("invalid callback page") from None
		if isinstance(page, float) and (not isfinite(page) or page != value):
			raise ValueError("invalid callback page")
		if not 0 <= value <= MAX_CALLBACK_PAGE:
			raise ValueError("page is outside the callback range")
		return value

	@staticmethod
	def _decode_compact_page(token: str) -> tuple[int, str, int] | None:
		if not token or any(char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_" for char in token):
			return None
		try:
			payload = urlsafe_b64decode(token + "=" * (-len(token) % 4))
		except (Base64Error, TypeError, ValueError):
			return None
		if len(payload) != PAGE_TOKEN_BYTES * 2 + 1:
			return None
		rule_index = int.from_bytes(payload[:PAGE_TOKEN_BYTES], "big")
		kind = payload[PAGE_TOKEN_BYTES]
		if kind not in (0, 1):
			return None
		return rule_index, "sellers" if kind == 0 else "keywords", TelegramAutoDumpingFlow._validate_callback_page(int.from_bytes(payload[-PAGE_TOKEN_BYTES:], "big"))

	def _blacklist_item_callback(self, prefix: str, rule_index: int, kind: str, page: int, item_index: int, item: str) -> str:
		if kind not in ("sellers", "keywords"):
			raise ValueError("invalid callback list kind")
		if not isinstance(item_index, int) or not 0 <= item_index <= MAX_CALLBACK_PAGE:
			raise ValueError("invalid blacklist item")
		rule_index = TelegramAutoDumpingFlow._validate_rule_reference(rule_index)
		page = TelegramAutoDumpingFlow._validate_callback_page(page)
		token = self._blacklist_payloads.put((rule_index, kind, page, item_index, item))
		payload = (
			rule_index.to_bytes(PAGE_TOKEN_BYTES, "big")
			+ bytes((0 if kind == "sellers" else 1,))
			+ page.to_bytes(PAGE_TOKEN_BYTES, "big")
			+ item_index.to_bytes(PAGE_TOKEN_BYTES, "big")
			+ int(token, 16).to_bytes(PAGE_TOKEN_BYTES, "big")
		)
		callback = f"{prefix}~{urlsafe_b64encode(payload).decode().rstrip('=')}"
		if len(callback.encode("utf-8")) > 64:
			raise ValueError("callback data exceeds Telegram's 64-byte limit")
		return callback

	@classmethod
	def _parse_blacklist_item_callback(cls, data: str, prefix: str) -> tuple[int, str, int, int, str]:
		if not isinstance(data, str) or not data.startswith(prefix) or not data[len(prefix):].startswith("~"):
			raise ValueError("invalid blacklist item callback")
		try:
			payload = urlsafe_b64decode(data[len(prefix) + 1:] + "=" * (-len(data[len(prefix) + 1:]) % 4))
		except (Base64Error, TypeError, ValueError):
			raise ValueError("invalid blacklist item callback") from None
		token = data[len(prefix) + 1:]
		if (
			any(char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_" for char in token)
			or len(payload) != PAGE_TOKEN_BYTES * 4 + 1
			or payload[PAGE_TOKEN_BYTES] not in (0, 1)
			or urlsafe_b64encode(payload).decode().rstrip("=") != token
		):
			raise ValueError("invalid blacklist item callback")
		return (
			cls._validate_rule_reference(int.from_bytes(payload[:PAGE_TOKEN_BYTES], "big")),
			"sellers" if payload[PAGE_TOKEN_BYTES] == 0 else "keywords",
			cls._validate_callback_page(int.from_bytes(payload[PAGE_TOKEN_BYTES + 1:PAGE_TOKEN_BYTES * 2 + 1], "big")),
			int.from_bytes(payload[PAGE_TOKEN_BYTES * 2 + 1:PAGE_TOKEN_BYTES * 3 + 1], "big"),
			format(int.from_bytes(payload[-PAGE_TOKEN_BYTES:], "big"), "x"),
		)

	def _rule_id_from_reference(self, rule_index: int) -> str:
		rules = self.host.settings["auto_dumping"]["rules"]
		index = self._rule_index_in_settings(self.host.settings, rule_index)
		return rules[index]["id"]

	@classmethod
	def _rule_index_in_settings(cls, settings: dict[str, Any], rule_index: int) -> int:
		index = cls._validate_rule_reference(rule_index)
		if not 0 <= index < len(settings["auto_dumping"]["rules"]):
			raise ValueError("rule reference not found")
		return index

	@classmethod
	def _rule_callback(cls, prefix: str, rule_index: int) -> str:
		return f"{prefix}{cls._validate_rule_reference(rule_index)}"

	@classmethod
	def _rule_callback_with_page(cls, prefix: str, rule_index: int, page: int) -> str:
		return cls._page_callback(prefix, cls._validate_rule_reference(rule_index), None, page)

	@classmethod
	def _rule_callback_parts(cls, data: str, prefix: str) -> tuple[int, int]:
		if not isinstance(data, str) or not data.startswith(prefix):
			raise ValueError("invalid rule callback")
		payload = data[len(prefix):]
		if ":" not in payload:
			return cls._validate_rule_reference(payload), 0
		context, _, page = cls._parse_page_callback(data, prefix)
		return cls._validate_rule_reference(context), page

	@classmethod
	def _rule_index_from_callback(cls, data: str, prefix: str) -> int:
		if not isinstance(data, str) or not data.startswith(prefix):
			raise ValueError("invalid rule callback")
		return cls._validate_rule_reference(data[len(prefix):])

	@staticmethod
	def _validate_rule_reference(rule_index: Any) -> int:
		if isinstance(rule_index, bool):
			raise ValueError("invalid rule reference")
		try:
			value = int(rule_index)
		except (TypeError, ValueError, OverflowError):
			raise ValueError("invalid rule reference") from None
		if isinstance(rule_index, float) and (not isfinite(rule_index) or rule_index != value):
			raise ValueError("invalid rule reference")
		if not 0 <= value <= MAX_RULE_REFERENCE:
			raise ValueError("rule reference is outside the callback range")
		return value

	def _pending_callback(self, call: telebot.types.CallbackQuery) -> None:
		self.host.tgbot.answer_callback_query(call.id)

	def _pending_page_callback(self, call: telebot.types.CallbackQuery) -> None:
		prefixes = (
			CBT_AUTO_DUMPING_PERIOD_PAGE,
			CBT_AUTO_DUMPING_RULES_PAGE,
			CBT_AUTO_DUMPING_BLACKLIST_PAGE,
		)
		prefix = next((prefix for prefix in prefixes if (call.data or "").startswith(prefix)), None)
		try:
			if prefix is None:
				raise ValueError
			self._parse_page_callback(call.data, prefix)
		except ValueError:
			self.host.tgbot.answer_callback_query(call.id, "Некорректная страница.", show_alert=True)
			return
		self.host.tgbot.answer_callback_query(call.id)

	def _blacklist_page_callback(self, call: telebot.types.CallbackQuery) -> None:
		try:
			rule_reference, kind, page = self._parse_page_callback(call.data, CBT_AUTO_DUMPING_BLACKLIST_PAGE)
			rule_index = self._rule_index_in_settings(self.host.settings, rule_reference)
			if not hasattr(call, "message"):
				self.host.tgbot.answer_callback_query(call.id)
				return
			if kind is None:
				self.show_blacklist(call, rule_index, page)
			else:
				self.show_blacklist_items(call, rule_index, kind, page)
		except ValueError:
			self.host.tgbot.answer_callback_query(call.id, "Некорректная страница.", show_alert=True)

	def show_main(self, chat_id: int, message_id: int | None = None, edit: bool = False) -> None:
		settings = self.host.settings["auto_dumping"]
		state = "включен" if settings["enabled"] else "выключен"
		last = self.service.storage.state.get("last_result", {})
		text = (
			f"<b>Автодемпинг</b>\n\nСостояние: <b>{state}</b>\n"
			f"Период: <b>{settings['interval_minutes']} мин.</b>\n"
			f"Правил: <b>{len(settings['rules'])}</b>\n"
			f"Последний цикл: <code>{escape(str(last or 'не было'))}</code>"
		)
		keyboard = K(row_width=1)
		keyboard.add(B("Статус", callback_data=f"{CBT_AUTO_DUMPING_STATUS}page:{chat_id}"))
		keyboard.add(B("Период", callback_data=self._page_callback(CBT_AUTO_DUMPING_PERIOD_PAGE, chat_id, None, 0)))
		keyboard.add(B("Правила", callback_data=self._page_callback(CBT_AUTO_DUMPING_RULES_PAGE, chat_id, None, 0)))
		keyboard.add(B("Запустить цикл", callback_data=f"{CBT_AUTO_DUMPING_RUN}{chat_id}"))
		self._send_or_edit(text, chat_id, message_id, keyboard, edit)

	def open_page(self, call: telebot.types.CallbackQuery) -> None:
		self.host.tgbot.answer_callback_query(call.id)
		self.show_main(call.message.chat.id, call.message.id, True)

	def _status_callback(self, call: telebot.types.CallbackQuery) -> None:
		value = call.data.replace(CBT_AUTO_DUMPING_STATUS, "", 1)
		if value.startswith("page:"):
			try:
				self._parse_legacy_page_callback(call.data, CBT_AUTO_DUMPING_STATUS)
			except ValueError:
				self.host.tgbot.answer_callback_query(call.id, "Некорректная страница.", show_alert=True)
				return
			self.show_status(call)
			return
		self.toggle(call)

	def show_status(self, call: telebot.types.CallbackQuery) -> None:
		settings = self.host.settings["auto_dumping"]
		state = "включен" if settings["enabled"] else "выключен"
		keyboard = K(row_width=2)
		keyboard.add(
			B("✅ Включено" if settings["enabled"] else "Включить", callback_data=f"{CBT_AUTO_DUMPING_STATUS}1"),
			B("⛔ Выключено" if not settings["enabled"] else "Выключить", callback_data=f"{CBT_AUTO_DUMPING_STATUS}0"),
		)
		keyboard.add(B("◀️ Назад", callback_data=f"{CBT_AUTO_DUMPING_PAGE}{call.message.chat.id}"))
		self.host.tgbot.edit_message_text(
			f"<b>Статус автодемпинга</b>\n\nСостояние: <b>{state}</b>",
			call.message.chat.id,
			call.message.id,
			reply_markup=keyboard,
		)
		self.host.tgbot.answer_callback_query(call.id)

	def toggle(self, call: telebot.types.CallbackQuery) -> None:
		prefix = CBT_AUTO_DUMPING_STATUS if call.data.startswith(CBT_AUTO_DUMPING_STATUS) else CBT_AUTO_DUMPING_TOGGLE
		value = call.data.replace(prefix, "", 1)
		if value not in ("0", "1"):
			self.host.tgbot.answer_callback_query(call.id, "Некорректный статус.", show_alert=True)
			return
		update_host_settings(self.host, lambda settings: settings["auto_dumping"].__setitem__("enabled", value == "1"))
		self._sync_scheduler()
		self.show_status(call)

	def set_interval(self, call: telebot.types.CallbackQuery) -> None:
		value = call.data.replace(CBT_AUTO_DUMPING_INTERVAL, "", 1)
		if value.startswith("page:"):
			try:
				self._parse_legacy_page_callback(call.data, CBT_AUTO_DUMPING_INTERVAL)
			except ValueError:
				self.host.tgbot.answer_callback_query(call.id, "Некорректная страница.", show_alert=True)
				return
			self.show_period(call)
			return
		if value == "custom":
			message = self.host.tgbot.send_message(call.message.chat.id, "Введите период в минутах.")
			self.host.tg.set_state(call.message.chat.id, message.id, call.from_user.id, STATE_AUTO_DUMPING_INTERVAL, {})
			self.host.tgbot.answer_callback_query(call.id)
			return
		try:
			minutes = int(value)
		except ValueError:
			self.host.tgbot.answer_callback_query(call.id, "Некорректный период.", show_alert=True)
			return
		self._save_interval(minutes, call)

	def show_period(self, call: telebot.types.CallbackQuery) -> None:
		keyboard = K(row_width=2)
		for minutes in INTERVAL_PRESETS:
			keyboard.add(B(f"{minutes} мин.", callback_data=f"{CBT_AUTO_DUMPING_INTERVAL}{minutes}"))
		keyboard.add(B("Своё значение", callback_data=f"{CBT_AUTO_DUMPING_INTERVAL}custom"))
		keyboard.add(B("◀️ Назад", callback_data=f"{CBT_AUTO_DUMPING_PAGE}{call.message.chat.id}"))
		self.host.tgbot.edit_message_text("<b>Период автодемпинга</b>", call.message.chat.id, call.message.id, reply_markup=keyboard)
		self.host.tgbot.answer_callback_query(call.id)

	def open_period(self, call: telebot.types.CallbackQuery) -> None:
		try:
			self._parse_page_callback(call.data, CBT_AUTO_DUMPING_PERIOD_PAGE)
		except ValueError:
			self.host.tgbot.answer_callback_query(call.id, "Некорректная страница.", show_alert=True)
			return
		self.show_period(call)

	@classmethod
	def _parse_legacy_page_callback(cls, data: str, prefix: str) -> int:
		context, _, page = cls._parse_page_callback(data, prefix)
		if context != "page":
			raise ValueError("invalid legacy page callback")
		return page

	def save_interval(self, message: telebot.types.Message) -> None:
		try:
			minutes = int((message.text or "").strip())
		except ValueError:
			self.host.tgbot.reply_to(message, "Введите положительное целое число минут.")
			return
		if minutes < 1:
			self.host.tgbot.reply_to(message, "Период должен быть положительным.")
			return
		self.host.tg.clear_state(message.chat.id, message.from_user.id, True)
		update_host_settings(self.host, lambda settings: settings["auto_dumping"].__setitem__("interval_minutes", minutes))
		self.scheduler.stop()
		self.scheduler.interval_minutes = minutes
		if self.host.settings["auto_dumping"]["enabled"]:
			self.scheduler.start()
		self.host.tgbot.send_message(message.chat.id, f"Период сохранён: {minutes} мин.")

	def _save_interval(self, minutes: int, call: telebot.types.CallbackQuery) -> None:
		if minutes < 1:
			self.host.tgbot.answer_callback_query(call.id, "Период должен быть положительным.", show_alert=True)
			return
		update_host_settings(self.host, lambda settings: settings["auto_dumping"].__setitem__("interval_minutes", minutes))
		self.scheduler.stop()
		self.scheduler.interval_minutes = minutes
		if self.host.settings["auto_dumping"]["enabled"]:
			self.scheduler.start()
		self._refresh(call)

	def run_now(self, call: telebot.types.CallbackQuery) -> None:
		result = self.service.run_cycle()
		self.host.tgbot.answer_callback_query(call.id, f"Цикл завершён: {result.get('updated', 0)} изменений.")
		self._refresh(call)

	def open_rules(self, call: telebot.types.CallbackQuery) -> None:
		page = 0
		if getattr(call, "data", "").startswith(CBT_AUTO_DUMPING_RULES_PAGE):
			try:
				_, _, page = self._parse_page_callback(call.data, CBT_AUTO_DUMPING_RULES_PAGE)
			except ValueError:
				self.host.tgbot.answer_callback_query(call.id, "Некорректная страница.", show_alert=True)
				return
		self.show_rules(call, page)

	def show_rules(self, call: telebot.types.CallbackQuery, page: int = 0) -> None:
		rules = self.host.settings["auto_dumping"]["rules"]
		items, pages = self._page_items(rules, page)
		page = self._display_page(page, pages)
		keyboard = K(row_width=1)
		for offset, rule in enumerate(items, page * PAGE_SIZE):
			keyboard.add(B(
				rule["subcategory"] + ": " + ", ".join(rule["keywords"]),
				callback_data=self._rule_callback_with_page(CBT_AUTO_DUMPING_RULE, offset, page),
			))
		if not items:
			keyboard.add(B("Правил пока нет", callback_data=self._page_callback(CBT_AUTO_DUMPING_RULES_PAGE, call.message.chat.id, None, page)))
		keyboard.add(B("➕ Добавить правило", callback_data=f"{CBT_AUTO_DUMPING_RULE_ADD}{call.message.chat.id}"))
		keyboard.row(
			B("◀️", callback_data=self._page_callback(CBT_AUTO_DUMPING_RULES_PAGE, call.message.chat.id, None, max(page - 1, 0))),
			B(f"{page + 1}/{pages}", callback_data=self._page_callback(CBT_AUTO_DUMPING_RULES_PAGE, call.message.chat.id, None, page)),
			B("▶️", callback_data=self._page_callback(CBT_AUTO_DUMPING_RULES_PAGE, call.message.chat.id, None, min(page + 1, pages - 1))),
			B("◀️ Назад", callback_data=f"{CBT_AUTO_DUMPING_PAGE}{call.message.chat.id}"),
		)
		self.host.tgbot.edit_message_text("<b>Правила автодемпинга</b>", call.message.chat.id, call.message.id, reply_markup=keyboard)
		self.host.tgbot.answer_callback_query(call.id)

	def show_rule(self, call: telebot.types.CallbackQuery) -> None:
		try:
			rule_index, page = self._rule_callback_parts(call.data, CBT_AUTO_DUMPING_RULE)
			rule_index = self._rule_index_in_settings(self.host.settings, rule_index)
		except ValueError:
			self.host.tgbot.answer_callback_query(call.id, "Правило не найдено.", show_alert=True)
			return
		rule = self.host.settings["auto_dumping"]["rules"][rule_index]
		keyboard = K(row_width=1)
		keyboard.add(B("⏹ Выключить" if rule.get("enabled", True) else "▶️ Включить", callback_data=self._rule_callback_with_page(CBT_AUTO_DUMPING_RULE_TOGGLE, rule_index, page)))
		keyboard.add(B("Черный список", callback_data=self._page_callback(CBT_AUTO_DUMPING_BLACKLIST_PAGE, rule_index, None, 0)))
		keyboard.add(B("🗑 Удалить", callback_data=self._rule_callback_with_page(CBT_AUTO_DUMPING_RULE_DELETE, rule_index, page)))
		keyboard.add(B("◀️ К правилам", callback_data=self._page_callback(CBT_AUTO_DUMPING_RULES_PAGE, call.message.chat.id, None, page)))
		text = f"<b>Правило {escape(str(rule.get('id', '')))}</b>\nПодкатегория: {escape(str(rule.get('subcategory', '')))}\nКлючевые слова: {escape(', '.join(rule.get('keywords', [])))}"
		self.host.tgbot.edit_message_text(text, call.message.chat.id, call.message.id, reply_markup=keyboard)
		self.host.tgbot.answer_callback_query(call.id)

	def toggle_rule(self, call: telebot.types.CallbackQuery) -> None:
		try:
			rule_index, page = self._rule_callback_parts(call.data, CBT_AUTO_DUMPING_RULE_TOGGLE)
			rule_index = self._rule_index_in_settings(self.host.settings, rule_index)
		except ValueError:
			self.host.tgbot.answer_callback_query(call.id, "Правило не найдено.", show_alert=True)
			return
		update_host_settings(self.host, lambda settings: self._mutate_rule(settings, rule_index, lambda rule: rule.__setitem__("enabled", not rule["enabled"])))
		self.show_rule(SimpleNamespace(id=call.id, data=self._rule_callback_with_page(CBT_AUTO_DUMPING_RULE, rule_index, page), message=call.message))

	def delete_rule(self, call: telebot.types.CallbackQuery) -> None:
		try:
			rule_index, page = self._rule_callback_parts(call.data, CBT_AUTO_DUMPING_RULE_DELETE)
			rule_index = self._rule_index_in_settings(self.host.settings, rule_index)
		except ValueError:
			self.host.tgbot.answer_callback_query(call.id, "Правило не найдено.", show_alert=True)
			return
		update_host_settings(self.host, lambda settings: self._delete_rule(settings, rule_index))
		self.show_rules(call, page)

	def add_rule(self, call: telebot.types.CallbackQuery) -> None:
		message = self.host.tgbot.send_message(call.message.chat.id, "Введите правило JSON: subcategory, keywords, keyword_mode, price_mode, dumping_value, competitor_min_price, own_min_price.")
		self.host.tg.set_state(call.message.chat.id, message.id, call.from_user.id, STATE_AUTO_DUMPING_RULE, {})
		self.host.tgbot.answer_callback_query(call.id)

	def save_rule(self, message: telebot.types.Message) -> None:
		import json
		try:
			data = json.loads(message.text or "")
			rule = validate_rule_input(data)
		except (ValueError, TypeError, json.JSONDecodeError) as exc:
			self.host.tgbot.reply_to(message, str(exc) or "Некорректное правило.")
			return
		rule["id"] = rule.get("id") or uuid4().hex
		update_host_settings(self.host, lambda settings: settings["auto_dumping"]["rules"].append(rule))
		self.host.tg.clear_state(message.chat.id, message.from_user.id, True)
		self.host.tgbot.send_message(message.chat.id, "Правило сохранено.")

	def _find_rule(self, rule_id: str) -> dict[str, Any]:
		for rule in self.host.settings["auto_dumping"]["rules"]:
			if rule.get("id") == rule_id:
				return rule
		raise ValueError("Правило не найдено.")

	def _blacklist_rule(self, settings: dict[str, Any], rule_index: int) -> dict[str, Any]:
		index = self._rule_index_in_settings(settings, rule_index)
		return settings["auto_dumping"]["rules"][index]

	def show_blacklist(self, call: telebot.types.CallbackQuery, rule_id: int | str, page: int) -> None:
		try:
			rule_index = self._rule_index_in_settings(self.host.settings, rule_id) if isinstance(rule_id, int) else next(
				index for index, rule in enumerate(self.host.settings["auto_dumping"]["rules"]) if rule.get("id") == rule_id
			)
		except (StopIteration, ValueError):
			self.host.tgbot.answer_callback_query(call.id, "Правило не найдено.", show_alert=True)
			return
		keyboard = K(row_width=1)
		keyboard.add(B("Продавцы", callback_data=self._page_callback(CBT_AUTO_DUMPING_BLACKLIST_PAGE, rule_index, "sellers", 0)))
		keyboard.add(B("Ключевые слова", callback_data=self._page_callback(CBT_AUTO_DUMPING_BLACKLIST_PAGE, rule_index, "keywords", 0)))
		keyboard.add(B("◀️ Назад", callback_data=self._rule_callback_with_page(CBT_AUTO_DUMPING_RULE, rule_index, page)))
		self.host.tgbot.edit_message_text("<b>Черный список правила</b>", call.message.chat.id, call.message.id, reply_markup=keyboard)
		self.host.tgbot.answer_callback_query(call.id)

	def show_blacklist_items(self, call: telebot.types.CallbackQuery, rule_id: int | str, kind: str, page: int) -> None:
		try:
			rule_index = self._rule_index_in_settings(self.host.settings, rule_id) if isinstance(rule_id, int) else next(
				index for index, rule in enumerate(self.host.settings["auto_dumping"]["rules"]) if rule.get("id") == rule_id
			)
			if kind not in ("sellers", "keywords"):
				raise ValueError
			rule = self._blacklist_rule(self.host.settings, rule_index)
		except (StopIteration, ValueError):
			self.host.tgbot.answer_callback_query(call.id, "Правило не найдено.", show_alert=True)
			return
		field = f"{kind}_blacklist"
		items, pages = self._page_items(rule.get(field, []), page)
		page = self._display_page(page, pages)
		keyboard = K(row_width=1)
		for offset, item in enumerate(items, page * PAGE_SIZE):
			keyboard.add(B(f"{item}  ✖️", callback_data=self._blacklist_item_callback(CBT_AUTO_DUMPING_BLACKLIST_DELETE, rule_index, kind, page, offset, item)))
		keyboard.add(B("➕ Добавить", callback_data=self._page_callback(CBT_AUTO_DUMPING_BLACKLIST_ADD, rule_index, kind, page)))
		keyboard.row(
			B("◀️", callback_data=self._page_callback(CBT_AUTO_DUMPING_BLACKLIST_PAGE, rule_index, kind, max(page - 1, 0))),
			B(f"{page + 1}/{pages}", callback_data=self._page_callback(CBT_AUTO_DUMPING_BLACKLIST_PAGE, rule_index, kind, page)),
			B("▶️", callback_data=self._page_callback(CBT_AUTO_DUMPING_BLACKLIST_PAGE, rule_index, kind, min(page + 1, pages - 1))),
			B("◀️ Назад", callback_data=self._page_callback(CBT_AUTO_DUMPING_BLACKLIST_PAGE, rule_index, None, page)),
		)
		self.host.tgbot.edit_message_text(
			f"<b>{'Продавцы' if kind == 'sellers' else 'Ключевые слова'}</b>\nВсего: {len(rule.get(field, []))}",
			call.message.chat.id,
			call.message.id,
			reply_markup=keyboard,
		)
		self.host.tgbot.answer_callback_query(call.id)

	def _add_blacklist(self, call: telebot.types.CallbackQuery) -> None:
		try:
			rule_index, kind, page = self._parse_page_callback(call.data, CBT_AUTO_DUMPING_BLACKLIST_ADD)
			rule_id = self._rule_id_from_reference(rule_index)
			if kind not in ("sellers", "keywords"):
				raise ValueError
		except ValueError:
			self.host.tgbot.answer_callback_query(call.id, "Правило не найдено.", show_alert=True)
			return
		state = STATE_AUTO_DUMPING_SELLERS if kind == "sellers" else STATE_AUTO_DUMPING_KEYWORDS
		message = self.host.tgbot.send_message(call.message.chat.id, "Введите значения через запятую.")
		self.host.tg.set_state(call.message.chat.id, message.id, call.from_user.id, state, {
			"rule_id": rule_id,
			"rule_index": rule_index,
			"kind": kind,
			"page": page,
			"message_id": call.message.id,
		})
		self.host.tgbot.answer_callback_query(call.id)

	def save_rule_blacklist(self, message: telebot.types.Message) -> str | None:
		state = self.host.tg.get_state(message.chat.id, message.from_user.id) or {}
		data = state.get("data") if isinstance(state, dict) else None
		if not isinstance(data, dict) or data.get("kind") not in ("sellers", "keywords"):
			self.host.tgbot.reply_to(message, "Некорректное состояние списка.")
			return None
		try:
			message_id = data["message_id"]
			if isinstance(message_id, bool) or not isinstance(message_id, int) or message_id < 1:
				raise ValueError
			page = self._validate_callback_page(data["page"])
			rule_index = self._rule_index_in_settings(self.host.settings, data["rule_index"])
			rule = self._blacklist_rule(self.host.settings, rule_index)
			if rule.get("id") != data["rule_id"]:
				raise ValueError
		except (KeyError, TypeError, ValueError):
			self.host.tgbot.send_message(message.chat.id, "Правило не найдено.")
			return None
		field = f"{data['kind']}_blacklist"
		values = normalize_words((message.text or "").split(","))
		update_host_settings(self.host, lambda settings: self._blacklist_rule(settings, rule_index).__setitem__(field, values))
		self.host.tg.clear_state(message.chat.id, message.from_user.id, True)
		confirmation = "Черный список сохранен."
		self.host.tgbot.send_message(message.chat.id, confirmation)
		self.show_blacklist_items(
			SimpleNamespace(id=f"save:{message_id}", message=SimpleNamespace(chat=message.chat, id=message_id)),
			rule_index,
			data["kind"],
			page,
		)
		return confirmation

	def _delete_blacklist(self, call: telebot.types.CallbackQuery) -> None:
		try:
			rule_index, kind, page, item_index, token = self._parse_blacklist_item_callback(call.data, CBT_AUTO_DUMPING_BLACKLIST_DELETE)
			rule = self._blacklist_rule(self.host.settings, rule_index)
			field = f"{kind}_blacklist"
			items = rule.get(field, [])
			if item_index >= len(items) or self._blacklist_payloads.pop(token) != (rule_index, kind, page, item_index, items[item_index]):
				raise ValueError
		except ValueError:
			self.host.tgbot.answer_callback_query(call.id, "Элемент не найден.", show_alert=True)
			return
		update_host_settings(self.host, lambda settings: self._blacklist_rule(settings, rule_index)[field].pop(item_index))
		self.show_blacklist_items(call, rule_index, kind, page)

	def _sync_scheduler(self) -> None:
		if self.host.settings["auto_dumping"]["enabled"]:
			self.scheduler.start()
		else:
			self.scheduler.stop()

	def _refresh(self, call: telebot.types.CallbackQuery) -> None:
		self.host.tgbot.answer_callback_query(call.id)
		self.show_main(call.message.chat.id, call.message.id, True)

	@staticmethod
	def _mutate_rule(settings: dict[str, Any], rule_index: int, mutation: Any) -> None:
		index = TelegramAutoDumpingFlow._rule_index_in_settings(settings, rule_index)
		mutation(settings["auto_dumping"]["rules"][index])

	@staticmethod
	def _delete_rule(settings: dict[str, Any], rule_index: int) -> None:
		index = TelegramAutoDumpingFlow._rule_index_in_settings(settings, rule_index)
		del settings["auto_dumping"]["rules"][index]

	def _send_or_edit(self, text: str, chat_id: int, message_id: int | None, keyboard: K, edit: bool) -> None:
		if edit and message_id is not None:
			self.host.tgbot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard)
		else:
			self.host.tgbot.send_message(chat_id, text, reply_markup=keyboard)
