import asyncio
import html
import inspect
import time
from logging import ERROR, getLogger
from typing import Any, Dict, List, Optional, Set, Tuple

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

AUTO_DELETE_TASKS = set()
_ACTIVE_WATCHER_TASKS: Dict[int, asyncio.Task] = {}

DEFAULT_FSUB_CAPTION = "<b>Please join below channel to get file!</b>"

# ============================================================
# 🛡️ SAFE OPTIONAL IMPORTS (ZERO PLUGIN LOAD CRASHES)
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
    from plugins.uibuttons import (
        get_deleted_file_notify_keyboard as _get_deleted_file_notify_keyboard,
    )
except Exception:
    _get_deleted_file_notify_keyboard = None


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


def _ensure_non_empty_text(text: Any, fallback: str = DEFAULT_FSUB_CAPTION) -> str:
    if text is None:
        return fallback
    s = str(text).strip()
    if not s or s.lower() in ["none", "null", "false"]:
        return fallback
    return s


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
    safe_txt = _ensure_non_empty_text(text)
    compat_kw = _prepare_compat_kwargs(
        kwargs, _REPLY_PARAMS, disable_preview=disable_web_page_preview
    )
    try:
        return await message.reply_text(safe_txt, **compat_kw)
    except MessageEmpty:
        return await message.reply_text(DEFAULT_FSUB_CAPTION, **compat_kw)
    except TypeError:
        compat_kw.pop("disable_web_page_preview", None)
        compat_kw.pop("link_preview_options", None)
        compat_kw.pop("reply_parameters", None)
        compat_kw.pop("reply_to_message_id", None)
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
    safe_txt = _ensure_non_empty_text(text)
    compat_kw = _prepare_compat_kwargs(
        kwargs, _EDIT_PARAMS, disable_preview=disable_web_page_preview
    )
    try:
        return await message.edit_text(safe_txt, **compat_kw)
    except TypeError:
        compat_kw.pop("disable_web_page_preview", None)
        compat_kw.pop("link_preview_options", None)
        return await message.edit_text(safe_txt, **compat_kw)
    except (MessageNotModified, MessageIdInvalid, ChatWriteForbidden, Forbidden):
        return None
    except Exception:
        compat_kw.pop("parse_mode", None)
        try:
            return await message.edit_text(safe_txt, **compat_kw)
        except Exception:
            return None


async def safe_send_message(
    client: Client,
    chat_id: int,
    text: str,
    disable_web_page_preview: Optional[bool] = True,
    **kwargs,
):
    safe_txt = _ensure_non_empty_text(text)
    compat_kw = _prepare_compat_kwargs(
        kwargs, _SEND_MSG_PARAMS, disable_preview=disable_web_page_preview
    )
    try:
        return await client.send_message(chat_id=chat_id, text=safe_txt, **compat_kw)
    except MessageEmpty:
        return await client.send_message(
            chat_id=chat_id, text=DEFAULT_FSUB_CAPTION, **compat_kw
        )
    except TypeError:
        compat_kw.pop("disable_web_page_preview", None)
        compat_kw.pop("link_preview_options", None)
        compat_kw.pop("reply_parameters", None)
        compat_kw.pop("reply_to_message_id", None)
        return await client.send_message(chat_id=chat_id, text=safe_txt, **compat_kw)
    except (ChatWriteForbidden, Forbidden, UserIsBlocked, PeerIdInvalid):
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
# 🎨 SAFE TELEGRAM BUTTON STYLE DETECTION
# ============================================================
BTN_PRIMARY = None
BTN_SECONDARY = None
BTN_SUCCESS = None
BTN_DANGER = None
_SUPPORTS_BTN_STYLE = False

try:
    from pyrogram.enums import ButtonStyle

    if "style" in inspect.signature(InlineKeyboardButton.__init__).parameters:
        BTN_PRIMARY = getattr(ButtonStyle, "PRIMARY", None)
        BTN_SECONDARY = getattr(ButtonStyle, "SECONDARY", None)
        BTN_SUCCESS = getattr(ButtonStyle, "SUCCESS", None)
        BTN_DANGER = getattr(ButtonStyle, "DANGER", None)
        _SUPPORTS_BTN_STYLE = True
except (ImportError, ValueError, TypeError):
    BTN_PRIMARY = BTN_SECONDARY = BTN_SUCCESS = BTN_DANGER = None
    _SUPPORTS_BTN_STYLE = False


