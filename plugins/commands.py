import ast
import asyncio
import base64
import json
import math
import os
import random
import re
import sys
from logging import ERROR, getLogger
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorClient
from pyrogram import Client, enums, filters
from pyrogram.errors import (
    ChatAdminRequired,
    FloodWait,
    MessageNotModified,
    PeerIdInvalid,
    QueryIdInvalid,
    UserIsBlocked,
)
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

import info
from database.connections_mdb import (
    active_connection,
    all_connections,
    delete_connection,
    if_active,
    make_active,
    make_inactive,
)
from database.filters_mdb import del_all, find_filter
from database.ia_filterdb import Media as _Media
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
    REQ_CHANNEL,
)
from plugins.custom_settings import get_bot_settings
from plugins.editable import get_ui
from plugins.fsub import ForceSub
from Script import script
from utils import (
    get_settings,
    get_size,
    is_subscribed,
    parse_text_and_markup,
    save_group_settings,
    temp,
)

logger = getLogger(__name__)
logger.setLevel(ERROR)

BATCH_FILES = {}
LOG_FILE = "TelegramBot.log"
MESSAGE_EMOJI_PLANE = '<tg-emoji emoji-id="5875465628285931233">✈️</tg-emoji> Telegram'
MESSAGE_EMOJI_LINK = '<tg-emoji emoji-id="5877465816030515018">🔗</tg-emoji> Link'
ADMIN_USERS = [int(a) for a in ADMINS if str(a).lstrip("-").isdigit()]

AUTO_DELETE_TASKS = set()

# ⚡ EXACT TELEGRAM SUPPORTED COLORS (3 Colors + Normal Failsafe)
try:
    from pyrogram.enums import ButtonStyle

    BTN_PRIMARY = getattr(ButtonStyle, "PRIMARY", 1)  # Blue
    BTN_SUCCESS = getattr(ButtonStyle, "SUCCESS", 3)  # Green
    BTN_DANGER = getattr(ButtonStyle, "DANGER", 4)  # Red
except ImportError:
    BTN_PRIMARY = 1
    BTN_SUCCESS = 3
    BTN_DANGER = 4

# ⚡ DATABASES INITIALIZATION
pm_db = None
cw_db = None
try:
    _DB_CLIENT = AsyncIOMotorClient(info.DATABASE_URI)
    _BOT_DB = _DB_CLIENT[info.DATABASE_NAME]
    pm_db = _BOT_DB["pm_settings"]
    cw_db = _BOT_DB["clean_words"]
except Exception as e:
    logger.error(f"Failed to init databases: {e}")


async def get_pm_settings():
    if pm_db is None:
        return {}
    settings = await pm_db.find_one({"id": "pm_config"})
    if not settings:
        return {
            "text": "<b>🚫 Don't Message Here, Message Here Only!</b>\n\nI do not respond to direct messages in PM. Please join our official group to request and download movies.",
            "image": getattr(info, "NOT_FOUND_IMG", None),
            "button_text": "💬 Message Here Only",
            "button_url": "https://t.me/Sandalwood_Kannada_Group",
            "button_color": "red",
        }
    return settings


async def save_pm_settings(key, value):
    if pm_db is not None:
        await pm_db.update_one({"id": "pm_config"}, {"$set": {key: value}}, upsert=True)


admin_filter = filters.user(ADMIN_USERS)


def create_btn(text, url=None, callback_data=None, style=None):
    kwargs = {"text": text}
    if url:
        kwargs["url"] = url
    if callback_data:
        kwargs["callback_data"] = callback_data
    if style is not None:
        kwargs["style"] = style
    try:
        return InlineKeyboardButton(**kwargs)
    except TypeError:
        kwargs.pop("style", None)
        return InlineKeyboardButton(**kwargs)


# ⚡ HTML FORMAT EXTRACTOR
def get_html_text(message: Message):
    if message.reply_to_message and message.reply_to_message.text:
        return message.reply_to_message.text.html
    elif len(message.command) > 1:
        html_text = message.text.html
        html_text = re.sub(r"^/\w+(?:@[a-zA-Z0-9_]+)?\s+", "", html_text, count=1)
        return html_text
    return None


def parse_timer(var_name: str, default_time: int = 1800) -> int:
    try:
        global_switch = getattr(info, "AUTO_DELETE", True)
        if str(global_switch).strip().lower() in ["false", "off", "0"]:
            return 0
        val = getattr(info, "AUTO_DELETE_TIME", getattr(info, var_name, default_time))
        if isinstance(val, bool):
            return 1800 if val else 0
        parsed_time = int(val)
        if 0 < parsed_time < 10:
            return 1800
        return parsed_time
    except Exception:
        return 1800


