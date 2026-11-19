import asyncio
import html
import inspect
import io
import math
import re
from datetime import datetime, timezone
from logging import ERROR, getLogger
from typing import Any, Dict, List, Optional, Tuple

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
    UserIsBlocked,
)
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

import info
from database.users_chats_db import db as _db

logger = getLogger(__name__)
logger.setLevel(ERROR)

# ============================================================
# 🛡️ PYROGRAM v2.2.26 COMPATIBILITY & TEXT-ONLY BUTTON BUILDER
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
        except (MessageNotModified, MessageIdInvalid, ChatWriteForbidden, Forbidden):
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
# 🗄️ TIMEOUT-SAFE DATABASE CURSOR & FALLBACK ENGINE
# ============================================================
_RAW_DB = None
try:
    _DB_CLIENT = AsyncIOMotorClient(
        info.DATABASE_URI,
        serverSelectionTimeoutMS=4000,
        connectTimeoutMS=4000,
        socketTimeoutMS=8000,
    )
    _RAW_DB = _DB_CLIENT[info.DATABASE_NAME]
except Exception as e:
    logger.error(f"Failed to init fallback DB client in channel.py: {e}")


async def _consume_cursor_or_iterable(obj: Any) -> List[dict]:
    if obj is None:
        return []
    if inspect.isawaitable(obj):
        obj = await obj
    if obj is None:
        return []
    if hasattr(obj, "to_list"):
        return await obj.to_list(length=None)
    if hasattr(obj, "__aiter__"):
        return [item async for item in obj]
    if isinstance(obj, (list, tuple, set)):
        return list(obj)
    return []


async def fetch_all_chats_safely() -> List[dict]:
    try:
        if hasattr(_db, "get_all_chats"):
            res = await asyncio.wait_for(
                _consume_cursor_or_iterable(_db.get_all_chats()), timeout=8.0
            )
            if res:
                return res
    except Exception as e:
        logger.error(f"_db.get_all_chats error: {e}")

    try:
        if hasattr(_db, "grp"):
            res = await asyncio.wait_for(
                _consume_cursor_or_iterable(_db.grp.find({})), timeout=8.0
            )
            if res:
                return res
    except Exception:
        pass

    if _RAW_DB is not None:
        for col_name in ("groups", "chats", "grp", "Chat"):
            try:
                docs = await asyncio.wait_for(
                    _RAW_DB[col_name].find({}).to_list(length=None), timeout=6.0
                )
                if docs:
                    return docs
            except Exception:
                continue
    return []


async def fetch_all_users_safely() -> List[dict]:
    try:
        if hasattr(_db, "get_all_users"):
            res = await asyncio.wait_for(
                _consume_cursor_or_iterable(_db.get_all_users()), timeout=10.0
            )
            if res:
                return res
    except Exception as e:
        logger.error(f"_db.get_all_users error: {e}")

    try:
        if hasattr(_db, "col"):
            res = await asyncio.wait_for(
                _consume_cursor_or_iterable(_db.col.find({})), timeout=10.0
            )
            if res:
                return res
    except Exception:
        pass

    if _RAW_DB is not None:
        for col_name in ("users", "user", "col", "User"):
            try:
                docs = await asyncio.wait_for(
                    _RAW_DB[col_name].find({}).to_list(length=None), timeout=8.0
                )
                if docs:
                    return docs
            except Exception:
                continue
    return []


def extract_chat_id_and_title(chat_doc: dict) -> Tuple[Optional[int], str]:
    raw_id = next(
        (chat_doc.get(k) for k in ("id", "chat_id", "_id", "group_id") if chat_doc.get(k) is not None),
        None,
    )
    cid = None
    if raw_id is not None:
        try:
            cid = int(str(raw_id).strip())
        except (ValueError, TypeError):
            cid = None

    title = (
        chat_doc.get("title")
        or chat_doc.get("name")
        or chat_doc.get("chat_title")
        or "Unknown Chat"
    )
    return cid, str(title)


def extract_user_id_and_name(user_doc: dict) -> Tuple[Optional[int], str]:
    raw_id = next(
        (user_doc.get(k) for k in ("id", "user_id", "_id") if user_doc.get(k) is not None),
        None,
    )
    uid = None
    if raw_id is not None:
        try:
            uid = int(str(raw_id).strip())
        except (ValueError, TypeError):
            uid = None

    name = (
        user_doc.get("name")
        or user_doc.get("first_name")
        or user_doc.get("username")
        or "Unknown User"
    )
    return uid, str(name)


