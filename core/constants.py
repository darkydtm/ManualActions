from __future__ import annotations

import os


NAME = "Manual Actions"
VERSION = "1.3.0"
DESCRIPTION = (
	"Ручное управление заказами прямо из Telegram.\n\n"
	"Работает в двух режимах:\n"
	"• В топике Chat Sync - команды без аргументов, контекст берётся из топика автоматически.\n"
	"• В любом чате - команды с явными аргументами.\n\n"
	"/refund [ID] - сделать возврат\n"
	"/bl [ник] - переключить чёрный список\n"
	"/bl_list - показать чёрный список\n"
	"/lot [ID] - показать информацию о лоте\n"
	"/orders [ник] - показать заказы пользователя\n"
	"/status [0/1/2] - переключить текущий статус\n"
	"!status - показать статус в FunPay"
)
CREDITS = "beavers_best"
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
CBT_LOT_SECTION = "ma_lot_section:"

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

CBT_PASTEBIN_PAGE = "ma_pb_page:"
CBT_PASTEBIN_ACCOUNT_PAGE = "ma_pb_account_page:"
CBT_PASTEBIN_PUBLISH_PAGE = "ma_pb_publish_page:"
CBT_PASTEBIN_TITLE_PAGE = "ma_pb_title_page:"
CBT_PASTEBIN_EXPIRE_PAGE = "ma_pb_expire_page:"
CBT_PASTEBIN_SET_EXPIRE = "ma_pb_set_expire:"
CBT_PASTEBIN_SET_TITLE_MODE = "ma_pb_set_title_mode:"
CBT_PASTEBIN_EDIT_DEV_KEY = "ma_pb_edit_dev_key:"
CBT_PASTEBIN_EDIT_USER_KEY = "ma_pb_edit_user_key:"
CBT_PASTEBIN_EDIT_USERNAME = "ma_pb_edit_username:"
CBT_PASTEBIN_EDIT_LOGIN_PASSWORD = "ma_pb_edit_login_password:"
CBT_PASTEBIN_FETCH_USER_KEY = "ma_pb_fetch_user_key:"
CBT_PASTEBIN_EDIT_FOLDER = "ma_pb_edit_folder:"
CBT_PASTEBIN_EDIT_CUSTOM_TITLE = "ma_pb_edit_title:"
CBT_PASTEBIN_VISIBILITY_PAGE = "ma_pb_visibility_page:"
CBT_PASTEBIN_SET_VISIBILITY = "ma_pb_set_visibility:"

CBT_UPDATER_PAGE = "ma_updater_page:"
CBT_UPDATER_MODE = "ma_updater_mode:"
CBT_UPDATER_INSTALL = "ma_updater_install:"
CBT_UPDATER_SKIP = "ma_updater_skip:"

STATE_STATUS_RESPONSE = "ma_status_response_text"
STATE_STATUS_AUTO = "ma_status_auto_text"
STATE_PASTEBIN_DEV_KEY = "ma_pastebin_dev_key"
STATE_PASTEBIN_USER_KEY = "ma_pastebin_user_key"
STATE_PASTEBIN_USERNAME = "ma_pastebin_username"
STATE_PASTEBIN_LOGIN_PASSWORD = "ma_pastebin_login_password"
STATE_PASTEBIN_FOLDER = "ma_pastebin_folder"
STATE_PASTEBIN_CUSTOM_TITLE = "ma_pastebin_custom_title"
