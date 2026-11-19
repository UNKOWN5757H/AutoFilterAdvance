import asyncio
import html
import inspect
import re
import time
from logging import ERROR, getLogger
from typing import Any, Dict, List, Optional, Tuple

import requests
from motor.motor_asyncio import AsyncIOMotorClient
from pyrogram import Client, enums, filters
from pyrogram.errors import (
    ChatWriteForbidden,
    Forbidden,
    MessageIdInvalid,
    MessageNotModified,
    PeerIdInvalid,
    UserIsBlocked,
)
from pyrogram.types import InlineKeyboardMarkup, Message

import info
from utils import save_group_settings

try:
    from database.connections_mdb import active_connection as _std_active_connection
except ImportError:
    _std_active_connection = None

try:
    from database.ia_filterdb import get_all_healthy_read_dbs, get_writable_System_db
except ImportError:
    get_all_healthy_read_dbs = None
    get_writable_System_db = None

try:
    from plugins.pm_filter import sanitize_markup_hide_links
except ImportError:
    try:
        from pm_filter import sanitize_markup_hide_links
    except ImportError:

        def sanitize_markup_hide_links(
            markup: Optional[InlineKeyboardMarkup],
        ) -> Optional[InlineKeyboardMarkup]:
            return markup


logger = getLogger(__name__)
logger.setLevel(ERROR)

_DEFAULT_FNF_IMG = getattr(info, "NOT_FOUND_IMG", None)
_DEFAULT_FNF_MSG = getattr(info, "NOT_FOUND_MSG", "<b>🚫 File not found.</b>")

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

_REPLY_PARAMS = set(inspect.signature(Message.reply_text).parameters.keys())
_EDIT_PARAMS = set(inspect.signature(Message.edit_text).parameters.keys())


def _prepare_compat_kwargs(
    kwargs: dict, supported_params: set, disable_preview: Optional[bool] = True
) -> dict:
    clean_kw = dict(kwargs)
    if "reply_markup" in clean_kw and isinstance(
        clean_kw["reply_markup"], InlineKeyboardMarkup
    ):
        clean_kw["reply_markup"] = sanitize_markup_hide_links(clean_kw["reply_markup"])

    explicit_disable = clean_kw.pop("disable_web_page_preview", disable_preview)
    if explicit_disable is not None:
        if (
            "link_preview_options" in supported_params
            and LinkPreviewOptions is not None
        ):
            try:
                clean_kw["link_preview_options"] = LinkPreviewOptions(
                    is_disabled=bool(explicit_disable)
                )
            except Exception:
                pass
        elif "disable_web_page_preview" in supported_params:
            clean_kw["disable_web_page_preview"] = bool(explicit_disable)

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
) -> Optional[Message]:
    if not message:
        return None
    compat_kw = _prepare_compat_kwargs(
        kwargs, _REPLY_PARAMS, disable_preview=disable_web_page_preview
    )
    try:
        return await message.reply_text(text, **compat_kw)
    except TypeError:
        for k in (
            "disable_web_page_preview",
            "link_preview_options",
            "reply_parameters",
            "reply_to_message_id",
        ):
            compat_kw.pop(k, None)
        return await message.reply_text(text, **compat_kw)
    except (ChatWriteForbidden, Forbidden, UserIsBlocked, PeerIdInvalid):
        return None


async def safe_edit_text(
    message: Message, text: str, disable_web_page_preview: bool = True, **kwargs
) -> Optional[Message]:
    if not message:
        return None
    compat_kw = _prepare_compat_kwargs(
        kwargs, _EDIT_PARAMS, disable_preview=disable_web_page_preview
    )
    try:
        return await message.edit_text(text, **compat_kw)
    except (MessageNotModified, MessageIdInvalid, ChatWriteForbidden, Forbidden):
        return None
    except TypeError:
        compat_kw.pop("disable_web_page_preview", None)
        compat_kw.pop("link_preview_options", None)
        try:
            return await message.edit_text(text, **compat_kw)
        except Exception:
            return None


