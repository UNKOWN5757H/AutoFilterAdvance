import asyncio
import base64
import json
import logging
import os
import random

from pyrogram import Client, enums, filters
from pyrogram.errors import FloodWait
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

import info
from database.connections_mdb import active_connection
from database.ia_filterdb import get_file_details
from database.users_chats_db import db
from database.plugin_dbs import plugin_db
from plugins.fsub import ForceSub
from Script import script
from utils import get_settings, get_size, save_group_settings, temp

logger = logging.getLogger(__name__)
BATCH_FILES = {}


def get_start_buttons(user_id):
    buttons = [
        [
            InlineKeyboardButton(
                "✈️ Group 1", url="https://t.me/Sandalwood_Kannada_Group"
            ),
            InlineKeyboardButton("✈️ Group 2", url="http://t.me/Kannada_Filmy_Group"),
            InlineKeyboardButton("✈️ Group 3", url="https://t.me/+GLsPkRgLGGszMzY1"),
        ]
    ]
    if user_id in info.ADMINS:
        buttons.append(
            [
                InlineKeyboardButton("ℹ️ 𝙷𝚎𝚕𝚙", callback_data="help"),
                InlineKeyboardButton("😊 𝙰𝚋𝚘𝚞𝚝", callback_data="about"),
            ]
        )
    buttons.append(
        [
            InlineKeyboardButton(
                "🔗 New Releases & OTT Updates",
                url="https://t.me/sandalwood_kannada_moviesz",
            )
        ]
    )
    return InlineKeyboardMarkup(buttons)


@Client.on_message(filters.command("start") & filters.incoming)
async def start(client: Client, message: Message):
    if getattr(info, "REPAIR_MODE", False) and (
        not message.from_user or message.from_user.id not in info.ADMINS
    ):
        return await message.reply_text(
            "🛠️ **Bot is currently under maintenance!**\nPlease try again later."
        )

    if message.from_user and await ban_db.is_banned(message.from_user.id):
        return await message.reply_text(
            "🚫 **You have been banned from using this bot by the ADMINS.**"
        )

    if message.chat.type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
        await message.reply(
            script.START_TXT.format(
                mention=(
                    message.from_user.mention
                    if message.from_user
                    else message.chat.title
                ),
                uname=temp.U_NAME,
                bname=temp.B_NAME,
            ),
            reply_markup=get_start_buttons(
                message.from_user.id if message.from_user else 0
            ),
            parse_mode=enums.ParseMode.HTML,
        )
        if not await db.get_chat(message.chat.id):
            await db.add_chat(message.chat.id, message.chat.title)
        return

    if not await db.is_user_exist(message.from_user.id):
        await db.add_user(message.from_user.id, message.from_user.first_name)

    if len(message.command) != 2:
        return await message.reply_photo(
            photo=random.choice(info.PICS),
            caption=script.START_TXT.format(
                mention=message.from_user.mention, uname=temp.U_NAME, bname=temp.B_NAME
            ),
            reply_markup=get_start_buttons(message.from_user.id),
        )

    cmd_data = message.command[1]
    if cmd_data in ["subscribe", "help", "about"]:
        if cmd_data == "subscribe":
            return await ForceSub(client, message)
        return await message.reply_photo(
            photo=random.choice(info.PICS),
            caption=script.START_TXT.format(
                mention=message.from_user.mention, uname=temp.U_NAME, bname=temp.B_NAME
            ),
            reply_markup=get_start_buttons(message.from_user.id),
        )

    kk, file_id = cmd_data.split("_", 1) if "_" in cmd_data else (False, cmd_data)
    if not await ForceSub(
        client,
        message,
        file_id=file_id,
        mode="checksubp" if kk == "filep" else "checksub",
    ):
        return

    if cmd_data.startswith("BATCH-"):
        sts = await message.reply("⏳ Please wait...")
        file_id = cmd_data.split("-", 1)[1]
        msgs = BATCH_FILES.get(file_id)

        if not msgs:
            file_path = await client.download_media(file_id)
            try:
                with open(file_path) as f:
                    msgs = json.load(f)
            except Exception:
                return await sts.edit("❌ UNABLE TO OPEN BATCH FILE.")
            finally:
                if os.path.exists(file_path):
                    os.remove(file_path)
            BATCH_FILES[file_id] = msgs

        for msg in msgs:
            f_caption = (
                info.BATCH_FILE_CAPTION.format(
                    file_name=msg.get("title", ""),
                    file_size=get_size(int(msg.get("size", 0))),
                    file_caption=msg.get("caption", ""),
                )
                if info.BATCH_FILE_CAPTION
                else msg.get("title", "")
            )
            if getattr(info, "CAPTION_PLUS", None):
                f_caption += f"\n\n{info.CAPTION_PLUS}"

            try:
                await client.send_cached_media(
                    chat_id=message.from_user.id,
                    file_id=msg.get("file_id"),
                    caption=f_caption,
                    protect_content=msg.get("protect", False),
                )
            except FloodWait as e:
                await asyncio.sleep(e.value)
                await client.send_cached_media(
                    chat_id=message.from_user.id,
                    file_id=msg.get("file_id"),
                    caption=f_caption,
                    protect_content=msg.get("protect", False),
                )
            await asyncio.sleep(1)
        return await sts.delete()

    files_ = await get_file_details(file_id)
    if not files_:
        return await message.reply("❌ No such file exists.")

    file_data = files_[0]
    f_caption = (
        info.CUSTOM_FILE_CAPTION.format(
            file_name=file_data.file_name,
            file_size=get_size(file_data.file_size),
            file_caption=file_data.caption or "",
        )
        if info.CUSTOM_FILE_CAPTION
        else file_data.file_name
    )
    if getattr(info, "CAPTION_PLUS", None):
        f_caption += f"\n\n{info.CAPTION_PLUS}"

    msg_sent = await client.send_cached_media(
        chat_id=message.from_user.id,
        file_id=file_id,
        caption=f_caption,
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "🎥 ಕನ್ನಡ ಹೊಸ ಮೂವೀಗಳು 🎥",
                        url="https://t.me/Sandalwood_kannada_moviesz",
                    )
                ]
            ]
        ),
        protect_content=(kk == "filep"),
    )

    warn_msg = await msg_sent.reply(
        "<b><u>❗️❗️❗️IMPORTANT❗️️❗️❗️</u></b>\n\nᴛʜɪꜱ ꜰɪʟᴇ ᴡɪʟʟ ʙᴇ ᴅᴇʟᴇᴛᴇᴅ ɪɴ <b><u><code>30 Minutes</code></u></b>.\n<b><i>ᴘʟᴇᴀꜱᴇ ꜰᴏʀᴡᴀʀᴅ ɪᴛ ꜱᴏᴍᴇᴡʜᴇʀᴇ ᴇʟꜱᴇ.</i></b>",
        quote=True,
    )

    if getattr(info, "FILE_AUTO_DELETE", 1800) > 0:
        asyncio.create_task(
            delete_after_delay(msg_sent, warn_msg, info.FILE_AUTO_DELETE)
        )


async def delete_after_delay(msg, warning_msg, delay):
    await asyncio.sleep(delay)
    try:
        await msg.delete()
        await warning_msg.edit_text("<b>ʏᴏᴜʀ ꜰɪʟᴇ ʜᴀꜱ ʙᴇᴇɴ ꜱᴜᴄᴄᴇꜱꜱꜰᴜʟʟʏ ᴅᴇʟᴇᴛᴇᴅ.</b>")
    except Exception:
        pass
