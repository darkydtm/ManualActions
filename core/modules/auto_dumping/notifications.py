from __future__ import annotations

from html import escape
from typing import Any, Callable

from .models import PriceDecision


class ConflictNotifier:
	def __init__(self, admin_notifier: Callable[[str], None] | None = None):
		self.admin_notifier = admin_notifier

	def notify_detected(self, decision: PriceDecision) -> None:
		self._send(self._text("обнаружен", decision))

	def notify_applied(self, decision: PriceDecision) -> None:
		self._send(self._text("применен", decision))

	def _send(self, text: str) -> None:
		if self.admin_notifier:
			self.admin_notifier(text)

	@staticmethod
	def _text(action: str, decision: PriceDecision) -> str:
		return (
			f"<b>Автодемпинг: конфликт {action}</b>\n"
			f"Лот: <code>{escape(decision.own_lot.id)}</code>\n"
			f"Правило: <code>{escape(decision.candidate.rule.id)}</code>\n"
			f"Цена: <b>{decision.candidate.final_price}</b>"
		)
