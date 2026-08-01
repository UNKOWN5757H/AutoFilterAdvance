import ast
import asyncio
import logging
import math
import re

from pyrogram import Client, enums, filters
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
NOT_FOUND_TEXT = getattr(info, "NOT_FOUND_MSG", "<b>🚫 File not found.</b>")
MESSAGE_EMOJI_PLANE = '<tg-emoji emoji-id="5875465628285931233">✈️</tg-emoji> Telegram'
MESSAGE_EMOJI_LINK = '<tg-emoji emoji-id="5877465816030515018">🔗</tg-emoji> Link'


async def delete_message_after_delay(message, delay: int):
    if not message:
        return
    await asyncio.sleep(delay)
    try:
        await message.delete()
    except Exception:
        pass


@Client.on_message((filters.group) & filters.text & filters.incoming)
async def give_filter(client, message):
    if getattr(info, "REPAIR_MODE", False) and (
        not message.from_user or message.from_user.id not in info.ADMINS
    ):
        return
    if message.from_user and await plugin_db.is_banned(message.from_user.id):
        return

    k = await manual_filters(client, message)
    if not k:
        await auto_filter(client, message)


@Client.on_callback_query(filters.regex(r"^next"))
async def next_page(bot, query):
    if getattr(info, "REPAIR_MODE", False) and query.from_user.id not in info.ADMINS:
        return
    ident, req, key, offset = query.data.split("_")

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
        return await query.answer("Expired button.", show_alert=True)

    files, n_offset, total = await get_search_results(
        search, max_results=10, offset=offset, filter=True
    )
    if not files:
        return
    files.sort(key=lambda x: getattr(x, "file_size", 0))

    settings = await get_settings(query.message.chat.id)
    btn = []

    for file in files:
        if settings.get("button", False):
            btn.append(
                [
                    InlineKeyboardButton(
                        text=f"{get_size(file.file_size)} | {file.file_name}",
                        url=f"https://t.me/{temp.U_NAME}?start=files_{file.file_id}",
                    )
                ]
            )
        else:
            btn.append(
                [
                    InlineKeyboardButton(
                        text=f"{file.file_name}",
                        url=f"https://t.me/{temp.U_NAME}?start=files_{file.file_id}",
                    ),
                    InlineKeyboardButton(
                        text=f"{get_size(file.file_size)}",
                        url=f"https://t.me/{temp.U_NAME}?start=files_{file.file_id}",
                    ),
                ]
            )

    off_set = 0 if 0 < offset <= 10 else (None if offset == 0 else offset - 10)

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
                    "•  Bᴀᴄᴋ Uᴘ Cʜᴀɴɴᴇʟ  •", url="https://t.me/KR_PICTURE"
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
        await query.answer()
    except Exception:
        pass


@Client.on_callback_query(filters.regex(r"^spolling"))
async def advantage_spoll_choker(bot, query):
    if getattr(info, "REPAIR_MODE", False) and query.from_user.id not in info.ADMINS:
        return

    _, user, movie_ = query.data.split("#")
    try:
        if int(user) != 0 and query.from_user.id != int(user):
            return await query.answer("That's not for you!", show_alert=True)
        if movie_ == "close_spellcheck":
            return await query.message.delete()

        movies = SPELL_CHECK.get(query.message.reply_to_message.id)
        if not movies:
            return await query.answer("Expired button.", show_alert=True)

        movie = movies[(int(movie_))]
        await query.answer("Checking for Movie in database...")
    except QueryIdInvalid:
        pass

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

            try:
                k_msg = await bot.send_photo(
                    chat_id=query.message.chat.id,
                    photo=FILE_NOT_FOUND_PIC,
                    caption=NOT_FOUND_TEXT,
                )
            except Forbidden as e:
                k_msg = (
                    await bot.send_message(
                        chat_id=query.message.chat.id,
                        text=f"{NOT_FOUND_TEXT}\n\n*(No photo attached due to permissions)*",
                    )
                    if "CHAT_SEND_PHOTOS_FORBIDDEN" in str(e)
                    else None
                )
            except Exception:
                k_msg = None

            if k_msg and getattr(info, "BUTTON_AUTO_DELETE", 1800) > 0:
                asyncio.create_task(
                    delete_message_after_delay(k_msg, info.BUTTON_AUTO_DELETE)
                )


