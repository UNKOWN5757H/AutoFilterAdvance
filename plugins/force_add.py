import asyncio
import inspect
import re
import time
from logging import ERROR, getLogger
from typing import Any, Dict, List, Optional, Set, Tuple

from motor.motor_asyncio import AsyncIOMotorClient
from pyrogram import Client, StopPropagation, enums, filters
from pyrogram.errors import (
    ChatWriteForbidden,
    Forbidden,
    MessageIdInvalid,
    MessageNotModified,
    PeerIdInvalid,
    QueryIdInvalid,
    UserIsBlocked,
)
from pyrogram.types import (
    CallbackQuery,
    ChatPermissions,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

import info

logger = getLogger(__name__)
logger.setLevel(ERROR)

# Strong reference set so sleeping auto-delete tasks are never garbage-collected
_BG_TASKS: Set[asyncio.Task] = set()

# ============================================================
# 🛡️ SAFE OPTIONAL IMPORTS & PYROGRAM v2.2.26 COMPATIBILITY
# ============================================================
try:
    from database.ia_filterdb import get_all_healthy_read_dbs, get_writable_System_db
except Exception:
    get_all_healthy_read_dbs = None
    get_writable_System_db = None

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
    callback_data: str = "noop",
    style: Any = None,
) -> InlineKeyboardButton:
    """Creates a pure text-only callback InlineKeyboardButton (zero links inside any button)."""
    kwargs: Dict[str, Any] = {
        "text": _clean_button_label(text),
        "callback_data": str(callback_data)[:64],
    }
    if _SUPPORTS_BTN_STYLE and style is not None:
        kwargs["style"] = style
    try:
        return InlineKeyboardButton(**kwargs)
    except Exception:
        kwargs.pop("style", None)
        return InlineKeyboardButton(**kwargs)


def _prepare_compat_kwargs(
    kwargs: dict, supported_params: set, disable_preview: Optional[bool] = True
) -> dict:
    clean_kw = dict(kwargs)
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


async def safe_answer(
    query: CallbackQuery, text: Optional[str] = None, show_alert: bool = False
):
    if not query:
        return
    try:
        if text is not None:
            await query.answer(str(text)[:200], show_alert=show_alert)
        else:
            await query.answer(show_alert=show_alert)
    except (QueryIdInvalid, Exception):
        pass


# ============================================================
# ⚙️ QUOTA-SAFE MULTI-DB ENGINE & FAST IN-MEMORY CACHES
# ============================================================
fa_config_db = None
fa_settings_sync_db = None
fa_users_db = None
_active_db = None
_std_conn_db = None

try:
    _DB_CLIENT = AsyncIOMotorClient(
        info.DATABASE_URI,
        serverSelectionTimeoutMS=4000,
        connectTimeoutMS=4000,
        socketTimeoutMS=8000,
    )
    _BOT_DB = _DB_CLIENT[info.DATABASE_NAME]
    fa_config_db = _BOT_DB["forceadd_config"]
    fa_settings_sync_db = _BOT_DB["force_add_settings"]
    fa_users_db = _BOT_DB["forceadd_users"]
    _active_db = _BOT_DB["active_connections"]
    _std_conn_db = _BOT_DB["CONNECTION"]
except Exception as e:
    logger.error(f"Failed to init Force Add DB: {e}")

_FA_CONFIG_CACHE: Dict[int, Tuple[float, Dict[str, Any]]] = {}
_ADMIN_STATUS_CACHE: Dict[Tuple[int, int], Tuple[float, bool]] = {}


def _get_writable_col(col_name: str, fallback_col: Any):
    if callable(get_writable_System_db):
        try:
            w_db = get_writable_System_db()
            if w_db is not None:
                return w_db[col_name]
        except Exception:
            pass
    return fallback_col


def invalidate_fa_cache(chat_id: int):
    _FA_CONFIG_CACHE.pop(int(chat_id), None)