async def silent_auto_delete(
    bot_message: Optional[Message],
    delay: int,
    warning_message: Optional[Message] = None,
):
    if not bot_message or delay <= 0:
        return
    await asyncio.sleep(delay)
    try:
        await bot_message.delete()
    except Exception:
        pass
    if warning_message:
        try:
            if getattr(warning_message.from_user, "is_bot", False):
                await warning_message.edit_text(
                    "<b>Hey 👋\n\nYour Request Has Been Deleted 👍\n\nIF YOU WANT THAT FILE, REQUEST AGAIN ❤️\n\nTᴇᴀᴍ: @KR_Picture</b>",
                    parse_mode=enums.ParseMode.HTML,
                )
            else:
                await warning_message.delete()
        except Exception:
            pass


def schedule_auto_delete(bot_msg, delay, warning_msg=None):
    if delay <= 0:
        return
    task = asyncio.create_task(silent_auto_delete(bot_msg, delay, warning_msg))
    AUTO_DELETE_TASKS.add(task)
    task.add_done_callback(AUTO_DELETE_TASKS.discard)


def build_dynamic_keyboard(custom_buttons, static_buttons):
    keyboard, row = [], []
    for btn in custom_buttons:
        style_map = {
            "blue": BTN_PRIMARY,
            "green": BTN_SUCCESS,
            "red": BTN_DANGER,
            "normal": None,
        }
        style = style_map.get(btn.get("color", "normal"), None)
        ibtn = create_btn(btn["text"], url=btn["url"], style=style)
        if btn.get("layout") == "sidebyside":
            row.append(ibtn)
            if len(row) == 2:
                keyboard.append(row)
                row = []
        else:
            if row:
                keyboard.append(row)
                row = []
            keyboard.append([ibtn])
    if row:
        keyboard.append(row)
    keyboard.extend(static_buttons)
    return InlineKeyboardMarkup(keyboard)


async def get_start_keyboard(user_id):
    ui = await get_ui()
    static_buttons = [
        [
            create_btn(
                "✈️ Gʀᴏᴜᴘ 1",
                url="https://t.me/Sandalwood_Kannada_Group",
                style=BTN_PRIMARY,
            ),
            create_btn(
                "✈️ Gʀᴏᴜᴘ 2", url="http://t.me/Kannada_Filmy_Group", style=BTN_PRIMARY
            ),
            create_btn(
                "✈️ Gʀᴏᴜᴘ 3", url="https://t.me/+GLsPkRgLGGszMzY1", style=BTN_PRIMARY
            ),
        ]
    ]
    if str(user_id) in [str(a) for a in ADMINS]:
        static_buttons.append(
            [
                create_btn("ℹ️ 𝙷𝚎𝚕𝚙", callback_data="help"),
                create_btn("😊 𝙰𝚋𝚘𝚞𝚝", callback_data="about"),
            ]
        )
    static_buttons.append(
        [
            create_btn(
                "🔗 Nᴇᴡ Rᴇʟᴇᴀꜱᴇꜱ & Oᴛᴛ Uᴘᴅᴀᴛᴇꜱ",
                url="https://t.me/sandalwood_kannada_moviesz",
                style=BTN_SUCCESS,
            )
        ]
    )
    return build_dynamic_keyboard(ui.get("start_buttons", []), static_buttons)


async def get_help_keyboard():
    static_buttons = [
        [
            create_btn("🖥️ UI Start", callback_data="helps_uistart"),
            create_btn("🖥️ UI Help", callback_data="helps_uihelp"),
            create_btn("🖥️ UI About", callback_data="helps_uiabout"),
        ],
        [
            create_btn("👋 Welcome", callback_data="helps_welcome"),
            create_btn("🖼️ Images", callback_data="helps_images"),
        ],
        [
            create_btn("🔍 Spell Check", callback_data="helps_spell"),
            create_btn("📝 Filters", callback_data="helps_filters"),
        ],
        [
            create_btn("📱 Force Sub", callback_data="helps_forcesub"),
            create_btn("👥 Force Add", callback_data="helps_forceadd"),
        ],
        [
            create_btn("🚫 Bans", callback_data="helps_bans"),
            create_btn("🗑️ Delete", callback_data="helps_delete"),
        ],
        [
            create_btn("📢 Promotions", callback_data="helps_promotions"),
            create_btn("📚 Index", callback_data="helps_index"),
        ],
        [
            create_btn("⚙ Settings", callback_data="helps_settings"),
            create_btn("🌐 Connections", callback_data="helps_connections"),
        ],
        [
            create_btn("📊 Utilities", callback_data="helps_utilities"),
            create_btn("💬 Custom Messages", callback_data="helps_custommessages"),
        ],
        [
            create_btn("📝 Post Handle", callback_data="helps_posthand"),
            create_btn("📝 Custom Captions", callback_data="helps_customcaption"),
        ],
        [create_btn("💾 Backup", callback_data="helps_backup", style=BTN_SUCCESS)],
        [
            create_btn("🔙 Back", callback_data="start", style=BTN_PRIMARY),
            create_btn("🔐 Cʟᴏsᴇ", callback_data="close_data", style=BTN_DANGER),
        ],
    ]
    return InlineKeyboardMarkup(static_buttons)


