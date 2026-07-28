import os
import sys
import time
import shutil
import asyncio
import logging
import datetime

from pyrogram import Client, filters, enums
from pyrogram.errors import (
    FloodWait, 
    UserIsBlocked, 
    InputUserDeactivated, 
    PeerIdInvalid
)
from pyrogram.types import (
    Message, 
    InlineKeyboardMarkup, 
    InlineKeyboardButton, 
    CallbackQuery
)

import info
from database.users_chats_db import db
from database.ia_filterdb import Media
from plugins.fsub import fsub_db  # Imports the FSubDB instance we created earlier

logger = logging.getLogger(__name__)

try:
    import psutil
except ImportError:
    psutil = None
    logger.warning("psutil is not installed. /server command will have limited functionality.")

# ============================================================
# 📜 Get Bot Logs
# ============================================================
@Client.on_message(filters.command("logs") & filters.user(info.ADMINS))
async def get_logs_cmd(bot: Client, message: Message):
    log_file = "TelegramBot.log"
    
    if not os.path.exists(log_file):
        return await message.reply_text("⚠️ **Log file not found!**")
        
    try:
        await message.reply_document(
            document=log_file,
            caption="📜 **Here are the latest bot logs.**"
        )
    except Exception as e:
        await message.reply_text(f"❌ **Failed to send logs:**\n`{e}`")


# ============================================================
# 🖥 Get Server Stats
# ============================================================
def get_size_str(bytes_size):
    """Helper to convert bytes to readable format."""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_size < 1024.0:
            return f"{bytes_size:.2f} {unit}"
        bytes_size /= 1024.0

@Client.on_message(filters.command("server") & filters.user(info.ADMINS))
async def server_stats_cmd(bot: Client, message: Message):
    msg = await message.reply_text("⏳ **Fetching server statistics...**")
    
    text = "🖥 **Server Statistics**\n\n"
    
    if psutil:
        # CPU & RAM
        cpu_pct = psutil.cpu_percent(interval=0.5)
        ram = psutil.virtual_memory()
        
        text += f"🧠 **CPU Usage:** `{cpu_pct}%`\n"
        text += f"📉 **RAM Usage:** `{ram.percent}%`\n"
        text += f"💾 **RAM Total:** `{get_size_str(ram.total)}`\n"
        text += f"💿 **RAM Free:** `{get_size_str(ram.available)}`\n\n"
    else:
        text += "⚠️ `psutil` not installed. Cannot fetch CPU/RAM.\n\n"

    # Disk Status
    total, used, free = shutil.disk_usage("/")
    text += f"💽 **Disk Total:** `{get_size_str(total)}`\n"
    text += f"📀 **Disk Used:** `{get_size_str(used)}` (`{(used/total)*100:.1f}%`)\n"
    text += f"💿 **Disk Free:** `{get_size_str(free)}`\n"
    
    await msg.edit_text(text)


# ============================================================
# ♻️ Restart Bot
# ============================================================
@Client.on_message(filters.command("restart") & filters.user(info.ADMINS))
async def restart_bot_cmd(bot: Client, message: Message):
    msg = await message.reply_text(
        "⚠️ **Are you sure you want to restart the bot?**",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Confirm Restart", callback_data="util_restart")]
        ])
    )

@Client.on_callback_query(filters.regex("^util_restart$") & filters.user(info.ADMINS))
async def confirm_restart_cb(bot: Client, query: CallbackQuery):
    await query.answer("♻️ Restarting...", show_alert=True)
    msg = await query.edit_message_text("♻️ **Bot is restarting... Please wait.**")
    
    # Save context to edit the message after restart
    with open("restart.txt", "w") as f:
        f.write(f"{msg.chat.id}\n{msg.id}")
        
    await asyncio.sleep(2)
    os._exit(1)


# ============================================================
# 📊 Get Bot User Stats (With Active Check)
# ============================================================
@Client.on_message(filters.command("stats") & filters.user(info.ADMINS))
async def bot_stats_cmd(bot: Client, message: Message):
    status_msg = await message.reply_text("⏳ **Checking active users in database... This might take a while depending on your DB size.**")
    
    users = await db.get_all_users()
    total_users = await db.total_users_count()
    
    active_users = 0
    blocked_users = 0
    deleted_accounts = 0
    processed = 0

    for user in users:
        user_id = user.get("id")
        try:
            # Send a typing action to verify if the user is active without spamming them
            await bot.send_chat_action(user_id, enums.ChatAction.TYPING)
            active_users += 1
        except UserIsBlocked:
            blocked_users += 1
            await db.delete_user(user_id) # Optional: Remove blocked users from DB
        except InputUserDeactivated:
            deleted_accounts += 1
            await db.delete_user(user_id) # Optional: Remove deleted accounts from DB
        except PeerIdInvalid:
            deleted_accounts += 1
            await db.delete_user(user_id)
        except FloodWait as e:
            await asyncio.sleep(e.value)
            active_users += 1 # Assume active if it's just a floodwait
        except Exception:
            # Assume active for other minor errors to be safe
            active_users += 1
            
        processed += 1
        # Update progress every 100 users to avoid rate limits on edit_message
        if processed % 100 == 0:
            try:
                await status_msg.edit_text(f"⏳ **Checking users:** `{processed} / {total_users}`")
            except:
                pass
            
    stats_text = (
        "📊 **Bot Database Statistics**\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 **Total Users (Before):** `{total_users}`\n"
        f"🟢 **Active Users:** `{active_users}`\n"
        f"🔴 **Blocked Bot:** `{blocked_users}`\n"
        f"💀 **Deleted Accounts:** `{deleted_accounts}`\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "*(Note: Inactive/Blocked users have been automatically pruned from the database)*"
    )
    
    await status_msg.edit_text(stats_text)