# ============================================================
# ⚙️ QUOTA-SAFE MULTI-DB ISOLATION & IN-MEMORY CACHE
# ============================================================
b_settings_db = g_welcome_db = _active_db = _std_conn_db = _custom_cap_db = None
try:
    _DB_CLIENT = AsyncIOMotorClient(
        info.DATABASE_URI,
        serverSelectionTimeoutMS=4000,
        connectTimeoutMS=4000,
        socketTimeoutMS=8000,
    )
    _BOT_DB = _DB_CLIENT[info.DATABASE_NAME]
    b_settings_db = _BOT_DB["global_bot_settings"]
    g_welcome_db = _BOT_DB["group_welcome_settings"]
    _active_db = _BOT_DB["active_connections"]
    _std_conn_db = _BOT_DB["CONNECTION"]
    _custom_cap_db = _BOT_DB["custom_captions"]
except Exception as e:
    logger.error(f"Failed to init custom settings DB: {e}")

_BOT_SETTINGS_CACHE: Optional[Dict[str, Any]] = None
_BOT_SETTINGS_CACHE_TS: float = 0.0
_WELCOME_CACHE: Dict[int, Tuple[float, Dict[str, Any]]] = {}

_INFO_ATTR_MAP = {
    "fsub_img": "FSUB_IMG",
    "fsub_msg": "FSUB_MSG",
    "auto_img": "AUTO_IMG",
    "not_found_img": "NOT_FOUND_IMG",
    "not_found_text": "NOT_FOUND_MSG",
    "info_msg": "INFO_MSG",
    "info_img": "INFO_IMG",
    "del_msg": "DEL_MSG",
    "del_img": "DEL_IMG",
}


def _get_candidate_cols(col_name: str, fallback_col: Any) -> List[Any]:
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


async def get_bot_settings(force_refresh: bool = False) -> Dict[str, Any]:
    global _BOT_SETTINGS_CACHE, _BOT_SETTINGS_CACHE_TS
    now = time.time()
    if (
        not force_refresh
        and _BOT_SETTINGS_CACHE is not None
        and (now - _BOT_SETTINGS_CACHE_TS) < 60
    ):
        return _BOT_SETTINGS_CACHE

    best_doc = None
    best_ts = -1.0
    for col in _get_candidate_cols("global_bot_settings", b_settings_db):
        try:
            doc = await asyncio.wait_for(
                col.find_one({"_id": "bot_config"}), timeout=2.5
            )
            if doc:
                doc_ts = float(doc.get("updated_at", 0.0) or 0.0)
                if best_doc is None or doc_ts >= best_ts:
                    best_doc = doc
                    best_ts = doc_ts
        except Exception:
            continue

    _BOT_SETTINGS_CACHE = best_doc or _BOT_SETTINGS_CACHE or {}
    _BOT_SETTINGS_CACHE_TS = now
    return _BOT_SETTINGS_CACHE


async def update_bot_settings(key: str, value: Any):
    global _BOT_SETTINGS_CACHE, _BOT_SETTINGS_CACHE_TS
    now = time.time()
    if _BOT_SETTINGS_CACHE is None:
        _BOT_SETTINGS_CACHE = {}
    _BOT_SETTINGS_CACHE[key] = value
    _BOT_SETTINGS_CACHE["updated_at"] = now
    _BOT_SETTINGS_CACHE_TS = now

    for col in _get_candidate_cols("global_bot_settings", b_settings_db):
        try:
            await asyncio.wait_for(
                col.update_one(
                    {"_id": "bot_config"},
                    {"$set": {key: value, "updated_at": now}},
                    upsert=True,
                ),
                timeout=2.5,
            )
        except Exception:
            continue

    info_attr = _INFO_ATTR_MAP.get(key)
    if info_attr:
        setattr(info, info_attr, value)
        for col in _get_candidate_cols("custom_captions", _custom_cap_db):
            try:
                await asyncio.wait_for(
                    col.update_one(
                        {"_id": "settings"}, {"$set": {info_attr: value}}, upsert=True
                    ),
                    timeout=2.5,
                )
            except Exception:
                continue


async def get_group_welcome(chat_id: int) -> Dict[str, Any]:
    cid = int(chat_id)
    now = time.time()
    cached = _WELCOME_CACHE.get(cid)
    if cached and (now - cached[0]) < 60:
        return cached[1]

    for col in _get_candidate_cols("group_welcome_settings", g_welcome_db):
        try:
            doc = await asyncio.wait_for(col.find_one({"_id": cid}), timeout=2.0)
            if doc:
                _WELCOME_CACHE[cid] = (now, doc)
                return doc
        except Exception:
            continue
    return {}


