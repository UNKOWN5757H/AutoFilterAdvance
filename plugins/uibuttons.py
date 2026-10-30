import asyncio
import builtins
import copy
import html
import importlib
import inspect
import math
import random
import re
import time
from logging import ERROR, getLogger
from typing import Any, Dict, List, Optional, Set, Tuple, Union

import requests
from motor.motor_asyncio import AsyncIOMotorClient
from pyrogram import Client, ContinuePropagation, StopPropagation, enums, filters
from pyrogram.errors import (
    ChatWriteForbidden,
    FloodWait,
    Forbidden,
    MediaCaptionTooLong,
    MessageIdInvalid,
    MessageNotModified,
    PeerIdInvalid,
    QueryIdInvalid,
    UserIsBlocked,
)
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

# Ensure typing aliases exist in builtins before importing other plugins
for _t_name, _t_obj in (
    ("Tuple", Tuple),
    ("List", List),
    ("Dict", Dict),
    ("Optional", Optional),
    ("Union", Union),
    ("Set", Set),
    ("Any", Any),
):
    if not hasattr(builtins, _t_name):
        setattr(builtins, _t_name, _t_obj)

import info
from database.users_chats_db import db as _db
from info import LOG_CHANNEL, PICS
from Script import script
from utils import get_size, temp

logger = getLogger(__name__)
logger.setLevel(ERROR)

# In-memory cache of known registered user IDs so `/start file_...` never waits on MongoDB
_KNOWN_USERS_RAM: Set[int] = set()
_KNOWN_CHATS_RAM: Set[int] = set()

# Safe optional imports
try:
    from database.ia_filterdb import (
        DYNAMIC_DB_META,
        Media,
        get_all_dbs_stats,
        get_all_healthy_read_dbs,
        get_writable_System_db,
        is_multi_db_enabled,
        mark_db_error,
    )
except Exception:
    Media = None
    DYNAMIC_DB_META = []
    get_all_dbs_stats = None
    get_all_healthy_read_dbs = None
    get_writable_System_db = None
    is_multi_db_enabled = None
    mark_db_error = None

try:
    from database.plugin_dbs import plugin_db as _plugin_db
except Exception:
    _plugin_db = None

try:
    from utils import parse_text_and_markup as _parse_text_and_markup
except Exception:
    _parse_text_and_markup = None

try:
    from utils import get_settings, save_group_settings
except Exception:
    get_settings = None
    save_group_settings = None

MESSAGE_EMOJI_PLANE = '<tg-emoji emoji-id="5875465628285931233">✈️</tg-emoji> Telegram'
MESSAGE_EMOJI_LINK = '<tg-emoji emoji-id="5877465816030515018">🔗</tg-emoji> Link'

DEFAULT_CLEAN_WORDS = ["sandalwood", "mkv", "mp4", "avi", "webm", "zip", "rar"]

DEFAULT_CLEANFILE_TXT = (
    "🧹 <b>Clean Filename Words Manager</b>\n"
    "━━━━━━━━━━━━━━━━━━━━━\n"
    "⚙️ <b>Current Mode:</b> {mode_str}\n"
    "🛡️ <b>Always Auto-Removed:</b> <code>Stylish Fonts</code>, <code>@usernames</code>, <code>links</code> & <code>symbols</code>\n"
    "🔢 <b>Total Active Words:</b> <code>{count}</code>\n\n"
    "📋 <b>Active Words Removed From Buttons:</b>\n{words_display}\n"
    "━━━━━━━━━━━━━━━━━━━━━\n"
    "<b>Commands & Interactive Controls:</b>\n"
    "• <code>/listcleanfilename</code> — View & manage active clean words.\n"
    "• <code>/addcleanfilename w1, w2</code> — Add words to existing list.\n"
    "• <code>/setcleanfilename w1, w2</code> — Replace custom words list.\n"
    "• <code>/defaultcleanfilename</code> — Restore default extensions & tags.\n"
    "• <code>/remcleanfilename</code> — Clear custom clean words."
)

# Direct Shortcut Command -> Help Section Key Map
HELP_SHORTCUT_MAP: Dict[str, str] = {
    "uistart": "helps_uistart",
    "uihelp": "helps_uihelp",
    "uiabout": "helps_uiabout",
    "welcome": "helps_welcome",
    "images": "helps_images",
    "spellcheck": "helps_spell",
    "autofilter": "helps_filters",
    "forcesub": "helps_forcesub",
    "forceadd": "helps_forceadd",
    "bans": "helps_bans",
    "deletes": "helps_delete",
    "broadcasts": "helps_promotions",
    "indexs": "helps_index",
    "settings": "helps_settings",
    "conection": "helps_connections",
    "connection": "helps_connections",
    "utilitys": "helps_utilities",
    "utilities": "helps_utilities",
    "custommessges": "helps_custommessages",
    "custommessages": "helps_custommessages",
    "customcaptions": "helps_customcaption",
    "backups": "helps_backup",
    "posthand": "helps_posthand",
    "shorteners": "helps_shortener",
    "shortners": "helps_shortener",
}

# ============================================================
# 🎯 DIRECT PLUGIN FUNCTION ROUTING TABLE (ZERO SILENT FAILURES)
# ============================================================
_DIRECT_CMD_ROUTES: Dict[str, Tuple[str, str]] = {
    # UI Start / Help / About (plugins/editable.py)
    "setstarttext": ("plugins.editable", "set_start_text"),
    "defaultstarttext": ("plugins.editable", "def_start_text"),
    "setstartimage": ("plugins.editable", "set_start_img"),
    "remstartimage": ("plugins.editable", "rem_start_img"),
    "addstartbutton": ("plugins.editable", "add_start_btn"),
    "editstartbuttons": ("plugins.editable", "edit_start_btn"),
    "remstartbutton": ("plugins.editable", "rem_start_btn"),
    "sethelptext": ("plugins.editable", "set_help_text"),
    "defaulthelptext": ("plugins.editable", "def_help_text"),
    "sethelpimage": ("plugins.editable", "set_help_img"),
    "remhelpimage": ("plugins.editable", "rem_help_img"),
    "addhelpbutton": ("plugins.editable", "add_help_btn"),
    "edithelpbuttons": ("plugins.editable", "edit_help_btn"),
    "remhelpbutton": ("plugins.editable", "rem_help_btn"),
    "setabouttext": ("plugins.editable", "set_about_text"),
    "defaultabouttext": ("plugins.editable", "def_about_text"),
    "setaboutimage": ("plugins.editable", "set_about_img"),
    "remaboutimage": ("plugins.editable", "rem_about_img"),
    "addaboutbutton": ("plugins.editable", "add_about_btn"),
    "editaboutbuttons": ("plugins.editable", "edit_about_btn"),
    "remaboutbutton": ("plugins.editable", "rem_about_btn"),
    # Welcome & Global Images & Stopwords (plugins/custom_settings.py)
    "enablewelcome": ("plugins.custom_settings", "enable_welc"),
    "disablewelcome": ("plugins.custom_settings", "disable_welc"),
    "setwelcometxt": ("plugins.custom_settings", "set_welc_txt"),
    "setwelcomeimg": ("plugins.custom_settings", "set_welc_img"),
    "setwelcome": ("plugins.custom_settings", "set_welcome_both"),
    "delwelcome": ("plugins.custom_settings", "del_welcome"),
    "setautoimg": ("plugins.custom_settings", "set_auto_img"),
    "remautoimg": ("plugins.custom_settings", "rem_auto_img"),
    "setfilenotfoundimg": ("plugins.custom_settings", "set_fnf_img"),
    "remfilenotfoundimg": ("plugins.custom_settings", "rem_fnf_img"),
    "defaultfilenotfoundimg": ("plugins.custom_settings", "default_fnf_img"),
    "setfsubimg": ("plugins.custom_settings", "set_fsub_img"),
    "addstopwords": ("plugins.custom_settings", "add_stopwords"),
    "stopwords": ("plugins.custom_settings", "show_stopwords"),
    "remstopwords": ("plugins.custom_settings", "rem_stopwords"),
    "remallstopwords": ("plugins.custom_settings", "rem_all_stopwords"),
    "defaultstopwords": ("plugins.custom_settings", "default_stopwords"),
    "setnotfoundtext": ("plugins.custom_settings", "set_fnf_text"),
    "remnotfoundtext": ("plugins.custom_settings", "rem_fnf_text"),
    "defaultnotfoundtext": ("plugins.custom_settings", "def_fnf_text"),
    # Filters (plugins/pm_filter.py)
    "filter": ("plugins.pm_filter", "add_filter_cmd"),
    "addfilter": ("plugins.pm_filter", "add_filter_cmd"),
    "addfilterbutton": ("plugins.pm_filter", "add_or_edit_filter_button_cmd"),
    "filterimage": ("plugins.pm_filter", "edit_filter_image_cmd"),
    "editfiltercolur": ("plugins.pm_filter", "edit_filter_colour_cmd"),
    "editfiltercolour": ("plugins.pm_filter", "edit_filter_colour_cmd"),
    "delfilter": ("plugins.pm_filter", "del_filter_cmd"),
    "listfilters": ("plugins.pm_filter", "list_filters_cmd"),
    "delall": ("plugins.pm_filter", "del_all_filters_cmd"),
    # Force Sub (plugins/fsub.py)
    "setfsub": ("plugins.fsub", "add_dynamic_fsub"),
    "rmfsub": ("plugins.fsub", "rem_fsub"),
    "remfsub": ("plugins.fsub", "rem_fsub"),
    "delfsub": ("plugins.fsub", "rem_fsub"),
    "rmallfsub": ("plugins.fsub", "rem_all_fsub"),
    "getallfsub": ("plugins.fsub", "get_all_fsub"),
    "allfsub": ("plugins.fsub", "get_all_fsub"),
    "fsub": ("plugins.fsub", "get_all_fsub"),
    "getactivefsub": ("plugins.fsub", "get_active_fsub_cmd"),
    "getpendingfsub": ("plugins.fsub", "get_pending_fsub_cmd"),
    "rotatefsub": ("plugins.fsub", "toggle_rotate"),
    "enablefsub": ("plugins.fsub", "enable_fsub"),
    "disablefsub": ("plugins.fsub", "disable_fsub"),
    "setfsubcount": ("plugins.fsub", "set_fsub_count_cmd"),
    "activatefsub": ("plugins.fsub", "toggle_fsub_channel_status_cmd"),
    "deactivatefsub": ("plugins.fsub", "toggle_fsub_channel_status_cmd"),
    "updatefsubtarget": ("plugins.fsub", "update_fsub_target_cmd"),
    "checkfsubusers": ("plugins.fsub", "check_fsub_users_cmd"),
    "totalrequests": ("plugins.fsub", "total_requests"),
    "purgerequests": ("plugins.fsub", "purge_requests"),
    "clearfsubusers": ("plugins.fsub", "clear_fsub_users_cmd"),
    # Force Add (plugins/force_add.py)
    "myadds": ("plugins.force_add", "my_adds"),
    "setforceadd": ("plugins.force_add", "set_force_add"),
    "remforceadd": ("plugins.force_add", "remove_force_add"),
    "getforceadd": ("plugins.force_add", "get_force_add"),
    "topaddall": ("plugins.force_add", "top_add_all"),
    "topadd24": ("plugins.force_add", "top_add_24"),
    "topadd7": ("plugins.force_add", "top_add_7"),
    "resetadddaily": ("plugins.force_add", "reset_add_daily"),
    "resetadd": ("plugins.force_add", "reset_all_adds"),
    # Bans, Enable/Disable, Admin Core (plugins/admincore.py & plugins/p_ttishow.py)
    "ban": ("plugins.admincore", "ban_user_cmd"),
    "unban": ("plugins.admincore", "unban_user_cmd"),
    "bannedusers": ("plugins.admincore", "check_banned_users"),
    "enable": ("plugins.p_ttishow", "enable_chat"),
    "disable": ("plugins.p_ttishow", "disable_chat"),
    "leave": ("plugins.channel", "leave_channel_cmd"),
    "leavechannel": ("plugins.channel", "leave_channel_cmd"),
    "channels": ("plugins.channel", "channels_dashboard_cmd"),
    "exportusers": ("plugins.channel", "export_users_cmd"),
    "exportgroups": ("plugins.channel", "export_groups_cmd"),
    "exportchannels": ("plugins.channel", "export_channels_cmd"),
    "connect": ("plugins.admincore", "addconnection_cmd"),
    "disconnect": ("plugins.admincore", "deleteconnection_cmd"),
    "connections": ("plugins.admincore", "connections_cmd"),
    "adminsettings": ("plugins.admincore", "show_admin_settings"),
    "logs": ("plugins.admincore", "get_logs_cmd"),
    "server": ("plugins.admincore", "server_stats_cmd"),
    "stats": ("plugins.admincore", "bot_stats_cmd"),
    "total": ("plugins.admincore", "bot_stats_cmd"),
    "optimize_db": ("plugins.admincore", "optimize_db_cmd"),
    "clearfiles": ("plugins.admincore", "wipe_prompt_cmd"),
    "clearusers": ("plugins.admincore", "wipe_prompt_cmd"),
    "cleanusers": ("plugins.admincore", "clean_users_cmd"),
    # Delete & Auto-Delete (plugins/delete.py)
    "delete": ("plugins.delete", "delete_single_file"),
    "delmulti": ("plugins.delete", "delete_multiple_files"),
    "autodelete": ("plugins.delete", "set_autodelete_timer"),
    "buttondel": ("plugins.delete", "set_button_autodelete_timer"),
    "purgeduplicates": ("plugins.delete", "purge_duplicates_cmd"),
    # Broadcast & Promotions (plugins/broadcast.py)
    "addpromo": ("plugins.broadcast", "add_promo_handler"),
    "delpromo": ("plugins.broadcast", "del_promo_handler"),
    "listpromos": ("plugins.broadcast", "list_promo_handler"),
    "broadcast": ("plugins.broadcast", "user_broadcast"),
    "group_broadcast": ("plugins.broadcast", "group_broadcast"),
    "listbroadcast": ("plugins.broadcast", "list_broadcast_status_cmd"),
    # Indexing & Live Auto-Index (plugins/index.py)
    "autoindex": ("plugins.index", "auto_index_cmd_handler"),
    "enableautoindex": ("plugins.index", "auto_index_cmd_handler"),
    "disableautoindex": ("plugins.index", "auto_index_cmd_handler"),
    "addindexchannel": ("plugins.index", "add_index_channel_cmd"),
    "rmindexchannel": ("plugins.index", "rm_index_channel_cmd"),
    "index": ("plugins.index", "index_command"),
    "indexdoc": ("plugins.index", "index_command"),
    "indexvideo": ("plugins.index", "index_command"),
    "indexaudio": ("plugins.index", "index_command"),
    "resumeindex": ("plugins.index", "resume_index_command"),
    "setskip": ("plugins.index", "set_skip_number"),
    "deleteskip": ("plugins.index", "delete_skip_number"),
    "currentskip": ("plugins.index", "current_skip_number"),
    "freedb": ("plugins.index", "freedb_command_handler"),
    # Custom Messages & Captions (plugins/custommessage.py & plugins/caption.py)
    "infomsg": ("plugins.custommessage", "set_info_msg"),
    "infoimg": ("plugins.custommessage", "set_info_img"),
    "fsubmsg": ("plugins.custommessage", "set_fsub_msg"),
    "fsubimg": ("plugins.custommessage", "set_fsub_img"),
    "delmsg": ("plugins.custommessage", "set_del_msg"),
    "delimg": ("plugins.custommessage", "set_del_img"),
    "notfoundmsg": ("plugins.custommessage", "set_notfound_msg"),
    "notfoundimg": ("plugins.custommessage", "set_notfound_img"),
    "customcaption": ("plugins.caption", "set_file_caption_cmd"),
    "captionplus": ("plugins.caption", "set_caption_plus_cmd"),
    # Backup & Multi-DB (plugins/backup.py & plugins/datadb.py)
    "dbbackup": ("plugins.backup", "db_backup_cmd"),
    "dbrestore": ("plugins.backup", "db_restore_cmd"),
    "dbstats": ("plugins.backup", "db_stats_cmd"),
    "dbschedule": ("plugins.backup", "db_schedule_cmd"),
    "datadb": ("plugins.datadb", "datadb_command_handler"),
    "bots": ("plugins.multibot", "bots_command_handler"),
    # Post Handler (plugins/post_handler.py)
    "post": ("plugins.post_handler", "post_command"),
    "editpost": ("plugins.post_handler", "edit_post_cmd"),
    "edittitle": ("plugins.post_handler", "cmd_edit_title"),
    "edityear": ("plugins.post_handler", "cmd_edit_year"),
    "editlangs": ("plugins.post_handler", "cmd_edit_langs"),
    "editresolutions": ("plugins.post_handler", "cmd_edit_res"),
    "editgenres": ("plugins.post_handler", "cmd_edit_gen"),
    "editotts": ("plugins.post_handler", "cmd_edit_ott"),
    "editbutton": ("plugins.post_handler", "cmd_edit_post_button"),
    "editbuttoncolour": ("plugins.post_handler", "cmd_edit_btn_color"),
    "editdirect": ("plugins.post_handler", "cmd_edit_post_direct"),
    "setpoststicker": ("plugins.post_handler", "set_autopost_sticker"),
    "rempoststicker": ("plugins.post_handler", "rem_autopost_sticker"),
    # PM Auto-Reply & Clean Filename (plugins/commands.py)
    "setpmtext": ("plugins.commands", "set_pm_text"),
    "rempmtext": ("plugins.commands", "rem_pm_text"),
    "setpmimage": ("plugins.commands", "set_pm_image"),
    "rempmimage": ("plugins.commands", "rem_pm_image"),
    "setpmbutton": ("plugins.commands", "set_pm_button"),
    "rempmbutton": ("plugins.commands", "rem_pm_button"),
    "pmautoreply": ("plugins.commands", "toggle_pm_autoreply_cmd"),
    "listcleanfilename": ("plugins.commands", "list_clean_words_cmd"),
    "addcleanfilename": ("plugins.commands", "add_clean_words_cmd"),
    "setcleanfilename": ("plugins.commands", "set_clean_words"),
    "defaultcleanfilename": ("plugins.commands", "default_clean_words"),
    "remcleanfilename": ("plugins.commands", "rem_clean_words"),
    # Link Shortener (plugins/shortner.py)
    "shortener": ("plugins.shortner", "shortener_cmd_handler"),
    "shortner": ("plugins.shortner", "shortener_cmd_handler"),
    "shortenerapi": ("plugins.shortner", "shortener_api_cmd_handler"),
    "shortenersite": ("plugins.shortner", "shortener_site_cmd_handler"),
}


