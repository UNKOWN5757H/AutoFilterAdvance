import os
from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from pyrogram.errors import ChatAdminRequired, MessageTooLong
from info import ADMINS, LOG_CHANNEL, SUPPORT_CHAT
from database.users_chats_db import db
from database.ia_filterdb import Media
from utils import get_size, temp, get_settings
from Script import script

# ============================================================
# 🚀 Handle when the bot joins a group
# ============================================================
@Client.on_message(filters.new_chat_members & filters.group)
async def save_group(bot, message):
    new_members = [u.id for u in message.new_chat_members]
    if temp.ME in new_members:
        # Bot added to a new group
        if not await db.get_chat(message.chat.id):
            total = await bot.get_chat_members_count(message.chat.id)
            added_by = message.from_user.mention if message.from_user else "Anonymous"
            await bot.send_message(
                LOG_CHANNEL,
                script.LOG_TEXT_G.format(message.chat.title, message.chat.id, total, added_by),
            )
            await db.add_chat(message.chat.id, message.chat.title)

        if message.chat.id in temp.BANNED_CHATS:
            btn = [[InlineKeyboardButton('🤖 OWNER', url=f"https://t.me/{SUPPORT_CHAT}")]]
            markup = InlineKeyboardMarkup(btn)
            warn_msg = await message.reply_text(
                "<b>🚫 This chat is restricted!\n"
                "My admins have disabled me here.\n"
                "Contact the owner to re-enable.</b>",
                reply_markup=markup,
            )
            try:
                await warn_msg.pin()
            except:
                pass
            await bot.leave_chat(message.chat.id)
            return

        btn = [
            [
                InlineKeyboardButton('ℹ️ Help', url=f"https://t.me/{temp.U_NAME}?start=help"),
                InlineKeyboardButton('📖 About', url=f"https://t.me/{temp.U_NAME}?start=about"),
            ]
        ]
        await message.reply_text(
            f"<b>Thanks for adding me to {message.chat.title} ❣️</b>\n\n"
            f"If you have any questions, contact the owner.",
            reply_markup=InlineKeyboardMarkup(btn),
        )

    else:
        settings = await get_settings(message.chat.id)
        if settings.get("welcome"):
            for user in message.new_chat_members:
                old_msg = temp.MELCOW.get("welcome")
                if old_msg:
                    try:
                        await old_msg.delete()
                    except:
                        pass
                temp.MELCOW["welcome"] = await message.reply_text(
                    f"<b>👋 Hey {user.mention}, welcome to {message.chat.title}!</b>"
                )


# ============================================================
# 🚪 /leave — Make the bot leave a chat
# ============================================================
@Client.on_message(filters.command("leave") & filters.user(ADMINS))
async def leave_chat(bot, message):
    if len(message.command) == 1:
        return await message.reply_text("⚠️ Usage: `/leave <chat_id>`")

    try:
        chat_id = int(message.command[1])
    except ValueError:
        return await message.reply_text("❌ Invalid chat ID!")

    try:
        btn = [[InlineKeyboardButton("🤖 OWNER", url=f"https://t.me/{SUPPORT_CHAT}")]]
        markup = InlineKeyboardMarkup(btn)
        await bot.send_message(
            chat_id,
            "<b>My admin asked me to leave this group 😔\n"
            "If you want me back, contact the owner.</b>",
            reply_markup=markup,
        )
        await bot.leave_chat(chat_id)
        await message.reply_text(f"✅ Left the chat `{chat_id}` successfully.")
    except Exception as e:
        await message.reply_text(f"⚠️ Error: `{e}`")


