import asyncio
import builtins
import html
import inspect
import logging
import math
import random
import re
from logging import ERROR, getLogger
from typing import Any, Dict, List, Optional, Set, Tuple, Union

import requests
from motor.motor_asyncio import AsyncIOMotorClient
from pyrogram import Client, enums, filters
from pyrogram.errors import (
    FloodWait,
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
from database.ia_filterdb import get_file_details
from database.users_chats_db import db as _db
from info import AUTH_CHANNEL, CUSTOM_FILE_CAPTION, LOG_CHANNEL, PICS, REQ_CHANNEL
from Script import script
from utils import get_size, is_subscribed, temp

logger = getLogger(__name__)
logger.setLevel(ERROR)

# Safe optional imports
try:
    from database.ia_filterdb import Media
except Exception:
    Media = None

try:
    from database.plugin_dbs import plugin_db as _plugin_db
except Exception:
    _plugin_db = None

try:
    from plugins.fsub import ForceSub
except Exception as _fsub_err:
    logger.error(f"Could not import ForceSub from plugins.fsub: {_fsub_err}")
    ForceSub = None

try:
    from utils import parse_text_and_markup as _parse_text_and_markup
except Exception:
    _parse_text_and_markup = None

try:
    from utils import get_settings, save_group_settings
except Exception:
    get_settings = None
    save_group_settings = None

LOG_FILE = "TelegramBot.log"
MESSAGE_EMOJI_PLANE = '<tg-emoji emoji-id="5875465628285931233">✈️</tg-emoji> Telegram'
MESSAGE_EMOJI_LINK = '<tg-emoji emoji-id="5877465816030515018">🔗</tg-emoji> Link'

DEFAULT_CLEAN_WORDS = ["sandalwood", "mkv", "mp4", "avi", "webm", "zip", "rar"]

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


def create_btn(
    text: str,
    url: Optional[str] = None,
    callback_data: Optional[str] = None,
    style: Any = None,
) -> InlineKeyboardButton:
    """Creates an InlineKeyboardButton safely. Pass style=None for no colour."""
    kwargs: Dict[str, Any] = {"text": str(text)}
    if url:
        kwargs["url"] = str(url).strip()
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
    compat_kw = _prepare_compat_kwargs(
        kwargs, _REPLY_PARAMS, disable_preview=disable_web_page_preview
    )
    try:
        return await message.reply_text(text, **compat_kw)
    except TypeError:
        compat_kw.pop("disable_web_page_preview", None)
        compat_kw.pop("link_preview_options", None)
        compat_kw.pop("reply_parameters", None)
        compat_kw.pop("reply_to_message_id", None)
        return await message.reply_text(text, **compat_kw)


async def safe_edit_text(
    message: Message, text: str, disable_web_page_preview: bool = True, **kwargs
):
    compat_kw = _prepare_compat_kwargs(
        kwargs, _EDIT_PARAMS, disable_preview=disable_web_page_preview
    )
    try:
        return await message.edit_text(text, **compat_kw)
    except TypeError:
        compat_kw.pop("disable_web_page_preview", None)
        compat_kw.pop("link_preview_options", None)
        return await message.edit_text(text, **compat_kw)


async def safe_send_message(
    client: Client,
    chat_id: int,
    text: str,
    disable_web_page_preview: Optional[bool] = True,
    **kwargs,
):
    compat_kw = _prepare_compat_kwargs(
        kwargs, _SEND_MSG_PARAMS, disable_preview=disable_web_page_preview
    )
    try:
        return await client.send_message(chat_id=chat_id, text=text, **compat_kw)
    except TypeError:
        compat_kw.pop("disable_web_page_preview", None)
        compat_kw.pop("link_preview_options", None)
        compat_kw.pop("reply_parameters", None)
        compat_kw.pop("reply_to_message_id", None)
        return await client.send_message(chat_id=chat_id, text=text, **compat_kw)


async def safe_answer(
    query: CallbackQuery,
    text: Optional[str] = None,
    show_alert: bool = False,
    url: Optional[str] = None,
):
    """Safely answers a CallbackQuery without ever raising QueryIdInvalid or blocking UI updates."""
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
# ⚙️ MONGODB INITIALIZATION & INTERACTIVE STATE HELPERS
# ============================================================
pm_db = cw_db = _BOT_DB = None
try:
    _DB_CLIENT = AsyncIOMotorClient(info.DATABASE_URI)
    _BOT_DB = _DB_CLIENT[info.DATABASE_NAME]
    pm_db = _BOT_DB["pm_settings"]
    cw_db = _BOT_DB["clean_words"]
except Exception as e:
    logger.error(f"Failed to init databases: {e}")


async def get_pm_settings() -> Dict[str, Any]:
    default_settings = {
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
    }
    if pm_db is None:
        return default_settings
    try:
        settings = await pm_db.find_one({"id": "pm_config"})
        if not settings:
            return default_settings
        return {**default_settings, **settings}
    except Exception as e:
        logger.error(f"Error fetching PM settings: {e}")
        return default_settings


async def save_pm_settings(key: str, value: Any):
    if pm_db is not None:
        await pm_db.update_one({"id": "pm_config"}, {"$set": {key: value}}, upsert=True)


async def get_clean_words_state() -> Tuple[bool, List[str]]:
    """Returns (use_default, active_words_list)."""
    if cw_db is None:
        return True, list(DEFAULT_CLEAN_WORDS)
    try:
        doc = await cw_db.find_one({"id": "words"})
        if not doc or doc.get("use_default", True):
            return True, list(DEFAULT_CLEAN_WORDS)
        return False, list(doc.get("list", []))
    except Exception:
        return True, list(DEFAULT_CLEAN_WORDS)


def _invalidate_pm_filter_clean_cache():
    try:
        import plugins.pm_filter as _pmf

        _pmf._CLEAN_WORDS_CACHE = (0.0, DEFAULT_CLEAN_WORDS)
    except Exception:
        pass


# ============================================================
# 🔄 INTERACTIVE INPUT LISTENER FOR HELP BUTTONS (NON-STUCK)
# ============================================================
_CMD_WAITING_INPUT: Dict[int, Dict[str, Any]] = {}


def cancel_cmd_user_input(chat_id: int):
    """Cancels any pending interactive input session in a chat so buttons never get stuck."""
    session = _CMD_WAITING_INPUT.pop(chat_id, None)
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


@Client.on_message(filters.private | filters.group, group=-15)
async def _cmd_interactive_listener(client: Client, message: Message):
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
    if session and (uid == session["user_id"] or uid == chat_id):
        fut = session["future"]
        if not fut.done():
            fut.set_result(message)
        message.stop_propagation()


async def wait_cmd_user_input(
    chat_id: int,
    user_id: int,
    prompt_msg: Optional[Message] = None,
    timeout: int = 90,
) -> Optional[Message]:
    cancel_cmd_user_input(chat_id)
    loop = asyncio.get_running_loop()
    future = loop.create_future()
    _CMD_WAITING_INPUT[chat_id] = {
        "future": future,
        "user_id": user_id,
        "prompt_msg": prompt_msg,
    }
    try:
        return await asyncio.wait_for(future, timeout=timeout)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        return None
    finally:
        if _CMD_WAITING_INPUT.get(chat_id, {}).get("future") is future:
            _CMD_WAITING_INPUT.pop(chat_id, None)
        if prompt_msg:
            try:
                await prompt_msg.delete()
            except Exception:
                pass


# ============================================================
# 👑 SMART AUTHORIZATION & ACTIVE GROUP HELPER
# ============================================================
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
    if not user_id:
        return False
    if hasattr(temp, "BANNED_USERS") and int(user_id) in temp.BANNED_USERS:
        return True
    if _plugin_db is None or not hasattr(_plugin_db, "is_banned"):
        return False
    try:
        return bool(await _plugin_db.is_banned(user_id))
    except Exception:
        return False


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
    if _BOT_DB is not None:
        try:
            doc = await _BOT_DB["active_connections"].find_one(
                {"user_id": str(user_id)}
            )
            if doc and doc.get("group_id"):
                return int(doc["group_id"])
        except Exception:
            pass
    return None


# ============================================================
# ⚡ CLOUD IMAGE UPLOADER (ZERO-FAIL)
# ============================================================
def _upload_sync(file_bytes):
    headers = {"User-Agent": "Mozilla/5.0"}
    endpoints = [
        (
            "https://catbox.moe/user/api.php",
            {"fileToUpload": ("img.jpg", file_bytes, "image/jpeg")},
            {"reqtype": "fileupload"},
        ),
        (
            "https://graph.org/upload",
            {"file": ("img.jpg", file_bytes, "image/jpeg")},
            None,
        ),
        ("https://envs.sh", {"file": ("img.jpg", file_bytes, "image/jpeg")}, None),
        ("https://x0.at", {"file": ("img.jpg", file_bytes, "image/jpeg")}, None),
        ("https://ttm.sh", {"file": ("img.jpg", file_bytes, "image/jpeg")}, None),
        ("https://0x0.st", {"file": ("img.jpg", file_bytes, "image/jpeg")}, None),
    ]
    for url, files_dict, data_dict in endpoints:
        try:
            res = requests.post(
                url, data=data_dict, files=files_dict, headers=headers, timeout=8
            )
            if res.status_code == 200:
                if url == "https://graph.org/upload":
                    return "https://graph.org" + res.json()[0]["src"]
                elif res.text.strip().startswith("http"):
                    return res.text.strip()
        except Exception:
            continue
    return None


async def upload_image_safely(client: Client, message: Message):
    try:
        file_io = await client.download_media(message, in_memory=True)
        if not file_io:
            return None
        return await asyncio.to_thread(_upload_sync, file_io.getvalue())
    except Exception:
        return None


# ============================================================
# 🛠️ HELPER FUNCTIONS
# ============================================================
def safe_parse_text_and_markup(text: str, default_markup=None):
    if not text:
        return "", default_markup
    if callable(_parse_text_and_markup):
        try:
            parsed_text, parsed_markup = _parse_text_and_markup(text, default_markup)
            return parsed_text or text, parsed_markup or default_markup
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
    """Safely formats Script templates whether they use named or positional placeholders."""
    if not template:
        return ""
    uname = uname or getattr(temp, "U_NAME", None) or "Bot"
    bname = bname or getattr(temp, "B_NAME", None) or "MovieBot"

    mapping = _SafeFormatDict(
        mention=mention,
        user=mention,
        uname=uname,
        bname=bname,
        bot=bname,
        plane_emoji=MESSAGE_EMOJI_PLANE,
        link_emoji=MESSAGE_EMOJI_LINK,
        **extra_kwargs,
    )

    try:
        return template.format_map(mapping)
    except (IndexError, ValueError, KeyError):
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
                return template


def get_html_text(message: Message):
    if message.reply_to_message:
        reply_msg = message.reply_to_message
        raw = reply_msg.text or reply_msg.caption
        if raw:
            return getattr(raw, "html", str(raw))
    if message.text and len(message.command) > 1:
        html_text = getattr(message.text, "html", str(message.text))
        return re.sub(r"^/\w+(?:@[a-zA-Z0-9_]+)?\s+", "", html_text, count=1)
    return None


def parse_timer(var_name: str, default_time: int = 1800) -> int:
    try:
        global_switch = getattr(info, "AUTO_DELETE", True)
        if str(global_switch).strip().lower() in ["false", "off", "0", "no"]:
            return 0
        val = getattr(info, "AUTO_DELETE_TIME", getattr(info, var_name, default_time))
        if isinstance(val, bool):
            return 1800 if val else 0
        parsed_time = int(str(val).strip())
        return 1800 if 0 < parsed_time < 10 else max(0, parsed_time)
    except Exception:
        return 1800


async def run_force_sub(client: Client, message: Message, file_id=False, mode=False):
    if not callable(ForceSub):
        return True
    try:
        return await ForceSub(client, message, file_id=file_id, mode=mode)
    except TypeError:
        try:
            return await ForceSub(client, message, file_id=file_id)
        except TypeError:
            return await ForceSub(client, message)
    except Exception as e:
        logger.error(f"ForceSub error: {e}")
        return True


# ============================================================
# 🔘 KEYBOARD & BUTTON BUILDERS (CLEAN, NO HELP COLORS, NO MIXING)
# ============================================================
def get_close_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[create_btn("🔐 Close", callback_data="close_data")]])