# ============================================================
# 🎛 MAIN CALLBACK HANDLER (MENU / BUTTONS) RESTORED!
# ============================================================
@Client.on_callback_query(
    filters.regex(
        r"^(close_data|delallconfirm|delallcancel|groupcb.*|connectcb.*|disconnect.*|deletecb.*|backcb|alertmessage.*|file.*|checksub.*|pages|start|help|about|bans|custommessages|customcaption|delete|forcesub|filters|index|promotions|settings|utilities|connections|forceadd|backup|stats|rfrsh)$"
    )
)
async def cb_handler(client: Client, query: CallbackQuery):
    if (
        getattr(info, "REPAIR_MODE", False)
        and query.from_user.id not in info.ADMINS
        and query.data != "close_data"
    ):
        return

    try:
        if query.data == "close_data":
            await query.message.delete()

        elif query.data == "delallconfirm":
            userid = query.from_user.id
            chat_type = query.message.chat.type

            if chat_type == enums.ChatType.PRIVATE:
                grpid = await active_connection(str(userid))
                if grpid:
                    chat = await client.get_chat(grpid)
                    title = chat.title
                else:
                    return await query.answer(
                        "Not connected to any group!", show_alert=True
                    )
            elif chat_type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
                grpid = query.message.chat.id
                title = query.message.chat.title
            else:
                return await query.answer("Join: @KR_PICTURE")

            st = await client.get_chat_member(grpid, userid)
            if (st.status == enums.ChatMemberStatus.OWNER) or (str(userid) in ADMINS):
                await del_all(query.message, grpid, title)
            else:
                await query.answer("Group Owner or Admin required!", show_alert=True)

        elif query.data == "delallcancel":
            try:
                await query.message.reply_to_message.delete()
                await query.message.delete()
            except Exception:
                pass

        elif "groupcb" in query.data:
            await query.answer()
            group_id, act = query.data.split(":")[1], query.data.split(":")[2]
            hr = await client.get_chat(int(group_id))
            stat, cb = (
                ("CONNECT", "connectcb") if act == "" else ("DISCONNECT", "disconnect")
            )

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
            await query.message.edit_text(
                f"Group Name : **{hr.title}**\nGroup ID : `{group_id}`",
                reply_markup=keyboard,
                parse_mode=enums.ParseMode.MARKDOWN,
            )

        elif "connectcb" in query.data:
            await query.answer()
            group_id = query.data.split(":")[1]
            hr = await client.get_chat(int(group_id))
            if await make_active(str(query.from_user.id), str(group_id)):
                await query.message.edit_text(
                    f"Connected to **{hr.title}**", parse_mode=enums.ParseMode.MARKDOWN
                )

        elif "disconnect" in query.data:
            await query.answer()
            group_id = query.data.split(":")[1]
            hr = await client.get_chat(int(group_id))
            if await make_inactive(str(query.from_user.id)):
                await query.message.edit_text(
                    f"Disconnected from **{hr.title}**",
                    parse_mode=enums.ParseMode.MARKDOWN,
                )

        elif "deletecb" in query.data:
            await query.answer()
            if await delete_connection(
                str(query.from_user.id), str(query.data.split(":")[1])
            ):
                await query.message.edit_text("Successfully deleted connection")

        elif query.data == "backcb":
            await query.answer()
            groupids = await all_connections(str(query.from_user.id))
            if not groupids:
                return await query.message.edit_text(
                    "There are no active connections!! Connect to some groups first."
                )

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
                await query.message.edit_text(
                    "Your connected group details ;\n\n",
                    reply_markup=InlineKeyboardMarkup(buttons),
                )

        elif "alertmessage" in query.data:
            grp_id, i, keyword = (
                query.message.chat.id,
                query.data.split(":")[1],
                query.data.split(":")[2],
            )
            reply_text, btn, alerts, fileid = await find_filter(grp_id, keyword)
            if alerts is not None:
                alerts = ast.literal_eval(alerts)
                alert = alerts[int(i)].replace("\\n", "\n").replace("\\t", "\t")
                await query.answer(alert, show_alert=True)

        elif query.data.startswith("file"):
            ident, file_id = query.data.split("#")
            files_ = await get_file_details(file_id)
            if not files_:
                return await query.answer("No such file exist.")

            files = files_[0]
            f_caption = (
                CUSTOM_FILE_CAPTION.format(
                    file_name=files.file_name or "",
                    file_size=get_size(files.file_size) or "",
                    file_caption=files.caption or "",
                )
                if CUSTOM_FILE_CAPTION
                else files.file_name
            )

            try:
                settings = await get_settings(query.message.chat.id)
                if (AUTH_CHANNEL or REQ_CHANNEL) and not await is_subscribed(
                    client, query
                ):
                    return await query.answer(
                        url=f"https://t.me/{temp.U_NAME}?start={ident}_{file_id}"
                    )
                elif settings.get("botpm", False):
                    return await query.answer(
                        url=f"https://t.me/{temp.U_NAME}?start={ident}_{file_id}"
                    )
                else:
                    await client.send_cached_media(
                        chat_id=query.from_user.id,
                        file_id=file_id,
                        caption=f_caption,
                        protect_content=(ident == "filep"),
                    )
                    await query.answer(
                        "Check PM, I have sent files in pm", show_alert=True
                    )
            except UserIsBlocked:
                await query.answer("Unblock the bot mahn !", show_alert=True)
            except (PeerIdInvalid, Exception):
                await query.answer(
                    url=f"https://t.me/{temp.U_NAME}?start={ident}_{file_id}"
                )

        elif query.data.startswith("checksub"):
            if (AUTH_CHANNEL or REQ_CHANNEL) and not await is_subscribed(client, query):
                return await query.answer(
                    "I Like Your Smartness, But Don't Be Oversmart 😒", show_alert=True
                )

            ident, file_id = query.data.split("#")
            files_ = await get_file_details(file_id)
            if not files_:
                return await query.answer("No such file exist.")

            files = files_[0]
            f_caption = (
                CUSTOM_FILE_CAPTION.format(
                    file_name=files.file_name or "",
                    file_size=get_size(files.file_size) or "",
                    file_caption=files.caption or "",
                )
                if CUSTOM_FILE_CAPTION
                else files.file_name
            )

            await query.answer()
            m = await client.send_cached_media(
                chat_id=query.from_user.id,
                file_id=file_id,
                caption=f_caption,
                protect_content=(ident == "checksubp"),
            )
            k = await client.send_message(
                chat_id=query.from_user.id,
                text=f"<blockquote><b><u>❗️❗️❗️IMPORTANT❗️️❗️❗️</u></b>\n\n⚠️ File will be deleted in 30 Minutes\n\n📌 Save or forward it.</blockquote>",
            )

            async def delete_and_notify():
                await asyncio.sleep(getattr(info, "FILE_AUTO_DELETE", 1800))
                try:
                    await m.delete()
                    await k.edit_text(
                        f"<b>Hey <i>{query.from_user.first_name}</i>\n\nYour Request Has Been Deleted 👍 \nIF YOU WANT THAT FILE, REQUEST AGAIN ❤️</b>"
                    )
                except Exception:
                    pass

            if getattr(info, "FILE_AUTO_DELETE", 1800) > 0:
                asyncio.create_task(delete_and_notify())

        elif query.data == "pages":
            await query.answer()

        elif query.data == "start":
            await query.answer()
            buttons = [
                [
                    InlineKeyboardButton(
                        "✈️ Group 1", url="https://t.me/Sandalwood_Kannada_Group"
                    ),
                    InlineKeyboardButton(
                        "✈️ Group 2", url="http://t.me/Kannada_Filmy_Group"
                    ),
                    InlineKeyboardButton(
                        "✈️ Group 3", url="https://t.me/+GLsPkRgLGGszMzY1"
                    ),
                ],
            ]
            if query.from_user.id in ADMINS or str(query.from_user.id) in ADMINS:
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
            await query.message.edit_text(
                text=script.START_TXT.format(
                    mention=query.from_user.mention,
                    uname=temp.U_NAME,
                    bname=temp.B_NAME,
                    plane_emoji=MESSAGE_EMOJI_PLANE,
                    link_emoji=MESSAGE_EMOJI_LINK,
                ),
                reply_markup=InlineKeyboardMarkup(buttons),
                parse_mode=enums.ParseMode.HTML,
            )

        elif query.data == "help":
            await query.answer()
            buttons = [
                [
                    InlineKeyboardButton("🚫 Bans", callback_data="bans"),
                    InlineKeyboardButton(
                        "💬 Custom Messages", callback_data="custommessages"
                    ),
                ],
                [
                    InlineKeyboardButton(
                        "📝 Custom Captions", callback_data="customcaption"
                    ),
                    InlineKeyboardButton("🗑️ Delete", callback_data="delete"),
                ],
                [
                    InlineKeyboardButton("📱 Force Sub", callback_data="forcesub"),
                    InlineKeyboardButton("📝 Filters", callback_data="filters"),
                ],
                [
                    InlineKeyboardButton("📚 Index", callback_data="index"),
                    InlineKeyboardButton("📢 Promotions", callback_data="promotions"),
                ],
                [
                    InlineKeyboardButton("⚙️ Settings", callback_data="settings"),
                    InlineKeyboardButton("📊 Utilities", callback_data="utilities"),
                ],
                [
                    InlineKeyboardButton("🌐 Connections", callback_data="connections"),
                    InlineKeyboardButton("👥 Force Add", callback_data="forceadd"),
                ],
                [InlineKeyboardButton("💾 Backup", callback_data="backup")],
                [
                    InlineKeyboardButton("🔙 Back", callback_data="start"),
                    InlineKeyboardButton("🔐 Cʟᴏsᴇ", callback_data="close_data"),
                ],
            ]
            await query.message.edit_text(
                text=script.HELP_TXT.format(mention=query.from_user.mention),
                reply_markup=InlineKeyboardMarkup(buttons),
                parse_mode=enums.ParseMode.HTML,
            )

        elif query.data == "about":
            await query.answer()
            buttons = [
                [InlineKeyboardButton("Sᴛᴀᴛᴜs ​", callback_data="stats")],
                [
                    InlineKeyboardButton("🏘 Hᴏᴍᴇ", callback_data="start"),
                    InlineKeyboardButton("🔐 Cʟᴏsᴇ", callback_data="close_data"),
                ],
            ]
            await query.message.edit_text(
                text=script.ABOUT_TXT.format(bname=temp.B_NAME),
                reply_markup=InlineKeyboardMarkup(buttons),
                parse_mode=enums.ParseMode.HTML,
            )

        elif query.data == "bans":
            await query.answer()
            await query.message.edit_text(
                text=script.BANS_TXT,
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🔙 Back", callback_data="help")]]
                ),
                parse_mode=enums.ParseMode.HTML,
            )

        elif query.data == "custommessages":
            await query.answer()
            await query.message.edit_text(
                text=script.CUSTOMMESSAGES_TXT,
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🔙 Back", callback_data="help")]]
                ),
                parse_mode=enums.ParseMode.HTML,
            )

        elif query.data == "customcaption":
            await query.answer()
            await query.message.edit_text(
                text=script.CUSTOMCAPTION_TXT,
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🔙 Back", callback_data="help")]]
                ),
                parse_mode=enums.ParseMode.HTML,
            )

        elif query.data == "delete":
            await query.answer()
            await query.message.edit_text(
                text=script.DELETE_TXT,
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🔙 Back", callback_data="help")]]
                ),
                parse_mode=enums.ParseMode.HTML,
            )

        elif query.data == "forcesub":
            await query.answer()
            await query.message.edit_text(
                text=script.FORCESUB_TXT,
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🔙 Back", callback_data="help")]]
                ),
                parse_mode=enums.ParseMode.HTML,
            )

        elif query.data == "filters":
            await query.answer()
            await query.message.edit_text(
                text=script.FILTERS_TXT,
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🔙 Back", callback_data="help")]]
                ),
                parse_mode=enums.ParseMode.HTML,
            )

        elif query.data == "index":
            await query.answer()
            await query.message.edit_text(
                text=script.INDEX_TXT,
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🔙 Back", callback_data="help")]]
                ),
                parse_mode=enums.ParseMode.HTML,
            )

        elif query.data == "promotions":
            await query.answer()
            await query.message.edit_text(
                text=script.PROMOTIONS_TXT,
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🔙 Back", callback_data="help")]]
                ),
                parse_mode=enums.ParseMode.HTML,
            )

        elif query.data == "settings":
            await query.answer()
            await query.message.edit_text(
                text=script.SETTINGS_TXT,
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🔙 Back", callback_data="help")]]
                ),
                parse_mode=enums.ParseMode.HTML,
            )

        elif query.data == "utilities":
            await query.answer()
            await query.message.edit_text(
                text=script.UTILITIES_TXT,
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🔙 Back", callback_data="help")]]
                ),
                parse_mode=enums.ParseMode.HTML,
            )

        elif query.data == "connections":
            await query.answer()
            await query.message.edit_text(
                text=script.CONNECTIONS_TXT,
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🔙 Back", callback_data="help")]]
                ),
                parse_mode=enums.ParseMode.HTML,
            )

        elif query.data == "forceadd":
            await query.answer()
            await query.message.edit_text(
                text=script.FORCEADD_TXT,
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🔙 Back", callback_data="help")]]
                ),
                parse_mode=enums.ParseMode.HTML,
            )

        elif query.data == "backup":
            await query.answer()
            await query.message.edit_text(
                text=script.BACKUP_TXT,
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🔙 Back", callback_data="help")]]
                ),
                parse_mode=enums.ParseMode.HTML,
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
            await query.message.edit_text(
                text=script.STATUS_TXT.format(
                    total, users, chats, get_size(monsize), get_size(free)
                ),
                reply_markup=InlineKeyboardMarkup(buttons),
                parse_mode=enums.ParseMode.HTML,
            )

    except QueryIdInvalid:
        pass
    except Exception as e:
        logger.error(f"Callback Error: {e}")


