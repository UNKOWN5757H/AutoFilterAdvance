import asyncio
import os
import platform
import shutil
import sys
from datetime import datetime
from logging import ERROR, getLogger

from pyrogram import Client, enums, filters
from pyrogram.errors import (
    FloodWait,
    InputUserDeactivated,
    PeerIdInvalid,
    UserDeactivatedBan,
    UserIsBlocked,
)
from pyrogram.types import CallbackQuery, Message, InlineKeyboardButton, InlineKeyboardMarkup

import info
from database.plugin_dbs import plugin_db as _plugin_db
from database.ia_filterdb import Media as _Media
from database.users_chats_db import db as _db
from database.connections_mdb import (
    add_connection,
    all_connections,
    delete_connection,
    if_active,
)

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
    if message.chat and message.chat.type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
        # If the sender is the group itself, it's a Group Anonymous Admin
        if message.sender_chat and message.sender_chat.id == message.chat.id:
            return True
            
        # If it's a Normal Admin in this group
        if message.from_user:
            try:
                member = await client.get_chat_member(message.chat.id, message.from_user.id)
                return member.status in [enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER]
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
# ℹ️ INFO COMMAND
# ============================================================
@Client.on_message(filters.command("info") & admin_filter)
async def who_is(client: Client, message: Message):
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
            return await status.edit_text("⚠️ No valid user found. *(Anonymous admins must reply to a user or provide an ID)*")

        text = (
            f"<b>👤 First Name:</b> {user.first_name}\n"
            f"<b>🧾 Last Name:</b> {user.last_name or 'None'}\n"
            f"<b>🆔 Telegram ID:</b> <code>{user.id}</code>\n"
            f"<b>🌐 Data Centre:</b> <code>{user.dc_id or 'N/A'}</code>\n"
            f"<b>💬 Username:</b> @{user.username or 'None'}\n"
            f"<b>🔗 User Link:</b> <a href='tg://user?id={user.id}'>Click Here</a>\n"
        )

        if message.chat.type in (enums.ChatType.SUPERGROUP, enums.ChatType.CHANNEL, enums.ChatType.GROUP):
            try:
                member = await client.get_chat_member(message.chat.id, user.id)
                if member.joined_date:
                    text += f"<b>📅 Joined Chat On:</b> <code>{member.joined_date.strftime('%Y-%m-%d %H:%M:%S')}</code>\n"
            except Exception:
                pass

        markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔐 Close", callback_data="close_data")]])
        photo_sent = False
        
        if user.photo:
            try:
                await message.reply_photo(photo=user.photo.big_file_id, caption=text, reply_markup=markup, parse_mode=enums.ParseMode.HTML)
                photo_sent = True
            except Exception:
                photo_sent = False

        if not photo_sent:
            await message.reply_text(text, reply_markup=markup, parse_mode=enums.ParseMode.HTML)

        await status.delete()
    except Exception as e:
        logger.error(f"Info Command Error: {e}")
        await status.edit_text("❌ An error occurred while fetching user data.")


# ============================================================
# 🔗 CONNECTION COMMANDS (Group Admin Managed internally)
# ============================================================
@Client.on_message((filters.private | filters.group) & filters.command("connect"))
async def addconnection(client: Client, message: Message):
    userid = message.from_user.id if message.from_user else None
    if not userid:
        return await message.reply("⚠️ You are posting as an anonymous admin. Please use `/connect group_id` in my PM.")

    if message.chat.type == enums.ChatType.PRIVATE:
        try:
            cmd, group_id = message.text.split(" ", 1)
            group_id = int(group_id)
        except Exception:
            return await message.reply_text("<b>Enter correct format!</b>\n\n<code>/connect groupid</code>", quote=True)
    else:
        group_id = message.chat.id

    is_admin = userid in get_admin_list()
    if not is_admin:
        try:
            st = await client.get_chat_member(group_id, userid)
            if st.status in [enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER]:
                is_admin = True
        except Exception:
            return await message.reply_text("❌ Invalid Group ID or I'm not in that group!", quote=True)

    if not is_admin:
        return await message.reply_text("❌ You must be an admin in the specified group!", quote=True)

    try:
        st = await client.get_chat_member(group_id, "me")
        if st.status == enums.ChatMemberStatus.ADMINISTRATOR:
            ttl = await client.get_chat(group_id)
            if await add_connection(str(group_id), str(userid)):
                await message.reply_text(f"✅ Successfully connected to **{ttl.title}**\nNow manage your group from my PM!", quote=True)
            else:
                await message.reply_text("⚠️ You're already connected to this chat!", quote=True)
        else:
            await message.reply_text("❌ Add me as an admin in the group first.", quote=True)
    except Exception:
        await message.reply_text("❌ Some error occurred! Try again later.", quote=True)


