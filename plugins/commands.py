import asyncio
import base64
import json
import math
import os
import random
import re
import sys
from logging import ERROR, getLogger

from pyrogram import Client, enums, filters
from pyrogram.enums import ButtonStyle
from pyrogram.errors import (
    ChatAdminRequired,
    FloodWait,
    MessageNotModified,
    PeerIdInvalid,
    UserIsBlocked,
)
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

import info
from database.connections_mdb import active_connection
from database.ia_filterdb import SafeMediaWrapper as _SafeMediaWrapper
from database.ia_filterdb import get_file_details
from database.plugin_dbs import plugin_db as _plugin_db
from database.users_chats_db import db as _db
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
            InlineKeyboardButton(
                "✈️ Gʀᴏᴜᴘ 1",
                url="https://t.me/Sandalwood_Kannada_Group",
                icon_custom_emoji_id=5258096772776991776,
                style=ButtonStyle.PRIMARY,
            ),
            InlineKeyboardButton(
                "✈️ Gʀᴏᴜᴘ 2",
                url="http://t.me/Kannada_Filmy_Group",
                icon_custom_emoji_id=5258096772776991776,
                style=ButtonStyle.PRIMARY,
            ),
            InlineKeyboardButton(
                "✈️ Gʀᴏᴜᴘ 3",
                url="https://t.me/+GLsPkRgLGGszMzY1",
                icon_custom_emoji_id=5258096772776991776,
                style=ButtonStyle.PRIMARY,
            ),
        ]
    ]

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
                "🔗 Nᴇᴡ Rᴇʟᴇᴀꜱᴇꜱ & Oᴛᴛ Uᴘᴅᴀᴛᴇꜱ",
                url="https://t.me/sandalwood_kannada_moviesz",
                icon_custom_emoji_id=5258503720928288433,
                style=ButtonStyle.SUCCESS,
            )
        ]
    )
    return InlineKeyboardMarkup(buttons)


