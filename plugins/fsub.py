import asyncio
import hashlib
import html
import inspect
import re
import time
from collections import OrderedDict
from logging import ERROR, getLogger
from typing import Any, Dict, List, Optional, Tuple

from motor.motor_asyncio import AsyncIOMotorClient
from pyrogram import Client, StopPropagation, enums, filters
from pyrogram.errors import (
    ChatAdminRequired,
    ChatWriteForbidden,
    FloodWait,
    Forbidden,
    MessageEmpty,
    MessageIdInvalid,
    MessageNotModified,
    PeerIdInvalid,
    QueryIdInvalid,
    UserIsBlocked,
    UserNotParticipant,
)
from pyrogram.types import (
    CallbackQuery,
    ChatJoinRequest,
    ChatMemberUpdated,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

import info

logger = getLogger(__name__)
logger.setLevel(ERROR)

_ACTIVE_WATCHER_TASKS: Dict[int, asyncio.Task] = {}
DEFAULT_FSUB_CAPTION = "<b>Please join below channel to get file!</b>"

# ============================================================
# 🛡️ SAFE OPTIONAL IMPORTS (MULTI-DB & HIDDEN-LINK REGISTRY)
# ============================================================
try:
    from database.ia_filterdb import get_file_details
except Exception:

    async def get_file_details(file_id: str):
        return []


try:
    from database.ia_filterdb import get_all_healthy_read_dbs, get_writable_System_db
except Exception:
    get_all_healthy_read_dbs = None
    get_writable_System_db = None

try:
    from utils import parse_text_and_markup
except Exception:

    def parse_text_and_markup(text: str, default_markup=None):
        return text, default_markup


try:
    from plugins.custom_settings import get_bot_settings
except Exception:

    async def get_bot_settings():
        return {}


try:
    from plugins.pm_filter import register_hidden_link, sanitize_markup_hide_links
except ImportError:
    try:
        from pm_filter import register_hidden_link, sanitize_markup_hide_links
    except ImportError:
        _LOCAL_HIDDEN_LINKS: Dict[str, str] = {}

        def register_hidden_link(url: str) -> str:
            clean_u = str(url or "").strip()
            if clean_u and not clean_u.startswith(("http://", "https://", "tg://")):
                clean_u = "https://" + clean_u.lstrip("/")
            token = hashlib.md5(clean_u.encode("utf-8")).hexdigest()[:12]
            if len(_LOCAL_HIDDEN_LINKS) >= 15000:
                _LOCAL_HIDDEN_LINKS.pop(next(iter(_LOCAL_HIDDEN_LINKS)), None)
            _LOCAL_HIDDEN_LINKS[token] = clean_u
            return token

        def sanitize_markup_hide_links(
            markup: Optional[InlineKeyboardMarkup],
        ) -> Optional[InlineKeyboardMarkup]:
            if not markup or not getattr(markup, "inline_keyboard", None):
                return markup
            rows = []
            for row in markup.inline_keyboard:
                new_row = []
                for b in row:
                    st = getattr(b, "style", None)
                    if getattr(b, "url", None):
                        new_row.append(create_btn(b.text, url=b.url, style=st))
                    else:
                        new_row.append(
                            create_btn(
                                b.text,
                                callback_data=getattr(b, "callback_data", "noop"),
                                style=st,
                            )
                        )
                if new_row:
                    rows.append(new_row)
            return InlineKeyboardMarkup(rows) if rows else None


# ============================================================
# 🛡️ PYROGRAM v2.2.26 COMPATIBILITY & HIDDEN-LINK BUTTONS
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
    pass


def _clean_button_label(raw_label: str) -> str:
    lbl = re.sub(r"<[^>]+>", "", str(raw_label or "")).strip()
    lbl = re.sub(r"(?i)https?://\S+|t\.me/\S+|www\.\S+", "", lbl).strip(" -|:")
    return lbl or "Open"


def create_btn(
    text: str,
    url: Optional[str] = None,
    callback_data: Optional[str] = None,
    style: Any = None,
) -> InlineKeyboardButton:
    """Creates an InlineKeyboardButton with ZERO visible links inside the button."""
    kwargs: Dict[str, Any] = {"text": _clean_button_label(text)}
    if callback_data:
        kwargs["callback_data"] = str(callback_data)[:64]
    elif url:
        kwargs["callback_data"] = f"olink#{register_hidden_link(url)}"
    else:
        kwargs["callback_data"] = "noop"

    if _SUPPORTS_BTN_STYLE and style is not None:
        kwargs["style"] = style
    try:
        return InlineKeyboardButton(**kwargs)
    except Exception:
        kwargs.pop("style", None)
        return InlineKeyboardButton(**kwargs)


def _ensure_non_empty_text(text: Any, fallback: str = DEFAULT_FSUB_CAPTION) -> str:
    if text is None:
        return fallback
    s = str(text).strip()
    if not s or s.lower() in ("none", "null", "false"):
        return fallback
    return s


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
        if "link_preview_options" in supported_params and LinkPreviewOptions is not None:
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
):
    if not message:
        return None
    safe_txt = _ensure_non_empty_text(text)
    compat_kw = _prepare_compat_kwargs(
        kwargs, _REPLY_PARAMS, disable_preview=disable_web_page_preview
    )
    try:
        return await message.reply_text(safe_txt, **compat_kw)
    except MessageEmpty:
        return await message.reply_text(DEFAULT_FSUB_CAPTION, **compat_kw)
    except TypeError:
        for k in (
            "disable_web_page_preview",
            "link_preview_options",
            "reply_parameters",
            "reply_to_message_id",
        ):
            compat_kw.pop(k, None)
        return await message.reply_text(safe_txt, **compat_kw)
    except (ChatWriteForbidden, Forbidden, UserIsBlocked, PeerIdInvalid):
        return None
    except Exception:
        compat_kw.pop("parse_mode", None)
        try:
            return await message.reply_text(safe_txt, **compat_kw)
        except Exception:
            return None


async def safe_edit_text(
    message: Message, text: str, disable_web_page_preview: bool = True, **kwargs
):
    if not message:
        return None
    safe_txt = _ensure_non_empty_text(text)
    compat_kw = _prepare_compat_kwargs(
        kwargs, _EDIT_PARAMS, disable_preview=disable_web_page_preview
    )
    try:
        return await message.edit_text(safe_txt, **compat_kw)
    except (MessageNotModified, MessageIdInvalid, ChatWriteForbidden, Forbidden):
        return None
    except TypeError:
        compat_kw.pop("disable_web_page_preview", None)
        compat_kw.pop("link_preview_options", None)
        try:
            return await message.edit_text(safe_txt, **compat_kw)
        except Exception:
            return None
    except Exception:
        compat_kw.pop("parse_mode", None)
        try:
            return await message.edit_text(safe_txt, **compat_kw)
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
# ⚙️ MONGODB CONFIG ONLY + STABLE RAM ROTATION & JOIN TRACKER
# ============================================================
_fsub_db = None
_active_db = None

_FSUB_CONFIG_CACHE: Optional[dict] = None
_FSUB_CACHE_TS: float = 0.0
_INVITE_LINK_CACHE: Dict[str, Tuple[float, str]] = {}
_DEAD_FSUB_CHANNELS: Dict[str, float] = {}

_USER_ASSIGNED_CHANNEL: Dict[int, str] = {}
_USER_ROTATION_CURSOR: Dict[int, int] = {}
_PENDING_FSUB_DELIVERIES: Dict[int, Dict[str, Any]] = {}
_DELIVERY_LOCKS: Dict[int, asyncio.Lock] = {}

_RAM_JOIN_REQS: OrderedDict = OrderedDict()
_MAX_RAM_JOIN_REQS = 250000


