from __future__ import annotations

import logging
import re
from typing import Any

from ...config.constants import LOGGER_NAME
from ...funpay.lots import get_profile_lots
from .models import Lot


logger = logging.getLogger(LOGGER_NAME)


class FunPayCatalogGateway:
	def __init__(self, cardinal: Any):
		self.cardinal = cardinal
		self._own_ids: set[str] = set()

	def own_lots(self) -> list[Lot]:
		lots = []
		for raw in self._profile_lots():
			lot = self.to_lot(raw)
			if not lot.id or not lot.active:
				continue
			lots.append(lot)
		self._own_ids = {lot.id for lot in lots}
		return lots

	def catalog_lots(self) -> list[Lot]:
		account = getattr(self.cardinal, "account", None)
		fetch = getattr(account, "get_subcategory_public_lots", None)
		if callable(fetch):
			return self._public_catalog(fetch)
		return self._legacy_catalog()

	def is_owned(self, lot: Lot) -> bool:
		raw = lot.raw
		if raw is not None and isinstance(getattr(raw, "owner", None), bool):
			return raw.owner
		if lot.id and lot.id in self._own_ids:
			return True
		try:
			return any(own.id == lot.id for own in self.own_lots())
		except Exception:
			logger.warning("Auto-dumping ownership check failed for %s, assume owned.", lot.id)
			return True

	def update_price(self, lot: Lot, price: float) -> None:
		price = round(float(price), 2)
		if price <= 0:
			raise ValueError("Refuse to set non-positive lot price.")
		account = getattr(self.cardinal, "account", None)
		get_fields = getattr(account, "get_lot_fields", None)
		save = getattr(account, "save_lot", None)
		if callable(get_fields) and callable(save):
			fields = get_fields(lot.id)
			fields.price = price
			renew = getattr(fields, "renew_fields", None)
			payload = renew() if callable(renew) else fields
			try:
				save(payload)
			except TypeError:
				save(lot.id, payload)
			return
		raw = lot.raw
		for method_name in ("set_price", "update_price", "edit_price"):
			method = getattr(raw, method_name, None)
			if callable(method):
				method(price)
				return
		for source in (getattr(self.cardinal, "profile", None), account, self.cardinal):
			for method_name in ("set_lot_price", "update_lot_price", "edit_lot"):
				method = getattr(source, method_name, None)
				if not callable(method):
					continue
				try:
					method(raw, price)
				except TypeError:
					method(lot.id, price)
				return
		raise RuntimeError("Cardinal lot price API is unavailable.")

	def _profile_lots(self) -> list[Any]:
		return get_profile_lots(self.cardinal)

	def _public_catalog(self, fetch: Any) -> list[Lot]:
		refs: dict[str, tuple[Any, Any]] = {}
		for raw in self._profile_lots():
			subcategory = getattr(raw, "subcategory", None)
			if isinstance(subcategory, (str, int, float)):
				sub_id, sub_type = subcategory, None
			elif subcategory is None:
				continue
			else:
				sub_id, sub_type = getattr(subcategory, "id", None), getattr(subcategory, "type", None)
			if sub_id is None:
				continue
			refs.setdefault(str(sub_id), (sub_id, sub_type))
		lots: list[Lot] = []
		seen: set[str] = set()
		errors = 0
		for sub_id, sub_type in refs.values():
			try:
				raw_lots = self._public_for_subcategory(fetch, sub_id, sub_type)
			except Exception:
				errors += 1
				logger.exception("Auto-dumping public lots read failed for subcategory %s.", sub_id)
				continue
			for raw in raw_lots or []:
				lot = self.to_lot(raw)
				if not lot.id or lot.id in seen or lot.price <= 0:
					continue
				seen.add(lot.id)
				lots.append(lot)
		if not lots and errors:
			raise RuntimeError("Cardinal public catalog read failed.")
		return lots

	@staticmethod
	def _public_for_subcategory(fetch: Any, sub_id: Any, sub_type: Any) -> list[Any]:
		if sub_type is not None:
			return list(fetch(sub_type, sub_id) or [])
		try:
			from FunPayAPI.common.enums import SubCategoryTypes
		except ImportError:
			return list(fetch(sub_id) or [])
		for candidate in (SubCategoryTypes.COMMON, SubCategoryTypes.CURRENCY):
			try:
				result = fetch(candidate, sub_id)
			except Exception:
				continue
			if result:
				return list(result)
		return []

	def _legacy_catalog(self) -> list[Lot]:
		for source in (self.cardinal, getattr(self.cardinal, "account", None), getattr(self.cardinal, "profile", None)):
			for name in ("get_lots", "get_catalog", "get_all_lots"):
				method = getattr(source, name, None)
				if callable(method):
					return [lot for lot in (self.to_lot(raw) for raw in (method() or [])) if lot.id]
		raise RuntimeError("Cardinal catalog API is unavailable.")

	@staticmethod
	def to_lot(lot: Any) -> Lot:
		subcategory = getattr(lot, "subcategory", None)
		if isinstance(subcategory, str):
			subcategory_name = subcategory
		elif isinstance(subcategory, (int, float)):
			subcategory_name = str(subcategory)
		elif subcategory is None:
			subcategory_name = ""
		else:
			subcategory_name = str(
				getattr(subcategory, "name", None)
				or getattr(subcategory, "fullname", None)
				or getattr(subcategory, "id", None)
				or ""
			)
		return Lot(
			id=str(getattr(lot, "id", None) or getattr(lot, "lot_id", "")),
			title=str(getattr(lot, "description", None) or getattr(lot, "title", "")),
			price=parse_price(getattr(lot, "price", 0)),
			subcategory=subcategory_name,
			username=str(getattr(lot, "username", None) or getattr(lot, "seller", "")),
			active=getattr(lot, "active", True) is not False,
			available=getattr(lot, "available", True) is not False,
			raw=lot,
		)


def parse_price(value: Any) -> float:
	if isinstance(value, bool):
		return 0.0
	if isinstance(value, (int, float)):
		return float(value)
	if isinstance(value, str):
		text = re.sub(r"[^0-9.,-]", "", value.strip().replace(" ", "").replace("\xa0", ""))
		if text.count(",") == 1 and text.count(".") == 0:
			text = text.replace(",", ".")
		else:
			text = text.replace(",", "")
		try:
			return float(text)
		except (TypeError, ValueError):
			return 0.0
	try:
		return float(value)
	except (TypeError, ValueError):
		return 0.0
