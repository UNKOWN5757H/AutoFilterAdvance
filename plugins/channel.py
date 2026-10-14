import asyncio
import html
import io
import math
from datetime import datetime, timezone
from logging import ERROR, getLogger

from pyrogram import Client, enums, filters
from pyrogram.errors import MessageNotModified, QueryIdInvalid
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
# 👑 FULL POWER ADMIN CHECKER (GLOBAL + CHAT + ANONYMOUS)
# ============================================================
def get_admin_list():
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

    # 1. Global Admin Check (Direct User)
    if message.from_user and message.from_user.id in admin_list:
        return True

    # 2. Global Admin Check (Anonymous/Channel sending as Chat)
    if message.sender_chat and message.sender_chat.id in admin_list:
        return True

    # 3. Group Admin Check (Normal & Anonymous Admins)
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
    """Properly checks if the user clicking the inline button is an admin."""
    if not query or not query.from_user:
        return False

    user_id = query.from_user.id
    admin_list = get_admin_list()

    # 1. Global Admin Check
    if user_id in admin_list:
        return True

    # 2. Group Admin Check (if button was clicked inside a group)
    if query.message and query.message.chat and query.message.chat.type in [
        enums.ChatType.GROUP,
        enums.ChatType.SUPERGROUP,
    ]:
        try:
            member = await client.get_chat_member(query.message.chat.id, user_id)
            return member.status in [
                enums.ChatMemberStatus.ADMINISTRATOR,
                enums.ChatMemberStatus.OWNER,
            ]
        except Exception:
            pass

    return False


async def admin_check(_, client: Client, message: Message):
    return await is_user_admin(client, message)


admin_filter = filters.create(admin_check)


# ============================================================
# 📱 INTERACTIVE CHANNEL MANAGER DASHBOARD (/channels)
# ============================================================
async def _fetch_single_channel_meta(client: Client, ch: dict):
    raw_id = ch.get("id") if ch.get("id") is not None else ch.get("chat_id")
    cid = int(raw_id)
    raw_title = str(ch.get("title") or ch.get("name") or "Unknown")
    short_title = raw_title[:20]

    status_tag = "❌ Left"
    member_count_str = "?"
    try:
        chat_obj = await client.get_chat(cid)
        if chat_obj.title:
            raw_title = chat_obj.title
            short_title = raw_title[:20]
        member_count_str = str(getattr(chat_obj, "members_count", None) or "?")
        member_self = await client.get_chat_member(cid, "me")
        if member_self.status in [
            enums.ChatMemberStatus.ADMINISTRATOR,
            enums.ChatMemberStatus.OWNER,
        ]:
            status_tag = "👑 Admin"
        else:
            status_tag = "👤 Member"
    except Exception:
        pass

    return {
        "cid": cid,
        "title": html.escape(short_title),
        "raw_title": short_title,
        "status_tag": status_tag,
        "member_count_str": member_count_str,
    }


async def build_channels_dashboard(client: Client, page: int = 1):
    chats_data = await _db.get_all_chats()
    chats = (
        await chats_data.to_list(length=None)
        if hasattr(chats_data, "to_list")
        else list(chats_data)
    )
    channels = [
        chat
        for chat in chats
        if str(chat.get("id") or chat.get("chat_id") or "").startswith("-100")
    ]

    total_channels = len(channels)
    if total_channels == 0:
        return (
            "⚠️ <b>No connected channels or supergroups found in database.</b>",
            InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔐 Close", callback_data="chan_close")]]
            ),
        )

    page_size = 5
    total_pages = max(1, math.ceil(total_channels / page_size))
    page = max(1, min(page, total_pages))

    start_idx = (page - 1) * page_size
    current_channels = channels[start_idx : start_idx + page_size]

    metas = await asyncio.gather(
        *[_fetch_single_channel_meta(client, ch) for ch in current_channels]
    )

    text = (
        f"📊 <b>Interactive Channel Dashboard</b> (Page {page}/{total_pages})\n"
        f"📢 <b>Connected Channels:</b> <code>{total_channels}</code>\n\n"
    )

    buttons = []
    for meta in metas:
        cid = meta["cid"]
        text += (
            f"• <b>{meta['title']}</b> (<code>{cid}</code>)\n"
            f"  └ {meta['status_tag']} | 👥 <code>{meta['member_count_str']}</code> members\n\n"
        )
        buttons.append(
            [
                InlineKeyboardButton(
                    f"📢 {meta['raw_title']}", callback_data=f"chan_info:{cid}"
                ),
                InlineKeyboardButton(
                    "🚪 Leave", callback_data=f"chan_leave:{cid}:{page}"
                ),
            ]
        )

    nav_row = []
    if page > 1:
        nav_row.append(
            InlineKeyboardButton("⬅️ Prev", callback_data=f"chan_page:{page - 1}")
        )
    if page < total_pages:
        nav_row.append(
            InlineKeyboardButton("Next ➡️", callback_data=f"chan_page:{page + 1}")
        )
    if nav_row:
        buttons.append(nav_row)

    buttons.append(
        [
            InlineKeyboardButton(
                "🔄 Refresh", callback_data=f"chan_page:{page}"
            ),
            InlineKeyboardButton("🔐 Close", callback_data="chan_close"),
        ]
    )
    return text, InlineKeyboardMarkup(buttons)