# ============================================================
# 🔗 LIVE CONNECTION TO plugins/editable.py (TIMEOUT-PROTECTED)
# ============================================================
_UI_SYNC_CACHE: Dict[str, Any] = {}
_UI_SYNC_TS: float = 0.0
_CUSTOM_ROWS_CACHE: Dict[str, Tuple[float, List[List[InlineKeyboardButton]]]] = {}


async def _ensure_ui_synced() -> Dict[str, Any]:
    """
    Ensures custom UI texts & images from plugins/editable.py are synced to runtime,
    protected by a strict 1.5s timeout so a slow/full MongoDB NEVER freezes `/start`!
    """
    global _UI_SYNC_CACHE, _UI_SYNC_TS
    now = time.time()
    if _UI_SYNC_TS > 0 and (now - _UI_SYNC_TS) < 120:
        return _UI_SYNC_CACHE
    try:
        from plugins.editable import get_ui

        res = await asyncio.wait_for(get_ui(), timeout=1.5)
        if isinstance(res, dict):
            _UI_SYNC_CACHE = res
            _UI_SYNC_TS = now
            return res
    except Exception:
        pass
    _UI_SYNC_TS = now
    return _UI_SYNC_CACHE


async def _get_custom_rows(menu_name: str) -> List[List[InlineKeyboardButton]]:
    """
    Fetches custom inline button rows configured via plugins/editable.py,
    protected by a strict 1.2s timeout so `/start` is always instant.
    """
    now = time.time()
    cached = _CUSTOM_ROWS_CACHE.get(menu_name)
    if cached and (now - cached[0]) < 120:
        return cached[1]
    try:
        from plugins.editable import get_custom_menu_rows

        rows = await asyncio.wait_for(get_custom_menu_rows(menu_name), timeout=1.2)
        if isinstance(rows, list):
            _CUSTOM_ROWS_CACHE[menu_name] = (now, rows)
            return rows
    except Exception:
        pass
    _CUSTOM_ROWS_CACHE[menu_name] = (now, [])
    return []


# ============================================================
# 🎨 SAFE TELEGRAM BUTTON STYLE DETECTION
# ============================================================
BTN_PRIMARY = None
BTN_SUCCESS = None
BTN_DANGER = None
_SUPPORTS_BTN_STYLE = False

try:
    from pyrogram.enums import ButtonStyle

    if "style" in inspect.signature(InlineKeyboardButton.__init__).parameters:
        BTN_PRIMARY = getattr(ButtonStyle, "PRIMARY", None)
        BTN_SUCCESS = getattr(ButtonStyle, "SUCCESS", None)
        BTN_DANGER = getattr(ButtonStyle, "DANGER", None)
        _SUPPORTS_BTN_STYLE = True
except (ImportError, ValueError, TypeError):
    BTN_PRIMARY = BTN_SUCCESS = BTN_DANGER = None
    _SUPPORTS_BTN_STYLE = False


def get_admin_list() -> List[int]:
    raw_admins = getattr(info, "ADMINS", [])
    if isinstance(raw_admins, (str, int)):
        raw_admins = str(raw_admins).replace(",", " ").split()
    elif isinstance(raw_admins, (list, tuple, set)):
        raw_admins = list(raw_admins)
    else:
        raw_admins = []
    return [int(x) for x in raw_admins if str(x).strip().lstrip("-").isdigit()]


async def is_global_admin(user_id: int) -> bool:
    if not user_id:
        return False
    return int(user_id) in get_admin_list()


async def is_user_banned(user_id: int) -> bool:
    """Fast 0ms RAM ban check via temp.BANNED_USERS."""
    if not user_id:
        return False
    if hasattr(temp, "BANNED_USERS") and int(user_id) in temp.BANNED_USERS:
        return True
    return False


def create_btn(
    text: str,
    url: Optional[str] = None,
    callback_data: Optional[str] = None,
    style: Any = None,
) -> InlineKeyboardButton:
    """Creates an InlineKeyboardButton safely. Pass style=None for no colour."""
    kwargs: Dict[str, Any] = {"text": str(text)}
    if url:
        clean_u = str(url).strip()
        if clean_u and not clean_u.startswith(("http://", "https://", "tg://")):
            clean_u = "https://" + clean_u.lstrip("/")
        kwargs["url"] = clean_u
    elif callback_data:
        kwargs["callback_data"] = str(callback_data)[:64]

    if _SUPPORTS_BTN_STYLE and style is not None:
        kwargs["style"] = style

    try:
        return InlineKeyboardButton(**kwargs)
    except Exception:
        kwargs.pop("style", None)
        return InlineKeyboardButton(**kwargs)


# ============================================================
# 🛡️ PYROGRAM v2.2.26 (LAYER 230) COMPATIBILITY ENGINE
# ============================================================
try:
    from pyrogram.types import LinkPreviewOptions
except ImportError:
    LinkPreviewOptions = None

try:
    from pyrogram.types import ReplyParameters
except ImportError:
    ReplyParameters = None

_SEND_MSG_PARAMS = set(inspect.signature(Client.send_message).parameters.keys())
_REPLY_PARAMS = set(inspect.signature(Message.reply_text).parameters.keys())
_EDIT_PARAMS = set(inspect.signature(Message.edit_text).parameters.keys())


def _prepare_compat_kwargs(
    kwargs: dict, supported_params: set, disable_preview: Optional[bool] = None
) -> dict:
    clean_kw = dict(kwargs)
    explicit_disable = clean_kw.pop("disable_web_page_preview", disable_preview)

    if explicit_disable is not None:
        if "disable_web_page_preview" in supported_params:
            clean_kw["disable_web_page_preview"] = bool(explicit_disable)
        elif (
            "link_preview_options" in supported_params
            and LinkPreviewOptions is not None
        ):
            try:
                clean_kw["link_preview_options"] = LinkPreviewOptions(
                    is_disabled=bool(explicit_disable)
                )
            except Exception:
                pass

    if "reply_to_message_id" in clean_kw:
        rep_id = clean_kw.pop("reply_to_message_id")
        if rep_id:
            if "reply_to_message_id" in supported_params:
                clean_kw["reply_to_message_id"] = rep_id
            elif "reply_parameters" in supported_params and ReplyParameters is not None:
                try:
                    clean_kw["reply_parameters"] = ReplyParameters(message_id=rep_id)
                except Exception:
                    pass

    return clean_kw


async def safe_reply_text(
    message: Message, text: str, disable_web_page_preview: bool = True, **kwargs
):
    safe_txt = str(text or "Hello!").strip() or "Hello!"
    compat_kw = _prepare_compat_kwargs(
        kwargs, _REPLY_PARAMS, disable_preview=disable_web_page_preview
    )
    try:
        return await message.reply_text(safe_txt, **compat_kw)
    except TypeError:
        compat_kw.pop("disable_web_page_preview", None)
        compat_kw.pop("link_preview_options", None)
        compat_kw.pop("reply_parameters", None)
        compat_kw.pop("reply_to_message_id", None)
        try:
            return await message.reply_text(safe_txt, **compat_kw)
        except Exception:
            pass
    except (ChatWriteForbidden, Forbidden, UserIsBlocked, PeerIdInvalid):
        return None
    except Exception:
        pass

    # Fallback: Strip invalid custom HTML / emoji tags if Telegram rejected HTML entities
    compat_kw.pop("parse_mode", None)
    plain_txt = re.sub(r"<[^>]+>", "", safe_txt).strip() or "Hello!"
    try:
        return await message.reply_text(plain_txt, **compat_kw)
    except Exception as e:
        logger.error(f"safe_reply_text fallback error: {e}")
        return None


async def safe_edit_text(
    message: Message, text: str, disable_web_page_preview: bool = True, **kwargs
):
    safe_txt = str(text or "Menu").strip() or "Menu"
    compat_kw = _prepare_compat_kwargs(
        kwargs, _EDIT_PARAMS, disable_preview=disable_web_page_preview
    )
    try:
        if getattr(message, "photo", None) or getattr(message, "video", None):
            cap_kw = {
                k: v
                for k, v in compat_kw.items()
                if k in ("reply_markup", "parse_mode")
            }
            return await message.edit_caption(caption=safe_txt, **cap_kw)
        return await message.edit_text(safe_txt, **compat_kw)
    except TypeError:
        compat_kw.pop("disable_web_page_preview", None)
        compat_kw.pop("link_preview_options", None)
        return await message.edit_text(safe_txt, **compat_kw)
    except (MessageNotModified, MessageIdInvalid, ChatWriteForbidden, Forbidden):
        return None
    except Exception:
        compat_kw.pop("parse_mode", None)
        plain_txt = re.sub(r"<[^>]+>", "", safe_txt).strip() or "Menu"
        try:
            return await message.edit_text(plain_txt, **compat_kw)
        except Exception:
            return None


