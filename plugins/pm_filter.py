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
    RandomIdDuplicate,
    UserIsBlocked,
)
from pyrogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

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
NOT_FOUND_TEXT = getattr(
    info,
    "NOT_FOUND_MSG",
    (
        "<b>🚫 File not found. Please note👇\n\n"
        "✅ Use correct spelling as given in Google.\n"
        "✅ DO NOT ask for files which are not released in OTT.\n"
        "✅ Request movies in this format - (Moviename) (Year of release)\n"
        "Eg. Jai Ganesh 2024 </b>"
    ),
)

MESSAGE_EMOJI_PLANE = '<tg-emoji emoji-id="5875465628285931233">✈️</tg-emoji> Telegram'
MESSAGE_EMOJI_LINK = '<tg-emoji emoji-id="5877465816030515018">🔗</tg-emoji> Link'


# ============================================================
# 🗑️ ADVANCED AUTO-DELETE & PRIVACY NOTIFICATION
# ============================================================
async def auto_delete_and_notify(client, bot_message, delay: int, user_message=None):
    """Deletes bot reply & user request, then sends an 11-minute self-destructing notice."""
    if not bot_message:
        return
    await asyncio.sleep(delay)
    try:
        is_group = bot_message.chat.type in [
            enums.ChatType.GROUP,
            enums.ChatType.SUPERGROUP,
        ]
        chat_id = bot_message.chat.id

        # 1. Delete bot's message
        try:
            await bot_message.delete()
        except Exception:
            pass

        # 2. Delete user's message
        if user_message:
            mention = (
                user_message.from_user.mention if user_message.from_user else "User"
            )
            try:
                await user_message.delete()
            except Exception:
                pass

            # 3. Send notification in group
            if is_group:
                default_text = "<b>Hey {mention} ⚓\n\n➡️ Your Request Has Been Deleted To Safeguard Your Privacy!\n\n➡️ Thank You For Using @KR_PICTURE</b>"

                # Fetch custom text from Script.py if available, else fallback to default
                text = getattr(script, "DELETE_TXT", default_text)

                # Safely use the client object to send the message
                notification = await client.send_message(
                    chat_id, text.format(mention=mention)
                )

                # 4. Delete notification after 11 minutes (660 seconds)
                await asyncio.sleep(660)
                try:
                    await notification.delete()
                except Exception:
                    pass
    except Exception as e:
        logger.error(f"Auto-delete notification error: {e}")


async def expire_cache_entry(cache: dict, key, delay: int):
    """Remove `key` from an in-memory cache (BUTTONS / SPELL_CHECK) after `delay`
    seconds. Without this, both dicts grow forever for as long as the bot runs."""
    await asyncio.sleep(delay)
    cache.pop(key, None)


# ============================================================
# 🔎 SEARCH LOGIC HELPERS
# ============================================================
async def advantage_spell_chok(client, msg):
    if not msg or not getattr(msg, "text", None):
        return

    query = (
        re.sub(
            r"\b(pl(i|e)*?(s|z+|ease|se|ese|(e+)s(e)?)|((send|snd|giv(e)?|gib)(\sme)?)|movie(s)?|new|latest|br((o|u)h?)*|^h(e|a)?(l)*(o)*|mal(ayalam)?|t(h)?amil|file|that|find|und(o)*|kit(t(i|y)?)?o(w)?|thar(u)?(o)*w?|kittum(o)*|aya(k)*(um(o)*)?|full\smovie|any(one)|with\ssubtitle(s)?)",
            "",
            msg.text,
            flags=re.IGNORECASE,
        ).strip()
        + " movie"
    )

    g_s = await search_gagala(query) or []
    g_s += await search_gagala(msg.text) or []
    gs_parsed = []

    pic_to_use = getattr(info, "NOT_FOUND_IMG", None) or FILE_NOT_FOUND_PIC
    text_to_use = getattr(info, "NOT_FOUND_MSG", None) or NOT_FOUND_TEXT

    if not g_s:
        try:
            k_msg = await msg.reply_photo(photo=pic_to_use, caption=text_to_use)
        except Exception:
            try:
                k_msg = await msg.reply_text(text=text_to_use)
            except Exception:
                k_msg = None

        if k_msg:
            delete_timer = getattr(info, "BUTTON_AUTO_DELETE", 1800)
            if delete_timer > 0:
                asyncio.create_task(
                    auto_delete_and_notify(client, k_msg, delete_timer, msg)
                )
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
        (re.sub(r"(\-|\(|\)|_)", "", i, flags=re.IGNORECASE)).strip() for i in gs_parsed
    ]
    movielist = list(dict.fromkeys(movielist))

    if not movielist:
        try:
            k_msg = await msg.reply_photo(photo=pic_to_use, caption=text_to_use)
        except Exception:
            try:
                k_msg = await msg.reply_text(text=text_to_use)
            except Exception:
                k_msg = None

        if k_msg:
            delete_timer = getattr(info, "BUTTON_AUTO_DELETE", 1800)
            if delete_timer > 0:
                asyncio.create_task(
                    auto_delete_and_notify(client, k_msg, delete_timer, msg)
                )
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
            "<b>I couldn't find anything related to that. Did you mean any one of these?</b>",
            reply_markup=InlineKeyboardMarkup(btn),
        )
    except Forbidden:
        pass


