from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from Utils import cardinal_tools

from .constants import LOGGER_NAME, LOGGER_PREFIX

if TYPE_CHECKING:
	from cardinal import Cardinal


logger = logging.getLogger(LOGGER_NAME)


class RemoteBlacklistUnsupported(RuntimeError):
	pass


@dataclass(frozen=True)
class UserIdentity:
	username: str
	user_id: int | None = None
	chat_id: int | str | None = None


def list_blocked_users(cardinal: Cardinal) -> list[str]:
	return sorted(list(cardinal.blacklist or []), key=lambda value: value.lower())


def block_user(cardinal: Cardinal, username: str, user_id: int | None = None, chat_id: int | str | None = None) -> bool:
	already_cached = username in cardinal.blacklist
	identity = resolve_user_identity(cardinal, username, chat_id)
	if user_id is not None:
		identity = UserIdentity(username=username, user_id=user_id, chat_id=identity.chat_id)

	apply_remote_blacklist_action(cardinal, "block", identity)
	if not already_cached:
		add_user_to_blacklist_cache(cardinal, username)
	return not already_cached


def unblock_user(cardinal: Cardinal, username: str, user_id: int | None = None, chat_id: int | str | None = None) -> bool:
	already_cached = username in cardinal.blacklist
	identity = resolve_user_identity(cardinal, username, chat_id)
	if user_id is not None:
		identity = UserIdentity(username=username, user_id=user_id, chat_id=identity.chat_id)

	apply_remote_blacklist_action(cardinal, "unblock", identity)
	if already_cached:
		remove_user_from_blacklist_cache(cardinal, username)
	return already_cached


def add_user_to_blacklist(cardinal: Cardinal, username: str) -> bool:
	if username in cardinal.blacklist:
		return False

	add_user_to_blacklist_cache(cardinal, username)
	return True


def remove_user_from_blacklist(cardinal: Cardinal, username: str) -> bool:
	if username not in cardinal.blacklist:
		return False

	remove_user_from_blacklist_cache(cardinal, username)
	return True


def add_user_to_blacklist_cache(cardinal: Cardinal, username: str) -> None:
	cardinal.blacklist.append(username)
	cardinal_tools.cache_blacklist(cardinal.blacklist)


def remove_user_from_blacklist_cache(cardinal: Cardinal, username: str) -> None:
	cardinal.blacklist.remove(username)
	cardinal_tools.cache_blacklist(cardinal.blacklist)


def apply_remote_blacklist_action(cardinal: Cardinal, action: str, identity: UserIdentity) -> None:
	if identity.chat_id is not None:
		set_chat_mute(cardinal, identity.chat_id, action == "block")
		return

	method = find_remote_method(cardinal, action)
	if method:
		call_remote_method(method, identity)
		return

	raise RemoteBlacklistUnsupported(
		"Не удалось найти чат FunPay для пользователя. Реальная блокировка требует node_id чата."
	)


def set_chat_mute(cardinal: Cardinal, chat_id: int | str, muted: bool) -> None:
	account = cardinal.account
	ensure_csrf_token(account)
	payload = {
		"node_id": chat_id,
		"mute": 1 if muted else 0,
		"csrf_token": getattr(account, "csrf_token", None),
	}
	headers = {
		"accept": "*/*",
		"content-type": "application/x-www-form-urlencoded; charset=UTF-8",
		"x-requested-with": "XMLHttpRequest",
	}
	response = account.method("post", "chat/mute", headers, payload, raise_not_200=True)
	validate_mute_response(response)


def ensure_csrf_token(account: Any) -> None:
	if getattr(account, "csrf_token", None):
		return
	account.get()


def validate_mute_response(response: Any) -> None:
	try:
		data = response.json()
	except Exception:
		return

	if data.get("error"):
		message = data.get("msg") or data.get("message") or "FunPay вернул ошибку блокировки."
		raise RuntimeError(message)


