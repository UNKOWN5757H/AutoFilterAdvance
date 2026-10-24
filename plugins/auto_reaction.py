import asyncio
import inspect
import random
from logging import ERROR, getLogger
from typing import List, Optional

from motor.motor_asyncio import AsyncIOMotorClient
from pyrogram import Client, enums, filters
from pyrogram.errors import (
    ChatWriteForbidden,
    FloodWait,
    Forbidden,
    MessageIdInvalid,
    MessageNotModified,
    PeerIdInvalid,
    ReactionEmpty,
    ReactionInvalid,
    UserIsBlocked,
)
from pyrogram.types import Message

import info

logger = getLogger(__name__)
logger.setLevel(ERROR)

# Default reaction flag if not in info.py
if not hasattr(info, "ENABLE_REACTION"):
    info.ENABLE_REACTION = True

DEFAULT_REACTIONS: List[str] = [
    "❤️",
]

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
) -> Optional[Message]:
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
    except (ChatWriteForbidden, Forbidden, UserIsBlocked, PeerIdInvalid):
        return None


# ============================================================
# ⚙️ MONGODB STORAGE FOR REACTION SETTINGS
# ============================================================
_react_db = None
_BOOT_LOADED = False

try:
    _DB_CLIENT = AsyncIOMotorClient(info.DATABASE_URI)
    _BOT_DB = _DB_CLIENT[info.DATABASE_NAME]
    _react_db = _BOT_DB["reaction_settings"]
except Exception as e:
    logger.error(f"Failed to init reaction_settings DB: {e}")


async def save_reaction_state(enabled: bool):
    info.ENABLE_REACTION = bool(enabled)
    if _react_db is not None:
        try:
            await _react_db.update_one(
                {"_id": "config"},
                {"$set": {"enabled": bool(enabled)}},
                upsert=True,
            )
        except Exception:
            pass


@Client.on_message(filters.all, group=-996)
async def load_reaction_state_on_boot(client: Client, message: Message):
    global _BOOT_LOADED
    if _BOOT_LOADED:
        return
    _BOOT_LOADED = True
    if _react_db is not None:
        try:
            doc = await _react_db.find_one({"_id": "config"})
            if doc and "enabled" in doc:
                info.ENABLE_REACTION = bool(doc["enabled"])
        except Exception:
            pass


# ============================================================
# 👑 ADMIN CHECKER
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
# 🎛️ REACTION COMMANDS (/enablereaction, /disablereaction)
# ============================================================
@Client.on_message(filters.command("enablereaction") & filters.incoming, group=-2)
async def enable_reaction_cmd(client: Client, message: Message):
    if not await is_user_admin(client, message):
        return await safe_reply_text(
            message,
            "❌ <b>Unauthorized:</b> Admin access required.",
            parse_mode=enums.ParseMode.HTML,
        )
    await save_reaction_state(True)
    await safe_reply_text(
        message,
        "❤️ <b>Auto-Reactions have been ENABLED globally!</b>",
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(filters.command("disablereaction") & filters.incoming, group=-2)
async def disable_reaction_cmd(client: Client, message: Message):
    if not await is_user_admin(client, message):
        return await safe_reply_text(
            message,
            "❌ <b>Unauthorized:</b> Admin access required.",
            parse_mode=enums.ParseMode.HTML,
        )
    await save_reaction_state(False)
    await safe_reply_text(
        message,
        "🚫 <b>Auto-Reactions have been DISABLED globally!</b>",
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

    reactions = getattr(info, "REACTIONS", None) or DEFAULT_REACTIONS
    if not isinstance(reactions, (list, tuple)) or not reactions:
        reactions = DEFAULT_REACTIONS

    chosen_emoji = random.choice(reactions)
    try:
        await message.react(emoji=chosen_emoji)
    except (ReactionInvalid, ReactionEmpty, MessageIdInvalid, Forbidden, FloodWait):
        pass
    except Exception:
        try:
            await client.send_reaction(
                chat_id=message.chat.id,
                message_id=message.id,
                emoji=chosen_emoji,
            )
        except Exception:
            pass
