import asyncio
import logging

from pyrogram import Client, filters
from pyrogram.errors import PeerIdInvalid, UserNotParticipant
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from database.users_chats_db import db
from info import ADMINS, SUPPORT_CHAT
from utils import temp


# ============================================================
# BAN COMMAND (Admins Only)
# ============================================================
@Client.on_message(filters.command("ban") & filters.user(ADMINS))
async def ban_user(bot: Client, message: Message):
    """
    Ban a user by ID or username.
    Usage: /ban <user_id|username> [reason]
    """
    if len(message.command) < 2:
        return await message.reply_text(
            "⚠️ Usage: `/ban <user_id | username> [reason]`"
        )

    args = message.text.split(None, 2)
    user_ref = args[1]
    reason = args[2] if len(args) > 2 else "No reason provided."

    try:
        user = (
            await bot.get_users(int(user_ref))
            if user_ref.isdigit()
            else await bot.get_users(user_ref)
        )
    except PeerIdInvalid:
        return await message.reply_text(
            "❌ Invalid user ID. I must have chatted with them before."
        )
    except Exception as e:
        logging.exception(e)
        return await message.reply_text(f"⚠️ Error: `{e}`")

    ban_status = await db.get_ban_status(user.id)
    if ban_status and ban_status.get("is_banned"):
        return await message.reply_text(
            f"🚫 {user.mention} is already banned.\nReason: `{ban_status['ban_reason']}`"
        )

    await db.ban_user(user.id, reason)
    temp.BANNED_USERS.append(user.id) if user.id not in temp.BANNED_USERS else None

    await message.reply_text(
        f"✅ {user.mention} has been banned.\n \nReason: `{reason}`"
    )


# ============================================================
# UNBAN COMMAND (Admins Only)
# ============================================================
@Client.on_message(filters.command("unban") & filters.user(ADMINS))
async def unban_user(bot: Client, message: Message):
    """Unban a user by ID or username."""
    if len(message.command) < 2:
        return await message.reply_text("⚠️ Usage: `/unban <user_id | username>`")

    user_ref = message.text.split(None, 2)[1]

    try:
        user = (
            await bot.get_users(int(user_ref))
            if user_ref.isdigit()
            else await bot.get_users(user_ref)
        )
    except PeerIdInvalid:
        return await message.reply_text(
            "❌ Invalid user ID. I must have chatted with them before."
        )
    except Exception as e:
        logging.exception(e)
        return await message.reply_text(f"⚠️ Error: `{e}`")

    ban_status = await db.get_ban_status(user.id)
    if not ban_status or not ban_status.get("is_banned"):
        return await message.reply_text(f"ℹ️ {user.mention} is not banned.")

    await db.remove_ban(user.id)
    if user.id in temp.BANNED_USERS:
        temp.BANNED_USERS.remove(user.id)

    await message.reply_text(f"✅ {user.mention} has been unbanned.")


# ============================================================
# PAGINATED BANNED USERS LIST (Admins Only)
# ============================================================
@Client.on_message(filters.command("bannedlist") & filters.user(ADMINS))
async def banned_list(bot: Client, message: Message):
    """Display a paginated list of banned users."""
    banned_users = await db.get_all_banned_users()

    if not banned_users:
        return await message.reply_text("✅ No users are currently banned.")

    await send_banned_page(message, banned_users, 0)


@Client.on_callback_query(filters.regex(r"^banpage_(\d+)$"))
async def paginate_banned_list(bot: Client, query: CallbackQuery):
    """Handle pagination callback."""
    try:
        page = int(query.data.split("_")[1])
        banned_users = await db.get_all_banned_users()
        await send_banned_page(
            query.message, banned_users, page, edit=True, query=query
        )
    except Exception as e:
        logging.exception(e)
        await query.answer("⚠️ Something went wrong.", show_alert=True)


async def send_banned_page(
    message_or_query, banned_users, page: int, edit=False, query=None
):
    """Helper to display or edit a paginated list."""
    PER_PAGE = 10
    total = len(banned_users)
    total_pages = (total - 1) // PER_PAGE + 1
    page = max(0, min(page, total_pages - 1))

    start = page * PER_PAGE
    end = start + PER_PAGE
    current = banned_users[start:end]

    text = f"🚫 **Banned Users** (Page {page + 1}/{total_pages})\n\n"
    for i, user in enumerate(current, start=start + 1):
        uid = user.get("id")
        reason = user.get("ban_reason", "No reason provided.")
        text += f"**{i}.** `{uid}` — {reason}\n"

    buttons = []
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"banpage_{page - 1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"banpage_{page + 1}"))
    if nav:
        buttons.append(nav)

    buttons.append([InlineKeyboardButton("❌ Close", callback_data="close_banlist")])
    markup = InlineKeyboardMarkup(buttons)

    if edit and query:
        await query.message.edit_text(
            text, reply_markup=markup, disable_web_page_preview=True
        )
        await query.answer()
    else:
        await message_or_query.reply_text(
            text, reply_markup=markup, disable_web_page_preview=True
        )


@Client.on_callback_query(filters.regex("^close_banlist$"))
async def close_banlist(bot: Client, query: CallbackQuery):
    """Close the banned list pagination."""
    try:
        await query.message.delete()
    except Exception:
        pass
    await query.answer("Closed ✅", show_alert=False)


# ============================================================
# CUSTOM FILTERS
# ============================================================
async def is_banned_user(_, __, message: Message):
    """Check if a user is banned."""
    return bool(message.from_user and message.from_user.id in temp.BANNED_USERS)


banned_user = filters.create(is_banned_user)


async def is_disabled_chat(_, __, message: Message):
    """Check if a chat is disabled."""
    return bool(message.chat and message.chat.id in temp.BANNED_CHATS)


disabled_chat = filters.create(is_disabled_chat)


# ============================================================
# REPLY TO BANNED USERS (Private)
# ============================================================
@Client.on_message(filters.private & banned_user & filters.incoming)
async def reply_banned_user(bot: Client, message: Message):
    """Notify banned users that they cannot use the bot."""
    ban = await db.get_ban_status(message.from_user.id)
    reason = ban.get("ban_reason", "No reason provided.")
    await message.reply_text(
        f"🚫 You are **banned** from using this bot.\n\n**Reason:** `{reason}`"
    )


# ============================================================
# LEAVE DISABLED GROUPS
# ============================================================
@Client.on_message(filters.group & disabled_chat & filters.incoming)
async def handle_disabled_group(bot: Client, message: Message):
    """Leave disabled groups after notifying."""
    chat_data = await db.get_chat(message.chat.id)
    reason = chat_data.get("reason", "No reason provided.")

    buttons = [
        [InlineKeyboardButton("🧩 Support", url=f"https://t.me/{SUPPORT_CHAT}")],
        [InlineKeyboardButton("🤖 Owner", url="https://t.me/Sandalwood_Help_Bot")],
    ]
    markup = InlineKeyboardMarkup(buttons)

    msg = await message.reply_text(
        f"🚷 **Chat Restricted!**\n\n"
        f"My admins have disabled me here.\n"
        f"**Reason:** `{reason}`\n\n"
        f"If you believe this is a mistake, please contact support.",
        reply_markup=markup,
    )

    try:
        await msg.pin()
    except Exception:
        pass

    await asyncio.sleep(3)
    try:
        await bot.leave_chat(message.chat.id)
    except Exception:
        pass
