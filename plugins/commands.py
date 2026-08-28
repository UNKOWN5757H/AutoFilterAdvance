import asyncio
import base64
import json
import math
import os
import random
import re
import sys
from logging import getLogger, ERROR

from pyrogram import Client, enums, filters
from pyrogram.enums import ButtonStyle
from pyrogram.errors import ChatAdminRequired, FloodWait, PeerIdInvalid, UserIsBlocked
from pyrogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import info
from database.connections_mdb import active_connection
# ⚡ FIXED: Removed unused Media object and aliased SafeMediaWrapper
from database.ia_filterdb import SafeMediaWrapper as _SafeMediaWrapper, get_file_details
from database.plugin_dbs import plugin_db as _plugin_db
from database.users_chats_db import db as _db
from info import (
    ADMINS, AUTH_CHANNEL, BATCH_FILE_CAPTION, CHANNELS,
    CUSTOM_FILE_CAPTION, LOG_CHANNEL, PICS, PROTECT_CONTENT,
)
from plugins.fsub import ForceSub
from Script import script
from utils import get_settings, get_size, save_group_settings, temp

logger = getLogger(__name__)
logger.setLevel(ERROR)

BATCH_FILES = {}
LOG_FILE = "TelegramBot.log"
MESSAGE_EMOJI_PLANE = '<tg-emoji emoji-id="5875465628285931233">✈️</tg-emoji> Telegram'
MESSAGE_EMOJI_LINK = '<tg-emoji emoji-id="5877465816030515018">🔗</tg-emoji> Link'
ADMIN_USERS = [int(a) for a in ADMINS if str(a).lstrip("-").isdigit()]

def get_start_buttons(user_id):
    buttons = [
        [
            InlineKeyboardButton("✈️ Gʀᴏᴜᴘ 1", url="https://t.me/Sandalwood_Kannada_Group", icon_custom_emoji_id=5258096772776991776, style=ButtonStyle.PRIMARY),
            InlineKeyboardButton("✈️ Gʀᴏᴜᴘ 2", url="http://t.me/Kannada_Filmy_Group", icon_custom_emoji_id=5258096772776991776, style=ButtonStyle.PRIMARY),
            InlineKeyboardButton("✈️ Gʀᴏᴜᴘ 3", url="https://t.me/+GLsPkRgLGGszMzY1", icon_custom_emoji_id=5258096772776991776, style=ButtonStyle.PRIMARY),
        ]
    ]

    if str(user_id) in [str(a) for a in ADMINS]:
        buttons.append([
            InlineKeyboardButton("ℹ️ 𝙷𝚎𝚕𝚙", callback_data="help"),
            InlineKeyboardButton("😊 𝙰𝚋𝚘𝚞𝚝", callback_data="about"),
        ])

    buttons.append([
        InlineKeyboardButton("🔗 Nᴇᴡ Rᴇʟᴇᴀꜱᴇꜱ & Oᴛᴛ Uᴘᴅᴀᴛᴇꜱ", url="https://t.me/sandalwood_kannada_moviesz", icon_custom_emoji_id=5258503720928288433, style=ButtonStyle.SUCCESS)
    ])
    return InlineKeyboardMarkup(buttons)