def _record_ram_join_req(chat_id: int, user_id: int):
    key = (int(chat_id), int(user_id))
    _RAM_JOIN_REQS[key] = time.time()
    _RAM_JOIN_REQS.move_to_end(key)
    if len(_RAM_JOIN_REQS) > _MAX_RAM_JOIN_REQS:
        _RAM_JOIN_REQS.popitem(last=False)


def _has_ram_join_req(chat_id: int, user_id: int) -> bool:
    return (int(chat_id), int(user_id)) in _RAM_JOIN_REQS


def _remove_ram_join_req(chat_id: int, user_id: int):
    _RAM_JOIN_REQS.pop((int(chat_id), int(user_id)), None)


try:
    _DB_CLIENT = AsyncIOMotorClient(
        info.DATABASE_URI,
        serverSelectionTimeoutMS=4000,
        connectTimeoutMS=4000,
        socketTimeoutMS=8000,
    )
    _BOT_DB = _DB_CLIENT[info.DATABASE_NAME]
    _fsub_db = _BOT_DB["fsub_config"]
    _active_db = _BOT_DB["active_connections"]
except Exception as e:
    logger.error(f"Failed to init FSub DB config: {e}")


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
            for _, t_db in get_all_healthy_read_dbs():
                c = t_db[col_name]
                if c not in cols:
                    cols.append(c)
        except Exception:
            pass
    if fallback_col is not None and fallback_col not in cols:
        cols.append(fallback_col)
    return cols


def _ordered_channel_keys(channels_dict: dict) -> List[str]:
    if not channels_dict:
        return []
    indexed_items = list(enumerate(channels_dict.items()))
    indexed_items.sort(
        key=lambda item: (
            float(item[1][1].get("order", item[0]))
            if isinstance(item[1][1], dict)
            else float(item[0])
        )
    )
    return [cid_str for _, (cid_str, _) in indexed_items]


async def get_fsub_config(force_refresh: bool = False) -> dict:
    global _FSUB_CONFIG_CACHE, _FSUB_CACHE_TS
    now = time.time()
    if (
        not force_refresh
        and _FSUB_CONFIG_CACHE is not None
        and (now - _FSUB_CACHE_TS) < 300
    ):
        return _FSUB_CONFIG_CACHE

    default_cfg = {
        "is_enabled": True,
        "max_count": 0,
        "rotation_enabled": True,
        "channels": {},
        "updated_at": 0.0,
    }

    best_doc = None
    best_ts = -1.0

    for col in _get_all_candidate_cols("fsub_config", _fsub_db):
        try:
            doc = await asyncio.wait_for(col.find_one({"_id": "config"}), timeout=2.5)
            if doc:
                doc_ts = float(doc.get("updated_at", 0.0) or 0.0)
                if best_doc is None or doc_ts >= best_ts:
                    best_doc = doc
                    best_ts = doc_ts
        except Exception:
            continue

    if best_doc:
        for k, v in default_cfg.items():
            best_doc.setdefault(k, v)
        ch_dict = best_doc.get("channels", {})
        if isinstance(ch_dict, dict):
            for idx, (_, cid_v) in enumerate(ch_dict.items()):
                if isinstance(cid_v, dict) and "order" not in cid_v:
                    cid_v["order"] = idx

        if (
            _FSUB_CONFIG_CACHE is not None
            and float(_FSUB_CONFIG_CACHE.get("updated_at", 0.0) or 0.0) > best_ts
        ):
            _FSUB_CACHE_TS = now
            return _FSUB_CONFIG_CACHE

        _FSUB_CONFIG_CACHE = best_doc
        _FSUB_CACHE_TS = now
        return best_doc

    if _FSUB_CONFIG_CACHE is not None:
        _FSUB_CACHE_TS = now
        return _FSUB_CONFIG_CACHE

    _FSUB_CONFIG_CACHE = default_cfg
    _FSUB_CACHE_TS = now
    return default_cfg


async def _persist_full_fsub_config(cfg_doc: dict):
    payload = {
        "is_enabled": cfg_doc.get("is_enabled", True),
        "max_count": cfg_doc.get("max_count", 0),
        "rotation_enabled": cfg_doc.get("rotation_enabled", True),
        "channels": cfg_doc.get("channels", {}),
        "updated_at": cfg_doc.get("updated_at", time.time()),
    }
    for col in _get_all_candidate_cols("fsub_config", _fsub_db):
        try:
            await asyncio.wait_for(
                col.update_one({"_id": "config"}, {"$set": payload}, upsert=True),
                timeout=2.5,
            )
        except Exception:
            continue


async def update_fsub_config(key: str, value: Any):
    global _FSUB_CACHE_TS
    if _FSUB_CONFIG_CACHE is None:
        await get_fsub_config()
    now = time.time()
    if _FSUB_CONFIG_CACHE is not None:
        _FSUB_CONFIG_CACHE[key] = value
        _FSUB_CONFIG_CACHE["updated_at"] = now
        _FSUB_CACHE_TS = now
        await _persist_full_fsub_config(_FSUB_CONFIG_CACHE)


async def update_fsub_channels(channels_dict: dict):
    global _FSUB_CACHE_TS
    _USER_ASSIGNED_CHANNEL.clear()
    _DEAD_FSUB_CHANNELS.clear()
    if _FSUB_CONFIG_CACHE is None:
        await get_fsub_config()
    now = time.time()
    ordered_keys = _ordered_channel_keys(channels_dict)
    clean_channels = {}
    for idx, k in enumerate(ordered_keys):
        v = dict(channels_dict[k]) if isinstance(channels_dict[k], dict) else {}
        v["order"] = idx
        clean_channels[str(k)] = v

    if _FSUB_CONFIG_CACHE is not None:
        _FSUB_CONFIG_CACHE["channels"] = clean_channels
        _FSUB_CONFIG_CACHE["updated_at"] = now
        _FSUB_CACHE_TS = now
        await _persist_full_fsub_config(_FSUB_CONFIG_CACHE)


# ============================================================
# 🚫 RAM-ONLY USER/REQUEST HELPERS
# ============================================================
async def get_total_fsub_users() -> int:
    return len(_RAM_JOIN_REQS)


async def clear_all_fsub_users() -> int:
    cnt = len(_RAM_JOIN_REQS)
    _RAM_JOIN_REQS.clear()
    _USER_ASSIGNED_CHANNEL.clear()
    _USER_ROTATION_CURSOR.clear()
    for col_name in ("fsub_verified_users", "fsub_users"):
        for col in _get_all_candidate_cols(col_name, None):
            try:
                await col.drop()
            except Exception:
                pass
    return cnt


async def get_total_join_requests() -> int:
    return len(_RAM_JOIN_REQS)


async def clear_all_join_requests() -> int:
    cnt = len(_RAM_JOIN_REQS)
    _RAM_JOIN_REQS.clear()
    _USER_ASSIGNED_CHANNEL.clear()
    _USER_ROTATION_CURSOR.clear()
    for col in _get_all_candidate_cols("fsub_join_requests", None):
        try:
            await col.drop()
        except Exception:
            pass
    return cnt


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


async def is_global_admin(user_id: int) -> bool:
    return bool(user_id and int(user_id) in get_admin_list())


async def get_active_connection(user_id: str) -> Optional[int]:
    uid_str = str(user_id)
    if _active_db is not None:
        try:
            doc = await asyncio.wait_for(
                _active_db.find_one({"user_id": uid_str}), timeout=2.0
            )
            if doc and doc.get("group_id"):
                return int(doc["group_id"])
        except Exception:
            pass

    try:
        from database.connections_mdb import active_connection

        conn = await active_connection(uid_str)
        if conn:
            return int(conn)
    except Exception:
        pass

    try:
        from database.connections_mdb import all_connections, if_active

        groupids = await all_connections(uid_str)
        if groupids:
            for gid in groupids:
                if await if_active(uid_str, str(gid)):
                    return int(gid)
            return int(groupids[-1])
    except Exception:
        pass

    return None


