import asyncio
import inspect
import random
import time
from logging import ERROR, getLogger
from typing import Any, Dict, List, Optional

from motor.motor_asyncio import AsyncIOMotorClient
from pyrogram import Client, enums, filters
from pyrogram.errors import (
    ChatWriteForbidden,
    FloodWait,
    Forbidden,
    MessageIdInvalid,
    MessageNotModified,
    PeerIdInvalid,
    QueryIdInvalid,
    ReactionEmpty,
    ReactionInvalid,
    UserIsBlocked,
)
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

import info

logger = getLogger(__name__)
logger.setLevel(ERROR)

if not hasattr(info, "ENABLE_REACTION"):
    info.ENABLE_REACTION = True

DEFAULT_REACTIONS: List[str] = ["❤️"]

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

BTN_SUCCESS = None
BTN_DANGER = None
_SUPPORTS_BTN_STYLE = False

try:
    from pyrogram.enums import ButtonStyle

    if "style" in inspect.signature(InlineKeyboardButton.__init__).parameters:
        BTN_SUCCESS = getattr(ButtonStyle, "SUCCESS", None)
        BTN_DANGER = getattr(ButtonStyle, "DANGER", None)
        _SUPPORTS_BTN_STYLE = True
except (ImportError, ValueError, TypeError):
    pass


def create_btn(
    text: str,
    callback_data: str = "noop",
    style: Any = None,
) -> InlineKeyboardButton:
    """Creates a pure text-only callback InlineKeyboardButton (zero links)."""
    kwargs: Dict[str, Any] = {
        "text": str(text),
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
    kwargs: dict, supported_params: set, disable_preview: bool = True
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
    message: Message, text: str, **kwargs
) -> Optional[Message]:
    if not message:
        return None
    compat_kw = _prepare_compat_kwargs(kwargs, _REPLY_PARAMS)
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
    message: Message, text: str, **kwargs
) -> Optional[Message]:
    if not message:
        return None
    compat_kw = _prepare_compat_kwargs(kwargs, _EDIT_PARAMS)
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
# ⚙️ QUOTA-SAFE MULTI-DB STORAGE FOR REACTION SETTINGS
# ============================================================
_react_db = None
_BOOT_LOADED = False
# Skip chats where reactions are disabled/forbidden for 10 minutes to avoid wasted API calls
_RESTRICTED_REACT_CHATS: Dict[int, float] = {}

try:
    _DB_CLIENT = AsyncIOMotorClient(
        info.DATABASE_URI,
        serverSelectionTimeoutMS=4000,
        connectTimeoutMS=4000,
        socketTimeoutMS=8000,
    )
    _BOT_DB = _DB_CLIENT[info.DATABASE_NAME]
    _react_db = _BOT_DB["reaction_settings"]
except Exception as e:
    logger.error(f"Failed to init reaction_settings DB: {e}")


def _get_reaction_cols() -> List[Any]:
    cols = []
    if callable(get_writable_System_db):
        try:
            w_db = get_writable_System_db()
            if w_db is not None:
                cols.append(w_db["reaction_settings"])
        except Exception:
            pass
    if callable(get_all_healthy_read_dbs):
        try:
            for _, r_db in get_all_healthy_read_dbs():
                c = r_db["reaction_settings"]
                if c not in cols:
                    cols.append(c)
        except Exception:
            pass
    if _react_db is not None and _react_db not in cols:
        cols.append(_react_db)
    return cols


async def save_reaction_state(enabled: bool):
    info.ENABLE_REACTION = bool(enabled)
    payload = {"enabled": bool(enabled), "updated_at": time.time()}
    for col in _get_reaction_cols():
        try:
            await asyncio.wait_for(
                col.update_one({"_id": "config"}, {"$set": payload}, upsert=True),
                timeout=2.5,
            )
        except Exception:
            continue


@Client.on_message(filters.all, group=-996)
async def load_reaction_state_on_boot(client: Client, message: Message):
    global _BOOT_LOADED
    if _BOOT_LOADED:
        return
    _BOOT_LOADED = True

    best_doc = None
    best_ts = -1.0
    for col in _get_reaction_cols():
        try:
            doc = await asyncio.wait_for(col.find_one({"_id": "config"}), timeout=2.0)
            if doc and "enabled" in doc:
                doc_ts = float(doc.get("updated_at", 0.0) or 0.0)
                if best_doc is None or doc_ts >= best_ts:
                    best_doc = doc
                    best_ts = doc_ts
        except Exception:
            continue

    if best_doc is not None:
        info.ENABLE_REACTION = bool(best_doc["enabled"])


# ============================================================
# 👑 ADMIN VERIFICATION
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


async def is_user_admin(client: Client, message: Message) -> bool:
    if not message:
        return False
    admin_list = get_admin_list()
    if message.from_user and message.from_user.id in admin_list:
        return True
    if message.sender_chat and message.sender_chat.id in admin_list:
        return True
    if message.chat and message.chat.type in [
        enums.ChatType.GROUP,
        enums.ChatType.SUPERGROUP,
    ]:
        if message.sender_chat and message.sender_chat.id == message.chat.id:
            return True
        if message.from_user:
            try:
                member = await client.get_chat_member(
                    message.chat.id, message.from_user.id
                )
                return member.status in [
                    enums.ChatMemberStatus.ADMINISTRATOR,
                    enums.ChatMemberStatus.OWNER,
                ]
            except Exception:
                pass
    return False