async def set_fa_config(
    chat_id: int,
    limit: Optional[int] = None,
    mode: Optional[str] = None,
    enabled: Optional[bool] = None,
):
    cid = int(chat_id)
    cur = await get_fa_config(cid, force_refresh=True)

    new_limit = cur["limit"] if limit is None else int(limit)
    new_mode = cur["mode"] if mode is None else str(mode)
    if enabled is None:
        new_enabled = new_limit > 0
    else:
        new_enabled = bool(enabled)
        if new_enabled and new_limit <= 0:
            new_limit = int(cur.get("saved_limit") or 5)

    saved_limit = new_limit if new_limit > 0 else int(cur.get("saved_limit") or 5)

    payload = {
        "chat_id": cid,
        "limit": new_limit if new_enabled else 0,
        "saved_limit": saved_limit,
        "mode": new_mode,
        "enabled": new_enabled,
        "is_enabled": new_enabled,
    }

    for col_name, fallback_col in (
        ("forceadd_config", fa_config_db),
        ("force_add_settings", fa_settings_sync_db),
    ):
        col = _get_writable_col(col_name, fallback_col)
        if col is not None:
            try:
                await asyncio.wait_for(
                    col.update_one({"chat_id": cid}, {"$set": payload}, upsert=True),
                    timeout=2.5,
                )
            except Exception as e:
                logger.error(f"set_fa_config ({col_name}) error: {e}")

    _FA_CONFIG_CACHE[cid] = (time.time(), payload)


async def get_fa_config(chat_id: int, force_refresh: bool = False) -> Dict[str, Any]:
    cid = int(chat_id)
    now = time.time()
    if not force_refresh and cid in _FA_CONFIG_CACHE:
        ts, cached_doc = _FA_CONFIG_CACHE[cid]
        if now - ts < 60:
            return cached_doc

    doc = None
    sync_doc = None
    cfg_col = _get_writable_col("forceadd_config", fa_config_db)
    sync_col = _get_writable_col("force_add_settings", fa_settings_sync_db)

    if cfg_col is not None:
        try:
            doc = await asyncio.wait_for(cfg_col.find_one({"chat_id": cid}), timeout=2.0)
        except Exception:
            doc = None

    if sync_col is not None:
        try:
            sync_doc = await asyncio.wait_for(
                sync_col.find_one({"chat_id": cid}), timeout=2.0
            )
        except Exception:
            sync_doc = None

    if doc or sync_doc:
        base = doc or sync_doc or {}
        limit_val = int(base.get("limit", 0))
        saved_limit = int(
            base.get("saved_limit") or (limit_val if limit_val > 0 else 5)
        )
        mode_val = str(base.get("mode", "all"))

        if sync_doc and "enabled" in sync_doc:
            is_en = bool(sync_doc["enabled"])
        elif "enabled" in base:
            is_en = bool(base["enabled"])
        else:
            is_en = limit_val > 0

        effective_limit = (limit_val if limit_val > 0 else saved_limit) if is_en else 0
        res = {
            "limit": effective_limit,
            "saved_limit": saved_limit,
            "mode": mode_val,
            "enabled": is_en and effective_limit > 0,
        }
        _FA_CONFIG_CACHE[cid] = (now, res)
        return res

    default_res = {"limit": 0, "saved_limit": 5, "mode": "all", "enabled": False}
    _FA_CONFIG_CACHE[cid] = (now, default_res)
    return default_res


async def add_user_score(chat_id: int, user_id: int, count: int):
    col = _get_writable_col("forceadd_users", fa_users_db)
    if col is not None and count > 0:
        timestamps = [int(time.time())] * count
        try:
            await asyncio.wait_for(
                col.update_one(
                    {"chat_id": int(chat_id), "user_id": int(user_id)},
                    {"$push": {"adds": {"$each": timestamps}}},
                    upsert=True,
                ),
                timeout=2.5,
            )
        except Exception:
            pass


async def get_user_score(chat_id: int, user_id: int) -> int:
    col = _get_writable_col("forceadd_users", fa_users_db)
    if col is not None:
        try:
            doc = await asyncio.wait_for(
                col.find_one({"chat_id": int(chat_id), "user_id": int(user_id)}),
                timeout=2.0,
            )
            if doc and "adds" in doc:
                return len(doc["adds"])
        except Exception:
            pass
    return 0


async def mark_new_user(chat_id: int, user_id: int):
    col = _get_writable_col("forceadd_users", fa_users_db)
    if col is not None:
        try:
            await asyncio.wait_for(
                col.update_one(
                    {"chat_id": int(chat_id), "user_id": int(user_id)},
                    {"$set": {"is_new": True}},
                    upsert=True,
                ),
                timeout=2.0,
            )
        except Exception:
            pass


