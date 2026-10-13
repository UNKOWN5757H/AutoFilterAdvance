import asyncio
import os
import platform
import shutil
import sys
from logging import ERROR, getLogger

from motor.motor_asyncio import AsyncIOMotorClient
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
# ⚙️ NATIVE CONNECTION ENGINE (100% UNBREAKABLE)
# ============================================================
_DB_CLIENT = AsyncIOMotorClient(info.DATABASE_URI)
_BOT_DB = _DB_CLIENT[info.DATABASE_NAME]

_conn_db = _BOT_DB["connections"]
_active_db = _BOT_DB["active_connections"]


async def add_connection(group_id: str, user_id: str):
    query = {"group_id": group_id, "user_id": user_id}
    if await _conn_db.find_one(query):
        return False
    await _conn_db.insert_one(query)
    return True


async def get_all_connections(user_id: str):
    cursor = _conn_db.find({"user_id": user_id})
    return [doc["group_id"] async for doc in cursor]


async def delete_connection(user_id: str, group_id: str):
    res = await _conn_db.delete_one({"user_id": user_id, "group_id": group_id})
    await _active_db.delete_one({"user_id": user_id, "group_id": group_id})
    return res.deleted_count > 0


async def make_active(user_id: str, group_id: str):
    await _active_db.update_one(
        {"user_id": user_id}, {"$set": {"group_id": group_id}}, upsert=True
    )


async def make_inactive(user_id: str):
    await _active_db.delete_one({"user_id": user_id})


async def get_active_connection(user_id: str):
    doc = await _active_db.find_one({"user_id": user_id})
    return doc["group_id"] if doc else None


# ============================================================
# 👑 SMART AUTHORIZATION ENGINE
# ============================================================
def get_admin_list():
    admin_list = []
    raw_admins = getattr(info, "ADMINS", [])
    if isinstance(raw_admins, int):
        admin_list.append(raw_admins)
    elif isinstance(raw_admins, str):
        admin_list.extend(
            [
                int(x.strip())
                for x in raw_admins.split()
                if x.strip().replace("-", "").isdigit()
            ]
        )
    elif isinstance(raw_admins, list):
        admin_list.extend(
            [int(x) for x in raw_admins if str(x).strip().replace("-", "").isdigit()]
        )
    return admin_list


async def is_global_admin(user_id: int):
    return user_id in get_admin_list()


async def quick_admin_check(client: Client, message: Message):
    uid = (
        message.from_user.id
        if message.from_user
        else getattr(message.sender_chat, "id", 0)
    )
    if await is_global_admin(uid):
        return True
    if message.chat.type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
        if message.sender_chat and message.sender_chat.id == message.chat.id:
            return True
        if message.from_user:
            try:
                member = await client.get_chat_member(message.chat.id, uid)
                return member.status in [
                    enums.ChatMemberStatus.ADMINISTRATOR,
                    enums.ChatMemberStatus.OWNER,
                ]
            except Exception:
                return False
    return False


if not hasattr(info, "REPAIR_MODE"):
    info.REPAIR_MODE = False


def get_size_str(bytes_size):
    if not bytes_size:
        return "0.00 B"
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if bytes_size < 1024.0:
            return f"{bytes_size:.2f} {unit}"
        bytes_size /= 1024.0
    return f"{bytes_size:.2f} PB"


# ============================================================
# ℹ️ INFO COMMAND
# ============================================================
@Client.on_message(filters.command("info"))
async def who_is(client: Client, message: Message):
    if not await quick_admin_check(client, message):
        return
    status = await message.reply_text("🔍 Fetching user info...")

    try:
        user = None
        if message.reply_to_message and message.reply_to_message.from_user:
            user = message.reply_to_message.from_user
        elif len(message.command) > 1:
            target = message.text.split(None, 1)[1]
            try:
                user = await client.get_users(target)
            except Exception:
                pass

        if not user:
            user = message.from_user
        if not user:
            return await status.edit_text(
                "⚠️ No valid user found. *(Anonymous admins must reply to a user or provide an ID)*"
            )

        text = (
            f"<b>👤 First Name:</b> {user.first_name}\n"
            f"<b>🧾 Last Name:</b> {user.last_name or 'None'}\n"
            f"<b>🆔 Telegram ID:</b> <code>{user.id}</code>\n"
            f"<b>🌐 Data Centre:</b> <code>{user.dc_id or 'N/A'}</code>\n"
            f"<b>💬 Username:</b> @{user.username or 'None'}\n"
            f"<b>🔗 User Link:</b> <a href='tg://user?id={user.id}'>Click Here</a>\n"
        )

        if message.chat.type in (
            enums.ChatType.SUPERGROUP,
            enums.ChatType.CHANNEL,
            enums.ChatType.GROUP,
        ):
            try:
                member = await client.get_chat_member(message.chat.id, user.id)
                if member.joined_date:
                    text += f"<b>📅 Joined Chat On:</b> <code>{member.joined_date.strftime('%Y-%m-%d %H:%M:%S')}</code>\n"
            except Exception:
                pass

        markup = InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔐 Close", callback_data="close_data")]]
        )
        if user.photo:
            try:
                await message.reply_photo(
                    photo=user.photo.big_file_id,
                    caption=text,
                    reply_markup=markup,
                    parse_mode=enums.ParseMode.HTML,
                )
            except Exception:
                await message.reply_text(
                    text, reply_markup=markup, parse_mode=enums.ParseMode.HTML
                )
        else:
            await message.reply_text(
                text, reply_markup=markup, parse_mode=enums.ParseMode.HTML
            )

        await status.delete()
    except Exception as e:
        logger.error(f"Info Command Error: {e}")
        await status.edit_text("❌ An error occurred while fetching user data.")