@Client.on_message(filters.command("start") & filters.incoming)
async def start(client: Client, message: Message):
    if getattr(info, "REPAIR_MODE", False):
        if not message.from_user or str(message.from_user.id) not in [str(a) for a in info.ADMINS]:
            return await message.reply_text("🛠️ **Bot is currently under maintenance!**")
    if message.from_user and await _plugin_db.is_banned(message.from_user.id):
        return await message.reply_text("🚫 **You have been banned from using this bot.**")

    bot_uname = temp.U_NAME or "my_bot"
    b_name = temp.B_NAME or "MovieBot"

    if message.chat.type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
        reply_markup = get_start_buttons(message.from_user.id if message.from_user else 0)
        await message.reply(
            script.START_TXT.format(
                mention=(message.from_user.mention if message.from_user else message.chat.title),
                uname=bot_uname, bname=b_name,
                plane_emoji=MESSAGE_EMOJI_PLANE, link_emoji=MESSAGE_EMOJI_LINK,
            ),
            reply_markup=reply_markup,
            parse_mode=enums.ParseMode.HTML,
        )
        await asyncio.sleep(2)
        if not await _db.get_chat(message.chat.id):
            total = await client.get_chat_members_count(message.chat.id)
            try: await client.send_message(LOG_CHANNEL, script.LOG_TEXT_G.format(message.chat.title, message.chat.id, total, "Unknown"))
            except Exception: pass
            await _db.add_chat(message.chat.id, message.chat.title)
        return

    if not await _db.is_user_exist(message.from_user.id):
        await _db.add_user(message.from_user.id, message.from_user.first_name)
        try: await client.send_message(LOG_CHANNEL, script.LOG_TEXT_P.format(message.from_user.id, message.from_user.mention))
        except Exception: pass

    if len(message.command) != 2:
        reply_markup = get_start_buttons(message.from_user.id)
        photo_to_send = random.choice(PICS) if PICS else None
        caption = script.START_TXT.format(mention=message.from_user.mention, uname=bot_uname, bname=b_name, plane_emoji=MESSAGE_EMOJI_PLANE, link_emoji=MESSAGE_EMOJI_LINK)
        try:
            if photo_to_send: await message.reply_photo(photo=photo_to_send, caption=caption, reply_markup=reply_markup, parse_mode=enums.ParseMode.HTML)
            else: await message.reply_text(text=caption, reply_markup=reply_markup, parse_mode=enums.ParseMode.HTML)
        except (UserIsBlocked, PeerIdInvalid): pass
        return

    if message.command[1] in ["subscribe", "error", "okay", "help", "start", "hehe"]:
        if message.command[1] == "subscribe": return await ForceSub(client, message)
        reply_markup = get_start_buttons(message.from_user.id)
        photo_to_send = random.choice(PICS) if PICS else None
        caption = script.START_TXT.format(mention=message.from_user.mention, uname=bot_uname, bname=b_name, plane_emoji=MESSAGE_EMOJI_PLANE, link_emoji=MESSAGE_EMOJI_LINK)
        try:
            if photo_to_send: await message.reply_photo(photo=photo_to_send, caption=caption, reply_markup=reply_markup, parse_mode=enums.ParseMode.HTML)
            else: await message.reply_text(text=caption, reply_markup=reply_markup, parse_mode=enums.ParseMode.HTML)
        except (UserIsBlocked, PeerIdInvalid): pass
        return

    cmd_data = message.command[1]
    kk, file_id = cmd_data.split("_", 1) if "_" in cmd_data else (False, False)
    pre = ("checksubp" if kk == "filep" else "checksub") if kk else False

    status = await ForceSub(client, message, file_id=file_id or cmd_data, mode=pre)
    if not status: return

    data = cmd_data
    if not file_id: file_id = data

    files_ = await get_file_details(file_id)
    if not files_: return await message.reply("⚠️ No such file exists.")

    files = files_[0]
    title = str(files.get("file_name", "Unknown") if isinstance(files, dict) else getattr(files, "file_name", "Unknown"))
    size_raw = int(files.get("file_size", 0) if isinstance(files, dict) else getattr(files, "file_size", 0))
    f_caption = str(files.get("caption", "") if isinstance(files, dict) else getattr(files, "caption", ""))
    db_file_id = files.get("full_file_id", files.get("file_id", file_id)) if isinstance(files, dict) else getattr(files, "full_file_id", getattr(files, "file_id", file_id))
    size = get_size(size_raw)

    if CUSTOM_FILE_CAPTION:
        try: f_caption = CUSTOM_FILE_CAPTION.format(file_name="" if title == "Unknown" else title, file_size="" if size == "0B" else size, file_caption="" if not f_caption else f_caption)
        except Exception: pass

    if not f_caption: f_caption = f"{title}"
    if getattr(info, "CAPTION_PLUS", None): f_caption += f"\n\n{info.CAPTION_PLUS}"

    try:
        msg = await client.send_cached_media(
            chat_id=message.from_user.id,
            file_id=db_file_id,
            caption=f_caption,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(text="🎥 ಕನ್ನಡ ಹೊಸ ಮೂವೀಗಳು 🎥", url="https://t.me/Sandalwood_kannada_moviesz", icon_custom_emoji_id=5258503720928288433, style=ButtonStyle.SUCCESS)]]),
            protect_content=True if kk in ["filep", "checksubp"] else False,
        )
    except FloodWait as e:
        await asyncio.sleep(e.value + 1)
        try: msg = await client.send_cached_media(chat_id=message.from_user.id, file_id=db_file_id, caption=f_caption, protect_content=True if kk in ["filep", "checksubp"] else False)
        except Exception as err: return await message.reply(f"⚠️ **Error:**\n`{err}`")
    except UserIsBlocked: return
    except Exception as e: return await message.reply(f"⚠️ **Error sending file:**\n`{e}`")

    try:
        k = await msg.reply("<b>📢 <u>Please Note</u>\n \n✅ The above file will be autodeleted in 30mins.\n \nTᴇᴀᴍ: @KR_Picture</b>", quote=True)
        delete_timer = getattr(info, "FILE_AUTO_DELETE", 1800)
        if delete_timer > 0: asyncio.create_task(delete_after_delay(msg, k, delete_timer))
    except Exception: pass