async def update_group_welcome(chat_id: int, key: str, value: Any):
    cid = int(chat_id)
    for col in _get_candidate_cols("group_welcome_settings", g_welcome_db):
        try:
            await asyncio.wait_for(
                col.update_one({"_id": cid}, {"$set": {key: value}}, upsert=True),
                timeout=2.5,
            )
        except Exception:
            continue

    cached = _WELCOME_CACHE.get(cid)
    cur_doc = dict(cached[1]) if cached else {}
    cur_doc[key] = value
    _WELCOME_CACHE[cid] = (time.time(), cur_doc)

    try:
        if key == "welcome":
            await save_group_settings(cid, "welcome", bool(value))
        elif key == "text":
            await save_group_settings(cid, "welcome_text", value)
        elif key == "img":
            await save_group_settings(cid, "welcome_img", value)
    except Exception:
        pass


# ============================================================
# 👑 SMART AUTHORIZATION & CONNECTION ENGINE
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


def _get_msg_uid(message: Message) -> int:
    return (
        message.from_user.id
        if message.from_user
        else getattr(message.sender_chat, "id", 0)
    )


async def is_global_admin(user_id: int) -> bool:
    return bool(user_id and int(user_id) in get_admin_list())


async def _require_global_admin(message: Message) -> bool:
    if await is_global_admin(_get_msg_uid(message)):
        return True
    await safe_reply_text(
        message,
        "❌ <b>Unauthorized:</b> You must be a Global Bot Admin.",
        parse_mode=enums.ParseMode.HTML,
    )
    return False


async def is_group_admin(client: Client, user_id: int, chat_id: int) -> bool:
    if await is_global_admin(user_id):
        return True
    if not user_id or not chat_id:
        return False
    try:
        member = await client.get_chat_member(int(chat_id), int(user_id))
        return member.status in [
            enums.ChatMemberStatus.ADMINISTRATOR,
            enums.ChatMemberStatus.OWNER,
        ]
    except Exception:
        return False


async def get_active_group(user_id: int) -> Optional[int]:
    if callable(_std_active_connection):
        try:
            conn = await _std_active_connection(str(user_id))
            if conn:
                return int(conn)
        except Exception:
            pass

    for col, query_doc, field_keys in (
        (
            _active_db,
            {
                "$or": [
                    {"user_id": str(user_id)},
                    {"user_id": int(user_id)},
                    {"_id": str(user_id)},
                    {"_id": int(user_id)},
                ]
            },
            ("group_id", "active_group", "chat_id"),
        ),
        (
            _std_conn_db,
            {"$or": [{"_id": str(user_id)}, {"_id": int(user_id)}]},
            ("active_group",),
        ),
    ):
        if col is not None:
            try:
                doc = await asyncio.wait_for(col.find_one(query_doc), timeout=2.0)
                if doc:
                    for fk in field_keys:
                        if doc.get(fk):
                            return int(doc[fk])
            except Exception:
                continue

    return None


async def get_target_chat(client: Client, message: Message) -> Optional[int]:
    if message.command and len(message.command) > 1:
        first_arg = message.command[1].strip()
        if first_arg.startswith("-100") and first_arg.lstrip("-").isdigit():
            return int(first_arg)

    if message.chat.type == enums.ChatType.PRIVATE:
        if not message.from_user:
            return None
        return await get_active_group(message.from_user.id)
    return message.chat.id


async def _resolve_admin_target_chat(client: Client, message: Message) -> Optional[int]:
    target_chat_id = await get_target_chat(client, message)
    if not target_chat_id:
        await safe_reply_text(
            message,
            "⚠️ <b>No active connection!</b>\nPlease run <code>/connect &lt;group_id&gt;</code> first or use this command inside a group.",
            parse_mode=enums.ParseMode.HTML,
        )
        return None
    if not await is_group_admin(client, _get_msg_uid(message), target_chat_id):
        await safe_reply_text(
            message,
            f"❌ <b>Unauthorized:</b> You must be an Admin of the target group (<code>{target_chat_id}</code>).",
            parse_mode=enums.ParseMode.HTML,
        )
        return None
    return target_chat_id


