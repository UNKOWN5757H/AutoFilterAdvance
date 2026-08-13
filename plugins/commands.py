import asyncio
import base64
import json
import logging
import os
import random
import re
import sys

from pyrogram import Client, enums, filters
from pyrogram.enums import ButtonStyle
from pyrogram.errors import ChatAdminRequired, FloodWait
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

import info
from database.connections_mdb import active_connection
from database.ia_filterdb import Media, SafeMediaWrapper, get_file_details

# Centralized database for ban checks
from database.plugin_dbs import plugin_db
from database.users_chats_db import db
from info import (
    ADMINS,
    AUTH_CHANNEL,
    BATCH_FILE_CAPTION,
    CHANNELS,
    CUSTOM_FILE_CAPTION,
    LOG_CHANNEL,
    PICS,
    PROTECT_CONTENT,
)
from plugins.fsub import ForceSub
from Script import script
from utils import get_settings, get_size, save_group_settings, temp

logger = logging.getLogger(__name__)

BATCH_FILES = {}
LOG_FILE = "TelegramBot.log"

MESSAGE_EMOJI_PLANE = '<tg-emoji emoji-id="5875465628285931233">✈️</tg-emoji> Telegram'
MESSAGE_EMOJI_LINK = '<tg-emoji emoji-id="5877465816030515018">🔗</tg-emoji> Link'

# Ensure ADMINS contains valid integers for Pyrogram filters
ADMIN_USERS = [int(a) for a in ADMINS if str(a).lstrip("-").isdigit()]


def get_start_buttons(user_id):
    """Helper to generate start buttons dynamically based on admin status."""
    buttons = [
        [
            InlineKeyboardButton(
                text="✈️ Gʀᴏᴜᴘ 1",
                url="https://t.me/Sandalwood_Kannada_Group",
                icon_custom_emoji_id=5258096772776991776,
                style=ButtonStyle.PRIMARY,
            ),
            InlineKeyboardButton(
                text="✈️ Gʀᴏᴜᴘ 2",
                url="http://t.me/Kannada_Filmy_Group",
                icon_custom_emoji_id=5258096772776991776,
                style=ButtonStyle.PRIMARY,
            ),
            InlineKeyboardButton(
                text="✈️ Gʀᴏᴜᴘ 3",
                url="https://t.me/+GLsPkRgLGGszMzY1",
                icon_custom_emoji_id=5258096772776991776,
                style=ButtonStyle.PRIMARY,
            ),
        ]
    ]

    # Safe parsing of ADMINS list for both string/int
    if str(user_id) in [str(a) for a in ADMINS]:
        buttons.append(
            [
                InlineKeyboardButton("ℹ️ 𝙷𝚎𝚕𝚙", callback_data="help"),
                InlineKeyboardButton("😊 𝙰𝚋𝚘𝚞𝚝", callback_data="about"),
            ]
        )

    buttons.append(
        [
            InlineKeyboardButton(
                text="🔗 Nᴇᴡ Rᴇʟᴇᴀꜱᴇꜱ & Oᴛᴛ Uᴘᴅᴀᴛᴇꜱ",
                url="https://t.me/sandalwood_kannada_moviesz",
                icon_custom_emoji_id=5258503720928288433,
                style=ButtonStyle.SUCCESS,
            )
        ]
    )
    return InlineKeyboardMarkup(buttons)