async def safe_send_message(
    client: Client,
    chat_id: int,
    text: str,
    disable_web_page_preview: Optional[bool] = True,
    **kwargs,
):
    safe_txt = str(text or "Hello!").strip() or "Hello!"
    compat_kw = _prepare_compat_kwargs(
        kwargs, _SEND_MSG_PARAMS, disable_preview=disable_web_page_preview
    )
    try:
        return await client.send_message(chat_id=chat_id, text=safe_txt, **compat_kw)
    except TypeError:
        compat_kw.pop("disable_web_page_preview", None)
        compat_kw.pop("link_preview_options", None)
        compat_kw.pop("reply_parameters", None)
        compat_kw.pop("reply_to_message_id", None)
        return await client.send_message(chat_id=chat_id, text=safe_txt, **compat_kw)
    except (ChatWriteForbidden, Forbidden, UserIsBlocked, PeerIdInvalid):
        return None
    except Exception:
        compat_kw.pop("parse_mode", None)
        plain_txt = re.sub(r"<[^>]+>", "", safe_txt).strip() or "Hello!"
        try:
            return await client.send_message(
                chat_id=chat_id, text=plain_txt, **compat_kw
            )
        except Exception:
            return None


async def safe_answer(
    query: CallbackQuery,
    text: Optional[str] = None,
    show_alert: bool = False,
    url: Optional[str] = None,
):
    if not query:
        return
    try:
        kwargs: Dict[str, Any] = {"show_alert": show_alert}
        if text is not None:
            kwargs["text"] = str(text)[:200]
        if url is not None:
            kwargs["url"] = url
        await query.answer(**kwargs)
    except (QueryIdInvalid, Exception):
        pass


# ============================================================
# ⚡ CLOUD IMAGE UPLOADER & MARKUP PARSER HELPERS
# ============================================================
def _upload_sync(file_bytes: bytes) -> Optional[str]:
    ua = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
    headers = {"User-Agent": ua, "Accept": "*/*"}

    try:
        res = requests.post(
            "https://litterbox.catbox.moe/resources/internals/api.php",
            data={"reqtype": "fileupload", "time": "72h"},
            files={"fileToUpload": ("img.jpg", file_bytes, "image/jpeg")},
            headers=headers,
            timeout=10,
        )
        if res.status_code == 200 and res.text.strip().startswith("http"):
            return res.text.strip()
    except Exception:
        pass

    endpoints = [
        (
            "https://catbox.moe/user/api.php",
            {"fileToUpload": ("img.jpg", file_bytes, "image/jpeg")},
            {"reqtype": "fileupload"},
        ),
        (
            "https://freeimage.host/api/1/upload",
            {"source": ("img.jpg", file_bytes, "image/jpeg")},
            {"key": "6d207e02198a847aa98d0a2a901485a5", "format": "json"},
        ),
        (
            "https://graph.org/upload",
            {"file": ("img.jpg", file_bytes, "image/jpeg")},
            None,
        ),
        ("https://envs.sh", {"file": ("img.jpg", file_bytes, "image/jpeg")}, None),
        ("https://x0.at", {"file": ("img.jpg", file_bytes, "image/jpeg")}, None),
        ("https://0x0.st", {"file": ("img.jpg", file_bytes, "image/jpeg")}, None),
    ]
    for url, files_dict, data_dict in endpoints:
        try:
            res = requests.post(
                url, data=data_dict, files=files_dict, headers=headers, timeout=10
            )
            if res.status_code in (200, 201):
                if url == "https://graph.org/upload":
                    return "https://graph.org" + res.json()[0]["src"]
                if url == "https://freeimage.host/api/1/upload":
                    u = res.json().get("image", {}).get("url")
                    if u and u.startswith("http"):
                        return u
                elif res.text.strip().startswith("http"):
                    return res.text.strip()
        except Exception:
            continue
    return None


async def upload_image_safely(client: Client, message: Message) -> Optional[str]:
    try:
        file_io = await client.download_media(message, in_memory=True)
        if not file_io:
            return None
        return await asyncio.to_thread(_upload_sync, file_io.getvalue())
    except Exception:
        return None


def safe_parse_text_and_markup(text: str, default_markup=None):
    """
    Parses text and optional inline buttons while ensuring `default_markup` (such as
    the Start/Help keyboard or PM Auto-Reply button) is ALWAYS preserved if `text`
    itself contains no custom buttons!
    """
    if not text:
        return "", default_markup
    if callable(_parse_text_and_markup):
        try:
            parsed_text, parsed_markup = _parse_text_and_markup(text, default_markup)
            has_valid_rows = bool(
                parsed_markup
                and getattr(parsed_markup, "inline_keyboard", None)
                and any(row for row in parsed_markup.inline_keyboard if row)
            )
            final_markup = parsed_markup if has_valid_rows else default_markup
            return parsed_text or text, final_markup
        except Exception as e:
            logger.error(f"parse_text_and_markup fallback triggered: {e}")
    return text, default_markup


class _SafeFormatDict(dict):
    def __missing__(self, key):
        return ""


def format_script_text(
    template: str,
    mention: str = "User",
    uname: str = None,
    bname: str = None,
    **extra_kwargs,
) -> str:
    if not template:
        return f"<b>Hello {mention}! 👋</b>"
    uname = uname or getattr(temp, "U_NAME", None) or "Bot"
    bname = bname or getattr(temp, "B_NAME", None) or "MovieBot"

    mapping = _SafeFormatDict(
        mention=mention,
        user=mention,
        first=mention,
        first_name=mention,
        uname=uname,
        username=uname,
        bname=bname,
        bot=bname,
        bot_name=bname,
        plane_emoji=MESSAGE_EMOJI_PLANE,
        link_emoji=MESSAGE_EMOJI_LINK,
        **extra_kwargs,
    )

    try:
        res = template.format_map(mapping)
        if res and res.strip():
            return res
    except (IndexError, ValueError, KeyError):
        pass

    try:
        return template.format(
            mention,
            uname,
            bname,
            MESSAGE_EMOJI_PLANE,
            MESSAGE_EMOJI_LINK,
            **mapping,
        )
    except Exception:
        try:
            return template.format(mention, bname)
        except Exception:
            return str(template)


# ============================================================
# ⚙️ QUOTA-SAFE MULTI-DB & RAM PM SETTINGS + CLEAN WORDS HELPERS
# ============================================================
pm_db = cw_db = _BOT_DB = None

# Persistent in-memory state so even when all 512MB MongoDB clusters are full,
# PM settings & Clean Filename changes work 100% and never revert!
_PM_RAM_STATE: Dict[str, Any] = {
    "enabled": True,
    "reply_admins": True,
    "text": (
        "<b>🚫 Don't Message Here, Message Here Only!</b>\n\n"
        "I do not respond to direct messages in PM. Please join our official group to request and download movies."
    ),
    "image": getattr(info, "NOT_FOUND_IMG", None),
    "button_text": "💬 Message Here Only",
    "button_url": "https://t.me/Sandalwood_Kannada_Group",
    "button_color": "red",
    "updated_at": 0.0,
}
_PM_CACHE_TS: float = 0.0

_CW_RAM_STATE: Dict[str, Any] = {
    "use_default": True,
    "list": list(DEFAULT_CLEAN_WORDS),
    "updated_at": 0.0,
}
_CW_CACHE_TS: float = 0.0

try:
    _DB_CLIENT = AsyncIOMotorClient(
        info.DATABASE_URI,
        serverSelectionTimeoutMS=3000,
        connectTimeoutMS=3000,
        socketTimeoutMS=5000,
    )
    _BOT_DB = _DB_CLIENT[info.DATABASE_NAME]
    pm_db = _BOT_DB["pm_settings"]
    cw_db = _BOT_DB["clean_words"]
except Exception as e:
    logger.error(f"Failed to init databases in uibuttons: {e}")


def _get_all_candidate_cols(col_name: str, fallback_col: Any) -> List[Any]:
    cols = []
    if callable(get_writable_System_db):
        try:
            w_db = get_writable_System_db()
            if w_db is not None:
                cols.append(w_db[col_name])
        except Exception:
            pass
    if callable(get_all_healthy_read_dbs):
        try:
            for _, r_db in get_all_healthy_read_dbs():
                c = r_db[col_name]
                if c not in cols:
                    cols.append(c)
        except Exception:
            pass
    if fallback_col is not None and fallback_col not in cols:
        cols.append(fallback_col)
    return cols


async def get_pm_settings(force_refresh: bool = False) -> Dict[str, Any]:
    global _PM_CACHE_TS
    now = time.time()
    if not force_refresh and _PM_CACHE_TS > 0 and (now - _PM_CACHE_TS) < 300:
        return _PM_RAM_STATE

    best_doc = None
    best_ts = -1.0
    for col in _get_all_candidate_cols("pm_settings", pm_db):
        try:
            doc = await asyncio.wait_for(col.find_one({"id": "pm_config"}), timeout=2.0)
            if doc:
                doc_ts = float(doc.get("updated_at", 0.0) or 0.0)
                if best_doc is None or doc_ts >= best_ts:
                    best_doc = doc
                    best_ts = doc_ts
        except Exception:
            continue

    if best_doc and best_ts >= float(_PM_RAM_STATE.get("updated_at", 0.0) or 0.0):
        for k, v in best_doc.items():
            if k != "_id":
                _PM_RAM_STATE[k] = v

    _PM_CACHE_TS = now
    return _PM_RAM_STATE


async def save_pm_settings(key: str, value: Any):
    global _PM_CACHE_TS
    now = time.time()
    _PM_RAM_STATE[key] = value
    _PM_RAM_STATE["updated_at"] = now
    _PM_CACHE_TS = now

    payload = {k: v for k, v in _PM_RAM_STATE.items() if k != "_id"}
    payload["id"] = "pm_config"
    for col in _get_all_candidate_cols("pm_settings", pm_db):
        try:
            await asyncio.wait_for(
                col.update_one({"id": "pm_config"}, {"$set": payload}, upsert=True),
                timeout=2.0,
            )
        except Exception:
            continue


async def get_clean_words_state() -> Tuple[bool, List[str]]:
    global _CW_CACHE_TS
    now = time.time()
    if _CW_CACHE_TS > 0 and (now - _CW_CACHE_TS) < 300:
        if _CW_RAM_STATE.get("use_default", True):
            return True, list(DEFAULT_CLEAN_WORDS)
        return False, list(_CW_RAM_STATE.get("list", []))

    best_doc = None
    best_ts = -1.0
    for col in _get_all_candidate_cols("clean_words", cw_db):
        try:
            doc = await asyncio.wait_for(col.find_one({"id": "words"}), timeout=2.0)
            if doc:
                doc_ts = float(doc.get("updated_at", 0.0) or 0.0)
                if best_doc is None or doc_ts >= best_ts:
                    best_doc = doc
                    best_ts = doc_ts
        except Exception:
            continue

    if best_doc and best_ts >= float(_CW_RAM_STATE.get("updated_at", 0.0) or 0.0):
        _CW_RAM_STATE["use_default"] = bool(best_doc.get("use_default", True))
        _CW_RAM_STATE["list"] = list(best_doc.get("list", DEFAULT_CLEAN_WORDS))
        _CW_RAM_STATE["updated_at"] = best_ts

    _CW_CACHE_TS = now
    if _CW_RAM_STATE.get("use_default", True):
        return True, list(DEFAULT_CLEAN_WORDS)
    return False, list(_CW_RAM_STATE.get("list", []))


async def save_clean_words_state(words_list: List[str], use_default: bool = False):
    global _CW_CACHE_TS
    now = time.time()
    _CW_RAM_STATE["use_default"] = bool(use_default)
    _CW_RAM_STATE["list"] = list(words_list)
    _CW_RAM_STATE["updated_at"] = now
    _CW_CACHE_TS = now

    payload = {
        "id": "words",
        "list": list(words_list),
        "use_default": bool(use_default),
        "updated_at": now,
    }
    for col in _get_all_candidate_cols("clean_words", cw_db):
        try:
            await asyncio.wait_for(
                col.update_one({"id": "words"}, {"$set": payload}, upsert=True),
                timeout=2.0,
            )
        except Exception:
            continue

    _invalidate_pm_filter_clean_cache()


def _invalidate_pm_filter_clean_cache():
    try:
        import plugins.pm_filter as _pmf

        if _CW_RAM_STATE.get("use_default", True):
            _pmf._CLEAN_WORDS_CACHE = (time.time(), list(DEFAULT_CLEAN_WORDS))
        else:
            _pmf._CLEAN_WORDS_CACHE = (time.time(), list(_CW_RAM_STATE.get("list", [])))
        for cache_attr in ("GLOBAL_SEARCH_CACHE", "POOL_SEARCH_CACHE"):
            c_obj = getattr(_pmf, cache_attr, None)
            if c_obj and hasattr(c_obj, "_data"):
                c_obj._data.clear()
    except Exception:
        pass


