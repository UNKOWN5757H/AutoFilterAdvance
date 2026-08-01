import datetime
import io
from pyrogram import Client, filters
from database.users_chats_db import db
from info import ADMINS

@Client.on_message(filters.command("users") & filters.user(ADMINS))
async def list_users(bot: Client, message):
    users = await db.get_all_users()
    if not users: return await message.reply_text("⚠️ No users found.")
    
    text = f"🧍 **User List**\n📅 Generated: `{datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC`\n👥 Total Users: `{len(users)}`\n\n"
    data = "\n".join([f"{u['id']} - {u.get('name', 'Unknown')}" for u in users])
    
    file = io.BytesIO(data.encode()); file.name = "users_list.txt"
    await message.reply_document(document=file, caption=text)

@Client.on_message(filters.command("chats") & filters.user(ADMINS))
async def list_chats(bot: Client, message):
    chats = await db.get_all_chats()
    if not chats: return await message.reply_text("⚠️ No groups found.")
    
    groups = [c for c in chats if not str(c["id"]).startswith("-100")]
    supergroups = [c for c in chats if str(c["id"]).startswith("-100")]
    
    text = f"💬 **Group Chats**\n📅 Generated: `{datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC`\n🏘️ Total Chats: `{len(chats)}`\n👥 Groups: `{len(groups)}` | 📢 Supergroups: `{len(supergroups)}`\n\n"
    data = "\n".join([f"{c['id']} - {c.get('title', 'Unknown')}" for c in chats])
    
    file = io.BytesIO(data.encode()); file.name = "chats_list.txt"
    await message.reply_document(document=file, caption=text)

@Client.on_message(filters.command(["channel", "channels"]) & filters.user(ADMINS))
async def list_channels(bot: Client, message):
    chats = await db.get_all_chats()
    channels = [c for c in chats if str(c["id"]).startswith("-100")]
    if not channels: return await message.reply_text("⚠️ No channels found.")
    
    text = f"📢 **Channel List**\n📅 Generated: `{datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC`\n📺 Total Channels: `{len(channels)}`\n\n"
    data = "\n".join([f"{c['id']} - {c.get('title', 'Unknown')}" for c in channels])
    
    file = io.BytesIO(data.encode()); file.name = "channels_list.txt"
    await message.reply_document(document=file, caption=text)