async def manual_filters(client, message, text=False):
    group_id = message.chat.id
    name = text or message.text
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

            button_layout = None
            if btn and btn != "[]":
                try:
                    button_layout = ast.literal_eval(btn)
                except Exception:
                    pass

            reply_markup = (
                InlineKeyboardMarkup(button_layout) if button_layout else None
            )

            try:
                sent_msg = None
                fileid_str = str(fileid).strip()

                if not fileid or fileid_str in ["None", "[]", "", "False"]:
                    if not reply_markup:
                        sent_msg = await client.send_message(
                            group_id,
                            reply_text,
                            disable_web_page_preview=True,
                            reply_to_message_id=reply_id,
                        )
                    else:
                        sent_msg = await client.send_message(
                            group_id,
                            reply_text,
                            disable_web_page_preview=True,
                            reply_markup=reply_markup,
                            reply_to_message_id=reply_id,
                        )
                else:
                    if not reply_markup:
                        sent_msg = await client.send_cached_media(
                            group_id,
                            fileid,
                            caption=reply_text or "",
                            reply_to_message_id=reply_id,
                        )
                    else:
                        sent_msg = await message.reply_cached_media(
                            fileid,
                            caption=reply_text or "",
                            reply_markup=reply_markup,
                            reply_to_message_id=reply_id,
                        )

                if sent_msg:
                    delete_timer = getattr(info, "BUTTON_AUTO_DELETE", 1800)
                    if delete_timer > 0:
                        asyncio.create_task(
                            auto_delete_and_notify(
                                client, sent_msg, delete_timer, message
                            )
                        )

            except FloodWait as e:
                logger.warning(
                    f"Telegram FloodWait in manual_filters! Sleeping for {e.value} seconds..."
                )
                await asyncio.sleep(e.value)
                try:
                    if not fileid or fileid_str in ["None", "[]", "", "False"]:
                        sent_msg = await client.send_message(
                            group_id,
                            reply_text,
                            disable_web_page_preview=True,
                            reply_markup=reply_markup,
                            reply_to_message_id=reply_id,
                        )
                    else:
                        sent_msg = await client.send_cached_media(
                            group_id,
                            fileid,
                            caption=reply_text or "",
                            reply_markup=reply_markup,
                            reply_to_message_id=reply_id,
                        )
                    if sent_msg:
                        delete_timer = getattr(info, "BUTTON_AUTO_DELETE", 1800)
                        if delete_timer > 0:
                            asyncio.create_task(
                                auto_delete_and_notify(
                                    client, sent_msg, delete_timer, message
                                )
                            )
                except Exception as e2:
                    logger.exception(f"manual_filter retry error: {e2}")
            except Forbidden as e:
                if "CHAT_SEND_PHOTOS_FORBIDDEN" in str(
                    e
                ) or "CHAT_SEND_MEDIA_FORBIDDEN" in str(e):
                    try:
                        fallback_text = (
                            f"{reply_text}\n\n*(Media blocked by chat permissions)*"
                            if reply_text
                            else "*(Media blocked by chat permissions)*"
                        )
                        sent_msg = await client.send_message(
                            group_id,
                            text=fallback_text,
                            reply_to_message_id=reply_id,
                            reply_markup=reply_markup,
                        )
                        if sent_msg:
                            delete_timer = getattr(info, "BUTTON_AUTO_DELETE", 1800)
                            if delete_timer > 0:
                                asyncio.create_task(
                                    auto_delete_and_notify(
                                        client, sent_msg, delete_timer, message
                                    )
                                )
                    except Exception:
                        pass
            except Exception as e:
                logger.exception(e)
            return True
    return False


