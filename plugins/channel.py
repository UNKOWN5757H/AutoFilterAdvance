import io
import math
from datetime import datetime, timezone
from logging import ERROR, getLogger

from pyrogram import Client, enums, filters
from pyrogram.errors import MessageNotModified
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


def get_admin_list():
    raw_admins = getattr(info, "ADMINS", [])
    if isinstance(raw_admins, str):
        return [
            int(x)
            for x in raw_admins.replace(",", " ").split()
            if x.strip().lstrip("-").isdigit()
        ]
    elif isinstance(raw_admins, int):
        return [raw_admins]
    elif isinstance(raw_admins, list):
        return [int(x) for x in raw_admins if str(x).strip().lstrip("-").isdigit()]
    return []


admin_filter = filters.create(
    lambda _, __, msg: bool(msg.from_user and msg.from_user.id in get_admin_list())
)


# ============================================================
# 📱 INTERACTIVE CHANNEL MANAGER DASHBOARD (/channels)
# ============================================================
async def build_channels_dashboard(client: Client, page: int = 1):
    chats_data = await _db.get_all_chats()
    chats = (
        await chats_data.to_list(length=None)
        if hasattr(chats_data, "to_list")
        else list(chats_data)
    )
    channels = [chat for chat in chats if str(chat.get("id", "")).startswith("-100")]

    total_channels = len(channels)
    if total_channels == 0:
        return "⚠️ **No channels found in database.**", None

    page_size = 5
    total_pages = max(1, math.ceil(total_channels / page_size))
    page = max(1, min(page, total_pages))

    start_idx = (page - 1) * page_size
    current_channels = channels[start_idx : start_idx + page_size]

    text = f"📊 **Interactive Channel Dashboard** (Page {page}/{total_pages})\n"
    text += f"📢 **Connected Channels:** `{total_channels}`\n\n"

    buttons = []
    for ch in current_channels:
        cid = int(ch["id"])
        title = ch.get("title", "Unknown")[:18]

        # Live verify rights & member count
        status_tag = "❌ Left"
        member_count_str = "?"
        try:
            chat_obj = await client.get_chat(cid)
            member_count_str = str(chat_obj.members_count or "?")
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

        text += f"• **{title}** (`{cid}`)\n  └ {status_tag} | 👥 `{member_count_str}` members\n\n"
        buttons.append(
            [
                InlineKeyboardButton(f"📢 {title}", callback_data=f"chan_info:{cid}"),
                InlineKeyboardButton(
                    "🚪 Leave", callback_data=f"chan_leave:{cid}:{page}"
                ),
            ]
        )

    nav_row = []
    if page > 1:
        nav_row.append(
            InlineKeyboardButton("⬅️ Prev", callback_data=f"chan_page:{page-1}")
        )
    if page < total_pages:
        nav_row.append(
            InlineKeyboardButton("Next ➡️", callback_data=f"chan_page:{page+1}")
        )
    if nav_row:
        buttons.append(nav_row)

    buttons.append(
        [
            InlineKeyboardButton(
                "🔄 Refresh Dashboard", callback_data=f"chan_page:{page}"
            )
        ]
    )
    return text, InlineKeyboardMarkup(buttons)


@Client.on_message(filters.command("channels") & admin_filter)
async def channels_dashboard_cmd(client: Client, message: Message):
    text, markup = await build_channels_dashboard(client, page=1)
    await message.reply_text(text, reply_markup=markup, disable_web_page_preview=True)


@Client.on_callback_query(filters.regex(r"^chan_page:(\d+)") & admin_filter)
async def channels_page_cb(client: Client, query: CallbackQuery):
    page = int(query.matches[0].group(1))
    text, markup = await build_channels_dashboard(client, page=page)
    try:
        await query.message.edit_text(
            text, reply_markup=markup, disable_web_page_preview=True
        )
    except MessageNotModified:
        pass
    await query.answer()