# ============================================================
# 🚫 /disable — Disable a group
# ============================================================
@Client.on_message(filters.command("disable") & filters.user(ADMINS))
async def disable_chat(bot, message):
    if len(message.command) == 1:
        return await message.reply_text("⚠️ Usage: `/disable <chat_id> [reason]`")

    parts = message.text.split(None, 2)
    chat = parts[1]
    reason = parts[2] if len(parts) > 2 else "No reason provided."

    try:
        chat_id = int(chat)
    except ValueError:
        return await message.reply_text("❌ Invalid chat ID!")

    chat_info = await db.get_chat(chat_id)
    if not chat_info:
        return await message.reply_text("⚠️ Chat not found in DB.")
    if chat_info.get("is_disabled"):
        return await message.reply_text(
            f"🚷 This chat is already disabled.\nReason: `{chat_info.get('reason', 'Unknown')}`"
        )

    await db.disable_chat(chat_id, reason)
    temp.BANNED_CHATS.append(chat_id)
    await message.reply_text(f"✅ Chat `{chat_id}` successfully disabled.")

    try:
        btn = [[InlineKeyboardButton("🤖 OWNER", url=f"https://t.me/{SUPPORT_CHAT}")]]
        markup = InlineKeyboardMarkup(btn)
        await bot.send_message(
            chat_id,
            f"<b>🚷 My admin has disabled me here.</b>\nReason: <code>{reason}</code>\n"
            f"If this is a mistake, contact the owner.",
            reply_markup=markup,
        )
        await bot.leave_chat(chat_id)
    except Exception as e:
        await message.reply_text(f"⚠️ Error notifying group: `{e}`")


# ============================================================
# ✅ /enable — Re-enable disabled group
# ============================================================
@Client.on_message(filters.command("enable") & filters.user(ADMINS))
async def enable_chat(bot, message):
    if len(message.command) == 1:
        return await message.reply_text("⚙️ Usage: `/enable <chat_id>`")

    try:
        chat_id = int(message.command[1])
    except ValueError:
        return await message.reply_text("❌ Invalid chat ID!")

    chat_info = await db.get_chat(chat_id)
    if not chat_info:
        return await message.reply_text("⚠️ Chat not found in DB.")
    if not chat_info.get("is_disabled"):
        return await message.reply_text("✅ This chat is already enabled.")

    await db.enable_chat(chat_id)
    if chat_id in temp.BANNED_CHATS:
        temp.BANNED_CHATS.remove(chat_id)
    await message.reply_text(f"✅ Chat `{chat_id}` successfully re-enabled.")


# ============================================================
# 📊 /stats — Show database stats
# ============================================================
@Client.on_message(filters.command("stats") & filters.user(ADMINS))
async def get_stats(bot, message):
    status_msg = await message.reply_text("📊 Fetching stats...")

    try:
        total_users = await db.total_users()
        total_chats = await db.total_chats()
        total_files = await Media.count_documents({})
        size_bytes = await db.get_db_size() if hasattr(db, "get_db_size") else 0
    except Exception as e:
        return await status_msg.edit(f"⚠️ Error fetching stats: `{e}`")

    free_space = 536870912 - size_bytes
    await status_msg.edit(
        script.STATUS_TXT.format(
            total_files,
            total_users,
            total_chats,
            get_size(size_bytes),
            get_size(free_space),
        )
    )


# ============================================================
# 🧑‍🤝‍🧑 /users — List users
# ============================================================
@Client.on_message(filters.command("users") & filters.user(ADMINS))
async def list_users(bot, message):
    temp_msg = await message.reply_text("📋 Fetching user list...")
    users = await db.get_all_users()

    if not users:
        return await temp_msg.edit("⚠️ No users found in the database.")

    out = "👥 **Users in Database:**\n\n"
    for user in users:
        out += f"• <a href='tg://user?id={user['id']}'>{user.get('name', 'Unknown')}</a>"
        if user.get("ban_status", {}).get("is_banned"):
            out += " (🚫 Banned)"
        out += "\n"

    try:
        await temp_msg.edit(out)
    except MessageTooLong:
        with open("users.txt", "w+", encoding="utf-8") as f:
            f.write(out)
        await message.reply_document("users.txt", caption="👥 List of users in DB.")
        os.remove("users.txt")
        await temp_msg.delete()
