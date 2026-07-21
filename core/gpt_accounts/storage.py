from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
from pathlib import Path
import tempfile
from threading import RLock
import time
from typing import Any, Callable, Iterable

from ..config.constants import GPT_ACCOUNTS_DELIVERY_FILE, LOGGER_NAME, LOGGER_PREFIX
from .settings import Account

import logging


logger = logging.getLogger(LOGGER_NAME)

STATUS_RESERVED = "reserved"
STATUS_WAITING_STOCK = "waiting_stock"
STATUS_COMPLETED = "completed"
STATUS_SEND_FAILED = "send_failed"
STATUS_RETRYABLE = "retryable"


@dataclass(frozen=True)
class OrderReservationRequest:
	order_id: str
	requested_amount: int
	buyer_username: str = ""
	fp_chat_id: int | str | None = None


@dataclass(frozen=True)
class ReservationResult:
	order_id: str
	status: str
	accounts: tuple[Account, ...]
	requested_amount: int
	shortage: bool


class GptAccountsDeliveryStorage:
	def __init__(self, path: str | Path = GPT_ACCOUNTS_DELIVERY_FILE, time_func: Callable[[], float] = time.time):
		self.path = Path(path)
		self.time_func = time_func
		self.lock = RLock()
		self.state = self.default_state()
		self.writable = True
		self.load()

	def load(self) -> dict[str, Any]:
		with self.lock:
			if not self.path.exists():
				self.state = self.default_state()
				self.writable = True
				return deepcopy(self.state)
			try:
				self.state = self.normalize_state(json.loads(self.path.read_text(encoding="utf-8")))
				self.writable = True
			except Exception:
				self.state = self.default_state()
				self.writable = False
				logger.warning(f"{LOGGER_PREFIX} Failed to load {self.path}.")
			return deepcopy(self.state)

	def stock_accounts(self) -> tuple[Account, ...]:
		with self.lock:
			return tuple(self.account(value) for value in self.state["stock"])

	def stock_count(self) -> int:
		with self.lock:
			return len(self.state["stock"])

	def existing_active_emails(self) -> set[str]:
		with self.lock:
			return self.active_emails(self.state)

	def add_accounts(self, accounts: Iterable[Account]) -> int:
		def mutate(state: dict[str, Any]) -> int:
			emails = self.active_emails(state)
			added = 0
			for account in accounts:
				if account.email.casefold() in emails:
					continue
				state["stock"].append(self.serialize_account(account))
				emails.add(account.email.casefold())
				added += 1
			return added
		return self.mutate(mutate)

	def remove_stock_account(self, email: str) -> bool:
		def mutate(state: dict[str, Any]) -> bool:
			for index, item in enumerate(state["stock"]):
				if self.account(item).email.casefold() == email.casefold():
					state["stock"].pop(index)
					return True
			return False
		return self.mutate(mutate)

	def clear_stock(self) -> int:
		def mutate(state: dict[str, Any]) -> int:
			count = len(state["stock"])
			state["stock"] = []
			return count
		return self.mutate(mutate)

	def reserve(self, request: OrderReservationRequest, shortage_mode: str) -> ReservationResult:
		order_id = str(request.order_id).strip().lstrip("#")
		requested = max(int(request.requested_amount), 1)
		def mutate(state: dict[str, Any]) -> ReservationResult:
			order = state["orders"].get(order_id)
			if order and order["status"] in (STATUS_RESERVED, STATUS_COMPLETED, STATUS_SEND_FAILED):
				return self.reservation_result(order)
			now = self.time_func()
			if not order:
				order = {
					"order_id": order_id, "status": STATUS_RETRYABLE, "requested_amount": requested,
					"buyer_username": request.buyer_username, "fp_chat_id": request.fp_chat_id,
					"reserved_accounts": [], "last_error": "", "shortage_notified": False,
					"created_at": now, "updated_at": now,
				}
				state["orders"][order_id] = order
			else:
				order["buyer_username"] = request.buyer_username or order.get("buyer_username", "")
				if request.fp_chat_id is not None:
					order["fp_chat_id"] = request.fp_chat_id
			available = len(state["stock"])
			take_count = 0 if shortage_mode == "all_or_nothing" and available < requested else min(available, requested)
			order["reserved_accounts"] = state["stock"][:take_count]
			state["stock"] = state["stock"][take_count:]
			order["status"] = STATUS_RESERVED if take_count else STATUS_WAITING_STOCK
			order["last_error"] = ""
			order["updated_at"] = now
			return self.reservation_result(order)
		return self.mutate(mutate)

	def restore_reservation(self, order_id: str, error: str) -> None:
		def mutate(state: dict[str, Any]) -> None:
			order = self.require_order(state, order_id)
			state["stock"] = list(order["reserved_accounts"]) + state["stock"]
			order["reserved_accounts"] = []
			order["status"] = STATUS_RETRYABLE
			order["last_error"] = error
			order["updated_at"] = self.time_func()
		self.mutate(mutate)

	def mark_completed(self, order_id: str) -> None:
		self.update_order(order_id, STATUS_COMPLETED, "")

	def mark_send_failed(self, order_id: str, error: str) -> None:
		self.update_order(order_id, STATUS_SEND_FAILED, error)

	def record_error(self, request: OrderReservationRequest, error: str) -> bool:
		def mutate(state: dict[str, Any]) -> bool:
			order = state["orders"].get(request.order_id)
			changed = not order or order.get("last_error") != error
			if not order:
				now = self.time_func()
				order = {"order_id": request.order_id, "status": STATUS_RETRYABLE, "requested_amount": request.requested_amount, "buyer_username": request.buyer_username, "fp_chat_id": request.fp_chat_id, "reserved_accounts": [], "shortage_notified": False, "created_at": now}
				state["orders"][request.order_id] = order
			order["last_error"] = error
			order["updated_at"] = self.time_func()
			return changed
		return self.mutate(mutate)

	def mark_shortage_notified(self, order_id: str) -> bool:
		def mutate(state: dict[str, Any]) -> bool:
			order = self.require_order(state, order_id)
			if order.get("shortage_notified"):
				return False
			order["shortage_notified"] = True
			return True
		return self.mutate(mutate)

	def get_order(self, order_id: str) -> dict[str, Any] | None:
		with self.lock:
			order = self.state["orders"].get(str(order_id).lstrip("#"))
			return deepcopy(order) if order else None

	def waiting_orders(self) -> tuple[dict[str, Any], ...]:
		with self.lock:
			return tuple(deepcopy(order) for order in self.state["orders"].values() if order["status"] in (STATUS_WAITING_STOCK, STATUS_RETRYABLE, STATUS_SEND_FAILED))

	def update_order(self, order_id: str, status: str, error: str) -> None:
		def mutate(state: dict[str, Any]) -> None:
			order = self.require_order(state, order_id)
			order["status"] = status
			order["last_error"] = error
			order["updated_at"] = self.time_func()
		self.mutate(mutate)

	def mutate(self, callback):
		with self.lock:
			if not self.writable:
				raise RuntimeError("GPT account storage is unavailable.")
			state = deepcopy(self.state)
			result = callback(state)
			self.write_state(state)
			self.state = state
			return result

	def write_state(self, state: dict[str, Any]) -> None:
		self.path.parent.mkdir(parents=True, exist_ok=True)
		with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.path.parent, delete=False) as file:
			json.dump(state, file, ensure_ascii=False, indent="\t")
			file.write("\n")
			temporary_path = Path(file.name)
		temporary_path.replace(self.path)

	@staticmethod
	def default_state() -> dict[str, Any]:
		return {"stock": [], "orders": {}}

	def normalize_state(self, data: Any) -> dict[str, Any]:
		if not isinstance(data, dict):
			return self.default_state()
		stock = self.normalize_accounts(data.get("stock"))
		orders = data.get("orders") if isinstance(data.get("orders"), dict) else {}
		for order_id, order in list(orders.items()):
			if not isinstance(order, dict):
				orders.pop(order_id)
				continue
			order["order_id"] = str(order.get("order_id") or order_id).lstrip("#")
			order["reserved_accounts"] = [self.serialize_account(item) for item in self.normalize_accounts(order.get("reserved_accounts"))]
			order["requested_amount"] = max(int(order.get("requested_amount") or 1), 1)
			order["status"] = order.get("status") if order.get("status") in (STATUS_RESERVED, STATUS_WAITING_STOCK, STATUS_COMPLETED, STATUS_SEND_FAILED, STATUS_RETRYABLE) else STATUS_RETRYABLE
			order.setdefault("shortage_notified", False)
			order.setdefault("last_error", "")
		return {"stock": [asdict(item) for item in stock], "orders": orders}

	@staticmethod
	def account(value: Any) -> Account:
		if not isinstance(value, dict):
			return Account("", "")
		return Account(str(value.get("email") or "").strip(), str(value.get("password") or "").strip(), str(value.get("two_factor_secret") or "").strip())

	@staticmethod
	def serialize_account(account: Account) -> dict[str, str]:
		return {
			"email": account.email,
			"password": account.password,
			"two_factor_secret": account.two_factor_secret,
		}

	def normalize_accounts(self, values: Any) -> list[Account]:
		if not isinstance(values, list):
			return []
		seen = set()
		result = []
		for value in values:
			account = self.account(value)
			if not account.email or not account.password or account.email.casefold() in seen:
				continue
			seen.add(account.email.casefold())
			result.append(account)
		return result

	def active_emails(self, state: dict[str, Any]) -> set[str]:
		emails = {self.account(item).email.casefold() for item in state["stock"]}
		for order in state["orders"].values():
			for account in order.get("reserved_accounts", []):
				emails.add(self.account(account).email.casefold())
		return emails

	def reservation_result(self, order: dict[str, Any]) -> ReservationResult:
		accounts = tuple(self.account(value) for value in order.get("reserved_accounts", []))
		return ReservationResult(order["order_id"], order["status"], accounts, int(order.get("requested_amount") or 1), len(accounts) < int(order.get("requested_amount") or 1))

	@staticmethod
	def require_order(state: dict[str, Any], order_id: str) -> dict[str, Any]:
		order = state["orders"].get(str(order_id).lstrip("#"))
		if not order:
			raise KeyError(order_id)
		return order