@Client.on_message((filters.private | filters.group) & filters.command("disconnect"))
async def deleteconnection(client: Client, message: Message):
    userid = message.from_user.id if message.from_user else None
    if not userid:
        return await message.reply("⚠️ You are an anonymous admin. Please use `/disconnect` in my PM.")

    if message.chat.type == enums.ChatType.PRIVATE:
        return await message.reply_text("Run `/connections` to view or disconnect from groups!", quote=True)
    
    group_id = message.chat.id
    is_admin = userid in get_admin_list()
    if not is_admin:
        try:
            st = await client.get_chat_member(group_id, userid)
            if st.status in [enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER]:
                is_admin = True
        except Exception:
            pass

    if not is_admin:
        return

    if await delete_connection(str(userid), str(group_id)):
        await message.reply_text("✅ Successfully disconnected from this chat", quote=True)
    else:
        await message.reply_text("⚠️ This chat isn't connected to me!", quote=True)


@Client.on_message(filters.private & filters.command("connections"))
async def connections(client: Client, message: Message):
    userid = message.from_user.id
    groupids = await all_connections(str(userid))

    if not groupids:
        return await message.reply_text("⚠️ There are no active connections! Connect to some groups first.", quote=True)

    buttons = []
    for groupid in groupids:
        try:
            ttl = await client.get_chat(int(groupid))
            act = " - ACTIVE" if await if_active(str(userid), str(groupid)) else ""
            buttons.append([InlineKeyboardButton(text=f"{ttl.title}{act}", callback_data=f"groupcb:{groupid}:{act}")])
        except Exception:
            pass

    if buttons:
        await message.reply_text("🔗 **Your connected group details:**\n\n", reply_markup=InlineKeyboardMarkup(buttons), quote=True)
    else:
        await message.reply_text("⚠️ There are no active connections!", quote=True)


# ============================================================
# ⚙️ ADMIN SETTINGS & MANAGEMENT
# ============================================================
@Client.on_message(filters.command("repairmode") & admin_filter)
async def toggle_repair_mode(bot: Client, message: Message):
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


@Client.on_message(filters.command("adminsettings") & admin_filter)
async def show_admin_settings(bot: Client, message: Message):
    repair_status = "🟢 ENABLED" if getattr(info, "REPAIR_MODE", False) else "🔴 DISABLED"
    fsub_status = "🟢 ENABLED" if getattr(info, "IS_FSUB_ENABLED", True) else "🔴 DISABLED"

    text = "⚙️ **Current Admin Settings Dashboard**\n━━━━━━━━━━━━━━━━━━━━━\n\n"
    text += f"🛠️ **Repair Mode:** {repair_status}\n🔐 **Force Subscribe:** {fsub_status}\n\n"
    text += f"📢 **Main FSub Channel:** <code>{getattr(info, 'AUTH_CHANNEL', '❌ Not Set')}</code>\n"
    text += f"📨 **Request FSub Channel:** <code>{getattr(info, 'REQ_CHANNEL', '❌ Not Set')}</code>\n\n"
    text += f"👥 **Total Admins Configured:** `{len(getattr(info, 'ADMINS', []))}`\n━━━━━━━━━━━━━━━━━━━━━\n💡 *Use commands like /repairmode to toggle values.*"

    await message.reply_text(text)


