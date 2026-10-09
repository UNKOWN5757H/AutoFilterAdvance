import io
from datetime import datetime, timezone
from logging import ERROR, getLogger

from pyrogram import Client, filters
from pyrogram.types import Message

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
