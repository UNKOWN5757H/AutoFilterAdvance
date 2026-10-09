import os
import re
from logging import ERROR, getLogger

from pyrogram import Client, enums, filters
from pyrogram.errors import ChatAdminRequired, MessageTooLong
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from database.users_chats_db import db as _db
import info
from plugins.custom_settings import get_group_welcome
from Script import script
from utils import get_settings, temp

logger = getLogger(__name__)
logger.setLevel(ERROR)

def get_admin_list():
    raw_admins = getattr(info, "ADMINS", [])
    if isinstance(raw_admins, str): return [int(x) for x in raw_admins.replace(",", " ").split() if x.strip().lstrip("-").isdigit()]
    elif isinstance(raw_admins, int): return [raw_admins]
    elif isinstance(raw_admins, list): return [int(x) for x in raw_admins if str(x).strip().lstrip("-").isdigit()]
    return []

admin_filter = filters.create(lambda _, __, msg: bool(msg.from_user and msg.from_user.id in get_admin_list()))

# ============================================================
# 🛡️ ADMIN GROUP GATEKEEPER & LINK PROTECTOR
# ============================================================
TELEGRAM_LINK_PATTERN = re.compile(r"(https?://)?(www\.)?(t(elegram)?\.(me|dog)|telegram\.org)/(joinchat/|[a-zA-Z0-9_]+)", re.IGNORECASE)

async def is_group_admin(bot: Client, chat_id: int, user_id: int) -> bool:
    if user_id in get_admin_list(): return True
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in [enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER]
    except Exception:
        return False

@Client.on_message(filters.group & ~filters.service, group=-2)
async def group_gatekeeper_and_link_protector(bot: Client, message: Message):
    if not message.from_user: return
    user_id = message.from_user.id
    chat_id = message.chat.id

    # Allow bot administrators & group admins
    if await is_group_admin(bot, chat_id, user_id):
        return

    text = message.text or message.caption or ""

    # Check for unauthorized Telegram channel / invite links
    if TELEGRAM_LINK_PATTERN.search(text):
        try:
            await message.delete()
            warning = await message.reply_text(
                f"⚠️ **Link Deleted!** {message.from_user.mention}, unauthorized invite links are not permitted in this group."
            )
            await asyncio.sleep(8)
            await warning.delete()
        except Exception:
            pass
        return

    # Check for spammed forward headers from channels
    if message.forward_from_chat and message.forward_from_chat.type == enums.ChatType.CHANNEL:
        try:
            await message.delete()
            warning = await message.reply_text(
                f"⚠️ **Channel Forward Blocked!** {message.from_user.mention}, forwarding messages from external channels is prohibited."
            )
            await asyncio.sleep(8)
            await warning.delete()
        except Exception:
            pass
        return