# ⚡ FIXED: Added explicit support for the /help command
@Client.on_message(filters.command(["start", "help"]) & filters.incoming)
async def start(client: Client, message: Message):
    if getattr(info, "REPAIR_MODE", False):
        if not message.from_user or str(message.from_user.id) not in [
            str(a) for a in info.ADMINS
        ]:
            return await message.reply_text(
                "🛠️ **Bot is currently under maintenance!**"
            )
    if message.from_user and await _plugin_db.is_banned(message.from_user.id):
        return await message.reply_text(
            "🚫 **You have been banned from using this bot.**"
        )

    bot_uname = temp.U_NAME or "my_bot"
    b_name = temp.B_NAME or "MovieBot"

    # ⚡ If the user types /help natively, instantly show the help menu
    is_help_command = (message.command[0] == "help") or (
        len(message.command) == 2 and message.command[1] == "help"
    )

    if is_help_command:
            buttons = [
                [
                    InlineKeyboardButton("🖥️ UI Start", callback_data="helps_uistart"),
                    InlineKeyboardButton("🖥️ UI Help", callback_data="helps_uihelp"),
                    InlineKeyboardButton("🖥️ UI About", callback_data="helps_uiabout")
                ],
                [
                    InlineKeyboardButton("👋 Welcome", callback_data="helps_welcome"),
                    InlineKeyboardButton("🖼️ Images", callback_data="helps_images"),
                ],
                [
                    InlineKeyboardButton("🔍 Spell Check", callback_data="helps_spell"),
                    InlineKeyboardButton("📝 Filters", callback_data="helps_filters"),
                ],
                [
                    InlineKeyboardButton("📱 Force Sub", callback_data="helps_forcesub"),
                    InlineKeyboardButton("👥 Force Add", callback_data="helps_forceadd"),
                ],
                [
                    InlineKeyboardButton("🚫 Bans", callback_data="helps_bans"),
                    InlineKeyboardButton("🗑️ Delete", callback_data="helps_delete"),
                ],
                [
                    InlineKeyboardButton("📢 Promotions", callback_data="helps_promotions"),
                    InlineKeyboardButton("📚 Index", callback_data="helps_index"),
                ],
                [
                    InlineKeyboardButton("⚙️ Settings", callback_data="helps_settings"),
                    InlineKeyboardButton("🌐 Connections", callback_data="helps_connections"),
                ],
                [
                    InlineKeyboardButton("📊 Utilities", callback_data="helps_utilities"),
                    InlineKeyboardButton("💬 Custom Messages", callback_data="helps_custommessages"),
                ],
                [
                    InlineKeyboardButton("📝 Post Handle", callback_data="helps_posthand"),
                    InlineKeyboardButton("📝 Custom Captions", callback_data="helps_customcaption"),
                ],
                [
                    InlineKeyboardButton("💾 Backup", callback_data="helps_backup"),
                ],
                [
                    InlineKeyboardButton("🔙 Back", callback_data="start"),
                    InlineKeyboardButton("🔐 Cʟᴏsᴇ", callback_data="close_data"),
                ],
            ]

        return await message.reply_text(
            text=script.HELP_TXT.format(
                mention=message.from_user.mention if message.from_user else "User"
            ),
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode=enums.ParseMode.HTML,
        )

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
        if not await _db.get_chat(message.chat.id):
            total = await client.get_chat_members_count(message.chat.id)
            try:
                await client.send_message(
                    LOG_CHANNEL,
                    script.LOG_TEXT_G.format(
                        message.chat.title, message.chat.id, total, "Unknown"
                    ),
                )
            except Exception:
                pass
            await _db.add_chat(message.chat.id, message.chat.title)
        return

    if not await _db.is_user_exist(message.from_user.id):
        await _db.add_user(message.from_user.id, message.from_user.first_name)
        try:
            await client.send_message(
                LOG_CHANNEL,
                script.LOG_TEXT_P.format(
                    message.from_user.id, message.from_user.mention
                ),
            )
        except Exception:
            pass

    if len(message.command) != 2:
        reply_markup = get_start_buttons(message.from_user.id)
        photo_to_send = random.choice(PICS) if PICS else None
        caption = script.START_TXT.format(
            mention=message.from_user.mention,
            uname=bot_uname,
            bname=b_name,
            plane_emoji=MESSAGE_EMOJI_PLANE,
            link_emoji=MESSAGE_EMOJI_LINK,
        )
        try:
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
        except (UserIsBlocked, PeerIdInvalid):
            pass
        return

    if message.command[1] in ["subscribe", "error", "okay", "hehe"]:
        if message.command[1] == "subscribe":
            return await ForceSub(client, message)
        reply_markup = get_start_buttons(message.from_user.id)
        photo_to_send = random.choice(PICS) if PICS else None
        caption = script.START_TXT.format(
            mention=message.from_user.mention,
            uname=bot_uname,
            bname=b_name,
            plane_emoji=MESSAGE_EMOJI_PLANE,
            link_emoji=MESSAGE_EMOJI_LINK,
        )
        try:
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
        except (UserIsBlocked, PeerIdInvalid):
            pass
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

    files_ = await get_file_details(file_id)
    if not files_:
        return await message.reply("⚠️ No such file exists.")

    files = files_[0]
    title = str(
        files.get("file_name", "Unknown")
        if isinstance(files, dict)
        else getattr(files, "file_name", "Unknown")
    )
    size_raw = int(
        files.get("file_size", 0)
        if isinstance(files, dict)
        else getattr(files, "file_size", 0)
    )
    f_caption = str(
        files.get("caption", "")
        if isinstance(files, dict)
        else getattr(files, "caption", "")
    )
    db_file_id = (
        files.get("full_file_id", files.get("file_id", file_id))
        if isinstance(files, dict)
        else getattr(files, "full_file_id", getattr(files, "file_id", file_id))
    )
    size = get_size(size_raw)

    if CUSTOM_FILE_CAPTION:
        try:
            f_caption = CUSTOM_FILE_CAPTION.format(
                file_name="" if title == "Unknown" else title,
                file_size="" if size == "0B" else size,
                file_caption="" if not f_caption else f_caption,
            )
        except Exception:
            pass

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
    except FloodWait as e:
        await asyncio.sleep(e.value + 1)
        try:
            msg = await client.send_cached_media(
                chat_id=message.from_user.id,
                file_id=db_file_id,
                caption=f_caption,
                protect_content=True if kk in ["filep", "checksubp"] else False,
            )
        except Exception as err:
            return await message.reply(f"⚠️ **Error:**\n`{err}`")
    except UserIsBlocked:
        return
    except Exception as e:
        return await message.reply(f"⚠️ **Error sending file:**\n`{e}`")

    try:
        k = await msg.reply(
            "<b>📢 <u>Please Note</u>\n \n✅ The above file will be autodeleted in 30mins to avoid copyright issues.\n \n✅ Please forward this file to your saved messages and start downloading from there.\n \nTᴇᴀᴍ: @KR_Picture</b>",
            quote=True,
        )
        delete_timer = getattr(info, "FILE_AUTO_DELETE", 1800)
        if delete_timer > 0:
            asyncio.create_task(delete_after_delay(msg, k, delete_timer))
    except Exception:
        pass