# ============================================================
# 🔗 CONNECTION COMMANDS (100% Native Engine)
# ============================================================
@Client.on_message(filters.command("connect"))
async def addconnection_cmd(client: Client, message: Message):
    uid = str(
        message.from_user.id
        if message.from_user
        else getattr(message.sender_chat, "id", 0)
    )
    if not await quick_admin_check(client, message):
        return await message.reply_text("❌ **Unauthorized:** Admin access required.")

    if message.chat.type == enums.ChatType.PRIVATE:
        if len(message.command) < 2:
            return await message.reply_text("⚠️ **Usage in PM:** `/connect <group_id>`")
        group_id = message.command[1].strip()
        try:
            chat = await client.get_chat(int(group_id))
            title = chat.title

            # Verify the user actually has admin rights in this target group
            if not await is_global_admin(int(uid)):
                member = await client.get_chat_member(int(group_id), int(uid))
                if member.status not in [
                    enums.ChatMemberStatus.ADMINISTRATOR,
                    enums.ChatMemberStatus.OWNER,
                ]:
                    return await message.reply_text(
                        f"❌ You are not an Admin in `{title}`"
                    )
        except Exception as e:
            return await message.reply_text(
                f"❌ Invalid Group ID or I'm not in that group!\nError: `{e}`"
            )
    else:
        group_id = str(message.chat.id)
        title = message.chat.title

    if await add_connection(group_id, uid):
        await make_active(uid, group_id)  # Auto-activate upon connect
        await message.reply_text(
            f"✅ **Successfully connected & activated:**\n`{title}`\n\nYou can now manage this group from my PM!"
        )
    else:
        await make_active(uid, group_id)
        await message.reply_text(
            f"⚠️ You were already connected to `{title}`.\n✅ It has been set as your **Active** connection!"
        )


@Client.on_message(filters.command("disconnect"))
async def deleteconnection_cmd(client: Client, message: Message):
    uid = str(
        message.from_user.id
        if message.from_user
        else getattr(message.sender_chat, "id", 0)
    )
    if not await quick_admin_check(client, message):
        return await message.reply_text("❌ **Unauthorized:** Admin access required.")

    if message.chat.type == enums.ChatType.PRIVATE:
        if len(message.command) < 2:
            return await message.reply_text(
                "⚠️ **Usage in PM:** `/disconnect <group_id>`\nOr use `/connections` to manage them."
            )
        group_id = message.command[1].strip()
    else:
        group_id = str(message.chat.id)

    if await delete_connection(uid, group_id):
        await message.reply_text(f"✅ **Successfully disconnected from:** `{group_id}`")
    else:
        await message.reply_text("⚠️ This chat isn't in your connections list!")