async def is_new_user(chat_id: int, user_id: int) -> bool:
    col = _get_writable_col("forceadd_users", fa_users_db)
    if col is not None:
        try:
            doc = await asyncio.wait_for(
                col.find_one({"chat_id": int(chat_id), "user_id": int(user_id)}),
                timeout=2.0,
            )
            return bool(doc.get("is_new", False)) if doc else False
        except Exception:
            pass
    return False


# ============================================================
# 🛡️ SAFE CHAT PERMISSIONS BUILDER & AUTO-DELETE TASK TRACKER
# ============================================================
_VALID_PERM_PARAMS = set(
    inspect.signature(ChatPermissions.__init__).parameters.keys()
) - {"self"}


def build_chat_permissions(can_send: bool) -> ChatPermissions:
    desired = {
        "can_send_messages": can_send,
        "can_send_media_messages": can_send,
        "can_send_other_messages": can_send,
        "can_add_web_page_previews": can_send,
        "can_send_audios": can_send,
        "can_send_documents": can_send,
        "can_send_photos": can_send,
        "can_send_videos": can_send,
        "can_send_video_notes": can_send,
        "can_send_voice_notes": can_send,
        "can_send_polls": can_send,
        "can_invite_users": True,
    }
    return ChatPermissions(
        **{k: v for k, v in desired.items() if k in _VALID_PERM_PARAMS}
    )


async def _delete_later(msg: Message, delay: int):
    await asyncio.sleep(delay)
    try:
        await msg.delete()
    except Exception:
        pass


def _schedule_delete(msg: Optional[Message], delay: int):
    if not msg or delay <= 0:
        return
    t = asyncio.create_task(_delete_later(msg, delay))
    _BG_TASKS.add(t)
    t.add_done_callback(_BG_TASKS.discard)


# ============================================================
# 🛡️ ANTI-SPAM WARNING CACHE
# ============================================================
class TTLCache:
    def __init__(self, maxsize: int = 5000, ttl: int = 60):
        self._data: Dict[str, float] = {}
        self._maxsize = maxsize
        self._ttl = ttl

    def is_rate_limited(self, key: str) -> bool:
        now = time.time()
        if key in self._data and now < self._data[key]:
            return True
        expired = [k for k, exp in list(self._data.items()) if now >= exp]
        for k in expired:
            self._data.pop(k, None)
        if len(self._data) >= self._maxsize:
            self._data.clear()
        self._data[key] = now + self._ttl
        return False


WARN_CACHE = TTLCache(ttl=60)


# ============================================================
# 👑 SMART AUTHORIZATION & CACHED ADMIN CHECK
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


async def get_active_connected_group(user_id: int) -> Optional[int]:
    uid_str = str(user_id)
    try:
        from plugins.pm_filter import get_active_connection

        conn = await get_active_connection(uid_str)
        if conn:
            return int(conn)
    except Exception:
        pass

    for col, q_key, f_key in (
        (_active_db, "user_id", "group_id"),
        (_std_conn_db, "_id", "active_group"),
    ):
        if col is not None:
            try:
                doc = await asyncio.wait_for(
                    col.find_one({q_key: uid_str}), timeout=2.0
                )
                if doc and doc.get(f_key):
                    return int(doc[f_key])
            except Exception:
                continue
    return None


async def resolve_target_group(message: Message) -> Optional[int]:
    if message.chat.type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
        return int(message.chat.id)
    if message.from_user:
        return await get_active_connected_group(message.from_user.id)
    return None


async def is_user_admin(
    client: Client,
    message: Message,
    target_chat_id: Optional[int] = None,
    use_cache: bool = False,
) -> bool:
    if not message:
        return False
    admin_list = get_admin_list()

    if message.from_user and message.from_user.id in admin_list:
        return True
    if message.sender_chat and message.sender_chat.id in admin_list:
        return True

    check_cid = target_chat_id or (
        message.chat.id
        if message.chat
        and message.chat.type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]
        else None
    )

    if check_cid:
        if message.sender_chat and message.sender_chat.id == check_cid:
            return True
        if message.from_user:
            cache_key = (int(check_cid), int(message.from_user.id))
            now = time.time()
            if use_cache and cache_key in _ADMIN_STATUS_CACHE:
                exp, cached_flag = _ADMIN_STATUS_CACHE[cache_key]
                if now < exp:
                    return cached_flag
            try:
                member = await client.get_chat_member(
                    int(check_cid), message.from_user.id
                )
                is_adm = member.status in [
                    enums.ChatMemberStatus.ADMINISTRATOR,
                    enums.ChatMemberStatus.OWNER,
                ]
                if len(_ADMIN_STATUS_CACHE) > 5000:
                    _ADMIN_STATUS_CACHE.clear()
                _ADMIN_STATUS_CACHE[cache_key] = (now + 120, is_adm)
                return is_adm
            except Exception:
                pass

    return False