# ============================================================
# 🚀 MAIN START COMMAND (Handles file delivery links)
# ============================================================
@Client.on_message(filters.command("start") & filters.incoming)
async def start(client: Client, message: Message):
    if getattr(info, "REPAIR_MODE", False):
        if not message.from_user or str(message.from_user.id) not in [
            str(a) for a in info.ADMINS
        ]:
            return await message.reply_text(
                "🛠️ **Bot is currently under maintenance!**\n\nWe are performing some upgrades/fixes. Please try again later."
            )

    if message.from_user and await plugin_db.is_banned(message.from_user.id):
        return await message.reply_text(
            "🚫 **You have been banned from using this bot.**\nIf you believe this is a mistake, please contact the administrators."
        )

    bot_uname = temp.U_NAME or "my_bot"
    b_name = temp.B_NAME or "MovieBot"

    if message.chat.type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
        reply_markup = get_start_buttons(
            message.from_user.id if message.from_user else 0
        )
        await message.reply(
            script.START_TXT.format(
                mention=(
                    message.from_user.mention
                    if message.from_user
                    else message.chat.title
                ),
                uname=bot_uname,
                bname=b_name,
                plane_emoji=MESSAGE_EMOJI_PLANE,
                link_emoji=MESSAGE_EMOJI_LINK,
            ),
            reply_markup=reply_markup,
            parse_mode=enums.ParseMode.HTML,
        )
        await asyncio.sleep(2)

        if not await db.get_chat(message.chat.id):
            total = await client.get_chat_members_count(message.chat.id)
            try:
                await client.send_message(
                    LOG_CHANNEL,
                    script.LOG_TEXT_G.format(
                        message.chat.title, message.chat.id, total, "Unknown"
                    ),
                )
            except Exception as e:
                logger.error(f"Failed to log new group: {e}")
            await db.add_chat(message.chat.id, message.chat.title)
        return

    if not await db.is_user_exist(message.from_user.id):
        await db.add_user(message.from_user.id, message.from_user.first_name)
        try:
            await client.send_message(
                LOG_CHANNEL,
                script.LOG_TEXT_P.format(
                    message.from_user.id, message.from_user.mention
                ),
            )
        except Exception as e:
            logger.error(f"Failed to log new user: {e}")

    if len(message.command) != 2:
        reply_markup = get_start_buttons(message.from_user.id)

        try:
            photo_to_send = random.choice(PICS) if PICS else None
        except Exception:
            photo_to_send = None

        caption = script.START_TXT.format(
            mention=message.from_user.mention,
            uname=bot_uname,
            bname=b_name,
            plane_emoji=MESSAGE_EMOJI_PLANE,
            link_emoji=MESSAGE_EMOJI_LINK,
        )

        if photo_to_send:
            await message.reply_photo(
                photo=photo_to_send,
                caption=caption,
                reply_markup=reply_markup,
                parse_mode=enums.ParseMode.HTML,
            )
        else:
            await message.reply_text(
                text=caption,
                reply_markup=reply_markup,
                parse_mode=enums.ParseMode.HTML,
            )
        return

    if message.command[1] in ["subscribe", "error", "okay", "help", "start", "hehe"]:
        if message.command[1] == "subscribe":
            return await ForceSub(client, message)

        reply_markup = get_start_buttons(message.from_user.id)

        try:
            photo_to_send = random.choice(PICS) if PICS else None
        except Exception:
            photo_to_send = None

        caption = script.START_TXT.format(
            mention=message.from_user.mention,
            uname=bot_uname,
            bname=b_name,
            plane_emoji=MESSAGE_EMOJI_PLANE,
            link_emoji=MESSAGE_EMOJI_LINK,
        )

        if photo_to_send:
            await message.reply_photo(
                photo=photo_to_send,
                caption=caption,
                reply_markup=reply_markup,
                parse_mode=enums.ParseMode.HTML,
            )
        else:
            await message.reply_text(
                text=caption,
                reply_markup=reply_markup,
                parse_mode=enums.ParseMode.HTML,
            )
        return

    cmd_data = message.command[1]
    kk, file_id = cmd_data.split("_", 1) if "_" in cmd_data else (False, False)
    pre = ("checksubp" if kk == "filep" else "checksub") if kk else False

    status = await ForceSub(client, message, file_id=file_id or cmd_data, mode=pre)
    if not status:
        return

    data = cmd_data
    if not file_id:
        file_id = data

    if data.split("-", 1)[0] == "BATCH":
        sts = await message.reply("Please wait...")
        file_id = data.split("-", 1)[1]
        msgs = BATCH_FILES.get(file_id)

        if not msgs:
            file = await client.download_media(file_id)
            try:
                with open(file) as file_data:
                    msgs = json.loads(file_data.read())
            except Exception:
                await sts.edit("FAILED")
                try:
                    await client.send_message(LOG_CHANNEL, "UNABLE TO OPEN BATCH FILE.")
                except Exception:
                    pass
                return
            finally:
                if os.path.exists(file):
                    os.remove(file)
            BATCH_FILES[file_id] = msgs

        for msg in msgs:
            title = msg.get("title")
            size = get_size(int(msg.get("size", 0)))
            f_caption = msg.get("caption", "")

            if BATCH_FILE_CAPTION:
                try:
                    f_caption = BATCH_FILE_CAPTION.format(
                        file_name="" if title is None else title,
                        file_size="" if size is None else size,
                        file_caption="" if f_caption is None else f_caption,
                    )
                except Exception as e:
                    logger.exception(e)

            if not f_caption:
                f_caption = f"{title}"
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
                    reply_markup=InlineKeyboardMarkup(
                        [
                            [
                                InlineKeyboardButton(
                                    text="🎥 ಕನ್ನಡ ಹೊಸ ಮೂವೀಗಳು 🎥",
                                    url="https://t.me/Sandalwood_kannada_moviesz",
                                    icon_custom_emoji_id=5258503720928288433,
                                    style=ButtonStyle.SUCCESS,
                                )
                            ]
                        ]
                    ),
                    protect_content=msg.get("protect", False),
                )
            except Exception as e:
                logger.warning(e, exc_info=True)
                continue
            await asyncio.sleep(1)

        return await sts.delete()

    elif data.split("-", 1)[0] == "DSTORE":
        sts = await message.reply("Please wait...")
        b_string = data.split("-", 1)[1]
        decoded = base64.urlsafe_b64decode(
            b_string + "=" * (-len(b_string) % 4)
        ).decode("ascii")
        try:
            f_msg_id, l_msg_id, f_chat_id, protect = decoded.split("_", 3)
        except ValueError:
            f_msg_id, l_msg_id, f_chat_id = decoded.split("_", 2)
            protect = "/pbatch" if PROTECT_CONTENT else "batch"

        message_ids = list(range(int(f_msg_id), int(l_msg_id) + 1))
        for i in range(0, len(message_ids), 200):
            chunk = message_ids[i : i + 200]
            try:
                messages = await client.get_messages(int(f_chat_id), chunk)
                for msg in messages:
                    if msg.empty:
                        continue
                    if msg.media:
                        media = getattr(msg, msg.media.value)
                        if BATCH_FILE_CAPTION:
                            try:
                                f_caption = BATCH_FILE_CAPTION.format(
                                    file_name=getattr(media, "file_name", ""),
                                    file_size=getattr(media, "file_size", ""),
                                    file_caption=getattr(msg, "caption", ""),
                                )
                            except Exception as e:
                                logger.exception(e)
                                f_caption = getattr(msg, "caption", "")
                        else:
                            f_caption = getattr(
                                msg, "caption", getattr(media, "file_name", "")
                            )

                        if getattr(info, "CAPTION_PLUS", None):
                            f_caption += f"\n\n{info.CAPTION_PLUS}"

                        try:
                            await msg.copy(
                                message.chat.id,
                                caption=f_caption,
                                protect_content=True if protect == "/pbatch" else False,
                            )
                        except FloodWait as e:
                            await asyncio.sleep(e.value)
                            await msg.copy(
                                message.chat.id,
                                caption=f_caption,
                                protect_content=True if protect == "/pbatch" else False,
                            )
                        except Exception as e:
                            logger.exception(e)
                            continue
                    else:
                        try:
                            await msg.copy(
                                message.chat.id,
                                protect_content=True if protect == "/pbatch" else False,
                            )
                        except FloodWait as e:
                            await asyncio.sleep(e.value)
                            await msg.copy(
                                message.chat.id,
                                protect_content=True if protect == "/pbatch" else False,
                            )
                        except Exception as e:
                            logger.exception(e)
                            continue
                    await asyncio.sleep(1)
            except Exception as e:
                logger.error(f"DSTORE Fetch Failed: {e}")

        return await sts.delete()

    files_ = await get_file_details(file_id)

    if not files_:
        try:
            decoded = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode(
                "ascii"
            )
            pre_str, decode_file_id = decoded.split("_", 1)

            files_ = await get_file_details(decode_file_id)
            if not files_:
                try:
                    msg = await client.send_cached_media(
                        chat_id=message.from_user.id,
                        file_id=decode_file_id,
                        protect_content=True if pre_str == "filep" else False,
                    )
                    filetype = msg.media.value
                    file = getattr(msg, filetype)
                    title = getattr(file, "file_name", "Unknown")
                    size = get_size(getattr(file, "file_size", 0))
                    f_caption = f"<code>{title}</code>"
                    if CUSTOM_FILE_CAPTION:
                        try:
                            f_caption = CUSTOM_FILE_CAPTION.format(
                                file_name=title, file_size=size, file_caption=""
                            )
                        except Exception:
                            pass
                    if getattr(info, "CAPTION_PLUS", None):
                        f_caption += f"\n\n{info.CAPTION_PLUS}"

                    await msg.edit_caption(f_caption)
                except Exception as e:
                    logger.error(f"Fallback direct send failed: {e}")
                    return await message.reply("⚠️ No such file exist.")
                return
            kk = pre_str
        except Exception:
            return await message.reply("⚠️ No such file exist.")

    files = files_[0]
    if isinstance(files, dict):
        title = str(files.get("file_name", "Unknown") or "Unknown")
        size_raw = int(files.get("file_size", 0) or 0)
        f_caption = str(files.get("caption", "") or "")
        db_file_id = files.get("full_file_id", files.get("file_id", file_id))
    else:
        title = str(getattr(files, "file_name", "Unknown") or "Unknown")
        size_raw = int(getattr(files, "file_size", 0) or 0)
        f_caption = str(getattr(files, "caption", "") or "")
        db_file_id = getattr(files, "full_file_id", getattr(files, "file_id", file_id))

    size = get_size(size_raw)

    if CUSTOM_FILE_CAPTION:
        try:
            f_caption = CUSTOM_FILE_CAPTION.format(
                file_name="" if title == "Unknown" else title,
                file_size="" if size == "0B" else size,
                file_caption="" if not f_caption else f_caption,
            )
        except Exception as e:
            logger.exception(e)

    if not f_caption:
        f_caption = f"{title}"

    if getattr(info, "CAPTION_PLUS", None):
        f_caption += f"\n\n{info.CAPTION_PLUS}"

    try:
        msg = await client.send_cached_media(
            chat_id=message.from_user.id,
            file_id=db_file_id,
            caption=f_caption,
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            text="🎥 ಕನ್ನಡ ಹೊಸ ಮೂವೀಗಳು 🎥",
                            url="https://t.me/Sandalwood_kannada_moviesz",
                            icon_custom_emoji_id=5258503720928288433,
                            style=ButtonStyle.SUCCESS,
                        )
                    ]
                ]
            ),
            protect_content=True if kk in ["filep", "checksubp"] else False,
        )
    except Exception as e:
        logger.error(f"Failed to send cached media: {e}")
        return await message.reply(
            f"⚠️ **Error sending file:**\n`{e}`\n\nPlease alert an admin."
        )

    k = await msg.reply(
        f"<b><u>❗️❗️❗️IMPORTANT❗️️❗️❗️</u></b>\n\nᴛʜɪꜱ ᴍᴏᴠɪᴇ ꜰɪʟᴇ/ᴠɪᴅᴇᴏ ᴡɪʟʟ ʙᴇ ᴅᴇʟᴇᴛᴇᴅ ɪɴ <b><u><code>30 Minutes</code></u> 🫥 <i></b>(ᴅᴜᴇ ᴛᴏ ᴄᴏᴘʏʀɪɢʜᴛ ɪꜱꜱᴜᴇꜱ)</i>.\n\n<b><i>ᴘʟᴇᴀꜱᴇ ꜰᴏʀᴡᴀʀᴅ ᴛʜɪꜱ ꜰɪʟᴇ ᴛᴏ ꜱᴏᴍᴇᴡʜᴇʀᴇ ᴇʟꜱᴇ ᴀɴᴅ ꜱᴛᴀʀᴛ ᴅᴏᴡɴʟᴏᴀᴅɪɴɢ ᴛʜᴇʀᴇ Team: @KR_Picture</i></b>",
        quote=True,
    )

    delete_timer = getattr(info, "FILE_AUTO_DELETE", 1800)
    if delete_timer > 0:
        asyncio.create_task(delete_after_delay(msg, k, delete_timer))