async def delete_after_delay(msg, warning_msg, delay):
    await asyncio.sleep(delay)
    try:
        await msg.delete()
        await warning_msg.edit_text(
            "<b>Yᴏᴜʀ Vɪᴅᴇᴏ / Fɪʟᴇ ɪꜱ Sᴜᴄᴄᴇꜱꜱꜰᴜʟʟʏ Dᴇʟᴇᴛᴇᴅ !!. Tᴇᴀᴍ: @KR_Picture</b>"
        )
    except Exception:
        pass


async def get_channels_page(client: Client, page: int = 1):
    raw_chats = await _db.get_all_chats()
    if hasattr(raw_chats, "__aiter__"):
        all_chats = [c async for c in raw_chats]
    elif isinstance(raw_chats, list):
        all_chats = raw_chats
    else:
        all_chats = list(raw_chats)

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

        link = "Private / No Link"
        username = chat.get("username")

        if username:
            link = f"https://t.me/{username}"
        else:
            try:
                chat_obj = await client.get_chat(chat_id)
                if chat_obj.username:
                    link = f"https://t.me/{chat_obj.username}"
                elif chat_obj.invite_link:
                    link = chat_obj.invite_link
                else:
                    link = await client.export_chat_invite_link(chat_id)
            except Exception:
                clean_id = (
                    str(chat_id)[4:]
                    if str(chat_id).startswith("-100")
                    else str(chat_id)
                )
                link = f"https://t.me/c/{clean_id}/1"

        text += (
            f"<b>{i}. {title}</b>\n🔗 Link: {link}\n🆔 ID: <code>{chat_id}</code>\n\n"
        )

    buttons = []
    nav_row = []
    if page > 1:
        nav_row.append(
            InlineKeyboardButton(
                "⬅️ Previous", callback_data=f"channels_page#{page - 1}"
            )
        )
    if page < total_pages:
        nav_row.append(
            InlineKeyboardButton("Next ➡️", callback_data=f"channels_page#{page + 1}")
        )
    if nav_row:
        buttons.append(nav_row)
    buttons.append([InlineKeyboardButton("🔐 Close", callback_data="close_data")])

    return text, InlineKeyboardMarkup(buttons)


@Client.on_message(filters.command(["channels", "channel"]) & filters.user(ADMIN_USERS))
async def list_all_channels_cmd(client: Client, message: Message):
    status_msg = await message.reply_text("⏳ Generating link database...")
    text, reply_markup = await get_channels_page(client, page=1)
    await status_msg.edit_text(
        text, reply_markup=reply_markup, disable_web_page_preview=True
    )


@Client.on_message(
    filters.command(["leavechannel", "leave"]) & filters.user(ADMIN_USERS)
)
async def leave_channel_cmd(client: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text(
            "⚙️ <b>Usage:</b> `/leavechannel <channel_id>`\n\n<b>Example:</b> `/leavechannel -1001234567890`"
        )

    target_chat_id = message.command[1].strip()
    try:
        chat_id_int = int(target_chat_id)
    except ValueError:
        return await message.reply_text("❌ Invalid Channel ID format.")

    chat_title = "Unknown Chat"
    tg_status = "⚠️ Not inside chat (Skipped)"
    db_status = "⚠️ Not inside DB"

    try:
        chat = await client.get_chat(chat_id_int)
        chat_title = chat.title or "Unknown"
        await client.leave_chat(chat_id_int)
        tg_status = "✅ Successfully left chat."
    except Exception as e:
        tg_status = f"⚠️ Could not leave Telegram chat: {e}"

    try:
        if hasattr(_db, "delete_chat"):
            await _db.delete_chat(chat_id_int)
        elif hasattr(_db, "grp"):
            await _db.grp.delete_one({"id": chat_id_int})
            await _db.grp.delete_one({"chat_id": chat_id_int})
        db_status = "✅ Removed from Database."
    except Exception as e:
        db_status = f"❌ DB Remove Error: {e}"

    await message.reply_text(
        f"🎯 **Operation Complete:**\n\n"
        f"<b>Name:</b> {chat_title}\n"
        f"<b>ID:</b> <code>{chat_id_int}</code>\n\n"
        f"<b>Telegram Status:</b> {tg_status}\n"
        f"<b>Database Status:</b> {db_status}"
    )


@Client.on_message(filters.command("settings"))
async def settings(client: Client, message: Message):
    userid = message.from_user.id if message.from_user else None
    if not userid:
        return await message.reply("You are an anonymous admin!")
    chat_type = message.chat.type
    grp_id, title = None, None

    if chat_type == enums.ChatType.PRIVATE:
        grpid = await active_connection(str(userid))
        if grpid is not None:
            try:
                chat = await client.get_chat(grpid)
                title, grp_id = chat.title, chat.id
            except Exception:
                return await message.reply("Make sure I'm present in your group!")
        else:
            return await message.reply("You are not connected to any active group!")
    elif chat_type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
        grp_id, title = message.chat.id, message.chat.title

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
        f"⚙️ **Settings for {title}**\n\nChoose the options below to configure your group's behavior.",
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
            f"⚙️ **Settings for {title}**\n\nChoose the options below to configure your group's behavior.",
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode=enums.ParseMode.MARKDOWN,
        )
        await query.answer("Settings Updated! ✅")
    except Exception:
        await query.answer("An error occurred!", show_alert=True)