@Client.on_message(filters.command("connections") & filters.private)
async def connections_cmd(client: Client, message: Message):
    uid = str(message.from_user.id)
    groups = await get_all_connections(uid)
    active_group = await get_active_connection(uid)

    if not groups:
        return await message.reply_text(
            "⚠️ **No active connections!**\nUse `/connect <group_id>` to add one."
        )

    buttons = []
    for gid in groups:
        try:
            title = (await client.get_chat(int(gid))).title
            prefix = "🟢" if gid == active_group else "⚪️"
            buttons.append(
                [
                    InlineKeyboardButton(
                        f"{prefix} {title}", callback_data=f"conn_grp:{gid}"
                    )
                ]
            )
        except Exception:
            buttons.append(
                [
                    InlineKeyboardButton(
                        f"⚠️ Unknown ({gid})", callback_data=f"conn_grp:{gid}"
                    )
                ]
            )

    await message.reply_text(
        "🔗 **Your Connected Groups:**\n\n*(Click a group to Activate or Disconnect it)*",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


# --- Connection Interactive Callbacks ---
@Client.on_callback_query(filters.regex(r"^conn_"))
async def connection_callbacks(client: Client, query: CallbackQuery):
    uid = str(query.from_user.id)
    data = query.data.split(":")
    action, group_id = data[0], data[1]

    if action == "conn_grp":
        try:
            title = (await client.get_chat(int(group_id))).title
        except Exception:
            title = "Unknown Group"

        buttons = [
            [
                InlineKeyboardButton(
                    "✅ Make Active", callback_data=f"conn_act:{group_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    "🗑️ Disconnect", callback_data=f"conn_del:{group_id}"
                )
            ],
            [InlineKeyboardButton("🔙 Back to List", callback_data="conn_menu")],
        ]
        await query.message.edit_text(
            f"⚙️ **Manage Connection:**\n`{title}`\n🆔 `{group_id}`",
            reply_markup=InlineKeyboardMarkup(buttons),
        )

    elif action == "conn_act":
        await make_active(uid, group_id)
        await query.answer("✅ Connection Activated!", show_alert=False)
        await build_connection_menu(client, query.message, uid)

    elif action == "conn_del":
        await delete_connection(uid, group_id)
        await query.answer("🗑️ Connection Deleted!", show_alert=False)
        await build_connection_menu(client, query.message, uid)

    elif action == "conn_menu":
        await build_connection_menu(client, query.message, uid)


async def build_connection_menu(client, message, uid):
    groups = await get_all_connections(uid)
    active_group = await get_active_connection(uid)

    if not groups:
        return await message.edit_text(
            "⚠️ **No active connections!**\nUse `/connect <group_id>` to add one."
        )

    buttons = []
    for gid in groups:
        try:
            title = (await client.get_chat(int(gid))).title
            prefix = "🟢" if gid == active_group else "⚪️"
            buttons.append(
                [
                    InlineKeyboardButton(
                        f"{prefix} {title}", callback_data=f"conn_grp:{gid}"
                    )
                ]
            )
        except Exception:
            buttons.append(
                [
                    InlineKeyboardButton(
                        f"⚠️ Unknown ({gid})", callback_data=f"conn_grp:{gid}"
                    )
                ]
            )

    await message.edit_text(
        "🔗 **Your Connected Groups:**\n\n*(Click a group to Activate or Disconnect it)*",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


# ============================================================
# ⚙️ ADMIN SETTINGS & MANAGEMENT
# ============================================================
@Client.on_message(filters.command("repairmode"))
async def toggle_repair_mode(bot: Client, message: Message):
    uid = (
        message.from_user.id
        if message.from_user
        else getattr(message.sender_chat, "id", 0)
    )
    if not await is_global_admin(uid):
        return await message.reply_text(
            "❌ **Unauthorized:** You must be a Global Bot Admin."
        )

    if len(message.command) > 1:
        arg = message.command[1].lower()
        if arg in ["on", "true", "enable"]:
            info.REPAIR_MODE = True
        elif arg in ["off", "false", "disable"]:
            info.REPAIR_MODE = False
        else:
            info.REPAIR_MODE = not getattr(info, "REPAIR_MODE", False)
    else:
        info.REPAIR_MODE = not getattr(info, "REPAIR_MODE", False)

    status = "🟢 **ENABLED**" if info.REPAIR_MODE else "🔴 **DISABLED**"
    text = f"🛠️ **Repair Mode is now {status}**\n\n"
    if info.REPAIR_MODE:
        text += "⚠️ *The bot is now in maintenance mode. It will NOT send any files to users until this is disabled.*"
    else:
        text += "✅ *The bot has returned to normal operation and will process file requests.*"
    await message.reply_text(text)


@Client.on_message(filters.command("adminsettings"))
async def show_admin_settings(bot: Client, message: Message):
    uid = (
        message.from_user.id
        if message.from_user
        else getattr(message.sender_chat, "id", 0)
    )
    if not await is_global_admin(uid):
        return await message.reply_text(
            "❌ **Unauthorized:** You must be a Global Bot Admin."
        )

    repair_status = (
        "🟢 ENABLED" if getattr(info, "REPAIR_MODE", False) else "🔴 DISABLED"
    )
    fsub_status = (
        "🟢 ENABLED" if getattr(info, "IS_FSUB_ENABLED", True) else "🔴 DISABLED"
    )

    text = "⚙️ **Current Admin Settings Dashboard**\n━━━━━━━━━━━━━━━━━━━━━\n\n"
    text += f"🛠️ **Repair Mode:** {repair_status}\n🔐 **Force Subscribe:** {fsub_status}\n\n"
    text += f"📢 **Main FSub Channel:** <code>{getattr(info, 'AUTH_CHANNEL', '❌ Not Set')}</code>\n"
    text += f"📨 **Request FSub Channel:** <code>{getattr(info, 'REQ_CHANNEL', '❌ Not Set')}</code>\n\n"
    text += f"👥 **Total Admins Configured:** `{len(getattr(info, 'ADMINS', []))}`\n━━━━━━━━━━━━━━━━━━━━━\n💡 *Use commands like /repairmode to toggle values.*"
    await message.reply_text(text)


@Client.on_message(filters.command("leave"))
async def leave_chat(bot: Client, message: Message):
    uid = (
        message.from_user.id
        if message.from_user
        else getattr(message.sender_chat, "id", 0)
    )
    if not await is_global_admin(uid):
        return await message.reply_text("❌ **Unauthorized.**")

    if len(message.command) == 1:
        return await message.reply_text("⚠️ Usage: `/leave <chat_id>`")
    try:
        chat_id = int(message.command[1])
        await bot.leave_chat(chat_id)
        await message.reply_text(f"✅ Left the chat `{chat_id}` successfully.")
    except Exception as e:
        await message.reply_text(f"⚠️ Error: `{e}`")


# ============================================================
# 🚫 BAN SYSTEM
# ============================================================
@Client.on_message(filters.command("ban"))
async def ban_user_cmd(bot: Client, message: Message):
    uid = (
        message.from_user.id
        if message.from_user
        else getattr(message.sender_chat, "id", 0)
    )
    if not await is_global_admin(uid):
        return await message.reply_text("❌ **Unauthorized: Global Admin Only.**")

    user_id = None
    if message.reply_to_message and message.reply_to_message.from_user:
        user_id = message.reply_to_message.from_user.id
    elif len(message.command) > 1:
        try:
            user_id = int(message.command[1])
        except ValueError:
            pass

    if not user_id:
        return await message.reply_text(
            "⚙️ **Usage:** `/ban [user_id]` or reply to a user."
        )

    try:
        if await is_global_admin(user_id):
            return await message.reply_text(
                "❌ **You cannot ban a bot administrator!**"
            )
        if user_id == bot.me.id:
            return await message.reply_text("❌ **I cannot ban myself!**")

        await _plugin_db.ban_user(user_id)
        await message.reply_text(
            f"🚫 **User `{user_id}` has been successfully BANNED.**\nThey can no longer use this bot."
        )
    except Exception as e:
        await message.reply_text(f"❌ **Error:** `{e}`")


@Client.on_message(filters.command("unban"))
async def unban_user_cmd(bot: Client, message: Message):
    uid = (
        message.from_user.id
        if message.from_user
        else getattr(message.sender_chat, "id", 0)
    )
    if not await is_global_admin(uid):
        return await message.reply_text("❌ **Unauthorized: Global Admin Only.**")

    user_id = None
    if message.reply_to_message and message.reply_to_message.from_user:
        user_id = message.reply_to_message.from_user.id
    elif len(message.command) > 1:
        try:
            user_id = int(message.command[1])
        except ValueError:
            pass

    if not user_id:
        return await message.reply_text(
            "⚙️ **Usage:** `/unban [user_id]` or reply to a user."
        )

    try:
        if not await _plugin_db.is_banned(user_id):
            return await message.reply_text(
                f"⚠️ **User `{user_id}` is not currently banned.**"
            )
        await _plugin_db.unban_user(user_id)
        await message.reply_text(
            f"✅ **User `{user_id}` has been successfully UNBANNED.**"
        )
    except Exception as e:
        await message.reply_text(f"❌ **Error:** `{e}`")


@Client.on_message(filters.command("bannedusers"))
async def check_banned_users(bot: Client, message: Message):
    uid = (
        message.from_user.id
        if message.from_user
        else getattr(message.sender_chat, "id", 0)
    )
    if not await is_global_admin(uid):
        return await message.reply_text("❌ **Unauthorized.**")

    try:
        count = await _plugin_db.get_ban_count()
        await message.reply_text(f"📊 **Total Banned Users:** `{count}`")
    except Exception as e:
        await message.reply_text(f"❌ **Error:** `{e}`")


# ============================================================
# 📜 LOGS & SERVER COMMANDS
# ============================================================
@Client.on_message(filters.command("logs"), group=3)
async def get_logs_cmd(bot: Client, message: Message):
    uid = (
        message.from_user.id
        if message.from_user
        else getattr(message.sender_chat, "id", 0)
    )
    if not await is_global_admin(uid):
        return
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


@Client.on_message(filters.command("server"), group=3)
async def server_stats_cmd(bot: Client, message: Message):
    uid = (
        message.from_user.id
        if message.from_user
        else getattr(message.sender_chat, "id", 0)
    )
    if not await is_global_admin(uid):
        return await message.reply_text("❌ **Unauthorized.**")

    msg = await message.reply_text("⏳ **Fetching server statistics...**")
    text = "🖥 **Server Statistics**\n━━━━━━━━━━━━━━\n"
    if psutil:
        cpu_pct, ram = psutil.cpu_percent(interval=0.5), psutil.virtual_memory()
        text += f"🧠 **CPU Usage:** `{cpu_pct}%`\n📉 **RAM Usage:** `{ram.percent}%`\n💾 **RAM Total:** `{get_size_str(ram.total)}`\n💿 **RAM Free:** `{get_size_str(ram.available)}`\n\n"
    else:
        text += f"🧠 **CPU Cores:** `{os.cpu_count()}`\n💻 **OS System:** `{platform.system()} {platform.release()}`\n\n"

    total, used, free = shutil.disk_usage("/")
    text += f"💽 **Disk Total:** `{get_size_str(total)}`\n📀 **Disk Used:** `{get_size_str(used)}` (`{(used/total)*100:.1f}%`)\n💿 **Disk Free:** `{get_size_str(free)}`\n━━━━━━━━━━━━━━"
    await msg.edit_text(text)


@Client.on_message(filters.command("restart"), group=3)
async def restart_bot_cmd(bot: Client, message: Message):
    uid = (
        message.from_user.id
        if message.from_user
        else getattr(message.sender_chat, "id", 0)
    )
    if not await is_global_admin(uid):
        return await message.reply_text("❌ **Unauthorized.**")

    await message.reply_text(
        "⚠️ **Are you sure you want to restart the bot?**",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("✅ Confirm Restart", callback_data="util_restart")]]
        ),
    )


