import datetime
import io
from logging import getLogger, ERROR

from pyrogram import Client, filters

from database.users_chats_db import db
from info import ADMINS

logger = getLogger(__name__)
logger.setLevel(ERROR)


# ============================================================
# 🧍 /exportusers — Show total users + export list
# ============================================================
@Client.on_message(filters.command("exportusers") & filters.user(ADMINS))
async def list_users(bot: Client, message):
    """List all registered users."""
    users_data = await db.get_all_users()

    if hasattr(users_data, "to_list"):
        users = await users_data.to_list(length=None)
    else:
        users = list(users_data)

    total = len(users)

    if total == 0:
        return await message.reply_text("⚠️ No users found in the database.")

    text = "🧍 **User List Export**\n\n"
    text += f"📅 Generated on: `{datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC`\n"
    text += f"👥 Total Users: `{total}`\n\n"

    data = "\n".join(
        [f"{user['id']} - {user.get('name', 'Unknown')}" for user in users]
    )
    file = io.BytesIO(data.encode())
    file.name = "users_list.txt"

    await message.reply_document(document=file, caption=text)


# ============================================================
# 💬 /exportgroups — Show all group chats
# ============================================================
@Client.on_message(filters.command("exportgroups") & filters.user(ADMINS))
async def list_chats(bot: Client, message):
    """List all registered group chats."""
    chats_data = await db.get_all_chats()

    if hasattr(chats_data, "to_list"):
        chats = await chats_data.to_list(length=None)
    else:
        chats = list(chats_data)

    total = len(chats)

    if total == 0:
        return await message.reply_text("⚠️ No groups found in the database.")

    groups = [chat for chat in chats if not str(chat["id"]).startswith("-100")]
    supergroups = [chat for chat in chats if str(chat["id"]).startswith("-100")]

    text = "💬 **Group Chats Export**\n\n"
    text += f"📅 Generated on: `{datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC`\n"
    text += f"🏘️ Total Chats: `{total}`\n"
    text += f"👥 Groups: `{len(groups)}` | 📢 Supergroups: `{len(supergroups)}`\n\n"

    data = "\n".join(
        [f"{chat['id']} - {chat.get('title', 'Unknown')}" for chat in chats]
    )
    file = io.BytesIO(data.encode())
    file.name = "chats_list.txt"

    await message.reply_document(document=file, caption=text)


# ============================================================
# 📢 /exportchannels — Show all channels the bot is in
# ============================================================
@Client.on_message(filters.command("exportchannels") & filters.user(ADMINS))
async def list_channels(bot: Client, message):
    """List all channels where the bot is present."""
    chats_data = await db.get_all_chats()

    if hasattr(chats_data, "to_list"):
        chats = await chats_data.to_list(length=None)
    else:
        chats = list(chats_data)

    channels = [chat for chat in chats if str(chat["id"]).startswith("-100")]
    total = len(channels)

    if total == 0:
        return await message.reply_text("⚠️ No channels found in the database.")

    text = "📢 **Channel List Export**\n\n"
    text += f"📅 Generated on: `{datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC`\n"
    text += f"📺 Total Channels: `{total}`\n\n"

    data = "\n".join(
        [f"{chat['id']} - {chat.get('title', 'Unknown')}" for chat in channels]
    )
    file = io.BytesIO(data.encode())
    file.name = "channels_list.txt"

    await message.reply_document(document=file, caption=text)
