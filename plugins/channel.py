import datetime
import io

from pyrogram import Client, filters
from database.users_chats_db import db
from info import ADMINS

@Client.on_message(filters.command("users") & filters.user(ADMINS))
async def list_users(bot: Client, message):
    users_data = await db.get_all_users()
    users = await users_data.to_list(length=None) if hasattr(users_data, "to_list") else list(users_data)
    total = len(users)

    if total == 0: return await message.reply_text("⚠️ No users found in the database.")

    text = f"🧍 **User List Export**\n\n📅 Generated on: `{datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC`\n👥 Total Users: `{total}`\n\n"
    data = "\n".join([f"{user['id']} - {user.get('name', 'Unknown')}" for user in users])
    file = io.BytesIO(data.encode())
    file.name = "users_list.txt"

    await message.reply_document(document=file, caption=text)

@Client.on_message(filters.command("chats") & filters.user(ADMINS))
async def list_chats(bot: Client, message):
    chats_data = await db.get_all_chats()
    chats = await chats_data.to_list(length=None) if hasattr(chats_data, "to_list") else list(chats_data)
    total = len(chats)

    if total == 0: return await message.reply_text("⚠️ No groups found in the database.")

    groups = [chat for chat in chats if not str(chat["id"]).startswith("-100")]
    supergroups = [chat for chat in chats if str(chat["id"]).startswith("-100")]

    text = f"💬 **Group Chats Export**\n\n📅 Generated on: `{datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC`\n🏘️ Total Chats: `{total}`\n👥 Groups: `{len(groups)}` | 📢 Supergroups: `{len(supergroups)}`\n\n"
    data = "\n".join([f"{chat['id']} - {chat.get('title', 'Unknown')}" for chat in chats])
    file = io.BytesIO(data.encode())
    file.name = "chats_list.txt"

    await message.reply_document(document=file, caption=text)

@Client.on_message(filters.command(["channel", "channels"]) & filters.user(ADMINS))
async def list_channels(bot: Client, message):
    chats_data = await db.get_all_chats()
    chats = await chats_data.to_list(length=None) if hasattr(chats_data, "to_list") else list(chats_data)

    channels = [chat for chat in chats if str(chat["id"]).startswith("-100")]
    total = len(channels)

    if total == 0: return await message.reply_text("⚠️ No channels found in the database.")

    text = f"📢 **Channel List Export**\n\n📅 Generated on: `{datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC`\n📺 Total Channels: `{total}`\n\n"
    data = "\n".join([f"{chat['id']} - {chat.get('title', 'Unknown')}" for chat in channels])
    file = io.BytesIO(data.encode())
    file.name = "channels_list.txt"

    await message.reply_document(document=file, caption=text)
