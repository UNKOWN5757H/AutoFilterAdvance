import ast
import asyncio
import logging
import math
import re

from pyrogram import Client, enums, filters
from pyrogram.enums import ButtonStyle
from pyrogram.errors import (
    ButtonUrlInvalid,
    FloodWait,
    Forbidden,
    MessageIdInvalid,
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
from database.filters_mdb import del_all, find_filter, get_filters
from database.ia_filterdb import Media, get_file_details, get_search_results
from database.plugin_dbs import plugin_db
from database.users_chats_db import db
from info import ADMINS, AUTH_CHANNEL, CUSTOM_FILE_CAPTION, REQ_CHANNEL
from Script import script
from utils import get_poster, get_settings, get_size, is_subscribed, search_gagala, temp

logger = logging.getLogger(__name__)
logger.setLevel(logging.ERROR)

BUTTONS = {}
SPELL_CHECK = {}

FILE_NOT_FOUND_PIC = getattr(
    info,
    "NOT_FOUND_IMG",
    "https://telegra.ph/file/c4f0458d30f61993aad45-086b84e8363b3c582e.jpg",
)
NOT_FOUND_TEXT = getattr(info, "NOT_FOUND_MSG", "<b>🚫 File not found.</b>")
MESSAGE_EMOJI_PLANE = '<tg-emoji emoji-id="5875465628285931233">✈️</tg-emoji> Telegram'
MESSAGE_EMOJI_LINK = '<tg-emoji emoji-id="5877465816030515018">🔗</tg-emoji> Link'

STOPWORDS = [
    "send",
    "snd",
    "give",
    "gib",
    "pls",
    "plz",
    "please",
    "need",
    "want",
    "upload",
    "uplod",
    "drop",
    "share",
    "find",
    "search",
    "provide",
    "post",
    "movie",
    "movies",
    "film",
    "films",
    "cinema",
    "cinemas",
    "full",
    "fullmovie",
    "download",
    "downlod",
    "link",
    "links",
    "file",
    "files",
    "print",
    "audio",
    "video",
    "ott",
    "hd",
    "hq",
    "bluray",
    "rip",
    "watch",
    "online",
    "bro",
    "bhai",
    "anna",
    "boss",
    "admin",
    "sir",
    "madam",
    "brodie",
    "dude",
    "macha",
    "machha",
    "guru",
    "chinnu",
    "brother",
    "beku",
    "bekithu",
    "bekittu",
    "bekagide",
    "kodi",
    "kodro",
    "kalsi",
    "kalsro",
    "kalisi",
    "haki",
    "haku",
    "hakro",
    "ideya",
    "irboda",
    "bidi",
    "madu",
    "yaradru",
    "chitra",
    "chithra",
    "chalanachitra",
    "chalanachithra",
    "kannadadalli",
    "sandalwood",
    "kr_picture",
    "kannada_filmy_group",
    "telegram",
]


def sanitize_search_query(text: str) -> str:
    if not text:
        return ""
    q = text.lower().strip()
    q = re.sub(r"https?://\S+|t\.me/\S+|@\w+", "", q)
    q = re.sub(r"[\[\]\(\)\{\}\-_.:|/#+]", " ", q)
    pattern = r"\b(" + "|".join(re.escape(w) for w in STOPWORDS) + r")\b"
    q = re.sub(pattern, " ", q, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", q).strip()


def clean_filename(name: str) -> str:
    if not name:
        return "File"
    name = re.sub(r"(?i)\[?@?sandalwood[^\]\s]*\]?", "", name)
    name = re.sub(r"(?i)\bsandalwood\b", "", name)
    name = re.sub(r"[_.-]", " ", name)
    name = re.sub(r"(?i)\b(mkv|mp4|avi|webm|zip|rar)\b", "", name)
    return re.sub(r"\s+", " ", name).strip()


async def silent_auto_delete(bot_message, delay: int, user_message=None):
    if not bot_message:
        return
    await asyncio.sleep(delay)
    try:
        await bot_message.delete()
    except Exception:
        pass
    if user_message:
        try:
            await user_message.delete()
        except Exception:
            pass


async def expire_cache_entry(cache: dict, key, delay: int):
    await asyncio.sleep(delay)
    cache.pop(key, None)


async def advantage_spell_chok(client, msg, search_query):
    clean_text = search_query or sanitize_search_query(msg.text)
    query = clean_text + " movie"
    g_s = await search_gagala(query) or []
    g_s += await search_gagala(clean_text) or []

    if not g_s:
        try:
            k_msg = await msg.reply_photo(
                photo=FILE_NOT_FOUND_PIC, caption=NOT_FOUND_TEXT
            )
        except Exception:
            try:
                k_msg = await msg.reply_text(text=NOT_FOUND_TEXT)
            except Exception:
                k_msg = None
        if k_msg:
            delete_timer = getattr(info, "BUTTON_AUTO_DELETE", 1800)
            if delete_timer > 0:
                asyncio.create_task(silent_auto_delete(k_msg, delete_timer, msg))
        return

    regex = re.compile(r".*(imdb|wikipedia).*", re.IGNORECASE)
    gs = list(filter(regex.match, g_s))
    gs_parsed = [
        re.sub(
            r"\b(\-([a-zA-Z-\s])\-\simdb|(\-\s)?imdb|(\-\s)?wikipedia|\(|\)|\-|reviews|full|all|episode(s)?|film|movie|series)",
            "",
            i,
            flags=re.IGNORECASE,
        )
        for i in gs
    ]

    if not gs_parsed:
        reg = re.compile(r"watch(\s[a-zA-Z0-9_\s\-\(\)]*)*\|.*", re.IGNORECASE)
        for mv in g_s:
            match = reg.match(mv)
            if match:
                gs_parsed.append(match.group(1))

    user = msg.from_user.id if msg.from_user else 0
    movielist = []
    gs_parsed = list(dict.fromkeys(gs_parsed))[:3]

    if gs_parsed:
        for mov in gs_parsed:
            try:
                imdb_s = await get_poster(mov.strip(), bulk=True)
                if imdb_s:
                    movielist += [movie.get("title") for movie in imdb_s]
            except Exception:
                pass

    movielist += [
        re.sub(r"(\-|\(|\)|_)", "", i, flags=re.IGNORECASE).strip() for i in gs_parsed
    ]
    movielist = list(dict.fromkeys([m for m in movielist if m]))

    if not movielist:
        try:
            k_msg = await msg.reply_photo(
                photo=FILE_NOT_FOUND_PIC, caption=NOT_FOUND_TEXT
            )
        except Exception:
            try:
                k_msg = await msg.reply_text(text=NOT_FOUND_TEXT)
            except Exception:
                k_msg = None
        if k_msg:
            delete_timer = getattr(info, "BUTTON_AUTO_DELETE", 1800)
            if delete_timer > 0:
                asyncio.create_task(silent_auto_delete(k_msg, delete_timer, msg))
        return

    SPELL_CHECK[msg.id] = movielist
    spell_check_ttl = getattr(info, "BUTTON_AUTO_DELETE", 1800)
    if spell_check_ttl > 0:
        asyncio.create_task(expire_cache_entry(SPELL_CHECK, msg.id, spell_check_ttl))

    btn = [
        [
            InlineKeyboardButton(
                text=movie.strip(), callback_data=f"spolling#{user}#{idx}"
            )
        ]
        for idx, movie in enumerate(movielist)
    ]
    btn.append(
        [
            InlineKeyboardButton(
                text="Close", callback_data=f"spolling#{user}#close_spellcheck"
            )
        ]
    )

    try:
        await msg.reply(
            "<b>I couldn't find exact files. Did you mean one of these?</b>",
            reply_markup=InlineKeyboardMarkup(btn),
        )
    except Forbidden:
        pass


def build_keyboard(btn_str: str):
    if not btn_str or btn_str in ["[]", "None", "False", ""]:
        return None
    try:
        parsed_btn = ast.literal_eval(btn_str)
        button_layout = []
        for row in parsed_btn:
            btn_row = []
            for b in row:
                if isinstance(b, dict):
                    b_copy = b.copy()
                    style_val = b_copy.pop("style", None)
                    style_map = {
                        1: ButtonStyle.PRIMARY,
                        3: ButtonStyle.SUCCESS,
                        4: ButtonStyle.DANGER,
                    }
                    btn_obj = InlineKeyboardButton(**b_copy)
                    if style_val in style_map:
                        btn_obj.style = style_map[style_val]
                    elif isinstance(style_val, ButtonStyle):
                        btn_obj.style = style_val
                    btn_row.append(btn_obj)
                else:
                    btn_row.append(b)
            button_layout.append(btn_row)
        return button_layout
    except Exception as e:
        logger.error(f"Button parsing error: {e}")
        return None


async def manual_filters(client, message, text=False):
    group_id = message.chat.id
    name = text or message.text or message.caption or ""
    reply_id = message.reply_to_message.id if message.reply_to_message else message.id
    keywords = await get_filters(group_id)
    if not keywords:
        return False

    for keyword in reversed(sorted(keywords, key=len)):
        pattern = r"( |^|[^\w])" + re.escape(keyword) + r"( |$|[^\w])"
        if re.search(pattern, name, flags=re.IGNORECASE):
            reply_text, btn, alert, fileid = await find_filter(group_id, keyword)
            if reply_text:
                reply_text = reply_text.replace("\\n", "\n").replace("\\t", "\t")

            button_layout = build_keyboard(btn)
            reply_markup = (
                InlineKeyboardMarkup(button_layout) if button_layout else None
            )

            sent_msg = None
            fileid_str = str(fileid).strip()

            if not fileid or fileid_str in ["None", "[]", "", "False"]:
                try:
                    sent_msg = await client.send_message(
                        message.chat.id,
                        reply_text or "",
                        disable_web_page_preview=True,
                        reply_markup=reply_markup,
                        reply_to_message_id=reply_id,
                    )
                except Exception:
                    try:
                        sent_msg = await client.send_message(
                            message.chat.id,
                            reply_text or "",
                            disable_web_page_preview=True,
                            reply_markup=reply_markup,
                        )
                    except Exception as e:
                        logger.error(f"Error sending text filter: {e}")
            else:
                try:
                    sent_msg = await client.send_cached_media(
                        message.chat.id,
                        fileid,
                        caption=reply_text or "",
                        reply_markup=reply_markup,
                        reply_to_message_id=reply_id,
                    )
                except Exception:
                    try:
                        sent_msg = await client.send_cached_media(
                            message.chat.id,
                            fileid,
                            caption=reply_text or "",
                            reply_markup=reply_markup,
                        )
                    except Exception:
                        try:
                            sent_msg = await client.send_photo(
                                message.chat.id,
                                photo=fileid,
                                caption=reply_text or "",
                                reply_markup=reply_markup,
                            )
                        except Exception as e:
                            logger.error(f"Error sending cached media: {e}")

            if sent_msg:
                delete_timer = getattr(info, "BUTTON_AUTO_DELETE", 1800)
                if delete_timer > 0:
                    asyncio.create_task(
                        silent_auto_delete(sent_msg, delete_timer, message)
                    )
            return True
    return False


async def auto_filter(client, msg, spoll=False):
    if not spoll:
        message = msg
        settings = await get_settings(message.chat.id)
        if not message.text or message.text.startswith(
            ("/", "!", "#", ".", ",", "?", "@")
        ):
            return

        search = sanitize_search_query(message.text)
        if not search or len(search) < 2:
            return

        files, offset, total_results = await get_search_results(
            search, max_results=10, offset=0, filter=True
        )

        if not files:
            stripped_search = re.sub(
                r"(?i)\b(kannada|telugu|tamil|malayalam|hindi|english|dual|multi)\b",
                "",
                search,
            ).strip()
            if stripped_search and stripped_search != search:
                files, offset, total_results = await get_search_results(
                    stripped_search, max_results=10, offset=0, filter=True
                )
                if files:
                    search = stripped_search

        if not files:
            if settings.get("spell_check"):
                return await advantage_spell_chok(client, msg, search)
            return
    else:
        settings = await get_settings(msg.message.chat.id)
        message = msg.message.reply_to_message
        if not message:
            message = msg.message
        search, files, offset, total_results = spoll

    if not files:
        return

    files.sort(
        key=lambda x: (
            x.get("file_size", 0) if isinstance(x, dict) else getattr(x, "file_size", 0)
        )
    )
    pre = "filep" if settings.get("file_secure") else "file"
    btn = []

    if not temp.U_NAME:
        try:
            bot_me = await client.get_me()
            temp.U_NAME = bot_me.username
        except Exception:
            pass
    bot_username = temp.U_NAME or "my_bot"

    for file in files:
        file_id = str(
            file.get("file_id", "")
            if isinstance(file, dict)
            else getattr(file, "file_id", "")
        )
        raw_name = str(
            file.get("file_name", "Unknown")
            if isinstance(file, dict)
            else getattr(file, "file_name", "Unknown")
        )
        file_size = int(
            file.get("file_size", 0)
            if isinstance(file, dict)
            else getattr(file, "file_size", 0)
        )
        display_name = clean_filename(raw_name)

        if settings.get("button", False):
            btn.append(
                [
                    InlineKeyboardButton(
                        text=f"{get_size(file_size)} | {display_name}",
                        url=f"https://t.me/{bot_username}?start={pre}_{file_id}",
                    )
                ]
            )
        else:
            btn.append(
                [
                    InlineKeyboardButton(
                        text=f"{display_name}",
                        url=f"https://t.me/{bot_username}?start={pre}_{file_id}",
                    ),
                    InlineKeyboardButton(
                        text=f"{get_size(file_size)}",
                        url=f"https://t.me/{bot_username}?start={pre}_{file_id}",
                    ),
                ]
            )

    btn.insert(
        0,
        [
            InlineKeyboardButton(
                text="• Bᴀᴄᴋ Uᴘ Cʜᴀɴɴᴇʟ •",
                url="https://t.me/KR_Picture",
                icon_custom_emoji_id=5258503720928288433,
                style=ButtonStyle.SUCCESS,
            )
        ],
    )

    if offset:
        key = f"{message.chat.id}-{message.id}"
        BUTTONS[key] = search
        req = message.from_user.id if message.from_user else 0
        cache_ttl = getattr(info, "BUTTON_AUTO_DELETE", 1800)
        if cache_ttl > 0:
            asyncio.create_task(expire_cache_entry(BUTTONS, key, cache_ttl))
        btn.append(
            [
                InlineKeyboardButton(
                    text=f"1/{math.ceil(int(total_results) / 10)}",
                    callback_data="pages",
                ),
                InlineKeyboardButton(
                    text="NEXT", callback_data=f"next_{req}_{key}_{offset}"
                ),
            ]
        )
    else:
        btn.append([InlineKeyboardButton(text="1/1", callback_data="pages")])

    mention = message.from_user.mention if message.from_user else "User"
    cap = f"<b>Hᴇʏ {mention} 👋🏻\n\n➤ Tɪᴛʟᴇ : {search.title()}\n➤ Yᴏᴜʀ Fɪʟᴇꜱ Rᴇᴀᴅʏ Nᴏᴡ 👇</b>"

    try:
        m = await message.reply_text(cap, reply_markup=InlineKeyboardMarkup(btn))
    except FloodWait as e:
        await asyncio.sleep(e.value)
        try:
            m = await message.reply_text(cap, reply_markup=InlineKeyboardMarkup(btn))
        except Exception as e2:
            logger.exception(f"auto_filter retry error: {e2}")
            return
    except Exception as e:
        logger.exception(f"auto_filter error: {e}")
        return

    if spoll:
        try:
            await msg.message.delete()
        except MessageIdInvalid:
            pass

    delete_timer = getattr(info, "BUTTON_AUTO_DELETE", 1800)
    if delete_timer > 0:
        asyncio.create_task(silent_auto_delete(m, delete_timer, message))


@Client.on_message((filters.group) & filters.text & filters.incoming)
async def give_filter(client, message):
    if getattr(info, "REPAIR_MODE", False):
        if not message.from_user or (
            str(message.from_user.id) not in [str(a) for a in info.ADMINS]
        ):
            return await message.reply_text(
                "🛠️ **Bot is currently under maintenance!**\n\nWe are performing some upgrades/fixes. Please try again later."
            )
    if message.from_user and await plugin_db.is_banned(message.from_user.id):
        return

    try:
        k = await manual_filters(client, message)
    except Exception as e:
        logger.error(f"Manual filter error: {e}")
        k = False

    if not k:
        try:
            await auto_filter(client, message)
        except Exception as e:
            logger.error(f"Auto filter error: {e}")


# ============================================================
# 📄 CHANNELS & LEAVE CHANNEL COMMANDS (15 PER PAGE)
# ============================================================
async def get_channels_page(client: Client, page: int = 1):
    raw_chats = await db.get_all_chats()
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
        username = chat.get("username")

        if username:
            link = f"https://t.me/{username}"
        elif str(chat_id).startswith("-100"):
            clean_id = str(chat_id)[4:]
            link = f"https://t.me/c/{clean_id}/1"
        else:
            link = "Private"

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


@Client.on_message(filters.command("channels"))
async def list_all_channels_cmd(client: Client, message: Message):
    user_id = message.from_user.id if message.from_user else 0
    if str(user_id) not in [str(a) for a in info.ADMINS]:
        return await message.reply_text(
            "❌ This command is restricted to Bot Admins only."
        )

    text, reply_markup = await get_channels_page(client, page=1)
    await message.reply_text(
        text, reply_markup=reply_markup, disable_web_page_preview=True
    )


@Client.on_message(filters.command(["leavechannel", "leave"]))
async def leave_channel_cmd(client: Client, message: Message):
    user_id = message.from_user.id if message.from_user else 0
    if str(user_id) not in [str(a) for a in info.ADMINS]:
        return await message.reply_text(
            "❌ This command is restricted to Bot Admins only."
        )

    if len(message.command) < 2:
        return await message.reply_text(
            "⚙️ <b>Usage:</b> `/leavechannel <channel_id>`\n\n<b>Example:</b> `/leavechannel -1001234567890`"
        )

    target_chat_id = message.command[1].strip()
    try:
        chat_id_int = int(target_chat_id)
    except ValueError:
        return await message.reply_text(
            "❌ Invalid Channel ID format. Must be an integer like `-100...`"
        )

    try:
        chat = await client.get_chat(chat_id_int)
        chat_title = chat.title or "Unknown"
        await client.leave_chat(chat_id_int)
        if hasattr(db, "delete_chat"):
            await db.delete_chat(chat_id_int)
        await message.reply_text(
            f"✅ <b>Successfully left:</b>\n\n<b>Name:</b> {chat_title}\n<b>ID:</b> <code>{chat_id_int}</code>"
        )
    except Exception as e:
        await message.reply_text(
            f"❌ <b>Failed to leave channel:</b>\n<code>{e}</code>"
        )


# ============================================================
# 📄 PAGINATION HANDLER
# ============================================================
@Client.on_callback_query(filters.regex(r"^next"))
async def next_page(bot, query):
    if getattr(info, "REPAIR_MODE", False):
        if str(query.from_user.id) not in [str(a) for a in info.ADMINS]:
            return await query.answer("🛠️ Bot is under maintenance!", show_alert=True)

    try:
        ident, req, key, offset = query.data.split("_")
    except ValueError:
        return await query.answer("Invalid button data!", show_alert=True)

    try:
        if int(req) not in [query.from_user.id, 0]:
            return await query.answer("That's not for you!", show_alert=True)
    except QueryIdInvalid:
        pass

    try:
        offset = int(offset)
    except ValueError:
        offset = 0

    search = BUTTONS.get(key)
    if not search:
        try:
            await query.answer("Expired button. Please request again.", show_alert=True)
        except QueryIdInvalid:
            pass
        return

    files, n_offset, total = await get_search_results(
        search, max_results=10, offset=offset, filter=True
    )
    try:
        n_offset = int(n_offset)
    except (ValueError, TypeError):
        n_offset = 0

    if not files:
        return
    files.sort(
        key=lambda x: (
            x.get("file_size", 0) if isinstance(x, dict) else getattr(x, "file_size", 0)
        )
    )

    settings = await get_settings(query.message.chat.id)
    btn = []
    bot_username = temp.U_NAME or "my_bot"
    pre = "filep" if settings.get("file_secure") else "file"

    for file in files:
        file_id = str(
            file.get("file_id", "")
            if isinstance(file, dict)
            else getattr(file, "file_id", "")
        )
        raw_name = str(
            file.get("file_name", "Unknown")
            if isinstance(file, dict)
            else getattr(file, "file_name", "Unknown")
        )
        file_size = int(
            file.get("file_size", 0)
            if isinstance(file, dict)
            else getattr(file, "file_size", 0)
        )
        display_name = clean_filename(raw_name)

        if settings.get("button", False):
            btn.append(
                [
                    InlineKeyboardButton(
                        text=f"{get_size(file_size)} | {display_name}",
                        url=f"https://t.me/{bot_username}?start={pre}_{file_id}",
                    )
                ]
            )
        else:
            btn.append(
                [
                    InlineKeyboardButton(
                        text=f"{display_name}",
                        url=f"https://t.me/{bot_username}?start={pre}_{file_id}",
                    ),
                    InlineKeyboardButton(
                        text=f"{get_size(file_size)}",
                        url=f"https://t.me/{bot_username}?start={pre}_{file_id}",
                    ),
                ]
            )

    if 0 < offset <= 10:
        off_set = 0
    elif offset == 0:
        off_set = None
    else:
        off_set = offset - 10

    if n_offset == 0:
        btn.append(
            [
                InlineKeyboardButton(
                    "BACK", callback_data=f"next_{req}_{key}_{off_set}"
                ),
                InlineKeyboardButton(
                    f"Pages {math.ceil(int(offset) / 10) + 1} / {math.ceil(total / 10)}",
                    callback_data="pages",
                ),
            ]
        )
    elif off_set is None:
        btn.insert(
            0,
            [
                InlineKeyboardButton(
                    text="• Bᴀᴄᴋ Uᴘ Cʜᴀɴɴᴇʟ •",
                    url="https://t.me/KR_Picture",
                    icon_custom_emoji_id=5258503720928288433,
                    style=ButtonStyle.SUCCESS,
                )
            ],
        )
        btn.append(
            [
                InlineKeyboardButton(
                    f"{math.ceil(int(offset) / 10) + 1} / {math.ceil(total / 10)}",
                    callback_data="pages",
                ),
                InlineKeyboardButton(
                    "NEXT", callback_data=f"next_{req}_{key}_{n_offset}"
                ),
            ]
        )
    else:
        btn.append(
            [
                InlineKeyboardButton(
                    "BACK", callback_data=f"next_{req}_{key}_{off_set}"
                ),
                InlineKeyboardButton(
                    f"{math.ceil(int(offset) / 10) + 1} / {math.ceil(total / 10)}",
                    callback_data="pages",
                ),
                InlineKeyboardButton(
                    "NEXT", callback_data=f"next_{req}_{key}_{n_offset}"
                ),
            ]
        )

    try:
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(btn))
    except (MessageNotModified, MessageIdInvalid, ButtonUrlInvalid):
        pass
    except FloodWait as e:
        await asyncio.sleep(e.value)
        try:
            await query.edit_message_reply_markup(
                reply_markup=InlineKeyboardMarkup(btn)
            )
        except Exception:
            pass
    try:
        await query.answer()
    except QueryIdInvalid:
        pass


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
            text, reply_markup = await get_channels_page(client, page=page_num)
            try:
                await query.message.edit_text(
                    text=text, reply_markup=reply_markup, disable_web_page_preview=True
                )
            except MessageNotModified:
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
            if groupids is None:
                try:
                    await query.message.edit_text("There are no active connections!!")
                except (MessageIdInvalid, MessageNotModified):
                    pass
                return
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
            bot_username = temp.U_NAME or "my_bot"

            if CUSTOM_FILE_CAPTION:
                try:
                    f_caption = CUSTOM_FILE_CAPTION.format(
                        file_name="" if title is None else title,
                        file_size="" if size is None else size,
                        file_caption="" if f_caption is None else f_caption,
                    )
                except Exception as e:
                    logger.exception(e)

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
            except UserIsBlocked:
                await query.answer("Unblock the bot mahn !", show_alert=True)
            except PeerIdInvalid:
                await query.answer(
                    url=f"https://t.me/{bot_username}?start={ident}_{file_id}"
                )
            except FloodWait as e:
                await asyncio.sleep(e.value)
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
                logger.exception(f"File send error: {e}")
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
                    logger.exception(e)
            if not f_caption:
                f_caption = f"{title}"

            await query.answer()
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

        elif query.data == "help":
            await query.answer()
            buttons = [
                [
                    InlineKeyboardButton("🚫 Bans", callback_data="helps_bans"),
                    InlineKeyboardButton(
                        "💬 Custom Messages", callback_data="helps_custommessages"
                    ),
                ],
                [
                    InlineKeyboardButton(
                        "📝 Custom Captions", callback_data="helps_customcaption"
                    ),
                    InlineKeyboardButton("🗑️ Delete", callback_data="helps_delete"),
                ],
                [
                    InlineKeyboardButton(
                        "📱 Force Sub", callback_data="helps_forcesub"
                    ),
                    InlineKeyboardButton("📝 Filters", callback_data="helps_filters"),
                ],
                [
                    InlineKeyboardButton("📚 Index", callback_data="helps_index"),
                    InlineKeyboardButton(
                        "📢 Promotions", callback_data="helps_promotions"
                    ),
                ],
                [
                    InlineKeyboardButton("⚙️ Settings", callback_data="helps_settings"),
                    InlineKeyboardButton(
                        "📊 Utilities", callback_data="helps_utilities"
                    ),
                ],
                [
                    InlineKeyboardButton(
                        "🌐 Connections", callback_data="helps_connections"
                    ),
                    InlineKeyboardButton(
                        "👥 Force Add", callback_data="helps_forceadd"
                    ),
                ],
                [
                    InlineKeyboardButton(
                        "📝 Post Handle", callback_data="helps_posthand"
                    ),
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
                "helps_bans": ("BANS_TXT", "🚫 Bans Help"),
                "helps_custommessages": (
                    "CUSTOMMESSAGES_TXT",
                    "💬 Custom Messages Help",
                ),
                "helps_customcaption": ("CUSTOMCAPTION_TXT", "📝 Custom Caption Help"),
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
            except Exception as err:
                logger.error(f"HTML error rendering {query.data}: {err}")
                clean_text = re.sub(
                    r"</?(b|i|u|s|code|pre|a|blockquote)[^>]*>", "", text
                )
                await query.message.edit_text(
                    text=clean_text,
                    reply_markup=InlineKeyboardMarkup(buttons),
                    parse_mode=None,
                )

        elif query.data in ["stats", "rfrsh"]:
            await query.answer()
            buttons = [
                [
                    InlineKeyboardButton("⇌ Bᴀᴄᴋ ⇌", callback_data="about"),
                    InlineKeyboardButton("♻️", callback_data="rfrsh"),
                ]
            ]
            total = await Media.count_documents()
            users = await db.total_users_count()
            chats = await db.total_chat_count()
            monsize = await db.get_db_size()
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