def extract_text_payload(message: Message) -> Optional[str]:
    if (
        message.reply_to_message
        and len(getattr(message, "command", [])) == 1
        and (message.reply_to_message.text or message.reply_to_message.caption)
    ):
        raw = message.reply_to_message.text or message.reply_to_message.caption
        return getattr(raw, "html", str(raw)).strip()

    if message.text and len(getattr(message, "command", [])) > 1:
        raw_html = getattr(message.text, "html", str(message.text))
        cleaned = re.sub(r"^/\w+(?:@[a-zA-Z0-9_]+)?\s+", "", raw_html, count=1)
        cleaned = re.sub(r"^-100\d+\s*", "", cleaned, count=1).strip()
        return cleaned or None
    return None


def _invalidate_pm_filter_search_cache():
    try:
        import plugins.pm_filter as _pmf

        _pmf.GLOBAL_SEARCH_CACHE._data.clear()
        _pmf.POOL_SEARCH_CACHE._data.clear()
        _pmf.FUZZY_TITLES_CACHE._data.clear()
    except Exception:
        pass


# ============================================================
# 🛑 SMART STOPWORDS ENGINE (GLOBAL SETTING)
# ============================================================
DEFAULT_STOPWORDS = [
    "send",
    "snd",
    "give",
    "gib",
    "pls",
    "plz",
    "please",
    "need",
    "want",
    "upload",
    "uplod",
    "drop",
    "share",
    "find",
    "search",
    "provide",
    "post",
    "movie",
    "movies",
    "film",
    "films",
    "cinema",
    "cinemas",
    "full",
    "fullmovie",
    "download",
    "downlod",
    "link",
    "links",
    "file",
    "files",
    "print",
    "audio",
    "ott",
    "hd",
    "hq",
    "bluray",
    "rip",
    "watch",
    "online",
    "admin",
    "beku",
    "bekithu",
    "bekittu",
    "bekagide",
    "kodi",
    "kodro",
    "kalsi",
    "kalsro",
    "kalisi",
    "haki",
    "haku",
    "hakro",
    "ideya",
    "irboda",
    "bidi",
    "madu",
    "yaradru",
    "kannadadalli",
    "sandalwood",
    "kr_picture",
    "kannada_filmy_group",
    "telegram",
    "dubbed",
]

ACTIVE_STOPWORDS = DEFAULT_STOPWORDS.copy()
_stopwords_loaded = False


def get_stopwords() -> List[str]:
    return ACTIVE_STOPWORDS


@Client.on_message(filters.all, group=-999)
async def load_stopwords_on_boot(client: Client, message: Message):
    global _stopwords_loaded, ACTIVE_STOPWORDS
    if _stopwords_loaded:
        return
    _stopwords_loaded = True
    try:
        settings = await get_bot_settings(force_refresh=True)
        custom_stops = settings.get("custom_stopwords")
        if custom_stops is not None:
            ACTIVE_STOPWORDS = list(custom_stops)
        for db_key, info_attr in _INFO_ATTR_MAP.items():
            if db_key in settings and settings[db_key] is not None:
                setattr(info, info_attr, settings[db_key])
    except Exception as e:
        logger.error(f"Boot settings load error: {e}")