# ============================================================
# 👑 FULL POWER ADMIN CHECKER
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


async def is_callback_user_admin(client: Client, query: CallbackQuery) -> bool:
    if not query or not query.from_user:
        return False
    if query.from_user.id in get_admin_list():
        return True
    if (
        query.message
        and query.message.chat
        and query.message.chat.type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]
    ):
        try:
            member = await client.get_chat_member(
                query.message.chat.id, query.from_user.id
            )
            return member.status in [
                enums.ChatMemberStatus.ADMINISTRATOR,
                enums.ChatMemberStatus.OWNER,
            ]
        except Exception:
            pass
    return False


async def _require_admin(client: Client, message: Message) -> bool:
    if await is_user_admin(client, message):
        return True
    await safe_reply_text(
        message,
        "❌ <b>Unauthorized:</b> Admin access required.",
        parse_mode=enums.ParseMode.HTML,
    )
    return False


async def _remove_chat_from_dbs(cid: int):
    try:
        if hasattr(_db, "delete_chat"):
            await _db.delete_chat(cid)
        if hasattr(_db, "grp"):
            await _db.grp.delete_many({"$or": [{"id": cid}, {"chat_id": cid}]})
    except Exception:
        pass

    if _RAW_DB is not None:
        for col_name in ("groups", "chats", "grp"):
            try:
                await _RAW_DB[col_name].delete_many(
                    {"$or": [{"id": cid}, {"chat_id": cid}, {"_id": cid}]}
                )
            except Exception:
                pass


# ============================================================
# 📱 INTERACTIVE CHANNEL MANAGER DASHBOARD (/channels)
# ============================================================
async def _fetch_single_channel_meta(
    client: Client, cid: int, default_title: str
) -> dict:
    raw_title = default_title or "Unknown"
    short_title = raw_title[:22]
    status_tag = "❌ Left / No Access"
    member_count_str = "?"
    invite_link = None

    async def _query_tg():
        nonlocal raw_title, short_title, status_tag, member_count_str, invite_link
        chat_obj = await client.get_chat(cid)
        if getattr(chat_obj, "title", None):
            raw_title = chat_obj.title
            short_title = raw_title[:22]
        member_count_str = str(getattr(chat_obj, "members_count", None) or "?")
        if getattr(chat_obj, "username", None):
            invite_link = f"https://t.me/{chat_obj.username}"
        elif getattr(chat_obj, "invite_link", None):
            invite_link = chat_obj.invite_link

        member_self = await client.get_chat_member(cid, "me")
        status_tag = (
            "👑 Admin"
            if member_self.status
            in [enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER]
            else "👤 Member"
        )

    try:
        await asyncio.wait_for(_query_tg(), timeout=4.0)
    except Exception:
        pass

    return {
        "cid": cid,
        "title": html.escape(short_title),
        "raw_title": short_title,
        "status_tag": status_tag,
        "member_count_str": member_count_str,
        "link": invite_link,
    }


