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

import requests
from motor.motor_asyncio import AsyncIOMotorClient
from pyrogram import Client, enums, filters
from pyrogram.errors import (
    ChatAdminRequired,
    FloodWait,
    MediaEmpty,
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

AUTO_DELETE_TASKS = set()

# ⚡ EXACT TELEGRAM SUPPORTED COLORS
try:
    from pyrogram.enums import ButtonStyle

    BTN_PRIMARY = getattr(ButtonStyle, "PRIMARY", 1)
    BTN_SUCCESS = getattr(ButtonStyle, "SUCCESS", 3)
    BTN_DANGER = getattr(ButtonStyle, "DANGER", 4)
except ImportError:
    BTN_PRIMARY, BTN_SUCCESS, BTN_DANGER = 1, 3, 4

# ============================================================
# ⚙️ MONGODB INITIALIZATION
# ============================================================
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


# ============================================================
# 👑 FOOLPROOF ADMIN PARSER
# ============================================================
def get_admin_list():
    raw_admins = getattr(info, "ADMINS", [])
    if isinstance(raw_admins, str):
        return [
            int(x)
            for x in raw_admins.replace(",", " ").split()
            if x.strip().lstrip("-").isdigit()
        ]
    elif isinstance(raw_admins, int):
        return [raw_admins]
    elif isinstance(raw_admins, list):
        return [int(x) for x in raw_admins if str(x).strip().lstrip("-").isdigit()]
    return []


admin_filter = filters.create(
    lambda _, __, msg: bool(msg.from_user and msg.from_user.id in get_admin_list())
)


# ============================================================
# ⚡ 10-LAYER TITANIUM CLOUD UPLOADER (ZERO-FAIL)
# ============================================================
def _upload_sync(file_bytes):
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        res = requests.post(
            "https://catbox.moe/user/api.php",
            data={"reqtype": "fileupload"},
            files={"fileToUpload": ("img.jpg", file_bytes, "image/jpeg")},
            timeout=6,
        )
    except:
        res = None
    if res and res.status_code == 200 and res.text.startswith("http"):
        return res.text.strip()

    try:
        res = requests.post(
            "https://graph.org/upload",
            files={"file": ("img.jpg", file_bytes, "image/jpeg")},
            timeout=6,
        )
    except:
        res = None
    if res and res.status_code == 200:
        return "https://graph.org" + res.json()[0]["src"]

    try:
        res = requests.post(
            "https://envs.sh",
            files={"file": ("img.jpg", file_bytes, "image/jpeg")},
            headers=headers,
            timeout=6,
        )
    except:
        res = None
    if res and res.status_code == 200 and res.text.startswith("http"):
        return res.text.strip()

    try:
        res = requests.post(
            "https://x0.at",
            files={"file": ("img.jpg", file_bytes, "image/jpeg")},
            headers=headers,
            timeout=6,
        )
    except:
        res = None
    if res and res.status_code == 200 and res.text.startswith("http"):
        return res.text.strip()

    try:
        res = requests.post(
            "https://ttm.sh",
            files={"file": ("img.jpg", file_bytes, "image/jpeg")},
            headers=headers,
            timeout=6,
        )
    except:
        res = None
    if res and res.status_code == 200 and res.text.startswith("http"):
        return res.text.strip()

    try:
        res = requests.post(
            "https://0x0.st",
            files={"file": ("img.jpg", file_bytes, "image/jpeg")},
            headers=headers,
            timeout=6,
        )
    except:
        res = None
    if res and res.status_code == 200 and res.text.startswith("http"):
        return res.text.strip()
    return None


async def upload_image_safely(client: Client, message: Message):
    try:
        file_io = await client.download_media(message, in_memory=True)
        if not file_io:
            return None
        return await asyncio.to_thread(_upload_sync, file_io.getvalue())
    except Exception:
        return None


# ============================================================
# 🛠️ HELPER FUNCTIONS
# ============================================================
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
    if user_id in get_admin_list():
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
        [
            create_btn("🧬 Auto post", callback_data="helps_autopost"),
            create_btn("💬 Pm Auto Reply", callback_data="helps_pmautoreply"),
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


# ============================================================
# 🎯 MAIN START & HELP COMMANDS
# ============================================================
@Client.on_message(filters.command(["start", "help"]) & filters.incoming)
async def start(client: Client, message: Message):
    if getattr(info, "REPAIR_MODE", False):
        if not message.from_user or message.from_user.id not in get_admin_list():
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

    # If simple /start
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

    # If deeply linked (file request or force sub)
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
    # ⚡ 3-LAYER FALLBACK FOR FILE DELIVERY
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
        msg = await client.send_cached_media(
            chat_id=message.from_user.id,
            file_id=db_file_id,
            caption=final_caption,
            protect_content=True if kk in ["filep", "checksubp"] else False,
            parse_mode=enums.ParseMode.HTML,
        )
    except Exception as e1:
        try:
            msg = await client.send_document(
                chat_id=message.from_user.id,
                document=db_file_id,
                caption=final_caption,
                reply_markup=final_keyboard,
                protect_content=True if kk in ["filep", "checksubp"] else False,
                parse_mode=enums.ParseMode.HTML,
            )
        except Exception as err:
            return await message.reply_text(
                f"⚠️ <b>Error:</b>\n<code>{err}</code>", parse_mode=enums.ParseMode.HTML
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
    if not message.reply_to_message or not message.reply_to_message.photo:
        return await message.reply_text(
            "⚙️ **Usage:** Reply to a photo with `/setpmimage`"
        )

    status = await message.reply_text(
        "⏳ **Uploading to Cloud (Testing 10 Hosters)...**"
    )
    url = await upload_image_safely(client, message.reply_to_message)

    if url:
        await save_pm_settings("image", url)
        await status.edit_text(
            "✅ **PM Image updated successfully!**\n*(Saved permanently to cloud)*"
        )
    else:
        file_id = message.reply_to_message.photo.file_id
        await save_pm_settings("image", file_id)
        await status.edit_text(
            "⚠️ Cloud blocked. **PM Image updated successfully!**\n*(Saved as Telegram File_ID)*"
        )


@Client.on_message(filters.command("rempmimage") & admin_filter)
async def rem_pm_image(client: Client, message: Message):
    await save_pm_settings("image", None)
    await message.reply_text("✅ PM Image removed.")


@Client.on_message(filters.command("setpmbutton") & admin_filter)
async def set_pm_button(client: Client, message: Message):
    try:
        if len(message.command) < 2:
            return await message.reply_text(
                "Usage: `/setpmbutton Text | URL | Color`\nColors: green, red, blue, normal"
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
# 📩 PM AUTO-REPLY ENGINE
# ============================================================
@Client.on_message(filters.private & filters.text & filters.incoming)
async def pm_auto_reply(client: Client, message: Message):
    if message.text.startswith("/"):
        return
    if getattr(info, "REPAIR_MODE", False):
        if not message.from_user or message.from_user.id not in get_admin_list():
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


# ============================================================
# ⚙️ CHANNELS & SETTINGS
# ============================================================
async def get_channels_page(client: Client, page: int = 1):
    raw_chats = await _db.get_all_chats()
    all_chats = (
        await raw_chats.to_list(length=None)
        if hasattr(raw_chats, "to_list")
        else list(raw_chats)
    )

    total_chats = len(all_chats)
    page_size = 15
    total_pages = max(1, math.ceil(total_chats / page_size))
    page = max(1, min(page, total_pages))

    start_idx = (page - 1) * page_size
    current_chats = all_chats[start_idx : start_idx + page_size]
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
    try:
        chat_id_int = int(message.command[1].strip())
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


# ============================================================
# 🎛️ INLINE CALLBACK HANDLER
# ============================================================
@Client.on_callback_query(
    filters.regex(
        r"^(close_data|channels_page#.*|delallconfirm|delallcancel|groupcb.*|connectcb.*|disconnect.*|deletecb.*|backcb|alertmessage.*|file.*|checksub.*|pages|start|help|about|helps_.*|stats|rfrsh)$"
    )
)
async def cb_handler(client: Client, query: CallbackQuery):
    if getattr(info, "REPAIR_MODE", False):
        if query.from_user.id not in get_admin_list() and query.data != "close_data":
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
        elif query.data == "start":
            await query.answer()
            ui = await get_ui()
            raw_text = ui.get("start_text") or script.START_TXT
            raw_text = raw_text.format(
                mention=query.from_user.mention,
                uname=temp.U_NAME or "my_bot",
                bname=temp.B_NAME or "MovieBot",
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
            raw_text = ui.get("help_text") or script.HELP_TXT
            raw_text = raw_text.format(
                mention=query.from_user.mention,
                uname=temp.U_NAME or "my_bot",
                bname=temp.B_NAME or "MovieBot",
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
            raw_text = ui.get("about_text") or script.ABOUT_TXT
            raw_text = raw_text.format(
                mention=query.from_user.mention, bname=temp.B_NAME or "MovieBot"
            )
            img = ui.get("about_img")
            final_text, final_keyboard = parse_text_and_markup(
                raw_text, await get_about_keyboard()
            )
            await transition_ui_message(
                client, query.message, final_text, final_keyboard, img
            )
        elif query.data.startswith("file") or query.data.startswith("checksub"):
            if query.data.startswith("checksub"):
                if (AUTH_CHANNEL or REQ_CHANNEL) and not await is_subscribed(
                    client, query
                ):
                    return await query.answer(
                        "Search Your Self In The Group. Team: @KR_PICTURE",
                        show_alert=True,
                    )

            try:
                ident, file_id = query.data.split("#")
            except ValueError:
                return await query.answer("Invalid button data!", show_alert=True)

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
            final_caption, final_keyboard = parse_text_and_markup(f_caption, None)

            await query.answer()
            m = None

            # ⚡ 3-LAYER FALLBACK FOR FILE DELIVERY
            try:
                m = await client.send_cached_media(
                    chat_id=query.from_user.id,
                    file_id=file_id,
                    caption=final_caption,
                    reply_markup=final_keyboard,
                    protect_content=True if ident in ["filep", "checksubp"] else False,
                    parse_mode=enums.ParseMode.HTML,
                )
            except FloodWait as e:
                await asyncio.sleep(e.value + 1)
                m = await client.send_cached_media(
                    chat_id=query.from_user.id,
                    file_id=file_id,
                    caption=final_caption,
                    reply_markup=final_keyboard,
                    protect_content=True if ident in ["filep", "checksubp"] else False,
                    parse_mode=enums.ParseMode.HTML,
                )
            except Exception:
                try:
                    m = await client.send_document(
                        chat_id=query.from_user.id,
                        document=file_id,
                        caption=final_caption,
                        reply_markup=final_keyboard,
                        protect_content=(
                            True if ident in ["filep", "checksubp"] else False
                        ),
                        parse_mode=enums.ParseMode.HTML,
                    )
                except Exception:
                    pass

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
    except QueryIdInvalid:
        pass