async def get_active_connected_group(
    user_id: int, fallback_chat: Optional[Message] = None
) -> Optional[int]:
    if fallback_chat and fallback_chat.chat.type in [
        enums.ChatType.GROUP,
        enums.ChatType.SUPERGROUP,
    ]:
        return int(fallback_chat.chat.id)
    try:
        from plugins.pm_filter import get_active_connection

        conn = await get_active_connection(str(user_id))
        if conn:
            return int(conn)
    except Exception:
        pass
    try:
        from database.connections_mdb import active_connection

        conn = await active_connection(str(user_id))
        if conn:
            return int(conn)
    except Exception:
        pass
    for col in _get_all_candidate_cols(
        "active_connections",
        _BOT_DB["active_connections"] if _BOT_DB is not None else None,
    ):
        try:
            doc = await col.find_one({"user_id": str(user_id)})
            if doc and doc.get("group_id"):
                return int(doc["group_id"])
        except Exception:
            continue
    return None


# ============================================================
# 🔄 INTERACTIVE INPUT LISTENER FOR HELP BUTTONS (NON-STUCK)
# ============================================================
_CMD_WAITING_INPUT: Dict[int, Dict[str, Any]] = {}


def is_waiting_for_cmd_input(chat_id: int) -> bool:
    """Used by plugins/commands.py and plugins/index.py so auto-handlers do not interrupt interactive prompts."""
    return int(chat_id) in _CMD_WAITING_INPUT


def cancel_cmd_user_input(chat_id: int):
    session = _CMD_WAITING_INPUT.pop(int(chat_id), None)
    if session:
        fut = session.get("future")
        if fut and not fut.done():
            fut.cancel()
        prompt_msg = session.get("prompt_msg")
        if prompt_msg:
            try:
                asyncio.create_task(prompt_msg.delete())
            except Exception:
                pass


@Client.on_message(filters.private | filters.group, group=-19)
async def _cmd_interactive_listener(client: Client, message: Message):
    if not message or not message.chat:
        return
    chat_id = message.chat.id
    if chat_id not in _CMD_WAITING_INPUT:
        return
    if (
        message.text
        and message.text.startswith("/")
        and message.text.strip().lower() not in ["/cancel"]
    ):
        cancel_cmd_user_input(chat_id)
        return

    uid = (
        message.from_user.id
        if message.from_user
        else getattr(message.sender_chat, "id", 0)
    )
    session = _CMD_WAITING_INPUT.get(chat_id)
    if session and (
        uid == session["user_id"] or uid == chat_id or await is_global_admin(uid)
    ):
        fut = session["future"]
        if not fut.done():
            fut.set_result(message)
        raise StopPropagation


async def wait_cmd_user_input(
    chat_id: int,
    user_id: int,
    prompt_msg: Optional[Message] = None,
    timeout: int = 90,
) -> Optional[Message]:
    cancel_cmd_user_input(chat_id)
    loop = asyncio.get_running_loop()
    future = loop.create_future()
    _CMD_WAITING_INPUT[int(chat_id)] = {
        "future": future,
        "user_id": user_id,
        "prompt_msg": prompt_msg,
    }
    try:
        return await asyncio.wait_for(future, timeout=timeout)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        return None
    finally:
        if _CMD_WAITING_INPUT.get(int(chat_id), {}).get("future") is future:
            _CMD_WAITING_INPUT.pop(int(chat_id), None)
        if prompt_msg:
            try:
                await prompt_msg.delete()
            except Exception:
                pass


# ============================================================
# 🔘 KEYBOARD & BUTTON BUILDERS
# ============================================================
def get_close_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[create_btn("🔐 Close", callback_data="close_data")]])


def get_back_close_keyboard(back_cb: str = "help") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                create_btn("🔙 Back", callback_data=back_cb),
                create_btn("🔐 Close", callback_data="close_data"),
            ]
        ]
    )


def get_cancel_input_keyboard(back_cb: str = "help") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[create_btn("❌ Cancel", callback_data=f"hact#cancel_input#{back_cb}")]]
    )


def get_deleted_file_notify_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                create_btn(
                    "Movie Request 📝",
                    url="https://t.me/Sandalwood_Kannada_Group",
                    style=BTN_SUCCESS,
                )
            ]
        ]
    )


def get_default_file_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                create_btn(
                    text="🎥 ಕನ್ನಡ ಹೊಸ ಮೂವೀಗಳು 🎥",
                    url="https://t.me/sandalwood_kannada_moviesz",
                    style=BTN_SUCCESS,
                )
            ]
        ]
    )


def _normalize_pm_button_url(raw_url: Optional[str]) -> Optional[str]:
    if not raw_url:
        return None
    u = str(raw_url).strip()
    if not u or u.lower() in ("none", "null", "off", "false"):
        return None
    if u.startswith("@"):
        return f"https://t.me/{u.lstrip('@')}"
    if not u.startswith(("http://", "https://", "tg://")):
        return "https://" + u.lstrip("/")
    return u


def get_pm_autoreply_keyboard(
    btn_text: Optional[str],
    btn_url: Optional[str],
    btn_color_str: str = "red",
) -> Optional[InlineKeyboardMarkup]:
    clean_txt = str(btn_text or "").strip()
    clean_url = _normalize_pm_button_url(btn_url)
    if not clean_txt or not clean_url:
        return None
    color_map = {
        "green": BTN_SUCCESS,
        "red": BTN_DANGER,
        "blue": BTN_PRIMARY,
        "normal": None,
    }
    return InlineKeyboardMarkup(
        [
            [
                create_btn(
                    clean_txt,
                    url=clean_url,
                    style=color_map.get(str(btn_color_str).lower(), None),
                )
            ]
        ]
    )


def append_fsub_back_button(
    f_markup: Optional[InlineKeyboardMarkup],
) -> InlineKeyboardMarkup:
    rows = (
        list(f_markup.inline_keyboard)
        if f_markup and getattr(f_markup, "inline_keyboard", None)
        else []
    )
    rows.append(
        [
            create_btn("🔙 Back", callback_data="helps_forcesub"),
            create_btn("🔐 Close", callback_data="close_data"),
        ]
    )
    return InlineKeyboardMarkup(rows)


async def get_start_keyboard(client: Client, user_id: int) -> InlineKeyboardMarkup:
    buttons = [
        [
            create_btn(
                "✈️ Gʀᴏᴜᴘ 1",
                url="https://t.me/Sandalwood_Kannada_Group",
                style=BTN_PRIMARY,
            ),
            create_btn(
                "✈️ Gʀᴏᴜᴘ 2",
                url="https://t.me/Kannada_Filmy_Group",
                style=BTN_PRIMARY,
            ),
            create_btn(
                "✈️ Gʀᴏᴜᴘ 3",
                url="https://t.me/+GLsPkRgLGGszMzY1",
                style=BTN_PRIMARY,
            ),
        ]
    ]
    custom_rows = await _get_custom_rows("start")
    if custom_rows:
        buttons.extend(custom_rows)

    if await is_global_admin(user_id):
        buttons.append(
            [
                create_btn("ℹ️ 𝙷𝚎𝚕𝚙", callback_data="help"),
                create_btn("😊 𝙰𝚋𝚘𝚞𝚝", callback_data="about"),
            ]
        )
    buttons.append(
        [
            create_btn(
                "🔗 Nᴇᴡ Rᴇʟᴇᴀꜱᴇꜱ & Oᴛᴛ Uᴘᴅᴀᴛᴇꜱ",
                url="https://t.me/sandalwood_kannada_moviesz",
                style=BTN_SUCCESS,
            )
        ]
    )
    return InlineKeyboardMarkup(buttons)


async def get_help_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [
            create_btn("🖥️ UI Start", callback_data="helps_uistart"),
            create_btn("🖥️ UI Help", callback_data="helps_uihelp"),
            create_btn("🖥️ UI About", callback_data="helps_uiabout"),
        ],
        [
            create_btn("👋 Welcome", callback_data="helps_welcome"),
            create_btn("🖼️ Images", callback_data="helps_images"),
        ],
        [
            create_btn("🔍 Spell Check", callback_data="helps_spell"),
            create_btn("📝 Filters", callback_data="helps_filters"),
        ],
        [
            create_btn("📱 Force Sub", callback_data="helps_forcesub"),
            create_btn("👥 Force Add", callback_data="helps_forceadd"),
        ],
        [
            create_btn("🚫 Bans", callback_data="helps_bans"),
            create_btn("🗑️ Delete", callback_data="helps_delete"),
        ],
        [
            create_btn("📢 Promotions", callback_data="helps_promotions"),
            create_btn("📚 Index", callback_data="helps_index"),
        ],
        [
            create_btn("⚙️ Settings", callback_data="helps_settings"),
            create_btn("🌐 Connections", callback_data="helps_connections"),
        ],
        [
            create_btn("📊 Utilities", callback_data="helps_utilities"),
            create_btn("💬 Custom Messages", callback_data="helps_custommessages"),
        ],
        [
            create_btn("📝 Post Handle", callback_data="helps_posthand"),
            create_btn("📝 Custom Captions", callback_data="helps_customcaption"),
        ],
        [
            create_btn("💬 PM Auto Reply", callback_data="helps_pmautoreply"),
            create_btn("🧹 Clean Filename", callback_data="helps_cleanfile"),
        ],
        [
            create_btn("🔗 Shortener", callback_data="helps_shortener"),
            create_btn("💾 Database", callback_data="helps_backup"),
        ],
    ]

    custom_rows = await _get_custom_rows("help")
    if custom_rows:
        rows.extend(custom_rows)
    rows.append(
        [
            create_btn("🔙 Back", callback_data="start"),
            create_btn("🔐 Close", callback_data="close_data"),
        ]
    )
    return InlineKeyboardMarkup(rows)


async def get_about_keyboard() -> InlineKeyboardMarkup:
    rows = []
    custom_rows = await _get_custom_rows("about")
    if custom_rows:
        rows.extend(custom_rows)
    rows.extend(
        [
            [create_btn("📊 Sᴛᴀᴛᴜs", callback_data="stats")],
            [
                create_btn("🏘 Hᴏᴍᴇ", callback_data="start"),
                create_btn("🔐 Cʟᴏsᴇ", callback_data="close_data"),
            ],
        ]
    )
    return InlineKeyboardMarkup(rows)


def get_stats_keyboard(back_cb: str = "about") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                create_btn(
                    "🗄️ Manage DB URLs (/datadb)",
                    callback_data="ddb#main",
                    style=BTN_PRIMARY,
                ),
            ],
            [
                create_btn("🔙 Back", callback_data=back_cb),
                create_btn("🔄 Refresh", callback_data=f"rfrsh#{back_cb}"),
            ],
        ]
    )


def get_cleanwords_keyboard(use_default: bool = True) -> InlineKeyboardMarkup:
    mode_label = "defaultcleanfilename ✅" if use_default else "defaultcleanfilename"
    return InlineKeyboardMarkup(
        [
            [
                create_btn("➕ Add Words", callback_data="hact#cw_add"),
                create_btn("setcleanfilename", callback_data="hact#cw_set"),
            ],
            [
                create_btn(mode_label, callback_data="hact#cw_default"),
                create_btn("remcleanfilename", callback_data="hact#cw_clear"),
            ],
            [
                create_btn("🔙 Back", callback_data="help"),
                create_btn("🔐 Close", callback_data="close_data"),
            ],
        ]
    )


