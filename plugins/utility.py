import asyncio
import datetime
import logging
import os
import shutil
import sys
import time

from pyrogram import Client, enums, filters
from pyrogram.errors import (
    FloodWait,
    InputUserDeactivated,
    PeerIdInvalid,
    UserIsBlocked,
)
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

import info
from database.ia_filterdb import Media
from database.users_chats_db import db
from plugins.fsub import fsub_db

logger = logging.getLogger(__name__)

try:
    import psutil
except ImportError:
    psutil = None
    logger.warning(
        "psutil is not installed. /server command will have limited functionality."
    )


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
            document=log_file, caption="📜 **Here are the latest bot logs.**"
        )
    except Exception as e:
        await message.reply_text(f"❌ **Failed to send logs:**\n`{e}`")


# ============================================================
# 🖥 Get Server Stats
# ============================================================
def get_size_str(bytes_size):
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if bytes_size < 1024.0:
            return f"{bytes_size:.2f} {unit}"
        bytes_size /= 1024.0


@Client.on_message(filters.command("server") & filters.user(info.ADMINS))
async def server_stats_cmd(bot: Client, message: Message):
    msg = await message.reply_text("⏳ **Fetching server statistics...**")
    text = "🖥 **Server Statistics**\n\n"

    if psutil:
        cpu_pct = psutil.cpu_percent(interval=0.5)
        ram = psutil.virtual_memory()
        text += f"🧠 **CPU Usage:** `{cpu_pct}%`\n"
        text += f"📉 **RAM Usage:** `{ram.percent}%`\n"
        text += f"💾 **RAM Total:** `{get_size_str(ram.total)}`\n"
        text += f"💿 **RAM Free:** `{get_size_str(ram.available)}`\n\n"
    else:
        text += "⚠️ `psutil` not installed. Cannot fetch CPU/RAM.\n\n"

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
    await message.reply_text(
        "⚠️ **Are you sure you want to restart the bot?**",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("✅ Confirm Restart", callback_data="util_restart")]]
        ),
    )


@Client.on_callback_query(filters.regex("^util_restart$") & filters.user(info.ADMINS))
async def confirm_restart_cb(bot: Client, query: CallbackQuery):
    await query.answer("♻️ Restarting...", show_alert=True)
    msg = await query.edit_message_text("♻️ **Bot is restarting... Please wait.**")
    with open("restart.txt", "w") as f:
        f.write(f"{msg.chat.id}\n{msg.id}")
    await asyncio.sleep(2)
    os._exit(1)


# ============================================================
# 📊 Get Bot User Stats (INSTANT)
# ============================================================
@Client.on_message(filters.command("stats") & filters.user(info.ADMINS))
async def bot_stats_cmd(bot: Client, message: Message):
    status_msg = await message.reply_text("⏳ **Fetching Database Stats...**")

    total_users = await db.total_users_count()
    total_chats = await db.total_chat_count()
    total_files = await Media.count_documents()
    db_size = await db.get_db_size()
    db_size_str = get_size_str(db_size)

    stats_text = (
        "📊 **Bot Database Statistics**\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 **Total Users:** `{total_users}`\n"
        f"🏘 **Total Groups:** `{total_chats}`\n"
        f"📁 **Total Files:** `{total_files}`\n"
        f"💾 **DB Size:** `{db_size_str}`\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "💡 *Tip: To check for and remove dead/blocked accounts, use `/cleanusers`*"
    )
    await status_msg.edit_text(stats_text)


