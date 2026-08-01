import ast
import asyncio
import logging
import math
import re

from pyrogram import Client, enums, filters
from pyrogram.errors import FloodWait, Forbidden
from pyrogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

import info
from database.filters_mdb import find_filter, get_filters
from database.ia_filterdb import get_search_results
from database.plugin_dbs import plugin_db
from utils import get_settings, get_size, search_gagala, temp

logger = logging.getLogger(__name__)
BUTTONS, SPELL_CHECK = {}, {}


async def delete_message_after_delay(message, delay: int):
    await asyncio.sleep(delay)
    try:
        await message.delete()
    except Exception:
        pass


@Client.on_message(filters.group & filters.text & filters.incoming)
async def give_filter(client, message):
    if getattr(info, "REPAIR_MODE", False) and (
        not message.from_user or message.from_user.id not in info.ADMINS
    ):
        return
    if message.from_user and await ban_db.is_banned(message.from_user.id):
        return
    if not await manual_filters(client, message):
        await auto_filter(client, message)


async def auto_filter(client, msg, spoll=False):
    settings = await get_settings(msg.chat.id if not spoll else msg.message.chat.id)
    message = msg if not spoll else msg.message.reply_to_message

    if not spoll:
        if (
            not message.text
            or message.text.startswith("/")
            or re.match(r"^[!,\.]", message.text)
            or not (2 < len(message.text) < 100)
        ):
            return
        search = message.text
        files, offset, total_results = await get_search_results(
            search.lower(), max_results=10, offset=0, filter=True
        )
        if not files:
            if settings.get("spell_check"):
                return await advantage_spell_chok(msg)
            return
    else:
        search, files, offset, total_results = spoll

    if not files:
        return
    files.sort(key=lambda x: getattr(x, "file_size", 0))

    pre = "filep" if settings.get("file_secure") else "file"
    btn = []

    for file in files:
        if settings.get("button"):
            btn.append(
                [
                    InlineKeyboardButton(
                        text=f"{get_size(file.file_size)} | {file.file_name}",
                        url=f"https://t.me/{temp.U_NAME}?start={pre}_{file.file_id}",
                    )
                ]
            )
        else:
            btn.append(
                [
                    InlineKeyboardButton(
                        text=file.file_name,
                        url=f"https://t.me/{temp.U_NAME}?start={pre}_{file.file_id}",
                    ),
                    InlineKeyboardButton(
                        text=get_size(file.file_size),
                        url=f"https://t.me/{temp.U_NAME}?start={pre}_{file.file_id}",
                    ),
                ]
            )

    btn.insert(
        0, [InlineKeyboardButton("• Bᴀᴄᴋ Uᴘ Cʜᴀɴɴᴇʟ •", url="https://t.me/KR_PICTURE")]
    )

    if offset:
        key = f"{message.chat.id}-{message.id}"
        BUTTONS[key] = search
        req = message.from_user.id if message.from_user else 0
        btn.append(
            [
                InlineKeyboardButton(
                    f"1/{math.ceil(int(total_results) / 10)}", callback_data="pages"
                ),
                InlineKeyboardButton(
                    "NEXT", callback_data=f"next_{req}_{key}_{offset}"
                ),
            ]
        )
    else:
        btn.append([InlineKeyboardButton("1/1", callback_data="pages")])

    cap = f"Hey {message.from_user.mention if message.from_user else 'User'} 👋🏻\n\n➤ Title : {search}\n➤ Your Files Ready Now 👇"

    try:
        m = await message.reply_text(cap, reply_markup=InlineKeyboardMarkup(btn))
        if spoll:
            await msg.message.delete()
        if getattr(info, "BUTTON_AUTO_DELETE", 1800) > 0:
            asyncio.create_task(delete_message_after_delay(m, info.BUTTON_AUTO_DELETE))
    except Exception as e:
        logger.error(f"Auto-Filter Error: {e}")


