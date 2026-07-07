from __future__ import annotations

from typing import TYPE_CHECKING

from Utils import cardinal_tools

if TYPE_CHECKING:
	from cardinal import Cardinal


def add_user_to_blacklist(cardinal: Cardinal, username: str) -> bool:
	if username in cardinal.blacklist:
		return False

	cardinal.blacklist.append(username)
	cardinal_tools.cache_blacklist(cardinal.blacklist)
	return True


def remove_user_from_blacklist(cardinal: Cardinal, username: str) -> bool:
	if username not in cardinal.blacklist:
		return False

	cardinal.blacklist.remove(username)
	cardinal_tools.cache_blacklist(cardinal.blacklist)
	return True
