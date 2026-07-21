from __future__ import annotations

from core.config.constants import CREDITS, DESCRIPTION, NAME, SETTINGS_PAGE, UUID, VERSION
from core.application.plugin import delete, pre_init


def bind_pre_init(c):
	pre_init(c, __file__)


BIND_TO_PRE_INIT = [bind_pre_init]
BIND_TO_DELETE = [delete]