async def build_channels_dashboard(
    client: Client, page: int = 1
) -> Tuple[str, InlineKeyboardMarkup]:
    raw_chats = await fetch_all_chats_safely()

    valid_chats: List[Tuple[int, str]] = []
    seen_ids = set()
    for ch in raw_chats:
        cid, title = extract_chat_id_and_title(ch)
        if cid is not None and cid not in seen_ids:
            seen_ids.add(cid)
            valid_chats.append((cid, title))

    total_channels = len(valid_chats)
    if total_channels == 0:
        return (
            "⚠️ <b>No connected channels or groups found in database.</b>",
            InlineKeyboardMarkup(
                [[create_btn("🔐 Close", callback_data="chan_close")]]
            ),
        )

    page_size = 5
    total_pages = max(1, math.ceil(total_channels / page_size))
    page = max(1, min(page, total_pages))

    start_idx = (page - 1) * page_size
    current_slice = valid_chats[start_idx : start_idx + page_size]

    metas = await asyncio.gather(
        *[
            _fetch_single_channel_meta(client, cid, title)
            for cid, title in current_slice
        ]
    )

    text = (
        f"📊 <b>Interactive Channel & Group Dashboard</b> (Page {page}/{total_pages})\n"
        f"📢 <b>Total Connected Chats:</b> <code>{total_channels}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
    )

    buttons: List[List[InlineKeyboardButton]] = []
    for idx, meta in enumerate(metas, start=start_idx + 1):
        cid = meta["cid"]
        link_str = f" | <a href='{meta['link']}'>Link</a>" if meta["link"] else ""
        text += (
            f"<b>{idx}. {meta['title']}</b> (<code>{cid}</code>)\n"
            f"   └ {meta['status_tag']} | 👥 <code>{meta['member_count_str']}</code>{link_str}\n\n"
        )
        buttons.append(
            [
                create_btn(
                    f"📢 {meta['raw_title']}",
                    callback_data=f"chan_info:{cid}",
                    style=BTN_PRIMARY,
                ),
                create_btn(
                    "🚪 Leave",
                    callback_data=f"chan_leave:{cid}:{page}",
                    style=BTN_DANGER,
                ),
            ]
        )

    nav_row: List[InlineKeyboardButton] = []
    if page > 1:
        nav_row.append(create_btn("⬅️ Prev", callback_data=f"chan_page:{page - 1}"))
    nav_row.append(
        create_btn(f"📄 {page}/{total_pages}", callback_data=f"chan_page:{page}")
    )
    if page < total_pages:
        nav_row.append(create_btn("Next ➡️", callback_data=f"chan_page:{page + 1}"))
    buttons.append(nav_row)

    buttons.append(
        [
            create_btn("🔄 Refresh", callback_data=f"chan_page:{page}"),
            create_btn("🔐 Close", callback_data="chan_close"),
        ]
    )
    return text, InlineKeyboardMarkup(buttons)


@Client.on_message(
    filters.command(["channels", "channeldashboard", "channel"]) & filters.incoming,
    group=-2,
)
async def channels_dashboard_cmd(client: Client, message: Message):
    if not await _require_admin(client, message):
        return

    status = await safe_reply_text(
        message,
        "⏳ <b>Loading Channel Dashboard...</b>",
        parse_mode=enums.ParseMode.HTML,
    )
    try:
        text, markup = await build_channels_dashboard(client, page=1)
        if status:
            await safe_edit_text(
                status,
                text,
                reply_markup=markup,
                disable_web_page_preview=True,
                parse_mode=enums.ParseMode.HTML,
            )
    except Exception as e:
        logger.error(f"channels_dashboard_cmd error: {e}")
        if status:
            await safe_edit_text(
                status,
                f"❌ <b>Error loading channels dashboard:</b>\n<code>{html.escape(str(e))}</code>",
                parse_mode=enums.ParseMode.HTML,
            )


@Client.on_callback_query(filters.regex(r"^chan_page:(\d+)$"), group=-2)
async def channels_page_cb(client: Client, query: CallbackQuery):
    if not await is_callback_user_admin(client, query):
        return await safe_answer(
            query, "❌ Unauthorized: Admins only!", show_alert=True
        )
    if not query.message:
        return await safe_answer(query)

    page = int(query.matches[0].group(1))
    await safe_answer(query, "Updating dashboard...")
    try:
        text, markup = await build_channels_dashboard(client, page=page)
        await safe_edit_text(
            query.message,
            text,
            reply_markup=markup,
            disable_web_page_preview=True,
            parse_mode=enums.ParseMode.HTML,
        )
    except Exception as e:
        logger.error(f"Error updating channel page: {e}")


@Client.on_callback_query(filters.regex(r"^chan_leave:(-?\d+):(\d+)$"), group=-2)
async def channels_leave_cb(client: Client, query: CallbackQuery):
    if not await is_callback_user_admin(client, query):
        return await safe_answer(
            query, "❌ Unauthorized: Admins only!", show_alert=True
        )
    if not query.message:
        return await safe_answer(query)

    cid = int(query.matches[0].group(1))
    page = int(query.matches[0].group(2))

    try:
        await client.leave_chat(cid)
    except Exception:
        pass
    await _remove_chat_from_dbs(cid)

    await safe_answer(query, f"✅ Left and removed chat {cid}", show_alert=True)
    try:
        text, markup = await build_channels_dashboard(client, page=page)
        await safe_edit_text(
            query.message,
            text,
            reply_markup=markup,
            disable_web_page_preview=True,
            parse_mode=enums.ParseMode.HTML,
        )
    except Exception as e:
        logger.error(f"channels_leave_cb refresh error: {e}")