# ============================================================
# 👥 WELCOME SYSTEM & CHAT LIFECYCLE
# ============================================================
@Client.on_message(filters.new_chat_members & filters.group)
async def save_group(bot: Client, message: Message):
    new_members = [u.id for u in message.new_chat_members]
    if temp.ME in new_members:
        if not await _db.get_chat(message.chat.id):
            total = await bot.get_chat_members_count(message.chat.id)
            added_by = message.from_user.mention if message.from_user else "Anonymous"
            log_chan = getattr(info, "LOG_CHANNEL", None)
            if log_chan:
                try:
                    await bot.send_message(log_chan, script.LOG_TEXT_G.format(message.chat.title, message.chat.id, total, added_by))
                except Exception:
                    pass
            await _db.add_chat(message.chat.id, message.chat.title)

        if message.chat.id in temp.BANNED_CHATS:
            support = getattr(info, "SUPPORT_CHAT", "")
            btn = [[InlineKeyboardButton("🤖 ADMINS", url=f"https://t.me/{support}")]] if support else []
            await message.reply_text("<b>🚫 This chat is restricted!\nMy admins have disabled me here.</b>", reply_markup=InlineKeyboardMarkup(btn) if btn else None)
            await bot.leave_chat(message.chat.id)
            return

        bot_user = temp.U_NAME or (await bot.get_me()).username
        btn = [[
            InlineKeyboardButton("ℹ️ Help", url=f"https://t.me/{bot_user}?start=help"),
            InlineKeyboardButton("📖 About", url=f"https://t.me/{bot_user}?start=about")
        ]]
        await message.reply_text(f"<b>Thanks for adding me to {message.chat.title} ❣️</b>", reply_markup=InlineKeyboardMarkup(btn))
    else:
        settings = await get_settings(message.chat.id)
        if settings.get("welcome"):
            w_settings = await get_group_welcome(message.chat.id)
            w_txt = w_settings.get("text") or "<b>👋 Hey {mention}, welcome to {title}!</b>"
            w_img = w_settings.get("img")
            try:
                total_members = await bot.get_chat_members_count(message.chat.id)
            except Exception:
                total_members = ""

            for user in message.new_chat_members:
                formatted_text = w_txt.format(mention=user.mention, title=message.chat.title, count=total_members)
                old_msg = temp.MELCOW.get(message.chat.id)
                if old_msg:
                    try:
                        await old_msg.delete()
                    except Exception:
                        pass

                if w_img:
                    temp.MELCOW[message.chat.id] = await message.reply_photo(photo=w_img, caption=formatted_text, parse_mode=enums.ParseMode.DEFAULT)
                else:
                    temp.MELCOW[message.chat.id] = await message.reply_text(text=formatted_text, parse_mode=enums.ParseMode.DEFAULT)

@Client.on_message(filters.command("leave") & admin_filter)
async def leave_chat(bot: Client, message: Message):
    if len(message.command) == 1:
        return await message.reply_text("⚠️ Usage: `/leave <chat_id>`")
    try:
        chat_id = int(message.command[1])
    except ValueError:
        return await message.reply_text("❌ Invalid chat ID!")

    try:
        await bot.leave_chat(chat_id)
        await message.reply_text(f"✅ Left the chat `{chat_id}` successfully.")
    except Exception as e:
        await message.reply_text(f"⚠️ Error: `{e}`")

@Client.on_message(filters.command("disable") & admin_filter)
async def disable_chat(bot: Client, message: Message):
    if len(message.command) == 1:
        return await message.reply_text("⚠️ Usage: `/disable <chat_id> [reason]`")
    parts = message.text.split(None, 2)
    try:
        chat_id = int(parts[1])
    except ValueError:
        return await message.reply_text("❌ Invalid chat ID!")
    reason = parts[2] if len(parts) > 2 else "No reason provided."

    chat_info = await _db.get_chat(chat_id)
    if not chat_info:
        return await message.reply_text("⚠️ Chat not found in DB.")
    if chat_info.get("is_disabled"):
        return await message.reply_text(f"🚷 This chat is already disabled.\nReason: `{chat_info.get('reason', 'Unknown')}`")

    await _db.disable_chat(chat_id, reason)
    if chat_id not in temp.BANNED_CHATS:
        temp.BANNED_CHATS.append(chat_id)
    await message.reply_text(f"✅ Chat `{chat_id}` successfully disabled.")

    try:
        await bot.leave_chat(chat_id)
    except Exception:
        pass

@Client.on_message(filters.command("enable") & admin_filter)
async def enable_chat(bot: Client, message: Message):
    if len(message.command) == 1:
        return await message.reply_text("⚙️ Usage: `/enable <chat_id>`")
    try:
        chat_id = int(message.command[1])
    except ValueError:
        return await message.reply_text("❌ Invalid chat ID!")

    chat_info = await _db.get_chat(chat_id)
    if not chat_info:
        return await message.reply_text("⚠️ Chat not found in DB.")
    if not chat_info.get("is_disabled"):
        return await message.reply_text("✅ This chat is already enabled.")

    await _db.re_enable_chat(chat_id)
    if chat_id in temp.BANNED_CHATS:
        temp.BANNED_CHATS.remove(chat_id)
    await message.reply_text(f"✅ Chat `{chat_id}` successfully re-enabled.")