def get_cancel_input_keyboard(back_cb: str = "help") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[create_btn("❌ Cancel", callback_data=f"hact#cancel_input#{back_cb}")]]
    )


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
    if await is_global_admin(user_id):
        # Help & About buttons have NO color
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
    """
    Main Help Menu Keyboard:
    - Strictly NO colours on any buttons.
    - Auto Post button removed.
    - Clean, organized layout with zero duplicate buttons.
    """
    return InlineKeyboardMarkup(
        [
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
                create_btn("💾 Backup", callback_data="helps_backup"),
            ],
            [
                create_btn("🔙 Back", callback_data="start"),
                create_btn("🔐 Close", callback_data="close_data"),
            ],
        ]
    )


async def get_about_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [create_btn("📊 Sᴛᴀᴛᴜs", callback_data="stats")],
            [
                create_btn("🏘 Hᴏᴍᴇ", callback_data="start"),
                create_btn("🔐 Cʟᴏsᴇ", callback_data="close_data"),
            ],
        ]
    )


def get_stats_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                create_btn("🔙 Back", callback_data="about"),
                create_btn("🔄 Refresh", callback_data="rfrsh"),
            ]
        ]
    )


def get_cleanwords_keyboard(use_default: bool = True) -> InlineKeyboardMarkup:
    """Clean Filename interactive control buttons (no colours, no duplicate buttons)."""
    mode_label = "🔄 Mode: Default ✅" if use_default else "🔄 Restore Default Words"
    return InlineKeyboardMarkup(
        [
            [
                create_btn("➕ Add Words", callback_data="hact#cw_add"),
                create_btn("✏️ Replace All", callback_data="hact#cw_set"),
            ],
            [
                create_btn(mode_label, callback_data="hact#cw_default"),
                create_btn("🗑️ Clear All Words", callback_data="hact#cw_clear"),
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
    """
    Builds interactive 1-click toggle & management buttons for Help sub-menus.
    - Strictly NO colours on any Help buttons.
    - Single 1-click toggle button per setting (no duplicate ON/OFF buttons).
    - Zero mixing of unrelated buttons across categories.
    """
    st = state or {}
    rows: List[List[InlineKeyboardButton]] = []

    if section_key == "helps_spell":
        at_on = bool(st.get("at_on", True))
        mc_on = bool(st.get("mc_on", True))
        spell_on = bool(st.get("spell_on", True))
        stops_count = int(st.get("stops_count", 0))

        rows.extend(
            [
                [
                    create_btn(
                        f"🔤 Auto-Translate: {'ON ✅' if at_on else 'OFF ❌'}",
                        callback_data="hact#at_toggle",
                    ),
                    create_btn(
                        f"💡 Multi-Choice: {'ON ✅' if mc_on else 'OFF ❌'}",
                        callback_data="hact#mc_toggle",
                    ),
                ],
                [
                    create_btn(
                        f"🔍 Group Spell Check: {'ON ✅' if spell_on else 'OFF ❌'}",
                        callback_data="hact#spell_toggle",
                    )
                ],
                [
                    create_btn(
                        f"📋 View Stopwords ({stops_count})",
                        callback_data="hact#sw_list",
                    ),
                    create_btn(
                        "➕ Add Stopwords",
                        callback_data="hact#sw_add",
                    ),
                ],
                [
                    create_btn(
                        "🔄 Default Stopwords",
                        callback_data="hact#sw_def",
                    ),
                    create_btn(
                        "🗑️ Clear Stopwords",
                        callback_data="hact#sw_clear",
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
                        f"💬 PM Reply: {'ON ✅' if pm_enabled else 'OFF ❌'}",
                        callback_data="hact#pm_toggle",
                    ),
                    create_btn(
                        f"👑 Reply Admins: {'ON ✅' if reply_admins else 'OFF ❌'}",
                        callback_data="hact#pm_adm_toggle",
                    ),
                ],
                [
                    create_btn("✏️ Set PM Text", callback_data="hact#pm_settext"),
                    create_btn("🔗 Set PM Button", callback_data="hact#pm_setbtn"),
                ],
                [
                    create_btn("🔄 Default PM Text", callback_data="hact#pm_deftext"),
                    create_btn("🗑️ Remove PM Button", callback_data="hact#pm_rembtn"),
                ],
                [
                    create_btn("🖼️ Remove PM Image", callback_data="hact#pm_remimg"),
                ],
            ]
        )

    elif section_key == "helps_forcesub":
        f_on = bool(st.get("f_on", True))
        rot_on = bool(st.get("rot_on", False))
        ch_count = int(st.get("ch_count", 0))

        rows.extend(
            [
                [
                    create_btn(
                        f"📱 ForceSub: {'ON ✅' if f_on else 'OFF ❌'}",
                        callback_data="hact#fsub_toggle",
                    ),
                    create_btn(
                        f"🔄 Auto-Rotate: {'ON ✅' if rot_on else 'OFF ❌'}",
                        callback_data="hact#fsub_rot",
                    ),
                ],
                [
                    create_btn(
                        f"📋 View Channels ({ch_count})",
                        callback_data="hact#fsub_list",
                    )
                ],
            ]
        )

    elif section_key == "helps_welcome":
        welc_on = bool(st.get("welc_on", True))
        rows.extend(
            [
                [
                    create_btn(
                        f"👋 Welcome Message: {'ON ✅' if welc_on else 'OFF ❌'}",
                        callback_data="hact#welc_toggle",
                    )
                ],
                [
                    create_btn(
                        "✏️ Set Welcome Text", callback_data="hact#welc_settxt"
                    ),
                    create_btn("🗑️ Reset Welcome", callback_data="hact#welc_del"),
                ],
            ]
        )

    elif section_key == "helps_filters":
        rows.append(
            [
                create_btn(
                    "📋 View Group Filters",
                    callback_data="hact#flt_list",
                )
            ]
        )

    elif section_key == "helps_settings":
        rep_on = bool(st.get("rep_on", False))
        rows.append(
            [
                create_btn(
                    f"🛠️ Repair Mode: {'ON ✅' if rep_on else 'OFF ❌'}",
                    callback_data="hact#repair_toggle",
                )
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
# ⏳ SILENT AUTO-DELETE ENGINE
# ============================================================
AUTO_DELETE_TASKS = set()


async def auto_delete_all_messages(
    client: Client, chat_id: int, is_pm: bool, delay: int, *messages
):
    await asyncio.sleep(delay)

    msg_ids = [m.id for m in messages if m is not None and hasattr(m, "id") and m.id]
    if msg_ids:
        try:
            await client.delete_messages(chat_id, msg_ids)
        except Exception:
            for msg in messages:
                if msg:
                    try:
                        await msg.delete()
                    except Exception:
                        pass

    if is_pm:
        notify_text = (
            "<b>Successfully deleted your file, if you want request again in group.</b>"
        )
        markup = InlineKeyboardMarkup(
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
        try:
            await safe_send_message(
                client,
                chat_id,
                text=notify_text,
                reply_markup=markup,
                parse_mode=enums.ParseMode.HTML,
            )
        except Exception:
            pass


def schedule_pm_auto_delete(
    client: Client, chat_id: int, is_pm: bool, delay: int, *messages
):
    if delay <= 0:
        return
    task = asyncio.create_task(
        auto_delete_all_messages(client, chat_id, is_pm, delay, *messages)
    )
    AUTO_DELETE_TASKS.add(task)
    task.add_done_callback(AUTO_DELETE_TASKS.discard)


# ============================================================
# 🎛️ HELP UI SECTION BUILDERS
# ============================================================
async def build_cleanwords_panel_ui() -> Tuple[str, InlineKeyboardMarkup]:
    """Builds the Clean Filename Words panel using Script.py text and clean buttons."""
    use_default, words = await get_clean_words_state()
    mode_str = "🟢 Default Clean Words" if use_default else "🔵 Custom Clean Words"
    words_display = (
        ", ".join(f"<code>{html.escape(str(w))}</code>" for w in words)
        if words
        else "<i>None (Filenames shown uncut)</i>"
    )
    text = script.CLEANFILE_TXT.format(
        mode_str=mode_str,
        count=len(words),
        words_display=words_display,
    )
    return text, get_cleanwords_keyboard(use_default=use_default)


async def build_interactive_help_section(
    client: Client,
    section_key: str,
    user_id: int,
    user_mention: str,
    msg_context: Optional[Message] = None,
) -> Tuple[str, InlineKeyboardMarkup]:
    """Builds Help section text from Script.py and attaches clean interactive buttons."""
    if section_key == "helps_cleanfile":
        return await build_cleanwords_panel_ui()

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
        "helps_index": ("INDEX_TXT", "📚 <b>Index Help</b>"),
        "helps_settings": ("SETTINGS_TXT", "⚙️ <b>Settings Help</b>"),
        "helps_connections": ("CONNECTIONS_TXT", "🌐 <b>Connections Help</b>"),
        "helps_utilities": ("UTILITIES_TXT", "📊 <b>Utilities Help</b>"),
        "helps_custommessages": ("CUSTOMMESSAGES_TXT", "💬 <b>Custom Messages</b>"),
        "helps_posthand": ("POSTHAND_TXT", "📝 <b>Post Handle Help</b>"),
        "helps_customcaption": ("CUSTOMCAPTION_TXT", "📝 <b>Custom Captions Help</b>"),
        "helps_backup": ("BACKUP_TXT", "💾 <b>Backup Help</b>"),
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

    if section_key == "helps_spell":
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
            f"• <b>Active Button:</b> <code>{html.escape(str(btn_txt))}</code> (<code>{btn_color}</code>)"
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
            f"• <b>Auto-Rotation:</b> <code>{'ON ✅' if rot_on else 'OFF ❌'}</code>\n"
            f"• <b>Channels:</b> <code>{ch_count}</code> | <b>Join Requests:</b> <code>{req_count}</code>"
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
        base_text += (
            f"\n\n━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔗 <b>Connected Group:</b> <code>{conn_gid or 'None (Use /connect <group_id>)'}</code>"
        )

    elif section_key == "helps_settings":
        rep_on = bool(getattr(info, "REPAIR_MODE", False))
        state = {"rep_on": rep_on}
        base_text += (
            f"\n\n━━━━━━━━━━━━━━━━━━━━━\n"
            f"🎛️ <b>Live System Status:</b>\n"
            f"• <b>Repair / Maintenance Mode:</b> <code>{'ON ✅' if rep_on else 'OFF ❌'}</code>"
        )

    return base_text, get_help_section_keyboard(section_key, state)


async def transition_ui_message(
    client: Client, msg_obj: Message, text: str, keyboard, img=None
):
    """Smoothly transitions between photo and text messages without getting stuck."""
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
# 📦 SHARED FILE SENDER LOGIC
# ============================================================
async def send_requested_file(
    client: Client,
    user_id: int,
    file_id: str,
    ident: str = "file",
    reply_target: Message = None,
    query: CallbackQuery = None,
):
    files_ = await get_file_details(file_id)
    if not files_:
        if query:
            await safe_answer(query, "⚠️ No such file exists.", show_alert=True)
        elif reply_target:
            await safe_reply_text(
                reply_target,
                "⚠️ No such file exists.",
                parse_mode=enums.ParseMode.HTML,
            )
        return

    files = files_[0]
    title = str(
        files.get("file_name", "Unknown")
        if isinstance(files, dict)
        else getattr(files, "file_name", "Unknown")
    )
    size = get_size(
        int(
            files.get("file_size", 0)
            if isinstance(files, dict)
            else getattr(files, "file_size", 0)
        )
    )
    f_caption = str(
        files.get("caption", "")
        if isinstance(files, dict)
        else getattr(files, "caption", "")
    )
    db_file_id = (
        files.get("full_file_id", files.get("file_id", file_id))
        if isinstance(files, dict)
        else getattr(files, "full_file_id", getattr(files, "file_id", file_id))
    )

    if CUSTOM_FILE_CAPTION:
        try:
            f_caption = CUSTOM_FILE_CAPTION.format(
                file_name="" if title == "Unknown" else title,
                file_size="" if size == "0B" else size,
                file_caption="" if not f_caption else f_caption,
            )
        except Exception:
            pass

    if not f_caption:
        f_caption = f"<b>{title}</b>"
    elif not f_caption.strip().startswith("<b>"):
        f_caption = f"<b>{f_caption}</b>"

    if getattr(info, "CAPTION_PLUS", None):
        f_caption += f"\n\n{info.CAPTION_PLUS}"

    default_btn = InlineKeyboardMarkup(
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
    final_caption, final_keyboard = safe_parse_text_and_markup(f_caption, default_btn)
    protect = True if ident in ["filep", "checksubp"] else False

    msg = None
    try:
        msg = await client.send_cached_media(
            chat_id=user_id,
            file_id=db_file_id,
            caption=final_caption,
            reply_markup=final_keyboard,
            protect_content=protect,
            parse_mode=enums.ParseMode.HTML,
        )
    except FloodWait as e:
        await asyncio.sleep(e.value + 1)
        msg = await client.send_cached_media(
            chat_id=user_id,
            file_id=db_file_id,
            caption=final_caption,
            reply_markup=final_keyboard,
            protect_content=protect,
            parse_mode=enums.ParseMode.HTML,
        )
    except (UserIsBlocked, PeerIdInvalid):
        if query and getattr(temp, "U_NAME", None):
            return await safe_answer(
                query, url=f"https://t.me/{temp.U_NAME}?start={ident}_{file_id}"
            )
        return
    except Exception:
        try:
            msg = await client.send_document(
                chat_id=user_id,
                document=db_file_id,
                caption=final_caption,
                reply_markup=final_keyboard,
                protect_content=protect,
                parse_mode=enums.ParseMode.HTML,
            )
        except (UserIsBlocked, PeerIdInvalid):
            if query and getattr(temp, "U_NAME", None):
                return await safe_answer(
                    query, url=f"https://t.me/{temp.U_NAME}?start={ident}_{file_id}"
                )
            return
        except Exception as err:
            if query:
                return await safe_answer(query, f"⚠️ Error: {err}", show_alert=True)
            if reply_target:
                return await safe_reply_text(
                    reply_target,
                    f"⚠️ <b>Error:</b>\n<code>{err}</code>",
                    parse_mode=enums.ParseMode.HTML,
                )
            return

    if query:
        await safe_answer(query, "📥 File sent to your PM!")

    if msg:
        try:
            delete_timer = parse_timer("FILE_AUTO_DELETE", 1800)
            m, s = divmod(delete_timer, 60)
            time_str = f"{m} Minutes {s} Seconds" if s > 0 else f"{m} Minutes"

            warn_text = (
                f"<b>📢 Please Note\n\n"
                f"✅ The above file will be autodeleted in {time_str} to avoid copyright issues.\n\n"
                f"✅ Please forward this file to your saved messages and start downloading from there.\n\n"
                f"Tᴇᴀᴍ: @KR_Picture</b>"
            )
            k = await safe_send_message(
                client,
                chat_id=user_id,
                text=warn_text,
                reply_to_message_id=msg.id,
                parse_mode=enums.ParseMode.HTML,
            )

            if delete_timer > 0:
                schedule_pm_auto_delete(client, user_id, True, delete_timer, msg, k)
        except Exception as e:
            logger.error(f"Auto-delete warning failed to send: {e}")


# ============================================================
# 🎯 MAIN START & HELP COMMANDS
# ============================================================
@Client.on_message(filters.command(["start", "help"]) & filters.incoming)
async def start(client: Client, message: Message):
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

    if not getattr(temp, "U_NAME", None) or not getattr(temp, "B_NAME", None):
        try:
            me = await client.get_me()
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

    is_help_command = (message.command[0].lower() == "help") or (
        len(message.command) == 2 and message.command[1].lower() == "help"
    )

    if is_help_command:
        if not is_admin:
            return await safe_reply_text(
                message,
                "❌ <b>Unauthorized:</b> Help menu and controls are restricted to Bot Admins only.",
                parse_mode=enums.ParseMode.HTML,
            )

        raw_help = getattr(script, "HELP_TXT", "<b>Help Menu</b>")
        text = format_script_text(
            raw_help, mention=user_mention, uname=bot_uname, bname=b_name
        )
        final_text, final_keyboard = safe_parse_text_and_markup(
            text, await get_help_keyboard()
        )
        img = getattr(info, "HELP_IMG", None)
        if img and len(final_text) <= 1024:
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

    # Group /start handling
    if message.chat.type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
        raw_text = format_script_text(
            getattr(script, "START_TXT", "Hello {mention}!"),
            mention=user_mention,
            uname=bot_uname,
            bname=b_name,
        )
        final_text, final_keyboard = safe_parse_text_and_markup(
            raw_text, await get_start_keyboard(client, uid)
        )
        await safe_reply_text(
            message,
            final_text,
            reply_markup=final_keyboard,
            parse_mode=enums.ParseMode.HTML,
            disable_web_page_preview=True,
        )
        await asyncio.sleep(2)
        if not await _db.get_chat(message.chat.id):
            try:
                total = await client.get_chat_members_count(message.chat.id)
                if LOG_CHANNEL:
                    await safe_send_message(
                        client,
                        LOG_CHANNEL,
                        script.LOG_TEXT_G.format(
                            message.chat.title, message.chat.id, total, "Unknown"
                        ),
                    )
            except Exception:
                pass
            await _db.add_chat(message.chat.id, message.chat.title)
        return

    # Register new private user
    if message.from_user and not await _db.is_user_exist(message.from_user.id):
        await _db.add_user(message.from_user.id, message.from_user.first_name)
        if LOG_CHANNEL:
            try:
                await safe_send_message(
                    client,
                    LOG_CHANNEL,
                    script.LOG_TEXT_P.format(
                        message.from_user.id, message.from_user.mention
                    ),
                )
            except Exception:
                pass

    # Standard /start with no deep-link payload
    if len(message.command) != 2 or message.command[1] in ["error", "okay", "hehe"]:
        raw_text = format_script_text(
            getattr(script, "START_TXT", "Hello {mention}!"),
            mention=user_mention,
            uname=bot_uname,
            bname=b_name,
        )
        final_text, final_keyboard = safe_parse_text_and_markup(
            raw_text, await get_start_keyboard(client, uid)
        )
        db_img = getattr(info, "START_IMG", None)
        photo_to_send = db_img if db_img else (random.choice(PICS) if PICS else None)

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
        return

    cmd_data = message.command[1]

    if cmd_data == "subscribe":
        return await run_force_sub(client, message)

    # 1. HANDLE DIRECT SEARCH LINKS
    if cmd_data.startswith("search_"):
        query_str = re.sub(r"[_+\-]+", " ", cmd_data.replace("search_", "", 1)).strip()
        try:
            from plugins.pm_filter import auto_filter

            message.text = query_str
            message.command = None
            await auto_filter(client, message)
        except Exception as e:
            logger.error(f"Search interceptor failed: {e}")
            await safe_reply_text(
                message,
                f"🔍 <b>Search Query:</b> <code>{query_str}</code>\n\nSend this text in our group to search!",
                parse_mode=enums.ParseMode.HTML,
            )
        return

    # 2. HANDLE STANDARD FILE LINKS
    kk, file_id = cmd_data.split("_", 1) if "_" in cmd_data else (False, False)
    pre = ("checksubp" if kk == "filep" else "checksub") if kk else False
    target_file_id = file_id or cmd_data

    status = await run_force_sub(client, message, file_id=target_file_id, mode=pre)
    if not status:
        return

    await send_requested_file(
        client=client,
        user_id=message.from_user.id,
        file_id=target_file_id,
        ident=kk or "file",
        reply_target=message,
    )


# ============================================================
# ⚙️ CLEAN FILENAME COMMANDS (ADMIN ONLY)
# ============================================================
@Client.on_message(
    filters.command(["listcleanfilename", "cleanfilenames", "cleanwords"])
    & filters.incoming,
    group=-2,
)
async def list_clean_words_cmd(client: Client, message: Message):
    uid = (
        message.from_user.id
        if message.from_user
        else getattr(message.sender_chat, "id", 0)
    )
    if not await is_global_admin(uid):
        return await safe_reply_text(
            message,
            "❌ <b>Unauthorized:</b> Global Bot Admin only.",
            parse_mode=enums.ParseMode.HTML,
        )

    text, markup = await build_cleanwords_panel_ui()
    await safe_reply_text(
        message,
        text,
        reply_markup=markup,
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(filters.command("setcleanfilename") & filters.incoming, group=-2)
async def set_clean_words(client: Client, message: Message):
    uid = (
        message.from_user.id
        if message.from_user
        else getattr(message.sender_chat, "id", 0)
    )
    if not await is_global_admin(uid):
        return await safe_reply_text(
            message,
            "❌ <b>Unauthorized:</b> Global Bot Admin only.",
            parse_mode=enums.ParseMode.HTML,
        )

    if len(message.command) < 2:
        text, markup = await build_cleanwords_panel_ui()
        return await safe_reply_text(
            message,
            "⚠️ <b>Usage:</b> <code>/setcleanfilename word1, word2, @ChannelName</code>\n\n"
            + text,
            reply_markup=markup,
            parse_mode=enums.ParseMode.HTML,
        )
    words_list = [
        w.strip() for w in message.text.split(None, 1)[1].split(",") if w.strip()
    ]
    if cw_db is not None:
        await cw_db.update_one(
            {"id": "words"},
            {"$set": {"list": words_list, "use_default": False}},
            upsert=True,
        )
        _invalidate_pm_filter_clean_cache()
        text, markup = await build_cleanwords_panel_ui()
        await safe_reply_text(
            message,
            f"✅ <b>Clean Words Updated Successfully!</b>\n\n{text}",
            reply_markup=markup,
            parse_mode=enums.ParseMode.HTML,
        )


@Client.on_message(filters.command("defaultcleanfilename") & filters.incoming, group=-2)
async def default_clean_words(client: Client, message: Message):
    uid = (
        message.from_user.id
        if message.from_user
        else getattr(message.sender_chat, "id", 0)
    )
    if not await is_global_admin(uid):
        return await safe_reply_text(
            message,
            "❌ <b>Unauthorized:</b> Global Bot Admin only.",
            parse_mode=enums.ParseMode.HTML,
        )

    if cw_db is not None:
        await cw_db.update_one(
            {"id": "words"}, {"$set": {"use_default": True}}, upsert=True
        )
        _invalidate_pm_filter_clean_cache()
        text, markup = await build_cleanwords_panel_ui()
        await safe_reply_text(
            message,
            f"✅ <b>Reverted to Default Clean Words!</b>\n\n{text}",
            reply_markup=markup,
            parse_mode=enums.ParseMode.HTML,
        )


@Client.on_message(filters.command("remcleanfilename") & filters.incoming, group=-2)
async def rem_clean_words(client: Client, message: Message):
    uid = (
        message.from_user.id
        if message.from_user
        else getattr(message.sender_chat, "id", 0)
    )
    if not await is_global_admin(uid):
        return await safe_reply_text(
            message,
            "❌ <b>Unauthorized:</b> Global Bot Admin only.",
            parse_mode=enums.ParseMode.HTML,
        )

    if cw_db is not None:
        await cw_db.update_one(
            {"id": "words"}, {"$set": {"list": [], "use_default": False}}, upsert=True
        )
        _invalidate_pm_filter_clean_cache()
        text, markup = await build_cleanwords_panel_ui()
        await safe_reply_text(
            message,
            f"🗑️ <b>All Clean Words Removed!</b>\n\n{text}",
            reply_markup=markup,
            parse_mode=enums.ParseMode.HTML,
        )


# ============================================================
# ⚙️ PM REPLY SETTINGS SETUP COMMANDS (ADMIN ONLY)
# ============================================================
@Client.on_message(filters.command("setpmtext") & filters.incoming, group=-2)
async def set_pm_text(client: Client, message: Message):
    uid = (
        message.from_user.id
        if message.from_user
        else getattr(message.sender_chat, "id", 0)
    )
    if not await is_global_admin(uid):
        return await safe_reply_text(
            message,
            "❌ <b>Unauthorized:</b> Global Bot Admin only.",
            parse_mode=enums.ParseMode.HTML,
        )
    try:
        text = get_html_text(message)
        if not text:
            return await safe_reply_text(
                message,
                "⚙️ <b>Usage:</b> <code>/setpmtext Your Text Here</code> or reply to a message.",
                parse_mode=enums.ParseMode.HTML,
            )
        await save_pm_settings("text", text)
        await safe_reply_text(
            message,
            f"✅ <b>PM Text updated successfully to:</b>\n\n{text}",
            parse_mode=enums.ParseMode.HTML,
        )
    except Exception as e:
        await safe_reply_text(message, f"⚠️ Error: {e}")


@Client.on_message(filters.command("rempmtext") & filters.incoming, group=-2)
async def rem_pm_text(client: Client, message: Message):
    uid = (
        message.from_user.id
        if message.from_user
        else getattr(message.sender_chat, "id", 0)
    )
    if not await is_global_admin(uid):
        return await safe_reply_text(
            message,
            "❌ <b>Unauthorized:</b> Global Bot Admin only.",
            parse_mode=enums.ParseMode.HTML,
        )
    await save_pm_settings(
        "text",
        "<b>🚫 Don't Message Here, Message Here Only!</b>\n\nI do not respond to direct messages in PM. Please join our official group to request and download movies.",
    )
    await safe_reply_text(
        message,
        "✅ <b>PM Text reset to default.</b>",
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(filters.command("setpmimage") & filters.incoming, group=-2)
async def set_pm_image(client: Client, message: Message):
    uid = (
        message.from_user.id
        if message.from_user
        else getattr(message.sender_chat, "id", 0)
    )
    if not await is_global_admin(uid):
        return await safe_reply_text(
            message,
            "❌ <b>Unauthorized:</b> Global Bot Admin only.",
            parse_mode=enums.ParseMode.HTML,
        )
    if not message.reply_to_message or not message.reply_to_message.photo:
        return await safe_reply_text(
            message,
            "⚙️ <b>Usage:</b> Reply to a photo with <code>/setpmimage</code>",
            parse_mode=enums.ParseMode.HTML,
        )

    status = await safe_reply_text(
        message, "⏳ <b>Uploading to Cloud...</b>", parse_mode=enums.ParseMode.HTML
    )
    url = await upload_image_safely(client, message.reply_to_message)
    if url:
        await save_pm_settings("image", url)
        await safe_edit_text(
            status,
            "✅ <b>PM Image updated successfully!</b>",
            parse_mode=enums.ParseMode.HTML,
        )
    else:
        file_id = message.reply_to_message.photo.file_id
        await save_pm_settings("image", file_id)
        await safe_edit_text(
            status,
            "⚠️ Cloud upload failed. <b>PM Image saved using Telegram File_ID!</b>",
            parse_mode=enums.ParseMode.HTML,
        )


@Client.on_message(filters.command("rempmimage") & filters.incoming, group=-2)
async def rem_pm_image(client: Client, message: Message):
    uid = (
        message.from_user.id
        if message.from_user
        else getattr(message.sender_chat, "id", 0)
    )
    if not await is_global_admin(uid):
        return await safe_reply_text(
            message,
            "❌ <b>Unauthorized:</b> Global Bot Admin only.",
            parse_mode=enums.ParseMode.HTML,
        )
    await save_pm_settings("image", None)
    await safe_reply_text(
        message, "✅ <b>PM Image removed.</b>", parse_mode=enums.ParseMode.HTML
    )


@Client.on_message(filters.command("setpmbutton") & filters.incoming, group=-2)
async def set_pm_button(client: Client, message: Message):
    uid = (
        message.from_user.id
        if message.from_user
        else getattr(message.sender_chat, "id", 0)
    )
    if not await is_global_admin(uid):
        return await safe_reply_text(
            message,
            "❌ <b>Unauthorized:</b> Global Bot Admin only.",
            parse_mode=enums.ParseMode.HTML,
        )
    try:
        if len(message.command) < 2:
            return await safe_reply_text(
                message,
                "⚙️ <b>Usage:</b> <code>/setpmbutton Text | URL | Color</code>",
                parse_mode=enums.ParseMode.HTML,
            )
        args = message.text.split(None, 1)[1].split("|")
        if len(args) < 2:
            return await safe_reply_text(
                message,
                "❌ Invalid format. Use: <code>Text | URL | Color</code>",
                parse_mode=enums.ParseMode.HTML,
            )

        btn_text, btn_url = args[0].strip(), args[1].strip()
        btn_color = args[2].strip().lower() if len(args) > 2 else "normal"
        if btn_color not in ["green", "red", "blue", "normal"]:
            btn_color = "normal"

        await save_pm_settings("button_text", btn_text)
        await save_pm_settings("button_url", btn_url)
        await save_pm_settings("button_color", btn_color)
        await safe_reply_text(
            message,
            f"✅ <b>PM Button updated!</b>\n<b>Text:</b> {btn_text}\n<b>URL:</b> {btn_url}\n<b>Color:</b> {btn_color}",
            parse_mode=enums.ParseMode.HTML,
        )
    except Exception as e:
        await safe_reply_text(message, f"⚠️ Error: {e}")


@Client.on_message(filters.command("rempmbutton") & filters.incoming, group=-2)
async def rem_pm_button(client: Client, message: Message):
    uid = (
        message.from_user.id
        if message.from_user
        else getattr(message.sender_chat, "id", 0)
    )
    if not await is_global_admin(uid):
        return await safe_reply_text(
            message,
            "❌ <b>Unauthorized:</b> Global Bot Admin only.",
            parse_mode=enums.ParseMode.HTML,
        )
    await save_pm_settings("button_text", None)
    await save_pm_settings("button_url", None)
    await safe_reply_text(
        message,
        "✅ <b>PM Button removed completely.</b>",
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(
    filters.command(["pmautoreply", "pmreply"]) & filters.incoming, group=-2
)
async def toggle_pm_autoreply_cmd(client: Client, message: Message):
    uid = (
        message.from_user.id
        if message.from_user
        else getattr(message.sender_chat, "id", 0)
    )
    if not await is_global_admin(uid):
        return await safe_reply_text(
            message,
            "❌ <b>Unauthorized:</b> Global Bot Admin only.",
            parse_mode=enums.ParseMode.HTML,
        )

    settings = await get_pm_settings()
    cur = bool(settings.get("enabled", True))
    if len(message.command) > 1:
        arg = message.command[1].strip().lower()
        new_val = (
            True
            if arg in ["on", "enable", "true", "1", "yes"]
            else False if arg in ["off", "disable", "false", "0", "no"] else (not cur)
        )
    else:
        new_val = not cur

    await save_pm_settings("enabled", new_val)
    text, markup = await build_interactive_help_section(
        client,
        "helps_pmautoreply",
        uid,
        message.from_user.mention if message.from_user else "Admin",
        message,
    )
    await safe_reply_text(
        message,
        text,
        reply_markup=markup,
        parse_mode=enums.ParseMode.HTML,
    )


# ============================================================
# ⚙️ CHANNELS & SETTINGS (ADMIN ONLY)
# ============================================================
async def get_channels_page(client: Client, page: int = 1):
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
        text += (
            f"<b>{i}. {title}</b>\n🔗 Link: {link}\n🆔 ID: <code>{chat_id}</code>\n\n"
        )

    return text, get_channels_page_keyboard(page, total_pages)


@Client.on_message(filters.command(["channels", "channel"]) & filters.incoming)
async def list_all_channels_cmd(client: Client, message: Message):
    uid = (
        message.from_user.id
        if message.from_user
        else getattr(message.sender_chat, "id", 0)
    )
    if not await is_global_admin(uid):
        return await safe_reply_text(
            message,
            "❌ <b>Unauthorized:</b> Global Bot Admin only.",
            parse_mode=enums.ParseMode.HTML,
        )

    status_msg = await safe_reply_text(message, "⏳ Generating link database...")
    text, reply_markup = await get_channels_page(client, page=1)
    await safe_edit_text(
        status_msg,
        text,
        reply_markup=reply_markup,
        disable_web_page_preview=True,
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(filters.command(["leavechannel", "leave"]) & filters.incoming)
async def leave_channel_cmd(client: Client, message: Message):
    uid = (
        message.from_user.id
        if message.from_user
        else getattr(message.sender_chat, "id", 0)
    )
    if not await is_global_admin(uid):
        return await safe_reply_text(
            message,
            "❌ <b>Unauthorized:</b> Global Bot Admin only.",
            parse_mode=enums.ParseMode.HTML,
        )

    if len(message.command) < 2:
        return await safe_reply_text(
            message,
            "⚙️ <b>Usage:</b> <code>/leavechannel &lt;channel_id&gt;</code>",
            parse_mode=enums.ParseMode.HTML,
        )
    try:
        chat_id_int = int(message.command[1].strip())
    except ValueError:
        return await safe_reply_text(message, "❌ Invalid Channel ID format.")

    chat_title, tg_status, db_status = (
        "Unknown Chat",
        "⚠️ Not inside chat",
        "⚠️ Not inside DB",
    )
    try:
        chat = await client.get_chat(chat_id_int)
        chat_title = chat.title or "Unknown"
        await client.leave_chat(chat_id_int)
        tg_status = "✅ Successfully left chat."
    except Exception as e:
        tg_status = f"⚠️ Could not leave Telegram chat: {e}"

    try:
        if hasattr(_db, "delete_chat"):
            await _db.delete_chat(chat_id_int)
        elif hasattr(_db, "grp"):
            await _db.grp.delete_one({"id": chat_id_int})
            await _db.grp.delete_one({"chat_id": chat_id_int})
        db_status = "✅ Removed from Database."
    except Exception as e:
        db_status = f"❌ DB Remove Error: {e}"

    await safe_reply_text(
        message,
        f"🎯 <b>Operation Complete:</b>\n\n"
        f"<b>Name:</b> {chat_title}\n"
        f"<b>ID:</b> <code>{chat_id_int}</code>\n\n"
        f"<b>Telegram Status:</b> {tg_status}\n"
        f"<b>Database Status:</b> {db_status}",
        parse_mode=enums.ParseMode.HTML,
    )


# ============================================================
# 📊 STATUS HELPER
# ============================================================
async def build_status_text() -> str:
    total_files = 0
    users = 0
    chats = 0
    monsize = "0 B"
    free = "512 MB"

    try:
        if Media is not None:
            total_files = await Media.count_documents({})
    except Exception:
        pass

    try:
        users = await _db.total_users_count()
        chats = await _db.total_chat_count()
        raw_size = await _db.get_db_size()
        monsize = get_size(raw_size)
        free = get_size(536870912 - raw_size)
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
        f"📁 <b>Total Files:</b> <code>{total_files}</code>\n"
        f"👤 <b>Total Users:</b> <code>{users}</code>\n"
        f"👥 <b>Total Chats:</b> <code>{chats}</code>\n"
        f"💾 <b>Used Storage:</b> <code>{monsize}</code>\n"
        f"🆓 <b>Free Storage:</b> <code>{free}</code>"
    )


# ============================================================
# 🎛️ INTERACTIVE HELP ACTION CALLBACKS (hact#...) - ADMIN ONLY
# ============================================================
@Client.on_callback_query(filters.regex(r"^hact#"), group=-2)
async def interactive_help_actions_cb(client: Client, query: CallbackQuery):
    uid = query.from_user.id if query.from_user else 0
    user_mention = query.from_user.mention if query.from_user else "Admin"
    if not await is_global_admin(uid):
        return await safe_answer(
            query, "❌ Unauthorized: Bot Admin only!", show_alert=True
        )

    chat_id = query.message.chat.id
    action_raw = query.data.split("#", 1)[1]

    # Handle inline cancel button on interactive prompts
    if action_raw.startswith("cancel_input"):
        cancel_cmd_user_input(chat_id)
        await safe_answer(query, "❌ Cancelled.")
        try:
            await query.message.delete()
        except Exception:
            pass
        return

    # Always cancel any stale waiting prompt when clicking another button
    cancel_cmd_user_input(chat_id)
    action = action_raw

    # --- CLEAN FILENAME WORDS ACTIONS ---
    if action in ["cw_default", "cw_clear"]:
        if cw_db is not None:
            if action == "cw_default":
                await cw_db.update_one(
                    {"id": "words"}, {"$set": {"use_default": True}}, upsert=True
                )
                await safe_answer(query, "✅ Reverted to Default Clean Words!")
            else:
                await cw_db.update_one(
                    {"id": "words"},
                    {"$set": {"list": [], "use_default": False}},
                    upsert=True,
                )
                await safe_answer(query, "🗑️ Cleared all Clean Words!")
            _invalidate_pm_filter_clean_cache()
        text, markup = await build_cleanwords_panel_ui()
        return await transition_ui_message(client, query.message, text, markup)

    if action in ["cw_add", "cw_set"]:
        await safe_answer(query)
        mode_label = (
            "ADD to existing clean words"
            if action == "cw_add"
            else "REPLACE all clean words"
        )
        prompt = await safe_reply_text(
            query.message,
            f"🧹 <b>Send the words separated by commas to {mode_label}:</b>\n\n"
            f"Example: <code>sandalwood, mkv, @MyChannel, www.site.com</code>",
            reply_markup=get_cancel_input_keyboard("helps_cleanfile"),
            parse_mode=enums.ParseMode.HTML,
        )
        resp = await wait_cmd_user_input(chat_id, uid, prompt_msg=prompt, timeout=90)
        if not resp or not resp.text or resp.text.strip().lower() == "/cancel":
            return
        try:
            await resp.delete()
        except Exception:
            pass

        new_words = [w.strip() for w in resp.text.split(",") if w.strip()]
        if cw_db is not None and new_words:
            if action == "cw_add":
                _, cur_words = await get_clean_words_state()
                merged = list(dict.fromkeys(cur_words + new_words))
            else:
                merged = new_words
            await cw_db.update_one(
                {"id": "words"},
                {"$set": {"list": merged, "use_default": False}},
                upsert=True,
            )
            _invalidate_pm_filter_clean_cache()
        text, markup = await build_cleanwords_panel_ui()
        return await transition_ui_message(client, query.message, text, markup)

    # --- AUTO-TRANSLATE & MULTI-CHOICE 1-CLICK TOGGLES ---
    if action in ["at_toggle", "at_on", "at_off", "mc_toggle", "mc_on", "mc_off"]:
        try:
            from plugins.pm_filter import get_feature_flags, set_feature_flag

            at_cur, mc_cur = await get_feature_flags()
            if action.startswith("at_"):
                new_state = (
                    (not at_cur) if action == "at_toggle" else (action == "at_on")
                )
                await set_feature_flag("autotranslate", new_state)
                await safe_answer(
                    query,
                    f"🔤 Auto-Translate: {'ON ✅' if new_state else 'OFF ❌'}",
                )
            else:
                new_state = (
                    (not mc_cur) if action == "mc_toggle" else (action == "mc_on")
                )
                await set_feature_flag("multichoice", new_state)
                await safe_answer(
                    query,
                    f"💡 Multi-Choice: {'ON ✅' if new_state else 'OFF ❌'}",
                )
        except Exception as e:
            return await safe_answer(query, f"Error: {e}", show_alert=True)

        text, markup = await build_interactive_help_section(
            client, "helps_spell", uid, user_mention, query.message
        )
        return await transition_ui_message(client, query.message, text, markup)

    # --- GROUP SPELL CHECK 1-CLICK TOGGLE ---
    if action in ["spell_toggle", "spell_on", "spell_off"]:
        conn_gid = await get_active_connected_group(uid, query.message)
        if not conn_gid:
            return await safe_answer(
                query,
                "⚠️ Connect a group first using /connect <group_id>!",
                show_alert=True,
            )
        cur_spell = True
        if callable(get_settings):
            try:
                g_set = await get_settings(conn_gid)
                cur_spell = bool(g_set.get("spell_check", True))
            except Exception:
                pass
        new_state = (
            (not cur_spell) if action == "spell_toggle" else (action == "spell_on")
        )
        if callable(save_group_settings):
            await save_group_settings(conn_gid, "spell_check", new_state)
        await safe_answer(
            query,
            f"🔍 Spell Check {'ON ✅' if new_state else 'OFF ❌'} for {conn_gid}!",
        )
        text, markup = await build_interactive_help_section(
            client, "helps_spell", uid, user_mention, query.message
        )
        return await transition_ui_message(client, query.message, text, markup)

    # --- STOPWORDS ACTIONS ---
    if action in ["sw_list", "sw_def", "sw_clear", "sw_add"]:
        try:
            import plugins.custom_settings as _cs
        except Exception:
            return await safe_answer(
                query, "custom_settings plugin unavailable!", show_alert=True
            )

        if action == "sw_list":
            stops = _cs.get_stopwords()
            if not stops:
                return await safe_answer(
                    query, "🛑 No active stopwords configured.", show_alert=True
                )
            await safe_answer(query, "📋 Sending stopwords list...")
            formatted = ", ".join(f"<code>{html.escape(str(w))}</code>" for w in stops)
            msg_txt = (
                f"🛑 <b>Active Stopwords ({len(stops)})</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"{formatted}\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"💡 <i>Tap any word above to copy it, or use <code>/remstopwords word</code></i>"
            )
            return await safe_send_message(
                client,
                chat_id=chat_id,
                text=msg_txt[:4090],
                reply_markup=get_close_keyboard(),
                parse_mode=enums.ParseMode.HTML,
            )
        elif action == "sw_def":
            _cs.ACTIVE_STOPWORDS = _cs.DEFAULT_STOPWORDS.copy()
            await _cs.update_bot_settings("custom_stopwords", _cs.ACTIVE_STOPWORDS)
            await safe_answer(query, "✅ Stopwords reset to default!")
        elif action == "sw_clear":
            _cs.ACTIVE_STOPWORDS = []
            await _cs.update_bot_settings("custom_stopwords", [])
            await safe_answer(query, "🗑️ All stopwords cleared!")
        elif action == "sw_add":
            await safe_answer(query)
            prompt = await safe_reply_text(
                query.message,
                "🛑 <b>Send the stopwords separated by commas to add:</b>\n\n"
                "Example: <code>dubbed, kannada, fullmovie, link</code>",
                reply_markup=get_cancel_input_keyboard("helps_spell"),
                parse_mode=enums.ParseMode.HTML,
            )
            resp = await wait_cmd_user_input(
                chat_id, uid, prompt_msg=prompt, timeout=90
            )
            if resp and resp.text and resp.text.strip().lower() != "/cancel":
                try:
                    await resp.delete()
                except Exception:
                    pass
                new_w = [w.strip().lower() for w in resp.text.split(",") if w.strip()]
                _cs.ACTIVE_STOPWORDS = list(dict.fromkeys(_cs.ACTIVE_STOPWORDS + new_w))
                await _cs.update_bot_settings("custom_stopwords", _cs.ACTIVE_STOPWORDS)

        text, markup = await build_interactive_help_section(
            client, "helps_spell", uid, user_mention, query.message
        )
        return await transition_ui_message(client, query.message, text, markup)

    # --- PM AUTO-REPLY ACTIONS ---
    if action in [
        "pm_toggle",
        "pm_on",
        "pm_off",
        "pm_adm_toggle",
        "pm_deftext",
        "pm_remimg",
        "pm_rembtn",
        "pm_settext",
        "pm_setbtn",
    ]:
        if action in ["pm_toggle", "pm_on", "pm_off"]:
            cfg = await get_pm_settings()
            cur = bool(cfg.get("enabled", True))
            new_state = (not cur) if action == "pm_toggle" else (action == "pm_on")
            await save_pm_settings("enabled", new_state)
            await safe_answer(
                query,
                f"💬 PM Auto-Reply: {'ON ✅' if new_state else 'OFF ❌'}",
            )
        elif action == "pm_adm_toggle":
            cfg = await get_pm_settings()
            new_adm = not bool(cfg.get("reply_admins", True))
            await save_pm_settings("reply_admins", new_adm)
            await safe_answer(
                query,
                f"👑 Reply to Admins: {'ON ✅' if new_adm else 'OFF ❌'}",
            )
        elif action == "pm_deftext":
            await save_pm_settings(
                "text",
                "<b>🚫 Don't Message Here, Message Here Only!</b>\n\nI do not respond to direct messages in PM. Please join our official group to request and download movies.",
            )
            await safe_answer(query, "✅ PM Text reset to default!")
        elif action == "pm_remimg":
            await save_pm_settings("image", None)
            await safe_answer(query, "🗑️ PM Image removed!")
        elif action == "pm_rembtn":
            await save_pm_settings("button_text", None)
            await save_pm_settings("button_url", None)
            await safe_answer(query, "🗑️ PM Button removed!")
        elif action == "pm_settext":
            await safe_answer(query)
            prompt = await safe_reply_text(
                query.message,
                "✏️ <b>Send the new PM Auto-Reply Text (HTML supported):</b>",
                reply_markup=get_cancel_input_keyboard("helps_pmautoreply"),
                parse_mode=enums.ParseMode.HTML,
            )
            resp = await wait_cmd_user_input(
                chat_id, uid, prompt_msg=prompt, timeout=90
            )
            if resp and (resp.text or resp.caption):
                raw_txt = resp.text or resp.caption
                if str(raw_txt).strip().lower() != "/cancel":
                    await save_pm_settings(
                        "text", getattr(raw_txt, "html", str(raw_txt))
                    )
                try:
                    await resp.delete()
                except Exception:
                    pass
        elif action == "pm_setbtn":
            await safe_answer(query)
            prompt = await safe_reply_text(
                query.message,
                "🔗 <b>Send the new PM Button in this format:</b>\n"
                "<code>Button Text | https://t.me/your_group | green</code>\n\n"
                "<i>Colors: green, red, blue, normal</i>",
                reply_markup=get_cancel_input_keyboard("helps_pmautoreply"),
                parse_mode=enums.ParseMode.HTML,
            )
            resp = await wait_cmd_user_input(
                chat_id, uid, prompt_msg=prompt, timeout=90
            )
            if resp and resp.text and "|" in resp.text:
                parts = [p.strip() for p in resp.text.split("|")]
                if len(parts) >= 2:
                    b_txt, b_url = parts[0], parts[1]
                    b_col = parts[2].lower() if len(parts) > 2 else "green"
                    if b_col not in ["green", "red", "blue", "normal"]:
                        b_col = "green"
                    await save_pm_settings("button_text", b_txt)
                    await save_pm_settings("button_url", b_url)
                    await save_pm_settings("button_color", b_col)
                try:
                    await resp.delete()
                except Exception:
                    pass

        text, markup = await build_interactive_help_section(
            client, "helps_pmautoreply", uid, user_mention, query.message
        )
        return await transition_ui_message(client, query.message, text, markup)

    # --- FORCE SUBSCRIBE ACTIONS ---
    if action in ["fsub_toggle", "fsub_on", "fsub_off", "fsub_rot", "fsub_list"]:
        try:
            from plugins.fsub import (
                build_fsub_list_ui,
                get_fsub_config,
                update_fsub_config,
            )

            if action in ["fsub_toggle", "fsub_on", "fsub_off"]:
                cfg = await get_fsub_config(force_refresh=True)
                cur = bool(cfg.get("is_enabled", True))
                new_state = (
                    (not cur) if action == "fsub_toggle" else (action == "fsub_on")
                )
                await update_fsub_config("is_enabled", new_state)
                await safe_answer(
                    query,
                    f"📱 ForceSub: {'ON ✅' if new_state else 'OFF ❌'}",
                )
            elif action == "fsub_rot":
                cfg = await get_fsub_config(force_refresh=True)
                new_rot = not bool(cfg.get("rotation_enabled", False))
                await update_fsub_config("rotation_enabled", new_rot)
                await safe_answer(
                    query,
                    f"🔄 Auto-Rotation: {'ON ✅' if new_rot else 'OFF ❌'}",
                )
            elif action == "fsub_list":
                await safe_answer(query)
                f_text, f_markup = await build_fsub_list_ui("All")
                rows = (
                    list(f_markup.inline_keyboard)
                    if f_markup and f_markup.inline_keyboard
                    else []
                )
                rows.append([create_btn("🔙 Back", callback_data="helps_forcesub")])
                return await transition_ui_message(
                    client, query.message, f_text, InlineKeyboardMarkup(rows)
                )
        except Exception as e:
            return await safe_answer(query, f"FSub error: {e}", show_alert=True)

        text, markup = await build_interactive_help_section(
            client, "helps_forcesub", uid, user_mention, query.message
        )
        return await transition_ui_message(client, query.message, text, markup)

    # --- WELCOME ACTIONS ---
    if action in ["welc_toggle", "welc_on", "welc_off", "welc_settxt", "welc_del"]:
        conn_gid = await get_active_connected_group(uid, query.message)
        if not conn_gid:
            return await safe_answer(
                query,
                "⚠️ Connect a group first using /connect <group_id>!",
                show_alert=True,
            )
        from plugins.custom_settings import get_group_welcome, update_group_welcome

        if action in ["welc_toggle", "welc_on", "welc_off"]:
            w_doc = await get_group_welcome(conn_gid)
            cur = bool(w_doc.get("welcome", True))
            new_state = (not cur) if action == "welc_toggle" else (action == "welc_on")
            await update_group_welcome(conn_gid, "welcome", new_state)
            await safe_answer(
                query,
                f"👋 Welcome {'ON ✅' if new_state else 'OFF ❌'} for {conn_gid}!",
            )
        elif action == "welc_del":
            await update_group_welcome(conn_gid, "img", None)
            await update_group_welcome(conn_gid, "text", None)
            await update_group_welcome(conn_gid, "welcome", False)
            await safe_answer(query, "🗑️ Welcome settings reset & disabled!")
        elif action == "welc_settxt":
            await safe_answer(query)
            prompt = await safe_reply_text(
                query.message,
                "👋 <b>Send the new Welcome Message text:</b>\n"
                "Variables: <code>{mention}</code>, <code>{title}</code>, <code>{count}</code>",
                reply_markup=get_cancel_input_keyboard("helps_welcome"),
                parse_mode=enums.ParseMode.HTML,
            )
            resp = await wait_cmd_user_input(
                chat_id, uid, prompt_msg=prompt, timeout=90
            )
            if resp and resp.text and resp.text.strip().lower() != "/cancel":
                await update_group_welcome(conn_gid, "text", resp.text)
                await update_group_welcome(conn_gid, "welcome", True)
                try:
                    await resp.delete()
                except Exception:
                    pass

        text, markup = await build_interactive_help_section(
            client, "helps_welcome", uid, user_mention, query.message
        )
        return await transition_ui_message(client, query.message, text, markup)

    # --- 📋 VIEW GROUP FILTERS (SENT AS EASY-TO-COPY TEXT MESSAGE) ---
    if action == "flt_list":
        conn_gid = await get_active_connected_group(uid, query.message)
        if not conn_gid:
            return await safe_answer(
                query,
                "⚠️ Connect a group first using /connect <group_id>!",
                show_alert=True,
            )
        try:
            from database.filters_mdb import get_filters

            kws = await get_filters(conn_gid)
            if not kws:
                return await safe_answer(
                    query, f"ℹ️ No filters found in group {conn_gid}.", show_alert=True
                )

            await safe_answer(query, f"📋 Sending {len(kws)} filters as text...")

            chat_title = str(conn_gid)
            try:
                c_obj = await client.get_chat(conn_gid)
                if c_obj and c_obj.title:
                    chat_title = html.escape(c_obj.title)
            except Exception:
                pass

            header = (
                f"📋 <b>Group Filters — {chat_title}</b>\n"
                f"🆔 <b>Group ID:</b> <code>{conn_gid}</code>\n"
                f"🔢 <b>Total Filters:</b> <code>{len(kws)}</code>\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
            )
            footer = (
                f"\n━━━━━━━━━━━━━━━━━━━━━\n"
                f"💡 <i>Tap any filter above to copy it!</i>\n"
                f"🗑️ <i>To delete:</i> <code>/delfilter filter_name</code>"
            )

            lines = [
                f"{idx}. <code>{html.escape(str(kw))}</code>"
                for idx, kw in enumerate(kws, start=1)
            ]

            chunks: List[str] = []
            current_chunk = header
            for line in lines:
                if len(current_chunk) + len(line) + len(footer) + 2 > 4000:
                    chunks.append(current_chunk + footer)
                    current_chunk = (
                        f"📋 <b>Group Filters (Cont.) — {chat_title}</b>\n"
                        f"━━━━━━━━━━━━━━━━━━━━━\n{line}\n"
                    )
                else:
                    current_chunk += line + "\n"
            chunks.append(current_chunk + footer)

            for chunk_text in chunks:
                await safe_send_message(
                    client,
                    chat_id=chat_id,
                    text=chunk_text,
                    reply_markup=get_close_keyboard(),
                    parse_mode=enums.ParseMode.HTML,
                )
            return
        except Exception as e:
            return await safe_answer(query, f"Error: {e}", show_alert=True)

    # --- REPAIR MODE 1-CLICK TOGGLE ---
    if action == "repair_toggle":
        info.REPAIR_MODE = not bool(getattr(info, "REPAIR_MODE", False))
        await safe_answer(
            query,
            f"🛠️ Repair Mode: {'ON ✅' if info.REPAIR_MODE else 'OFF ❌'}",
        )
        text, markup = await build_interactive_help_section(
            client, "helps_settings", uid, user_mention, query.message
        )
        return await transition_ui_message(client, query.message, text, markup)


# ============================================================
# 🎛️ INLINE CALLBACK HANDLER
# ============================================================
@Client.on_callback_query(
    filters.regex(
        r"^(close_data|channels_page#.*|alertmessage.*|file.*|checksub.*|pages|start|help|about|helps_.*|stats|rfrsh)$"
    )
)
async def cb_handler(client: Client, query: CallbackQuery):
    uid = (
        query.from_user.id
        if query.from_user
        else getattr(query.message.sender_chat, "id", 0)
    )
    user_mention = query.from_user.mention if query.from_user else "User"
    bot_uname = getattr(temp, "U_NAME", None) or "my_bot"
    b_name = getattr(temp, "B_NAME", None) or "MovieBot"

    cancel_cmd_user_input(query.message.chat.id)
    is_admin = await is_global_admin(uid)

    if (
        getattr(info, "REPAIR_MODE", False)
        and not is_admin
        and query.data != "close_data"
    ):
        return await safe_answer(query, "🛠️ Bot is under maintenance!", show_alert=True)

    # Restrict Help, About, Stats, and Channels callbacks strictly to Bot Admins
    if (
        query.data in ["help", "about", "stats", "rfrsh"]
        or query.data.startswith("helps_")
        or query.data.startswith("channels_page#")
    ):
        if not is_admin:
            return await safe_answer(
                query,
                "❌ Unauthorized: This menu is restricted to Bot Admins only!",
                show_alert=True,
            )

    try:
        if query.data == "close_data":
            await safe_answer(query, "Closed!")
            try:
                await query.message.delete()
            except Exception:
                pass
            if query.message.reply_to_message:
                try:
                    await query.message.reply_to_message.delete()
                except Exception:
                    pass

        elif query.data == "pages":
            await safe_answer(query, "📄 Page Indicator")

        elif query.data.startswith("alertmessage"):
            parts = (
                query.data.split(":", 1)
                if ":" in query.data
                else query.data.split("#", 1)
            )
            alert_txt = parts[1] if len(parts) > 1 else "Alert!"
            await safe_answer(query, alert_txt[:200], show_alert=True)

        elif query.data.startswith("channels_page#"):
            page_num = int(query.data.split("#")[1])
            await safe_answer(query)
            text, reply_markup = await get_channels_page(client, page=page_num)
            await transition_ui_message(client, query.message, text, reply_markup)

        elif query.data == "start":
            await safe_answer(query)
            raw_text = format_script_text(
                getattr(script, "START_TXT", "Hello {mention}!"),
                mention=user_mention,
                uname=bot_uname,
                bname=b_name,
            )
            final_text, final_keyboard = safe_parse_text_and_markup(
                raw_text, await get_start_keyboard(client, uid)
            )
            await transition_ui_message(
                client,
                query.message,
                final_text,
                final_keyboard,
                getattr(info, "START_IMG", None),
            )

        elif query.data == "help":
            await safe_answer(query)
            raw_text = format_script_text(
                getattr(script, "HELP_TXT", "<b>Help Menu</b>"),
                mention=user_mention,
                uname=bot_uname,
                bname=b_name,
            )
            final_text, final_keyboard = safe_parse_text_and_markup(
                raw_text, await get_help_keyboard()
            )
            await transition_ui_message(
                client,
                query.message,
                final_text,
                final_keyboard,
                getattr(info, "HELP_IMG", None),
            )

        elif query.data == "about":
            await safe_answer(query)
            raw_text = format_script_text(
                getattr(script, "ABOUT_TXT", "<b>About {bname}</b>"),
                mention=user_mention,
                uname=bot_uname,
                bname=b_name,
            )
            final_text, final_keyboard = safe_parse_text_and_markup(
                raw_text, await get_about_keyboard()
            )
            await transition_ui_message(
                client,
                query.message,
                final_text,
                final_keyboard,
                getattr(info, "ABOUT_IMG", None),
            )

        elif query.data in ["stats", "rfrsh"]:
            await safe_answer(
                query,
                "Refreshing Database Stats..."
                if query.data == "rfrsh"
                else "Loading Stats...",
            )
            status_text = await build_status_text()
            await transition_ui_message(
                client, query.message, status_text, get_stats_keyboard()
            )

        elif query.data.startswith("helps_"):
            await safe_answer(query)
            text, buttons = await build_interactive_help_section(
                client, query.data, uid, user_mention, query.message
            )
            await transition_ui_message(client, query.message, text, buttons)

        elif query.data.startswith("file") or query.data.startswith("checksub"):
            if (
                query.data.startswith("checksub")
                and (AUTH_CHANNEL or REQ_CHANNEL)
                and not await is_subscribed(client, query)
            ):
                return await safe_answer(
                    query,
                    "⚠️ Please join our channel first, then click Try Again! Team: @KR_PICTURE",
                    show_alert=True,
                )

            try:
                ident, file_id = query.data.split("#", 1)
            except ValueError:
                return await safe_answer(
                    query, "⚠️ Invalid button data!", show_alert=True
                )

            await send_requested_file(
                client=client,
                user_id=query.from_user.id,
                file_id=file_id,
                ident=ident,
                query=query,
            )

    except Exception as e:
        logger.error(f"Callback Handler Error: {e}")


# ============================================================
# 📩 PM AUTO-REPLY ENGINE
# ============================================================
@Client.on_message(
    filters.private & filters.incoming & ~filters.bot & ~filters.service,
    group=1,
)
async def pm_auto_reply(client: Client, message: Message):
    raw_txt = (message.text or message.caption or "").strip()
    if raw_txt.startswith("/"):
        return

    if message.chat.id in _CMD_WAITING_INPUT:
        return

    uid = (
        message.from_user.id
        if message.from_user
        else getattr(message.sender_chat, "id", 0)
    )

    if getattr(info, "REPAIR_MODE", False) and not await is_global_admin(uid):
        return
    if message.from_user and await is_user_banned(uid):
        return

    settings = await get_pm_settings()
    if not settings.get("enabled", True):
        return

    if await is_global_admin(uid):
        if message.forward_from_chat or getattr(message, "forward_origin", None):
            return
        if message.document or message.video or message.audio:
            return
        if not settings.get("reply_admins", True):
            return

    text = settings.get("text", "<b>🚫 Don't Message Here, Message Here Only!</b>")
    pm_img = settings.get("image", getattr(info, "NOT_FOUND_IMG", None))
    btn_text = settings.get("button_text", "💬 Message Here Only")
    btn_url = settings.get("button_url", "https://t.me/Sandalwood_Kannada_Group")
    btn_color_str = str(settings.get("button_color", "red")).lower()

    color_map = {
        "green": BTN_SUCCESS,
        "red": BTN_DANGER,
        "blue": BTN_PRIMARY,
        "normal": None,
    }
    default_markup = (
        InlineKeyboardMarkup(
            [
                [
                    create_btn(
                        btn_text,
                        url=btn_url,
                        style=color_map.get(btn_color_str, None),
                    )
                ]
            ]
        )
        if btn_text and btn_url
        else None
    )

    final_text, final_markup = safe_parse_text_and_markup(text, default_markup)
    final_text = final_text or text

    try:
        if pm_img and str(pm_img).lower() != "none" and len(final_text) <= 1024:
            try:
                await message.reply_photo(
                    photo=pm_img,
                    caption=final_text,
                    reply_markup=final_markup,
                    parse_mode=enums.ParseMode.HTML,
                )
                return
            except Exception:
                pass
        await safe_reply_text(
            message,
            text=final_text,
            reply_markup=final_markup,
            parse_mode=enums.ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception as e:
        logger.error(f"PM Reply Error: {e}")