async def get_target_chat(client: Client, message: Message) -> Optional[int]:
    if message.chat.type == enums.ChatType.PRIVATE:
        if not message.from_user:
            return None
        return await get_active_connection(str(message.from_user.id))
    return message.chat.id


async def verify_admin(
    client: Client, message: Message, target_chat_id: Optional[int] = None
) -> bool:
    uid = (
        message.from_user.id
        if message.from_user
        else getattr(message.sender_chat, "id", 0)
    )
    if await is_global_admin(uid):
        return True

    if message.chat.type == enums.ChatType.PRIVATE:
        if not target_chat_id:
            return False
        try:
            member = await client.get_chat_member(int(target_chat_id), uid)
            return member.status in [
                enums.ChatMemberStatus.ADMINISTRATOR,
                enums.ChatMemberStatus.OWNER,
            ]
        except Exception:
            return False

    if message.chat.type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
        if message.sender_chat and message.sender_chat.id == message.chat.id:
            return True
        if message.from_user:
            try:
                member = await client.get_chat_member(message.chat.id, uid)
                return member.status in [
                    enums.ChatMemberStatus.ADMINISTRATOR,
                    enums.ChatMemberStatus.OWNER,
                ]
            except Exception:
                return False
    return False


async def _require_fsub_admin(bot: Client, message: Message) -> bool:
    target_chat_id = await get_target_chat(bot, message)
    if await verify_admin(bot, message, target_chat_id):
        return True
    await safe_reply_text(
        message,
        "❌ <b>Unauthorized:</b> Admin only.",
        parse_mode=enums.ParseMode.HTML,
    )
    return False


async def verify_cb_admin(client: Client, query: CallbackQuery) -> bool:
    uid = query.from_user.id if query.from_user else 0
    if await is_global_admin(uid):
        return True
    if query.message and query.message.chat:
        if query.message.chat.type in [
            enums.ChatType.GROUP,
            enums.ChatType.SUPERGROUP,
        ]:
            try:
                member = await client.get_chat_member(query.message.chat.id, uid)
                return member.status in [
                    enums.ChatMemberStatus.ADMINISTRATOR,
                    enums.ChatMemberStatus.OWNER,
                ]
            except Exception:
                return False
        if query.message.chat.type == enums.ChatType.PRIVATE:
            conn_id = await get_active_connection(str(uid))
            if conn_id:
                try:
                    member = await client.get_chat_member(int(conn_id), uid)
                    return member.status in [
                        enums.ChatMemberStatus.ADMINISTRATOR,
                        enums.ChatMemberStatus.OWNER,
                    ]
                except Exception:
                    return False
    return False


# ============================================================
# 🔄 ASYNC NATIVE LISTENER ENGINE
# ============================================================
_WAITING_REQUESTS: Dict[int, dict] = {}


async def _fsub_waiting_filter_func(_, __, message: Message) -> bool:
    if not message.chat or message.chat.id not in _WAITING_REQUESTS:
        return False
    if (
        message.text
        and message.text.startswith("/")
        and message.text.strip().lower() != "/cancel"
    ):
        return False
    return True


fsub_waiting_filter = filters.create(_fsub_waiting_filter_func)


@Client.on_message((filters.group | filters.private) & fsub_waiting_filter, group=-12)
async def custom_listener(client: Client, message: Message):
    req_info = _WAITING_REQUESTS.get(message.chat.id)
    if not req_info:
        return

    sender_id = (
        message.from_user.id
        if message.from_user
        else getattr(message.sender_chat, "id", 0)
    )
    if (
        sender_id == req_info["session_id"]
        or sender_id == message.chat.id
        or await is_global_admin(sender_id)
    ):
        future = req_info["future"]
        if not future.done():
            future.set_result(message)
        raise StopPropagation


async def native_listen(
    client: Client, chat_id: int, user_id: int, timeout: int = 120
) -> Message:
    if chat_id in _WAITING_REQUESTS:
        old_fut = _WAITING_REQUESTS[chat_id].get("future")
        if old_fut and not old_fut.done():
            old_fut.cancel()

    loop = asyncio.get_running_loop()
    future = loop.create_future()
    _WAITING_REQUESTS[chat_id] = {"future": future, "session_id": user_id}
    try:
        return await asyncio.wait_for(future, timeout=timeout)
    finally:
        if _WAITING_REQUESTS.get(chat_id, {}).get("future") is future:
            _WAITING_REQUESTS.pop(chat_id, None)


# ============================================================
# 🔗 SELF-HEALING INVITE LINK & REAL-TIME LIVE CHECK ENGINE
# ============================================================
async def get_invite_link(
    bot: Client, chat_id_str: str, config: dict, force_regenerate: bool = False
) -> str:
    now = time.time()
    if now < _DEAD_FSUB_CHANNELS.get(chat_id_str, 0.0):
        return ""

    channels = config.get("channels", {})
    channel_data = channels.get(chat_id_str, {})
    if channel_data.get("target"):
        return str(channel_data["target"]).strip()

    if not force_regenerate:
        cached = _INVITE_LINK_CACHE.get(chat_id_str)
        if cached and (now - cached[0]) < 1800 and cached[1]:
            return cached[1]
        if channel_data.get("link"):
            _INVITE_LINK_CACHE[chat_id_str] = (now, str(channel_data["link"]).strip())
            return str(channel_data["link"]).strip()

    try:
        chat_id_int = int(str(chat_id_str).strip())
        chat = await bot.get_chat(chat_id_int)
        is_req = channel_data.get("type") == "req"
        inv_link = ""
        try:
            invite = await bot.create_chat_invite_link(
                chat_id_int, creates_join_request=is_req
            )
            inv_link = invite.invite_link
        except FloodWait as e:
            if e.value <= 5:
                await asyncio.sleep(e.value + 1)
            inv_link = channel_data.get("link") or ""
        except Exception:
            if not is_req:
                try:
                    inv_link = await bot.export_chat_invite_link(chat_id_int)
                except Exception:
                    inv_link = chat.invite_link or (
                        f"https://t.me/{chat.username}" if chat.username else ""
                    )

        if inv_link:
            _INVITE_LINK_CACHE[chat_id_str] = (now, inv_link)
            if chat_id_str in channels:
                channels[chat_id_str]["link"] = inv_link
                channels[chat_id_str]["title"] = chat.title or str(chat_id_int)
            return inv_link
        _DEAD_FSUB_CHANNELS[chat_id_str] = now + 300
        return ""
    except (ChatAdminRequired, PeerIdInvalid, Forbidden) as e:
        logger.error(f"FSub channel {chat_id_str} unreachable/no admin: {e}")
        _DEAD_FSUB_CHANNELS[chat_id_str] = now + 300
        return ""
    except Exception as e:
        logger.error(f"get_invite_link error for {chat_id_str}: {e}")
        return channel_data.get("link") or ""