# ============================================================
# 📢 Broadcast Message
# ============================================================
@Client.on_message(filters.command("broadcast") & filters.user(info.ADMINS))
async def broadcast_cmd(bot: Client, message: Message):
    if not message.reply_to_message:
        return await message.reply_text("⚠️ **Please reply to a message you want to broadcast.**")
        
    b_msg = message.reply_to_message
    status_msg = await message.reply_text("⏳ **Broadcast Started...**")
    
    users = await db.get_all_users()
    total_users = await db.total_users_count()
    
    successful = 0
    blocked = 0
    deleted = 0
    failed = 0
    
    for user in users:
        user_id = user.get("id")
        try:
            await b_msg.copy(chat_id=user_id)
            successful += 1
        except FloodWait as e:
            await asyncio.sleep(e.value)
            await b_msg.copy(chat_id=user_id)
            successful += 1
        except UserIsBlocked:
            blocked += 1
            await db.delete_user(user_id)
        except InputUserDeactivated:
            deleted += 1
            await db.delete_user(user_id)
        except PeerIdInvalid:
            deleted += 1
            await db.delete_user(user_id)
        except Exception:
            failed += 1
            
        # Optional: Add a tiny sleep to prevent massive floodwaits
        await asyncio.sleep(0.1)
            
    text = (
        "📢 **Broadcast Completed!**\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 **Total Users:** `{total_users}`\n"
        f"✅ **Successful:** `{successful}`\n"
        f"🚫 **Blocked:** `{blocked}`\n"
        f"💀 **Deleted Accounts:** `{deleted}`\n"
        f"❌ **Failed:** `{failed}`"
    )
    await status_msg.edit_text(text)


# ============================================================
# 📁 Total DB Files
# ============================================================
@Client.on_message(filters.command("total") & filters.user(info.ADMINS))
async def total_files_cmd(bot: Client, message: Message):
    msg = await message.reply_text("⏳ **Calculating total files in database...**")
    try:
        total = await Media.count_documents()
        await msg.edit_text(f"📁 **Total Files in Database:** `{total}`")
    except Exception as e:
        await msg.edit_text(f"❌ **Error fetching total files:**\n`{e}`")


# ============================================================
# 🗑 Clear/Nuke Commands (With Confirmations)
# ============================================================

# 1. Clear Files
@Client.on_message(filters.command("clearfiles") & filters.user(info.ADMINS))
async def clear_files_cmd(bot: Client, message: Message):
    await message.reply_text(
        "⚠️ **WARNING!** ⚠️\nThis will permanently delete **ALL** files indexed in your database.\n\nAre you absolutely sure?",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔥 YES, NUKE FILES", callback_data="nuke_files")],
            [InlineKeyboardButton("❌ Cancel", callback_data="close_data")]
        ])
    )

# 2. Clear Users
@Client.on_message(filters.command("clearusers") & filters.user(info.ADMINS))
async def clear_users_cmd(bot: Client, message: Message):
    await message.reply_text(
        "⚠️ **WARNING!** ⚠️\nThis will permanently delete **ALL** users from your database. (Bot stats will reset to 0)\n\nAre you absolutely sure?",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔥 YES, NUKE USERS", callback_data="nuke_users")],
            [InlineKeyboardButton("❌ Cancel", callback_data="close_data")]
        ])
    )

# 3. Clear ForceSub Users
@Client.on_message(filters.command("clearfsubusers") & filters.user(info.ADMINS))
async def clear_fsub_cmd(bot: Client, message: Message):
    await message.reply_text(
        "⚠️ **WARNING!** ⚠️\nThis will clear the Force Sub DB. Everyone will have to rejoin the channels.\n\nAre you sure?",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔥 YES, CLEAR FSUB", callback_data="nuke_fsub")],
            [InlineKeyboardButton("❌ Cancel", callback_data="close_data")]
        ])
    )

# Nuke Callbacks
@Client.on_callback_query(filters.regex(r"^nuke_(files|users|fsub)$") & filters.user(info.ADMINS))
async def nuke_callbacks(bot: Client, query: CallbackQuery):
    action = query.data.split("_")[1]
    
    await query.message.edit_text("⏳ **Executing request... This may take a moment.**")
    
    try:
        if action == "files":
            res = await Media.collection.delete_many({})
            await query.message.edit_text(f"✅ **Database Wiped!**\n🗑 **Deleted Files:** `{res.deleted_count}`")
            
        elif action == "users":
            # Accessing the motor collection directly from users_chats_db
            res = await db.col.delete_many({})
            await query.message.edit_text(f"✅ **Database Wiped!**\n🗑 **Deleted Users:** `{res.deleted_count}`")
            
        elif action == "fsub":
            await fsub_db.clear_all()
            await query.message.edit_text("✅ **Force Subscribe Database has been completely cleared.**")
            
    except Exception as e:
        logger.exception(f"Error during nuke_{action}")
        await query.message.edit_text(f"❌ **Error occurred:**\n`{e}`")
