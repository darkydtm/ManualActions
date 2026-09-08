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
		self._rule_payloads = CallbackPayloadCache()
		self._blacklist_navigation_payloads = CallbackPayloadCache()
		self._blacklist_state_payloads = CallbackPayloadCache()
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
		self.host.tg.msg_handler(self.save_interval, func=lambda m: self.host.tg.check_state(m.chat.id, m.from_user.id, STATE_AUTO_DUMPING_INTERVAL), content_types=["text", "photo"])
		self.host.tg.msg_handler(self.save_rule, func=lambda m: self.host.tg.check_state(m.chat.id, m.from_user.id, STATE_AUTO_DUMPING_RULE), content_types=["text", "photo"])
		self.host.tg.msg_handler(self.save_rule_blacklist, func=lambda m: self.host.tg.check_state(m.chat.id, m.from_user.id, STATE_AUTO_DUMPING_SELLERS), content_types=["text", "photo"])
		self.host.tg.msg_handler(self.save_rule_blacklist, func=lambda m: self.host.tg.check_state(m.chat.id, m.from_user.id, STATE_AUTO_DUMPING_KEYWORDS), content_types=["text", "photo"])
		file_handler = getattr(self.host.tg, "file_handler", None)
		if callable(file_handler):
			file_handler(STATE_AUTO_DUMPING_RULE, self.save_rule)
			file_handler(STATE_AUTO_DUMPING_SELLERS, self.save_rule_blacklist)
			file_handler(STATE_AUTO_DUMPING_KEYWORDS, self.save_rule_blacklist)

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

	def _blacklist_item_callback(self, prefix: str, rule_index: int, kind: str, page: int, item_index: int, item: str, rules_page: int = 0) -> str:
		if kind not in ("sellers", "keywords"):
			raise ValueError("invalid callback list kind")
		if not isinstance(item_index, int) or not 0 <= item_index <= MAX_CALLBACK_PAGE:
			raise ValueError("invalid blacklist item")
		rule_index = TelegramAutoDumpingFlow._validate_rule_reference(rule_index)
		page = TelegramAutoDumpingFlow._validate_callback_page(page)
		rules_page = TelegramAutoDumpingFlow._validate_callback_page(rules_page)
		self._rule_index_in_settings(self.host.settings, rule_index)
		rule = self.host.settings["auto_dumping"]["rules"][rule_index]
		rule_id = rule["id"]
		token = self._blacklist_payloads.put((prefix, rule_index, rule_id, rule, kind, page, item_index, item, rules_page))
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

	def _blacklist_navigation_callback(self, prefix: str, rule_index: int, kind: str | None, page: int, rules_page: int) -> str:
		if kind not in (None, "sellers", "keywords"):
			raise ValueError("invalid callback list kind")
		rule_index = TelegramAutoDumpingFlow._validate_rule_reference(rule_index)
		page = TelegramAutoDumpingFlow._validate_callback_page(page)
		rules_page = TelegramAutoDumpingFlow._validate_callback_page(rules_page)
		self._rule_index_in_settings(self.host.settings, rule_index)
		rule = self.host.settings["auto_dumping"]["rules"][rule_index]
		rule_id = rule["id"]
		token = self._blacklist_navigation_payloads.put((prefix, rule_index, rule_id, rule, kind, page, rules_page))
		payload = rule_index.to_bytes(PAGE_TOKEN_BYTES, "big") + int(token, 16).to_bytes(PAGE_TOKEN_BYTES, "big")
		callback = f"{prefix}~{urlsafe_b64encode(payload).decode().rstrip('=')}"
		if len(callback.encode("utf-8")) > 64:
			raise ValueError("callback data exceeds Telegram's 64-byte limit")
		return callback

	def _parse_blacklist_page_callback(self, data: str, prefix: str) -> tuple[int, str | None, int, int, str]:
		if not isinstance(data, str) or not data.startswith(prefix) or not data[len(prefix):].startswith("~"):
			raise ValueError("invalid blacklist page callback")
		token = data[len(prefix) + 1:]
		try:
			payload = urlsafe_b64decode(token + "=" * (-len(token) % 4))
		except (Base64Error, TypeError, ValueError):
			raise ValueError("invalid blacklist page callback") from None
		if (
			any(char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_" for char in token)
			or len(payload) != PAGE_TOKEN_BYTES * 2
			or urlsafe_b64encode(payload).decode().rstrip("=") != token
		):
			raise ValueError("invalid blacklist page callback")
		index = self._validate_rule_reference(int.from_bytes(payload[:PAGE_TOKEN_BYTES], "big"))
		cached = self._blacklist_navigation_payloads.pop(format(int.from_bytes(payload[-PAGE_TOKEN_BYTES:], "big"), "x"))
		if not isinstance(cached, tuple) or len(cached) != 7 or cached[:2] != (prefix, index):
			raise ValueError("invalid blacklist page callback")
		try:
			current_rule = self.host.settings["auto_dumping"]["rules"][index]
			if current_rule is not cached[3] or current_rule.get("id") != cached[2]:
				raise ValueError
			kind = cached[4]
			page = self._validate_callback_page(cached[5])
			rules_page = self._validate_callback_page(cached[6])
		except (IndexError, TypeError, ValueError):
			raise ValueError("invalid blacklist page callback") from None
		if kind not in (None, "sellers", "keywords"):
			raise ValueError("invalid blacklist page callback")
		return index, kind, page, rules_page, cached[2]

	def _rule_id_from_reference(self, rule_index: int) -> str:
		rules = self.host.settings["auto_dumping"]["rules"]
		index = self._rule_index_in_settings(self.host.settings, rule_index)
		return rules[index]["id"]

	@classmethod
	def _rule_index_in_settings(cls, settings: dict[str, Any], rule_index: int, rule_id: str | None = None) -> int:
		index = cls._validate_rule_reference(rule_index)
		if not 0 <= index < len(settings["auto_dumping"]["rules"]):
			raise ValueError("rule reference not found")
		if rule_id is not None and settings["auto_dumping"]["rules"][index].get("id") != rule_id:
			raise ValueError("rule reference not found")
		return index

	def _rule_callback_with_page(self, prefix: str, rule_index: int, page: int) -> str:
		rule_index = self._validate_rule_reference(rule_index)
		page = self._validate_callback_page(page)
		rule_id = self._rule_id_from_reference(rule_index)
		rule = self.host.settings["auto_dumping"]["rules"][rule_index]
		token = self._rule_payloads.put((prefix, rule_index, rule_id, rule, page))
		payload = rule_index.to_bytes(PAGE_TOKEN_BYTES, "big") + int(token, 16).to_bytes(PAGE_TOKEN_BYTES, "big")
		callback = f"{prefix}~{urlsafe_b64encode(payload).decode().rstrip('=')}"
		if len(callback.encode("utf-8")) > 64:
			raise ValueError("callback data exceeds Telegram's 64-byte limit")
		return callback

	def _rule_callback_parts(self, data: str, prefix: str) -> tuple[int, int, str]:
		if not isinstance(data, str) or not data.startswith(prefix) or not data[len(prefix):].startswith("~"):
			raise ValueError("invalid rule callback")
		token = data[len(prefix) + 1:]
		try:
			payload = urlsafe_b64decode(token + "=" * (-len(token) % 4))
		except (Base64Error, TypeError, ValueError):
			raise ValueError("invalid rule callback") from None
		if (
			any(char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_" for char in token)
			or len(payload) != PAGE_TOKEN_BYTES * 2
			or urlsafe_b64encode(payload).decode().rstrip("=") != token
		):
			raise ValueError("invalid rule callback")
		rule_index = self._validate_rule_reference(int.from_bytes(payload[:PAGE_TOKEN_BYTES], "big"))
		cached = self._rule_payloads.pop(format(int.from_bytes(payload[-PAGE_TOKEN_BYTES:], "big"), "x"))
		if not isinstance(cached, tuple) or len(cached) != 5 or cached[:2] != (prefix, rule_index):
			raise ValueError("invalid rule callback")
		try:
			current_rule = self.host.settings["auto_dumping"]["rules"][rule_index]
			if current_rule is not cached[3] or current_rule.get("id") != cached[2]:
				raise ValueError
		except (IndexError, TypeError, ValueError):
			raise ValueError("invalid rule callback") from None
		return rule_index, self._validate_callback_page(cached[4]), cached[2]

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
			rule_reference, kind, page, rules_page, rule_id = self._parse_blacklist_page_callback(call.data, CBT_AUTO_DUMPING_BLACKLIST_PAGE)
			rule_index = self._rule_index_in_settings(self.host.settings, rule_reference)
			if not hasattr(call, "message"):
				self.host.tgbot.answer_callback_query(call.id)
				return
			if kind is None:
				self.show_blacklist(call, rule_reference, rules_page)
			else:
				self.show_blacklist_items(call, rule_reference, kind, page, rules_page)
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
		keyboard.add(B("⚙️ Состояние", callback_data=f"{CBT_AUTO_DUMPING_STATUS}page"))
		keyboard.add(B("⏱ Период", callback_data=self._page_callback(CBT_AUTO_DUMPING_PERIOD_PAGE, chat_id, None, 0)))
		keyboard.add(B("📋 Правила", callback_data=self._page_callback(CBT_AUTO_DUMPING_RULES_PAGE, chat_id, None, 0)))
		keyboard.add(B("▶️ Запустить цикл", callback_data=f"{CBT_AUTO_DUMPING_RUN}{chat_id}"))
		self._send_or_edit(text, chat_id, message_id, keyboard, edit)

	def open_page(self, call: telebot.types.CallbackQuery) -> None:
		self.host.tgbot.answer_callback_query(call.id)
		self.show_main(call.message.chat.id, call.message.id, True)

	def _status_callback(self, call: telebot.types.CallbackQuery) -> None:
		value = call.data.replace(CBT_AUTO_DUMPING_STATUS, "", 1)
		if value == "page" or value.startswith("page:"):
			if value.startswith("page:"):
				try:
					int(value[5:])
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
			f"<b>Состояние автодемпинга</b>\n\nСостояние: <b>{state}</b>",
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
		if value == "cancel":
			self.host.tg.clear_state(call.message.chat.id, call.from_user.id, True)
			self.show_period(call)
			return
		if value == "custom":
			keyboard = K(row_width=1)
			keyboard.add(B("❌ Отмена", callback_data=f"{CBT_AUTO_DUMPING_INTERVAL}cancel"))
			message = self.host.tgbot.send_message(
				call.message.chat.id,
				"Введите период в минутах - целое число от 1.\nНапример: <code>5</code>",
				reply_markup=keyboard,
			)
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
		text = (getattr(message, "text", None) or getattr(message, "caption", None) or "").strip()
		try:
			minutes = int(text)
		except ValueError:
			self.host.tgbot.reply_to(message, "Введите целое число минут от 1. Например: 5")
			return
		if minutes < 1:
			self.host.tgbot.reply_to(message, "Период должен быть от 1 минуты. Например: 5")
			return
		self.host.tg.clear_state(message.chat.id, message.from_user.id, True)
		update_host_settings(self.host, lambda settings: settings["auto_dumping"].__setitem__("interval_minutes", minutes))
		self.scheduler.stop()
		self.scheduler.set_interval(minutes)
		if self.host.settings["auto_dumping"]["enabled"]:
			self.scheduler.start()
		self.host.tgbot.send_message(message.chat.id, f"Период сохранён: {minutes} мин.")

	def _save_interval(self, minutes: int, call: telebot.types.CallbackQuery) -> None:
		if minutes < 1:
			self.host.tgbot.answer_callback_query(call.id, "Период должен быть положительным.", show_alert=True)
			return
		update_host_settings(self.host, lambda settings: settings["auto_dumping"].__setitem__("interval_minutes", minutes))
		self.scheduler.stop()
		self.scheduler.set_interval(minutes)
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
			rule_index, page, rule_id = self._rule_callback_parts(call.data, CBT_AUTO_DUMPING_RULE)
		except ValueError:
			self.host.tgbot.answer_callback_query(call.id, "Правило не найдено.", show_alert=True)
			return
		rule = self.host.settings["auto_dumping"]["rules"][rule_index]
		keyboard = K(row_width=1)
		keyboard.add(B("⏹ Выключить" if rule.get("enabled", True) else "▶️ Включить", callback_data=self._rule_callback_with_page(CBT_AUTO_DUMPING_RULE_TOGGLE, rule_index, page)))
		keyboard.add(B("Черный список", callback_data=self._blacklist_navigation_callback(CBT_AUTO_DUMPING_BLACKLIST_PAGE, rule_index, None, 0, page)))
		keyboard.add(B("🗑 Удалить", callback_data=self._rule_callback_with_page(CBT_AUTO_DUMPING_RULE_DELETE, rule_index, page)))
		keyboard.add(B("◀️ К правилам", callback_data=self._page_callback(CBT_AUTO_DUMPING_RULES_PAGE, call.message.chat.id, None, page)))
		text = f"<b>Правило {escape(str(rule.get('id', '')))}</b>\nПодкатегория: {escape(str(rule.get('subcategory', '')))}\nКлючевые слова: {escape(', '.join(rule.get('keywords', [])))}"
		self.host.tgbot.edit_message_text(text, call.message.chat.id, call.message.id, reply_markup=keyboard)
		self.host.tgbot.answer_callback_query(call.id)

	def toggle_rule(self, call: telebot.types.CallbackQuery) -> None:
		try:
			rule_index, page, rule_id = self._rule_callback_parts(call.data, CBT_AUTO_DUMPING_RULE_TOGGLE)
		except ValueError:
			self.host.tgbot.answer_callback_query(call.id, "Правило не найдено.", show_alert=True)
			return
		update_host_settings(self.host, lambda settings: self._mutate_rule(settings, rule_index, rule_id, lambda rule: rule.__setitem__("enabled", not rule["enabled"])))
		self.show_rule(SimpleNamespace(id=call.id, data=self._rule_callback_with_page(CBT_AUTO_DUMPING_RULE, rule_index, page), message=call.message))

	def delete_rule(self, call: telebot.types.CallbackQuery) -> None:
		try:
			rule_index, page, rule_id = self._rule_callback_parts(call.data, CBT_AUTO_DUMPING_RULE_DELETE)
		except ValueError:
			self.host.tgbot.answer_callback_query(call.id, "Правило не найдено.", show_alert=True)
			return
		update_host_settings(self.host, lambda settings: self._delete_rule(settings, rule_index, rule_id))
		self.show_rules(call, page)

	def add_rule(self, call: telebot.types.CallbackQuery) -> None:
		value = call.data.replace(CBT_AUTO_DUMPING_RULE_ADD, "", 1)
		if value != str(call.message.chat.id):
			self._rule_step_callback(call)
			return
		data: dict[str, Any] = {"step": "subcategory", "rule": {}}
		self._ask_rule(
			call.message.chat.id,
			call.from_user.id,
			data,
			"<b>Новое правило - шаг 1/7</b>\n\nВведите подкатегорию FunPay - точное название раздела.\nНапример: <code>Золото</code>",
			self._rule_cancel_keyboard(),
		)
		self.host.tgbot.answer_callback_query(call.id)

	@staticmethod
	def _rule_cancel_keyboard() -> K:
		keyboard = K(row_width=1)
		keyboard.add(B("❌ Отмена", callback_data=f"{CBT_AUTO_DUMPING_RULE_ADD}cancel"))
		return keyboard

	@staticmethod
	def _keyword_mode_keyboard() -> K:
		keyboard = K(row_width=2)
		keyboard.add(B("🔎 Любое слово", callback_data=f"{CBT_AUTO_DUMPING_RULE_ADD}mode:any"), B("🔎 Все слова", callback_data=f"{CBT_AUTO_DUMPING_RULE_ADD}mode:all"))
		keyboard.add(B("❌ Отмена", callback_data=f"{CBT_AUTO_DUMPING_RULE_ADD}cancel"))
		return keyboard

	@staticmethod
	def _price_mode_keyboard() -> K:
		keyboard = K(row_width=2)
		keyboard.add(B("💵 Сумма в рублях", callback_data=f"{CBT_AUTO_DUMPING_RULE_ADD}price:fixed"), B("📉 Процент", callback_data=f"{CBT_AUTO_DUMPING_RULE_ADD}price:percent"))
		keyboard.add(B("❌ Отмена", callback_data=f"{CBT_AUTO_DUMPING_RULE_ADD}cancel"))
		return keyboard

	@staticmethod
	def _confirm_keyboard() -> K:
		keyboard = K(row_width=2)
		keyboard.add(B("✅ Сохранить", callback_data=f"{CBT_AUTO_DUMPING_RULE_ADD}confirm"), B("❌ Отмена", callback_data=f"{CBT_AUTO_DUMPING_RULE_ADD}cancel"))
		return keyboard

	def _ask_rule(self, chat_id: int, user_id: int, data: dict[str, Any], text: str, keyboard: K | None = None) -> None:
		sent = self.host.tgbot.send_message(chat_id, text, reply_markup=keyboard)
		data["prompt_id"] = getattr(sent, "id", data.get("prompt_id"))
		self.host.tg.set_state(chat_id, data["prompt_id"], user_id, STATE_AUTO_DUMPING_RULE, data)

	def _input_text(self, message: telebot.types.Message) -> str | None:
		document = getattr(message, "document", None)
		text = getattr(message, "text", None) or getattr(message, "caption", None) or ""
		if document is not None and not text.strip():
			filename = str(getattr(document, "file_name", "") or "")
			if not filename.lower().endswith(".txt"):
				self.host.tgbot.reply_to(message, "Пришлите текст сообщением или файл .txt.")
				return None
			try:
				file_info = self.host.tgbot.get_file(document.file_id)
				content = self.host.tgbot.download_file(file_info.file_path)
				text = content.decode("utf-8-sig")
			except Exception:
				self.host.tgbot.reply_to(message, "Не удалось прочитать файл. Пришлите текст сообщением.")
				return None
		return text.strip()

	@staticmethod
	def _parse_amount(text: str) -> float | None:
		try:
			return float(text.replace(",", ".").replace(" ", ""))
		except (TypeError, ValueError):
			return None

	def save_rule(self, message: telebot.types.Message) -> None:
		state = self.host.tg.get_state(message.chat.id, message.from_user.id) or {}
		data = state.get("data", {})
		if not isinstance(data, dict):
			return
		rule = data.get("rule")
		if not isinstance(rule, dict):
			return
		step = data.get("step")
		text = self._input_text(message)
		if text is None:
			return
		chat_id, user_id = message.chat.id, message.from_user.id
		if step == "subcategory":
			first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
			if not first_line:
				self.host.tgbot.reply_to(message, "Подкатегория не может быть пустой. Например: Золото")
				return
			rule["subcategory"] = first_line
			data["step"] = "keywords"
			self._ask_rule(
				chat_id,
				user_id,
				data,
				"<b>Шаг 2/7</b>\n\nВведите ключевые слова через запятую, с новой строки или файлом .txt.\nНапример: <code>gemini, pro, 18 месяцев</code>",
				self._rule_cancel_keyboard(),
			)
			return
		elif step == "keywords":
			keywords = normalize_words(text.replace("\n", ",").split(","))
			if not keywords:
				self.host.tgbot.reply_to(message, "Нужно хотя бы одно ключевое слово. Например: gemini, pro")
				return
			rule["keywords"] = keywords
			data["step"] = "keyword_mode"
			self._ask_rule(
				chat_id,
				user_id,
				data,
				"<b>Шаг 3/7</b>\n\nКогда срабатывать правилу - при любом совпадении или только когда в названии есть все слова?",
				self._keyword_mode_keyboard(),
			)
			return
		elif step in ("dumping_value", "competitor_min_price", "own_min_price"):
			value = self._parse_amount(text)
			positive = step == "dumping_value"
			if value is None or (value <= 0 if positive else value < 0):
				if positive:
					example = "Например: 10 (процентов)" if rule.get("price_mode") == "percent" else "Например: 5 (рублей)"
					self.host.tgbot.reply_to(message, f"Введите положительное число. {example}")
				else:
					self.host.tgbot.reply_to(message, "Введите 0 или больше. Например: 100")
				return
			rule[step] = value
			next_step = {"dumping_value": "competitor_min_price", "competitor_min_price": "own_min_price", "own_min_price": "confirm"}[step]
			data["step"] = next_step
			if next_step == "confirm":
				self._ask_rule(chat_id, user_id, data, self._rule_summary(rule), self._confirm_keyboard())
			elif next_step == "competitor_min_price":
				self._ask_rule(
					chat_id,
					user_id,
					data,
					"<b>Шаг 6/7</b>\n\nНиже какой цены конкурента не опускаться? 0 - без ограничения.\nНапример: <code>100</code>",
					self._rule_cancel_keyboard(),
				)
			else:
				self._ask_rule(
					chat_id,
					user_id,
					data,
					"<b>Шаг 7/7</b>\n\nНиже какой своей цены не опускаться? 0 - без ограничения.\nНапример: <code>50</code>",
					self._rule_cancel_keyboard(),
				)
			return
		elif step == "keyword_mode":
			self._ask_rule(
				chat_id,
				user_id,
				data,
				"<b>Шаг 3/7</b>\n\nВыберите кнопкой: любое слово или все слова?",
				self._keyword_mode_keyboard(),
			)
			return
		elif step == "price_mode":
			self._ask_rule(
				chat_id,
				user_id,
				data,
				"<b>Шаг 4/7</b>\n\nКак снижать цену: фиксированной суммой или процентом?",
				self._price_mode_keyboard(),
			)
			return
		self.host.tgbot.reply_to(message, "Создание правила прервано: неизвестный шаг. Начните заново.")
		self.host.tg.clear_state(chat_id, user_id, True)

	def _rule_step_callback(self, call: telebot.types.CallbackQuery) -> None:
		value = call.data.replace(CBT_AUTO_DUMPING_RULE_ADD, "", 1)
		state = self.host.tg.get_state(call.message.chat.id, call.from_user.id) or {}
		data = state.get("data", {})
		rule = data.get("rule", {})
		if value == "cancel":
			self.host.tg.clear_state(call.message.chat.id, call.from_user.id, True)
			self.show_rules(call)
			return
		if value in ("mode:any", "mode:all"):
			if not isinstance(data, dict) or not isinstance(rule, dict):
				self.host.tgbot.answer_callback_query(call.id, "Создание правила истекло. Начните заново.", show_alert=True)
				return
			rule["keyword_mode"] = value.split(":", 1)[1]
			data["step"] = "price_mode"
			self._ask_rule(
				call.message.chat.id,
				call.from_user.id,
				data,
				"<b>Шаг 4/7</b>\n\nКак снижать цену: фиксированной суммой в рублях или процентом?",
				self._price_mode_keyboard(),
			)
		elif value in ("price:fixed", "price:percent"):
			if not isinstance(data, dict) or not isinstance(rule, dict):
				self.host.tgbot.answer_callback_query(call.id, "Создание правила истекло. Начните заново.", show_alert=True)
				return
			rule["price_mode"] = value.split(":", 1)[1]
			data["step"] = "dumping_value"
			example = "Например: <code>10</code>" if rule["price_mode"] == "percent" else "Например: <code>5</code>"
			unit = "процентов" if rule["price_mode"] == "percent" else "рублей"
			self._ask_rule(
				call.message.chat.id,
				call.from_user.id,
				data,
				f"<b>Шаг 5/7</b>\n\nНа сколько {unit} опускаться ниже конкурента?\n{example}",
				self._rule_cancel_keyboard(),
			)
		elif value == "confirm":
			rule["id"] = uuid4().hex
			try:
				rule = validate_rule_input(rule)
			except ValueError as exc:
				self.host.tgbot.answer_callback_query(call.id, str(exc), show_alert=True)
				return
			update_host_settings(self.host, lambda settings: settings["auto_dumping"]["rules"].append(rule))
			self.host.tg.clear_state(call.message.chat.id, call.from_user.id, True)
			self.host.tgbot.send_message(call.message.chat.id, f"Правило сохранено: {rule['subcategory']}: {', '.join(rule['keywords'])}")
		else:
			self.host.tgbot.answer_callback_query(call.id, "Некорректный шаг.", show_alert=True)
			return
		self.host.tgbot.answer_callback_query(call.id)

	@staticmethod
	def _rule_summary(rule: dict[str, Any]) -> str:
		return (
			"<b>Проверьте правило</b>\n\n"
			f"Подкатегория: <code>{escape(str(rule.get('subcategory', '')))}</code>\n"
			f"Ключевые слова: <code>{escape(', '.join(rule.get('keywords', [])))}</code>\n"
			f"Совпадение: <code>{'все' if rule.get('keyword_mode') == 'all' else 'любое'}</code>\n"
			f"Демпинг: <code>{rule.get('dumping_value')} {'%' if rule.get('price_mode') == 'percent' else '₽'}</code>\n"
			f"Минимум конкурента: <code>{rule.get('competitor_min_price')}</code>\n"
			f"Минимум своего лота: <code>{rule.get('own_min_price')}</code>"
		)

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
		keyboard.add(B("Продавцы", callback_data=self._blacklist_navigation_callback(CBT_AUTO_DUMPING_BLACKLIST_PAGE, rule_index, "sellers", 0, page)))
		keyboard.add(B("Ключевые слова", callback_data=self._blacklist_navigation_callback(CBT_AUTO_DUMPING_BLACKLIST_PAGE, rule_index, "keywords", 0, page)))
		keyboard.add(B("◀️ Назад", callback_data=self._rule_callback_with_page(CBT_AUTO_DUMPING_RULE, rule_index, page)))
		self.host.tgbot.edit_message_text("<b>Черный список правила</b>", call.message.chat.id, call.message.id, reply_markup=keyboard)
		self.host.tgbot.answer_callback_query(call.id)

	def show_blacklist_items(self, call: telebot.types.CallbackQuery, rule_id: int | str, kind: str, page: int, rules_page: int = 0) -> None:
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
		rules_page = self._validate_callback_page(rules_page)
		keyboard = K(row_width=1)
		for offset, item in enumerate(items, page * PAGE_SIZE):
			keyboard.add(B(f"{item}  ✖️", callback_data=self._blacklist_item_callback(CBT_AUTO_DUMPING_BLACKLIST_DELETE, rule_index, kind, page, offset, item, rules_page)))
		keyboard.add(B("➕ Добавить", callback_data=self._blacklist_navigation_callback(CBT_AUTO_DUMPING_BLACKLIST_ADD, rule_index, kind, page, rules_page)))
		keyboard.row(
			B("◀️", callback_data=self._blacklist_navigation_callback(CBT_AUTO_DUMPING_BLACKLIST_PAGE, rule_index, kind, max(page - 1, 0), rules_page)),
			B(f"{page + 1}/{pages}", callback_data=self._blacklist_navigation_callback(CBT_AUTO_DUMPING_BLACKLIST_PAGE, rule_index, kind, page, rules_page)),
			B("▶️", callback_data=self._blacklist_navigation_callback(CBT_AUTO_DUMPING_BLACKLIST_PAGE, rule_index, kind, min(page + 1, pages - 1), rules_page)),
			B("◀️ Назад", callback_data=self._blacklist_navigation_callback(CBT_AUTO_DUMPING_BLACKLIST_PAGE, rule_index, None, 0, rules_page)),
		)
		self.host.tgbot.edit_message_text(
			f"<b>{'Продавцы' if kind == 'sellers' else 'Ключевые слова'}</b>\nВсего: {len(rule.get(field, []))}",
			call.message.chat.id,
			call.message.id,
			reply_markup=keyboard,
		)
		self.host.tgbot.answer_callback_query(call.id)

	def _add_blacklist(self, call: telebot.types.CallbackQuery) -> None:
		if call.data == f"{CBT_AUTO_DUMPING_BLACKLIST_ADD}cancel":
			state = self.host.tg.get_state(call.message.chat.id, call.from_user.id) or {}
			data = state.get("data", {})
			self.host.tg.clear_state(call.message.chat.id, call.from_user.id, True)
			try:
				rule_index = self._rule_index_in_settings(self.host.settings, data["rule_index"])
				kind = data["kind"]
				page = self._validate_callback_page(data["page"])
				rules_page = self._validate_callback_page(data.get("rules_page", 0))
				if kind not in ("sellers", "keywords"):
					raise ValueError
			except (KeyError, TypeError, ValueError):
				self.host.tgbot.answer_callback_query(call.id, "Отменено.")
				return
			self.show_blacklist_items(call, rule_index, kind, page, rules_page)
			return
		try:
			rule_index, kind, page, rules_page, rule_id = self._parse_blacklist_page_callback(call.data, CBT_AUTO_DUMPING_BLACKLIST_ADD)
			if kind not in ("sellers", "keywords"):
				raise ValueError
		except ValueError:
			self.host.tgbot.answer_callback_query(call.id, "Правило не найдено.", show_alert=True)
			return
		state = STATE_AUTO_DUMPING_SELLERS if kind == "sellers" else STATE_AUTO_DUMPING_KEYWORDS
		cancel_keyboard = K(row_width=1)
		cancel_keyboard.add(B("❌ Отмена", callback_data=f"{CBT_AUTO_DUMPING_BLACKLIST_ADD}cancel"))
		hint = "продавцов" if kind == "sellers" else "стоп-слов"
		message = self.host.tgbot.send_message(
			call.message.chat.id,
			f"Введите {hint} через запятую, с новой строки или файлом .txt.\nЧтобы очистить список, отправьте <code>-</code>.",
			reply_markup=cancel_keyboard,
		)
		rule = self.host.settings["auto_dumping"]["rules"][rule_index]
		state_token = self._blacklist_state_payloads.put((CBT_AUTO_DUMPING_BLACKLIST_ADD, rule_index, rule_id, rule, kind, page, rules_page))
		self.host.tg.set_state(call.message.chat.id, message.id, call.from_user.id, state, {
			"rule_id": rule_id,
			"rule_index": rule_index,
			"rule_token": state_token,
			"kind": kind,
			"page": page,
			"message_id": call.message.id,
		})
		if rules_page:
			self.host.tg.get_state(call.message.chat.id, call.from_user.id)["data"]["rules_page"] = rules_page
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
			rules_page = self._validate_callback_page(data.get("rules_page", 0))
			rule_index = self._rule_index_in_settings(self.host.settings, data["rule_index"])
			rule = self._blacklist_rule(self.host.settings, rule_index)
			cached = self._blacklist_state_payloads.pop(data["rule_token"])
			if (
				not isinstance(cached, tuple)
				or len(cached) != 7
				or cached[:3] != (CBT_AUTO_DUMPING_BLACKLIST_ADD, rule_index, data["rule_id"])
				or cached[3] is not rule
				or cached[4:] != (data["kind"], data["page"], data.get("rules_page", 0))
			):
				raise ValueError
		except (KeyError, TypeError, ValueError):
			self.host.tgbot.send_message(message.chat.id, "Правило не найдено.")
			return None
		field = f"{data['kind']}_blacklist"
		text = self._input_text(message)
		if text is None:
			return
		current = self._blacklist_rule(self.host.settings, rule_index)
		if text == "-":
			values = []
		else:
			values = normalize_words([*current.get(field, []), *normalize_words(text.replace("\n", ",").split(","))])
		update_host_settings(self.host, lambda settings: self._blacklist_rule(settings, rule_index).__setitem__(field, values))
		self.host.tg.clear_state(message.chat.id, message.from_user.id, True)
		confirmation = "Черный список сохранен."
		self.host.tgbot.send_message(message.chat.id, confirmation)
		self.show_blacklist_items(
			SimpleNamespace(id=f"save:{message_id}", message=SimpleNamespace(chat=message.chat, id=message_id)),
			rule_index,
			data["kind"],
			page,
			rules_page,
		)
		return confirmation

	def _delete_blacklist(self, call: telebot.types.CallbackQuery) -> None:
		try:
			rule_index, kind, page, item_index, token = self._parse_blacklist_item_callback(call.data, CBT_AUTO_DUMPING_BLACKLIST_DELETE)
			rule = self._blacklist_rule(self.host.settings, rule_index)
			field = f"{kind}_blacklist"
			items = rule.get(field, [])
			cached = self._blacklist_payloads.pop(token)
			if (
				not isinstance(cached, tuple)
				or len(cached) != 9
				or item_index >= len(items)
				or cached[:3] != (CBT_AUTO_DUMPING_BLACKLIST_DELETE, rule_index, rule.get("id"))
				or cached[3] is not rule
				or cached[4:7] != (kind, page, item_index)
				or cached[7] != items[item_index]
			):
				raise ValueError
			rules_page = self._validate_callback_page(cached[8])
		except ValueError:
			self.host.tgbot.answer_callback_query(call.id, "Элемент не найден.", show_alert=True)
			return
		update_host_settings(self.host, lambda settings: self._blacklist_rule(settings, rule_index)[field].pop(item_index))
		self.show_blacklist_items(call, rule_index, kind, page, rules_page)

	def _sync_scheduler(self) -> None:
		if self.host.settings["auto_dumping"]["enabled"]:
			self.scheduler.start()
		else:
			self.scheduler.stop()

	def _refresh(self, call: telebot.types.CallbackQuery) -> None:
		self.host.tgbot.answer_callback_query(call.id)
		self.show_main(call.message.chat.id, call.message.id, True)

	@staticmethod
	def _mutate_rule(settings: dict[str, Any], rule_index: int, rule_id: str, mutation: Any) -> None:
		index = TelegramAutoDumpingFlow._rule_index_in_settings(settings, rule_index, rule_id)
		mutation(settings["auto_dumping"]["rules"][index])

	@staticmethod
	def _delete_rule(settings: dict[str, Any], rule_index: int, rule_id: str) -> None:
		index = TelegramAutoDumpingFlow._rule_index_in_settings(settings, rule_index, rule_id)
		del settings["auto_dumping"]["rules"][index]

	def _send_or_edit(self, text: str, chat_id: int, message_id: int | None, keyboard: K, edit: bool) -> None:
		if edit and message_id is not None:
			self.host.tgbot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard)
		else:
			self.host.tgbot.send_message(chat_id, text, reply_markup=keyboard)