async def auto_filter(client, msg, spoll=False):
    if not spoll:
        message = msg
        settings = await get_settings(message.chat.id)

        if (
            not message.text
            or message.text.startswith("/")
            or re.findall(r"((^\/|^,|^!|^\.|^[\U0001F600-\U000E007F]).*)", message.text)
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
        settings = await get_settings(msg.message.chat.id)
        message = msg.message.reply_to_message
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
        0,
        [InlineKeyboardButton("•  Bᴀᴄᴋ Uᴘ Cʜᴀɴɴᴇʟ  •", url="https://t.me/KR_PICTURE")],
    )

    if offset:
        key = f"{message.chat.id}-{message.id}"
        BUTTONS[key] = search
        req = message.from_user.id if message.from_user else 0
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

    cap = f"Hey {message.from_user.mention if message.from_user else 'User'} 👋🏻\n\n➤ Title : {search}\n➤ Your Files Ready Now 👇"

    try:
        m = await message.reply_text(cap, reply_markup=InlineKeyboardMarkup(btn))
    except Exception as e:
        return logger.error(f"auto_filter error: {e}")

    if spoll:
        try:
            await msg.message.delete()
        except MessageIdInvalid:
            pass

    if getattr(info, "BUTTON_AUTO_DELETE", 1800) > 0:
        asyncio.create_task(delete_message_after_delay(m, info.BUTTON_AUTO_DELETE))


