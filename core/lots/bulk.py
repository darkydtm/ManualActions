from __future__ import annotations

from dataclasses import dataclass
import logging
import threading
from typing import Any, Callable

from ..config.constants import LOGGER_NAME, LOGGER_PREFIX
from ..funpay.lots import get_profile_lots
from ..runtime.settings import update_settings


ACTION_ON = "on"
ACTION_OFF = "off"
DEFAULT_BULK_LOTS_SETTINGS = {
	"disabled_lot_ids": [],
}


logger = logging.getLogger(LOGGER_NAME)


@dataclass(frozen=True)
class BulkLotsProgress:
	action: str
	total: int
	processed: int
	succeeded: int
	skipped: int
	failed: int


@dataclass(frozen=True)
class BulkLotsResult(BulkLotsProgress):
	failed_ids: tuple[str, ...]


def normalize_bulk_lots_settings(data: Any) -> dict[str, list[str]]:
	ids = data.get("disabled_lot_ids") if isinstance(data, dict) else []
	if not isinstance(ids, list):
		ids = []
	return {
		"disabled_lot_ids": list(dict.fromkeys(
			str(item).strip()
			for item in ids
			if str(item).strip()
		)),
	}


class BulkLotsService:
	def __init__(self, cardinal: Any, settings: dict[str, Any], save_settings: Callable[[], None]):
		self.cardinal = cardinal
		self.settings = settings
		self.save_settings = save_settings
		self._lock = threading.Lock()
		self._running = False

	def preview_count(self, action: str) -> int:
		return len(self._candidate_ids(action))

	def start(
		self,
		action: str,
		on_progress: Callable[[BulkLotsProgress], None],
		on_complete: Callable[[BulkLotsResult], None],
	) -> bool:
		with self._lock:
			if self._running:
				return False
			self._running = True

		threading.Thread(
			target=self._run,
			args=(action, on_progress, on_complete),
			name="manual-actions-bulk-lots",
			daemon=True,
		).start()
		return True

	def execute(
		self,
		action: str,
		on_progress: Callable[[BulkLotsProgress], None] | None = None,
	) -> BulkLotsResult:
		lot_ids = self._candidate_ids(action)
		succeeded = 0
		skipped = 0
		failed = 0
		failed_ids: list[str] = []
		target_active = action == ACTION_ON

		for processed, lot_id in enumerate(lot_ids, start=1):
			try:
				fields = self.cardinal.account.get_lot_fields(int(lot_id))
				if bool(getattr(fields, "active", False)) == target_active:
					skipped += 1
					if action == ACTION_ON:
						self._remember_disabled(lot_id, False)
				else:
					fields.active = target_active
					self.cardinal.account.save_lot(fields)
					self._remember_disabled(lot_id, action == ACTION_OFF)
					succeeded += 1
			except Exception as exc:
				failed += 1
				failed_ids.append(lot_id)
				logger.error(f"{LOGGER_PREFIX} Failed to set lot {lot_id} active={target_active}: {exc}")

			progress = BulkLotsProgress(action, len(lot_ids), processed, succeeded, skipped, failed)
			if on_progress:
				on_progress(progress)

		return BulkLotsResult(action, len(lot_ids), len(lot_ids), succeeded, skipped, failed, tuple(failed_ids))

	def _run(
		self,
		action: str,
		on_progress: Callable[[BulkLotsProgress], None],
		on_complete: Callable[[BulkLotsResult], None],
	) -> None:
		try:
			result = self.execute(action, on_progress)
		except Exception as exc:
			logger.error(f"{LOGGER_PREFIX} Bulk lot operation failed: {exc}")
			result = BulkLotsResult(action, 0, 0, 0, 0, 1, ())
		finally:
			with self._lock:
				self._running = False
		on_complete(result)

	def _candidate_ids(self, action: str) -> list[str]:
		if action not in (ACTION_ON, ACTION_OFF):
			raise ValueError(f"Unsupported bulk lot action: {action}")
		lots = get_profile_lots(self.cardinal)
		if action == ACTION_ON:
			self._forget_enabled_lot_ids(lots)
		target_active = action == ACTION_ON
		return [
			self._lot_id(lot)
			for lot in lots
			if bool(getattr(lot, "active", False)) != target_active
		]

	def _forget_enabled_lot_ids(self, lots: list[Any]) -> None:
		enabled_ids = {self._lot_id(lot) for lot in lots if getattr(lot, "active", False)}
		if not enabled_ids.intersection(self.settings["bulk_lots"]["disabled_lot_ids"]):
			return

		def mutate(settings: dict[str, Any]) -> None:
			settings["bulk_lots"]["disabled_lot_ids"][:] = [
				lot_id
				for lot_id in settings["bulk_lots"]["disabled_lot_ids"]
				if lot_id not in enabled_ids
			]

		update_settings(self.settings, self.save_settings, mutate)

	def _remember_disabled(self, lot_id: str, disabled: bool) -> None:
		def mutate(settings: dict[str, Any]) -> None:
			ids = settings["bulk_lots"]["disabled_lot_ids"]
			if disabled and lot_id not in ids:
				ids.append(lot_id)
			elif not disabled and lot_id in ids:
				ids.remove(lot_id)

		update_settings(self.settings, self.save_settings, mutate)

	@staticmethod
	def _lot_id(lot: Any) -> str:
		lot_id = getattr(lot, "id", None) or getattr(lot, "lot_id", None)
		if lot_id is None:
			raise ValueError("Lot has no ID")
		return str(lot_id)