@Client.on_callback_query(filters.regex(r"^chan_info:(-?\d+)$"), group=-2)
async def channels_info_cb(client: Client, query: CallbackQuery):
    if not await is_callback_user_admin(client, query):
        return await safe_answer(
            query, "❌ Unauthorized: Admins only!", show_alert=True
        )

    cid = int(query.matches[0].group(1))
    try:
        chat = await asyncio.wait_for(client.get_chat(cid), timeout=5.0)
        uname = f"@{chat.username}" if getattr(chat, "username", None) else "Private"
        members = getattr(chat, "members_count", None) or "?"
        await safe_answer(
            query,
            f"📢 Title: {chat.title}\n🆔 ID: {chat.id}\n🔗 Username: {uname}\n👥 Members: {members}",
            show_alert=True,
        )
    except Exception as e:
        await safe_answer(query, f"⚠️ Could not fetch live info:\n{e}", show_alert=True)


@Client.on_callback_query(filters.regex(r"^chan_close$"), group=-2)
async def channels_close_cb(client: Client, query: CallbackQuery):
    if not await is_callback_user_admin(client, query):
        return await safe_answer(
            query, "❌ Unauthorized: Admins only!", show_alert=True
        )
    await safe_answer(query, "Closed!")
    if query.message:
        try:
            await query.message.delete()
        except Exception:
            pass
        if query.message.reply_to_message:
            try:
                await query.message.reply_to_message.delete()
            except Exception:
                pass


# ============================================================
# 🚪 LEAVE CHANNEL / GROUP BY ID COMMAND (/leavechannel, /leave)
# ============================================================
@Client.on_message(
    filters.command(["leavechannel", "leave"]) & filters.incoming,
    group=-2,
)
async def leave_channel_cmd(client: Client, message: Message):
    if not await _require_admin(client, message):
        return

    if len(message.command) < 2:
        return await safe_reply_text(
            message,
            "⚙️ <b>Usage:</b> <code>/leavechannel &lt;channel_or_group_id&gt;</code>",
            parse_mode=enums.ParseMode.HTML,
        )

    try:
        chat_id_int = int(message.command[1].strip())
    except ValueError:
        return await safe_reply_text(
            message,
            "❌ <b>Invalid Chat ID format.</b> Example: <code>/leavechannel -1001234567890</code>",
            parse_mode=enums.ParseMode.HTML,
        )

    chat_title = "Unknown Chat"
    try:
        chat = await client.get_chat(chat_id_int)
        chat_title = chat.title or "Unknown Chat"
    except Exception:
        pass

    try:
        await client.leave_chat(chat_id_int)
        tg_status = "✅ Successfully left chat."
    except Exception as e:
        tg_status = f"⚠️ Could not leave Telegram chat: {html.escape(str(e))}"

    try:
        await _remove_chat_from_dbs(chat_id_int)
        db_status = "✅ Removed from Database."
    except Exception as e:
        db_status = f"❌ DB Remove Error: {html.escape(str(e))}"

    await safe_reply_text(
        message,
        f"🎯 <b>Operation Complete:</b>\n\n"
        f"<b>Name:</b> {html.escape(chat_title)}\n"
        f"<b>ID:</b> <code>{chat_id_int}</code>\n\n"
        f"<b>Telegram Status:</b> {tg_status}\n"
        f"<b>Database Status:</b> {db_status}",
        parse_mode=enums.ParseMode.HTML,
    )


# ============================================================
# 📄 EXPORT COMMANDS (/exportusers, /exportgroups, /exportchannels)
# ============================================================
async def _send_export_document(
    message: Message,
    status_msg: Optional[Message],
    content: str,
    filename: str,
    caption: str,
):
    bio = io.BytesIO(content.encode("utf-8", errors="replace"))
    bio.name = filename
    try:
        await message.reply_document(
            document=bio,
            file_name=filename,
            caption=caption,
            parse_mode=enums.ParseMode.HTML,
        )
    except TypeError:
        bio.seek(0)
        await message.reply_document(
            document=bio, caption=caption, parse_mode=enums.ParseMode.HTML
        )
    except FloodWait as e:
        await asyncio.sleep(e.value + 1)
        bio.seek(0)
        await message.reply_document(
            document=bio, caption=caption, parse_mode=enums.ParseMode.HTML
        )
    if status_msg:
        try:
            await status_msg.delete()
        except Exception:
            pass