def find_remote_method(cardinal: Cardinal, action: str) -> Any | None:
	method_names = {
		"block": ("block_user", "ban_user", "add_user_to_blacklist", "add_to_blacklist"),
		"unblock": ("unblock_user", "unban_user", "remove_user_from_blacklist", "remove_from_blacklist"),
	}[action]
	for owner in (getattr(cardinal, "account", None), cardinal):
		if not owner:
			continue
		for name in method_names:
			method = getattr(owner, name, None)
			if callable(method):
				return method
	return None


def call_remote_method(method: Any, identity: UserIdentity) -> None:
	signature = inspect.signature(method)
	parameters = signature.parameters
	kwargs = {}
	for name in parameters:
		if name in ("username", "nickname", "name", "login"):
			kwargs[name] = identity.username
		elif name in ("user_id", "userId", "id"):
			kwargs[name] = identity.user_id
		elif name in ("chat_id", "node", "node_id"):
			kwargs[name] = identity.chat_id
	kwargs = {key: value for key, value in kwargs.items() if value is not None}

	if kwargs:
		method(**kwargs)
		return

	try:
		method(identity.username)
	except TypeError:
		if identity.user_id is None:
			raise
		method(identity.user_id)


def resolve_user_identity(cardinal: Cardinal, username: str, chat_id: int | str | None = None) -> UserIdentity:
	if chat_id is not None:
		user_id = resolve_user_id_from_chat(cardinal, username, chat_id)
		return UserIdentity(username=username, user_id=user_id, chat_id=chat_id)

	user_id, resolved_chat_id = resolve_user_id_from_saved_chat(cardinal, username)
	if resolved_chat_id is not None:
		return UserIdentity(username=username, user_id=user_id, chat_id=resolved_chat_id)

	user_id = resolve_user_id_from_sales(cardinal, username)
	return UserIdentity(username=username, user_id=user_id, chat_id=chat_id)


def resolve_user_id_from_saved_chat(cardinal: Cardinal, username: str) -> tuple[int | None, int | str | None]:
	account = getattr(cardinal, "account", None)
	if not account or not hasattr(account, "get_chat_by_name"):
		return None, None
	try:
		chat = account.get_chat_by_name(username, make_request=True)
	except TypeError:
		chat = account.get_chat_by_name(username)
	except Exception as exc:
		logger.error(f"{LOGGER_PREFIX} Failed to resolve chat for {username}: {exc}")
		return None, None
	if not chat:
		return None, None
	chat_id = getattr(chat, "id", None)
	return resolve_user_id_from_chat(cardinal, username, chat_id), chat_id


def resolve_user_id_from_chat(cardinal: Cardinal, username: str, chat_id: int | str | None) -> int | None:
	if chat_id is None:
		return None
	account = getattr(cardinal, "account", None)
	if not account:
		return None
	try:
		history = account.get_chat_history(chat_id, interlocutor_username=username)
	except Exception as exc:
		logger.error(f"{LOGGER_PREFIX} Failed to resolve user id from chat {chat_id}: {exc}")
		return None

	for message in reversed(history or []):
		if getattr(message, "author", None) == username:
			return getattr(message, "author_id", None)
		if getattr(message, "chat_name", None) == username and getattr(message, "author", None) != getattr(account, "username", None):
			return getattr(message, "author_id", None)
	return None


def resolve_user_id_from_sales(cardinal: Cardinal, username: str) -> int | None:
	account = getattr(cardinal, "account", None)
	if not account:
		return None
	try:
		getter = getattr(account, "get_sales", None) or getattr(account, "get_sells", None)
		if not getter:
			return None
		result = getter(buyer=username, state="paid")
		sales = result[1] if len(result) > 1 else []
	except Exception:
		return None

	for order in sales:
		user_id = getattr(order, "buyer_id", None)
		if user_id is not None:
			return user_id
	return None
