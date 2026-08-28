import asyncio
import os
import shutil
from logging import ERROR, getLogger

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
from database.plugin_dbs import plugin_db
from database.users_chats_db import db

logger = getLogger(__name__)
logger.setLevel(ERROR)

try:
    import psutil
except ImportError:
    psutil = None


def get_admin_list():
    raw_admins = getattr(info, "ADMINS", [])
    if isinstance(raw_admins, str):
        return [x.strip() for x in raw_admins.replace(",", " ").split() if x.strip()]
    elif isinstance(raw_admins, int):
        return [str(raw_admins)]
    elif isinstance(raw_admins, list):
        return [str(a) for a in raw_admins]
    return []


async def admin_check(_, __, message: Message):
    if not message.from_user:
        return False
    return str(message.from_user.id) in get_admin_list()


admin_filter = filters.create(admin_check)


async def cb_admin_check(_, __, query: CallbackQuery):
    if not query.from_user:
        return False
    return str(query.from_user.id) in get_admin_list()


cb_admin_filter = filters.create(cb_admin_check)


def get_size_str(bytes_size):
    if not bytes_size:
        return "0.00 B"
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if bytes_size < 1024.0:
            return f"{bytes_size:.2f} {unit}"
        bytes_size /= 1024.0
    return f"{bytes_size:.2f} PB"


@Client.on_message(
    filters.command("logs") & admin_filter & (filters.private | filters.group), group=3
)
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


@Client.on_message(
    filters.command("server") & admin_filter & (filters.private | filters.group),
    group=3,
)
async def server_stats_cmd(bot: Client, message: Message):
    msg = await message.reply_text("⏳ **Fetching server statistics...**")
    text = "🖥 **Server Statistics**\n\n"
    if psutil:
        cpu_pct = psutil.cpu_percent(interval=None)
        ram = psutil.virtual_memory()
        text += f"🧠 **CPU Usage:** `{cpu_pct}%`\n📉 **RAM Usage:** `{ram.percent}%`\n💾 **RAM Total:** `{get_size_str(ram.total)}`\n💿 **RAM Free:** `{get_size_str(ram.available)}`\n\n"
    total, used, free = shutil.disk_usage("/")
    text += f"💽 **Disk Total:** `{get_size_str(total)}`\n📀 **Disk Used:** `{get_size_str(used)}` (`{(used/total)*100:.1f}%`)\n💿 **Disk Free:** `{get_size_str(free)}`\n"
    await msg.edit_text(text)


@Client.on_message(
    filters.command("restart") & admin_filter & (filters.private | filters.group),
    group=3,
)
async def restart_bot_cmd(bot: Client, message: Message):
    await message.reply_text(
        "⚠️ **Are you sure you want to restart the bot?**",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("✅ Confirm Restart", callback_data="util_restart")]]
        ),
    )


@Client.on_callback_query(filters.regex("^util_restart$") & cb_admin_filter, group=3)
async def confirm_restart_cb(bot: Client, query: CallbackQuery):
    await query.answer("♻️ Restarting...", show_alert=True)
    msg = await query.edit_message_text("♻️ **Bot is restarting... Please wait.**")
    with open("restart.txt", "w") as f:
        f.write(f"{msg.chat.id}\n{msg.id}")
    await asyncio.sleep(2)
    os._exit(1)


@Client.on_message(
    filters.command("stats") & admin_filter & (filters.private | filters.group), group=3
)
async def bot_stats_cmd(bot: Client, message: Message):
    status_msg = await message.reply_text("⏳ **Fetching Database Stats...**")
    total_users = await db.total_users_count()
    total_chats = await db.total_chat_count()
    total_files = await Media.count_documents()
    db_size = await db.get_db_size()
    stats_text = f"📊 **Bot Database Statistics**\n━━━━━━━━━━━━━━\n👥 **Total Users:** `{total_users}`\n🏘 **Total Groups:** `{total_chats}`\n📁 **Total Files:** `{total_files}`\n💾 **DB Size:** `{get_size_str(db_size)}`\n━━━━━━━━━━━━━━"
    await status_msg.edit_text(stats_text)


@Client.on_message(
    filters.command("cleanusers") & admin_filter & (filters.private | filters.group),
    group=3,
)
async def clean_users_cmd(bot: Client, message: Message):
    status_msg = await message.reply_text(
        "⏳ **Starting Deep Clean...** (Processing in background)"
    )
    users = await db.get_all_users()
    if not isinstance(users, list):
        try:
            users = await users.to_list(length=None)
        except AttributeError:
            users = list(users)
    active, blocked = 0, 0
    for i in range(0, len(users), 50):
        chunk = users[i : i + 50]

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
            except Exception:
                return "active"

        results = await asyncio.gather(*[check_user(u) for u in chunk])
        active += results.count("active")
        blocked += results.count("blocked")
        if (i + len(chunk)) % 500 == 0:
            try:
                await status_msg.edit_text(
                    f"⏳ **Cleaning:** `{i + len(chunk)}/{len(users)}`"
                )
            except Exception:
                pass
        await asyncio.sleep(1.5)
    await status_msg.edit_text(
        f"✅ **Deep Clean Completed!**\n🟢 **Active:** `{active}`\n🔴 **Removed:** `{blocked}`"
    )


@Client.on_message(
    filters.command("total") & admin_filter & (filters.private | filters.group), group=3
)
async def total_files_cmd(bot: Client, message: Message):
    msg = await message.reply_text("⏳ **Calculating total files in database...**")
    total = await Media.count_documents()
    await msg.edit_text(f"📁 **Total Files in Database:** `{total}`")


@Client.on_message(
    filters.command("clearfiles") & admin_filter & (filters.private | filters.group),
    group=3,
)
async def clear_files_cmd(bot: Client, message: Message):
    await message.reply_text(
        "⚠️ **WARNING!** ⚠️\nDelete **ALL** files indexed in your database?",
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


@Client.on_message(
    filters.command("clearusers") & admin_filter & (filters.private | filters.group),
    group=3,
)
async def clear_users_cmd(bot: Client, message: Message):
    await message.reply_text(
        "⚠️ **WARNING!** ⚠️\nDelete **ALL** users from your database?",
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


@Client.on_message(
    filters.command("clearfsubusers")
    & admin_filter
    & (filters.private | filters.group),
    group=3,
)
async def clear_fsub_cmd(bot: Client, message: Message):
    await message.reply_text(
        "⚠️ **WARNING!** ⚠️\nClear the Force Sub DB?",
        reply_markup=InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("🔥 YES, CLEAR FSUB", callback_data="nuke_fsub")],
                [InlineKeyboardButton("❌ Cancel", callback_data="close_data")],
            ]
        ),
    )


@Client.on_callback_query(
    filters.regex(r"^nuke_(files|users|fsub)$") & cb_admin_filter, group=3
)
async def nuke_callbacks(bot: Client, query: CallbackQuery):
    await query.answer("Processing request...", show_alert=False)
    action = query.data.split("_")[1]
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
            await plugin_db.clear_fsub_users()
            await query.message.edit_text(
                "✅ **Force Subscribe Database has been completely cleared.**"
            )
    except Exception as e:
        logger.exception(f"Error during nuke_{action}")
        await query.message.edit_text(f"❌ **Error occurred:**\n`{e}`")