async def delete_after_delay(msg, warning_msg, delay):
    await asyncio.sleep(delay)
    try:
        await msg.delete()
        await warning_msg.edit_text(
            "<b>Yᴏᴜʀ Vɪᴅᴇᴏ / Fɪʟᴇ ɪꜱ Sᴜᴄᴄᴇꜱꜱꜰᴜʟʟʏ Dᴇʟᴇᴛᴇᴅ !!. Tᴇᴀᴍ: @KR_Picture</b>"
        )
    except Exception:
        pass


@Client.on_message(filters.command("channel") & filters.user(ADMIN_USERS))
async def channel_info(bot, message):
    if isinstance(CHANNELS, (int, str)):
        channels = [CHANNELS]
    elif isinstance(CHANNELS, list):
        channels = CHANNELS
    else:
        raise ValueError("Unexpected type of CHANNELS")

    text = "📑 **Indexed channels/groups**\n"
    for channel in channels:
        try:
            chat = await bot.get_chat(channel)
            text += (
                "\n@" + chat.username
                if chat.username
                else "\n" + (chat.title or chat.first_name)
            )
        except Exception as e:
            text += f"\n{channel} - (Error fetching: {e})"

    text += f"\n\n**Total:** {len(CHANNELS)}"
    if len(text) < 4096:
        await message.reply(text)
    else:
        file = "Indexed channels.txt"
        with open(file, "w") as f:
            f.write(text)
        await message.reply_document(file)
        os.remove(file)