async def delete_after_delay(msg, warning_msg, delay):
    await asyncio.sleep(delay)
    try:
        await msg.delete()
        await warning_msg.edit_text("<b>Yᴏᴜʀ Vɪᴅᴇᴏ / Fɪʟᴇ ɪꜱ Sᴜᴄᴄᴇꜱꜱꜰᴜʟʟʏ Dᴇʟᴇᴛᴇᴅ !!. Tᴇᴀᴍ: @KR_Picture</b>")
    except Exception: pass

async def get_channels_page(client: Client, page: int = 1):
    raw_chats = await _db.get_all_chats()
    if hasattr(raw_chats, "__aiter__"): all_chats = [c async for c in raw_chats]
    elif isinstance(raw_chats, list): all_chats = raw_chats
    else: all_chats = list(raw_chats)

    total_chats = len(all_chats)
    page_size = 15
    total_pages = max(1, math.ceil(total_chats / page_size))
    page = max(1, min(page, total_pages))

    start_idx = (page - 1) * page_size
    end_idx = start_idx + page_size
    current_chats = all_chats[start_idx:end_idx]

    text = f"📑 <b>All Connected Channels & Groups</b> (Page {page}/{total_pages})\n\n"
    for i, chat in enumerate(current_chats, start=start_idx + 1):
        chat_id = chat.get("id") or chat.get("chat_id")
        title = chat.get("title") or chat.get("name") or "Unknown"
        username = chat.get("username")
        link = f"https://t.me/{username}" if username else (f"https://t.me/c/{str(chat_id)[4:]}/1" if str(chat_id).startswith("-100") else "Private")
        text += f"<b>{i}. {title}</b>\n🔗 Link: {link}\n🆔 ID: <code>{chat_id}</code>\n\n"

    buttons = []
    nav_row = []
    if page > 1: nav_row.append(InlineKeyboardButton("⬅️ Previous", callback_data=f"channels_page#{page - 1}"))
    if page < total_pages: nav_row.append(InlineKeyboardButton("Next ➡️", callback_data=f"channels_page#{page + 1}"))
    if nav_row: buttons.append(nav_row)
    buttons.append([InlineKeyboardButton("🔐 Close", callback_data="close_data")])
    return text, InlineKeyboardMarkup(buttons)

@Client.on_message(filters.command(["channels", "channel"]) & filters.user(ADMIN_USERS))
async def list_all_channels_cmd(client: Client, message: Message):
    text, reply_markup = await get_channels_page(client, page=1)
    await message.reply_text(text, reply_markup=reply_markup, disable_web_page_preview=True)

@Client.on_message(filters.command(["leavechannel", "leave"]) & filters.user(ADMIN_USERS))
async def leave_channel_cmd(client: Client, message: Message):
    if len(message.command) < 2: return await message.reply_text("⚙️ <b>Usage:</b> `/leavechannel <channel_id>`\n\n<b>Example:</b> `/leavechannel -1001234567890`")
    target_chat_id = message.command[1].strip()
    try: chat_id_int = int(target_chat_id)
    except ValueError: return await message.reply_text("❌ Invalid Channel ID format.")

    try:
        chat = await client.get_chat(chat_id_int)
        chat_title = chat.title or "Unknown"
        await client.leave_chat(chat_id_int)
        if hasattr(_db, "delete_chat"): await _db.delete_chat(chat_id_int)
        await message.reply_text(f"✅ <b>Successfully left:</b>\n\n<b>Name:</b> {chat_title}\n<b>ID:</b> <code>{chat_id_int}</code>")
    except Exception as e: await message.reply_text(f"❌ <b>Failed to leave channel:</b>\n<code>{e}</code>")

