import asyncio
import os
import platform
import shutil
import sys
from logging import ERROR, getLogger

from pyrogram import Client, enums, filters
from pyrogram.errors import (
    FloodWait,
    InputUserDeactivated,
    PeerIdInvalid,
    UserDeactivatedBan,
    UserIsBlocked,
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
# 👑 FULL POWER ADMIN CHECKER (GLOBAL + CHAT + ANONYMOUS)
# ============================================================
def get_admin_list():
    raw_admins = getattr(info, "ADMINS", [])
    if isinstance(raw_admins, (str, int)):
        raw_admins = str(raw_admins).replace(",", " ").split()
    return [int(x) for x in raw_admins if str(x).strip().lstrip("-").isdigit()]


async def is_user_admin(client: Client, message: Message):
    admin_list = get_admin_list()

    # 1. Global Admin Check (Direct User)
    if message.from_user and message.from_user.id in admin_list:
        return True

    # 2. Global Admin Check (Anonymous/Channel sending as Chat)
    if message.sender_chat and message.sender_chat.id in admin_list:
        return True

    # 3. Group Admin Check (Normal & Anonymous Admins)
    if message.chat and message.chat.type in [
        enums.ChatType.GROUP,
        enums.ChatType.SUPERGROUP,
    ]:
        # If the sender is the group itself, it's a Group Anonymous Admin
        if message.sender_chat and message.sender_chat.id == message.chat.id:
            return True

        # If it's a Normal Admin in this group
        if message.from_user:
            try:
                member = await client.get_chat_member(
                    message.chat.id, message.from_user.id
                )
                return member.status in [
                    enums.ChatMemberStatus.ADMINISTRATOR,
                    enums.ChatMemberStatus.OWNER,
                ]
            except Exception:
                pass

    return False


async def admin_check(_, client: Client, message: Message):
    return await is_user_admin(client, message)


async def cb_admin_check(_, client: Client, query: CallbackQuery):
    return await is_user_admin(client, query.message)


admin_filter = filters.create(admin_check)
cb_admin_filter = filters.create(cb_admin_check)


def get_size_str(bytes_size):
    if not bytes_size:
        return "0.00 B"
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if bytes_size < 1024.0:
            return f"{bytes_size:.2f} {unit}"
        bytes_size /= 1024.0
    return f"{bytes_size:.2f} PB"


# ============================================================
# 📜 LOGS COMMAND
# ============================================================
@Client.on_message(filters.command("logs") & admin_filter, group=3)
async def get_logs_cmd(bot: Client, message: Message):
    log_file = "TelegramBot.log"
    if not os.path.exists(log_file):
        return await message.reply_text(
            "⚠️ **Log file not found!** No errors recorded yet."
        )

    try:
        await message.reply_document(
            document=log_file, caption="📜 **Here are the latest bot logs.**"
        )
    except Exception as e:
        await message.reply_text(f"❌ **Failed to send logs:**\n`{e}`")


# ============================================================
# 🖥️ SERVER STATS
# ============================================================
@Client.on_message(filters.command("server") & admin_filter, group=3)
async def server_stats_cmd(bot: Client, message: Message):
    msg = await message.reply_text("⏳ **Fetching server statistics...**")
    text = "🖥 **Server Statistics**\n━━━━━━━━━━━━━━\n"

    if psutil:
        cpu_pct = psutil.cpu_percent(interval=0.5)
        ram = psutil.virtual_memory()
        text += f"🧠 **CPU Usage:** `{cpu_pct}%`\n📉 **RAM Usage:** `{ram.percent}%`\n💾 **RAM Total:** `{get_size_str(ram.total)}`\n💿 **RAM Free:** `{get_size_str(ram.available)}`\n\n"
    else:
        text += f"🧠 **CPU Cores:** `{os.cpu_count()}`\n💻 **OS System:** `{platform.system()} {platform.release()}`\n\n"

    total, used, free = shutil.disk_usage("/")
    text += f"💽 **Disk Total:** `{get_size_str(total)}`\n📀 **Disk Used:** `{get_size_str(used)}` (`{(used/total)*100:.1f}%`)\n💿 **Disk Free:** `{get_size_str(free)}`\n━━━━━━━━━━━━━━"

    await msg.edit_text(text)


# ============================================================
# ♻️ RESTART COMMAND (Optimized with OS Exec)
# ============================================================
@Client.on_message(filters.command("restart") & admin_filter, group=3)
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
    try:
        with open("restart.txt", "w") as f:
            f.write(f"{msg.chat.id}\n{msg.id}")
    except Exception:
        pass

    # Executes an immediate, clean process restart
    os.execl(sys.executable, sys.executable, *sys.argv)


# ============================================================
# 📊 BOT DATABASE STATS (Combined stats & total)
# ============================================================
@Client.on_message(filters.command(["stats", "total"]) & admin_filter, group=3)
async def bot_stats_cmd(bot: Client, message: Message):
    status_msg = await message.reply_text("⏳ **Fetching Database Stats...**")
    try:
        total_users = await _db.total_users_count()
        total_chats = await _db.total_chat_count()
        total_files = await _Media.count_documents({})
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


# ============================================================
# 🧹 DEEP CLEAN USERS
# ============================================================
@Client.on_message(filters.command("cleanusers") & admin_filter, group=3)
async def clean_users_cmd(bot: Client, message: Message):
    status_msg = await message.reply_text(
        "⏳ **Starting Deep Clean...** (This is a safe background process)"
    )

    try:
        users_cursor = await _db.get_all_users()
        users = (
            await users_cursor.to_list(length=None)
            if hasattr(users_cursor, "to_list")
            else list(users_cursor)
        )
    except Exception as e:
        return await status_msg.edit_text(f"❌ **Failed to fetch users:** `{e}`")

    active, blocked, total_users = 0, 0, len(users)

    async def check_user(u):
        user_id = u.get("id") or u.get("user_id")
        if not user_id:
            return "blocked"
        try:
            await bot.send_chat_action(user_id, enums.ChatAction.TYPING)
            return "active"
        except FloodWait as e:
            await asyncio.sleep(e.value + 1)
            return "active"
        except (UserIsBlocked, InputUserDeactivated, PeerIdInvalid, UserDeactivatedBan):
            await _db.delete_user(user_id)
            return "blocked"
        except Exception:
            return "active"

    for i in range(0, total_users, 30):
        chunk = users[i : i + 30]
        results = await asyncio.gather(*[check_user(u) for u in chunk])

        active += results.count("active")
        blocked += results.count("blocked")

        if (i + len(chunk)) % 300 == 0 or (i + len(chunk)) == total_users:
            try:
                await status_msg.edit_text(
                    f"⏳ **Cleaning Database...**\nScanned: `{i + len(chunk)} / {total_users}`"
                )
            except Exception:
                pass

        await asyncio.sleep(2)

    await status_msg.edit_text(
        f"✅ **Deep Clean Completed!**\n\n🟢 **Active Users Kept:** `{active}`\n🔴 **Dead Accounts Removed:** `{blocked}`"
    )


# ============================================================
# 🔥 DATABASE WIPE COMMANDS (Consolidated)
# ============================================================
@Client.on_message(
    filters.command(["clearfiles", "clearusers", "clearfsubusers"]) & admin_filter,
    group=3,
)
async def wipe_prompt_cmd(bot: Client, message: Message):
    cmd = message.command[0]
    action = (
        "files" if cmd == "clearfiles" else "users" if cmd == "clearusers" else "fsub"
    )

    await message.reply_text(
        f"⚠️ **WARNING!** ⚠️\nDelete **ALL** {action} in your database?",
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        f"🔥 YES, DELETE ALL {action.upper()}",
                        callback_data=f"nuke_{action}",
                    )
                ],
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
            collection = getattr(_Media, "collection", _Media)
            res = await collection.delete_many({})
            count = getattr(res, "deleted_count", "All")
            await query.message.edit_text(
                f"✅ **Database Wiped!**\n🗑 **Deleted Files:** `{count}`"
            )

        elif action == "users":
            collection = getattr(_db, "col", _db)
            res = await collection.delete_many({})
            count = getattr(res, "deleted_count", "All")
            await query.message.edit_text(
                f"✅ **Database Wiped!**\n🗑 **Deleted Users:** `{count}`"
            )

        elif action == "fsub":
            await _plugin_db.clear_fsub_users()
            await query.message.edit_text(
                "✅ **Force Subscribe Database has been completely cleared.**"
            )

    except Exception as e:
        logger.exception(f"Error during nuke_{action}")
        await query.message.edit_text(f"❌ **Error occurred:**\n`{e}`")