async def get_about_keyboard():
    return InlineKeyboardMarkup(
        [
            [create_btn("Sᴛᴀᴛᴜs ​", callback_data="stats")],
            [
                create_btn("🏘 Hᴏᴍᴇ", callback_data="start", style=BTN_SUCCESS),
                create_btn("🔐 Cʟᴏsᴇ", callback_data="close_data", style=BTN_DANGER),
            ],
        ]
    )


async def transition_ui_message(client, msg_obj, text, keyboard, img=None):
    try:
        if img:
            if msg_obj.photo or msg_obj.video or msg_obj.document:
                await msg_obj.edit_caption(
                    caption=text, reply_markup=keyboard, parse_mode=enums.ParseMode.HTML
                )
            else:
                await msg_obj.delete()
                await client.send_photo(
                    chat_id=msg_obj.chat.id,
                    photo=img,
                    caption=text,
                    reply_markup=keyboard,
                    parse_mode=enums.ParseMode.HTML,
                )
        else:
            if msg_obj.photo or msg_obj.video or msg_obj.document:
                await msg_obj.delete()
                await client.send_message(
                    chat_id=msg_obj.chat.id,
                    text=text,
                    reply_markup=keyboard,
                    parse_mode=enums.ParseMode.HTML,
                )
            else:
                await msg_obj.edit_text(
                    text=text, reply_markup=keyboard, parse_mode=enums.ParseMode.HTML
                )
    except MessageNotModified:
        pass
    except Exception as e:
        logger.error(f"UI Transition Error: {e}")