async def check_user_in_channel(
    bot: Client, channel_id: int, user_id: int, is_req: bool = False
) -> bool:
    cid, uid = int(channel_id), int(user_id)
    cid_str = str(cid)

    if time.time() < _DEAD_FSUB_CHANNELS.get(cid_str, 0.0):
        return True

    if is_req and _has_ram_join_req(cid, uid):
        return True

    try:
        member = await bot.get_chat_member(cid, uid)
        if member.status in (
            enums.ChatMemberStatus.MEMBER,
            enums.ChatMemberStatus.ADMINISTRATOR,
            enums.ChatMemberStatus.OWNER,
            enums.ChatMemberStatus.RESTRICTED,
        ):
            return True
        if member.status in (enums.ChatMemberStatus.LEFT, enums.ChatMemberStatus.BANNED):
            if not is_req:
                _remove_ram_join_req(cid, uid)
    except UserNotParticipant:
        pass
    except FloodWait as e:
        if e.value <= 5:
            await asyncio.sleep(e.value + 1)
            return await check_user_in_channel(bot, cid, uid, is_req)
        return True
    except (ChatAdminRequired, PeerIdInvalid, Forbidden):
        _DEAD_FSUB_CHANNELS[cid_str] = time.time() + 300
        return True
    except Exception:
        return True

    return bool(is_req and _has_ram_join_req(cid, uid))


async def _get_missing_channels_and_buttons(
    bot: Client, user_id: int, config: dict, is_refresh: bool = False
) -> Tuple[List[List[InlineKeyboardButton]], List[int]]:
    channels_dict = config.get("channels", {})
    if not channels_dict:
        return [], []

    now = time.time()
    ordered_cids = [
        cid
        for cid in _ordered_channel_keys(channels_dict)
        if now >= _DEAD_FSUB_CHANNELS.get(cid, 0.0)
    ]
    if not ordered_cids:
        return [], []

    uid = int(user_id)
    rotation_enabled = config.get("rotation_enabled", True)
    max_count = int(config.get("max_count", 0) or 0)

    if rotation_enabled:
        assigned_cid = _USER_ASSIGNED_CHANNEL.get(uid)
        if assigned_cid and assigned_cid in channels_dict:
            is_req = channels_dict.get(assigned_cid, {}).get("type") == "req"
            if not await check_user_in_channel(bot, int(assigned_cid), uid, is_req):
                link = await get_invite_link(bot, assigned_cid, config)
                if link:
                    btn_text = "⚓ Request to Join" if is_req else "📢 Join Channel"
                    return (
                        [[create_btn(btn_text, url=link, style=BTN_PRIMARY)]],
                        [int(assigned_cid)],
                    )
            else:
                _USER_ASSIGNED_CHANNEL.pop(uid, None)
                try:
                    completed_idx = ordered_cids.index(assigned_cid)
                    _USER_ROTATION_CURSOR[uid] = (completed_idx + 1) % len(ordered_cids)
                except ValueError:
                    pass

        async def _check_line_single(cid_str: str):
            is_req = channels_dict.get(cid_str, {}).get("type") == "req"
            return cid_str, is_req, await check_user_in_channel(
                bot, int(cid_str), uid, is_req
            )

        results = await asyncio.gather(
            *[_check_line_single(cid) for cid in ordered_cids],
            return_exceptions=True,
        )

        status_by_cid: Dict[str, Tuple[bool, bool]] = {
            r[0]: (r[1], r[2]) for r in results if not isinstance(r, Exception)
        }

        start_idx = _USER_ROTATION_CURSOR.get(uid, 0) % len(ordered_cids)
        rotated_order = ordered_cids[start_idx:] + ordered_cids[:start_idx]

        for cid_str in rotated_order:
            is_req, joined = status_by_cid.get(cid_str, (False, True))
            if joined:
                continue
            link = await get_invite_link(bot, cid_str, config)
            if link:
                if len(_USER_ASSIGNED_CHANNEL) > 100000:
                    _USER_ASSIGNED_CHANNEL.clear()
                _USER_ASSIGNED_CHANNEL[uid] = cid_str
                btn_text = "⚓ Request to Join" if is_req else "📢 Join Channel"
                return (
                    [[create_btn(btn_text, url=link, style=BTN_PRIMARY)]],
                    [int(cid_str)],
                )

        return [], []

    eligible_channels = [
        cid
        for cid in ordered_cids
        if channels_dict.get(cid, {}).get("status", "active") == "active"
    ]
    if not eligible_channels:
        return [], []

    async def _check_static_single(cid_str: str):
        is_req = channels_dict.get(cid_str, {}).get("type") == "req"
        return cid_str, is_req, await check_user_in_channel(
            bot, int(cid_str), uid, is_req
        )

    results = await asyncio.gather(
        *[_check_static_single(cid) for cid in eligible_channels],
        return_exceptions=True,
    )

    not_joined_buttons: List[List[InlineKeyboardButton]] = []
    missing_cids: List[int] = []

    for res in results:
        if isinstance(res, Exception):
            continue
        cid_str, is_req, joined = res
        if joined:
            continue
        if max_count > 0 and len(missing_cids) >= max_count:
            break
        link = await get_invite_link(bot, cid_str, config)
        if link:
            btn_text = "⚓ Request to Join" if is_req else "📢 Join Channel"
            not_joined_buttons.append(
                [create_btn(btn_text, url=link, style=BTN_PRIMARY)]
            )
            missing_cids.append(int(cid_str))

    return not_joined_buttons, missing_cids


async def _get_missing_channel_buttons(
    bot: Client, user_id: int, config: dict
) -> List[List[InlineKeyboardButton]]:
    btns, _ = await _get_missing_channels_and_buttons(
        bot, user_id, config, is_refresh=False
    )
    return btns


# ============================================================
# 🚀 AUTOMATIC FILE DELIVERY ENGINE
# ============================================================
async def _deliver_verified_file(
    bot: Client, user_id: int, chat_id: int, file_id: str, mode: str = "checksub"
):
    if not file_id or file_id == "0":
        return

    if file_id.startswith(("BATCH-", "DSTORE-")):
        try:
            from plugins.genlink import deliver_genlink_payload

            if await deliver_genlink_payload(bot, user_id, chat_id, file_id):
                return
        except Exception as e:
            logger.error(f"Genlink FSub delivery error: {e}")

    try:
        from plugins.commands import send_requested_file

        if await get_file_details(file_id):
            await send_requested_file(
                client=bot,
                user_id=user_id,
                file_id=file_id,
                ident=mode or "file",
            )
            return
    except Exception as e:
        logger.error(f"Delegate send_requested_file error in fsub: {e}")

    try:
        from plugins.genlink import deliver_genlink_payload

        prefix = "filep" if mode in ("filep", "checksubp") else "file"
        await deliver_genlink_payload(bot, user_id, chat_id, f"{prefix}_{file_id}")
    except Exception:
        pass


async def _check_and_auto_deliver_for_user(
    bot: Client, user_id: int, joined_chat_id: Optional[int] = None
) -> bool:
    uid = int(user_id)
    if uid not in _PENDING_FSUB_DELIVERIES:
        return False

    if len(_DELIVERY_LOCKS) > 10000:
        _DELIVERY_LOCKS.clear()
    lock = _DELIVERY_LOCKS.setdefault(uid, asyncio.Lock())

    async with lock:
        pending = _PENDING_FSUB_DELIVERIES.get(uid)
        if not pending:
            return False

        config = await get_fsub_config()
        channels_dict = config.get("channels", {})
        ordered_cids = _ordered_channel_keys(channels_dict)

        for req_cid in pending.get("required_channels", []):
            if joined_chat_id is not None and int(req_cid) == int(joined_chat_id):
                continue
            is_req = channels_dict.get(str(req_cid), {}).get("type") == "req"
            if not await check_user_in_channel(bot, int(req_cid), uid, is_req):
                return False

        assigned_cid = _USER_ASSIGNED_CHANNEL.pop(uid, None)
        if assigned_cid and ordered_cids and assigned_cid in ordered_cids:
            idx = ordered_cids.index(assigned_cid)
            if len(_USER_ROTATION_CURSOR) > 100000:
                _USER_ROTATION_CURSOR.clear()
            _USER_ROTATION_CURSOR[uid] = (idx + 1) % len(ordered_cids)

        _PENDING_FSUB_DELIVERIES.pop(uid, None)

        watcher = _ACTIVE_WATCHER_TASKS.pop(uid, None)
        if watcher and not watcher.done() and watcher is not asyncio.current_task():
            watcher.cancel()

        prompt_chat_id = pending.get("chat_id")
        prompt_msg_id = pending.get("prompt_msg_id")
        if prompt_chat_id and prompt_msg_id:
            try:
                await bot.delete_messages(prompt_chat_id, prompt_msg_id)
            except Exception:
                pass

        file_id = pending.get("file_id", "0")
        mode = pending.get("mode", "checksub")
        if file_id and file_id != "0":
            await _deliver_verified_file(bot, uid, prompt_chat_id or uid, file_id, mode)
        return True