async def auto_filter(client, msg, spoll=False):
    if not spoll:
        message = msg
        settings = await get_settings(message.chat.id)

        if not message.text:
            return

        if message.text.startswith(("/", "!", "#", ".", ",", "?", "@")):
            return

        if not (2 < len(message.text) < 100):
            return

        search = message.text
        files, offset, total_results = await get_search_results(
            search.lower(), max_results=10, offset=0, filter=True
        )

        if not files:
            if settings.get("spell_check"):
                return await advantage_spell_chok(client, msg)
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
        file_name = str(
            file.get("file_name", "Unknown")
            if isinstance(file, dict)
            else getattr(file, "file_name", "Unknown")
        )
        file_size = int(
            file.get("file_size", 0)
            if isinstance(file, dict)
            else getattr(file, "file_size", 0)
        )

        if settings.get("button", False):
            btn.append(
                [
                    InlineKeyboardButton(
                        text=f"{get_size(file_size)} | {file_name}",
                        url=f"https://t.me/{bot_username}?start={pre}_{file_id}",
                    )
                ]
            )
        else:
            btn.append(
                [
                    InlineKeyboardButton(
                        text=file_name,
                        url=f"https://t.me/{bot_username}?start={pre}_{file_id}",
                    ),
                    InlineKeyboardButton(
                        text=get_size(file_size),
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
    cap = f"Hey {mention} 👋🏻\n\n➤ Title : {search}\n➤ Your Files Ready Now 👇"

    try:
        m = await message.reply_text(cap, reply_markup=InlineKeyboardMarkup(btn))
    except FloodWait as e:
        logger.warning(
            f"Telegram FloodWait triggered! Sleeping for {e.value} seconds..."
        )
        await asyncio.sleep(e.value)
        try:
            m = await message.reply_text(cap, reply_markup=InlineKeyboardMarkup(btn))
        except Exception as e2:
            logger.exception(f"auto_filter retry error: {e2}")
            return
    except ButtonUrlInvalid:
        logger.error("ButtonUrlInvalid during auto_filter send.")
        return
    except Forbidden:
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
        asyncio.create_task(auto_delete_and_notify(client, m, delete_timer, message))


# ============================================================
# 🔍 MAIN ENTRY POINT
# ============================================================
@Client.on_message((filters.group) & filters.text & filters.incoming)
async def give_filter(client, message):
    if getattr(info, "REPAIR_MODE", False):
        if not message.from_user or (
            str(message.from_user.id) not in [str(a) for a in info.ADMINS]
        ):
            return await message.reply_text(
                "🛠️ **Bot is currently under maintenance!**\n\n"
                "We are performing some upgrades/fixes. Please try again later."
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
# 📄 PAGINATION HANDLER
# ============================================================
@Client.on_callback_query(filters.regex(r"^next"))
async def next_page(bot, query):
    if getattr(info, "REPAIR_MODE", False):
        if str(query.from_user.id) not in [str(a) for a in info.ADMINS]:
            return await query.answer(
                "🛠️ Bot is currently under maintenance! Please try again later.",
                show_alert=True,
            )

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
            await query.answer(
                "You are using an old button that has expired. Please send the request again.",
                show_alert=True,
            )
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

    if not temp.U_NAME:
        try:
            bot_me = await bot.get_me()
            temp.U_NAME = bot_me.username
        except Exception:
            pass
    bot_username = temp.U_NAME or "my_bot"

    pre = "filep" if settings.get("file_secure") else "file"

    for file in files:
        file_id = str(
            file.get("file_id", "")
            if isinstance(file, dict)
            else getattr(file, "file_id", "")
        )
        file_name = str(
            file.get("file_name", "Unknown")
            if isinstance(file, dict)
            else getattr(file, "file_name", "Unknown")
        )
        file_size = int(
            file.get("file_size", 0)
            if isinstance(file, dict)
            else getattr(file, "file_size", 0)
        )

        if settings.get("button", False):
            btn.append(
                [
                    InlineKeyboardButton(
                        text=f"{get_size(file_size)} | {file_name}",
                        url=f"https://t.me/{bot_username}?start={pre}_{file_id}",
                    )
                ]
            )
        else:
            btn.append(
                [
                    InlineKeyboardButton(
                        text=f"{file_name}",
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


# ============================================================
# ✍️ SPELL CHECK CALLBACK HANDLER
# ============================================================
@Client.on_callback_query(filters.regex(r"^spolling"))
async def advantage_spoll_choker(bot, query):
    if getattr(info, "REPAIR_MODE", False):
        if str(query.from_user.id) not in [str(a) for a in info.ADMINS]:
            return await query.answer(
                "🛠️ Bot is currently under maintenance! Please try again later.",
                show_alert=True,
            )

    try:
        _, user, movie_ = query.data.split("#")
    except ValueError:
        return await query.answer("Invalid button data!", show_alert=True)

    movie = None
    try:
        if int(user) != 0 and query.from_user.id != int(user):
            return await query.answer("That's not for you!", show_alert=True)

        if movie_ == "close_spellcheck":
            return await query.message.delete()

        reply_msg = query.message.reply_to_message
        if not reply_msg:
            return await query.answer(
                "The original message was deleted!", show_alert=True
            )

        movies = SPELL_CHECK.get(reply_msg.id)
        if not movies:
            return await query.answer("Expired spell check button.", show_alert=True)

        movie = movies[(int(movie_))]
        await query.answer("Checking for Movie in database...")
    except QueryIdInvalid:
        pass
    except Exception as e:
        logger.error(f"Spolling error: {e}")
        return

    if movie is None:
        return

    k = await manual_filters(bot, query.message, text=movie)
    if not k:
        files, offset, total_results = await get_search_results(
            movie, max_results=10, offset=0, filter=True
        )
        if files:
            k = (movie, files, offset, total_results)
            await auto_filter(bot, query, k)
        else:
            try:
                await query.message.delete()
            except MessageIdInvalid:
                pass

            pic_to_use = getattr(info, "NOT_FOUND_IMG", None) or FILE_NOT_FOUND_PIC
            text_to_use = getattr(info, "NOT_FOUND_MSG", None) or NOT_FOUND_TEXT

            k_msg = None
            try:
                k_msg = await bot.send_photo(
                    chat_id=query.message.chat.id, photo=pic_to_use, caption=text_to_use
                )
            except Exception:
                try:
                    k_msg = await bot.send_message(
                        chat_id=query.message.chat.id, text=f"{text_to_use}"
                    )
                except Exception:
                    pass

            if k_msg:
                delete_timer = getattr(info, "BUTTON_AUTO_DELETE", 1800)
                if delete_timer > 0:
                    asyncio.create_task(
                        auto_delete_and_notify(
                            bot, k_msg, delete_timer, query.message.reply_to_message
                        )
                    )


# ============================================================
# 🎛 MAIN CALLBACK HANDLER (MENU / BUTTONS)
# ============================================================
@Client.on_callback_query(
    filters.regex(
        r"^(close_data|delallconfirm|delallcancel|groupcb.*|connectcb.*|disconnect.*|deletecb.*|backcb|alertmessage.*|file.*|checksub.*|pages|start|help|about|helps_bans|helps_custommessages|helps_customcaption|helps_delete|helps_forcesub|helps_filters|helps_index|helps_promotions|helps_settings|helps_utilities|helps_connections|helps_forceadd|helps_backup|stats|rfrsh)$"
    )
)
async def cb_handler(client: Client, query: CallbackQuery):
    if getattr(info, "REPAIR_MODE", False):
        if (
            str(query.from_user.id) not in [str(a) for a in info.ADMINS]
            and query.data != "close_data"
        ):
            return await query.answer(
                "🛠️ Bot is currently under maintenance! Please try again later.",
                show_alert=True,
            )

    try:
        if query.data == "close_data":
            await query.message.delete()

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
                            "I'm not connected to any groups!\nCheck /connections or connect to any groups",
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
                    "You need to be Group Owner or an Auth User to do that!",
                    show_alert=True,
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
                    await query.message.edit_text(
                        "There are no active connections!! Connect to some groups first."
                    )
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
                await query.answer("Couldn't load that alert.", show_alert=True)

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
            if not temp.U_NAME:
                try:
                    bot_me = await client.get_me()
                    temp.U_NAME = bot_me.username
                except Exception:
                    pass
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
                logger.warning(f"FloodWait {e.value}s sending file to PM.")
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
                except Exception as e2:
                    logger.exception(f"Retry after FloodWait failed: {e2}")
            except QueryIdInvalid:
                pass
            except Exception as e:
                logger.exception(f"Unexpected error sending file to PM: {e}")
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
                    "<b>📢 Please Note\n\n"
                    "✅ The above file will be autodeleted in 30mins to avoid copyright issues.\n\n"
                    "✅ Please forward this file to your saved messages and start downloading from there.\n\n"
                    "Tᴇᴀᴍ: @KR_Picture</b>"
                ),
            )

            async def delete_and_notify():
                delete_timer = getattr(info, "FILE_AUTO_DELETE", 1800)
                await asyncio.sleep(delete_timer)
                try:
                    await m.delete()
                    await k.edit_text(
                        f"<b>Hey <i>{query.from_user.first_name}</i>\n\n"
                        f"Your Request Has Been Deleted 👍 \n(Due To Avoid Copyrights Issue😌)\n\n"
                        f"IF YOU WANT THAT FILE, REQUEST AGAIN ❤️ In Our Group</b>"
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
                        text="🔗 Nᴇᴡ Rᴇʟᴇᴀꜱᴇꜱ & Oᴛᴛ Uᴘᴅᴀᴛᴇꜱ",
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
                [InlineKeyboardButton("💾 Backup", callback_data="helps_backup")],
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
                # Fallback to prevent silent failing if string formatting has issues
                try:
                    safe_text = str(script.HELP_TXT).replace(
                        "{mention}", query.from_user.first_name
                    )
                    await query.message.edit_text(
                        text=safe_text,
                        reply_markup=InlineKeyboardMarkup(buttons),
                    )
                except (MessageNotModified, Exception):
                    pass

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
                "helps_bans": (
                    "BANS_TXT",
                    "🚫 Bans Help\nManage bans via /ban and /unban.",
                ),
                "helps_custommessages": (
                    "CUSTOMMESSAGES_TXT",
                    "💬 Custom Messages Help\nUse /infomsg, /delmsg, etc. to set custom text.",
                ),
                "helps_customcaption": (
                    "CUSTOMCAPTION_TXT",
                    "📝 Custom Caption Help\nUse /customcaption to set a custom caption for files.",
                ),
                "helps_delete": (
                    "DELETE_TXT",
                    "🗑️ Delete Help\nUse /delete to remove a file.",
                ),
                "helps_forcesub": (
                    "FORCESUB_TXT",
                    "📱 Force Sub Help\nManage Force Sub settings using /setfsub, /rmfsub, etc.",
                ),
                "helps_filters": (
                    "FILTERS_TXT",
                    "📝 Filters Help\nUse /filter and /delfilter.",
                ),
                "helps_index": (
                    "INDEX_TXT",
                    "📚 Index Help\nUse /index to index channel files.",
                ),
                "helps_promotions": (
                    "PROMOTIONS_TXT",
                    "📢 Promotions Help\nManage promos using /addpromo.",
                ),
                "helps_settings": (
                    "SETTINGS_TXT",
                    "⚙️ Settings Help\nUse /settings to configure the bot.",
                ),
                "helps_utilities": (
                    "UTILITIES_TXT",
                    "📊 Utilities Help\nUse /stats, /id, and other tools.",
                ),
                "helps_connections": (
                    "CONNECTIONS_TXT",
                    "🌐 Connections Help\nManage your connections using /connect and /connections.",
                ),
                "helps_forceadd": (
                    "FORCEADD_TXT",
                    "👥 Force Add Help\nUse /setforceadd to enforce group invites.",
                ),
                "helps_backup": (
                    "BACKUP_TXT",
                    "💾 Backup Help\nUse /dbbackup to save the database.",
                ),
            }

            target_var, default_text = help_dict.get(
                query.data, ("HELP_TXT", "Help information unavailable.")
            )
            text = getattr(script, target_var, default_text)

            try:
                await query.message.edit_text(
                    text=text,
                    reply_markup=InlineKeyboardMarkup(buttons),
                    parse_mode=enums.ParseMode.HTML,
                )
            except Exception:
                clean_text = re.sub(
                    r"</?(b|i|u|s|code|pre|a|blockquote)[^>]*>", "", text
                )
                await query.message.edit_text(
                    text=clean_text,
                    reply_markup=InlineKeyboardMarkup(buttons),
                    parse_mode=enums.ParseMode.DISABLED,
                )

        elif query.data in ["stats", "rfrsh"]:
            if query.data == "rfrsh":
                try:
                    await query.answer("Fetching MongoDb DataBase")
                except QueryIdInvalid:
                    pass
            else:
                await query.answer()
            buttons = [
                [
                    InlineKeyboardButton(
                        "⇌ Bᴀᴄᴋ ⇌",
                        callback_data="help" if query.data == "rfrsh" else "about",
                    ),
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
