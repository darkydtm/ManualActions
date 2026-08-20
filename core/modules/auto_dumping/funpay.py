from __future__ import annotations

from typing import Any

from .models import Lot


class FunPayCatalogGateway:
	def __init__(self, cardinal: Any):
		self.cardinal = cardinal

	def own_lots(self) -> list[Lot]:
		return [self.to_lot(lot) for lot in self._profile_lots() if self.to_lot(lot).active]

	def catalog_lots(self) -> list[Lot]:
		for source in (self.cardinal, getattr(self.cardinal, "account", None), getattr(self.cardinal, "profile", None)):
			for name in ("get_lots", "get_catalog", "get_all_lots"):
				method = getattr(source, name, None)
				if callable(method):
					return [self.to_lot(lot) for lot in (method() or [])]
		raise RuntimeError("Cardinal catalog API is unavailable.")

	def is_owned(self, lot: Lot) -> bool:
		raw = lot.raw
		if raw is not None and isinstance(getattr(raw, "owner", None), bool):
			return raw.owner
		return any(own.id == lot.id for own in self.own_lots())

	def update_price(self, lot: Lot, price: float) -> None:
		raw = lot.raw
		for method_name in ("set_price", "update_price", "edit_price"):
			method = getattr(raw, method_name, None)
			if callable(method):
				method(price)
				return
		for source in (getattr(self.cardinal, "profile", None), getattr(self.cardinal, "account", None), self.cardinal):
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
		profile = getattr(self.cardinal, "profile", None)
		method = getattr(profile, "get_lots", None)
		if callable(method):
			return list(method() or [])
		return []

	@staticmethod
	def to_lot(lot: Any) -> Lot:
		subcategory = getattr(lot, "subcategory", None)
		subcategory_id = getattr(subcategory, "id", None) or getattr(subcategory, "name", None) or subcategory
		return Lot(
			id=str(getattr(lot, "id", None) or getattr(lot, "lot_id", "")),
			title=str(getattr(lot, "description", None) or getattr(lot, "title", "")),
			price=float(getattr(lot, "price", 0) or 0),
			subcategory=str(subcategory_id or ""),
			username=str(getattr(lot, "username", None) or getattr(lot, "seller", "")),
			active=getattr(lot, "active", True) is not False,
			available=getattr(lot, "available", True) is not False,
			raw=lot,
		)
