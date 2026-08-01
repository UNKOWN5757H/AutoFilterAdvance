import os
from pyrogram import Client, enums, filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from database.users_chats_db import db
from info import ADMINS, LOG_CHANNEL, SUPPORT_CHAT
from Script import script
from utils import get_settings, temp

@Client.on_message(filters.new_chat_members & filters.group)
async def save_group(bot, message):
    new_members = [u.id for u in message.new_chat_members]
    if temp.ME in new_members:
        if not await db.get_chat(message.chat.id):
            total = await bot.get_chat_members_count(message.chat.id)
            added_by = message.from_user.mention if message.from_user else "Anonymous"
            try:
                await bot.send_message(LOG_CHANNEL, script.LOG_TEXT_G.format(message.chat.title, message.chat.id, total, added_by))
            except Exception:
                pass
            await db.add_chat(message.chat.id, message.chat.title)

        if message.chat.id in temp.BANNED_CHATS:
            markup = InlineKeyboardMarkup([[InlineKeyboardButton("🤖 ADMINS", url=f"https://t.me/{SUPPORT_CHAT}")]])
            warn_msg = await message.reply_text("<b>🚫 This chat is restricted!\nMy admins have disabled me here.\nContact the ADMINS to re-enable.</b>", reply_markup=markup)
            await bot.leave_chat(message.chat.id)
            return
            
        btn = [[InlineKeyboardButton("ℹ️ Help", url=f"https://t.me/{temp.U_NAME}?start=help")]]
        await message.reply_text(f"<b>Thanks for adding me to {message.chat.title} ❣️</b>\n\nIf you have any questions, contact the ADMINS.", reply_markup=InlineKeyboardMarkup(btn))
    else:
        settings = await get_settings(message.chat.id)
        if settings.get("welcome"):
            for user in message.new_chat_members:
                old_msg = temp.MELCOW.get(message.chat.id)
                if old_msg:
                    try:
                        await old_msg.delete()
                    except Exception:
                        pass
                temp.MELCOW[message.chat.id] = await message.reply_text(f"<b>👋 Hey {user.mention}, welcome to {message.chat.title}!</b>")

@Client.on_message(filters.command("leave") & filters.user(ADMINS))
async def leave_chat(bot, message):
    if len(message.command) == 1:
        return await message.reply_text("⚠️ Usage: `/leave <chat_id>`")
    chat_id = int(message.command[1])
    try:
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("🤖 ADMINS", url=f"https://t.me/{SUPPORT_CHAT}")]])
        await bot.send_message(chat_id, "<b>My admin asked me to leave this group 😔\nIf you want me back, contact the ADMINS.</b>", reply_markup=markup)
        await bot.leave_chat(chat_id)
        await message.reply_text(f"✅ Left the chat `{chat_id}` successfully.")
    except Exception as e:
        await message.reply_text(f"⚠️ Error: `{e}`")