async def is_callback_user_admin(
    client: Client, query: CallbackQuery, chat_id: Optional[int] = None
) -> bool:
    if not query or not query.from_user:
        return False
    user_id = query.from_user.id
    if user_id in get_admin_list():
        return True

    target_chat_id = chat_id or (query.message.chat.id if query.message else None)
    if target_chat_id:
        try:
            member = await client.get_chat_member(int(target_chat_id), user_id)
            return member.status in [
                enums.ChatMemberStatus.ADMINISTRATOR,
                enums.ChatMemberStatus.OWNER,
            ]
        except Exception:
            pass
    return False


async def _resolve_admin_group(
    bot: Client, message: Message, require_admin: bool = True
) -> Optional[int]:
    grp_id = await resolve_target_group(message)
    if not grp_id:
        await safe_reply_text(
            message,
            "⚠️ <b>No active group connected!</b>\nUse <code>/connect &lt;group_id&gt;</code> in PM or run this command inside your group.",
            parse_mode=enums.ParseMode.HTML,
        )
        return None
    if require_admin and not await is_user_admin(bot, message, target_chat_id=grp_id):
        await safe_reply_text(
            message,
            "❌ <b>Unauthorized:</b> Group Admin access required.",
            parse_mode=enums.ParseMode.HTML,
        )
        return None
    return grp_id


