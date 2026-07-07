from __future__ import annotations

import os


NAME = "Manual Actions"
VERSION = "1.2.0"
DESCRIPTION = (
	"Ручное управление заказами прямо из Telegram.\n\n"
	"Работает в двух режимах:\n"
	"• В топике Chat Sync - команды без аргументов, контекст берётся из топика автоматически.\n"
	"• В любом чате - команды с явными аргументами.\n\n"
	"/refund [ID] - сделать возврат\n"
	"/bl [ник] - добавить в чёрный список\n"
	"/unbl [ник] - убрать из чёрного списка\n"
	"/bl_list - показать чёрный список\n"
	"/status [0/1/2] - переключить текущий статус\n"
	"!status - показать статус в FunPay"
)
CREDITS = "@developer"
UUID = "b7e2d3f4-1a2b-4c5d-8e9f-0a1b2c3d4e5f"
SETTINGS_PAGE = True

LOGGER_NAME = "FPC.manual_actions"
LOGGER_PREFIX = "[MANUAL]"

PLUGIN_FOLDER = "storage/plugins/manual_actions"
SETTINGS_FILE = os.path.join(PLUGIN_FOLDER, "settings.json")

SYNC_PLUGIN_UUID = "745ed27e-3196-47c3-9483-e382c09fd2d8"

CBT_BL_UNBL = "ma_unbl:"
CBT_BL_LIST = "ma_bl_list:"
CBT_BL_CONFIRM = "ma_bl_confirm:"
CBT_BL_CANCEL = "ma_bl_cancel:"
CBT_BL_USER = "ma_bl_user:"
CBT_BL_UNBLOCK = "ma_bl_unblock:"
CBT_BLACKLIST_PAGE = "ma_blacklist_page:"
CBT_REFUND_CNF = "ma_rfcnf:"
CBT_REFUND_CANCEL = "ma_rfcancel:"

CBT_LOT_REFRESH = "ma_lot_refresh:"
CBT_LOT_VIEWED = "ma_lot_viewed:"

CBT_ORDERS_PAGE = "ma_orders_page:"
CBT_ORDERS_FILTER = "ma_orders_filter:"
CBT_ORDERS_DETAIL = "ma_orders_detail:"
CBT_ORDERS_REFUND = "ma_orders_refund:"

CBT_STATUS_PAGE = "ma_status_page:"
CBT_STATUS_DETAIL = "ma_status_detail:"
CBT_STATUS_SET = "ma_status_set:"
CBT_STATUS_EDIT_RESPONSE = "ma_status_edit_response:"
CBT_STATUS_EDIT_AUTO = "ma_status_edit_auto:"
CBT_STATUS_TOGGLE_AUTO = "ma_status_toggle_auto:"

STATE_STATUS_RESPONSE = "ma_status_response_text"
STATE_STATUS_AUTO = "ma_status_auto_text"