@Client.on_message(filters.command("settings"))
async def settings(client: Client, message: Message):
    userid = message.from_user.id if message.from_user else None
    if not userid:
        return await message.reply(
            "You are an anonymous admin! Please verify your identity."
        )

    chat_type = message.chat.type
    grp_id = None
    title = None

    if chat_type == enums.ChatType.PRIVATE:
        grpid = await active_connection(str(userid))
        if grpid is not None:
            try:
                chat = await client.get_chat(grpid)
                title = chat.title
                grp_id = chat.id
            except Exception:
                return await message.reply("Make sure I'm present in your group!")
        else:
            return await message.reply(
                "You are not connected to any active group!\n\nUse /connect <groupid> to connect first."
            )
    elif chat_type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
        grp_id = message.chat.id
        title = message.chat.title

    if not grp_id:
        return
    settings_dict = await get_settings(grp_id)

    btn_text = "✅" if settings_dict.get("button", False) else "❌"
    botpm_text = "✅" if settings_dict.get("botpm", False) else "❌"
    file_secure_text = "✅" if settings_dict.get("file_secure", False) else "❌"
    imdb_text = "✅" if settings_dict.get("imdb", False) else "❌"
    spell_check_text = "✅" if settings_dict.get("spell_check", False) else "❌"
    welcome_text = "✅" if settings_dict.get("welcome", False) else "❌"

    buttons = [
        [
            InlineKeyboardButton(
                f"Buttons: {btn_text}",
                callback_data=f"setgs#button#{settings_dict.get('button', False)}#{grp_id}",
            ),
            InlineKeyboardButton(
                f"Bot PM: {botpm_text}",
                callback_data=f"setgs#botpm#{settings_dict.get('botpm', False)}#{grp_id}",
            ),
        ],
        [
            InlineKeyboardButton(
                f"File Secure: {file_secure_text}",
                callback_data=f"setgs#file_secure#{settings_dict.get('file_secure', False)}#{grp_id}",
            ),
            InlineKeyboardButton(
                f"IMDB: {imdb_text}",
                callback_data=f"setgs#imdb#{settings_dict.get('imdb', False)}#{grp_id}",
            ),
        ],
        [
            InlineKeyboardButton(
                f"Spell Check: {spell_check_text}",
                callback_data=f"setgs#spell_check#{settings_dict.get('spell_check', False)}#{grp_id}",
            ),
            InlineKeyboardButton(
                f"Welcome: {welcome_text}",
                callback_data=f"setgs#welcome#{settings_dict.get('welcome', False)}#{grp_id}",
            ),
        ],
        [InlineKeyboardButton("🗑 Close", callback_data="close_data")],
    ]
    await message.reply_text(
        text=f"⚙️ **Settings for {title}**\n\nChoose the options below to configure your group's behavior.",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode=enums.ParseMode.MARKDOWN,
    )


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
            [
                InlineKeyboardButton(
                    f"Buttons: {btn_text}",
                    callback_data=f"setgs#button#{settings_dict.get('button', False)}#{grp_id}",
                ),
                InlineKeyboardButton(
                    f"Bot PM: {botpm_text}",
                    callback_data=f"setgs#botpm#{settings_dict.get('botpm', False)}#{grp_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    f"File Secure: {file_secure_text}",
                    callback_data=f"setgs#file_secure#{settings_dict.get('file_secure', False)}#{grp_id}",
                ),
                InlineKeyboardButton(
                    f"IMDB: {imdb_text}",
                    callback_data=f"setgs#imdb#{settings_dict.get('imdb', False)}#{grp_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    f"Spell Check: {spell_check_text}",
                    callback_data=f"setgs#spell_check#{settings_dict.get('spell_check', False)}#{grp_id}",
                ),
                InlineKeyboardButton(
                    f"Welcome: {welcome_text}",
                    callback_data=f"setgs#welcome#{settings_dict.get('welcome', False)}#{grp_id}",
                ),
            ],
            [InlineKeyboardButton("🗑 Close", callback_data="close_data")],
        ]
        await query.message.edit_text(
            text=f"⚙️ **Settings for {title}**\n\nChoose the options below to configure your group's behavior.",
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode=enums.ParseMode.MARKDOWN,
        )
        await query.answer("Settings Updated! ✅")
    except Exception as e:
        logger.exception("Error in settings_callback")
        await query.answer("An error occurred!", show_alert=True)