def get_help_section_keyboard(
    section_key: str, state: Optional[Dict[str, Any]] = None
) -> InlineKeyboardMarkup:
    st = state or {}
    rows: List[List[InlineKeyboardButton]] = []

    if section_key == "helps_uistart":
        rows.extend(
            [
                [
                    create_btn("setstarttext", callback_data="hact#cmd#setstarttext"),
                    create_btn(
                        "defaultstarttext", callback_data="hact#cmd#defaultstarttext"
                    ),
                    create_btn("setstartimage", callback_data="hact#cmd#setstartimage"),
                ],
                [
                    create_btn("remstartimage", callback_data="hact#cmd#remstartimage"),
                    create_btn(
                        "addstartbutton", callback_data="hact#cmd#addstartbutton"
                    ),
                ],
                [
                    create_btn(
                        "editstartbuttons", callback_data="hact#cmd#editstartbuttons"
                    ),
                    create_btn(
                        "remstartbutton", callback_data="hact#cmd#remstartbutton"
                    ),
                ],
            ]
        )
    elif section_key == "helps_uihelp":
        rows.extend(
            [
                [
                    create_btn("sethelptext", callback_data="hact#cmd#sethelptext"),
                    create_btn(
                        "defaulthelptext", callback_data="hact#cmd#defaulthelptext"
                    ),
                    create_btn("sethelpimage", callback_data="hact#cmd#sethelpimage"),
                ],
                [
                    create_btn("remhelpimage", callback_data="hact#cmd#remhelpimage"),
                    create_btn("addhelpbutton", callback_data="hact#cmd#addhelpbutton"),
                ],
                [
                    create_btn(
                        "edithelpbuttons", callback_data="hact#cmd#edithelpbuttons"
                    ),
                    create_btn("remhelpbutton", callback_data="hact#cmd#remhelpbutton"),
                ],
            ]
        )
    elif section_key == "helps_uiabout":
        rows.extend(
            [
                [
                    create_btn("setabouttext", callback_data="hact#cmd#setabouttext"),
                    create_btn(
                        "defaultabouttext", callback_data="hact#cmd#defaultabouttext"
                    ),
                    create_btn("setaboutimage", callback_data="hact#cmd#setaboutimage"),
                ],
                [
                    create_btn("remaboutimage", callback_data="hact#cmd#remaboutimage"),
                    create_btn(
                        "addaboutbutton", callback_data="hact#cmd#addaboutbutton"
                    ),
                ],
                [
                    create_btn(
                        "editaboutbuttons", callback_data="hact#cmd#editaboutbuttons"
                    ),
                    create_btn(
                        "remaboutbutton", callback_data="hact#cmd#remaboutbutton"
                    ),
                ],
            ]
        )
    elif section_key == "helps_welcome":
        welc_on = bool(st.get("welc_on", True))
        rows.extend(
            [
                [
                    create_btn(
                        f"On/Off: {'ON ✅' if welc_on else 'OFF ❌'}",
                        callback_data="hact#welc_toggle",
                    )
                ],
                [
                    create_btn("Set text", callback_data="hact#welc_settxt"),
                    create_btn("set image", callback_data="hact#cmd#setwelcomeimg"),
                ],
                [
                    create_btn("Set welcome", callback_data="hact#cmd#setwelcome"),
                    create_btn("del welcome", callback_data="hact#welc_del"),
                ],
            ]
        )
    elif section_key == "helps_images":
        rows.extend(
            [
                [
                    create_btn("setautoimg", callback_data="hact#cmd#setautoimg"),
                    create_btn("remautoimg", callback_data="hact#cmd#remautoimg"),
                ],
                [
                    create_btn(
                        "setfilenotfoundimg",
                        callback_data="hact#cmd#setfilenotfoundimg",
                    ),
                    create_btn(
                        "remfilenotfoundimg",
                        callback_data="hact#cmd#remfilenotfoundimg",
                    ),
                ],
                [
                    create_btn(
                        "defaultfilenotfoundimg",
                        callback_data="hact#cmd#defaultfilenotfoundimg",
                    ),
                    create_btn("setfsubimg", callback_data="hact#cmd#setfsubimg"),
                ],
            ]
        )
    elif section_key == "helps_spell":
        at_on = bool(st.get("at_on", True))
        mc_on = bool(st.get("mc_on", True))
        spell_on = bool(st.get("spell_on", True))
        stops_count = int(st.get("stops_count", 0))
        rows.extend(
            [
                [
                    create_btn(
                        f"autotranslate: {'ON ✅' if at_on else 'OFF ❌'}",
                        callback_data="hact#at_toggle",
                    ),
                    create_btn(
                        f"multichoice: {'ON ✅' if mc_on else 'OFF ❌'}",
                        callback_data="hact#mc_toggle",
                    ),
                ],
                [
                    create_btn(
                        f"spellcheck: {'ON ✅' if spell_on else 'OFF ❌'}",
                        callback_data="hact#spell_toggle",
                    ),
                    create_btn(
                        f"stopwords ({stops_count})", callback_data="hact#sw_list"
                    ),
                ],
                [
                    create_btn("addstopwords", callback_data="hact#sw_add"),
                    create_btn("remstopwords", callback_data="hact#cmd#remstopwords"),
                ],
                [
                    create_btn("defaultstopwords", callback_data="hact#sw_def"),
                    create_btn("remallstopwords", callback_data="hact#sw_clear"),
                ],
                [
                    create_btn(
                        "setnotfoundtext", callback_data="hact#cmd#setnotfoundtext"
                    ),
                    create_btn(
                        "defaultnotfoundtext",
                        callback_data="hact#cmd#defaultnotfoundtext",
                    ),
                ],
            ]
        )
    elif section_key == "helps_filters":
        rows.extend(
            [
                [
                    create_btn("➕ filter", callback_data="hact#cmd#filter"),
                    create_btn("🔘 addfilter", callback_data="hact#cmd#addfilter"),
                ],
                [
                    create_btn(
                        "➕ addfilterbutton", callback_data="hact#cmd#addfilterbutton"
                    ),
                    create_btn("🖼️ filterimage", callback_data="hact#cmd#filterimage"),
                ],
                [
                    create_btn(
                        "🎨 editfiltercolur", callback_data="hact#cmd#editfiltercolur"
                    ),
                    create_btn("🗑️ delfilter", callback_data="hact#cmd#delfilter"),
                ],
                [
                    create_btn("📋 listfilters", callback_data="hact#flt_list"),
                    create_btn("🔥 delall", callback_data="hact#cmd#delall"),
                ],
            ]
        )
    elif section_key == "helps_forcesub":
        f_on = bool(st.get("f_on", True))
        rot_on = bool(st.get("rot_on", False))
        rows.extend(
            [
                [
                    create_btn(
                        f"On/Off: {'ON ✅' if f_on else 'OFF ❌'}",
                        callback_data="hact#fsub_toggle",
                    ),
                    create_btn(
                        f"auto rotate: {'ON ✅' if rot_on else 'OFF ❌'}",
                        callback_data="hact#fsub_rot",
                    ),
                ],
                [
                    create_btn("Set fsub", callback_data="hact#cmd#setfsub"),
                    create_btn("rm fsub", callback_data="hact#cmd#rmfsub"),
                ],
                [
                    create_btn("Getallfsub", callback_data="hact#fsub_list"),
                    create_btn("rmallfsub", callback_data="hact#cmd#rmallfsub"),
                ],
                [
                    create_btn("totalrequests", callback_data="hact#cmd#totalrequests"),
                    create_btn("purgerequests", callback_data="hact#cmd#purgerequests"),
                ],
            ]
        )
    elif section_key == "helps_forceadd":
        fa_on = bool(st.get("fa_on", False))
        rows.extend(
            [
                [
                    create_btn(
                        f"On/Off: {'ON ✅' if fa_on else 'OFF ❌'}",
                        callback_data="hact#fa_toggle",
                    ),
                    create_btn("myadds", callback_data="hact#cmd#myadds"),
                ],
                [
                    create_btn("Set forceadd", callback_data="hact#cmd#setforceadd"),
                    create_btn("remforceadd", callback_data="hact#cmd#remforceadd"),
                ],
                [
                    create_btn("getforceadd", callback_data="hact#cmd#getforceadd"),
                    create_btn("topaddall", callback_data="hact#cmd#topaddall"),
                ],
                [
                    create_btn("topadd24", callback_data="hact#cmd#topadd24"),
                    create_btn("topadd7", callback_data="hact#cmd#topadd7"),
                ],
                [
                    create_btn("resetadddaily", callback_data="hact#cmd#resetadddaily"),
                    create_btn("resetadd", callback_data="hact#cmd#resetadd"),
                ],
            ]
        )
    elif section_key == "helps_bans":
        rows.extend(
            [
                [
                    create_btn("ban", callback_data="hact#cmd#ban"),
                    create_btn("unban", callback_data="hact#cmd#unban"),
                ],
                [
                    create_btn("Banned users", callback_data="hact#cmd#bannedusers"),
                    create_btn("leave", callback_data="hact#cmd#leave"),
                ],
                [
                    create_btn("Enable", callback_data="hact#cmd#enable"),
                    create_btn("disable", callback_data="hact#cmd#disable"),
                ],
            ]
        )
    elif section_key == "helps_delete":
        rows.extend(
            [
                [
                    create_btn("Delete", callback_data="hact#cmd#delete"),
                    create_btn("del multi", callback_data="hact#cmd#delmulti"),
                ],
                [
                    create_btn("Autodelete", callback_data="hact#cmd#autodelete"),
                    create_btn("buttondel", callback_data="hact#cmd#buttondel"),
                    create_btn(
                        "purgeduplicates", callback_data="hact#cmd#purgeduplicates"
                    ),
                ],
            ]
        )
    elif section_key == "helps_promotions":
        rows.extend(
            [
                [
                    create_btn("addpromo", callback_data="hact#cmd#addpromo"),
                    create_btn("delpromo", callback_data="hact#cmd#delpromo"),
                ],
                [
                    create_btn("broadcast", callback_data="hact#cmd#broadcast"),
                    create_btn(
                        "group_broadcast", callback_data="hact#cmd#group_broadcast"
                    ),
                ],
                [
                    create_btn("listpromos", callback_data="hact#cmd#listpromos"),
                    create_btn("listbroadcast", callback_data="hact#cmd#listbroadcast"),
                ],
            ]
        )
    elif section_key == "helps_index":
        autoidx_on = bool(st.get("autoidx_on", True))
        autoidx_count = int(st.get("autoidx_count", 0))
        rows.extend(
            [
                # 📡 Live Auto-Index Controls inside 📚 Index:
                [
                    create_btn(
                        f"{'✅ ' if autoidx_on else ''}🟢 Auto-Index ON",
                        callback_data="hact#autoidx_on",
                        style=BTN_SUCCESS if autoidx_on else None,
                    ),
                    create_btn(
                        f"{'🚫 ' if not autoidx_on else ''}🔴 Auto-Index OFF",
                        callback_data="hact#autoidx_off",
                        style=BTN_DANGER if not autoidx_on else None,
                    ),
                ],
                [
                    create_btn(
                        "➕ Add DB Channel",
                        callback_data="hact#cmd#addindexchannel",
                        style=BTN_PRIMARY,
                    ),
                    create_btn(
                        f"📋 DB Channels ({autoidx_count})",
                        callback_data="hact#autoidx_list",
                        style=BTN_PRIMARY,
                    ),
                ],
                [
                    create_btn(
                        "➖ Remove DB Channel",
                        callback_data="hact#cmd#rmindexchannel",
                    ),
                    create_btn(
                        "🧹 Free DB Space",
                        callback_data="hact#cmd#freedb",
                    ),
                ],
                # Existing Manual Index Buttons:
                [
                    create_btn("index", callback_data="hact#cmd#index"),
                    create_btn("indexdoc", callback_data="hact#cmd#indexdoc"),
                    create_btn("indexvideo", callback_data="hact#cmd#indexvideo"),
                ],
                [
                    create_btn("indexaudio", callback_data="hact#cmd#indexaudio"),
                    create_btn("resumeindex", callback_data="hact#cmd#resumeindex"),
                ],
                [
                    create_btn("setskip", callback_data="hact#cmd#setskip"),
                    create_btn("deleteskip", callback_data="hact#cmd#deleteskip"),
                    create_btn("currentskip", callback_data="hact#cmd#currentskip"),
                ],
            ]
        )
    elif section_key == "helps_settings":
        rep_on = bool(st.get("rep_on", False))
        react_on = bool(st.get("react_on", True))
        mb_on = bool(st.get("mb_on", True))
        mb_count = int(st.get("mb_count", 0))
        on_label = "✅ Multi Bot On" if mb_on else "Multi Bot On"
        off_label = "🚫 Off" if not mb_on else "Off"

        rows.extend(
            [
                # 🤖 All /bots (Multi-Bot Master-Worker) Buttons inside ⚙️ Settings:
                [
                    create_btn(
                        on_label,
                        callback_data="mb#on",
                        style=BTN_SUCCESS if mb_on else None,
                    ),
                    create_btn(
                        off_label,
                        callback_data="mb#off",
                        style=BTN_DANGER if not mb_on else None,
                    ),
                ],
                [
                    create_btn(
                        "➕ Add Bot",
                        callback_data="mb#add",
                        style=BTN_PRIMARY,
                    ),
                    create_btn(
                        f"📋 Bot list ({mb_count})",
                        callback_data="mb#list#0",
                        style=BTN_PRIMARY,
                    ),
                ],
                [
                    create_btn(
                        "➖ Remove Bot",
                        callback_data="mb#list#0",
                    ),
                    create_btn(
                        "🗑️ Remove All Bot",
                        callback_data="mb#remall_ask",
                        style=BTN_DANGER,
                    ),
                ],
                # Existing Settings Buttons:
                [
                    create_btn(
                        f"repairmode: {'ON ✅' if rep_on else 'OFF ❌'}",
                        callback_data="hact#repair_toggle",
                    ),
                    create_btn("adminsettings", callback_data="hact#cmd#adminsettings"),
                ],
                [
                    create_btn(
                        f"enablereaction {'✅' if react_on else ''}".strip(),
                        callback_data="hact#cmd#enablereaction",
                    ),
                    create_btn(
                        f"disablereaction {'✅' if not react_on else ''}".strip(),
                        callback_data="hact#cmd#disablereaction",
                    ),
                ],
            ]
        )
    elif section_key == "helps_connections":
        rows.extend(
            [
                [
                    create_btn("Connect", callback_data="hact#cmd#connect"),
                    create_btn("disconnect", callback_data="hact#cmd#disconnect"),
                ],
                [
                    create_btn("Connections", callback_data="hact#cmd#connections"),
                    create_btn("exportusers", callback_data="hact#cmd#exportusers"),
                ],
                [
                    create_btn("exportgroups", callback_data="hact#cmd#exportgroups"),
                    create_btn(
                        "exportchannels", callback_data="hact#cmd#exportchannels"
                    ),
                ],
                [
                    create_btn("channels", callback_data="hact#cmd#channels"),
                    create_btn("leavechannel", callback_data="hact#cmd#leavechannel"),
                ],
            ]
        )
    elif section_key == "helps_utilities":
        rows.extend(
            [
                [
                    create_btn("Logs", callback_data="hact#cmd#logs"),
                    create_btn("server", callback_data="hact#cmd#server"),
                    create_btn("stats", callback_data="hact#cmd#stats"),
                ],
                [
                    create_btn("Optimize_db", callback_data="hact#cmd#optimize_db"),
                    create_btn("total", callback_data="hact#cmd#total"),
                    create_btn(
                        "clearfsubusers", callback_data="hact#cmd#clearfsubusers"
                    ),
                ],
                [
                    create_btn("clearfiles", callback_data="hact#cmd#clearfiles"),
                    create_btn("clearusers", callback_data="hact#cmd#clearusers"),
                    create_btn("cleanusers", callback_data="hact#cmd#cleanusers"),
                ],
            ]
        )
    elif section_key == "helps_custommessages":
        rows.extend(
            [
                [
                    create_btn("infomsg", callback_data="hact#cmd#infomsg"),
                    create_btn("infoimg", callback_data="hact#cmd#infoimg"),
                    create_btn("fsubmsg", callback_data="hact#cmd#fsubmsg"),
                ],
                [
                    create_btn("delmsg", callback_data="hact#cmd#delmsg"),
                    create_btn("delimg", callback_data="hact#cmd#delimg"),
                    create_btn("fsubimg", callback_data="hact#cmd#fsubimg"),
                ],
                [
                    create_btn("notfoundmsg", callback_data="hact#cmd#notfoundmsg"),
                    create_btn("notfoundimg", callback_data="hact#cmd#notfoundimg"),
                ],
            ]
        )
    elif section_key == "helps_customcaption":
        rows.extend(
            [
                [
                    create_btn("customcaption", callback_data="hact#cmd#customcaption"),
                    create_btn("captionplus", callback_data="hact#cmd#captionplus"),
                ],
            ]
        )
    elif section_key == "helps_backup":
        ddb_on = bool(st.get("ddb_on", True))
        ddb_count = int(st.get("ddb_count", 0))
        ddb_on_label = "✅ Multi Database On" if ddb_on else "Multi Database On"
        ddb_off_label = "🚫 Off" if not ddb_on else "Off"

        rows.extend(
            [
                # 🗄️ All /datadb (Multi-Database) Buttons inside 💾 Backup:
                [
                    create_btn(
                        ddb_on_label,
                        callback_data="ddb#on",
                        style=BTN_SUCCESS if ddb_on else None,
                    ),
                    create_btn(
                        ddb_off_label,
                        callback_data="ddb#off",
                        style=BTN_DANGER if not ddb_on else None,
                    ),
                ],
                [
                    create_btn(
                        "Add url",
                        callback_data="ddb#add",
                        style=BTN_PRIMARY,
                    ),
                    create_btn(
                        f"url list ({ddb_count})",
                        callback_data="ddb#list#0",
                        style=BTN_PRIMARY,
                    ),
                ],
                [
                    create_btn(
                        "Remove url",
                        callback_data="ddb#list#0",
                    ),
                    create_btn(
                        "Remove All url",
                        callback_data="ddb#remall_ask",
                        style=BTN_DANGER,
                    ),
                ],
                # Existing Backup Buttons:
                [
                    create_btn("dbbackup", callback_data="hact#cmd#dbbackup"),
                    create_btn("dbrestore", callback_data="hact#cmd#dbrestore"),
                ],
                [
                    create_btn("dbstats", callback_data="hact#cmd#dbstats"),
                    create_btn("dbschedule", callback_data="hact#cmd#dbschedule"),
                ],
            ]
        )
    elif section_key == "helps_posthand":
        rows.extend(
            [
                [
                    create_btn("post", callback_data="hact#cmd#post"),
                    create_btn("editpost", callback_data="hact#cmd#editpost"),
                ],
                [
                    create_btn("edittitle", callback_data="hact#cmd#edittitle"),
                    create_btn("edityear", callback_data="hact#cmd#edityear"),
                ],
                [
                    create_btn("editlangs", callback_data="hact#cmd#editlangs"),
                    create_btn(
                        "editresolutions", callback_data="hact#cmd#editresolutions"
                    ),
                ],
                [
                    create_btn("editgenres", callback_data="hact#cmd#editgenres"),
                    create_btn("editotts", callback_data="hact#cmd#editotts"),
                ],
                [
                    create_btn("editbutton", callback_data="hact#cmd#editbutton"),
                    create_btn(
                        "editbuttoncolour", callback_data="hact#cmd#editbuttoncolour"
                    ),
                ],
                [
                    create_btn("editdirect", callback_data="hact#cmd#editdirect"),
                    create_btn(
                        "setpoststicker", callback_data="hact#cmd#setpoststicker"
                    ),
                    create_btn(
                        "rempoststicker", callback_data="hact#cmd#rempoststicker"
                    ),
                ],
            ]
        )
    elif section_key == "helps_pmautoreply":
        pm_enabled = bool(st.get("pm_enabled", True))
        reply_admins = bool(st.get("reply_admins", True))
        rows.extend(
            [
                [
                    create_btn(
                        f"On/Off: {'ON ✅' if pm_enabled else 'OFF ❌'}",
                        callback_data="hact#pm_toggle",
                    ),
                    create_btn(
                        f"Reply Admins: {'ON ✅' if reply_admins else 'OFF ❌'}",
                        callback_data="hact#pm_adm_toggle",
                    ),
                ],
                [
                    create_btn("setpmtext", callback_data="hact#pm_settext"),
                    create_btn("rempmtext", callback_data="hact#pm_deftext"),
                ],
                [
                    create_btn("setpmimage", callback_data="hact#cmd#setpmimage"),
                    create_btn("rempmimage", callback_data="hact#pm_remimg"),
                ],
                [
                    create_btn("setpmbutton", callback_data="hact#pm_setbtn"),
                    create_btn("rempmbutton", callback_data="hact#pm_rembtn"),
                ],
            ]
        )
    elif section_key == "helps_shortener":
        sh_on = bool(st.get("sh_on", False))
        rows.extend(
            [
                [
                    create_btn(
                        f"On/Off: {'ON 🟢' if sh_on else 'OFF 🔴'}",
                        callback_data="shrt#toggle",
                        style=BTN_SUCCESS if sh_on else BTN_DANGER,
                    )
                ],
                [
                    create_btn(
                        "🔑 Set API", callback_data="shrt#set_api", style=BTN_PRIMARY
                    ),
                    create_btn(
                        "🌐 Set Site", callback_data="shrt#set_site", style=BTN_PRIMARY
                    ),
                ],
                [
                    create_btn("👁️ View API & Site", callback_data="shrt#view"),
                    create_btn(
                        "🗑️ Remove API & Site",
                        callback_data="shrt#remove",
                        style=BTN_DANGER,
                    ),
                ],
            ]
        )

    rows.append(
        [
            create_btn("🔙 Back", callback_data="help"),
            create_btn("🔐 Close", callback_data="close_data"),
        ]
    )
    return InlineKeyboardMarkup(rows)