@Client.on_message(filters.command("settings"))
async def settings(client: Client, message: Message):
    userid = message.from_user.id if message.from_user else None
    if not userid: return await message.reply("You are an anonymous admin!")
    chat_type = message.chat.type
    grp_id, title = None, None

    if chat_type == enums.ChatType.PRIVATE:
        grpid = await active_connection(str(userid))
        if grpid is not None:
            try:
                chat = await client.get_chat(grpid)
                title, grp_id = chat.title, chat.id
            except Exception: return await message.reply("Make sure I'm present in your group!")
        else: return await message.reply("You are not connected to any active group!")
    elif chat_type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
        grp_id, title = message.chat.id, message.chat.title

    if not grp_id: return
    settings_dict = await get_settings(grp_id)
    btn_text = "✅" if settings_dict.get("button", False) else "❌"
    botpm_text = "✅" if settings_dict.get("botpm", False) else "❌"
    file_secure_text = "✅" if settings_dict.get("file_secure", False) else "❌"
    imdb_text = "✅" if settings_dict.get("imdb", False) else "❌"
    spell_check_text = "✅" if settings_dict.get("spell_check", False) else "❌"
    welcome_text = "✅" if settings_dict.get("welcome", False) else "❌"

    buttons = [
        [InlineKeyboardButton(f"Buttons: {btn_text}", callback_data=f"setgs#button#{settings_dict.get('button', False)}#{grp_id}"), InlineKeyboardButton(f"Bot PM: {botpm_text}", callback_data=f"setgs#botpm#{settings_dict.get('botpm', False)}#{grp_id}")],
        [InlineKeyboardButton(f"File Secure: {file_secure_text}", callback_data=f"setgs#file_secure#{settings_dict.get('file_secure', False)}#{grp_id}"), InlineKeyboardButton(f"IMDB: {imdb_text}", callback_data=f"setgs#imdb#{settings_dict.get('imdb', False)}#{grp_id}")],
        [InlineKeyboardButton(f"Spell Check: {spell_check_text}", callback_data=f"setgs#spell_check#{settings_dict.get('spell_check', False)}#{grp_id}"), InlineKeyboardButton(f"Welcome: {welcome_text}", callback_data=f"setgs#welcome#{settings_dict.get('welcome', False)}#{grp_id}")],
        [InlineKeyboardButton("🗑 Close", callback_data="close_data")],
    ]
    await message.reply_text(f"⚙️ **Settings for {title}**\n\nChoose the options below to configure your group's behavior.", reply_markup=InlineKeyboardMarkup(buttons), parse_mode=enums.ParseMode.MARKDOWN)

@Client.on_callback_query(filters.regex(r"^setgs#"))
async def settings_callback(client: Client, query: CallbackQuery):
    try:
        _, setting_name, current_state, grp_id = query.data.split("#")
        grp_id = int(grp_id)
        new_state = False if current_state.lower() == "true" else True
        await save_group_settings(grp_id, setting_name, new_state)

        settings_dict = await get_settings(grp_id)
        chat = await client.get_chat(grp_id)
        title = chat.title
        btn_text = "✅" if settings_dict.get("button", False) else "❌"
        botpm_text = "✅" if settings_dict.get("botpm", False) else "❌"
        file_secure_text = "✅" if settings_dict.get("file_secure", False) else "❌"
        imdb_text = "✅" if settings_dict.get("imdb", False) else "❌"
        spell_check_text = "✅" if settings_dict.get("spell_check", False) else "❌"
        welcome_text = "✅" if settings_dict.get("welcome", False) else "❌"

        buttons = [
            [InlineKeyboardButton(f"Buttons: {btn_text}", callback_data=f"setgs#button#{settings_dict.get('button', False)}#{grp_id}"), InlineKeyboardButton(f"Bot PM: {botpm_text}", callback_data=f"setgs#botpm#{settings_dict.get('botpm', False)}#{grp_id}")],
            [InlineKeyboardButton(f"File Secure: {file_secure_text}", callback_data=f"setgs#file_secure#{settings_dict.get('file_secure', False)}#{grp_id}"), InlineKeyboardButton(f"IMDB: {imdb_text}", callback_data=f"setgs#imdb#{settings_dict.get('imdb', False)}#{grp_id}")],
            [InlineKeyboardButton(f"Spell Check: {spell_check_text}", callback_data=f"setgs#spell_check#{settings_dict.get('spell_check', False)}#{grp_id}"), InlineKeyboardButton(f"Welcome: {welcome_text}", callback_data=f"setgs#welcome#{settings_dict.get('welcome', False)}#{grp_id}")],
            [InlineKeyboardButton("🗑 Close", callback_data="close_data")],
        ]
        await query.message.edit_text(f"⚙️ **Settings for {title}**\n\nChoose the options below to configure your group's behavior.", reply_markup=InlineKeyboardMarkup(buttons), parse_mode=enums.ParseMode.MARKDOWN)
        await query.answer("Settings Updated! ✅")
    except Exception:
        await query.answer("An error occurred!", show_alert=True)