def create_btn(text, url=None, callback_data=None, style=None):
    kwargs = {"text": str(text)}
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
# ⏳ SELF-CONTAINED AUTO-DELETE ENGINE
# ============================================================
def get_auto_delete_timer(
    var_name: str = "FILE_AUTO_DELETE", default_time: int = 1800
) -> int:
    try:
        global_switch = getattr(info, "AUTO_DELETE", True)
        if str(global_switch).strip().lower() in ["false", "off", "0", "no"]:
            return 0
        raw_val = getattr(
            info,
            var_name,
            getattr(
                info,
                "FILE_AUTO_DELETE",
                getattr(info, "AUTO_DELETE_TIME", default_time),
            ),
        )
        if isinstance(raw_val, bool):
            return default_time if raw_val else 0
        val = int(str(raw_val).strip())
        return 1800 if 0 < val < 10 else max(0, val)
    except Exception:
        return default_time


async def _fsub_auto_delete_worker(
    client: Client, chat_id: int, is_pm: bool, delay: int, *messages
):
    await asyncio.sleep(delay)
    msg_ids = [m.id for m in messages if m is not None and hasattr(m, "id") and m.id]
    if msg_ids:
        try:
            await client.delete_messages(chat_id, msg_ids)
        except Exception:
            for m in messages:
                if m is not None:
                    try:
                        await m.delete()
                    except Exception:
                        pass

    if is_pm:
        notify_text = (
            getattr(info, "DEL_MSG", None)
            or "<b>Successfully deleted your file, if you want request again in group.</b>"
        )
        markup = (
            _get_deleted_file_notify_keyboard()
            if callable(_get_deleted_file_notify_keyboard)
            else InlineKeyboardMarkup(
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


def schedule_auto_delete(
    client: Client, chat_id: int, is_pm: bool, delay: int, *messages
):
    if delay <= 0:
        return
    task = asyncio.create_task(
        _fsub_auto_delete_worker(client, chat_id, is_pm, delay, *messages)
    )
    AUTO_DELETE_TASKS.add(task)
    task.add_done_callback(AUTO_DELETE_TASKS.discard)


# ============================================================
# ⚙️ MONGODB CONFIG ONLY (ONLY FSUB CHANNELS ARE SAVED IN DB)
# ============================================================
_fsub_db = None
_active_db = None
_BOT_DB = None

_FSUB_CONFIG_CACHE: Optional[dict] = None
_FSUB_CACHE_TS: float = 0.0
_INVITE_LINK_CACHE: Dict[str, str] = {}

_USER_ASSIGNED_CHANNEL: Dict[int, str] = {}
_PENDING_FSUB_DELIVERIES: Dict[int, Dict[str, Any]] = {}
_DELIVERY_LOCKS: Dict[int, asyncio.Lock] = {}

# Ephemeral in-memory tracker ONLY for active pending file requests on private Join-Request channels
# (Never saved to MongoDB, cleared immediately upon file delivery or session expiry)
_ACTIVE_SESSION_JOIN_REQS: Set[Tuple[int, int]] = set()

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


def _get_writable_col(col_name: str, fallback_col: Any):
    if callable(get_writable_System_db):
        try:
            target_db = get_writable_System_db()
            if target_db is not None:
                return target_db[col_name]
        except Exception:
            pass
    return fallback_col


def _get_all_candidate_cols(col_name: str, fallback_col: Any) -> List[Any]:
    cols = []
    w_col = _get_writable_col(col_name, None)
    if w_col is not None:
        cols.append(w_col)
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
            doc = await col.find_one({"_id": "config"})
            if doc:
                doc_ts = float(doc.get("updated_at", 0.0) or 0.0)
                if best_doc is None or doc_ts >= best_ts:
                    best_doc = doc
                    best_ts = doc_ts
        except Exception:
            continue

    if best_doc:
        for k, v in default_cfg.items():
            if k not in best_doc:
                best_doc[k] = v
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
    """Saves ONLY the ForceSub channel configuration in MongoDB."""
    payload = {
        "is_enabled": cfg_doc.get("is_enabled", True),
        "max_count": cfg_doc.get("max_count", 0),
        "rotation_enabled": cfg_doc.get("rotation_enabled", True),
        "channels": cfg_doc.get("channels", {}),
        "updated_at": cfg_doc.get("updated_at", time.time()),
    }
    for col in _get_all_candidate_cols("fsub_config", _fsub_db):
        try:
            await col.update_one({"_id": "config"}, {"$set": payload}, upsert=True)
        except Exception:
            continue


async def update_fsub_config(key: str, value: Any):
    global _FSUB_CONFIG_CACHE, _FSUB_CACHE_TS
    if _FSUB_CONFIG_CACHE is None:
        await get_fsub_config()
    now = time.time()
    if _FSUB_CONFIG_CACHE is not None:
        _FSUB_CONFIG_CACHE[key] = value
        _FSUB_CONFIG_CACHE["updated_at"] = now
        _FSUB_CACHE_TS = now
        await _persist_full_fsub_config(_FSUB_CONFIG_CACHE)


async def update_fsub_channels(channels_dict: dict):
    global _FSUB_CONFIG_CACHE, _FSUB_CACHE_TS
    _USER_ASSIGNED_CHANNEL.clear()
    if _FSUB_CONFIG_CACHE is None:
        await get_fsub_config()
    now = time.time()
    if _FSUB_CONFIG_CACHE is not None:
        _FSUB_CONFIG_CACHE["channels"] = dict(channels_dict)
        _FSUB_CONFIG_CACHE["updated_at"] = now
        _FSUB_CACHE_TS = now
        await _persist_full_fsub_config(_FSUB_CONFIG_CACHE)


# ============================================================
# 🚫 NO-OP USER/REQUEST HELPERS (ZERO USER DATA SAVED IN DB)
# ============================================================
async def get_total_fsub_users() -> int:
    """User records are never stored in MongoDB (live Telegram check on every file request)."""
    return 0


async def clear_all_fsub_users() -> int:
    """Drops any legacy user collections if they existed previously to free DB space."""
    _ACTIVE_SESSION_JOIN_REQS.clear()
    for col_name in ("fsub_verified_users", "fsub_users"):
        for col in _get_all_candidate_cols(col_name, None):
            try:
                await col.drop()
            except Exception:
                pass
    return 0


async def get_total_join_requests() -> int:
    """Join requests are never stored in MongoDB."""
    return 0


async def clear_all_join_requests() -> int:
    """Drops any legacy join request collections if they existed previously to free DB space."""
    cnt = len(_ACTIVE_SESSION_JOIN_REQS)
    _ACTIVE_SESSION_JOIN_REQS.clear()
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
    if not user_id:
        return False
    return int(user_id) in get_admin_list()


async def get_active_connection(user_id: str) -> Optional[int]:
    uid_str = str(user_id)
    if _active_db is not None:
        try:
            doc = await _active_db.find_one({"user_id": uid_str})
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
        elif query.message.chat.type == enums.ChatType.PRIVATE:
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
# 🔄 ASYNC NATIVE LISTENER ENGINE (NON-BLOCKING FILTER)
# ============================================================
_WAITING_REQUESTS: Dict[int, dict] = {}


async def _fsub_waiting_filter_func(_, __, message: Message) -> bool:
    if not message.chat or message.chat.id not in _WAITING_REQUESTS:
        return False
    if (
        message.text
        and message.text.startswith("/")
        and message.text.strip().lower() not in ["/cancel"]
    ):
        return False
    return True


fsub_waiting_filter = filters.create(_fsub_waiting_filter_func)


@Client.on_message((filters.group | filters.private) & fsub_waiting_filter, group=-12)
async def custom_listener(client: Client, message: Message):
    chat_id = message.chat.id
    req_info = _WAITING_REQUESTS.get(chat_id)
    if not req_info:
        return

    sender_id = (
        message.from_user.id
        if message.from_user
        else getattr(message.sender_chat, "id", 0)
    )
    expected_session_id = req_info["session_id"]

    if (
        sender_id == expected_session_id
        or sender_id == chat_id
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
# 🔗 INVITE LINK & REAL-TIME LIVE MEMBERSHIP CHECK ENGINE
# ============================================================
async def get_invite_link(bot: Client, chat_id_str: str, config: dict) -> str:
    channels = config.get("channels", {})
    channel_data = channels.get(chat_id_str, {})
    if channel_data.get("target"):
        return channel_data["target"]
    if channel_data.get("link"):
        return channel_data["link"]
    if chat_id_str in _INVITE_LINK_CACHE:
        return _INVITE_LINK_CACHE[chat_id_str]

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
        except Exception:
            try:
                inv_link = await bot.export_chat_invite_link(chat_id_int)
            except Exception:
                inv_link = chat.invite_link or (
                    f"https://t.me/{chat.username}" if chat.username else ""
                )

        if inv_link:
            _INVITE_LINK_CACHE[chat_id_str] = inv_link
            if chat_id_str not in channels:
                channels[chat_id_str] = {
                    "title": chat.title or str(chat_id_int),
                    "link": inv_link,
                    "target": None,
                    "type": "req" if is_req else "regular",
                    "status": "active",
                }
            else:
                channels[chat_id_str]["link"] = inv_link
                channels[chat_id_str]["title"] = chat.title or str(chat_id_int)
            await update_fsub_channels(channels)
        return inv_link
    except (ChatAdminRequired, Exception) as e:
        logger.error(f"get_invite_link error for {chat_id_str}: {e}")
        return ""


async def check_user_in_channel(
    bot: Client, channel_id: int, user_id: int, is_req: bool = False
) -> bool:
    """
    Performs a 100% real-time live check against Telegram on every single request.
    Zero user records or join requests are ever stored in MongoDB!
    """
    cid, uid = int(channel_id), int(user_id)
    try:
        member = await bot.get_chat_member(cid, uid)
        if member.status in [
            enums.ChatMemberStatus.MEMBER,
            enums.ChatMemberStatus.ADMINISTRATOR,
            enums.ChatMemberStatus.OWNER,
        ]:
            return True
    except UserNotParticipant:
        pass
    except FloodWait as e:
        if e.value <= 5:
            await asyncio.sleep(e.value + 1)
            return await check_user_in_channel(bot, cid, uid, is_req)
        return True
    except Exception:
        pass

    # If the user just clicked "Request to Join" during this active pending file request
    if is_req and (cid, uid) in _ACTIVE_SESSION_JOIN_REQS:
        return True

    return False


async def _get_missing_channels_and_buttons(
    bot: Client, user_id: int, config: dict, is_refresh: bool = False
) -> Tuple[List[List[InlineKeyboardButton]], List[int]]:
    """
    Performs a real-time live check against Telegram every single time a user requests a file.
    """
    channels_dict = config.get("channels", {})
    if not channels_dict:
        return [], []

    rotation_enabled = config.get("rotation_enabled", True)
    max_count = int(config.get("max_count", 0) or 0)

    if rotation_enabled:
        all_channels = list(channels_dict.keys())
        if not all_channels:
            return [], []

        uid = int(user_id)

        async def _check_line_single(cid_str: str):
            ch_data = channels_dict.get(cid_str, {})
            is_req = ch_data.get("type") == "req"
            joined = await check_user_in_channel(bot, int(cid_str), uid, is_req)
            return cid_str, is_req, joined

        results = await asyncio.gather(
            *[_check_line_single(cid) for cid in all_channels],
            return_exceptions=True,
        )

        for res in results:
            if isinstance(res, Exception):
                continue
            cid_str, is_req, joined = res
            if joined:
                continue
            link = await get_invite_link(bot, cid_str, config)
            if link:
                btn_text = "⚓ Request to Join" if is_req else "📢 Join Channel"
                return (
                    [[create_btn(btn_text, url=link, style=BTN_PRIMARY)]],
                    [int(cid_str)],
                )

        return [], []

    # Static priority mode
    eligible_channels = [
        k for k, v in channels_dict.items() if v.get("status", "active") == "active"
    ]
    if not eligible_channels:
        return [], []

    not_joined_buttons = []
    missing_cids: List[int] = []
    channels_to_force = 0

    for cid_str in eligible_channels:
        ch_data = channels_dict.get(cid_str, {})
        is_req = ch_data.get("type") == "req"
        if await check_user_in_channel(bot, int(cid_str), user_id, is_req):
            continue
        if max_count > 0 and channels_to_force >= max_count:
            break
        link = await get_invite_link(bot, cid_str, config)
        if link:
            btn_text = "⚓ Request to Join" if is_req else "📢 Join Channel"
            not_joined_buttons.append(
                [create_btn(btn_text, url=link, style=BTN_PRIMARY)]
            )
            missing_cids.append(int(cid_str))
            channels_to_force += 1

    return not_joined_buttons, missing_cids


async def _get_missing_channel_buttons(
    bot: Client, user_id: int, config: dict
) -> List[List[InlineKeyboardButton]]:
    """Helper used by utils.is_subscribed for live Telegram membership verification."""
    btns, _ = await _get_missing_channels_and_buttons(
        bot, user_id, config, is_refresh=False
    )
    return btns


# ============================================================
# 🚀 AUTOMATIC FILE DELIVERY ENGINE (LIVE CHECK, ZERO DB WRITES)
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

        files_ = await get_file_details(file_id)
        if files_:
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

        prefix = "filep" if mode in ["filep", "checksubp"] else "file"
        if await deliver_genlink_payload(bot, user_id, chat_id, f"{prefix}_{file_id}"):
            return
    except Exception:
        pass


def _clear_ephemeral_user_join_reqs(user_id: int):
    """Clears any ephemeral join-request flags for this user so the next file request checks fresh."""
    uid = int(user_id)
    for pair in list(_ACTIVE_SESSION_JOIN_REQS):
        if pair[1] == uid:
            _ACTIVE_SESSION_JOIN_REQS.discard(pair)


async def _check_and_auto_deliver_for_user(bot: Client, user_id: int) -> bool:
    uid = int(user_id)
    pending = _PENDING_FSUB_DELIVERIES.get(uid)
    if not pending:
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
        required_cids: List[int] = pending.get("required_channels", [])

        for req_cid in required_cids:
            ch_data = channels_dict.get(str(req_cid), {})
            is_req = ch_data.get("type") == "req"
            if not await check_user_in_channel(bot, int(req_cid), uid, is_req):
                return False

        _PENDING_FSUB_DELIVERIES.pop(uid, None)
        _clear_ephemeral_user_join_reqs(uid)

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
        for _ in range(150):  # 150 * 2s = 5 minutes
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
        _clear_ephemeral_user_join_reqs(uid)
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

    _clear_ephemeral_user_join_reqs(uid)

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

    task = asyncio.create_task(_background_join_poller(bot, uid))
    _ACTIVE_WATCHER_TASKS[uid] = task


# ============================================================
# 🛑 MAIN FORCESUB INTERCEPTOR (LIVE CHECK EVERY TIME, ZERO DB STORAGE)
# ============================================================
async def ForceSub(
    bot: Client, message: Message, file_id: str = None, mode: str = None
) -> bool:
    user = message.from_user
    if not user:
        return True
    if await is_global_admin(user.id):
        return True

    config = await get_fsub_config()
    if not config.get("is_enabled", True) or not config.get("channels"):
        return True

    try:
        # Clear any old session state so every file request performs a fresh live check against Telegram
        _clear_ephemeral_user_join_reqs(user.id)

        not_joined_buttons, missing_cids = await _get_missing_channels_and_buttons(
            bot, user.id, config, is_refresh=False
        )

        if not not_joined_buttons:
            return True

        safe_mode = mode or "checksub"
        safe_fid = file_id or "0"

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
            final_markup = parsed_markup or default_markup
        except Exception:
            final_markup = default_markup

        sent_prompt: Optional[Message] = None
        try:
            if custom_fsub_img and str(custom_fsub_img).strip().lower() not in [
                "none",
                "null",
                "false",
                "",
            ]:
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
    user_id = query.from_user.id if query.from_user else 0
    data = query.data

    mode = "checksub"
    file_id = "0"
    if data.startswith("refresh_fsub#"):
        parts = data.split("#", 2)
        if len(parts) == 3:
            _, mode, file_id = parts
    elif data.startswith("refresh_fsub_"):
        file_id = data.replace("refresh_fsub_", "", 1)

    config = await get_fsub_config()
    channels_dict = config.get("channels", {})

    if not await is_global_admin(user_id) and channels_dict:
        not_joined_buttons, missing_cids = await _get_missing_channels_and_buttons(
            bot, user_id, config, is_refresh=True
        )

        if not_joined_buttons:
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
    _clear_ephemeral_user_join_reqs(user_id)
    await safe_answer(query, "✅ Subscription verified!", show_alert=False)

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
    """
    Handles live join requests in memory ONLY if the user has an active pending file request.
    Never saves anything to MongoDB, and clears immediately once the file is delivered!
    """
    user = join_req.from_user
    if not user or not join_req.chat:
        return
    try:
        uid = int(user.id)
        cid = int(join_req.chat.id)
        if uid in _PENDING_FSUB_DELIVERIES:
            _ACTIVE_SESSION_JOIN_REQS.add((cid, uid))
            await _check_and_auto_deliver_for_user(bot, uid)
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

        if new_m.status in [
            enums.ChatMemberStatus.MEMBER,
            enums.ChatMemberStatus.ADMINISTRATOR,
            enums.ChatMemberStatus.OWNER,
        ]:
            uid = int(new_m.user.id)
            if uid in _PENDING_FSUB_DELIVERIES:
                await _check_and_auto_deliver_for_user(bot, uid)
    except Exception as e:
        logger.error(f"auto_deliver_on_channel_join error: {e}")


# ============================================================
# ⚙️ CONFIGURATION COMMANDS & INTERACTIVE BUTTONS
# ============================================================
@Client.on_message(filters.command("rotatefsub"), group=-15)
async def toggle_rotate(bot: Client, message: Message):
    target_chat_id = await get_target_chat(bot, message)
    if not await verify_admin(bot, message, target_chat_id):
        return await safe_reply_text(
            message,
            "❌ <b>Unauthorized:</b> Admin only.",
            parse_mode=enums.ParseMode.HTML,
        )

    config = await get_fsub_config()
    current = config.get("rotation_enabled", True)
    new_val = not current
    await update_fsub_config("rotation_enabled", new_val)
    status = (
        "🟢 ENABLED (Sequential In-Line: Ch A ➔ Ch B ➔ Ch C, 1 Button at a Time + Auto-Send)"
        if new_val
        else "🔴 DISABLED (Static Priority + Auto-Send)"
    )
    await safe_reply_text(
        message,
        f"🔄 <b>Auto-Rotation Engine:</b> {status}\n\n"
        f"<i>When enabled, every member is checked in line in real time against Telegram!</i>",
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(filters.command("enablefsub"), group=-15)
async def enable_fsub(bot: Client, message: Message):
    target_chat_id = await get_target_chat(bot, message)
    if not await verify_admin(bot, message, target_chat_id):
        return await safe_reply_text(
            message,
            "❌ <b>Unauthorized:</b> Admin only.",
            parse_mode=enums.ParseMode.HTML,
        )

    await update_fsub_config("is_enabled", True)
    await safe_reply_text(
        message,
        "✅ <b>Force Subscribe has been ENABLED.</b>",
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(filters.command("disablefsub"), group=-15)
async def disable_fsub(bot: Client, message: Message):
    target_chat_id = await get_target_chat(bot, message)
    if not await verify_admin(bot, message, target_chat_id):
        return await safe_reply_text(
            message,
            "❌ <b>Unauthorized:</b> Admin only.",
            parse_mode=enums.ParseMode.HTML,
        )

    await update_fsub_config("is_enabled", False)
    await safe_reply_text(
        message,
        "❌ <b>Force Subscribe has been DISABLED.</b>",
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(filters.command("setfsubcount"), group=-15)
async def set_fsub_count_cmd(bot: Client, message: Message):
    target_chat_id = await get_target_chat(bot, message)
    if not await verify_admin(bot, message, target_chat_id):
        return await safe_reply_text(
            message,
            "❌ <b>Unauthorized:</b> Admin only.",
            parse_mode=enums.ParseMode.HTML,
        )

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
        fsub_type = "req" if is_req else "regular"

        config = await get_fsub_config()
        channels = dict(config.get("channels", {}))
        max_count = int(config.get("max_count", 0) or 0)
        active_count = len(
            [
                k
                for k, c in channels.items()
                if c.get("status") == "active" and k != str(chat.id)
            ]
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

        _INVITE_LINK_CACHE[str(chat.id)] = inv_link

        channels[str(chat.id)] = {
            "title": chat.title or str(chat.id),
            "link": inv_link,
            "target": None,
            "type": fsub_type,
            "status": status,
        }
        await update_fsub_channels(channels)

        safe_title = html.escape(str(chat.title or chat.id))
        safe_link = html.escape(str(inv_link))
        msg = (
            f"✅ <b>Successfully Configured FSub!</b>\n\n"
            f"📢 <b>Channel:</b> <code>{safe_title}</code>\n"
            f"🆔 <b>ID:</b> <code>{chat.id}</code>\n"
            f"🔗 <b>Link:</b> {safe_link}\n"
            f"⚙️ <b>Type:</b> <code>{'Join Request' if is_req else 'Normal'}</code>\n"
            f"🟢 <b>Status:</b> <code>{status.upper()}</code>"
        )
        return True, msg
    except ChatAdminRequired:
        return (
            False,
            "❌ <b>The bot is not an admin in that channel or lacks 'Invite Users' rights.</b>",
        )
    except Exception as e:
        return False, f"❌ <b>Error:</b> <code>{html.escape(str(e))}</code>"


@Client.on_message(filters.command("setfsub"), group=-15)
async def add_dynamic_fsub(bot: Client, message: Message):
    target_chat_id = await get_target_chat(bot, message)
    if not await verify_admin(bot, message, target_chat_id):
        return await safe_reply_text(
            message,
            "❌ <b>Unauthorized:</b> Admin only.",
            parse_mode=enums.ParseMode.HTML,
        )

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
        arg2 = message.command[2].strip().lower()
        is_req = arg2 in ["y", "yes", "req", "request", "true"]
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
                "❌ Cancel",
                callback_data="fsub_setup#cancel#0",
                style=BTN_DANGER,
            )
        ],
    ]

    safe_title = html.escape(str(chat.title or channel_id))
    ask_msg = await safe_reply_text(
        message,
        f"🎯 <b>Target:</b> <code>{safe_title}</code> (<code>{channel_id}</code>)\n\n"
        f"Do you want this to be a <b>Join Request</b> channel?\n\n"
        f"👉 <b>Click a button below</b> <i>(or reply with <code>y</code> for Yes / <code>n</code> for No)</i>:",
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
        if txt in ["y", "yes", "n", "no"]:
            is_req = txt in ["y", "yes"]
            try:
                await resp.delete()
            except Exception:
                pass
            _, result_text = await _finalize_setfsub(
                bot, message.chat.id, channel_id, is_req
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

    data = query.data
    if query.message and query.message.chat.id in _WAITING_REQUESTS:
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
        is_req = mode == "req"
        _, result_text = await _finalize_setfsub(
            bot, query.message.chat.id, channel_id, is_req
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
                f"✅ <b>All join requests purged successfully!</b> (<code>{count}</code> deleted)",
                parse_mode=enums.ParseMode.HTML,
            )


@Client.on_message(filters.command(["rmfsub", "remfsub", "delfsub"]), group=-15)
async def rem_fsub(bot: Client, message: Message):
    target_chat_id = await get_target_chat(bot, message)
    if not await verify_admin(bot, message, target_chat_id):
        return await safe_reply_text(
            message,
            "❌ <b>Unauthorized:</b> Admin only.",
            parse_mode=enums.ParseMode.HTML,
        )

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
    target_chat_id = await get_target_chat(bot, message)
    if not await verify_admin(bot, message, target_chat_id):
        return await safe_reply_text(
            message,
            "❌ <b>Unauthorized:</b> Admin only.",
            parse_mode=enums.ParseMode.HTML,
        )

    _INVITE_LINK_CACHE.clear()
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
        "ON (In-Line: Ch A ➔ Ch B ➔ Ch C, 1 Button + Auto-Send)"
        if config.get("rotation_enabled", True)
        else "OFF (Static Priority + Auto-Send)"
    )
    fsub_enabled = "🟢 ENABLED" if config.get("is_enabled", True) else "🔴 DISABLED"

    channels = list(channels_dict.items())
    if filter_status:
        channels = [(k, v) for k, v in channels if v.get("status") == filter_status]

    header = (
        f"📡 <b>Force Subscribe Status:</b> {fsub_enabled}\n"
        f"⚙️ <b>Queue Limit:</b> <code>{max_count if max_count > 0 else 'Unlimited'}</code>\n"
        f"🔄 <b>Auto-Rotation:</b> <code>{rot_status}</code>\n"
        f"⚡ <b>Verification Mode:</b> <code>100% Real-Time Live Telegram Check (Zero User DB Storage)</code>\n\n"
    )

    if not channels:
        return (
            header
            + f"❌ <i>No {title_prefix.lower()} ForceSub channels configured.</i>",
            None,
        )

    text = (
        header
        + f"📋 <b>{title_prefix} ForceSub Channels In Line ({len(channels)}):</b>\n\n"
    )
    buttons = []
    for idx, (cid, data) in enumerate(channels, 1):
        status_emoji = "🟢" if data.get("status", "active") == "active" else "🟡"
        req_type = "Join Request" if data.get("type") == "req" else "Normal"
        raw_title = str(data.get("title", "Unknown"))
        safe_title = html.escape(raw_title)
        active_link = html.escape(
            str(data.get("target") or data.get("link") or "No Link Generated")
        )
        text += (
            f"{idx}. {status_emoji} <b>{safe_title}</b>\n"
            f"├ ID: <code>{html.escape(str(cid))}</code>\n"
            f"├ Type: <code>{req_type}</code>\n"
            f"└ Link: {active_link}\n\n"
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
    target_chat_id = await get_target_chat(bot, message)
    if not await verify_admin(bot, message, target_chat_id):
        return await safe_reply_text(
            message,
            "❌ <b>Unauthorized:</b> Admin only.",
            parse_mode=enums.ParseMode.HTML,
        )

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
    target_chat_id = await get_target_chat(bot, message)
    if not await verify_admin(bot, message, target_chat_id):
        return await safe_reply_text(
            message,
            "❌ <b>Unauthorized:</b> Admin only.",
            parse_mode=enums.ParseMode.HTML,
        )

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
    target_chat_id = await get_target_chat(bot, message)
    if not await verify_admin(bot, message, target_chat_id):
        return await safe_reply_text(
            message,
            "❌ <b>Unauthorized:</b> Admin only.",
            parse_mode=enums.ParseMode.HTML,
        )

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
    target_chat_id = await get_target_chat(bot, message)
    if not await verify_admin(bot, message, target_chat_id):
        return await safe_reply_text(
            message,
            "❌ <b>Unauthorized:</b> Admin only.",
            parse_mode=enums.ParseMode.HTML,
        )

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
    await update_fsub_channels(channels)
    await safe_reply_text(
        message,
        f"✅ <b>Channel <code>{html.escape(cid)}</code> status updated to:</b> <code>{new_status.upper()}</code>",
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(filters.command("updatefsubtarget"), group=-15)
async def update_fsub_target_cmd(bot: Client, message: Message):
    target_chat_id = await get_target_chat(bot, message)
    if not await verify_admin(bot, message, target_chat_id):
        return await safe_reply_text(
            message,
            "❌ <b>Unauthorized:</b> Admin only.",
            parse_mode=enums.ParseMode.HTML,
        )

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
        None if target_link.lower() in ["off", "none", "reset"] else target_link
    )
    _INVITE_LINK_CACHE.pop(cid, None)
    await update_fsub_channels(channels)
    await safe_reply_text(
        message,
        f"✅ <b>Updated custom target link for <code>{html.escape(cid)}</code>!</b>",
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(filters.command("checkfsubusers"), group=-15)
async def check_fsub_users_cmd(bot: Client, message: Message):
    target_chat_id = await get_target_chat(bot, message)
    if not await verify_admin(bot, message, target_chat_id):
        return await safe_reply_text(
            message,
            "❌ <b>Unauthorized:</b> Admin only.",
            parse_mode=enums.ParseMode.HTML,
        )

    await safe_reply_text(
        message,
        "ℹ️ <b>Live Telegram Check Mode Active:</b>\n"
        "User records and join requests are <b>not</b> stored in MongoDB. "
        "Every file request is verified in real time against Telegram!",
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(filters.command("clearfsubusers"), group=-15)
async def clear_fsub_users_cmd(bot: Client, message: Message):
    target_chat_id = await get_target_chat(bot, message)
    if not await verify_admin(bot, message, target_chat_id):
        return await safe_reply_text(
            message,
            "❌ <b>Unauthorized:</b> Admin only.",
            parse_mode=enums.ParseMode.HTML,
        )

    await clear_all_fsub_users()
    await safe_reply_text(
        message,
        "🗑️ <b>Dropped any legacy ForceSub user collections from MongoDB!</b> (Zero user records are stored).",
        parse_mode=enums.ParseMode.HTML,
    )


# ============================================================
# 📊 JOIN REQUEST COMMANDS
# ============================================================
@Client.on_message(filters.command("totalrequests"), group=-15)
async def total_requests(bot: Client, message: Message):
    target_chat_id = await get_target_chat(bot, message)
    if not await verify_admin(bot, message, target_chat_id):
        return await safe_reply_text(
            message,
            "❌ <b>Unauthorized:</b> Admin only.",
            parse_mode=enums.ParseMode.HTML,
        )

    await safe_reply_text(
        message,
        "ℹ️ <b>Join requests are not saved in MongoDB.</b>\n"
        "The bot performs a real-time live check against Telegram every single time a user requests a file.",
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(filters.command("purgerequests"), group=-15)
async def purge_requests(bot: Client, message: Message):
    target_chat_id = await get_target_chat(bot, message)
    if not await verify_admin(bot, message, target_chat_id):
        return await safe_reply_text(
            message,
            "❌ <b>Unauthorized:</b> Admin only.",
            parse_mode=enums.ParseMode.HTML,
        )

    await clear_all_join_requests()
    await safe_reply_text(
        message,
        "✅ <b>Dropped any legacy join request collections from MongoDB!</b> (Zero join requests are stored in the database).",
        parse_mode=enums.ParseMode.HTML,
    )