def get_channels_page_keyboard(page: int, total_pages: int) -> InlineKeyboardMarkup:
    buttons: List[List[InlineKeyboardButton]] = []
    nav_row: List[InlineKeyboardButton] = []
    if page > 1:
        nav_row.append(
            create_btn("⬅️ Previous", callback_data=f"channels_page#{page - 1}")
        )
    if page < total_pages:
        nav_row.append(create_btn("Next ➡️", callback_data=f"channels_page#{page + 1}"))
    if nav_row:
        buttons.append(nav_row)
    buttons.append([create_btn("🔐 Close", callback_data="close_data")])
    return InlineKeyboardMarkup(buttons)


# ============================================================
# 🎛️ HELP UI SECTION BUILDERS & CHANNELS PAGE BUILDER
# ============================================================
async def get_channels_page(
    client: Client, page: int = 1
) -> Tuple[str, InlineKeyboardMarkup]:
    raw_chats = await _db.get_all_chats()
    all_chats = (
        await raw_chats.to_list(length=None)
        if hasattr(raw_chats, "to_list")
        else list(raw_chats)
    )

    total_chats, page_size = len(all_chats), 15
    total_pages = max(1, math.ceil(total_chats / page_size))
    page = max(1, min(page, total_pages))

    start_idx = (page - 1) * page_size
    text = f"📑 <b>All Connected Channels & Groups</b> (Page {page}/{total_pages})\n\n"

    if not all_chats:
        text += "<i>No connected chats found in database.</i>\n"

    for i, chat in enumerate(
        all_chats[start_idx : start_idx + page_size], start=start_idx + 1
    ):
        chat_id = chat.get("id") or chat.get("chat_id")
        title = chat.get("title") or chat.get("name") or "Unknown"
        username = chat.get("username")
        link = f"https://t.me/{username}" if username else "Private / No Link"
        if not username and chat_id:
            try:
                chat_obj = await client.get_chat(chat_id)
                link = (
                    f"https://t.me/{chat_obj.username}"
                    if chat_obj.username
                    else chat_obj.invite_link
                    or await client.export_chat_invite_link(chat_id)
                )
            except Exception:
                clean_id = (
                    str(chat_id)[4:]
                    if str(chat_id).startswith("-100")
                    else str(chat_id)
                )
                link = f"https://t.me/c/{clean_id}/1"
        text += f"<b>{i}. {html.escape(str(title))}</b>\n🔗 Link: {link}\n🆔 ID: <code>{chat_id}</code>\n\n"

    return text, get_channels_page_keyboard(page, total_pages)


async def build_status_text() -> str:
    """
    Connected directly to the Live Multi-Database Stats Engine (`admincore._build_db_stats_text`
    and `ia_filterdb.get_all_dbs_stats`) so the Status button in About & Utilities shows
    every connected `/datadb` database, file counts, used storage, and free storage!
    """
    try:
        from plugins.admincore import _build_db_stats_text

        return await _build_db_stats_text()
    except Exception:
        pass

    try:
        from plugins.datadb import load_datadb_config

        await load_datadb_config()
    except Exception:
        pass

    total_files = 0
    users = 0
    chats = 0
    monsize = "0 B"
    free = "512 MB"

    try:
        users, chats = await asyncio.gather(
            _db.total_users_count(), _db.total_chat_count()
        )
    except Exception:
        pass

    if callable(get_all_dbs_stats):
        try:
            st = await get_all_dbs_stats()
            total_files = int(st.get("total_files", 0))
            monsize = get_size(st.get("total_used_bytes", 0))
            free = get_size(st.get("total_free_bytes", 0))
            all_dbs = st.get("all_dbs", [])
            lines = [
                f"📊 <b>Multi-Database Cluster Status ({len(all_dbs)} DBs)</b>",
                "━━━━━━━━━━━━━━━━━━━━━",
                f"📁 <b>Combined Total Files:</b> <code>{total_files:,}</code>",
                f"👤 <b>Total Users:</b> <code>{users:,}</code>",
                f"👥 <b>Total Chats:</b> <code>{chats:,}</code>",
                f"💾 <b>Total Used Storage:</b> <code>{monsize}</code>",
                f"🆓 <b>Total Free Storage:</b> <code>{free}</code>",
                "━━━━━━━━━━━━━━━━━━━━━",
            ]
            for d in all_dbs:
                idx = d.get("index", 1)
                lbl = html.escape(str(d.get("label", f"DB {idx}")))
                f_cnt = d.get("files", 0)
                u_str = get_size(d.get("used_bytes", 0))
                st_str = d.get("status", "🟢 Connected")
                lines.append(
                    f"🗄️ <b>DB #{idx} ({lbl}):</b> <code>{f_cnt:,} files</code> | <code>{u_str}</code> ({st_str})"
                )
            return "\n".join(lines)
        except Exception:
            pass

    try:
        if Media is not None:
            col = getattr(Media, "collection", Media)
            total_files = await col.count_documents({})
        raw_size = await _db.get_db_size()
        monsize = get_size(raw_size)
        free = get_size(max(0, 536870912 - raw_size))
    except Exception:
        pass

    status_template = getattr(script, "STATUS_TXT", None)
    if status_template:
        try:
            return status_template.format(total_files, users, chats, monsize, free)
        except Exception:
            pass

    return (
        f"📊 <b>Bot Database Status</b>\n\n"
        f"📁 <b>Total Files:</b> <code>{total_files:,}</code>\n"
        f"👤 <b>Total Users:</b> <code>{users:,}</code>\n"
        f"👥 <b>Total Chats:</b> <code>{chats:,}</code>\n"
        f"💾 <b>Used Storage:</b> <code>{monsize}</code>\n"
        f"🆓 <b>Free Storage:</b> <code>{free}</code>"
    )


async def build_cleanwords_panel_ui() -> Tuple[str, InlineKeyboardMarkup]:
    use_default, words = await get_clean_words_state()
    mode_str = "🟢 Default Clean Words" if use_default else "🔵 Custom Clean Words"
    words_display = (
        ", ".join(f"<code>{html.escape(str(w))}</code>" for w in words)
        if words
        else "<i>None (Only Stylish Fonts, @usernames, links & symbols are stripped)</i>"
    )
    tpl = getattr(script, "CLEANFILE_TXT", DEFAULT_CLEANFILE_TXT)
    try:
        text = tpl.format(
            mode_str=mode_str,
            count=len(words),
            words_display=words_display,
        )
    except Exception:
        text = DEFAULT_CLEANFILE_TXT.format(
            mode_str=mode_str,
            count=len(words),
            words_display=words_display,
        )
    if "@usernames" not in text:
        text = text.replace(
            f"⚙️ <b>Current Mode:</b> {mode_str}\n",
            f"⚙️ <b>Current Mode:</b> {mode_str}\n"
            f"🛡️ <b>Always Auto-Removed:</b> <code>Stylish Fonts</code>, <code>@usernames</code>, <code>links</code> & <code>symbols</code>\n",
        )
    return text, get_cleanwords_keyboard(use_default=use_default)