@Client.on_message(filters.command("addstopwords") & filters.incoming, group=-2)
async def add_stopwords(client: Client, message: Message):
    global ACTIVE_STOPWORDS
    if not await _require_global_admin(message):
        return

    if len(message.command) < 2:
        return await safe_reply_text(
            message,
            "⚠️ <b>Usage:</b> <code>/addstopwords word1, word2</code>",
            parse_mode=enums.ParseMode.HTML,
        )

    raw_input = message.text.split(None, 1)[1]
    new_words = [w.strip().lower() for w in re.split(r"[,\n]+", raw_input) if w.strip()]
    ACTIVE_STOPWORDS = sorted(set(ACTIVE_STOPWORDS + new_words))
    await update_bot_settings("custom_stopwords", ACTIVE_STOPWORDS)
    _invalidate_pm_filter_search_cache()
    await safe_reply_text(
        message,
        f"✅ <b>Added {len(new_words)} stopwords globally.</b>\n"
        f"📊 <b>Total Active:</b> <code>{len(ACTIVE_STOPWORDS)}</code>",
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(filters.command("stopwords") & filters.incoming, group=-2)
async def show_stopwords(client: Client, message: Message):
    if not await _require_global_admin(message):
        return

    if not ACTIVE_STOPWORDS:
        return await safe_reply_text(
            message,
            "ℹ️ <b>No stopwords are currently active.</b>",
            parse_mode=enums.ParseMode.HTML,
        )
    escaped_words = html.escape(", ".join(ACTIVE_STOPWORDS))
    await safe_reply_text(
        message,
        f"🛑 <b>Current Active Stopwords:</b>\n\n"
        f"<code>{escaped_words}</code>\n\n"
        f"<b>Total:</b> <code>{len(ACTIVE_STOPWORDS)}</code>",
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(filters.command("remstopwords") & filters.incoming, group=-2)
async def rem_stopwords(client: Client, message: Message):
    global ACTIVE_STOPWORDS
    if not await _require_global_admin(message):
        return

    if len(message.command) < 2:
        return await safe_reply_text(
            message,
            "⚠️ <b>Usage:</b> <code>/remstopwords word1, word2</code>",
            parse_mode=enums.ParseMode.HTML,
        )

    raw_input = message.text.split(None, 1)[1]
    words_to_remove = {
        w.strip().lower() for w in re.split(r"[,\n]+", raw_input) if w.strip()
    }
    if not ACTIVE_STOPWORDS:
        return await safe_reply_text(
            message,
            "ℹ️ <b>There are no stopwords to remove.</b>",
            parse_mode=enums.ParseMode.HTML,
        )

    original_count = len(ACTIVE_STOPWORDS)
    ACTIVE_STOPWORDS = [w for w in ACTIVE_STOPWORDS if w not in words_to_remove]
    await update_bot_settings("custom_stopwords", ACTIVE_STOPWORDS)
    _invalidate_pm_filter_search_cache()
    await safe_reply_text(
        message,
        f"✅ <b>Removed {original_count - len(ACTIVE_STOPWORDS)} stopwords.</b>\n"
        f"📊 <b>Total Left:</b> <code>{len(ACTIVE_STOPWORDS)}</code>",
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(filters.command("remallstopwords") & filters.incoming, group=-2)
async def rem_all_stopwords(client: Client, message: Message):
    global ACTIVE_STOPWORDS
    if not await _require_global_admin(message):
        return

    ACTIVE_STOPWORDS = []
    await update_bot_settings("custom_stopwords", [])
    _invalidate_pm_filter_search_cache()
    await safe_reply_text(
        message,
        "🗑️ <b>All stopwords have been completely removed globally.</b>",
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(filters.command("defaultstopwords") & filters.incoming, group=-2)
async def default_stopwords(client: Client, message: Message):
    global ACTIVE_STOPWORDS
    if not await _require_global_admin(message):
        return

    ACTIVE_STOPWORDS = DEFAULT_STOPWORDS.copy()
    await update_bot_settings("custom_stopwords", ACTIVE_STOPWORDS)
    _invalidate_pm_filter_search_cache()
    await safe_reply_text(
        message,
        "✅ <b>Stopwords have been successfully reset to default.</b>",
        parse_mode=enums.ParseMode.HTML,
    )


# ============================================================
# ☁️ RELIABLE CLOUD UPLOAD ENGINE
# ============================================================
def _upload_sync(file_bytes: bytes) -> Optional[str]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
    }
    for url, files_dict, data_dict in (
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
            "https://litterbox.catbox.moe/resources/internals/api.php",
            {"fileToUpload": ("img.jpg", file_bytes, "image/jpeg")},
            {"reqtype": "fileupload", "time": "72h"},
        ),
        ("https://envs.sh", {"file": ("img.jpg", file_bytes, "image/jpeg")}, None),
        ("https://0x0.st", {"file": ("img.jpg", file_bytes, "image/jpeg")}, None),
    ):
        try:
            res = requests.post(
                url, data=data_dict, files=files_dict, headers=headers, timeout=8
            )
            if res.status_code in (200, 201):
                if "freeimage.host" in url:
                    u = res.json().get("image", {}).get("url")
                    if u and u.startswith("http"):
                        return u
                elif res.text.strip().startswith("http"):
                    return res.text.strip()
        except Exception:
            continue
    return None


async def upload_image_safely(client: Client, message: Message):
    try:
        file_io = await client.download_media(message, in_memory=True)
        if not file_io:
            return None, "❌ Failed to download the image."
        url = await asyncio.to_thread(_upload_sync, file_io.getvalue())
        if not url:
            return None, "❌ All cloud uploaders failed."
        return url, None
    except Exception as e:
        return None, f"❌ Internal Error: {e}"


# ============================================================
# 🖼️ GLOBAL IMAGE & TEXT SETTINGS (GLOBAL ADMINS ONLY)
# ============================================================
async def process_global_image_setting(
    client: Client, message: Message, setting_key: str, success_msg: str
):
    if not await _require_global_admin(message):
        return

    target_msg = (
        message.reply_to_message
        if (message.reply_to_message and message.reply_to_message.photo)
        else (message if message.photo else None)
    )

    if target_msg is None and len(message.command) > 1:
        arg = message.text.split(None, 1)[1].strip()
        if arg.lower() in ("off", "none", "reset", "clear"):
            await update_bot_settings(setting_key, None)
            return await safe_reply_text(
                message,
                f"🗑️ <b>{success_msg.replace('updated!', 'removed!')}</b>",
                parse_mode=enums.ParseMode.HTML,
            )
        if arg.startswith(("http://", "https://")) or len(arg) > 20:
            await update_bot_settings(setting_key, arg)
            return await safe_reply_text(
                message, f"✅ <b>{success_msg}</b>", parse_mode=enums.ParseMode.HTML
            )

    if not target_msg or not target_msg.photo:
        return await safe_reply_text(
            message,
            f"⚠️ <b>Usage:</b> Reply to a photo with <code>/{message.command[0]}</code>",
            parse_mode=enums.ParseMode.HTML,
        )

    status = await safe_reply_text(
        message, "⏳ <b>Uploading to Cloud...</b>", parse_mode=enums.ParseMode.HTML
    )
    url, _ = await upload_image_safely(client, target_msg)

    if url:
        await update_bot_settings(setting_key, url)
        if status:
            await safe_edit_text(
                status,
                f"✅ <b>{success_msg}</b>\n<i>(Saved permanently to cloud)</i>",
                parse_mode=enums.ParseMode.HTML,
            )
    else:
        await update_bot_settings(setting_key, target_msg.photo.file_id)
        if status:
            await safe_edit_text(
                status,
                f"⚠️ Cloud blocked. <b>{success_msg}</b>\n<i>(Saved as Telegram File_ID)</i>",
                parse_mode=enums.ParseMode.HTML,
            )


@Client.on_message(filters.command("setfsubimg") & filters.incoming, group=-2)
async def set_fsub_img(client: Client, message: Message):
    await process_global_image_setting(
        client, message, "fsub_img", "Force Subscribe Image updated!"
    )


@Client.on_message(filters.command("setautoimg") & filters.incoming, group=-2)
async def set_auto_img(client: Client, message: Message):
    await process_global_image_setting(
        client, message, "auto_img", "Default Auto-Filter Image updated!"
    )


@Client.on_message(filters.command("setfilenotfoundimg") & filters.incoming, group=-2)
async def set_fnf_img(client: Client, message: Message):
    await process_global_image_setting(
        client, message, "not_found_img", "File Not Found Image updated!"
    )


@Client.on_message(filters.command("remautoimg") & filters.incoming, group=-2)
async def rem_auto_img(client: Client, message: Message):
    if not await _require_global_admin(message):
        return
    await update_bot_settings("auto_img", None)
    await safe_reply_text(
        message,
        "🗑️ <b>Default Auto-Filter Image removed.</b>",
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(filters.command("remfilenotfoundimg") & filters.incoming, group=-2)
async def rem_fnf_img(client: Client, message: Message):
    if not await _require_global_admin(message):
        return
    await update_bot_settings("not_found_img", None)
    await safe_reply_text(
        message,
        "🗑️ <b>File Not Found Image removed.</b>",
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(
    filters.command("defaultfilenotfoundimg") & filters.incoming, group=-2
)
async def default_fnf_img(client: Client, message: Message):
    if not await _require_global_admin(message):
        return
    await update_bot_settings("not_found_img", _DEFAULT_FNF_IMG)
    await safe_reply_text(
        message,
        "✅ <b>File Not Found Image reset to default.</b>",
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(filters.command("setnotfoundtext") & filters.incoming, group=-2)
async def set_fnf_text(client: Client, message: Message):
    if not await _require_global_admin(message):
        return
    text_val = extract_text_payload(message)
    if not text_val:
        return await safe_reply_text(
            message,
            "⚠️ <b>Usage:</b> <code>/setnotfoundtext &lt;your text&gt;</code> or reply to a message.",
            parse_mode=enums.ParseMode.HTML,
        )
    await update_bot_settings("not_found_text", text_val)
    await safe_reply_text(
        message,
        "✅ <b>File Not Found Text updated!</b>",
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(filters.command("remnotfoundtext") & filters.incoming, group=-2)
async def rem_fnf_text(client: Client, message: Message):
    if not await _require_global_admin(message):
        return
    await update_bot_settings("not_found_text", None)
    await safe_reply_text(
        message,
        "🗑️ <b>File Not Found Text removed.</b>",
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(filters.command("defaultnotfoundtext") & filters.incoming, group=-2)
async def def_fnf_text(client: Client, message: Message):
    if not await _require_global_admin(message):
        return
    await update_bot_settings("not_found_text", _DEFAULT_FNF_MSG)
    await safe_reply_text(
        message,
        "✅ <b>File Not Found Text reset to default.</b>",
        parse_mode=enums.ParseMode.HTML,
    )


# ============================================================
# 🪄 SPELL CHECK & 👋 WELCOME SETTINGS (PM & GROUP ROUTING)
# ============================================================
@Client.on_message(filters.command("enablespellcheck") & filters.incoming, group=-2)
async def enable_spell_check(client: Client, message: Message):
    target_chat_id = await _resolve_admin_target_chat(client, message)
    if not target_chat_id:
        return
    await save_group_settings(target_chat_id, "spell_check", True)
    await safe_reply_text(
        message,
        f"✅ <b>Spell Check Enabled for chat:</b> <code>{target_chat_id}</code>",
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(filters.command("disablespellcheck") & filters.incoming, group=-2)
async def disable_spell_check(client: Client, message: Message):
    target_chat_id = await _resolve_admin_target_chat(client, message)
    if not target_chat_id:
        return
    await save_group_settings(target_chat_id, "spell_check", False)
    await safe_reply_text(
        message,
        f"🚫 <b>Spell Check Disabled for chat:</b> <code>{target_chat_id}</code>",
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(filters.command("enablewelcome") & filters.incoming, group=-2)
async def enable_welc(client: Client, message: Message):
    target_chat_id = await _resolve_admin_target_chat(client, message)
    if not target_chat_id:
        return
    await update_group_welcome(target_chat_id, "welcome", True)
    await safe_reply_text(
        message,
        f"✅ <b>Welcome Messages Enabled for <code>{target_chat_id}</code>.</b>",
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(filters.command("disablewelcome") & filters.incoming, group=-2)
async def disable_welc(client: Client, message: Message):
    target_chat_id = await _resolve_admin_target_chat(client, message)
    if not target_chat_id:
        return
    await update_group_welcome(target_chat_id, "welcome", False)
    await safe_reply_text(
        message,
        f"🚫 <b>Welcome Messages Disabled for <code>{target_chat_id}</code>.</b>",
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(filters.command("setwelcometxt") & filters.incoming, group=-2)
async def set_welc_txt(client: Client, message: Message):
    target_chat_id = await _resolve_admin_target_chat(client, message)
    if not target_chat_id:
        return
    text_val = extract_text_payload(message)
    if not text_val:
        return await safe_reply_text(
            message,
            "⚠️ <b>Usage:</b> <code>/setwelcometxt &lt;Your text&gt;</code> or reply to a text message.\n\n"
            "💡 <b>Variables:</b> <code>{mention}</code>, <code>{title}</code>, <code>{count}</code>",
            parse_mode=enums.ParseMode.HTML,
        )
    await update_group_welcome(target_chat_id, "text", text_val)
    await update_group_welcome(target_chat_id, "welcome", True)
    await safe_reply_text(
        message,
        f"✅ <b>Welcome Text updated for <code>{target_chat_id}</code>!</b>",
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(filters.command("setwelcomeimg") & filters.incoming, group=-2)
async def set_welc_img(client: Client, message: Message):
    target_chat_id = await _resolve_admin_target_chat(client, message)
    if not target_chat_id:
        return

    target_msg = (
        message.reply_to_message
        if (message.reply_to_message and message.reply_to_message.photo)
        else (message if message.photo else None)
    )
    if not target_msg or not target_msg.photo:
        return await safe_reply_text(
            message,
            "⚠️ <b>Usage:</b> Reply to a photo with <code>/setwelcomeimg</code>",
            parse_mode=enums.ParseMode.HTML,
        )

    status = await safe_reply_text(
        message, "⏳ <b>Uploading to Cloud...</b>", parse_mode=enums.ParseMode.HTML
    )
    url, _ = await upload_image_safely(client, target_msg)
    if url:
        await update_group_welcome(target_chat_id, "img", url)
        if status:
            await safe_edit_text(
                status,
                f"✅ <b>Welcome Image updated for <code>{target_chat_id}</code> (Cloud Saved)!</b>",
                parse_mode=enums.ParseMode.HTML,
            )
    else:
        await update_group_welcome(target_chat_id, "img", target_msg.photo.file_id)
        if status:
            await safe_edit_text(
                status,
                f"⚠️ Cloud blocked. <b>Welcome Image updated for <code>{target_chat_id}</code> (File ID Saved)!</b>",
                parse_mode=enums.ParseMode.HTML,
            )


@Client.on_message(filters.command("setwelcome") & filters.incoming, group=-2)
async def set_welcome_both(client: Client, message: Message):
    target_chat_id = await _resolve_admin_target_chat(client, message)
    if not target_chat_id:
        return

    target_msg = (
        message.reply_to_message
        if (message.reply_to_message and message.reply_to_message.photo)
        else (message if message.photo else None)
    )
    if not target_msg or not target_msg.photo:
        return await safe_reply_text(
            message,
            "⚠️ <b>Usage:</b> Reply to a photo containing a caption with <code>/setwelcome</code>",
            parse_mode=enums.ParseMode.HTML,
        )

    raw_cap = target_msg.caption
    txt = getattr(raw_cap, "html", str(raw_cap)) if raw_cap else None
    if txt and txt.startswith("/setwelcome"):
        txt = re.sub(r"^/setwelcome(?:@[a-zA-Z0-9_]+)?\s*", "", txt, count=1).strip()

    status = await safe_reply_text(
        message, "⏳ <b>Processing...</b>", parse_mode=enums.ParseMode.HTML
    )
    url, _ = await upload_image_safely(client, target_msg)
    await update_group_welcome(target_chat_id, "img", url or target_msg.photo.file_id)
    if txt:
        await update_group_welcome(target_chat_id, "text", txt)
    await update_group_welcome(target_chat_id, "welcome", True)

    if status:
        await safe_edit_text(
            status,
            f"✅ <b>Welcome Image & Text set for <code>{target_chat_id}</code>!</b>",
            parse_mode=enums.ParseMode.HTML,
        )


@Client.on_message(filters.command("delwelcome") & filters.incoming, group=-2)
async def del_welcome(client: Client, message: Message):
    target_chat_id = await _resolve_admin_target_chat(client, message)
    if not target_chat_id:
        return
    await update_group_welcome(target_chat_id, "img", None)
    await update_group_welcome(target_chat_id, "text", None)
    await update_group_welcome(target_chat_id, "welcome", False)
    await safe_reply_text(
        message,
        f"🗑️ <b>Welcome settings deleted and disabled for <code>{target_chat_id}</code>.</b>",
        parse_mode=enums.ParseMode.HTML,
    )