async def _background_join_poller(bot: Client, user_id: int):
    uid = int(user_id)
    try:
        for _ in range(90):
            await asyncio.sleep(2)
            if uid not in _PENDING_FSUB_DELIVERIES:
                return
            if await _check_and_auto_deliver_for_user(bot, uid):
                return
    except asyncio.CancelledError:
        return
    except Exception:
        pass
    finally:
        if _ACTIVE_WATCHER_TASKS.get(uid) is asyncio.current_task():
            _ACTIVE_WATCHER_TASKS.pop(uid, None)


def _register_pending_fsub_delivery(
    bot: Client,
    user_id: int,
    chat_id: int,
    file_id: str,
    mode: str,
    prompt_msg_id: Optional[int],
    required_channels: List[int],
):
    uid = int(user_id)
    if len(_PENDING_FSUB_DELIVERIES) > 20000:
        _PENDING_FSUB_DELIVERIES.clear()

    old_pending = _PENDING_FSUB_DELIVERIES.get(uid)
    if (
        old_pending
        and old_pending.get("prompt_msg_id")
        and old_pending.get("chat_id")
        and old_pending.get("prompt_msg_id") != prompt_msg_id
    ):
        asyncio.create_task(
            bot.delete_messages(old_pending["chat_id"], old_pending["prompt_msg_id"])
        )

    _PENDING_FSUB_DELIVERIES[uid] = {
        "chat_id": int(chat_id),
        "file_id": str(file_id or "0"),
        "mode": str(mode or "checksub"),
        "prompt_msg_id": prompt_msg_id,
        "required_channels": list(required_channels),
        "timestamp": time.time(),
    }

    old_task = _ACTIVE_WATCHER_TASKS.pop(uid, None)
    if old_task and not old_task.done():
        old_task.cancel()

    _ACTIVE_WATCHER_TASKS[uid] = asyncio.create_task(_background_join_poller(bot, uid))


# ============================================================
# 🛑 MAIN FORCESUB INTERCEPTOR (HIDDEN-LINK BUTTONS + AUTO-DELIVER)
# ============================================================
async def ForceSub(
    bot: Client, message: Message, file_id: str = None, mode: str = None
) -> bool:
    user = message.from_user
    if not user or await is_global_admin(user.id):
        return True

    config = await get_fsub_config()
    if not config.get("is_enabled", True) or not config.get("channels"):
        return True

    try:
        not_joined_buttons, missing_cids = await _get_missing_channels_and_buttons(
            bot, user.id, config, is_refresh=False
        )
        if not not_joined_buttons:
            return True

        safe_mode = mode or "checksub"
        safe_fid = file_id or "0"
        not_joined_buttons.append(
            [
                create_btn(
                    "🔄 Try Again",
                    callback_data=f"refresh_fsub#{safe_mode}#{safe_fid}",
                    style=BTN_SUCCESS,
                )
            ]
        )

        b_settings = await get_bot_settings() or {}
        custom_fsub_img = b_settings.get("fsub_img") or getattr(info, "FSUB_IMG", None)
        raw_fsub_msg = b_settings.get("fsub_msg") or getattr(info, "FSUB_MSG", None)
        fsub_caption = _ensure_non_empty_text(raw_fsub_msg, DEFAULT_FSUB_CAPTION)

        default_markup = InlineKeyboardMarkup(not_joined_buttons)
        try:
            parsed_cap, parsed_markup = parse_text_and_markup(
                fsub_caption, default_markup
            )
            fsub_caption = _ensure_non_empty_text(parsed_cap, DEFAULT_FSUB_CAPTION)
            final_markup = sanitize_markup_hide_links(parsed_markup or default_markup)
        except Exception:
            final_markup = default_markup

        sent_prompt: Optional[Message] = None
        try:
            if custom_fsub_img and str(custom_fsub_img).strip().lower() not in (
                "none",
                "null",
                "false",
                "",
            ):
                try:
                    sent_prompt = await message.reply_photo(
                        photo=custom_fsub_img,
                        caption=fsub_caption,
                        reply_markup=final_markup,
                        parse_mode=enums.ParseMode.HTML,
                    )
                except Exception:
                    sent_prompt = None

            if sent_prompt is None:
                sent_prompt = await safe_reply_text(
                    message,
                    fsub_caption,
                    reply_markup=final_markup,
                    disable_web_page_preview=True,
                    parse_mode=enums.ParseMode.HTML,
                )
        except (UserIsBlocked, PeerIdInvalid, ChatWriteForbidden, Forbidden):
            return False
        except Exception as e:
            logger.error(f"ForceSub reply error: {e}")

        _register_pending_fsub_delivery(
            bot=bot,
            user_id=user.id,
            chat_id=message.chat.id,
            file_id=safe_fid,
            mode=safe_mode,
            prompt_msg_id=sent_prompt.id if sent_prompt else None,
            required_channels=missing_cids,
        )
        return False
    except Exception as e:
        logger.error(f"ForceSub error: {e}")
        return True


@Client.on_callback_query(filters.regex(r"^refresh_fsub"), group=-3)
async def refresh_fsub_callback(bot: Client, query: CallbackQuery):
    if not query.message:
        return await safe_answer(query)
    user_id = query.from_user.id if query.from_user else 0
    data = query.data

    mode, file_id = "checksub", "0"
    if data.startswith("refresh_fsub#"):
        parts = data.split("#", 2)
        if len(parts) == 3:
            _, mode, file_id = parts
    elif data.startswith("refresh_fsub_"):
        file_id = data.replace("refresh_fsub_", "", 1)

    config = await get_fsub_config()
    if not await is_global_admin(user_id) and config.get("channels"):
        not_joined_buttons, missing_cids = await _get_missing_channels_and_buttons(
            bot, user_id, config, is_refresh=True
        )
        if not_joined_buttons:
            not_joined_buttons.append(
                [
                    create_btn(
                        "🔄 Try Again",
                        callback_data=f"refresh_fsub#{mode}#{file_id}",
                        style=BTN_SUCCESS,
                    )
                ]
            )
            await safe_answer(
                query,
                "❌ Please join the channel above — your file will be sent automatically!",
                show_alert=True,
            )
            try:
                await query.message.edit_reply_markup(
                    InlineKeyboardMarkup(not_joined_buttons)
                )
            except (MessageNotModified, MessageIdInvalid):
                pass
            _register_pending_fsub_delivery(
                bot=bot,
                user_id=user_id,
                chat_id=query.message.chat.id,
                file_id=file_id,
                mode=mode,
                prompt_msg_id=query.message.id,
                required_channels=missing_cids,
            )
            return

    _PENDING_FSUB_DELIVERIES.pop(int(user_id), None)
    await safe_answer(query, "✅ Subscription verified!")
    try:
        await query.message.delete()
    except Exception:
        pass

    await _deliver_verified_file(bot, user_id, query.message.chat.id, file_id, mode)