async def build_interactive_help_section(
    client: Client,
    section_key: str,
    user_id: int,
    user_mention: str,
    msg_context: Optional[Message] = None,
) -> Tuple[str, InlineKeyboardMarkup]:
    if section_key == "helps_cleanfile":
        return await build_cleanwords_panel_ui()

    if section_key == "helps_shortener":
        try:
            from plugins.shortner import build_shortener_panel

            sh_txt, sh_kb = await build_shortener_panel()
            rows = list(sh_kb.inline_keyboard)[:-1] if sh_kb else []
            rows.append(
                [
                    create_btn("🔙 Back", callback_data="help"),
                    create_btn("🔐 Close", callback_data="close_data"),
                ]
            )
            return sh_txt, InlineKeyboardMarkup(rows)
        except Exception as e:
            return (
                f"🔗 <b>Link Shortener Help</b>\n\n⚠️ Error loading shortner.py: <code>{html.escape(str(e))}</code>",
                get_help_section_keyboard("helps_shortener", {"sh_on": False}),
            )

    ui_doc = await _ensure_ui_synced()
    bot_uname = getattr(temp, "U_NAME", None) or "my_bot"
    b_name = getattr(temp, "B_NAME", None) or "MovieBot"

    help_dict = {
        "helps_uistart": ("UISTART_TXT", "🎨 <b>UI Start Menu</b>"),
        "helps_uihelp": ("UIHELP_TXT", "🎨 <b>UI Help Menu</b>"),
        "helps_uiabout": ("UIABOUT_TXT", "🎨 <b>UI About Menu</b>"),
        "helps_welcome": ("WELCOME_TXT", "👋 <b>Welcome Help</b>"),
        "helps_images": ("IMAGES_TXT", "🖼️ <b>Images Help</b>"),
        "helps_spell": ("SPELLCHECK_TXT", "🔍 <b>Spell Check & Smart Search Help</b>"),
        "helps_filters": ("FILTERS_TXT", "📝 <b>Filters Help</b>"),
        "helps_forcesub": ("FORCESUB_TXT", "📱 <b>Force Sub Help</b>"),
        "helps_forceadd": ("FORCEADD_TXT", "👥 <b>Force Add Help</b>"),
        "helps_bans": ("BANS_TXT", "🚫 <b>Bans Help</b>"),
        "helps_delete": ("DELETE_TXT", "🗑️ <b>Delete Help</b>"),
        "helps_promotions": ("PROMOTIONS_TXT", "📢 <b>Promotions Help</b>"),
        "helps_index": ("INDEX_TXT", "📚 <b>Index & Live Auto-Index Help</b>"),
        "helps_settings": ("SETTINGS_TXT", "⚙️ <b>Settings & Multi-Bot Help</b>"),
        "helps_connections": ("CONNECTIONS_TXT", "🌐 <b>Connections Help</b>"),
        "helps_utilities": ("UTILITIES_TXT", "📊 <b>Utilities Help</b>"),
        "helps_custommessages": ("CUSTOMMESSAGES_TXT", "💬 <b>Custom Messages</b>"),
        "helps_posthand": ("POSTHAND_TXT", "📝 <b>Post Handle Help</b>"),
        "helps_customcaption": ("CUSTOMCAPTION_TXT", "📝 <b>Custom Captions Help</b>"),
        "helps_backup": ("BACKUP_TXT", "💾 <b>Backup & Multi-Database Help</b>"),
        "helps_pmautoreply": ("PMAUTOREPLY_TXT", "💬 <b>PM Auto Reply Help</b>"),
    }

    target_var, default_text = help_dict.get(
        section_key, ("HELP_TXT", "Help unavailable.")
    )
    raw_section = getattr(script, target_var, default_text)
    base_text = format_script_text(
        raw_section, mention=user_mention, uname=bot_uname, bname=b_name
    )

    state: Dict[str, Any] = {}

    if section_key in ["helps_uistart", "helps_uihelp", "helps_uiabout"]:
        menu_prefix = section_key.replace("helps_ui", "")
        has_txt = bool(ui_doc.get(f"{menu_prefix}_text"))
        has_img = bool(ui_doc.get(f"{menu_prefix}_img"))
        btns_cnt = len(ui_doc.get(f"{menu_prefix}_buttons", []) or [])
        base_text += (
            f"\n\n━━━━━━━━━━━━━━━━━━━━━\n"
            f"🎛️ <b>Live {menu_prefix.title()} UI Status:</b>\n"
            f"• <b>Custom Text:</b> <code>{'Active ✅' if has_txt else 'Default'}</code>\n"
            f"• <b>Custom Image:</b> <code>{'Active ✅' if has_img else 'Default'}</code>\n"
            f"• <b>Custom Buttons:</b> <code>{btns_cnt}</code>"
        )

    elif section_key == "helps_spell":
        try:
            from plugins.pm_filter import get_feature_flags

            at_on, mc_on = await get_feature_flags()
        except Exception:
            at_on, mc_on = True, True

        try:
            from plugins.custom_settings import get_stopwords

            stops = get_stopwords()
        except Exception:
            stops = []

        conn_gid = await get_active_connected_group(user_id, msg_context)
        spell_on = True
        if conn_gid and callable(get_settings):
            try:
                g_set = await get_settings(conn_gid)
                spell_on = bool(g_set.get("spell_check", True))
            except Exception:
                pass

        state = {
            "at_on": at_on,
            "mc_on": mc_on,
            "spell_on": spell_on,
            "stops_count": len(stops),
        }
        base_text += (
            f"\n\n━━━━━━━━━━━━━━━━━━━━━\n"
            f"🎛️ <b>Live Smart Search Status:</b>\n"
            f"• <b>Auto-Translate:</b> <code>{'ON ✅' if at_on else 'OFF ❌'}</code>\n"
            f"• <b>Multi-Choice:</b> <code>{'ON ✅' if mc_on else 'OFF ❌'}</code>\n"
            f"• <b>Group Spell Check:</b> <code>{'ON ✅' if spell_on else 'OFF ❌'}</code> "
            f"(Group: <code>{conn_gid or 'Not Connected'}</code>)\n"
            f"• <b>Active Stopwords:</b> <code>{len(stops)}</code>"
        )

    elif section_key == "helps_pmautoreply":
        pm_cfg = await get_pm_settings()
        pm_enabled = bool(pm_cfg.get("enabled", True))
        reply_admins = bool(pm_cfg.get("reply_admins", True))
        btn_txt = pm_cfg.get("button_text") or "None"
        btn_url = pm_cfg.get("button_url") or "None"
        btn_color = str(pm_cfg.get("button_color", "red")).upper()

        state = {
            "pm_enabled": pm_enabled,
            "reply_admins": reply_admins,
        }
        base_text += (
            f"\n\n━━━━━━━━━━━━━━━━━━━━━\n"
            f"🎛️ <b>Live PM Auto-Reply Status:</b>\n"
            f"• <b>PM Auto-Reply:</b> <code>{'ON ✅' if pm_enabled else 'OFF ❌'}</code>\n"
            f"• <b>Reply to Admins:</b> <code>{'ON ✅' if reply_admins else 'OFF ❌'}</code>\n"
            f"• <b>Active Button:</b> <code>{html.escape(str(btn_txt))}</code> (<code>{btn_color}</code>)\n"
            f"• <b>Button URL:</b> <code>{html.escape(str(btn_url))}</code>"
        )

    elif section_key == "helps_forcesub":
        try:
            from plugins.fsub import get_fsub_config, get_total_join_requests

            f_cfg = await get_fsub_config()
            f_on = bool(f_cfg.get("is_enabled", True))
            rot_on = bool(f_cfg.get("rotation_enabled", False))
            ch_count = len(f_cfg.get("channels", {}))
            req_count = await get_total_join_requests()
        except Exception:
            f_on, rot_on, ch_count, req_count = True, False, 0, 0

        state = {
            "f_on": f_on,
            "rot_on": rot_on,
            "ch_count": ch_count,
        }
        base_text += (
            f"\n\n━━━━━━━━━━━━━━━━━━━━━\n"
            f"🎛️ <b>Live ForceSub Status:</b>\n"
            f"• <b>ForceSub:</b> <code>{'ON ✅' if f_on else 'OFF ❌'}</code>\n"
            f"• <b>Auto-Rotation (1 Ch/Member + Auto-Send):</b> <code>{'ON ✅' if rot_on else 'OFF ❌'}</code>\n"
            f"• <b>Channels:</b> <code>{ch_count}</code> | <b>Join Requests:</b> <code>{req_count}</code>"
        )

    elif section_key == "helps_index":
        autoidx_on = True
        autoidx_count = 0
        try:
            from plugins.index import (
                get_all_allowed_auto_index_channels,
                get_auto_index_config,
            )

            idx_cfg = await get_auto_index_config()
            autoidx_on = bool(idx_cfg.get("is_enabled", True))
            all_ch = await get_all_allowed_auto_index_channels()
            autoidx_count = len(all_ch)
        except Exception:
            pass

        cur_skip = int(getattr(temp, "CURRENT", 0) or 0)
        state = {
            "autoidx_on": autoidx_on,
            "autoidx_count": autoidx_count,
        }
        base_text += (
            f"\n\n━━━━━━━━━━━━━━━━━━━━━\n"
            f"📡 <b>Live Database Channel Auto-Index Status:</b>\n"
            f"• <b>Auto-Index Mode:</b> <code>{'ON ✅ (Auto-Saving New Files)' if autoidx_on else 'OFF ❌'}</code>\n"
            f"• <b>Monitored DB Channels:</b> <code>{autoidx_count if autoidx_count > 0 else 'All Admin Channels'}</code>\n"
            f"• <b>Current Skip ID:</b> <code>{cur_skip}</code>"
        )

    elif section_key == "helps_forceadd":
        conn_gid = await get_active_connected_group(user_id, msg_context)
        fa_on = False
        if conn_gid:
            try:
                from plugins.force_add import get_fa_config

                fa_cfg = await get_fa_config(conn_gid, force_refresh=True)
                fa_on = bool(fa_cfg.get("enabled", False))
            except Exception:
                if _BOT_DB is not None:
                    try:
                        fa_doc = await _BOT_DB["force_add_settings"].find_one(
                            {"chat_id": int(conn_gid)}
                        )
                        if fa_doc:
                            fa_on = bool(
                                fa_doc.get("enabled", fa_doc.get("is_enabled", False))
                            )
                    except Exception:
                        pass
        state = {"fa_on": fa_on}
        base_text += (
            f"\n\n━━━━━━━━━━━━━━━━━━━━━\n"
            f"🎛️ <b>Live Force Add Status:</b>\n"
            f"• <b>Connected Group:</b> <code>{conn_gid or 'None (/connect first)'}</code>\n"
            f"• <b>Force Add:</b> <code>{'ON ✅' if fa_on else 'OFF ❌'}</code>"
        )

    elif section_key == "helps_welcome":
        conn_gid = await get_active_connected_group(user_id, msg_context)
        welc_on = True
        if conn_gid:
            try:
                from plugins.custom_settings import get_group_welcome

                w_doc = await get_group_welcome(conn_gid)
                welc_on = bool(w_doc.get("welcome", True))
            except Exception:
                pass

        state = {"welc_on": welc_on}
        base_text += (
            f"\n\n━━━━━━━━━━━━━━━━━━━━━\n"
            f"🎛️ <b>Live Welcome Status:</b>\n"
            f"• <b>Connected Group:</b> <code>{conn_gid or 'None (/connect first)'}</code>\n"
            f"• <b>Welcome Message:</b> <code>{'ON ✅' if welc_on else 'OFF ❌'}</code>"
        )

    elif section_key == "helps_filters":
        conn_gid = await get_active_connected_group(user_id, msg_context)
        flt_count = 0
        try:
            from plugins.pm_filter import safe_get_all_filters

            kws = await safe_get_all_filters(conn_gid or "global")
            flt_count = len(kws)
        except Exception:
            pass
        base_text += (
            f"\n\n━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔗 <b>Connected Group:</b> <code>{conn_gid or 'Global (All Groups)'}</code>\n"
            f"🔢 <b>Active Manual Filters:</b> <code>{flt_count}</code>"
        )

    elif section_key == "helps_settings":
        rep_on = bool(getattr(info, "REPAIR_MODE", False))
        react_on = bool(getattr(info, "ENABLE_REACTION", True))
        mb_on = True
        mb_count = 0
        try:
            from plugins.multibot import load_multibot_config

            mb_cfg = await load_multibot_config()
            mb_on = bool(mb_cfg.get("enabled", True))
            mb_count = len(mb_cfg.get("bots", []))
        except Exception:
            pass

        state = {
            "rep_on": rep_on,
            "react_on": react_on,
            "mb_on": mb_on,
            "mb_count": mb_count,
        }
        base_text += (
            f"\n\n━━━━━━━━━━━━━━━━━━━━━\n"
            f"🎛️ <b>Live System & Multi-Bot Status:</b>\n"
            f"• <b>Multi-Bot Mode (<code>/bots</code>):</b> <code>{'ON ✅' if mb_on else 'OFF ❌'}</code> (<code>{mb_count} Workers</code>)\n"
            f"• <b>Repair / Maintenance Mode:</b> <code>{'ON ✅' if rep_on else 'OFF ❌'}</code>\n"
            f"• <b>Auto Reactions:</b> <code>{'ON ✅' if react_on else 'OFF ❌'}</code>"
        )

    elif section_key == "helps_backup":
        ddb_on = True
        ddb_count = 0
        try:
            from plugins.datadb import load_datadb_config

            ddb_cfg = await load_datadb_config()
            ddb_on = bool(ddb_cfg.get("enabled", True))
            ddb_count = len(ddb_cfg.get("urls", []))
        except Exception:
            if callable(is_multi_db_enabled):
                ddb_on = is_multi_db_enabled()
            ddb_count = len(DYNAMIC_DB_META) if DYNAMIC_DB_META else 0

        state = {
            "ddb_on": ddb_on,
            "ddb_count": ddb_count,
        }
        base_text += (
            f"\n\n━━━━━━━━━━━━━━━━━━━━━\n"
            f"🗄️ <b>Live Multi-Database Status (<code>/datadb</code>):</b>\n"
            f"• <b>Multi-Database Mode:</b> <code>{'ON ✅' if ddb_on else 'OFF ❌'}</code>\n"
            f"• <b>Added Extra DB URLs:</b> <code>{ddb_count} (Unlimited)</code>"
        )

    return base_text, get_help_section_keyboard(section_key, state)