# ============================================================
# ⚙️ CONFIGURATION COMMANDS (GROUP & CONNECTED PM)
# ============================================================
@Client.on_message(filters.command("setforceadd") & filters.incoming, group=-2)
async def set_force_add(bot: Client, message: Message):
    grp_id = await _resolve_admin_group(bot, message, require_admin=True)
    if not grp_id:
        return

    if len(message.command) < 2:
        return await safe_reply_text(
            message,
            "⚙️ <b>Usage:</b> <code>/setforceadd &lt;number&gt;</code>\n"
            "<b>Example:</b> <code>/setforceadd 5</code>",
            parse_mode=enums.ParseMode.HTML,
        )

    try:
        limit = int(message.command[1])
        if limit < 0:
            raise ValueError
    except ValueError:
        return await safe_reply_text(
            message,
            "❌ <b>Please provide a valid positive number.</b>",
            parse_mode=enums.ParseMode.HTML,
        )

    if limit == 0:
        await set_fa_config(grp_id, limit=0, mode="all", enabled=False)
        return await safe_reply_text(
            message,
            f"🗑️ <b>Force Add disabled for group <code>{grp_id}</code>.</b>",
            parse_mode=enums.ParseMode.HTML,
        )

    kb = InlineKeyboardMarkup(
        [
            [
                create_btn(
                    "👥 Force Add for ALL Members",
                    callback_data=f"fa_set_{limit}_all_{grp_id}",
                    style=BTN_PRIMARY,
                )
            ],
            [
                create_btn(
                    "🆕 Force Add for ONLY NEW Members",
                    callback_data=f"fa_set_{limit}_new_{grp_id}",
                    style=BTN_SUCCESS,
                )
            ],
        ]
    )

    await safe_reply_text(
        message,
        f"🎯 <b>Target Group:</b> <code>{grp_id}</code>\n"
        f"🔢 <b>Required Invites:</b> <code>{limit}</code>\n\n"
        "<b>Who should this requirement apply to?</b>",
        reply_markup=kb,
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_callback_query(filters.regex(r"^fa_set_(\d+)_([a-z]+)_(-?\d+)$"), group=-2)
async def set_forceadd_callback(bot: Client, query: CallbackQuery):
    limit = int(query.matches[0].group(1))
    mode = query.matches[0].group(2)
    grp_id = int(query.matches[0].group(3))

    if not await is_callback_user_admin(bot, query, chat_id=grp_id):
        return await safe_answer(
            query,
            "❌ Unauthorized: Only group admins can configure Force Add!",
            show_alert=True,
        )

    await set_fa_config(grp_id, limit=limit, mode=mode, enabled=True)
    mode_text = (
        "ALL MEMBERS" if mode == "all" else "ONLY NEW MEMBERS (who join from now on)"
    )

    await safe_answer(query, "✅ Force Add Configured!")
    await safe_edit_text(
        query.message,
        f"✅ <b>Force Add Configured Successfully!</b>\n\n"
        f"🏘️ <b>Group ID:</b> <code>{grp_id}</code>\n"
        f"🔢 <b>Limit:</b> <code>{limit} members</code>\n"
        f"🎯 <b>Target:</b> <code>{mode_text}</code>\n"
        f"<i>(Engine is now 100% Active)</i>",
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(filters.command("remforceadd") & filters.incoming, group=-2)
async def remove_force_add(bot: Client, message: Message):
    grp_id = await _resolve_admin_group(bot, message, require_admin=True)
    if not grp_id:
        return

    await set_fa_config(grp_id, limit=0, mode="all", enabled=False)
    await safe_reply_text(
        message,
        f"🗑️ <b>Force Add requirement has been completely removed for <code>{grp_id}</code>.</b>",
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(filters.command("getforceadd") & filters.incoming, group=-2)
async def get_force_add(bot: Client, message: Message):
    grp_id = await _resolve_admin_group(bot, message, require_admin=False)
    if not grp_id:
        return

    settings = await get_fa_config(grp_id, force_refresh=True)
    if settings["limit"] == 0 or not settings.get("enabled", False):
        await safe_reply_text(
            message,
            f"ℹ️ <b>Force Add is currently DISABLED in group <code>{grp_id}</code>.</b>",
            parse_mode=enums.ParseMode.HTML,
        )
    else:
        target = "Everyone" if settings["mode"] == "all" else "Only New Members"
        await safe_reply_text(
            message,
            f"ℹ️ <b>Force Add Configuration (<code>{grp_id}</code>):</b>\n\n"
            f"🔢 <b>Required Adds:</b> <code>{settings['limit']}</code> members\n"
            f"🎯 <b>Applies to:</b> <code>{target}</code>",
            parse_mode=enums.ParseMode.HTML,
        )


# ============================================================
# 📊 LEADERBOARD & STATS LOGIC (BATCHED USER LOOKUP)
# ============================================================
async def generate_leaderboard(
    bot: Client,
    message: Message,
    title: str,
    time_limit_seconds: Optional[int] = None,
):
    grp_id = await _resolve_admin_group(bot, message, require_admin=False)
    if not grp_id:
        return

    col = _get_writable_col("forceadd_users", fa_users_db)
    if col is None:
        return await safe_reply_text(
            message, "❌ <b>Database Error.</b>", parse_mode=enums.ParseMode.HTML
        )

    pipeline: List[Dict[str, Any]] = [{"$match": {"chat_id": int(grp_id)}}]

    if time_limit_seconds:
        cutoff = int(time.time()) - time_limit_seconds
        pipeline.extend(
            [
                {
                    "$project": {
                        "user_id": 1,
                        "valid_adds": {
                            "$filter": {
                                "input": {"$ifNull": ["$adds", []]},
                                "as": "timestamp",
                                "cond": {"$gte": ["$$timestamp", cutoff]},
                            }
                        },
                    }
                },
                {
                    "$project": {
                        "user_id": 1,
                        "score": {"$size": {"$ifNull": ["$valid_adds", []]}},
                    }
                },
            ]
        )
    else:
        pipeline.append(
            {"$project": {"user_id": 1, "score": {"$size": {"$ifNull": ["$adds", []]}}}}
        )

    pipeline.extend(
        [{"$match": {"score": {"$gt": 0}}}, {"$sort": {"score": -1}}, {"$limit": 10}]
    )

    try:
        top_users = await asyncio.wait_for(
            col.aggregate(pipeline).to_list(length=10), timeout=4.0
        )
    except Exception:
        top_users = []

    if not top_users:
        return await safe_reply_text(
            message,
            f"📊 <b>{title}</b> (<code>{grp_id}</code>)\n\nNo members have added anyone yet!",
            parse_mode=enums.ParseMode.HTML,
        )

    # Single batched API call for all top 10 users
    uids = [d["user_id"] for d in top_users]
    user_map: Dict[int, str] = {}
    try:
        users_objs = await bot.get_users(uids)
        if not isinstance(users_objs, list):
            users_objs = [users_objs]
        for u in users_objs:
            if u:
                user_map[u.id] = u.mention
    except Exception:
        pass

    lines = [f"📊 <b>{title} (Top 10)</b>\n🆔 <b>Group:</b> <code>{grp_id}</code>\n"]
    for i, data in enumerate(top_users, 1):
        uid, score = data["user_id"], data["score"]
        user_name = user_map.get(uid, f"User <code>{uid}</code>")
        lines.append(f"<b>{i}.</b> {user_name} ➔ <code>{score}</code> added")

    await safe_reply_text(
        message,
        "\n".join(lines),
        disable_web_page_preview=True,
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(filters.command("topaddall") & filters.incoming, group=-2)
async def top_add_all(bot: Client, message: Message):
    await generate_leaderboard(bot, message, "All-Time Top Adders", None)


@Client.on_message(filters.command("topadd24") & filters.incoming, group=-2)
async def top_add_24(bot: Client, message: Message):
    await generate_leaderboard(bot, message, "Top Adders (Past 24 Hours)", 86400)


@Client.on_message(filters.command("topadd7") & filters.incoming, group=-2)
async def top_add_7(bot: Client, message: Message):
    await generate_leaderboard(bot, message, "Top Adders (Past 7 Days)", 604800)


@Client.on_message(filters.command("resetadddaily") & filters.incoming, group=-2)
async def reset_add_daily(bot: Client, message: Message):
    grp_id = await _resolve_admin_group(bot, message, require_admin=True)
    if not grp_id:
        return

    col = _get_writable_col("forceadd_users", fa_users_db)
    if col is not None:
        cutoff = int(time.time()) - 86400
        await col.update_many(
            {"chat_id": int(grp_id)}, {"$pull": {"adds": {"$lt": cutoff}}}
        )
        await safe_reply_text(
            message,
            f"♻️ <b>Daily limits reset for <code>{grp_id}</code>!</b> Leaderboards for past 24h have been wiped.",
            parse_mode=enums.ParseMode.HTML,
        )


@Client.on_message(filters.command("resetadd") & filters.incoming, group=-2)
async def reset_all_adds(bot: Client, message: Message):
    grp_id = await _resolve_admin_group(bot, message, require_admin=True)
    if not grp_id:
        return

    col = _get_writable_col("forceadd_users", fa_users_db)
    if col is not None:
        await col.update_many({"chat_id": int(grp_id)}, {"$set": {"adds": []}})
        await safe_reply_text(
            message,
            f"💥 <b>TOTAL RESET for <code>{grp_id}</code>!</b> All members' scores are now 0.",
            parse_mode=enums.ParseMode.HTML,
        )


@Client.on_message(filters.command("myadds") & filters.incoming, group=-2)
async def my_adds(bot: Client, message: Message):
    if not message.from_user:
        return
    grp_id = await _resolve_admin_group(bot, message, require_admin=False)
    if not grp_id:
        return

    settings = await get_fa_config(grp_id)
    current_adds = await get_user_score(grp_id, message.from_user.id)

    if settings["limit"] == 0:
        return await safe_reply_text(
            message,
            f"ℹ️ <b>Force Add is not active in <code>{grp_id}</code>.</b>\n"
            f"👥 <b>Your Total Invites:</b> <code>{current_adds}</code>",
            parse_mode=enums.ParseMode.HTML,
        )

    if current_adds >= settings["limit"]:
        await safe_reply_text(
            message,
            f"✅ You have added <b>{current_adds}</b> members. You are cleared to chat freely!",
            parse_mode=enums.ParseMode.HTML,
        )
    else:
        await safe_reply_text(
            message,
            f"⚠️ You have added <b>{current_adds}/{settings['limit']}</b> members.",
            parse_mode=enums.ParseMode.HTML,
        )


# ============================================================
# 🎯 THE ENGINE: TRACKER & HIGH-SPEED ENFORCER
# ============================================================
@Client.on_message(filters.new_chat_members & filters.group, group=10)
async def track_added_members(bot: Client, message: Message):
    settings = await get_fa_config(message.chat.id)
    if settings["limit"] == 0:
        return

    for u in message.new_chat_members:
        if not u.is_bot:
            await mark_new_user(message.chat.id, u.id)

    if not message.from_user:
        return

    adder_id = message.from_user.id
    added_others = [
        u for u in message.new_chat_members if u.id != adder_id and not u.is_bot
    ]
    if not added_others:
        return

    await add_user_score(message.chat.id, adder_id, len(added_others))
    current_adds = await get_user_score(message.chat.id, adder_id)

    if current_adds >= settings["limit"]:
        try:
            await bot.restrict_chat_member(
                chat_id=message.chat.id,
                user_id=adder_id,
                permissions=build_chat_permissions(can_send=True),
            )
            msg = await bot.send_message(
                chat_id=message.chat.id,
                text=(
                    f"🎉 <b>Congratulations {message.from_user.mention}!</b>\n\n"
                    f"You've added <b>{current_adds}</b> members and met the group requirement. "
                    f"<b>You can now chat freely!</b>"
                ),
                parse_mode=enums.ParseMode.HTML,
            )
            _schedule_delete(msg, 15)
        except Exception:
            pass


@Client.on_message(
    filters.group
    & ~filters.service
    & ~filters.new_chat_members
    & ~filters.left_chat_member,
    group=-1,
)
async def enforce_force_add(bot: Client, message: Message):
    user = message.from_user
    if not user or user.is_bot or not message.chat:
        return

    # 1. Check 0ms RAM config cache FIRST before making any Telegram API calls!
    chat_id, user_id = message.chat.id, user.id
    settings = await get_fa_config(chat_id)
    limit = settings["limit"]
    if limit == 0:
        return

    text = message.text or message.caption
    if text and text.startswith("/"):
        return

    # 2. Cached admin check (avoids calling get_chat_member on every message)
    if await is_user_admin(bot, message, target_chat_id=chat_id, use_cache=True):
        return

    if settings["mode"] == "new" and not await is_new_user(chat_id, user_id):
        return

    current_adds = await get_user_score(chat_id, user_id)
    if current_adds < limit:
        try:
            await message.delete()
        except Exception:
            pass

        try:
            await bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=user_id,
                permissions=build_chat_permissions(can_send=False),
            )
        except Exception:
            pass

        warn_key = f"warn_{chat_id}_{user_id}"
        if not WARN_CACHE.is_rate_limited(warn_key):
            try:
                warn_msg = await bot.send_message(
                    chat_id=chat_id,
                    text=(
                        f"🛑 <b>Hold on, {user.mention}!</b>\n\n"
                        f"You must add <b>{limit - current_adds} more member(s)</b> to this group before you can send messages.\n\n"
                        f"🔇 <b>You have been restricted from messaging.</b>"
                    ),
                    reply_markup=InlineKeyboardMarkup(
                        [
                            [
                                create_btn(
                                    "📊 How many users have I added?",
                                    callback_data="forceadd_check",
                                    style=BTN_PRIMARY,
                                )
                            ]
                        ]
                    ),
                    parse_mode=enums.ParseMode.HTML,
                )
                _schedule_delete(warn_msg, 60)
            except Exception as e:
                logger.error(f"ForceAdd warning error: {e}")

        raise StopPropagation


@Client.on_callback_query(filters.regex(r"^forceadd_check$"), group=-2)
async def check_adds_button(bot: Client, query: CallbackQuery):
    if not query.message or not query.from_user:
        return
    chat_id, user_id = query.message.chat.id, query.from_user.id
    settings = await get_fa_config(chat_id)

    if settings["limit"] == 0:
        return await safe_answer(
            query, "Force Add is not active in this group.", show_alert=True
        )

    current_adds = await get_user_score(chat_id, user_id)
    if current_adds >= settings["limit"]:
        try:
            await bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=user_id,
                permissions=build_chat_permissions(can_send=True),
            )
        except Exception:
            pass
        await safe_answer(
            query,
            f"✅ You have added {current_adds} members.\nYou are cleared to chat freely!",
            show_alert=True,
        )
    else:
        await safe_answer(
            query,
            f"⚠️ You have added {current_adds}/{settings['limit']} members.\n\nYou need {settings['limit'] - current_adds} more to chat.",
            show_alert=True,
        )