@Client.on_callback_query(filters.regex(r"^chan_leave:(-?\d+):(\d+)") & admin_filter)
async def channels_leave_cb(client: Client, query: CallbackQuery):
    cid = int(query.matches[0].group(1))
    page = int(query.matches[0].group(2))
    try:
        await client.leave_chat(cid)
    except Exception:
        pass

    try:
        await _db.disable_chat(cid, "Admin Dashboard Left")
    except Exception:
        pass

    await query.answer(f"Left channel {cid}", show_alert=True)
    text, markup = await build_channels_dashboard(client, page=page)
    try:
        await query.message.edit_text(
            text, reply_markup=markup, disable_web_page_preview=True
        )
    except Exception:
        pass


@Client.on_callback_query(filters.regex(r"^chan_info:(-?\d+)") & admin_filter)
async def channels_info_cb(client: Client, query: CallbackQuery):
    cid = int(query.matches[0].group(1))
    try:
        chat = await client.get_chat(cid)
        await query.answer(
            f"Title: {chat.title}\nID: {chat.id}\nMembers: {chat.members_count}",
            show_alert=True,
        )
    except Exception as e:
        await query.answer(f"Error fetching channel: {e}", show_alert=True)


# ============================================================
# 📄 EXPORT SCRIPTS
# ============================================================
@Client.on_message(filters.command("exportusers") & admin_filter)
async def export_users_cmd(bot: Client, message: Message):
    status = await message.reply_text("⏳ **Exporting users from database...**")
    users_data = await _db.get_all_users()
    users = (
        await users_data.to_list(length=None)
        if hasattr(users_data, "to_list")
        else list(users_data)
    )
    total = len(users)

    if total == 0:
        return await status.edit_text("⚠️ No users found in the database.")

    time_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    text = f"🧍 **User List Export**\n\n📅 Generated on: `{time_str} UTC`\n👥 Total Users: `{total}`\n\n"
    data = "\n".join(
        [
            f"{user.get('id', 'Unknown')} - {user.get('name', 'Unknown')}"
            for user in users
        ]
    )

    file = io.BytesIO(data.encode("utf-8"))
    file.name = "users_list.txt"

    await message.reply_document(document=file, caption=text)
    await status.delete()


@Client.on_message(filters.command("exportgroups") & admin_filter)
async def export_groups_cmd(bot: Client, message: Message):
    status = await message.reply_text("⏳ **Exporting groups from database...**")
    chats_data = await _db.get_all_chats()
    chats = (
        await chats_data.to_list(length=None)
        if hasattr(chats_data, "to_list")
        else list(chats_data)
    )
    total = len(chats)

    if total == 0:
        return await status.edit_text("⚠️ No groups found in the database.")

    groups = [chat for chat in chats if not str(chat.get("id", "")).startswith("-100")]
    supergroups = [chat for chat in chats if str(chat.get("id", "")).startswith("-100")]

    time_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    text = f"💬 **Group Chats Export**\n\n📅 Generated on: `{time_str} UTC`\n🏘️ Total Chats: `{total}`\n👥 Groups: `{len(groups)}` | 📢 Supergroups: `{len(supergroups)}`\n\n"
    data = "\n".join(
        [
            f"{chat.get('id', 'Unknown')} - {chat.get('title', 'Unknown')}"
            for chat in chats
        ]
    )

    file = io.BytesIO(data.encode("utf-8"))
    file.name = "chats_list.txt"

    await message.reply_document(document=file, caption=text)
    await status.delete()


@Client.on_message(filters.command("exportchannels") & admin_filter)
async def export_channels_cmd(bot: Client, message: Message):
    status = await message.reply_text("⏳ **Exporting channels from database...**")
    chats_data = await _db.get_all_chats()
    chats = (
        await chats_data.to_list(length=None)
        if hasattr(chats_data, "to_list")
        else list(chats_data)
    )
    channels = [chat for chat in chats if str(chat.get("id", "")).startswith("-100")]
    total = len(channels)

    if total == 0:
        return await status.edit_text("⚠️ No channels found in the database.")

    time_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    text = f"📢 **Channel List Export**\n\n📅 Generated on: `{time_str} UTC`\n📺 Total Channels: `{total}`\n\n"
    data = "\n".join(
        [
            f"{chat.get('id', 'Unknown')} - {chat.get('title', 'Unknown')}"
            for chat in channels
        ]
    )

    file = io.BytesIO(data.encode("utf-8"))
    file.name = "channels_list.txt"

    await message.reply_document(document=file, caption=text)
    await status.delete()