async def transition_ui_message(
    client: Client, msg_obj: Message, text: str, keyboard, img=None
):
    has_media = bool(
        msg_obj.photo or msg_obj.video or msg_obj.document or msg_obj.animation
    )
    can_use_caption = len(text or "") <= 1024

    try:
        if img and can_use_caption:
            if has_media:
                await msg_obj.edit_caption(
                    caption=text,
                    reply_markup=keyboard,
                    parse_mode=enums.ParseMode.HTML,
                )
                return
            else:
                try:
                    await client.send_photo(
                        chat_id=msg_obj.chat.id,
                        photo=img,
                        caption=text,
                        reply_markup=keyboard,
                        parse_mode=enums.ParseMode.HTML,
                    )
                    await msg_obj.delete()
                    return
                except Exception:
                    pass

        if has_media:
            if can_use_caption and img is None:
                try:
                    await msg_obj.edit_caption(
                        caption=text,
                        reply_markup=keyboard,
                        parse_mode=enums.ParseMode.HTML,
                    )
                    return
                except MediaCaptionTooLong:
                    pass
            await safe_send_message(
                client,
                chat_id=msg_obj.chat.id,
                text=text,
                reply_markup=keyboard,
                parse_mode=enums.ParseMode.HTML,
                disable_web_page_preview=True,
            )
            try:
                await msg_obj.delete()
            except Exception:
                pass
        else:
            await safe_edit_text(
                msg_obj,
                text=text,
                reply_markup=keyboard,
                parse_mode=enums.ParseMode.HTML,
                disable_web_page_preview=True,
            )
    except (MessageNotModified, MessageIdInvalid):
        pass
    except MediaCaptionTooLong:
        try:
            await safe_send_message(
                client,
                chat_id=msg_obj.chat.id,
                text=text,
                reply_markup=keyboard,
                parse_mode=enums.ParseMode.HTML,
                disable_web_page_preview=True,
            )
            await msg_obj.delete()
        except Exception as e:
            logger.error(f"Caption Fallback Error: {e}")
    except Exception as e:
        logger.error(f"UI Transition Error: {e}")


# ============================================================
# ⚡ DIRECT HELP SECTION SHORTCUT COMMANDS (/uistart, /welcome, etc.)
# ============================================================
@Client.on_message(
    filters.command(list(HELP_SHORTCUT_MAP.keys())),
    group=-15,
)
async def help_category_shortcut_cmds(client: Client, message: Message):
    uid = (
        message.from_user.id
        if message.from_user
        else getattr(message.sender_chat, "id", 0)
    )
    cancel_cmd_user_input(message.chat.id)

    if not await is_global_admin(uid):
        return await safe_reply_text(
            message,
            "❌ <b>Unauthorized:</b> Help menus and controls are restricted to Bot Admins only.",
            parse_mode=enums.ParseMode.HTML,
        )

    cmd_name = message.command[0].lower().strip()
    section_key = HELP_SHORTCUT_MAP.get(cmd_name, "helps_uistart")
    user_mention = (
        message.from_user.mention
        if message.from_user
        else (message.chat.title or "Admin")
    )

    text, markup = await build_interactive_help_section(
        client, section_key, uid, user_mention, message
    )
    await safe_reply_text(
        message,
        text=text,
        reply_markup=markup,
        parse_mode=enums.ParseMode.HTML,
        disable_web_page_preview=True,
    )


async def _register_user_in_bg(client: Client, user):
    """Registers a new PM user in the background so `/start` is never delayed or blocked by a full DB."""
    if not user or user.id in _KNOWN_USERS_RAM:
        return
    _KNOWN_USERS_RAM.add(user.id)
    try:
        exists = await asyncio.wait_for(_db.is_user_exist(user.id), timeout=2.0)
        if not exists:
            await asyncio.wait_for(
                _db.add_user(user.id, user.first_name or "User"), timeout=2.0
            )
            if LOG_CHANNEL:
                await safe_send_message(
                    client,
                    LOG_CHANNEL,
                    script.LOG_TEXT_P.format(user.id, user.mention),
                )
    except Exception:
        pass


async def _register_chat_in_bg(client: Client, chat):
    """Registers a group chat in the background so `/start` in groups never hangs on MongoDB."""
    if not chat or chat.id in _KNOWN_CHATS_RAM:
        return
    _KNOWN_CHATS_RAM.add(chat.id)
    try:
        chat_doc = await asyncio.wait_for(_db.get_chat(chat.id), timeout=2.0)
        if not chat_doc:
            try:
                total = await client.get_chat_members_count(chat.id)
                if LOG_CHANNEL:
                    await safe_send_message(
                        client,
                        LOG_CHANNEL,
                        script.LOG_TEXT_G.format(chat.title, chat.id, total, "Unknown"),
                    )
            except Exception:
                pass
            await asyncio.wait_for(
                _db.add_chat(chat.id, chat.title or "Group"), timeout=2.0
            )
    except Exception:
        pass


# ============================================================
# 🎯 MAIN START & HELP COMMANDS (INSTANT & UNBREAKABLE)
# ============================================================
@Client.on_message(filters.command(["start", "help"]), group=-16)
async def start_and_help_cmd(client: Client, message: Message):
    if not message or not message.chat:
        return

    uid = (
        message.from_user.id
        if message.from_user
        else getattr(message.sender_chat, "id", 0)
    )
    cancel_cmd_user_input(message.chat.id)

    is_admin = await is_global_admin(uid)

    if getattr(info, "REPAIR_MODE", False) and not is_admin:
        return await safe_reply_text(
            message,
            "🛠️ <b>Bot is currently under maintenance!</b>",
            parse_mode=enums.ParseMode.HTML,
        )

    if message.from_user and await is_user_banned(uid):
        return

    cmd_list = message.command or ["start"]

    # ⚡ FAST-PATH FOR FILE & SEARCH DEEP-LINKS (0ms Overhead):
    if (
        message.chat.type == enums.ChatType.PRIVATE
        and len(cmd_list) == 2
        and cmd_list[1] not in ["help", "error", "okay", "hehe", "start"]
    ):
        if message.from_user and uid not in _KNOWN_USERS_RAM:
            asyncio.create_task(_register_user_in_bg(client, message.from_user))

        cmd_data = cmd_list[1].strip()
        try:
            from plugins.commands import run_force_sub, send_requested_file
        except ImportError:
            from commands import run_force_sub, send_requested_file

        if cmd_data == "subscribe":
            return await run_force_sub(client, message)

        if cmd_data.startswith("search_"):
            query_str = re.sub(
                r"[_+\-]+", " ", cmd_data.replace("search_", "", 1)
            ).strip()
            try:
                from plugins.pm_filter import auto_filter

                message.text = query_str
                message.command = None
                await auto_filter(client, message)
            except Exception as e:
                logger.error(f"Search interceptor failed: {e}")
                await safe_reply_text(
                    message,
                    f"🔍 <b>Search Query:</b> <code>{html.escape(query_str)}</code>\n\nSend this text in our group to search!",
                    parse_mode=enums.ParseMode.HTML,
                )
            return

        # Support BATCH- and DSTORE- deep links if genlink plugin is present
        if cmd_data.startswith(("BATCH-", "DSTORE-")):
            status = await run_force_sub(
                client, message, file_id=cmd_data, mode="checksub"
            )
            if not status:
                return
            try:
                from plugins.genlink import deliver_genlink_payload

                if await deliver_genlink_payload(
                    client, uid, message.chat.id, cmd_data
                ):
                    return
            except Exception as e:
                logger.error(f"Genlink start error: {e}")

        kk, file_id = cmd_data.split("_", 1) if "_" in cmd_data else (False, False)
        pre = ("checksubp" if kk == "filep" else "checksub") if kk else False
        target_file_id = file_id or cmd_data

        status = await run_force_sub(client, message, file_id=target_file_id, mode=pre)
        if not status:
            return

        return await send_requested_file(
            client=client,
            user_id=uid,
            file_id=target_file_id,
            ident=kk or "file",
            reply_target=message,
        )

    # Sync custom UI in background/timeout-protected so `/start` never blocks
    await _ensure_ui_synced()

    if not getattr(temp, "U_NAME", None) or not getattr(temp, "B_NAME", None):
        try:
            me = await asyncio.wait_for(client.get_me(), timeout=3.0)
            temp.U_NAME = me.username
            temp.B_NAME = me.first_name
            temp.ME = me.id
        except Exception:
            pass

    bot_uname = getattr(temp, "U_NAME", None) or "my_bot"
    b_name = getattr(temp, "B_NAME", None) or "MovieBot"
    user_mention = (
        message.from_user.mention
        if message.from_user
        else (message.chat.title or "User")
    )

    is_help_command = (cmd_list[0].lower() == "help") or (
        len(cmd_list) == 2 and cmd_list[1].lower() == "help"
    )

    if is_help_command:
        if not is_admin:
            return await safe_reply_text(
                message,
                "❌ <b>Unauthorized:</b> Help menu and controls are restricted to Bot Admins only.",
                parse_mode=enums.ParseMode.HTML,
            )

        raw_help = getattr(script, "HELP_TXT", None) or "<b>⚙️ Bot Help Menu</b>"
        text = format_script_text(
            raw_help, mention=user_mention, uname=bot_uname, bname=b_name
        )
        final_text, final_keyboard = safe_parse_text_and_markup(
            text, await get_help_keyboard()
        )
        img = getattr(info, "HELP_IMG", None)
        if (
            img
            and str(img).strip().lower() not in ["none", "null", "false", ""]
            and len(final_text) <= 1024
        ):
            try:
                return await message.reply_photo(
                    photo=img,
                    caption=final_text,
                    reply_markup=final_keyboard,
                    parse_mode=enums.ParseMode.HTML,
                )
            except Exception:
                pass
        return await safe_reply_text(
            message,
            text=final_text,
            reply_markup=final_keyboard,
            parse_mode=enums.ParseMode.HTML,
            disable_web_page_preview=True,
        )

    # Group /start handling (non-blocking background chat registration)
    if message.chat.type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
        if message.chat.id not in _KNOWN_CHATS_RAM:
            asyncio.create_task(_register_chat_in_bg(client, message.chat))

        raw_start = (
            getattr(script, "START_TXT", None)
            or "<b>Hello {mention}! 👋\n\nI am {bname}, ready to find movies for you!</b>"
        )
        raw_text = format_script_text(
            raw_start,
            mention=user_mention,
            uname=bot_uname,
            bname=b_name,
        )
        final_text, final_keyboard = safe_parse_text_and_markup(
            raw_text, await get_start_keyboard(client, uid)
        )
        return await safe_reply_text(
            message,
            final_text,
            reply_markup=final_keyboard,
            parse_mode=enums.ParseMode.HTML,
            disable_web_page_preview=True,
        )

    # Register new private user in background
    if message.from_user and uid not in _KNOWN_USERS_RAM:
        asyncio.create_task(_register_user_in_bg(client, message.from_user))

    # Standard Private /start with no deep-link payload
    raw_start = (
        getattr(script, "START_TXT", None)
        or "<b>Hello {mention}! 👋\n\nWelcome to {bname}! Join our official groups below to request and download movies.</b>"
    )
    raw_text = format_script_text(
        raw_start,
        mention=user_mention,
        uname=bot_uname,
        bname=b_name,
    )
    final_text, final_keyboard = safe_parse_text_and_markup(
        raw_text, await get_start_keyboard(client, uid)
    )

    db_img = getattr(info, "START_IMG", None)
    valid_pics = [
        p
        for p in (PICS or [])
        if p and str(p).strip().lower() not in ["none", "null", "false", ""]
    ]
    photo_to_send = (
        db_img
        if (db_img and str(db_img).strip().lower() not in ["none", "null", "false", ""])
        else (random.choice(valid_pics) if valid_pics else None)
    )

    try:
        if photo_to_send and len(final_text) <= 1024:
            try:
                return await message.reply_photo(
                    photo=photo_to_send,
                    caption=final_text,
                    reply_markup=final_keyboard,
                    parse_mode=enums.ParseMode.HTML,
                )
            except Exception:
                try:
                    # Fallback if custom <tg-emoji> tags in caption failed on non-Premium bot
                    clean_cap = re.sub(r"</?tg-emoji[^>]*>", "", final_text)
                    return await message.reply_photo(
                        photo=photo_to_send,
                        caption=clean_cap,
                        reply_markup=final_keyboard,
                        parse_mode=enums.ParseMode.HTML,
                    )
                except Exception:
                    pass

        await safe_reply_text(
            message,
            text=final_text,
            reply_markup=final_keyboard,
            parse_mode=enums.ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except (UserIsBlocked, PeerIdInvalid):
        pass
    except Exception as e:
        logger.error(f"/start reply error: {e}")
        await safe_reply_text(
            message,
            text=f"<b>Hello {user_mention}! 👋</b>",
            reply_markup=final_keyboard,
            parse_mode=enums.ParseMode.HTML,
        )
