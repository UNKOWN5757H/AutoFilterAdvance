import asyncio
import os
import shutil
import platform
from logging import ERROR, getLogger

from pyrogram import Client, enums, filters
from pyrogram.errors import (
    FloodWait,
    InputUserDeactivated,
    PeerIdInvalid,
    UserIsBlocked,
    UserDeactivatedBan
)
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

import info

from database.ia_filterdb import Media as _Media
from database.plugin_dbs import plugin_db as _plugin_db
from database.users_chats_db import db as _db

logger = getLogger(__name__)
logger.setLevel(ERROR)

try:
    import psutil
except ImportError:
    psutil = None

# ============================================================
# 👑 FOOLPROOF ADMIN CHECKER
# ============================================================
def get_admin_list():
    raw_admins = getattr(info, "ADMINS", [])
    if isinstance(raw_admins, str): return [int(x) for x in raw_admins.replace(",", " ").split() if x.strip().lstrip("-").isdigit()]
    elif isinstance(raw_admins, int): return [raw_admins]
    elif isinstance(raw_admins, list): return [int(x) for x in raw_admins if str(x).strip().lstrip("-").isdigit()]
    return []

async def admin_check(_, __, message: Message):
    if not message.from_user: return False
    return message.from_user.id in get_admin_list()

async def cb_admin_check(_, __, query: CallbackQuery):
    if not query.from_user: return False
    return query.from_user.id in get_admin_list()

admin_filter = filters.create(admin_check)
cb_admin_filter = filters.create(cb_admin_check)

def get_size_str(bytes_size):
    if not bytes_size: return "0.00 B"
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if bytes_size < 1024.0: return f"{bytes_size:.2f} {unit}"
        bytes_size /= 1024.0
    return f"{bytes_size:.2f} PB"

# ============================================================
# 📜 LOGS COMMAND
# ============================================================
@Client.on_message(filters.command("logs") & admin_filter, group=3)
async def get_logs_cmd(bot: Client, message: Message):
    log_file = "TelegramBot.log"
    if not os.path.exists(log_file):
        return await message.reply_text("⚠️ **Log file not found!** No errors recorded yet.")
    try:
        await message.reply_document(document=log_file, caption="📜 **Here are the latest bot logs.**")
    except Exception as e:
        await message.reply_text(f"❌ **Failed to send logs:**\n`{e}`")


# ============================================================
# 🖥️ SERVER STATS (WITH 2-LAYER FALLBACK)
# ============================================================
@Client.on_message(filters.command("server") & admin_filter, group=3)
async def server_stats_cmd(bot: Client, message: Message):
    msg = await message.reply_text("⏳ **Fetching server statistics...**")
    text = "🖥 **Server Statistics**\n━━━━━━━━━━━━━━\n"
    
    # Layer 1: Try psutil for exact stats
    if psutil:
        try:
            cpu_pct = psutil.cpu_percent(interval=0.5)
            ram = psutil.virtual_memory()
            text += f"🧠 **CPU Usage:** `{cpu_pct}%`\n📉 **RAM Usage:** `{ram.percent}%`\n💾 **RAM Total:** `{get_size_str(ram.total)}`\n💿 **RAM Free:** `{get_size_str(ram.available)}`\n\n"
        except Exception: pass
    else:
        # Layer 2: Fallback to native OS stats if psutil is blocked
        text += f"🧠 **CPU Cores:** `{os.cpu_count()}`\n💻 **OS System:** `{platform.system()} {platform.release()}`\n\n"

    try:
        total, used, free = shutil.disk_usage("/")
        text += f"💽 **Disk Total:** `{get_size_str(total)}`\n📀 **Disk Used:** `{get_size_str(used)}` (`{(used/total)*100:.1f}%`)\n💿 **Disk Free:** `{get_size_str(free)}`\n"
    except Exception: pass
    
    text += "━━━━━━━━━━━━━━"
    await msg.edit_text(text)


# ============================================================
# ♻️ RESTART COMMAND
# ============================================================
@Client.on_message(filters.command("restart") & admin_filter, group=3)
async def restart_bot_cmd(bot: Client, message: Message):
    await message.reply_text(
        "⚠️ **Are you sure you want to restart the bot?**",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Confirm Restart", callback_data="util_restart")]])
    )

@Client.on_callback_query(filters.regex("^util_restart$") & cb_admin_filter, group=3)
async def confirm_restart_cb(bot: Client, query: CallbackQuery):
    await query.answer("♻️ Restarting...", show_alert=True)
    msg = await query.edit_message_text("♻️ **Bot is restarting... Please wait.**")
    try:
        with open("restart.txt", "w") as f:
            f.write(f"{msg.chat.id}\n{msg.id}")
    except Exception: pass
    await asyncio.sleep(2)
    os._exit(1)


# ============================================================
# 📊 BOT DATABASE STATS
# ============================================================
@Client.on_message(filters.command("stats") & admin_filter, group=3)
async def bot_stats_cmd(bot: Client, message: Message):
    status_msg = await message.reply_text("⏳ **Fetching Database Stats...**")
    try:
        total_users = await _db.total_users_count()
        total_chats = await _db.total_chat_count()
        
        # Layer 1 for counting files
        try: total_files = await _Media.count_documents({})
        except: 
            # Layer 2 fallback
            try: total_files = await _Media.count_documents()
            except: total_files = "Unknown"

        db_size = await _db.get_db_size()
        
        stats_text = (
            f"📊 **Bot Database Statistics**\n━━━━━━━━━━━━━━\n"
            f"👥 **Total Users:** `{total_users}`\n"
            f"🏘 **Total Groups:** `{total_chats}`\n"
            f"📁 **Total Files:** `{total_files}`\n"
            f"💾 **DB Size:** `{get_size_str(db_size)}`\n━━━━━━━━━━━━━━"
        )
        await status_msg.edit_text(stats_text)
    except Exception as e:
        await status_msg.edit_text(f"❌ **Error fetching stats:** `{e}`")