@Client.on_message(
    filters.command(["exportusers", "users_list"]) & filters.incoming,
    group=-2,
)
async def export_users_cmd(bot: Client, message: Message):
    if not await _require_admin(bot, message):
        return

    status = await safe_reply_text(
        message,
        "⏳ <b>Exporting users from database...</b>",
        parse_mode=enums.ParseMode.HTML,
    )
    try:
        users = await fetch_all_users_safely()
        lines = [
            f"{uid} - {name}"
            for uid, name in (extract_user_id_and_name(u) for u in users)
            if uid is not None
        ]
        if not lines:
            if status:
                await safe_edit_text(
                    status,
                    "⚠️ <b>No valid user records found in the database.</b>",
                    parse_mode=enums.ParseMode.HTML,
                )
            return

        time_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        caption = (
            f"🧍 <b>User List Export</b>\n\n"
            f"📅 <b>Generated on:</b> <code>{time_str} UTC</code>\n"
            f"👥 <b>Total Users:</b> <code>{len(lines)}</code>"
        )
        await _send_export_document(
            message, status, "\n".join(lines), "users_list.txt", caption
        )
    except Exception as e:
        logger.error(f"export_users_cmd error: {e}")
        if status:
            await safe_edit_text(
                status,
                f"❌ <b>Failed to export users:</b>\n<code>{html.escape(str(e))}</code>",
                parse_mode=enums.ParseMode.HTML,
            )


@Client.on_message(
    filters.command(["exportgroups", "groups_list"]) & filters.incoming,
    group=-2,
)
async def export_groups_cmd(bot: Client, message: Message):
    if not await _require_admin(bot, message):
        return

    status = await safe_reply_text(
        message,
        "⏳ <b>Exporting groups from database...</b>",
        parse_mode=enums.ParseMode.HTML,
    )
    try:
        chats = await fetch_all_chats_safely()
        normal_groups, supergroups, lines = 0, 0, []

        for c in chats:
            cid, title = extract_chat_id_and_title(c)
            if cid is None:
                continue
            if str(cid).startswith("-100"):
                supergroups += 1
            else:
                normal_groups += 1
            lines.append(f"{cid} - {title}")

        if not lines:
            if status:
                await safe_edit_text(
                    status,
                    "⚠️ <b>No valid group records found in the database.</b>",
                    parse_mode=enums.ParseMode.HTML,
                )
            return

        time_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        caption = (
            f"💬 <b>Group Chats Export</b>\n\n"
            f"📅 <b>Generated on:</b> <code>{time_str} UTC</code>\n"
            f"🏘️ <b>Total Chats:</b> <code>{len(lines)}</code>\n"
            f"👥 <b>Groups:</b> <code>{normal_groups}</code> | 📢 <b>Supergroups/Channels:</b> <code>{supergroups}</code>"
        )
        await _send_export_document(
            message, status, "\n".join(lines), "chats_list.txt", caption
        )
    except Exception as e:
        logger.error(f"export_groups_cmd error: {e}")
        if status:
            await safe_edit_text(
                status,
                f"❌ <b>Failed to export groups:</b>\n<code>{html.escape(str(e))}</code>",
                parse_mode=enums.ParseMode.HTML,
            )


@Client.on_message(
    filters.command(["exportchannels", "channels_list"]) & filters.incoming,
    group=-2,
)
async def export_channels_cmd(bot: Client, message: Message):
    if not await _require_admin(bot, message):
        return

    status = await safe_reply_text(
        message,
        "⏳ <b>Exporting channels from database...</b>",
        parse_mode=enums.ParseMode.HTML,
    )
    try:
        chats = await fetch_all_chats_safely()
        lines = [
            f"{cid} - {title}"
            for cid, title in (extract_chat_id_and_title(c) for c in chats)
            if cid is not None and str(cid).startswith("-100")
        ]

        if not lines:
            if status:
                await safe_edit_text(
                    status,
                    "⚠️ <b>No channels/supergroups found in the database.</b>",
                    parse_mode=enums.ParseMode.HTML,
                )
            return

        time_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        caption = (
            f"📢 <b>Channel List Export</b>\n\n"
            f"📅 <b>Generated on:</b> <code>{time_str} UTC</code>\n"
            f"📺 <b>Total Channels:</b> <code>{len(lines)}</code>"
        )
        await _send_export_document(
            message, status, "\n".join(lines), "channels_list.txt", caption
        )
    except Exception as e:
        logger.error(f"export_channels_cmd error: {e}")
        if status:
            await safe_edit_text(
                status,
                f"❌ <b>Failed to export channels:</b>\n<code>{html.escape(str(e))}</code>",
                parse_mode=enums.ParseMode.HTML,
            )