@Client.on_message(filters.command(["start", "help"]) & filters.incoming)
async def start(client: Client, message: Message):
    if getattr(info, "REPAIR_MODE", False):
        if not message.from_user or str(message.from_user.id) not in [
            str(a) for a in info.ADMINS
        ]:
            return await message.reply_text(
                "🛠️ <b>Bot is currently under maintenance!</b>",
                parse_mode=enums.ParseMode.HTML,
            )
    if message.from_user and await _plugin_db.is_banned(message.from_user.id):
        return

    bot_uname = temp.U_NAME or "my_bot"
    b_name = temp.B_NAME or "MovieBot"
    ui = await get_ui()
    is_help_command = (message.command[0] == "help") or (
        len(message.command) == 2 and message.command[1] == "help"
    )

    if is_help_command:
        text = ui.get("help_text") or script.HELP_TXT
        text = text.format(
            mention=message.from_user.mention if message.from_user else "User",
            uname=bot_uname,
            bname=b_name,
        )
        final_text, final_keyboard = parse_text_and_markup(
            text, await get_help_keyboard()
        )
        img = ui.get("help_img")

        if img:
            return await message.reply_photo(
                photo=img,
                caption=final_text,
                reply_markup=final_keyboard,
                parse_mode=enums.ParseMode.HTML,
            )
        else:
            return await message.reply_text(
                text=final_text,
                reply_markup=final_keyboard,
                parse_mode=enums.ParseMode.HTML,
            )

    if message.chat.type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
        raw_text = ui.get("start_text") or script.START_TXT
        raw_text = raw_text.format(
            mention=(
                message.from_user.mention if message.from_user else message.chat.title
            ),
            uname=bot_uname,
            bname=b_name,
            plane_emoji=MESSAGE_EMOJI_PLANE,
            link_emoji=MESSAGE_EMOJI_LINK,
        )
        final_text, final_keyboard = parse_text_and_markup(
            raw_text,
            await get_start_keyboard(message.from_user.id if message.from_user else 0),
        )

        await message.reply(
            final_text, reply_markup=final_keyboard, parse_mode=enums.ParseMode.HTML
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

    if len(message.command) != 2 or message.command[1] in ["error", "okay", "hehe"]:
        raw_text = ui.get("start_text") or script.START_TXT
        raw_text = raw_text.format(
            mention=message.from_user.mention,
            uname=bot_uname,
            bname=b_name,
            plane_emoji=MESSAGE_EMOJI_PLANE,
            link_emoji=MESSAGE_EMOJI_LINK,
        )
        final_text, final_keyboard = parse_text_and_markup(
            raw_text, await get_start_keyboard(message.from_user.id)
        )
        db_img = ui.get("start_img")
        photo_to_send = db_img if db_img else (random.choice(PICS) if PICS else None)

        try:
            if photo_to_send:
                await message.reply_photo(
                    photo=photo_to_send,
                    caption=final_text,
                    reply_markup=final_keyboard,
                    parse_mode=enums.ParseMode.HTML,
                )
            else:
                await message.reply_text(
                    text=final_text,
                    reply_markup=final_keyboard,
                    parse_mode=enums.ParseMode.HTML,
                )
        except (UserIsBlocked, PeerIdInvalid):
            pass
        return

    if message.command[1] == "subscribe":
        return await ForceSub(client, message)

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
        return await message.reply_text(
            "⚠️ No such file exists.", parse_mode=enums.ParseMode.HTML
        )

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
        f_caption = f"<b>{title}</b>"
    if getattr(info, "CAPTION_PLUS", None):
        f_caption += f"\n\n{info.CAPTION_PLUS}"

    final_caption, final_keyboard = parse_text_and_markup(
        f_caption,
        InlineKeyboardMarkup(
            [
                [
                    create_btn(
                        text="🎥 ಕನ್ನಡ ಹೊಸ ಮೂವೀಗಳು 🎥",
                        url="https://t.me/Sandalwood_kannada_moviesz",
                        style=BTN_SUCCESS,
                    )
                ]
            ]
        ),
    )

    msg = None
    try:
        msg = await client.send_cached_media(
            chat_id=message.from_user.id,
            file_id=db_file_id,
            caption=final_caption,
            reply_markup=final_keyboard,
            protect_content=True if kk in ["filep", "checksubp"] else False,
            parse_mode=enums.ParseMode.HTML,
        )
    except FloodWait as e:
        await asyncio.sleep(e.value + 1)
        try:
            msg = await client.send_cached_media(
                chat_id=message.from_user.id,
                file_id=db_file_id,
                caption=final_caption,
                protect_content=True if kk in ["filep", "checksubp"] else False,
                parse_mode=enums.ParseMode.HTML,
            )
        except Exception as err:
            return await message.reply_text(
                f"⚠️ <b>Error:</b>\n<code>{err}</code>", parse_mode=enums.ParseMode.HTML
            )
    except UserIsBlocked:
        return
    except Exception as e:
        return await message.reply_text(
            f"⚠️ <b>Error sending file:</b>\n<code>{e}</code>",
            parse_mode=enums.ParseMode.HTML,
        )

    if msg:
        try:
            k = await client.send_message(
                chat_id=message.from_user.id,
                text="<b>📢 Please Note\n\n✅ The above file will be autodeleted in 30 Minutes to avoid copyright issues.\n\n✅ Please forward this file to your saved messages and start downloading from there.\n\nTᴇᴀᴍ: @KR_Picture</b>",
                reply_to_message_id=msg.id,
                parse_mode=enums.ParseMode.HTML,
            )
            delete_timer = parse_timer("FILE_AUTO_DELETE", 1800)
            if delete_timer > 0:
                schedule_auto_delete(msg, delete_timer, k)
        except Exception as e:
            logger.error(f"Auto-delete warning failed to send: {e}")


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

    buttons, nav_row = [], []
    if page > 1:
        nav_row.append(
            create_btn(
                "⬅️ Previous",
                callback_data=f"channels_page#{page - 1}",
                style=BTN_PRIMARY,
            )
        )
    if page < total_pages:
        nav_row.append(
            create_btn(
                "Next ➡️", callback_data=f"channels_page#{page + 1}", style=BTN_PRIMARY
            )
        )
    if nav_row:
        buttons.append(nav_row)
    buttons.append(
        [create_btn("🔐 Close", callback_data="close_data", style=BTN_DANGER)]
    )
    return text, InlineKeyboardMarkup(buttons)


@Client.on_message(filters.command(["channels", "channel"]) & admin_filter)
async def list_all_channels_cmd(client: Client, message: Message):
    status_msg = await message.reply_text("⏳ Generating link database...")
    text, reply_markup = await get_channels_page(client, page=1)
    await status_msg.edit_text(
        text,
        reply_markup=reply_markup,
        disable_web_page_preview=True,
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(filters.command(["leavechannel", "leave"]) & admin_filter)
async def leave_channel_cmd(client: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text(
            "⚙️ <b>Usage:</b> <code>/leavechannel &lt;channel_id&gt;</code>",
            parse_mode=enums.ParseMode.HTML,
        )
    target_chat_id = message.command[1].strip()
    try:
        chat_id_int = int(target_chat_id)
    except ValueError:
        return await message.reply_text("❌ Invalid Channel ID format.")
    chat_title, tg_status, db_status = (
        "Unknown Chat",
        "⚠️ Not inside chat",
        "⚠️ Not inside DB",
    )

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
        f"🎯 <b>Operation Complete:</b>\n\n<b>Name:</b> {chat_title}\n<b>ID:</b> <code>{chat_id_int}</code>\n\n<b>Telegram Status:</b> {tg_status}\n<b>Database Status:</b> {db_status}",
        parse_mode=enums.ParseMode.HTML,
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
                title, gr_id = chat.title, chat.id
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
            create_btn(
                f"Buttons: {btn_text}",
                callback_data=f"setgs#button#{settings_dict.get('button', False)}#{grp_id}",
                style=BTN_PRIMARY,
            ),
            create_btn(
                f"Bot PM: {botpm_text}",
                callback_data=f"setgs#botpm#{settings_dict.get('botpm', False)}#{grp_id}",
                style=BTN_PRIMARY,
            ),
        ],
        [
            create_btn(
                f"File Secure: {file_secure_text}",
                callback_data=f"setgs#file_secure#{settings_dict.get('file_secure', False)}#{grp_id}",
                style=BTN_PRIMARY,
            ),
            create_btn(
                f"IMDB: {imdb_text}",
                callback_data=f"setgs#imdb#{settings_dict.get('imdb', False)}#{grp_id}",
                style=BTN_PRIMARY,
            ),
        ],
        [
            create_btn(
                f"Spell Check: {spell_check_text}",
                callback_data=f"setgs#spell_check#{settings_dict.get('spell_check', False)}#{grp_id}",
                style=BTN_PRIMARY,
            ),
            create_btn(
                f"Welcome: {welcome_text}",
                callback_data=f"setgs#welcome#{settings_dict.get('welcome', False)}#{grp_id}",
                style=BTN_PRIMARY,
            ),
        ],
        [create_btn("🗑 Close", callback_data="close_data", style=BTN_DANGER)],
    ]
    await message.reply_text(
        f"⚙️ <b>Settings for {title}</b>\n\nChoose the options below to configure your group's behavior.",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode=enums.ParseMode.HTML,
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
                create_btn(
                    f"Buttons: {btn_text}",
                    callback_data=f"setgs#button#{settings_dict.get('button', False)}#{grp_id}",
                    style=BTN_PRIMARY,
                ),
                create_btn(
                    f"Bot PM: {botpm_text}",
                    callback_data=f"setgs#botpm#{settings_dict.get('botpm', False)}#{grp_id}",
                    style=BTN_PRIMARY,
                ),
            ],
            [
                create_btn(
                    f"File Secure: {file_secure_text}",
                    callback_data=f"setgs#file_secure#{settings_dict.get('file_secure', False)}#{grp_id}",
                    style=BTN_PRIMARY,
                ),
                create_btn(
                    f"IMDB: {imdb_text}",
                    callback_data=f"setgs#imdb#{settings_dict.get('imdb', False)}#{grp_id}",
                    style=BTN_PRIMARY,
                ),
            ],
            [
                create_btn(
                    f"Spell Check: {spell_check_text}",
                    callback_data=f"setgs#spell_check#{settings_dict.get('spell_check', False)}#{grp_id}",
                    style=BTN_PRIMARY,
                ),
                create_btn(
                    f"Welcome: {welcome_text}",
                    callback_data=f"setgs#welcome#{settings_dict.get('welcome', False)}#{grp_id}",
                    style=BTN_PRIMARY,
                ),
            ],
            [create_btn("🗑 Close", callback_data="close_data", style=BTN_DANGER)],
        ]
        await query.message.edit_text(
            f"⚙️ <b>Settings for {title}</b>\n\nChoose the options below to configure your group's behavior.",
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode=enums.ParseMode.HTML,
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
                    text=text,
                    reply_markup=reply_markup,
                    disable_web_page_preview=True,
                    parse_mode=enums.ParseMode.HTML,
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
                        chat, title = await client.get_chat(grpid), chat.title
                    except Exception:
                        return await query.answer("Join: @KR_PICTURE")
                else:
                    return await query.answer("Join: @KR_PICTURE")
            elif chat_type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
                grpid, title = query.message.chat.id, query.message.chat.title
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
            try:
                await query.message.delete()
            except Exception:
                pass
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
                        create_btn(
                            f"{stat}",
                            callback_data=f"{cb}:{group_id}",
                            style=BTN_PRIMARY,
                        ),
                        create_btn(
                            "DELETE",
                            callback_data=f"deletecb:{group_id}",
                            style=BTN_DANGER,
                        ),
                    ],
                    [create_btn("BACK", callback_data="backcb")],
                ]
            )
            try:
                await query.message.edit_text(
                    f"Group Name : <b>{hr.title}</b>\nGroup ID : <code>{group_id}</code>",
                    reply_markup=keyboard,
                    parse_mode=enums.ParseMode.HTML,
                )
            except Exception:
                pass
        elif "connectcb" in query.data:
            await query.answer()
            group_id = query.data.split(":")[1]
            hr = await client.get_chat(int(group_id))
            if await make_active(str(query.from_user.id), str(group_id)):
                try:
                    await query.message.edit_text(
                        f"Connected to <b>{hr.title}</b>",
                        parse_mode=enums.ParseMode.HTML,
                    )
                except Exception:
                    pass
        elif "disconnect" in query.data:
            await query.answer()
            group_id = query.data.split(":")[1]
            hr = await client.get_chat(int(group_id))
            if await make_inactive(str(query.from_user.id)):
                try:
                    await query.message.edit_text(
                        f"Disconnected from <b>{hr.title}</b>",
                        parse_mode=enums.ParseMode.HTML,
                    )
                except Exception:
                    pass
        elif "deletecb" in query.data:
            await query.answer()
            if await delete_connection(
                str(query.from_user.id), str(query.data.split(":")[1])
            ):
                try:
                    await query.message.edit_text(
                        "Successfully deleted connection",
                        parse_mode=enums.ParseMode.HTML,
                    )
                except Exception:
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
                            create_btn(
                                text=f"{ttl.title}{act}",
                                callback_data=f"groupcb:{groupid}:{act}",
                                style=BTN_PRIMARY,
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
                        parse_mode=enums.ParseMode.HTML,
                    )
                except Exception:
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
            except Exception:
                await query.answer("Couldn't load alert.", show_alert=True)
        elif query.data.startswith("file"):
            try:
                ident, file_id = query.data.split("#")
            except ValueError:
                return await query.answer("Invalid file request!", show_alert=True)

            files_ = await get_file_details(file_id)
            if not files_:
                return await query.answer("No such file exist.", show_alert=True)

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
                except Exception:
                    pass
            if not f_caption:
                f_caption = f"<b>{title}</b>"
            final_caption, final_keyboard = parse_text_and_markup(f_caption, None)

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
                    m = await client.send_cached_media(
                        chat_id=query.from_user.id,
                        file_id=file_id,
                        caption=final_caption,
                        reply_markup=final_keyboard,
                        protect_content=True if ident == "filep" else False,
                        parse_mode=enums.ParseMode.HTML,
                    )
                    k = await client.send_message(
                        chat_id=query.from_user.id,
                        text="<b>📢 Please Note\n\n✅ The above file will be autodeleted in 30 Minutes to avoid copyright issues.\n\n✅ Please forward this file to your saved messages and start downloading from there.\n\nTᴇᴀᴍ: @KR_Picture</b>",
                        reply_to_message_id=m.id,
                        parse_mode=enums.ParseMode.HTML,
                    )
                    await query.answer(
                        "Check PM, I have sent the files!", show_alert=True
                    )
                    delete_timer = parse_timer("FILE_AUTO_DELETE", 1800)
                    if delete_timer > 0:
                        schedule_auto_delete(m, delete_timer, k)
            except Exception:
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
                except Exception:
                    pass
            if not f_caption:
                f_caption = f"<b>{title}</b>"
            final_caption, final_keyboard = parse_text_and_markup(f_caption, None)

            await query.answer()
            m = None
            try:
                m = await client.send_cached_media(
                    chat_id=query.from_user.id,
                    file_id=file_id,
                    caption=final_caption,
                    reply_markup=final_keyboard,
                    protect_content=True if ident == "checksubp" else False,
                    parse_mode=enums.ParseMode.HTML,
                )
            except FloodWait as e:
                await asyncio.sleep(e.value + 1)
                try:
                    m = await client.send_cached_media(
                        chat_id=query.from_user.id,
                        file_id=file_id,
                        caption=final_caption,
                        reply_markup=final_keyboard,
                        protect_content=True if ident == "checksubp" else False,
                        parse_mode=enums.ParseMode.HTML,
                    )
                except Exception:
                    pass
            except (UserIsBlocked, PeerIdInvalid):
                return

            if m:
                try:
                    k = await client.send_message(
                        chat_id=query.from_user.id,
                        text="<b>📢 Please Note\n\n✅ The above file will be autodeleted in 30 Minutes to avoid copyright issues.\n\n✅ Please forward this file to your saved messages and start downloading from there.\n\nTᴇᴀᴍ: @KR_Picture</b>",
                        reply_to_message_id=m.id,
                        parse_mode=enums.ParseMode.HTML,
                    )
                    delete_timer = parse_timer("FILE_AUTO_DELETE", 1800)
                    if delete_timer > 0:
                        schedule_auto_delete(m, delete_timer, k)
                except Exception:
                    pass

        elif query.data == "pages":
            await query.answer()
        elif query.data == "start":
            await query.answer()
            ui = await get_ui()
            bot_uname = temp.U_NAME or "my_bot"
            b_name = temp.B_NAME or "MovieBot"
            raw_text = ui.get("start_text") or script.START_TXT
            raw_text = raw_text.format(
                mention=query.from_user.mention,
                uname=bot_uname,
                bname=b_name,
                plane_emoji=MESSAGE_EMOJI_PLANE,
                link_emoji=MESSAGE_EMOJI_LINK,
            )
            img = ui.get("start_img")
            final_text, final_keyboard = parse_text_and_markup(
                raw_text, await get_start_keyboard(query.from_user.id)
            )
            await transition_ui_message(
                client, query.message, final_text, final_keyboard, img
            )
        elif query.data == "help":
            await query.answer()
            ui = await get_ui()
            bot_uname = temp.U_NAME or "my_bot"
            b_name = temp.B_NAME or "MovieBot"
            raw_text = ui.get("help_text") or script.HELP_TXT
            raw_text = raw_text.format(
                mention=query.from_user.mention, uname=bot_uname, bname=b_name
            )
            img = ui.get("help_img")
            final_text, final_keyboard = parse_text_and_markup(
                raw_text, await get_help_keyboard()
            )
            await transition_ui_message(
                client, query.message, final_text, final_keyboard, img
            )
        elif query.data == "about":
            await query.answer()
            ui = await get_ui()
            bot_uname = temp.U_NAME or "my_bot"
            b_name = temp.B_NAME or "MovieBot"
            raw_text = ui.get("about_text") or script.ABOUT_TXT
            raw_text = raw_text.format(mention=query.from_user.mention, bname=b_name)
            img = ui.get("about_img")
            final_text, final_keyboard = parse_text_and_markup(
                raw_text, await get_about_keyboard()
            )
            await transition_ui_message(
                client, query.message, final_text, final_keyboard, img
            )
        elif query.data.startswith("helps_"):
            await query.answer()
            buttons = [[create_btn("🔙 Back", callback_data="help")]]
            help_dict = {
                "helps_uistart": ("UISTART_TXT", "🎨 UI Start Menu"),
                "helps_uihelp": ("UIHELP_TXT", "🎨 UI Help Menu"),
                "helps_uiabout": ("UIABOUT_TXT", "🎨 UI About Menu"),
                "helps_welcome": ("WELCOME_TXT", "👋 Welcome Help"),
                "helps_images": ("IMAGES_TXT", "🖼️ Images Help"),
                "helps_spell": ("SPELLCHECK_TXT", "🔍 Spell Check Help"),
                "helps_filters": ("FILTERS_TXT", "📝 Filters Help"),
                "helps_forcesub": ("FORCESUB_TXT", "📱 Force Sub Help"),
                "helps_forceadd": ("FORCEADD_TXT", "👥 Force Add Help"),
                "helps_bans": ("BANS_TXT", "🚫 Bans Help"),
                "helps_delete": ("DELETE_TXT", "🗑 Delete Help"),
                "helps_promotions": ("PROMOTIONS_TXT", "📢 Promotions Help"),
                "helps_index": ("INDEX_TXT", "📚 Index Help"),
                "helps_settings": ("SETTINGS_TXT", "⚙️ Settings Help"),
                "helps_connections": ("CONNECTIONS_TXT", "🌐 Connections Help"),
                "helps_utilities": ("UTILITIES_TXT", "📊 Utilities Help"),
                "helps_custommessages": ("CUSTOMMESSAGES_TXT", "💬 Custom Messages"),
                "helps_posthand": ("POSTHAND_TXT", "📝 Post Handle Help"),
                "helps_customcaption": ("CUSTOMCAPTION_TXT", "📝 Custom Captions Help"),
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
                pass
            except Exception:
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
                    create_btn("⇌ Bᴀᴄᴋ ⇌", callback_data="about"),
                    create_btn("♻️", callback_data="rfrsh", style=BTN_SUCCESS),
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


# ============================================================
# ⚙️ CLEAN FILENAME COMMANDS
# ============================================================
@Client.on_message(filters.command("setcleanfilename") & admin_filter)
async def set_clean_words(client: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text(
            "⚠️ **Usage:** `/setcleanfilename word1, word2, @ChannelName`"
        )
    words = message.text.split(None, 1)[1]
    words_list = [w.strip() for w in words.split(",") if w.strip()]
    if cw_db is not None:
        await cw_db.update_one(
            {"id": "words"},
            {"$set": {"list": words_list, "use_default": False}},
            upsert=True,
        )
        await message.reply_text(
            f"✅ **Clean Words Set Successfully!**\n\nThe following words will be removed from buttons:\n`{', '.join(words_list)}`"
        )


@Client.on_message(filters.command("defaultcleanfilename") & admin_filter)
async def default_clean_words(client: Client, message: Message):
    if cw_db is not None:
        await cw_db.update_one(
            {"id": "words"}, {"$set": {"use_default": True}}, upsert=True
        )
        await message.reply_text(
            "✅ **Reverted to Default Clean Words!**\n(Standard extensions and default tags will be removed)."
        )


@Client.on_message(filters.command("remcleanfilename") & admin_filter)
async def rem_clean_words(client: Client, message: Message):
    if cw_db is not None:
        await cw_db.update_one(
            {"id": "words"}, {"$set": {"list": [], "use_default": False}}, upsert=True
        )
        await message.reply_text(
            "🗑️ **All Clean Words Removed.**\nFilenames will now display exactly as they are uploaded."
        )


# ============================================================
# ⚙️ PM REPLY SETTINGS SETUP COMMANDS
# ============================================================
@Client.on_message(filters.command("setpmtext") & admin_filter)
async def set_pm_text(client: Client, message: Message):
    try:
        text = get_html_text(message)
        if not text:
            return await message.reply_text(
                "Usage: `/setpmtext Your Text Here` (Supports HTML bold, quotes, links, etc.) or reply to a text."
            )
        await save_pm_settings("text", text)
        await message.reply_text(f"✅ PM Text updated successfully to:\n\n{text}")
    except Exception as e:
        await message.reply_text(f"Error: {e}")


@Client.on_message(filters.command("rempmtext") & admin_filter)
async def rem_pm_text(client: Client, message: Message):
    await save_pm_settings(
        "text",
        "<b>🚫 Don't Message Here, Message Here Only!</b>\n\nI do not respond to direct messages in PM. Please join our official group to request and download movies.",
    )
    await message.reply_text("✅ PM Text reset to default.")


@Client.on_message(filters.command("setpmimage") & admin_filter)
async def set_pm_image(client: Client, message: Message):
    try:
        if message.reply_to_message and message.reply_to_message.photo:
            file_id = message.reply_to_message.photo.file_id
            await save_pm_settings("image", file_id)
            return await message.reply_text(
                "✅ PM Image updated successfully from replied photo!"
            )
        elif len(message.command) > 1:
            url = message.text.split(None, 1)[1]
            await save_pm_settings("image", url)
            return await message.reply_text("✅ PM Image URL updated successfully!")
        await message.reply_text("Usage: `/setpmimage [URL]` or reply to a photo.")
    except Exception as e:
        await message.reply_text(f"Error: {e}")


@Client.on_message(filters.command("rempmimage") & admin_filter)
async def rem_pm_image(client: Client, message: Message):
    await save_pm_settings("image", None)
    await message.reply_text("✅ PM Image removed.")


@Client.on_message(filters.command("setpmbutton") & admin_filter)
async def set_pm_button(client: Client, message: Message):
    try:
        if len(message.command) < 2:
            return await message.reply_text(
                "Usage: `/setpmbutton Text | URL | Color`\nColors: green, red, blue, normal\nExample: `/setpmbutton Join Here | https://t.me/xyz | green`"
            )
        args = message.text.split(None, 1)[1].split("|")
        if len(args) < 2:
            return await message.reply_text(
                "❌ Invalid format. Use: `Text | URL | Color`"
            )

        btn_text, btn_url = args[0].strip(), args[1].strip()
        btn_color = args[2].strip().lower() if len(args) > 2 else "normal"
        if btn_color not in ["green", "red", "blue", "normal"]:
            btn_color = "normal"

        await save_pm_settings("button_text", btn_text)
        await save_pm_settings("button_url", btn_url)
        await save_pm_settings("button_color", btn_color)
        await message.reply_text(
            f"✅ PM Button updated!\nText: {btn_text}\nURL: {btn_url}\nColor: {btn_color}"
        )
    except Exception as e:
        await message.reply_text(f"Error: {e}")


@Client.on_message(filters.command("rempmbutton") & admin_filter)
async def rem_pm_button(client: Client, message: Message):
    await save_pm_settings("button_text", None)
    await save_pm_settings("button_url", None)
    await message.reply_text("✅ PM Button removed completely.")


# ============================================================
# 📩 PM AUTO-REPLY ENGINE (DON'T MESSAGE HERE)
# ============================================================
@Client.on_message(filters.private & filters.text & filters.incoming)
async def pm_auto_reply(client: Client, message: Message):
    if message.text.startswith("/"):
        return
    if getattr(info, "REPAIR_MODE", False):
        if not message.from_user or str(message.from_user.id) not in [
            str(a) for a in info.ADMINS
        ]:
            return
    if message.from_user and await _plugin_db.is_banned(message.from_user.id):
        return

    settings = await get_pm_settings()
    text = settings.get(
        "text",
        "<b>🚫 Don't Message Here, Message Here Only!</b>\n\nI do not respond to direct messages in PM. Please join our official group to request and download movies.",
    )
    pm_img = settings.get("image", getattr(info, "NOT_FOUND_IMG", None))

    btn_text = settings.get("button_text", "💬 Message Here Only")
    btn_url = settings.get("button_url", "https://t.me/Sandalwood_Kannada_Group")
    btn_color_str = settings.get("button_color", "green")

    color_map = {
        "green": BTN_SUCCESS,
        "red": BTN_DANGER,
        "blue": BTN_PRIMARY,
        "normal": None,
    }
    btn_style = color_map.get(btn_color_str, None)

    reply_markup = None
    if btn_text and btn_url:
        buttons = [[create_btn(btn_text, url=btn_url, style=btn_style)]]
        reply_markup = InlineKeyboardMarkup(buttons)

    try:
        if pm_img and str(pm_img).lower() != "none":
            await message.reply_photo(
                photo=pm_img,
                caption=text,
                reply_markup=reply_markup,
                parse_mode=enums.ParseMode.HTML,
            )
        else:
            await message.reply_text(
                text=text, reply_markup=reply_markup, parse_mode=enums.ParseMode.HTML
            )
    except Exception as e:
        logger.error(f"PM Reply Error: {e}")