@Client.on_message(filters.command("total") & admin_filter, group=3)
async def total_files_cmd(bot: Client, message: Message):
    msg = await message.reply_text("⏳ **Calculating total files in database...**")
    try: total = await _Media.count_documents({})
    except:
        try: total = await _Media.count_documents()
        except: total = "Error"
    await msg.edit_text(f"📁 **Total Files in Database:** `{total}`")


# ============================================================
# 🧹 DEEP CLEAN USERS (BULLETPROOF VERSION)
# ============================================================
@Client.on_message(filters.command("cleanusers") & admin_filter, group=3)
async def clean_users_cmd(bot: Client, message: Message):
    status_msg = await message.reply_text("⏳ **Starting Deep Clean...** (This is a safe background process)")
    
    try:
        users_cursor = await _db.get_all_users()
        users = await users_cursor.to_list(length=None) if hasattr(users_cursor, "to_list") else list(users_cursor)
    except Exception as e:
        return await status_msg.edit_text(f"❌ **Failed to fetch users:** `{e}`")

    active, blocked = 0, 0
    total_users = len(users)

    async def check_user(u):
        user_id = u.get("id") or u.get("user_id")
        if not user_id: return "blocked"
        try:
            await bot.send_chat_action(user_id, enums.ChatAction.TYPING)
            return "active"
        except FloodWait as e:
            await asyncio.sleep(e.value + 1)
            return "active" # Assume active if we got floodwaited
        except (UserIsBlocked, InputUserDeactivated, PeerIdInvalid, UserDeactivatedBan):
            await _db.delete_user(user_id)
            return "blocked"
        except Exception: return "active" # If unknown error, keep user safe

    # Process in safe chunks to avoid crashing bot memory
    for i in range(0, total_users, 30):
        chunk = users[i : i + 30]
        results = await asyncio.gather(*[check_user(u) for u in chunk])
        
        active += results.count("active")
        blocked += results.count("blocked")
        
        # Update message every 300 users
        if (i + len(chunk)) % 300 == 0 or (i + len(chunk)) == total_users:
            try: await status_msg.edit_text(f"⏳ **Cleaning Database...**\nScanned: `{i + len(chunk)} / {total_users}`")
            except Exception: pass
            
        await asyncio.sleep(2) # 2 Second delay prevents Telegram API Bans

    await status_msg.edit_text(f"✅ **Deep Clean Completed!**\n\n🟢 **Active Users Kept:** `{active}`\n🔴 **Dead Accounts Removed:** `{blocked}`")


# ============================================================
# 🔥 DATABASE WIPE COMMANDS (DANGEROUS)
# ============================================================
@Client.on_message(filters.command("clearfiles") & admin_filter, group=3)
async def clear_files_cmd(bot: Client, message: Message):
    await message.reply_text(
        "⚠️ **WARNING!** ⚠️\nDelete **ALL** files indexed in your database?",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔥 YES, DELETE ALL FILES", callback_data="nuke_files")],
            [InlineKeyboardButton("❌ Cancel", callback_data="close_data")]
        ])
    )

@Client.on_message(filters.command("clearusers") & admin_filter, group=3)
async def clear_users_cmd(bot: Client, message: Message):
    await message.reply_text(
        "⚠️ **WARNING!** ⚠️\nDelete **ALL** users from your database?",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔥 YES, DELETE ALL USERS", callback_data="nuke_users")],
            [InlineKeyboardButton("❌ Cancel", callback_data="close_data")]
        ])
    )

@Client.on_message(filters.command("clearfsubusers") & admin_filter, group=3)
async def clear_fsub_cmd(bot: Client, message: Message):
    await message.reply_text(
        "⚠️ **WARNING!** ⚠️\nClear the Force Sub Database?",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔥 YES, CLEAR FSUB", callback_data="nuke_fsub")],
            [InlineKeyboardButton("❌ Cancel", callback_data="close_data")]
        ])
    )

@Client.on_callback_query(filters.regex(r"^nuke_(files|users|fsub)$") & cb_admin_filter, group=3)
async def nuke_callbacks(bot: Client, query: CallbackQuery):
    await query.answer("Processing request...", show_alert=False)
    action = query.data.split("_")[1]
    await query.message.edit_text("⏳ **Executing request... This may take a moment.**")
    
    try:
        if action == "files":
            try: res = await _Media.collection.delete_many({})
            except: res = await _Media.delete_many({})
            count = res.deleted_count if hasattr(res, "deleted_count") else "All"
            await query.message.edit_text(f"✅ **Database Wiped!**\n🗑 **Deleted Files:** `{count}`")
            
        elif action == "users":
            try: res = await _db.col.delete_many({})
            except: res = await _db.delete_many({})
            count = res.deleted_count if hasattr(res, "deleted_count") else "All"
            await query.message.edit_text(f"✅ **Database Wiped!**\n🗑 **Deleted Users:** `{count}`")
            
        elif action == "fsub":
            await _plugin_db.clear_fsub_users()
            await query.message.edit_text("✅ **Force Subscribe Database has been completely cleared.**")
            
    except Exception as e:
        logger.exception(f"Error during nuke_{action}")
        await query.message.edit_text(f"❌ **Error occurred:**\n`{e}`")