# ============================================================
# 🎛️ REACTION COMMANDS & INTERACTIVE TOGGLE PANEL
# ============================================================
def _build_reaction_panel(enabled: bool) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                create_btn(
                    f"{'✅ ' if enabled else ''}Enable",
                    callback_data="react#on",
                    style=BTN_SUCCESS if enabled else None,
                ),
                create_btn(
                    f"{'🚫 ' if not enabled else ''}Disable",
                    callback_data="react#off",
                    style=BTN_DANGER if not enabled else None,
                ),
            ],
            [create_btn("🔐 Close", callback_data="react#close")],
        ]
    )


@Client.on_message(
    filters.command(["enablereaction", "disablereaction", "reaction", "reactions"])
    & filters.incoming,
    group=-2,
)
async def reaction_cmd_handler(client: Client, message: Message):
    if not await is_user_admin(client, message):
        return await safe_reply_text(
            message,
            "❌ <b>Unauthorized:</b> Admin access required.",
            parse_mode=enums.ParseMode.HTML,
        )

    cmd = message.command[0].lower()
    if cmd == "enablereaction":
        await save_reaction_state(True)
    elif cmd == "disablereaction":
        await save_reaction_state(False)
    elif len(message.command) > 1:
        arg = message.command[1].strip().lower()
        if arg in ("on", "enable", "true", "1", "yes"):
            await save_reaction_state(True)
        elif arg in ("off", "disable", "false", "0", "no"):
            await save_reaction_state(False)

    enabled = bool(getattr(info, "ENABLE_REACTION", True))
    status_str = "🟢 ENABLED" if enabled else "🔴 DISABLED"
    await safe_reply_text(
        message,
        f"❤️ <b>Auto-Reactions Status:</b> <code>{status_str}</code>",
        reply_markup=_build_reaction_panel(enabled),
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_callback_query(filters.regex(r"^react#"), group=-2)
async def reaction_toggle_callback(client: Client, query: CallbackQuery):
    uid = query.from_user.id if query.from_user else 0
    if uid not in get_admin_list():
        if query.message and query.message.chat.type in [
            enums.ChatType.GROUP,
            enums.ChatType.SUPERGROUP,
        ]:
            try:
                member = await client.get_chat_member(query.message.chat.id, uid)
                if member.status not in [
                    enums.ChatMemberStatus.ADMINISTRATOR,
                    enums.ChatMemberStatus.OWNER,
                ]:
                    return await safe_answer(query, "❌ Admin only!", show_alert=True)
            except Exception:
                return await safe_answer(query, "❌ Admin only!", show_alert=True)
        else:
            return await safe_answer(query, "❌ Admin only!", show_alert=True)

    action = query.data.split("#", 1)[1]
    if action == "close":
        await safe_answer(query, "Closed.")
        if query.message:
            try:
                await query.message.delete()
            except Exception:
                pass
        return

    new_state = action == "on"
    await save_reaction_state(new_state)
    status_str = "🟢 ENABLED" if new_state else "🔴 DISABLED"
    await safe_answer(query, f"Auto-Reactions: {status_str}")
    if query.message:
        await safe_edit_text(
            query.message,
            f"❤️ <b>Auto-Reactions Status:</b> <code>{status_str}</code>",
            reply_markup=_build_reaction_panel(new_state),
            parse_mode=enums.ParseMode.HTML,
        )


# ============================================================
# ⚡ NON-BLOCKING AUTO-REACTION LISTENER
# ============================================================
@Client.on_message(
    (filters.group | filters.private)
    & filters.incoming
    & ~filters.service
    & ~filters.bot,
    group=15,
)
async def auto_react_listener(client: Client, message: Message):
    if not getattr(info, "ENABLE_REACTION", True):
        return
    if getattr(info, "REPAIR_MODE", False):
        return
    if not message or not message.chat:
        return

    chat_id = message.chat.id
    now = time.time()
    if _RESTRICTED_REACT_CHATS.get(chat_id, 0.0) > now:
        return

    reactions = getattr(info, "REACTIONS", None) or DEFAULT_REACTIONS
    if not isinstance(reactions, (list, tuple)) or not reactions:
        reactions = DEFAULT_REACTIONS

    chosen_emoji = random.choice(reactions)
    try:
        await message.react(emoji=chosen_emoji)
    except (ReactionInvalid, ReactionEmpty, Forbidden, ChatWriteForbidden):
        if len(_RESTRICTED_REACT_CHATS) > 1000:
            _RESTRICTED_REACT_CHATS.clear()
        _RESTRICTED_REACT_CHATS[chat_id] = now + 600
    except (MessageIdInvalid, FloodWait):
        pass
    except Exception:
        try:
            await client.send_reaction(
                chat_id=chat_id,
                message_id=message.id,
                emoji=chosen_emoji,
            )
        except Exception:
            pass