@Client.on_callback_query(filters.regex("^util_restart$"), group=3)
async def confirm_restart_cb(bot: Client, query: CallbackQuery):
    uid = query.from_user.id
    if not await is_global_admin(uid):
        return await query.answer("❌ Unauthorized.", show_alert=True)

    await query.answer("♻️ Restarting...", show_alert=True)
    msg = await query.edit_message_text("♻️ **Bot is restarting... Please wait.**")
    try:
        with open("restart.txt", "w") as f:
            f.write(f"{msg.chat.id}\n{msg.id}")
    except Exception:
        pass
    os.execl(sys.executable, sys.executable, *sys.argv)


# ============================================================
# 📊 BOT DATABASE STATS & CLEANUP
# ============================================================
@Client.on_message(filters.command(["stats", "total"]), group=3)
async def bot_stats_cmd(bot: Client, message: Message):
    uid = (
        message.from_user.id
        if message.from_user
        else getattr(message.sender_chat, "id", 0)
    )
    if not await is_global_admin(uid):
        return await message.reply_text("❌ **Unauthorized.**")

    status_msg = await message.reply_text("⏳ **Fetching Database Stats...**")
    try:
        total_users, total_chats, total_files, db_size = (
            await _db.total_users_count(),
            await _db.total_chat_count(),
            await _Media.count_documents({}),
            await _db.get_db_size(),
        )
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


@Client.on_message(filters.command("cleanusers"), group=3)
async def clean_users_cmd(bot: Client, message: Message):
    uid = (
        message.from_user.id
        if message.from_user
        else getattr(message.sender_chat, "id", 0)
    )
    if not await is_global_admin(uid):
        return await message.reply_text("❌ **Unauthorized.**")

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
# 🔥 DATABASE WIPE COMMANDS
# ============================================================
@Client.on_message(
    filters.command(["clearfiles", "clearusers", "clearfsubusers"]), group=3
)
async def wipe_prompt_cmd(bot: Client, message: Message):
    uid = (
        message.from_user.id
        if message.from_user
        else getattr(message.sender_chat, "id", 0)
    )
    if not await is_global_admin(uid):
        return await message.reply_text("❌ **Unauthorized.**")

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


@Client.on_callback_query(filters.regex(r"^nuke_(files|users|fsub)$"), group=3)
async def nuke_callbacks(bot: Client, query: CallbackQuery):
    uid = query.from_user.id
    if not await is_global_admin(uid):
        return await query.answer("❌ Unauthorized.", show_alert=True)

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