# ============================================================
# 🚪 INSTANT AUTO-DELIVERY ON JOIN REQUEST OR NORMAL CHANNEL JOIN
# ============================================================
@Client.on_chat_join_request(group=-3)
async def join_reqs_handler(bot: Client, join_req: ChatJoinRequest):
    user = join_req.from_user
    if not user or not join_req.chat:
        return
    try:
        uid, cid = int(user.id), int(join_req.chat.id)
        _record_ram_join_req(cid, uid)
        if uid in _PENDING_FSUB_DELIVERIES:
            await _check_and_auto_deliver_for_user(bot, uid, joined_chat_id=cid)
    except Exception as e:
        logger.error(f"join_reqs_handler auto-deliver error: {e}")


@Client.on_chat_member_updated(group=-3)
async def auto_deliver_on_channel_join(
    bot: Client, chat_member_updated: ChatMemberUpdated
):
    try:
        if not chat_member_updated or not chat_member_updated.chat:
            return
        new_m = chat_member_updated.new_chat_member
        if not new_m or not new_m.user:
            return

        cid, uid = int(chat_member_updated.chat.id), int(new_m.user.id)
        if new_m.status in (
            enums.ChatMemberStatus.MEMBER,
            enums.ChatMemberStatus.ADMINISTRATOR,
            enums.ChatMemberStatus.OWNER,
        ):
            if uid in _PENDING_FSUB_DELIVERIES:
                await _check_and_auto_deliver_for_user(bot, uid, joined_chat_id=cid)
        elif new_m.status in (
            enums.ChatMemberStatus.LEFT,
            enums.ChatMemberStatus.BANNED,
        ):
            _remove_ram_join_req(cid, uid)
    except Exception as e:
        logger.error(f"auto_deliver_on_channel_join error: {e}")