# ============================================================
# 🧹 Deep Clean Users (BACKGROUND CHECKER)
# ============================================================
@Client.on_message(filters.command("cleanusers") & filters.user(info.ADMINS))
async def clean_users_cmd(bot: Client, message: Message):
    status_msg = await message.reply_text(
        "⏳ **Starting Deep Clean...**\n*This will take time due to Telegram API limits. The bot will process this in the background.*"
    )

    users = await db.get_all_users()
    total_users = await db.total_users_count()

    active_users = 0
    blocked_users = 0
    deleted_accounts = 0

    # Process in optimized batches of 50 to speed it up without triggering major flood limits
    chunk_size = 50
    for i in range(0, len(users), chunk_size):
        chunk = users[i : i + chunk_size]

        async def check_user(user):
            user_id = user.get("id")
            try:
                await bot.send_chat_action(user_id, enums.ChatAction.TYPING)
                return "active"
            except UserIsBlocked:
                await db.delete_user(user_id)
                return "blocked"
            except InputUserDeactivated:
                await db.delete_user(user_id)
                return "deleted"
            except PeerIdInvalid:
                await db.delete_user(user_id)
                return "deleted"
            except FloodWait as e:
                await asyncio.sleep(e.value)
                return "active"
            except Exception:
                return "active"

        results = await asyncio.gather(*[check_user(u) for u in chunk])

        for res in results:
            if res == "active":
                active_users += 1
            elif res == "blocked":
                blocked_users += 1
            elif res == "deleted":
                deleted_accounts += 1

        processed = i + len(chunk)
        if processed % 500 == 0 or processed == total_users:
            try:
                await status_msg.edit_text(
                    f"⏳ **Cleaning users:** `{processed} / {total_users}`"
                )
            except:
                pass

        # Mandatory sleep to respect Telegram's limits
        await asyncio.sleep(1.5)

    stats_text = (
        "✅ **Deep Clean Completed!**\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 **Total Users (Before):** `{total_users}`\n"
        f"🟢 **Active Users:** `{active_users}`\n"
        f"🔴 **Removed Blocked:** `{blocked_users}`\n"
        f"💀 **Removed Deleted:** `{deleted_accounts}`\n"
        "━━━━━━━━━━━━━━━━━━━━━"
    )
    await status_msg.edit_text(stats_text)


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
@Client.on_message(filters.command("clearfiles") & filters.user(info.ADMINS))
async def clear_files_cmd(bot: Client, message: Message):
    await message.reply_text(
        "⚠️ **WARNING!** ⚠️\nThis will permanently delete **ALL** files indexed in your database.\n\nAre you absolutely sure?",
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "🔥 YES, DELETE ALL FILES", callback_data="nuke_files"
                    )
                ],
                [InlineKeyboardButton("❌ Cancel", callback_data="close_data")],
            ]
        ),
    )


@Client.on_message(filters.command("clearusers") & filters.user(info.ADMINS))
async def clear_users_cmd(bot: Client, message: Message):
    await message.reply_text(
        "⚠️ **WARNING!** ⚠️\nThis will permanently delete **ALL** users from your database. (Bot stats will reset to 0)\n\nAre you absolutely sure?",
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "🔥 YES, DELETE ALL USERS", callback_data="nuke_users"
                    )
                ],
                [InlineKeyboardButton("❌ Cancel", callback_data="close_data")],
            ]
        ),
    )


@Client.on_message(filters.command("clearfsubusers") & filters.user(info.ADMINS))
async def clear_fsub_cmd(bot: Client, message: Message):
    await message.reply_text(
        "⚠️ **WARNING!** ⚠️\nThis will clear the Force Sub DB. Everyone will have to rejoin the channels.\n\nAre you sure?",
        reply_markup=InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("🔥 YES, CLEAR FSUB", callback_data="nuke_fsub")],
                [InlineKeyboardButton("❌ Cancel", callback_data="close_data")],
            ]
        ),
    )


@Client.on_callback_query(
    filters.regex(r"^nuke_(files|users|fsub)$") & filters.user(info.ADMINS)
)
async def nuke_callbacks(bot: Client, query: CallbackQuery):
    action = query.data.split("_")[1]
    await query.answer("Wiping database... please wait.", show_alert=True)
    await query.message.edit_text("⏳ **Executing request... This may take a moment.**")

    try:
        if action == "files":
            res = await Media.collection.delete_many({})
            await query.message.edit_text(
                f"✅ **Database Wiped!**\n🗑 **Deleted Files:** `{res.deleted_count}`"
            )
        elif action == "users":
            res = await db.col.delete_many({})
            await query.message.edit_text(
                f"✅ **Database Wiped!**\n🗑 **Deleted Users:** `{res.deleted_count}`"
            )
        elif action == "fsub":
            await fsub_db.clear_all()
            await query.message.edit_text(
                "✅ **Force Subscribe Database has been completely cleared.**"
            )
    except Exception as e:
        logger.exception(f"Error during nuke_{action}")
        await query.message.edit_text(f"❌ **Error occurred:**\n`{e}`")