@Client.on_callback_query(
    filters.regex(
        r"^(close_data|channels_page#.*|delallconfirm|delallcancel|groupcb.*|connectcb.*|disconnect.*|deletecb.*|backcb|alertmessage.*|file.*|checksub.*|pages|start|help|about|helps_.*|stats|rfrsh)$"
    )
)
async def cb_handler(client: Client, query: CallbackQuery):
    if getattr(info, "REPAIR_MODE", False):
        if (
            str(query.from_user.id) not in [str(a) for a in info.ADMINS]
            and query.data != "close_data"
        ):
            return await query.answer("🛠️ Bot is under maintenance!", show_alert=True)

    try:
        if query.data == "close_data":
            await query.message.delete()
        elif query.data.startswith("channels_page#"):
            page_num = int(query.data.split("#")[1])
            try:
                text, reply_markup = await get_channels_page(client, page=page_num)
                await query.message.edit_text(
                    text=text, reply_markup=reply_markup, disable_web_page_preview=True
                )
            except Exception:
                pass
            await query.answer()

        elif query.data == "delallconfirm":
            userid = query.from_user.id
            chat_type = query.message.chat.type

            if chat_type == enums.ChatType.PRIVATE:
                grpid = await active_connection(str(userid))
                if grpid is not None:
                    try:
                        chat = await client.get_chat(grpid)
                        title = chat.title
                    except Exception:
                        try:
                            await query.message.edit_text(
                                "Make sure I'm present in your group!!", quote=True
                            )
                        except (MessageIdInvalid, MessageNotModified):
                            pass
                        return await query.answer("Join: @KR_PICTURE")
                else:
                    try:
                        await query.message.edit_text(
                            "I'm not connected to any groups!\nCheck /connections",
                            quote=True,
                        )
                    except (MessageIdInvalid, MessageNotModified):
                        pass
                    return await query.answer("Join: @KR_PICTURE")
            elif chat_type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
                grpid = query.message.chat.id
                title = query.message.chat.title
            else:
                return await query.answer("Join: @KR_PICTURE")

            try:
                st = await client.get_chat_member(grpid, userid)
                is_owner_or_admin = (st.status == enums.ChatMemberStatus.OWNER) or (
                    str(userid) in [str(a) for a in info.ADMINS]
                )
            except Exception:
                is_owner_or_admin = str(userid) in [str(a) for a in info.ADMINS]

            if is_owner_or_admin:
                await del_all(query.message, grpid, title)
            else:
                await query.answer(
                    "You need to be Group Owner or Admin to do that!", show_alert=True
                )

        elif query.data == "delallcancel":
            userid = query.from_user.id
            chat_type = query.message.chat.type
            if chat_type == enums.ChatType.PRIVATE:
                try:
                    await query.message.reply_to_message.delete()
                    await query.message.delete()
                except Exception:
                    pass
            elif chat_type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
                grp_id = query.message.chat.id
                try:
                    st = await client.get_chat_member(grp_id, userid)
                    is_owner_or_admin = (st.status == enums.ChatMemberStatus.OWNER) or (
                        str(userid) in [str(a) for a in info.ADMINS]
                    )
                except Exception:
                    is_owner_or_admin = str(userid) in [str(a) for a in info.ADMINS]

                if is_owner_or_admin:
                    try:
                        await query.message.delete()
                        await query.message.reply_to_message.delete()
                    except Exception:
                        pass
                else:
                    await query.answer("That's not for you!!", show_alert=True)

        elif "groupcb" in query.data:
            await query.answer()
            group_id = query.data.split(":")[1]
            act = query.data.split(":")[2]
            hr = await client.get_chat(int(group_id))
            stat = "CONNECT" if act == "" else "DISCONNECT"
            cb = "connectcb" if act == "" else "disconnect"
            keyboard = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            f"{stat}", callback_data=f"{cb}:{group_id}"
                        ),
                        InlineKeyboardButton(
                            "DELETE", callback_data=f"deletecb:{group_id}"
                        ),
                    ],
                    [InlineKeyboardButton("BACK", callback_data="backcb")],
                ]
            )
            try:
                await query.message.edit_text(
                    f"Group Name : **{hr.title}**\nGroup ID : `{group_id}`",
                    reply_markup=keyboard,
                    parse_mode=enums.ParseMode.MARKDOWN,
                )
            except (MessageIdInvalid, MessageNotModified):
                pass

        elif "connectcb" in query.data:
            await query.answer()
            group_id = query.data.split(":")[1]
            hr = await client.get_chat(int(group_id))
            if await make_active(str(query.from_user.id), str(group_id)):
                try:
                    await query.message.edit_text(
                        f"Connected to **{hr.title}**",
                        parse_mode=enums.ParseMode.MARKDOWN,
                    )
                except (MessageIdInvalid, MessageNotModified):
                    pass

        elif "disconnect" in query.data:
            await query.answer()
            group_id = query.data.split(":")[1]
            hr = await client.get_chat(int(group_id))
            if await make_inactive(str(query.from_user.id)):
                try:
                    await query.message.edit_text(
                        f"Disconnected from **{hr.title}**",
                        parse_mode=enums.ParseMode.MARKDOWN,
                    )
                except (MessageIdInvalid, MessageNotModified):
                    pass

        elif "deletecb" in query.data:
            await query.answer()
            if await delete_connection(
                str(query.from_user.id), str(query.data.split(":")[1])
            ):
                try:
                    await query.message.edit_text("Successfully deleted connection")
                except (MessageIdInvalid, MessageNotModified):
                    pass

        elif query.data == "backcb":
            await query.answer()
            groupids = await all_connections(str(query.from_user.id))
            if not groupids:
                return await query.message.edit_text("No active connections.")
            buttons = []
            for groupid in groupids:
                try:
                    ttl = await client.get_chat(int(groupid))
                    active = await if_active(str(query.from_user.id), str(groupid))
                    act = " - ACTIVE" if active else ""
                    buttons.append(
                        [
                            InlineKeyboardButton(
                                text=f"{ttl.title}{act}",
                                callback_data=f"groupcb:{groupid}:{act}",
                            )
                        ]
                    )
                except Exception:
                    pass
            if buttons:
                try:
                    await query.message.edit_text(
                        "Your connected group details ;\n\n",
                        reply_markup=InlineKeyboardMarkup(buttons),
                    )
                except (MessageIdInvalid, MessageNotModified):
                    pass

        elif "alertmessage" in query.data:
            try:
                grp_id = query.message.chat.id
                _, i, keyword = query.data.split(":", 2)
                reply_text, btn, alerts, fileid = await find_filter(grp_id, keyword)
                if alerts is not None:
                    alerts = ast.literal_eval(alerts)
                    alert = alerts[int(i)].replace("\\n", "\n").replace("\\t", "\t")
                    await query.answer(alert, show_alert=True)
                else:
                    await query.answer(
                        "No alert text set for this filter.", show_alert=True
                    )
            except (IndexError, ValueError, SyntaxError) as e:
                logger.error(f"alertmessage error: {e}")
                await query.answer("Couldn't load alert.", show_alert=True)

        elif query.data.startswith("file"):
            try:
                ident, file_id = query.data.split("#")
            except ValueError:
                return await query.answer("Invalid file request!", show_alert=True)

            files_ = await get_file_details(file_id)
            if not files_:
                return await query.answer("No such file exist.")

            files = files_[0]
            title = str(
                files.get("file_name", "Unknown")
                if isinstance(files, dict)
                else getattr(files, "file_name", "Unknown")
            )
            size = get_size(
                int(
                    files.get("file_size", 0)
                    if isinstance(files, dict)
                    else getattr(files, "file_size", 0)
                )
            )
            f_caption = str(
                files.get("caption", "")
                if isinstance(files, dict)
                else getattr(files, "caption", "")
            )

            settings = await get_settings(query.message.chat.id)
            bot_username = temp.U_NAME or (await client.get_me()).username or "bot"

            if CUSTOM_FILE_CAPTION:
                try:
                    f_caption = CUSTOM_FILE_CAPTION.format(
                        file_name="" if title is None else title,
                        file_size="" if size is None else size,
                        file_caption="" if f_caption is None else f_caption,
                    )
                except Exception as e:
                    logger.exception(str(e))

            if not f_caption:
                f_caption = f"{title}"

            try:
                if (AUTH_CHANNEL or REQ_CHANNEL) and not await is_subscribed(
                    client, query
                ):
                    return await query.answer(
                        url=f"https://t.me/{bot_username}?start={ident}_{file_id}"
                    )
                elif settings.get("botpm", False):
                    return await query.answer(
                        url=f"https://t.me/{bot_username}?start={ident}_{file_id}"
                    )
                else:
                    await client.send_cached_media(
                        chat_id=query.from_user.id,
                        file_id=file_id,
                        caption=f_caption,
                        protect_content=True if ident == "filep" else False,
                    )
                    await query.answer(
                        "Check PM, I have sent files in pm", show_alert=True
                    )
            except (UserIsBlocked, PeerIdInvalid):
                await query.answer(
                    url=f"https://t.me/{bot_username}?start={ident}_{file_id}"
                )
            except FloodWait as e:
                await asyncio.sleep(e.value + 1)
                try:
                    await client.send_cached_media(
                        chat_id=query.from_user.id,
                        file_id=file_id,
                        caption=f_caption,
                        protect_content=True if ident == "filep" else False,
                    )
                    await query.answer(
                        "Check PM, I have sent files in pm", show_alert=True
                    )
                except Exception:
                    pass
            except QueryIdInvalid:
                pass
            except Exception as e:
                logger.warning(f"File send error: {e}")
                try:
                    await query.answer(
                        url=f"https://t.me/{bot_username}?start={ident}_{file_id}"
                    )
                except Exception:
                    pass

        elif query.data.startswith("checksub"):
            if (AUTH_CHANNEL or REQ_CHANNEL) and not await is_subscribed(client, query):
                return await query.answer(
                    "Search Your Self In The Group. Team: @KR_PICTURE", show_alert=True
                )

            try:
                ident, file_id = query.data.split("#")
            except ValueError:
                return await query.answer("Invalid button data!", show_alert=True)

            files_ = await get_file_details(file_id)
            if not files_:
                return await query.answer("No such file exist.")

            files = files_[0]
            title = str(
                files.get("file_name", "Unknown")
                if isinstance(files, dict)
                else getattr(files, "file_name", "Unknown")
            )
            size = get_size(
                int(
                    files.get("file_size", 0)
                    if isinstance(files, dict)
                    else getattr(files, "file_size", 0)
                )
            )
            f_caption = str(
                files.get("caption", "")
                if isinstance(files, dict)
                else getattr(files, "caption", "")
            )

            if CUSTOM_FILE_CAPTION:
                try:
                    f_caption = CUSTOM_FILE_CAPTION.format(
                        file_name="" if title is None else title,
                        file_size="" if size is None else size,
                        file_caption="" if f_caption is None else f_caption,
                    )
                except Exception as e:
                    logger.exception(str(e))
            if not f_caption:
                f_caption = f"{title}"

            await query.answer()
            try:
                m = await client.send_cached_media(
                    chat_id=query.from_user.id,
                    file_id=file_id,
                    caption=f_caption,
                    protect_content=True if ident == "checksubp" else False,
                )
                k = await client.send_message(
                    chat_id=query.from_user.id,
                    text=(
                        "<b>📢 <u>Please Note</u>\n \n✅ The above file will be autodeleted in 30mins to avoid copyright issues.\n \n✅ Please forward this file to your saved messages and start downloading from there.\n \nTᴇᴀᴍ: @KR_Picture</b>"
                    ),
                )
            except FloodWait as e:
                await asyncio.sleep(e.value + 1)
                m = await client.send_cached_media(
                    chat_id=query.from_user.id,
                    file_id=file_id,
                    caption=f_caption,
                    protect_content=True if ident == "checksubp" else False,
                )
                k = await client.send_message(
                    chat_id=query.from_user.id,
                    text="<b>📢 <u>Please Note</u>\n \n✅ The above file will be autodeleted in 30mins.\n \nTᴇᴀᴍ: @KR_Picture</b>",
                )
            except (UserIsBlocked, PeerIdInvalid):
                return

            async def delete_and_notify():
                delete_timer = getattr(info, "FILE_AUTO_DELETE", 1800)
                await asyncio.sleep(delete_timer)
                try:
                    await m.delete()
                    await k.edit_text(
                        f"<b>Hey <i>{query.from_user.first_name}</i>\n\nYour Request Has Been Deleted 👍\n\nIF YOU WANT THAT FILE, REQUEST AGAIN ❤️</b>"
                    )
                except Exception:
                    pass

            file_timer = getattr(info, "FILE_AUTO_DELETE", 1800)
            if file_timer > 0:
                asyncio.create_task(delete_and_notify())

        elif query.data == "pages":
            await query.answer()

        elif query.data == "start":
            await query.answer()
            user_id = query.from_user.id
            buttons = [
                [
                    InlineKeyboardButton(
                        text="✈️ Group 1",
                        url="https://t.me/Sandalwood_Kannada_Group",
                        icon_custom_emoji_id=5258096772776991776,
                        style=ButtonStyle.PRIMARY,
                    ),
                    InlineKeyboardButton(
                        text="✈️ Group 2",
                        url="http://t.me/Kannada_Filmy_Group",
                        icon_custom_emoji_id=5258096772776991776,
                        style=ButtonStyle.PRIMARY,
                    ),
                    InlineKeyboardButton(
                        text="✈️ Group 3",
                        url="https://t.me/+GLsPkRgLGGszMzY1",
                        icon_custom_emoji_id=5258096772776991776,
                        style=ButtonStyle.PRIMARY,
                    ),
                ]
            ]
            if str(user_id) in [str(a) for a in info.ADMINS]:
                buttons.append(
                    [
                        InlineKeyboardButton("ℹ️ 𝙷𝚎𝚕𝚙", callback_data="help"),
                        InlineKeyboardButton("😊 𝙰𝚋𝚘𝚞𝚝", callback_data="about"),
                    ]
                )
            buttons.append(
                [
                    InlineKeyboardButton(
                        text="🔗 New Releases & OTT Updates",
                        url="https://t.me/sandalwood_kannada_moviesz",
                        icon_custom_emoji_id=5258503720928288433,
                        style=ButtonStyle.SUCCESS,
                    )
                ]
            )

            try:
                bot_uname = temp.U_NAME or "my_bot"
                b_name = temp.B_NAME or "MovieBot"
                await query.message.edit_text(
                    text=script.START_TXT.format(
                        mention=query.from_user.mention,
                        uname=bot_uname,
                        bname=b_name,
                        plane_emoji=MESSAGE_EMOJI_PLANE,
                        link_emoji=MESSAGE_EMOJI_LINK,
                    ),
                    reply_markup=InlineKeyboardMarkup(buttons),
                    parse_mode=enums.ParseMode.HTML,
                )
            except Exception as e:
                logger.error(f"Error editing start message: {e}")

        # ============================================
        # ⚡ 18-BUTTON DYNAMIC HELP MENU HANDLER
        # ============================================
                elif query.data == "help":
            await query.answer()
            buttons = [
                # ⚡ 3 NEW UI BUTTONS
                [
                    InlineKeyboardButton("🖥️ UI Start", callback_data="helps_uistart"),
                    InlineKeyboardButton("🖥️ UI Help", callback_data="helps_uihelp"),
                    InlineKeyboardButton("🖥️ UI About", callback_data="helps_uiabout")
                ],
                [
                    InlineKeyboardButton("👋 Welcome", callback_data="helps_welcome"),
                    InlineKeyboardButton("🖼️ Images", callback_data="helps_images"),
                ],
                [
                    InlineKeyboardButton("🔍 Spell Check", callback_data="helps_spell"),
                    InlineKeyboardButton("📝 Filters", callback_data="helps_filters"),
                ],
                [
                    InlineKeyboardButton("📱 Force Sub", callback_data="helps_forcesub"),
                    InlineKeyboardButton("👥 Force Add", callback_data="helps_forceadd"),
                ],
                [
                    InlineKeyboardButton("🚫 Bans", callback_data="helps_bans"),
                    InlineKeyboardButton("🗑️ Delete", callback_data="helps_delete"),
                ],
                [
                    InlineKeyboardButton("📢 Promotions", callback_data="helps_promotions"),
                    InlineKeyboardButton("📚 Index", callback_data="helps_index"),
                ],
                [
                    InlineKeyboardButton("⚙️ Settings", callback_data="helps_settings"),
                    InlineKeyboardButton("🌐 Connections", callback_data="helps_connections"),
                ],
                [
                    InlineKeyboardButton("📊 Utilities", callback_data="helps_utilities"),
                    InlineKeyboardButton("💬 Custom Messages", callback_data="helps_custommessages"),
                ],
                [
                    InlineKeyboardButton("📝 Post Handle", callback_data="helps_posthand"),
                    InlineKeyboardButton("📝 Custom Captions", callback_data="helps_customcaption"),
                ],
                [
                    InlineKeyboardButton("💾 Backup", callback_data="helps_backup"),
                ],
                [
                    InlineKeyboardButton("🔙 Back", callback_data="start"),
                    InlineKeyboardButton("🔐 Cʟᴏsᴇ", callback_data="close_data"),
                ],
            ]
            
            
            try:
                await query.message.edit_text(
                    text=script.HELP_TXT.format(mention=query.from_user.mention),
                    reply_markup=InlineKeyboardMarkup(buttons),
                    parse_mode=enums.ParseMode.HTML,
                )
            except MessageNotModified:
                pass
            except Exception as e:
                logger.error(f"Help Button Error: {e}")

        elif query.data == "about":
            await query.answer()
            buttons = [
                [InlineKeyboardButton("Sᴛᴀᴛᴜs ​", callback_data="stats")],
                [
                    InlineKeyboardButton("🏘 Hᴏᴍᴇ", callback_data="start"),
                    InlineKeyboardButton("🔐 Cʟᴏsᴇ", callback_data="close_data"),
                ],
            ]
            try:
                b_name = temp.B_NAME or "MovieBot"
                await query.message.edit_text(
                    text=script.ABOUT_TXT.format(bname=b_name),
                    reply_markup=InlineKeyboardMarkup(buttons),
                    parse_mode=enums.ParseMode.HTML,
                )
            except Exception:
                pass

        elif query.data.startswith("helps_"):
            await query.answer()
            buttons = [[InlineKeyboardButton("🔙 Back", callback_data="help")]]
            help_dict = {
                "helps_uistart": ("UISTART_TXT", "🎨 UI Start Menu"),
                "helps_uihelp": ("UIHELP_TXT", "🎨 UI Help Menu"),
                "helps_uiabout": ("UIABOUT_TXT", "🎨 UI About Menu"),
                "helps_welcome": ("WELCOME_TXT", "👋 Welcome Help"),
                "helps_images": ("IMAGES_TXT", "🖼️ Images Help"),
                "helps_spell": ("SPELLCHECK_TXT", "🔍 Spell Check Help"),
                "helps_bans": ("BANS_TXT", "🚫 Bans Help"),
                "helps_customcaption": ("CUSTOMCAPTION_TXT", "💬 Custom Captions Help"),
                "helps_delete": ("DELETE_TXT", "🗑️ Delete Help"),
                "helps_forcesub": ("FORCESUB_TXT", "📱 Force Sub Help"),
                "helps_filters": ("FILTERS_TXT", "📝 Filters Help"),
                "helps_index": ("INDEX_TXT", "📚 Index Help"),
                "helps_promotions": ("PROMOTIONS_TXT", "📢 Promotions Help"),
                "helps_settings": ("SETTINGS_TXT", "⚙️ Settings Help"),
                "helps_utilities": ("UTILITIES_TXT", "📊 Utilities Help"),
                "helps_connections": ("CONNECTIONS_TXT", "🌐 Connections Help"),
                "helps_forceadd": ("FORCEADD_TXT", "👥 Force Add Help"),
                "helps_posthand": ("POSTHAND_TXT", "📝 Post Handle Help"),
                "helps_custommessages": (
                    "CUSTOMMESSAGES_TXT",
                    "💬 Custom Messages",
                ),  # ⚡ FIXED: Typo here caused broken button
                "helps_backup": ("BACKUP_TXT", "💾 Backup Help"),
            }
            target_var, default_text = help_dict.get(
                query.data, ("HELP_TXT", "Help unavailable.")
            )
            text = getattr(script, target_var, default_text)

            try:
                await query.message.edit_text(
                    text=text,
                    reply_markup=InlineKeyboardMarkup(buttons),
                    parse_mode=enums.ParseMode.HTML,
                )
            except MessageNotModified:
                pass  # ⚡ FIXED: Prevent ugly text fallback when clicking the same button twice
            except Exception:
                # Safely fallback to raw text if HTML strictly fails due to weird characters in Script
                clean_text = re.sub(
                    r"</?(b|i|u|s|code|pre|a|blockquote)[^>]*>", "", text
                )
                try:
                    await query.message.edit_text(
                        text=clean_text,
                        reply_markup=InlineKeyboardMarkup(buttons),
                        parse_mode=enums.ParseMode.DISABLED,
                    )
                except Exception:
                    pass

        elif query.data in ["stats", "rfrsh"]:
            await query.answer()
            buttons = [
                [
                    InlineKeyboardButton("⇌ Bᴀᴄᴋ ⇌", callback_data="about"),
                    InlineKeyboardButton("♻️", callback_data="rfrsh"),
                ]
            ]
            total = await _Media.count_documents()
            users = await _db.total_users_count()
            chats = await _db.total_chat_count()
            monsize = await _db.get_db_size()
            free = 536870912 - monsize

            try:
                await query.message.edit_text(
                    text=script.STATUS_TXT.format(
                        total, users, chats, get_size(monsize), get_size(free)
                    ),
                    reply_markup=InlineKeyboardMarkup(buttons),
                    parse_mode=enums.ParseMode.HTML,
                )
            except Exception:
                pass

    except QueryIdInvalid:
        pass