@Client.on_message(filters.command("leave") & admin_filter)
async def leave_chat(bot: Client, message: Message):
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
@Client.on_message(filters.command("ban") & admin_filter)
async def ban_user_cmd(bot: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text("⚙️ **Usage:** `/ban [user_id]`")
    try:
        user_id = int(message.command[1])
        if user_id in get_admin_list():
            return await message.reply_text("❌ **You cannot ban a bot administrator!**")
        if user_id == bot.me.id:
            return await message.reply_text("❌ **I cannot ban myself!**")

        await _plugin_db.ban_user(user_id)
        await message.reply_text(f"🚫 **User `{user_id}` has been successfully BANNED.**\nThey can no longer use this bot.")
    except ValueError:
        await message.reply_text("❌ **Invalid User ID!** Please provide a valid numerical ID.")
    except Exception as e:
        await message.reply_text(f"❌ **Error:** `{e}`")


@Client.on_message(filters.command("unban") & admin_filter)
async def unban_user_cmd(bot: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text("⚙️ **Usage:** `/unban [user_id]`")
    try:
        user_id = int(message.command[1])
        if not await _plugin_db.is_banned(user_id):
            return await message.reply_text(f"⚠️ **User `{user_id}` is not currently banned.**")

        await _plugin_db.unban_user(user_id)
        await message.reply_text(f"✅ **User `{user_id}` has been successfully UNBANNED.**")
    except ValueError:
        await message.reply_text("❌ **Invalid User ID!** Please provide a valid numerical ID.")
    except Exception as e:
        await message.reply_text(f"❌ **Error:** `{e}`")


@Client.on_message(filters.command("bannedusers") & admin_filter)
async def check_banned_users(bot: Client, message: Message):
    try:
        count = await _plugin_db.get_ban_count()
        await message.reply_text(f"📊 **Total Banned Users:** `{count}`")
    except Exception as e:
        await message.reply_text(f"❌ **Error:** `{e}`")


# ============================================================
# 📜 LOGS & SERVER COMMANDS
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


@Client.on_message(filters.command("restart") & admin_filter, group=3)
async def restart_bot_cmd(bot: Client, message: Message):
    await message.reply_text(
        "⚠️ **Are you sure you want to restart the bot?**",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Confirm Restart", callback_data="util_restart")]]),
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

    os.execl(sys.executable, sys.executable, *sys.argv)


# ============================================================
# 📊 BOT DATABASE STATS & CLEANUP
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


@Client.on_message(filters.command("cleanusers") & admin_filter, group=3)
async def clean_users_cmd(bot: Client, message: Message):
    status_msg = await message.reply_text("⏳ **Starting Deep Clean...** (This is a safe background process)")

    try:
        users_cursor = await _db.get_all_users()
        users = await users_cursor.to_list(length=None) if hasattr(users_cursor, "to_list") else list(users_cursor)
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
                await status_msg.edit_text(f"⏳ **Cleaning Database...**\nScanned: `{i + len(chunk)} / {total_users}`")
            except Exception:
                pass

        await asyncio.sleep(2)

    await status_msg.edit_text(f"✅ **Deep Clean Completed!**\n\n🟢 **Active Users Kept:** `{active}`\n🔴 **Dead Accounts Removed:** `{blocked}`")


# ============================================================
# 🔥 DATABASE WIPE COMMANDS
# ============================================================
@Client.on_message(filters.command(["clearfiles", "clearusers", "clearfsubusers"]) & admin_filter, group=3)
async def wipe_prompt_cmd(bot: Client, message: Message):
    cmd = message.command[0]
    action = "files" if cmd == "clearfiles" else "users" if cmd == "clearusers" else "fsub"

    await message.reply_text(
        f"⚠️ **WARNING!** ⚠️\nDelete **ALL** {action} in your database?",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(f"🔥 YES, DELETE ALL {action.upper()}", callback_data=f"nuke_{action}")],
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
            collection = getattr(_Media, "collection", _Media)
            res = await collection.delete_many({})
            count = getattr(res, "deleted_count", "All")
            await query.message.edit_text(f"✅ **Database Wiped!**\n🗑 **Deleted Files:** `{count}`")

        elif action == "users":
            collection = getattr(_db, "col", _db)
            res = await collection.delete_many({})
            count = getattr(res, "deleted_count", "All")
            await query.message.edit_text(f"✅ **Database Wiped!**\n🗑 **Deleted Users:** `{count}`")

        elif action == "fsub":
            await _plugin_db.clear_fsub_users()
            await query.message.edit_text("✅ **Force Subscribe Database has been completely cleared.**")

    except Exception as e:
        logger.exception(f"Error during nuke_{action}")
        await query.message.edit_text(f"❌ **Error occurred:**\n`{e}`")
