from __future__ import annotations

from base64 import urlsafe_b64decode, urlsafe_b64encode
from html import escape
from math import ceil
from string import hexdigits
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
	STATE_AUTO_DUMPING_RULE,
)
from ...runtime.settings import update_host_settings
from .settings import INTERVAL_PRESETS, normalize_rule


PAGE_SIZE = 5


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

	def register(self) -> None:
		if not self.host.tg:
			return
		self.host.tg.cbq_handler(self.open_page, lambda c: (c.data or "").startswith(CBT_AUTO_DUMPING_PAGE))
		self.host.tg.cbq_handler(self.toggle, lambda c: (c.data or "").startswith(CBT_AUTO_DUMPING_TOGGLE))
		self.host.tg.cbq_handler(self.set_interval, lambda c: (c.data or "").startswith(CBT_AUTO_DUMPING_INTERVAL))
		self.host.tg.cbq_handler(self.run_now, lambda c: (c.data or "").startswith(CBT_AUTO_DUMPING_RUN))
		self.host.tg.cbq_handler(self.open_rules, lambda c: (c.data or "").startswith(CBT_AUTO_DUMPING_RULES))
		self.host.tg.cbq_handler(self.show_rule, lambda c: (c.data or "").startswith(CBT_AUTO_DUMPING_RULE))
		self.host.tg.cbq_handler(self.toggle_rule, lambda c: (c.data or "").startswith(CBT_AUTO_DUMPING_RULE_TOGGLE))
		self.host.tg.cbq_handler(self.delete_rule, lambda c: (c.data or "").startswith(CBT_AUTO_DUMPING_RULE_DELETE))
		self.host.tg.cbq_handler(self.add_rule, lambda c: (c.data or "").startswith(CBT_AUTO_DUMPING_RULE_ADD))
		for prefix in (
			CBT_AUTO_DUMPING_STATUS,
			CBT_AUTO_DUMPING_PERIOD_PAGE,
			CBT_AUTO_DUMPING_RULES_PAGE,
			CBT_AUTO_DUMPING_BLACKLIST_PAGE,
			CBT_AUTO_DUMPING_BLACKLIST_DELETE,
			CBT_AUTO_DUMPING_BLACKLIST_ADD,
		):
			self.host.tg.cbq_handler(self._pending_callback, lambda c, prefix=prefix: (c.data or "").startswith(prefix))
		self.host.tg.msg_handler(self.save_interval, func=lambda m: self.host.tg.check_state(m.chat.id, m.from_user.id, STATE_AUTO_DUMPING_INTERVAL))
		self.host.tg.msg_handler(self.save_rule, func=lambda m: self.host.tg.check_state(m.chat.id, m.from_user.id, STATE_AUTO_DUMPING_RULE))

	@staticmethod
	def _page_items(items: list[Any], page: int) -> tuple[list[Any], int]:
		try:
			page = max(int(page), 0)
		except (TypeError, ValueError):
			page = 0
		pages = max(1, ceil(len(items) / PAGE_SIZE))
		page = min(page, pages - 1)
		start = page * PAGE_SIZE
		return items[start:start + PAGE_SIZE], pages

	@staticmethod
	def _page_callback(prefix: str, context: str, page: int) -> str:
		try:
			page = max(int(page), 0)
		except (TypeError, ValueError):
			page = 0
		parts = str(context).split(":")
		if len(parts) > 1 and parts[-1] in ("sellers", "keywords"):
			rule_id = parts[-2]
			if len(rule_id) == 32 and all(char in hexdigits for char in rule_id):
				parts[-2] = urlsafe_b64encode(bytes.fromhex(rule_id)).decode().rstrip("=")
		context = ":".join(parts)
		return f"{prefix}{context}:{page}"

	@staticmethod
	def _parse_page_callback(data: str, prefix: str) -> tuple[str, int]:
		if not isinstance(data, str) or not data.startswith(prefix):
			return "", 0
		payload = data[len(prefix):]
		context, separator, page = payload.rpartition(":")
		if not separator:
			return TelegramAutoDumpingFlow._expand_rule_context(payload), 0
		try:
			page = max(int(page), 0)
		except (TypeError, ValueError):
			page = 0
		return TelegramAutoDumpingFlow._expand_rule_context(context), page

	@staticmethod
	def _expand_rule_context(context: str) -> str:
		parts = context.split(":")
		if len(parts) > 1 and parts[-1] in ("sellers", "keywords"):
			token = parts[-2]
			if len(token) != 22 or any(char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_" for char in token):
				return context
			try:
				rule_id = urlsafe_b64decode(token + "=" * (-len(token) % 4)).hex()
			except (ValueError, TypeError):
				return context
			if len(rule_id) == 32:
				parts[-2] = rule_id
		return ":".join(parts)

	def _pending_callback(self, call: telebot.types.CallbackQuery) -> None:
		self.host.tgbot.answer_callback_query(call.id)

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
		keyboard.add(B("⏹ Выключить" if settings["enabled"] else "▶️ Включить", callback_data=f"{CBT_AUTO_DUMPING_TOGGLE}{chat_id}"))
		keyboard.add(B("⏱ 1 мин.", callback_data=f"{CBT_AUTO_DUMPING_INTERVAL}1"))
		keyboard.add(B("⏱ Период", callback_data=f"{CBT_AUTO_DUMPING_INTERVAL}page:{chat_id}"))
		keyboard.add(B("📋 Правила", callback_data=f"{CBT_AUTO_DUMPING_RULES}{chat_id}"))
		keyboard.add(B("▶️ Запустить цикл", callback_data=f"{CBT_AUTO_DUMPING_RUN}{chat_id}"))
		self._send_or_edit(text, chat_id, message_id, keyboard, edit)

	def open_page(self, call: telebot.types.CallbackQuery) -> None:
		self.host.tgbot.answer_callback_query(call.id)
		self.show_main(call.message.chat.id, call.message.id, True)

	def toggle(self, call: telebot.types.CallbackQuery) -> None:
		update_host_settings(self.host, lambda settings: settings["auto_dumping"].__setitem__("enabled", not settings["auto_dumping"]["enabled"]))
		self._refresh(call)
		self._sync_scheduler()

	def set_interval(self, call: telebot.types.CallbackQuery) -> None:
		value = call.data.replace(CBT_AUTO_DUMPING_INTERVAL, "", 1)
		if value.startswith("page:"):
			keyboard = K(row_width=2)
			for minutes in INTERVAL_PRESETS:
				keyboard.add(B(f"{minutes} мин.", callback_data=f"{CBT_AUTO_DUMPING_INTERVAL}{minutes}"))
			keyboard.add(B("Своё значение", callback_data=f"{CBT_AUTO_DUMPING_INTERVAL}custom"))
			self.host.tgbot.edit_message_text("<b>Период автодемпинга</b>", call.message.chat.id, call.message.id, reply_markup=keyboard)
			self.host.tgbot.answer_callback_query(call.id)
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
		keyboard = K(row_width=1)
		for rule in self.host.settings["auto_dumping"]["rules"]:
			keyboard.add(B(rule["subcategory"] + ": " + ", ".join(rule["keywords"]), callback_data=f"{CBT_AUTO_DUMPING_RULE}{rule['id']}"))
		keyboard.add(B("➕ Добавить правило", callback_data=f"{CBT_AUTO_DUMPING_RULE_ADD}{call.message.chat.id}"))
		keyboard.add(B("◀️ Назад", callback_data=f"{CBT_AUTO_DUMPING_PAGE}{call.message.chat.id}"))
		self.host.tgbot.edit_message_text("<b>Правила автодемпинга</b>", call.message.chat.id, call.message.id, reply_markup=keyboard)
		self.host.tgbot.answer_callback_query(call.id)

	def show_rule(self, call: telebot.types.CallbackQuery) -> None:
		rule = self._find_rule(call.data.replace(CBT_AUTO_DUMPING_RULE, "", 1))
		if not rule:
			self.host.tgbot.answer_callback_query(call.id, "Правило не найдено.", show_alert=True)
			return
		keyboard = K(row_width=1)
		keyboard.add(B("⏹ Выключить" if rule["enabled"] else "▶️ Включить", callback_data=f"{CBT_AUTO_DUMPING_RULE_TOGGLE}{rule['id']}"))
		keyboard.add(B("🗑 Удалить", callback_data=f"{CBT_AUTO_DUMPING_RULE_DELETE}{rule['id']}"))
		keyboard.add(B("◀️ К правилам", callback_data=f"{CBT_AUTO_DUMPING_RULES}{call.message.chat.id}"))
		text = f"<b>Правило {escape(rule['id'])}</b>\nПодкатегория: {escape(rule['subcategory'])}\nКлючевые слова: {escape(', '.join(rule['keywords']))}"
		self.host.tgbot.edit_message_text(text, call.message.chat.id, call.message.id, reply_markup=keyboard)
		self.host.tgbot.answer_callback_query(call.id)

	def toggle_rule(self, call: telebot.types.CallbackQuery) -> None:
		rule_id = call.data.replace(CBT_AUTO_DUMPING_RULE_TOGGLE, "", 1)
		update_host_settings(self.host, lambda settings: self._mutate_rule(settings, rule_id, lambda rule: rule.__setitem__("enabled", not rule["enabled"])))
		self._refresh(call)

	def delete_rule(self, call: telebot.types.CallbackQuery) -> None:
		rule_id = call.data.replace(CBT_AUTO_DUMPING_RULE_DELETE, "", 1)
		update_host_settings(self.host, lambda settings: settings["auto_dumping"].__setitem__("rules", [rule for rule in settings["auto_dumping"]["rules"] if rule["id"] != rule_id]))
		self.open_rules(call)

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

	def _sync_scheduler(self) -> None:
		if self.host.settings["auto_dumping"]["enabled"]:
			self.scheduler.start()
		else:
			self.scheduler.stop()

	def _refresh(self, call: telebot.types.CallbackQuery) -> None:
		self.host.tgbot.answer_callback_query(call.id)
		self.show_main(call.message.chat.id, call.message.id, True)

	def _find_rule(self, rule_id: str) -> dict[str, Any] | None:
		return next((rule for rule in self.host.settings["auto_dumping"]["rules"] if rule["id"] == rule_id), None)

	@staticmethod
	def _mutate_rule(settings: dict[str, Any], rule_id: str, mutation: Any) -> None:
		rule = next(rule for rule in settings["auto_dumping"]["rules"] if rule["id"] == rule_id)
		mutation(rule)

	def _send_or_edit(self, text: str, chat_id: int, message_id: int | None, keyboard: K, edit: bool) -> None:
		if edit and message_id is not None:
			self.host.tgbot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard)
		else:
			self.host.tgbot.send_message(chat_id, text, reply_markup=keyboard)