@Client.on_message(filters.command(["channels", "channeldashboard"]) & admin_filter)
async def channels_dashboard_cmd(client: Client, message: Message):
    status = await message.reply_text(
        "⏳ <b>Loading Channel Dashboard...</b>",
        parse_mode=enums.ParseMode.HTML,
    )
    text, markup = await build_channels_dashboard(client, page=1)
    await status.edit_text(
        text,
        reply_markup=markup,
        disable_web_page_preview=True,
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_callback_query(filters.regex(r"^chan_page:(\d+)$"))
async def channels_page_cb(client: Client, query: CallbackQuery):
    if not await is_callback_user_admin(client, query):
        return await query.answer("❌ Unauthorized: Admins only!", show_alert=True)

    page = int(query.matches[0].group(1))
    await query.answer("Updating dashboard...")
    text, markup = await build_channels_dashboard(client, page=page)
    try:
        await query.message.edit_text(
            text,
            reply_markup=markup,
            disable_web_page_preview=True,
            parse_mode=enums.ParseMode.HTML,
        )
    except MessageNotModified:
        pass
    except Exception as e:
        logger.error(f"Error updating channel page: {e}")


@Client.on_callback_query(filters.regex(r"^chan_leave:(-?\d+):(\d+)$"))
async def channels_leave_cb(client: Client, query: CallbackQuery):
    if not await is_callback_user_admin(client, query):
        return await query.answer("❌ Unauthorized: Admins only!", show_alert=True)

    cid = int(query.matches[0].group(1))
    page = int(query.matches[0].group(2))

    try:
        await client.leave_chat(cid)
    except Exception:
        pass

    try:
        if hasattr(_db, "delete_chat"):
            await _db.delete_chat(cid)
        elif hasattr(_db, "grp"):
            await _db.grp.delete_one({"id": cid})
            await _db.grp.delete_one({"chat_id": cid})
        elif hasattr(_db, "disable_chat"):
            await _db.disable_chat(cid, "Admin Dashboard Left")
    except Exception:
        pass

    try:
        await query.answer(f"✅ Left and removed channel {cid}", show_alert=True)
    except QueryIdInvalid:
        pass

    text, markup = await build_channels_dashboard(client, page=page)
    try:
        await query.message.edit_text(
            text,
            reply_markup=markup,
            disable_web_page_preview=True,
            parse_mode=enums.ParseMode.HTML,
        )
    except MessageNotModified:
        pass
    except Exception:
        pass


@Client.on_callback_query(filters.regex(r"^chan_info:(-?\d+)$"))
async def channels_info_cb(client: Client, query: CallbackQuery):
    if not await is_callback_user_admin(client, query):
        return await query.answer("❌ Unauthorized: Admins only!", show_alert=True)

    cid = int(query.matches[0].group(1))
    try:
        chat = await client.get_chat(cid)
        uname = f"@{chat.username}" if getattr(chat, "username", None) else "Private"
        await query.answer(
            f"📢 Title: {chat.title}\n🆔 ID: {chat.id}\n🔗 Username: {uname}\n👥 Members: {chat.members_count or '?'}",
            show_alert=True,
        )
    except Exception as e:
        await query.answer(f"⚠️ Could not fetch live info:\n{e}", show_alert=True)


@Client.on_callback_query(filters.regex(r"^chan_close$"))
async def channels_close_cb(client: Client, query: CallbackQuery):
    if not await is_callback_user_admin(client, query):
        return await query.answer("❌ Unauthorized: Admins only!", show_alert=True)
    await query.answer("Closed!")
    try:
        await query.message.delete()
    except Exception:
        pass


# ============================================================
# 📄 EXPORT SCRIPTS
# ============================================================
@Client.on_message(filters.command("exportusers") & admin_filter)
async def export_users_cmd(bot: Client, message: Message):
    status = await message.reply_text(
        "⏳ <b>Exporting users from database...</b>",
        parse_mode=enums.ParseMode.HTML,
    )
    users_data = await _db.get_all_users()
    users = (
        await users_data.to_list(length=None)
        if hasattr(users_data, "to_list")
        else list(users_data)
    )
    total = len(users)

    if total == 0:
        return await status.edit_text(
            "⚠️ <b>No users found in the database.</b>",
            parse_mode=enums.ParseMode.HTML,
        )

    time_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    text = (
        f"🧍 <b>User List Export</b>\n\n"
        f"📅 Generated on: <code>{time_str} UTC</code>\n"
        f"👥 Total Users: <code>{total}</code>"
    )
    data = "\n".join(
        [
            f"{user.get('id', 'Unknown')} - {user.get('name', 'Unknown')}"
            for user in users
        ]
    )

    file = io.BytesIO(data.encode("utf-8"))
    file.name = "users_list.txt"

    await message.reply_document(
        document=file, caption=text, parse_mode=enums.ParseMode.HTML
    )
    await status.delete()


@Client.on_message(filters.command("exportgroups") & admin_filter)
async def export_groups_cmd(bot: Client, message: Message):
    status = await message.reply_text(
        "⏳ <b>Exporting groups from database...</b>",
        parse_mode=enums.ParseMode.HTML,
    )
    chats_data = await _db.get_all_chats()
    chats = (
        await chats_data.to_list(length=None)
        if hasattr(chats_data, "to_list")
        else list(chats_data)
    )
    total = len(chats)

    if total == 0:
        return await status.edit_text(
            "⚠️ <b>No groups found in the database.</b>",
            parse_mode=enums.ParseMode.HTML,
        )

    groups = [
        chat
        for chat in chats
        if not str(chat.get("id") or chat.get("chat_id") or "").startswith("-100")
    ]
    supergroups = [
        chat
        for chat in chats
        if str(chat.get("id") or chat.get("chat_id") or "").startswith("-100")
    ]

    time_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    text = (
        f"💬 <b>Group Chats Export</b>\n\n"
        f"📅 Generated on: <code>{time_str} UTC</code>\n"
        f"🏘️ Total Chats: <code>{total}</code>\n"
        f"👥 Groups: <code>{len(groups)}</code> | 📢 Supergroups: <code>{len(supergroups)}</code>"
    )
    data = "\n".join(
        [
            f"{chat.get('id') or chat.get('chat_id', 'Unknown')} - {chat.get('title') or chat.get('name', 'Unknown')}"
            for chat in chats
        ]
    )

    file = io.BytesIO(data.encode("utf-8"))
    file.name = "chats_list.txt"

    await message.reply_document(
        document=file, caption=text, parse_mode=enums.ParseMode.HTML
    )
    await status.delete()


@Client.on_message(filters.command("exportchannels") & admin_filter)
async def export_channels_cmd(bot: Client, message: Message):
    status = await message.reply_text(
        "⏳ <b>Exporting channels from database...</b>",
        parse_mode=enums.ParseMode.HTML,
    )
    chats_data = await _db.get_all_chats()
    chats = (
        await chats_data.to_list(length=None)
        if hasattr(chats_data, "to_list")
        else list(chats_data)
    )
    channels = [
        chat
        for chat in chats
        if str(chat.get("id") or chat.get("chat_id") or "").startswith("-100")
    ]
    total = len(channels)

    if total == 0:
        return await status.edit_text(
            "⚠️ <b>No channels found in the database.</b>",
            parse_mode=enums.ParseMode.HTML,
        )

    time_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    text = (
        f"📢 <b>Channel List Export</b>\n\n"
        f"📅 Generated on: <code>{time_str} UTC</code>\n"
        f"📺 Total Channels: <code>{total}</code>"
    )
    data = "\n".join(
        [
            f"{chat.get('id') or chat.get('chat_id', 'Unknown')} - {chat.get('title') or chat.get('name', 'Unknown')}"
            for chat in channels
        ]
    )

    file = io.BytesIO(data.encode("utf-8"))
    file.name = "channels_list.txt"

    await message.reply_document(
        document=file, caption=text, parse_mode=enums.ParseMode.HTML
    )
    await status.delete()