async def advantage_spell_chok(msg):
    query = (
        re.sub(
            r"\b(pl(i|e)*?(s|z+|ease|se|ese|(e+)s(e)?)|((send|snd|giv(e)?|gib)(\sme)?)|movie(s)?|new|latest|br((o|u)h?)*|^h(e|a)?(l)*(o)*|mal(ayalam)?|t(h)?amil|file|that|find|und(o)*|kit(t(i|y)?)?o(w)?|thar(u)?(o)*w?|kittum(o)*|aya(k)*(um(o)*)?|full\smovie|any(one)|with\ssubtitle(s)?)",
            "",
            msg.text,
            flags=re.IGNORECASE,
        ).strip()
        + " movie"
    )
    g_s = await search_gagala(query)
    g_s += await search_gagala(msg.text)

    if not g_s:
        try:
            k_msg = await msg.reply_photo(
                photo=FILE_NOT_FOUND_PIC, caption=NOT_FOUND_TEXT
            )
            if getattr(info, "BUTTON_AUTO_DELETE", 1800) > 0:
                asyncio.create_task(
                    delete_message_after_delay(k_msg, info.BUTTON_AUTO_DELETE)
                )
        except Exception:
            pass
        return

    gs = list(filter(re.compile(r".*(imdb|wikipedia).*", re.IGNORECASE).match, g_s))
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
            if match := reg.match(mv):
                gs_parsed.append(match.group(1))

    user = msg.from_user.id if msg.from_user else 0
    gs_parsed = list(dict.fromkeys(gs_parsed))[:3]
    movielist = []

    if gs_parsed:
        for mov in gs_parsed:
            if imdb_s := await get_poster(mov.strip(), bulk=True):
                movielist += [movie.get("title") for movie in imdb_s]

    movielist += [
        (re.sub(r"(\-|\(|\)|_)", "", i, flags=re.IGNORECASE)).strip() for i in gs_parsed
    ]
    movielist = list(dict.fromkeys(movielist))

    if not movielist:
        try:
            k_msg = await msg.reply_photo(
                photo=FILE_NOT_FOUND_PIC, caption=NOT_FOUND_TEXT
            )
            if getattr(info, "BUTTON_AUTO_DELETE", 1800) > 0:
                asyncio.create_task(
                    delete_message_after_delay(k_msg, info.BUTTON_AUTO_DELETE)
                )
        except Exception:
            pass
        return

    SPELL_CHECK[msg.id] = movielist
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

    for keyword in reversed(sorted(keywords, key=len)):
        if re.search(
            r"( |^|[^\w])" + re.escape(keyword) + r"( |$|[^\w])",
            name,
            flags=re.IGNORECASE,
        ):
            reply_text, btn, alert, fileid = await find_filter(group_id, keyword)

            if reply_text:
                reply_text = reply_text.replace("\\n", "\n").replace("\\t", "\t")

            try:
                reply_markup = (
                    InlineKeyboardMarkup(ast.literal_eval(btn)) if btn != "[]" else None
                )
                if fileid == "None":
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

                if sent_msg and getattr(info, "BUTTON_AUTO_DELETE", 1800) > 0:
                    asyncio.create_task(
                        delete_message_after_delay(sent_msg, info.BUTTON_AUTO_DELETE)
                    )
            except Forbidden as e:
                if "CHAT_SEND_PHOTOS_FORBIDDEN" in str(
                    e
                ) or "CHAT_SEND_MEDIA_FORBIDDEN" in str(e):
                    try:
                        sent_msg = await client.send_message(
                            group_id,
                            text=(
                                f"{reply_text}\n\n*(Media blocked)*"
                                if reply_text
                                else "*(Media blocked)*"
                            ),
                            reply_to_message_id=reply_id,
                        )
                        if sent_msg and getattr(info, "BUTTON_AUTO_DELETE", 1800) > 0:
                            asyncio.create_task(
                                delete_message_after_delay(
                                    sent_msg, info.BUTTON_AUTO_DELETE
                                )
                            )
                    except Exception:
                        pass
            except Exception as e:
                logger.exception(e)
            return True
    return False
