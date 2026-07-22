from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
from threading import RLock
import time
from typing import Any, Callable, Iterable

from ...config.constants import GEMINI_DELIVERY_FILE, LOGGER_NAME, LOGGER_PREFIX
from ...runtime.persistence import AtomicWriteError, atomic_write_json


logger = logging.getLogger(LOGGER_NAME)

STATUS_RESERVED = "reserved"
STATUS_WAITING_STOCK = "waiting_stock"
STATUS_GIST_CREATED = "gist_created"
STATUS_COMPLETED = "completed"
STATUS_SEND_FAILED = "send_failed"
STATUS_RETRYABLE = "retryable"

TERMINAL_STATUSES = {
	STATUS_COMPLETED,
	STATUS_SEND_FAILED,
	STATUS_GIST_CREATED,
}


class StorageUnavailableError(RuntimeError):
	pass


@dataclass(frozen=True)
class OrderReservationRequest:
	order_id: str
	requested_amount: int
	buyer_username: str = ""
	fp_chat_id: int | str | None = None


@dataclass(frozen=True)
class GeminiReservationResult:
	order_id: str
	status: str
	links: tuple[str, ...]
	requested_amount: int
	shortage: bool
	raw_url: str = ""


class GeminiDeliveryStorage:
	def __init__(
		self,
		path: str | Path = GEMINI_DELIVERY_FILE,
		completion_limit: int = 1000,
		time_func: Callable[[], float] = time.time,
	):
		self.path = Path(path)
		self.completion_limit = completion_limit
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
				data = json.loads(self.path.read_text(encoding="utf-8"))
				self.state = self.normalize_state(data)
				self.writable = True
			except Exception:
				self.state = self.default_state()
				self.writable = False
				logger.warning(f"{LOGGER_PREFIX} Failed to load {self.path}.")
				logger.debug("TRACEBACK", exc_info=True)
			return deepcopy(self.state)

	def stock_links(self) -> tuple[str, ...]:
		with self.lock:
			return tuple(self.state["stock"])

	def stock_count(self) -> int:
		with self.lock:
			return len(self.state["stock"])

	def existing_active_links(self) -> set[str]:
		with self.lock:
			return self.active_links(self.state)

	def add_links(self, links: Iterable[str]) -> int:
		def mutate(state: dict[str, Any]) -> int:
			existing = self.active_links(state)
			added = 0
			for link in links:
				if link in existing:
					continue
				state["stock"].append(link)
				existing.add(link)
				added += 1
			return added

		return self.mutate(mutate)

	def remove_stock_item(self, index: int) -> str | None:
		def mutate(state: dict[str, Any]) -> str | None:
			if index < 0 or index >= len(state["stock"]):
				return None
			return state["stock"].pop(index)

		return self.mutate(mutate)

	def remove_stock_link(self, link: str) -> bool:
		def mutate(state: dict[str, Any]) -> bool:
			try:
				state["stock"].remove(link)
			except ValueError:
				return False
			return True

		return self.mutate(mutate)

	def clear_stock(self) -> int:
		def mutate(state: dict[str, Any]) -> int:
			count = len(state["stock"])
			state["stock"] = []
			return count

		return self.mutate(mutate)

	def reserve(self, request: OrderReservationRequest, shortage_mode: str) -> GeminiReservationResult:
		order_id = str(request.order_id).strip().lstrip("#")
		requested_amount = max(int(request.requested_amount), 1)

		def mutate(state: dict[str, Any]) -> GeminiReservationResult:
			orders = state["orders"]
			order = orders.get(order_id)
			if order and order["status"] in TERMINAL_STATUSES | {STATUS_RESERVED}:
				return self.reservation_result(order)

			now = self.time_func()
			if order:
				requested = int(order.get("requested_amount") or requested_amount)
				order["updated_at"] = now
				order["buyer_username"] = request.buyer_username or order.get("buyer_username", "")
				order["fp_chat_id"] = request.fp_chat_id if request.fp_chat_id is not None else order.get("fp_chat_id")
			else:
				requested = requested_amount
				order = {
					"order_id": order_id,
					"status": STATUS_RETRYABLE,
					"requested_amount": requested,
					"delivered_amount": 0,
					"buyer_username": request.buyer_username,
					"fp_chat_id": request.fp_chat_id,
					"reserved_links": [],
					"raw_url": "",
					"last_error": "",
					"shortage_notified": False,
					"created_at": now,
					"updated_at": now,
				}
				orders[order_id] = order

			available = len(state["stock"])
			if shortage_mode == "all_or_nothing" and available < requested:
				take_count = 0
			else:
				take_count = min(requested, available)

			links = state["stock"][:take_count]
			state["stock"] = state["stock"][take_count:]
			order["reserved_links"] = links
			order["delivered_amount"] = len(links)
			order["last_error"] = ""
			order["status"] = STATUS_RESERVED if links else STATUS_WAITING_STOCK
			order["updated_at"] = now
			return self.reservation_result(order)

		return self.mutate(mutate)

	def restore_reservation(self, order_id: str, error: str) -> None:
		def mutate(state: dict[str, Any]) -> None:
			order = self.require_order(state, order_id)
			state["stock"] = list(order["reserved_links"]) + state["stock"]
			order["reserved_links"] = []
			order["delivered_amount"] = 0
			order["status"] = STATUS_RETRYABLE
			order["last_error"] = error
			order["updated_at"] = self.time_func()

		self.mutate(mutate)

	def mark_gist_created(self, order_id: str, raw_url: str) -> dict[str, Any]:
		def mutate(state: dict[str, Any]) -> dict[str, Any]:
			order = self.require_order(state, order_id)
			order["status"] = STATUS_GIST_CREATED
			order["raw_url"] = raw_url
			order["last_error"] = ""
			order["updated_at"] = self.time_func()
			return deepcopy(order)

		return self.mutate(mutate)

	def mark_completed(self, order_id: str) -> None:
		def mutate(state: dict[str, Any]) -> None:
			order = self.require_order(state, order_id)
			now = self.time_func()
			order["status"] = STATUS_COMPLETED
			order["completed_at"] = now
			order["updated_at"] = now
			self.trim_completed_orders(state)

		self.mutate(mutate)

	def mark_send_failed(self, order_id: str, error: str) -> None:
		def mutate(state: dict[str, Any]) -> None:
			order = self.require_order(state, order_id)
			order["status"] = STATUS_SEND_FAILED
			order["last_error"] = error
			order["updated_at"] = self.time_func()

		self.mutate(mutate)

	def record_error(self, request: OrderReservationRequest, error: str) -> bool:
		order_id = str(request.order_id).strip().lstrip("#")

		def mutate(state: dict[str, Any]) -> bool:
			order = state["orders"].get(order_id)
			changed = not order or order.get("last_error") != error
			if not order:
				now = self.time_func()
				order = {
					"order_id": order_id,
					"status": STATUS_RETRYABLE,
					"requested_amount": max(int(request.requested_amount), 1),
					"delivered_amount": 0,
					"buyer_username": request.buyer_username,
					"fp_chat_id": request.fp_chat_id,
					"reserved_links": [],
					"raw_url": "",
					"shortage_notified": False,
					"created_at": now,
				}
				state["orders"][order_id] = order
			else:
				order["buyer_username"] = request.buyer_username or order.get("buyer_username", "")
				if request.fp_chat_id is not None:
					order["fp_chat_id"] = request.fp_chat_id
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
			order["updated_at"] = self.time_func()
			return True

		return self.mutate(mutate)

	def get_order(self, order_id: str) -> dict[str, Any] | None:
		with self.lock:
			order = self.state["orders"].get(str(order_id).strip().lstrip("#"))
			return deepcopy(order) if order else None

	def waiting_orders(self) -> list[dict[str, Any]]:
		with self.lock:
			orders = [
				deepcopy(order)
				for order in self.state["orders"].values()
				if order["status"] == STATUS_WAITING_STOCK
			]
		return sorted(orders, key=lambda order: order.get("updated_at", 0), reverse=True)

	def mutate(self, operation: Callable[[dict[str, Any]], Any]) -> Any:
		with self.lock:
			if not self.writable:
				raise StorageUnavailableError(f"Storage is unavailable: {self.path}")
			next_state = deepcopy(self.state)
			result = operation(next_state)
			self.save_state(next_state)
			self.state = next_state
			return result

	def save_state(self, state: dict[str, Any]) -> None:
		try:
			atomic_write_json(self.path, state)
		except AtomicWriteError as exc:
			raise StorageUnavailableError(f"Failed to save storage: {self.path}") from exc

	def trim_completed_orders(self, state: dict[str, Any]) -> None:
		completed = [
			order
			for order in state["orders"].values()
			if order["status"] == STATUS_COMPLETED
		]
		completed.sort(key=lambda order: order.get("completed_at", 0), reverse=True)
		for order in completed[self.completion_limit:]:
			state["orders"].pop(order["order_id"], None)

	@staticmethod
	def active_links(state: dict[str, Any]) -> set[str]:
		links = set(state["stock"])
		for order in state["orders"].values():
			if order["status"] != STATUS_COMPLETED:
				links.update(order.get("reserved_links", []))
		return links

	@staticmethod
	def require_order(state: dict[str, Any], order_id: str) -> dict[str, Any]:
		normalized_order_id = str(order_id).strip().lstrip("#")
		order = state["orders"].get(normalized_order_id)
		if not order:
			raise KeyError(normalized_order_id)
		return order

	@staticmethod
	def reservation_result(order: dict[str, Any]) -> GeminiReservationResult:
		requested_amount = int(order.get("requested_amount") or 1)
		links = tuple(order.get("reserved_links", []))
		return GeminiReservationResult(
			order_id=order["order_id"],
			status=order["status"],
			links=links,
			requested_amount=requested_amount,
			shortage=len(links) < requested_amount,
			raw_url=order.get("raw_url", ""),
		)

	@staticmethod
	def default_state() -> dict[str, Any]:
		return {
			"stock": [],
			"orders": {},
		}

	@classmethod
	def normalize_state(cls, data: Any) -> dict[str, Any]:
		if not isinstance(data, dict):
			raise ValueError("Storage root must be an object.")

		stock = data.get("stock")
		orders = data.get("orders")
		if not isinstance(stock, list) or not all(isinstance(link, str) for link in stock):
			raise ValueError("Storage stock must be a string list.")
		if not isinstance(orders, dict):
			raise ValueError("Storage orders must be an object.")

		normalized_orders = {}
		for order_id, order in orders.items():
			if not isinstance(order_id, str) or not isinstance(order, dict):
				continue
			status = order.get("status")
			if status not in {
				STATUS_RESERVED,
				STATUS_WAITING_STOCK,
				STATUS_GIST_CREATED,
				STATUS_COMPLETED,
				STATUS_SEND_FAILED,
				STATUS_RETRYABLE,
			}:
				continue
			normalized = deepcopy(order)
			normalized["order_id"] = order_id
			normalized["reserved_links"] = [
				link
				for link in order.get("reserved_links", [])
				if isinstance(link, str)
			]
			normalized_orders[order_id] = normalized

		return {
			"stock": list(stock),
			"orders": normalized_orders,
		}