# ============================================================
# ⚙️ CONFIGURATION COMMANDS & INTERACTIVE BUTTONS
# ============================================================
@Client.on_message(filters.command("rotatefsub"), group=-15)
async def toggle_rotate(bot: Client, message: Message):
    if not await _require_fsub_admin(bot, message):
        return
    config = await get_fsub_config()
    new_val = not config.get("rotation_enabled", True)
    await update_fsub_config("rotation_enabled", new_val)
    status = (
        "🟢 ENABLED (Sequential In-Line: Ch A ➔ Ch B ➔ Ch C, 1 Button at a Time + Auto-Send)"
        if new_val
        else "🔴 DISABLED (Static Priority + Auto-Send)"
    )
    await safe_reply_text(
        message,
        f"🔄 <b>Auto-Rotation Engine:</b> {status}",
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(filters.command("enablefsub"), group=-15)
async def enable_fsub(bot: Client, message: Message):
    if not await _require_fsub_admin(bot, message):
        return
    await update_fsub_config("is_enabled", True)
    await safe_reply_text(
        message,
        "✅ <b>Force Subscribe has been ENABLED.</b>",
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(filters.command("disablefsub"), group=-15)
async def disable_fsub(bot: Client, message: Message):
    if not await _require_fsub_admin(bot, message):
        return
    await update_fsub_config("is_enabled", False)
    await safe_reply_text(
        message,
        "❌ <b>Force Subscribe has been DISABLED.</b>",
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(filters.command("setfsubcount"), group=-15)
async def set_fsub_count_cmd(bot: Client, message: Message):
    if not await _require_fsub_admin(bot, message):
        return
    if len(message.command) < 2 or not message.command[1].strip().isdigit():
        return await safe_reply_text(
            message,
            "⚙️ <b>Usage:</b> <code>/setfsubcount &lt;number&gt;</code>\n<i>(Use 0 for unlimited active channels)</i>",
            parse_mode=enums.ParseMode.HTML,
        )
    count_val = int(message.command[1].strip())
    await update_fsub_config("max_count", count_val)
    await safe_reply_text(
        message,
        f"✅ <b>Maximum ForceSub Queue Count set to:</b> <code>{count_val if count_val > 0 else 'Unlimited'}</code>",
        parse_mode=enums.ParseMode.HTML,
    )


async def _finalize_setfsub(
    bot: Client, chat_id: int, channel_id: str, is_req: bool
) -> Tuple[bool, str]:
    try:
        chat = await bot.get_chat(
            int(channel_id) if str(channel_id).lstrip("-").isdigit() else channel_id
        )
        config = await get_fsub_config()
        channels = dict(config.get("channels", {}))
        max_count = int(config.get("max_count", 0) or 0)
        active_count = sum(
            1
            for k, c in channels.items()
            if c.get("status") == "active" and k != str(chat.id)
        )
        status = "pending" if max_count > 0 and active_count >= max_count else "active"

        inv_link = ""
        try:
            invite = await bot.create_chat_invite_link(
                chat.id, creates_join_request=is_req
            )
            inv_link = invite.invite_link
        except Exception as e:
            if is_req:
                return (
                    False,
                    f"❌ <b>Failed to create Join Request link for <code>{html.escape(str(chat.title))}</code>.</b>\n"
                    f"Make sure the bot is an admin with <b>'Invite Users via Link'</b> permission.\n"
                    f"<code>Error: {html.escape(str(e))}</code>",
                )
            try:
                inv_link = await bot.export_chat_invite_link(chat.id)
            except Exception:
                inv_link = chat.invite_link or (
                    f"https://t.me/{chat.username}" if chat.username else ""
                )
            if not inv_link:
                return (
                    False,
                    f"❌ <b>The bot is not an admin in <code>{html.escape(str(chat.title))}</code> or lacks 'Invite Users' rights.</b>",
                )

        _INVITE_LINK_CACHE[str(chat.id)] = (time.time(), inv_link)
        _DEAD_FSUB_CHANNELS.pop(str(chat.id), None)

        existing_order = (
            channels[str(chat.id)].get("order", len(channels))
            if str(chat.id) in channels and isinstance(channels[str(chat.id)], dict)
            else len(channels)
        )
        channels[str(chat.id)] = {
            "title": chat.title or str(chat.id),
            "link": inv_link,
            "target": None,
            "type": "req" if is_req else "regular",
            "status": status,
            "order": existing_order,
        }
        await update_fsub_channels(channels)

        return (
            True,
            f"✅ <b>Successfully Configured FSub!</b>\n\n"
            f"📢 <b>Channel:</b> <code>{html.escape(str(chat.title or chat.id))}</code>\n"
            f"🆔 <b>ID:</b> <code>{chat.id}</code>\n"
            f"🔗 <b>Link:</b> <code>{html.escape(str(inv_link))}</code>\n"
            f"⚙️ <b>Type:</b> <code>{'Join Request' if is_req else 'Normal'}</code>\n"
            f"🟢 <b>Status:</b> <code>{status.upper()}</code>",
        )
    except ChatAdminRequired:
        return (
            False,
            "❌ <b>The bot is not an admin in that channel or lacks 'Invite Users' rights.</b>",
        )
    except Exception as e:
        return False, f"❌ <b>Error:</b> <code>{html.escape(str(e))}</code>"


@Client.on_message(filters.command("setfsub"), group=-15)
async def add_dynamic_fsub(bot: Client, message: Message):
    if not await _require_fsub_admin(bot, message):
        return

    if len(message.command) < 2:
        return await safe_reply_text(
            message,
            "⚙️ <b>Usage:</b> <code>/setfsub &lt;channel_id&gt;</code>\nExample: <code>/setfsub -1001234567890</code>",
            parse_mode=enums.ParseMode.HTML,
        )

    channel_id = message.command[1].strip()
    try:
        chat = await bot.get_chat(
            int(channel_id) if channel_id.lstrip("-").isdigit() else channel_id
        )
        channel_id = str(chat.id)
    except Exception as e:
        return await safe_reply_text(
            message,
            f"❌ <b>Failed to fetch channel.</b> Make sure the bot is an admin in <code>{html.escape(channel_id)}</code>.\n<code>Error: {html.escape(str(e))}</code>",
            parse_mode=enums.ParseMode.HTML,
        )

    if len(message.command) >= 3:
        is_req = message.command[2].strip().lower() in (
            "y",
            "yes",
            "req",
            "request",
            "true",
        )
        _, result_text = await _finalize_setfsub(
            bot, message.chat.id, channel_id, is_req
        )
        return await safe_reply_text(
            message,
            result_text,
            disable_web_page_preview=True,
            parse_mode=enums.ParseMode.HTML,
        )

    buttons = [
        [
            create_btn(
                "⚓ Join Request (Yes)",
                callback_data=f"fsub_setup#req#{channel_id}",
                style=BTN_SUCCESS,
            ),
            create_btn(
                "📢 Normal Invite (No)",
                callback_data=f"fsub_setup#reg#{channel_id}",
                style=BTN_PRIMARY,
            ),
        ],
        [
            create_btn(
                "❌ Cancel", callback_data="fsub_setup#cancel#0", style=BTN_DANGER
            )
        ],
    ]

    ask_msg = await safe_reply_text(
        message,
        f"🎯 <b>Target:</b> <code>{html.escape(str(chat.title or channel_id))}</code> (<code>{channel_id}</code>)\n\n"
        f"Do you want this to be a <b>Join Request</b> channel?\n\n"
        f"👉 <b>Click a button below</b> <i>(or reply with <code>y</code> / <code>n</code>)</i>:",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode=enums.ParseMode.HTML,
    )

    try:
        user_id = (
            message.from_user.id
            if message.from_user
            else getattr(message.sender_chat, "id", 0)
        )
        resp = await native_listen(bot, message.chat.id, user_id, timeout=60)
        if not resp or not resp.text:
            return
        txt = resp.text.strip().lower()
        if txt == "/cancel":
            if ask_msg:
                await safe_edit_text(
                    ask_msg,
                    "❌ <b>FSub setup cancelled.</b>",
                    parse_mode=enums.ParseMode.HTML,
                )
            return
        if txt in ("y", "yes", "n", "no"):
            try:
                await resp.delete()
            except Exception:
                pass
            _, result_text = await _finalize_setfsub(
                bot, message.chat.id, channel_id, txt in ("y", "yes")
            )
            if ask_msg:
                await safe_edit_text(
                    ask_msg,
                    result_text,
                    disable_web_page_preview=True,
                    parse_mode=enums.ParseMode.HTML,
                )
            else:
                await safe_reply_text(
                    message,
                    result_text,
                    disable_web_page_preview=True,
                    parse_mode=enums.ParseMode.HTML,
                )
    except (asyncio.TimeoutError, asyncio.CancelledError):
        pass


@Client.on_callback_query(
    filters.regex(r"^(fsub_setup#|fsub_purge#|fsub_del#)"), group=-15
)
async def fsub_admin_callbacks(bot: Client, query: CallbackQuery):
    if not await verify_cb_admin(bot, query):
        return await safe_answer(query, "❌ Unauthorized: Admin only.", show_alert=True)
    if not query.message:
        return await safe_answer(query)

    data = query.data
    if query.message.chat.id in _WAITING_REQUESTS:
        fut = _WAITING_REQUESTS[query.message.chat.id].get("future")
        if fut and not fut.done():
            fut.cancel()
        _WAITING_REQUESTS.pop(query.message.chat.id, None)

    if data.startswith("fsub_setup#"):
        _, mode, channel_id = data.split("#", 2)
        if mode == "cancel":
            await safe_answer(query, "Cancelled.")
            return await safe_edit_text(
                query.message,
                "❌ <b>FSub setup cancelled.</b>",
                parse_mode=enums.ParseMode.HTML,
            )

        await safe_answer(query, "⏳ Configuring FSub channel...")
        _, result_text = await _finalize_setfsub(
            bot, query.message.chat.id, channel_id, mode == "req"
        )
        return await safe_edit_text(
            query.message,
            result_text,
            disable_web_page_preview=True,
            parse_mode=enums.ParseMode.HTML,
        )

    if data.startswith("fsub_del#"):
        _, channel_id = data.split("#", 1)
        config = await get_fsub_config()
        channels = dict(config.get("channels", {}))
        if channel_id in channels:
            del channels[channel_id]
            _INVITE_LINK_CACHE.pop(channel_id, None)
            _DEAD_FSUB_CHANNELS.pop(channel_id, None)
            await update_fsub_channels(channels)
            await safe_answer(query, "🗑️ Channel removed!", show_alert=True)
            text, markup = await build_fsub_list_ui("All")
            return await safe_edit_text(
                query.message,
                text,
                reply_markup=markup,
                disable_web_page_preview=True,
                parse_mode=enums.ParseMode.HTML,
            )
        return await safe_answer(query, "Channel already removed.", show_alert=True)

    if data.startswith("fsub_purge#"):
        _, action = data.split("#", 1)
        if action == "cancel":
            await safe_answer(query, "Cancelled.")
            return await safe_edit_text(
                query.message,
                "❌ <b>Operation cancelled.</b>",
                parse_mode=enums.ParseMode.HTML,
            )
        if action == "confirm":
            count = await clear_all_join_requests()
            await safe_answer(query, "✅ Join requests purged!", show_alert=True)
            return await safe_edit_text(
                query.message,
                f"✅ <b>All join requests purged from RAM & DB!</b> (<code>{count}</code> cleared)",
                parse_mode=enums.ParseMode.HTML,
            )


@Client.on_message(filters.command(["rmfsub", "remfsub", "delfsub"]), group=-15)
async def rem_fsub(bot: Client, message: Message):
    if not await _require_fsub_admin(bot, message):
        return
    if len(message.command) < 2:
        return await safe_reply_text(
            message,
            "⚙️ <b>Usage:</b> <code>/rmfsub &lt;channel_id&gt;</code>",
            parse_mode=enums.ParseMode.HTML,
        )
    channel_id = message.command[1].strip()

    config = await get_fsub_config()
    channels = dict(config.get("channels", {}))
    if channel_id in channels:
        del channels[channel_id]
        _INVITE_LINK_CACHE.pop(channel_id, None)
        _DEAD_FSUB_CHANNELS.pop(channel_id, None)
        await update_fsub_channels(channels)
        await safe_reply_text(
            message,
            f"🗑️ <b>ForceSub channel <code>{html.escape(channel_id)}</code> removed permanently.</b>",
            parse_mode=enums.ParseMode.HTML,
        )
    else:
        await safe_reply_text(
            message,
            "❌ <b>Channel not found in FSub database.</b>",
            parse_mode=enums.ParseMode.HTML,
        )


@Client.on_message(
    filters.command(["rmallfsub", "remallfsub", "delallfsub"]), group=-15
)
async def rem_all_fsub(bot: Client, message: Message):
    if not await _require_fsub_admin(bot, message):
        return
    _INVITE_LINK_CACHE.clear()
    _DEAD_FSUB_CHANNELS.clear()
    await update_fsub_channels({})
    await safe_reply_text(
        message,
        "🗑️ <b>ALL ForceSub channels have been removed and database is empty.</b>",
        parse_mode=enums.ParseMode.HTML,
    )


async def build_fsub_list_ui(
    title_prefix: str = "All", filter_status: str = None
) -> Tuple[str, Optional[InlineKeyboardMarkup]]:
    config = await get_fsub_config()
    channels_dict = config.get("channels", {})
    max_count = config.get("max_count", 0)
    rot_status = (
        "ON (Sticky Progressive In-Line: Ch 1 ➔ Ch 2 ➔ Ch 3)"
        if config.get("rotation_enabled", True)
        else "OFF (Static Priority + Auto-Send)"
    )
    fsub_enabled = "🟢 ENABLED" if config.get("is_enabled", True) else "🔴 DISABLED"

    ordered_keys = _ordered_channel_keys(channels_dict)
    channels = [(k, channels_dict[k]) for k in ordered_keys]
    if filter_status:
        channels = [(k, v) for k, v in channels if v.get("status") == filter_status]

    header = (
        f"📡 <b>Force Subscribe Status:</b> {fsub_enabled}\n"
        f"⚙️ <b>Queue Limit:</b> <code>{max_count if max_count > 0 else 'Unlimited'}</code>\n"
        f"🔄 <b>Auto-Rotation:</b> <code>{rot_status}</code>\n"
        f"⚡ <b>Verification Mode:</b> <code>Real-Time Live Check + RAM Join-Request Tracker</code>\n\n"
    )

    if not channels:
        return (
            header + f"❌ <i>No {title_prefix.lower()} ForceSub channels configured.</i>",
            None,
        )

    text = (
        header
        + f"📋 <b>{title_prefix} ForceSub Channels In Line ({len(channels)}):</b>\n\n"
    )
    buttons = []
    for idx, (cid, data) in enumerate(channels, 1):
        is_dead = time.time() < _DEAD_FSUB_CHANNELS.get(cid, 0.0)
        status_emoji = (
            "🔴"
            if is_dead
            else ("🟢" if data.get("status", "active") == "active" else "🟡")
        )
        req_type = "Join Request" if data.get("type") == "req" else "Normal"
        raw_title = str(data.get("title", "Unknown"))
        active_link = html.escape(
            str(data.get("target") or data.get("link") or "No Link Generated")
        )
        text += (
            f"{idx}. {status_emoji} <b>{html.escape(raw_title)}</b>\n"
            f"├ ID: <code>{html.escape(str(cid))}</code>\n"
            f"├ Type: <code>{req_type}</code>\n"
            f"└ Link: <code>{active_link}</code>\n\n"
        )
        buttons.append(
            [
                create_btn(
                    f"🗑️ Remove {raw_title[:20]}",
                    callback_data=f"fsub_del#{cid}",
                    style=BTN_DANGER,
                )
            ]
        )

    return text, (InlineKeyboardMarkup(buttons) if buttons else None)


@Client.on_message(filters.command(["getallfsub", "allfsub", "fsub"]), group=-15)
async def get_all_fsub(bot: Client, message: Message):
    if not await _require_fsub_admin(bot, message):
        return
    text, markup = await build_fsub_list_ui("All")
    await safe_reply_text(
        message,
        text,
        reply_markup=markup,
        disable_web_page_preview=True,
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(filters.command(["getactivefsub", "activefsub"]), group=-15)
async def get_active_fsub_cmd(bot: Client, message: Message):
    if not await _require_fsub_admin(bot, message):
        return
    text, markup = await build_fsub_list_ui("Active", filter_status="active")
    await safe_reply_text(
        message,
        text,
        reply_markup=markup,
        disable_web_page_preview=True,
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(filters.command(["getpendingfsub", "pendingfsub"]), group=-15)
async def get_pending_fsub_cmd(bot: Client, message: Message):
    if not await _require_fsub_admin(bot, message):
        return
    text, markup = await build_fsub_list_ui("Pending", filter_status="pending")
    await safe_reply_text(
        message,
        text,
        reply_markup=markup,
        disable_web_page_preview=True,
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(filters.command(["activatefsub", "deactivatefsub"]), group=-15)
async def toggle_fsub_channel_status_cmd(bot: Client, message: Message):
    if not await _require_fsub_admin(bot, message):
        return
    cmd = message.command[0].lower()
    if len(message.command) < 2:
        return await safe_reply_text(
            message,
            f"⚙️ <b>Usage:</b> <code>/{cmd} &lt;channel_id&gt;</code>",
            parse_mode=enums.ParseMode.HTML,
        )

    cid = message.command[1].strip()
    config = await get_fsub_config()
    channels = dict(config.get("channels", {}))
    if cid not in channels:
        return await safe_reply_text(
            message,
            f"❌ <b>Channel <code>{html.escape(cid)}</code> not found in FSub database.</b>",
            parse_mode=enums.ParseMode.HTML,
        )

    new_status = "active" if cmd == "activatefsub" else "pending"
    channels[cid]["status"] = new_status
    _DEAD_FSUB_CHANNELS.pop(cid, None)
    await update_fsub_channels(channels)
    await safe_reply_text(
        message,
        f"✅ <b>Channel <code>{html.escape(cid)}</code> status updated to:</b> <code>{new_status.upper()}</code>",
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(filters.command("updatefsubtarget"), group=-15)
async def update_fsub_target_cmd(bot: Client, message: Message):
    if not await _require_fsub_admin(bot, message):
        return
    if len(message.command) < 3:
        return await safe_reply_text(
            message,
            "⚙️ <b>Usage:</b> <code>/updatefsubtarget &lt;channel_id&gt; &lt;custom_invite_url_or_off&gt;</code>",
            parse_mode=enums.ParseMode.HTML,
        )

    cid = message.command[1].strip()
    target_link = message.command[2].strip()
    config = await get_fsub_config()
    channels = dict(config.get("channels", {}))
    if cid not in channels:
        return await safe_reply_text(
            message,
            f"❌ <b>Channel <code>{html.escape(cid)}</code> not found in FSub database.</b>",
            parse_mode=enums.ParseMode.HTML,
        )

    channels[cid]["target"] = (
        None if target_link.lower() in ("off", "none", "reset") else target_link
    )
    _INVITE_LINK_CACHE.pop(cid, None)
    _DEAD_FSUB_CHANNELS.pop(cid, None)
    await update_fsub_channels(channels)
    await safe_reply_text(
        message,
        f"✅ <b>Updated custom target link for <code>{html.escape(cid)}</code>!</b>",
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(filters.command("checkfsubusers"), group=-15)
async def check_fsub_users_cmd(bot: Client, message: Message):
    if not await _require_fsub_admin(bot, message):
        return
    await safe_reply_text(
        message,
        f"ℹ️ <b>Live Telegram Check + RAM Join-Request Mode Active:</b>\n"
        f"• <b>Active Join Requests in RAM:</b> <code>{len(_RAM_JOIN_REQS):,}</code>\n"
        f"• <b>MongoDB User Storage:</b> <code>0 Bytes (Disabled)</code>",
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(filters.command("clearfsubusers"), group=-15)
async def clear_fsub_users_cmd(bot: Client, message: Message):
    if not await _require_fsub_admin(bot, message):
        return
    cnt = await clear_all_fsub_users()
    await safe_reply_text(
        message,
        f"🗑️ <b>Cleared <code>{cnt:,}</code> RAM Join Requests & dropped any legacy MongoDB user collections!</b>",
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(filters.command("totalrequests"), group=-15)
async def total_requests(bot: Client, message: Message):
    if not await _require_fsub_admin(bot, message):
        return
    await safe_reply_text(
        message,
        f"📨 <b>Active Join Requests in RAM:</b> <code>{len(_RAM_JOIN_REQS):,}</code>\n"
        f"<i>(Zero join requests are stored in MongoDB)</i>",
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(filters.command("purgerequests"), group=-15)
async def purge_requests(bot: Client, message: Message):
    if not await _require_fsub_admin(bot, message):
        return
    cnt = await clear_all_join_requests()
    await safe_reply_text(
        message,
        f"✅ <b>Purged <code>{cnt:,}</code> join requests from RAM and dropped any legacy MongoDB collections!</b>",
        parse_mode=enums.ParseMode.HTML,
    )