async def advantage_spell_chok(msg):
    query = (
        re.sub(
            r"\b(pls|send|movie|latest|new|full)\b", "", msg.text, flags=re.IGNORECASE
        ).strip()
        + " movie"
    )
    gs_parsed = await search_gagala(query)

    if not gs_parsed:
        return await send_not_found(msg)

    movielist = list(
        dict.fromkeys(
            [
                re.sub(r"(\-|\(|\)|_)", "", i, flags=re.IGNORECASE).strip()
                for i in gs_parsed[:3]
            ]
        )
    )
    if not movielist:
        return await send_not_found(msg)

    SPELL_CHECK[msg.id] = movielist
    user = msg.from_user.id if msg.from_user else 0
    btn = [
        [InlineKeyboardButton(text=m, callback_data=f"spolling#{user}#{idx}")]
        for idx, m in enumerate(movielist)
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
            "<b>Did you mean any one of these?</b>",
            reply_markup=InlineKeyboardMarkup(btn),
        )
    except Forbidden:
        pass


async def send_not_found(msg):
    pic = getattr(
        info,
        "NOT_FOUND_IMG",
        "https://telegra.ph/file/c4f0458d30f61993aad45-086b84e8363b3c582e.jpg",
    )
    text = getattr(info, "NOT_FOUND_MSG", "<b>🚫 File not found.</b>")
    try:
        m = await msg.reply_photo(photo=pic, caption=text)
        if getattr(info, "BUTTON_AUTO_DELETE", 1800) > 0:
            asyncio.create_task(delete_message_after_delay(m, info.BUTTON_AUTO_DELETE))
    except Exception:
        pass


async def manual_filters(client, message):
    name = message.text
    keywords = await get_filters(message.chat.id)
    for keyword in reversed(sorted(keywords, key=len)):
        if re.search(
            r"( |^|[^\w])" + re.escape(keyword) + r"( |$|[^\w])",
            name,
            flags=re.IGNORECASE,
        ):
            reply_text, btn, alert, fileid = await find_filter(message.chat.id, keyword)
            reply_markup = (
                InlineKeyboardMarkup(ast.literal_eval(btn))
                if btn and btn != "[]"
                else None
            )

            try:
                if fileid == "None":
                    m = await client.send_message(
                        message.chat.id,
                        reply_text,
                        reply_markup=reply_markup,
                        reply_to_message_id=message.id,
                    )
                else:
                    m = await client.send_cached_media(
                        message.chat.id,
                        fileid,
                        caption=reply_text or "",
                        reply_markup=reply_markup,
                        reply_to_message_id=message.id,
                    )

                if getattr(info, "BUTTON_AUTO_DELETE", 1800) > 0:
                    asyncio.create_task(
                        delete_message_after_delay(m, info.BUTTON_AUTO_DELETE)
                    )
            except Exception as e:
                logger.error(e)
            return True
    return False


@Client.on_callback_query(filters.regex(r"^next"))
async def next_page(bot, query):
    ident, req, key, offset = query.data.split("_")
    if int(req) not in [query.from_user.id, 0]:
        return await query.answer("That's not for you!", show_alert=True)

    search = BUTTONS.get(key)
    if not search:
        return await query.answer("Expired button.", show_alert=True)

    files, n_offset, total = await get_search_results(
        search, max_results=10, offset=int(offset), filter=True
    )
    if not files:
        return

    btn = []
    for file in files:
        btn.append(
            [
                InlineKeyboardButton(
                    text=file.file_name,
                    url=f"https://t.me/{temp.U_NAME}?start=file_{file.file_id}",
                )
            ]
        )

    off_set = 0 if 0 < int(offset) <= 10 else int(offset) - 10
    nav = []
    if off_set > 0:
        nav.append(
            InlineKeyboardButton("BACK", callback_data=f"next_{req}_{key}_{off_set}")
        )
    nav.append(
        InlineKeyboardButton(
            f"{math.ceil(int(offset) / 10) + 1}/{math.ceil(total / 10)}",
            callback_data="pages",
        )
    )
    if n_offset:
        nav.append(
            InlineKeyboardButton("NEXT", callback_data=f"next_{req}_{key}_{n_offset}")
        )

    btn.append(nav)
    try:
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(btn))
    except Exception:
        pass
