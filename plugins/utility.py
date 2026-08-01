import asyncio
import os
import shutil
import logging
from pyrogram import Client, enums, filters
from pyrogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from pyrogram.errors import FloodWait, InputUserDeactivated, PeerIdInvalid, UserIsBlocked
import info
from database.ia_filterdb import Media
from database.users_chats_db import db
from database.plugin_dbs import plugin_db

logger = logging.getLogger(__name__)

def get_size_str(bytes_size):
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if bytes_size < 1024.0: return f"{bytes_size:.2f} {unit}"
        bytes_size /= 1024.0

@Client.on_message(filters.command("server") & filters.user(info.ADMINS))
async def server_stats_cmd(bot: Client, message: Message):
    msg = await message.reply_text("⏳ **Fetching server statistics...**")
    total, used, free = shutil.disk_usage("/")
    text = f"💽 **Disk Total:** `{get_size_str(total)}`\n📀 **Disk Used:** `{get_size_str(used)}` (`{(used/total)*100:.1f}%`)\n💿 **Disk Free:** `{get_size_str(free)}`\n"
    await msg.edit_text(text)

@Client.on_message(filters.command("stats") & filters.user(info.ADMINS))
async def bot_stats_cmd(bot: Client, message: Message):
    status_msg = await message.reply_text("⏳ **Fetching Database Stats...**")
    total_users = await db.total_users_count()
    total_chats = await db.total_chat_count()
    total_files = await Media.count_documents()
    db_size = await db.get_db_size()
    
    stats_text = (
        "📊 **Bot Database Statistics**\n━━━━━━━━━━━━━━\n"
        f"👥 **Total Users:** `{total_users}`\n🏘 **Total Groups:** `{total_chats}`\n"
        f"📁 **Total Files:** `{total_files}`\n💾 **DB Size:** `{get_size_str(db_size)}`\n━━━━━━━━━━━━━━"
    )
    await status_msg.edit_text(stats_text)

@Client.on_message(filters.command("cleanusers") & filters.user(info.ADMINS))
async def clean_users_cmd(bot: Client, message: Message):
    status_msg = await message.reply_text("⏳ **Starting Deep Clean...** (Processing in background)")
    users = await db.get_all_users()
    active, blocked = 0, 0

    for i in range(0, len(users), 50):
        chunk = users[i:i + 50]
        async def check_user(u):
            try:
                await bot.send_chat_action(u["id"], enums.ChatAction.TYPING)
                return "active"
            except (UserIsBlocked, InputUserDeactivated, PeerIdInvalid):
                await db.delete_user(u["id"])
                return "blocked"
            except FloodWait as e:
                await asyncio.sleep(e.value)
                return "active"
            except Exception: return "active"
            
        results = await asyncio.gather(*[check_user(u) for u in chunk])
        active += results.count("active")
        blocked += results.count("blocked")
        
        if (i + len(chunk)) % 500 == 0:
            try: await status_msg.edit_text(f"⏳ **Cleaning:** `{i + len(chunk)}/{len(users)}`")
            except Exception: pass
        await asyncio.sleep(1.5)

    await status_msg.edit_text(f"✅ **Deep Clean Completed!**\n🟢 **Active:** `{active}`\n🔴 **Removed:** `{blocked}`")

@Client.on_message(filters.command("clearfsubusers") & filters.user(info.ADMINS))
async def clear_fsub_cmd(bot: Client, message: Message):
    await plugin_db.clear_fsub_users()
    await message.reply_text("✅ **Force Subscribe Database has been completely cleared.**")