@Client.on_message(
    filters.private & filters.command("movie_update") & filters.user(ADMIN_USERS)
)
async def set_movie_update_notification(client, message):
    bot_id = client.me.id
    try:
        option = message.text.split(" ", 1)[1].strip().lower()
        enable_status = option in ["on", "true"]
    except (IndexError, ValueError):
        return await message.reply_text(
            "<b>💔 Invalid option. Please send 'on' or 'off' after the command.</b>"
        )
    try:
        await db.update_movie_update_status(bot_id, enable_status)
        response_text = (
            "<b>ᴍᴏᴠɪᴇ ᴜᴘᴅᴀᴛᴇ ɴᴏᴛɪꜰɪᴄᴀᴛɪᴏɴ ᴇɴᴀʙʟᴇᴅ ✅</b>"
            if enable_status
            else "<b>ᴍᴏᴠɪᴇ ᴜᴘᴅᴀᴛᴇ ɴᴏᴛɪꜰɪᴄᴀᴛɪᴏɴ ᴅɪꜱᴀʙʟᴇᴅ ❌</b>"
        )
        await message.reply_text(response_text)
    except Exception as e:
        logger.error(f"Error in set_movie_update_notification: {e}")
        await message.reply_text(f"<b>❗ An error occurred: {e}</b>")


# ============================================================
# 📩 PM AUTO-REPLY CATCH-ALL
# ============================================================
@Client.on_message(filters.private & filters.incoming, group=1)
async def pm_auto_reply(client: Client, message: Message):
    # Ignore commands (like /start or /help) so it doesn't double-reply
    if message.text and message.text.startswith("/"):
        return

    # --- YOUR CUSTOM MESSAGE HERE ---
    reply_text = "<b>Request Movies Here 👇</b>"

    # --- GREEN BUTTON (Matched exactly to your /start command style) ---
    buttons = [
        [
            InlineKeyboardButton(
                text="🔗 Jᴏɪɴ Oᴜʀ Mᴀɪɴ Cʜᴀɴɴᴇʟ",
                url="https://t.me/Sandalwood_Kannada_Group",
                icon_custom_emoji_id=5258503720928288433,
                style=ButtonStyle.SUCCESS,
            )
        ]
    ]

    try:
        await message.reply_text(
            text=reply_text, reply_markup=InlineKeyboardMarkup(buttons), quote=True
        )
    except Exception as e:
        logger.error(f"Error in PM auto-reply: {e}")
