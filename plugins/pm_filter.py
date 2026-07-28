import ast
import asyncio
import logging
import math
import re

from pyrogram import Client, enums, filters
from pyrogram.errors import (
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
from database.users_chats_db import db
import info
from info import ADMINS, AUTH_CHANNEL, CUSTOM_FILE_CAPTION, REQ_CHANNEL
from Script import script
from utils import (
    get_poster,
    get_settings,
    get_size,
    is_subscribed,
    save_group_settings,
    search_gagala,
    temp,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.ERROR)

BUTTONS = {}
SPELL_CHECK = {}
DELETE_TIME = 1800  # 30 Minutes

FILE_NOT_FOUND_PIC = "https://telegra.ph/file/c4f0458d30f61993aad45-086b84e8363b3c582e.jpg"
NOT_FOUND_TEXT = (
    "<b>🚫 File not found. Please note👇\n \n"
    "✅ Use correct spelling as given in Google.\n \n"
    "✅ DO NOT ask for files which are not released in OTT.\n \n"
    "✅ Request movies in this format - (Moviename) (Year of release) \n"
    "Eg. Jai Ganesh 2024 </b>"
)

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


# ============================================================
# 🔍 MAIN AUTO-FILTER HANDLER
# ============================================================
@Client.on_message((filters.group) & filters.text & filters.incoming)
async def give_filter(client, message):
    # 🛠️ REPAIR MODE CHECK
    if getattr(info, "REPAIR_MODE", False):
        if not message.from_user or message.from_user.id not in info.ADMINS:
            return await message.reply_text(
                "🛠️ **Bot is currently under maintenance!**\n\n"
                "We are performing some upgrades/fixes. Please try again later."
            )

    k = await manual_filters(client, message)
    if not k:
        await auto_filter(client, message)


# ============================================================
# 📄 PAGINATION HANDLER
# ============================================================
@Client.on_callback_query(filters.regex(r"^next"))
async def next_page(bot, query):
    # 🛠️ REPAIR MODE CHECK FOR CALLBACKS
    if getattr(info, "REPAIR_MODE", False):
        if query.from_user.id not in info.ADMINS:
            return await query.answer(
                "🛠️ Bot is currently under maintenance! We are performing some upgrades. Please try again later.",
                show_alert=True
            )

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
        try:
            await query.answer(
                "You are using one of my old messages, please send the request again.",
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

    files.sort(key=lambda x: x.get("file_size", 0) if isinstance(x, dict) else getattr(x, "file_size", 0))

    settings = await get_settings(query.message.chat.id)
    btn = []

    for file in files:
        file_id = file.get("file_id", "") if isinstance(file, dict) else getattr(file, "file_id", "")
        file_name = file.get("file_name", "Unknown") if isinstance(file, dict) else getattr(file, "file_name", "Unknown")
        file_size = file.get("file_size", 0) if isinstance(file, dict) else getattr(file, "file_size", 0)

        if settings.get("button", False):
            btn.append(
                [InlineKeyboardButton(text=f"{get_size(file_size)} | {file_name}", url=f"https://t.me/{temp.U_NAME}?start=files_{file_id}")]
            )
        else:
            btn.append(
                [
                    InlineKeyboardButton(text=f"{file_name}", url=f"https://t.me/{temp.U_NAME}?start=files_{file_id}"),
                    InlineKeyboardButton(text=f"{get_size(file_size)}", url=f"https://t.me/{temp.U_NAME}?start=files_{file_id}"),
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
                InlineKeyboardButton("BACK", callback_data=f"next_{req}_{key}_{off_set}"),
                InlineKeyboardButton(f"Pages {math.ceil(int(offset) / 10) + 1} / {math.ceil(total / 10)}", callback_data="pages"),
            ]
        )
    elif off_set is None:
        btn.insert(0, [InlineKeyboardButton("•  Bᴀᴄᴋ Uᴘ Cʜᴀɴɴᴇʟ  •", url="https://t.me/KR_PICTURE")])
        btn.append(
            [
                InlineKeyboardButton(f"{math.ceil(int(offset) / 10) + 1} / {math.ceil(total / 10)}", callback_data="pages"),
                InlineKeyboardButton("NEXT", callback_data=f"next_{req}_{key}_{n_offset}"),
            ]
        )
    else:
        btn.append(
            [
                InlineKeyboardButton("BACK", callback_data=f"next_{req}_{key}_{off_set}"),
                InlineKeyboardButton(f"{math.ceil(int(offset) / 10) + 1} / {math.ceil(total / 10)}", callback_data="pages"),
                InlineKeyboardButton("NEXT", callback_data=f"next_{req}_{key}_{n_offset}"),
            ]
        )

    try:
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(btn))
    except (MessageNotModified, MessageIdInvalid):
        pass
    except FloodWait as e:
        await asyncio.sleep(e.value)
        try:
            await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(btn))
        except Exception:
            pass
    try:
        await query.answer()
    except QueryIdInvalid:
        pass


# ============================================================
# ✍️ SPELL CHECK HANDLER
# ============================================================
@Client.on_callback_query(filters.regex(r"^spolling"))
async def advantage_spoll_choker(bot, query):
    # 🛠️ REPAIR MODE CHECK FOR CALLBACKS
    if getattr(info, "REPAIR_MODE", False):
        if query.from_user.id not in info.ADMINS:
            return await query.answer(
                "🛠️ Bot is currently under maintenance! We are performing some upgrades. Please try again later.",
                show_alert=True
            )

    _, user, movie_ = query.data.split("#")
    try:
        if int(user) != 0 and query.from_user.id != int(user):
            return await query.answer("That's not for you!", show_alert=True)

        if movie_ == "close_spellcheck":
            return await query.message.delete()

        movies = SPELL_CHECK.get(query.message.reply_to_message.id)
        if not movies:
            return await query.answer("You are clicking on an old button which is expired.", show_alert=True)

        movie = movies[(int(movie_))]
        await query.answer("Checking for Movie in database...")
    except QueryIdInvalid:
        pass

    k = await manual_filters(bot, query.message, text=movie)
    if not k:
        files, offset, total_results = await get_search_results(movie, max_results=10, offset=0, filter=True)
        if files:
            k = (movie, files, offset, total_results)
            await auto_filter(bot, query, k)
        else:
            try:
                await query.message.delete()
            except MessageIdInvalid:
                pass

            try:
                k_msg = await bot.send_photo(chat_id=query.message.chat.id, photo=FILE_NOT_FOUND_PIC, caption=NOT_FOUND_TEXT)
            except Forbidden as e:
                if "CHAT_SEND_PHOTOS_FORBIDDEN" in str(e):
                    k_msg = await bot.send_message(chat_id=query.message.chat.id, text=f"{NOT_FOUND_TEXT}\n\n*(No photo attached due to chat permissions)*")
                else:
                    k_msg = None
            except Exception:
                k_msg = None

            if k_msg:
                asyncio.create_task(delete_message_after_delay(k_msg, DELETE_TIME))


# ============================================================
# 🎛 MAIN CALLBACK HANDLER (MENU / BUTTONS)
# ============================================================
@Client.on_callback_query()
async def cb_handler(client: Client, query: CallbackQuery):
    # 🛠️ REPAIR MODE CHECK FOR CALLBACKS
    if getattr(info, "REPAIR_MODE", False):
        # We allow admins to bypass, or if the user is just closing a menu ("close_data") they can do that.
        if query.from_user.id not in info.ADMINS and query.data != "close_data":
            return await query.answer(
                "🛠️ Bot is currently under maintenance! We are performing some upgrades. Please try again later.",
                show_alert=True
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
                    grp_id = grpid
                    try:
                        chat = await client.get_chat(grpid)
                        title = chat.title
                    except Exception:
                        try:
                            await query.message.edit_text("Make sure I'm present in your group!!", quote=True)
                        except (MessageIdInvalid, MessageNotModified):
                            pass
                        return await query.answer("Join: @KR_PICTURE")
                else:
                    try:
                        await query.message.edit_text("I'm not connected to any groups!\nCheck /connections or connect to any groups", quote=True)
                    except (MessageIdInvalid, MessageNotModified):
                        pass
                    return await query.answer("Join: @KR_PICTURE")

            elif chat_type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
                grp_id = query.message.chat.id
                title = query.message.chat.title
            else:
                return await query.answer("Join: @KR_PICTURE")

            st = await client.get_chat_member(grp_id, userid)
            if (st.status == enums.ChatMemberStatus.OWNER) or (str(userid) in ADMINS):
                await del_all(query.message, grp_id, title)
            else:
                await query.answer("You need to be Group Owner or an Auth User to do that!", show_alert=True)

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
                st = await client.get_chat_member(grp_id, userid)
                if (st.status == enums.ChatMemberStatus.OWNER) or (str(userid) in ADMINS):
                    try:
                        await query.message.delete()
                        await query.message.reply_to_message.delete()
                    except Exception:
                        pass
                else:
                    await query.answer("That's not for you!!", show_alert=True)

        # Connection Handlers
        elif "groupcb" in query.data:
            await query.answer()
            group_id = query.data.split(":")[1]
            act = query.data.split(":")[2]
            hr = await client.get_chat(int(group_id))
            title = hr.title

            stat = "CONNECT" if act == "" else "DISCONNECT"
            cb = "connectcb" if act == "" else "disconnect"

            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton(f"{stat}", callback_data=f"{cb}:{group_id}"), InlineKeyboardButton("DELETE", callback_data=f"deletecb:{group_id}")],
                [InlineKeyboardButton("BACK", callback_data="backcb")]
            ])
            try:
                await query.message.edit_text(f"Group Name : **{title}**\nGroup ID : `{group_id}`", reply_markup=keyboard, parse_mode=enums.ParseMode.MARKDOWN)
            except (MessageIdInvalid, MessageNotModified):
                pass

        elif "connectcb" in query.data:
            await query.answer()
            group_id = query.data.split(":")[1]
            hr = await client.get_chat(int(group_id))
            mkact = await make_active(str(query.from_user.id), str(group_id))
            try:
                if mkact:
                    await query.message.edit_text(f"Connected to **{hr.title}**", parse_mode=enums.ParseMode.MARKDOWN)
                else:
                    await query.message.edit_text("Some error occurred!!", parse_mode=enums.ParseMode.MARKDOWN)
            except (MessageIdInvalid, MessageNotModified):
                pass

        elif "disconnect" in query.data:
            await query.answer()
            group_id = query.data.split(":")[1]
            hr = await client.get_chat(int(group_id))
            mkinact = await make_inactive(str(query.from_user.id))
            try:
                if mkinact:
                    await query.message.edit_text(f"Disconnected from **{hr.title}**", parse_mode=enums.ParseMode.MARKDOWN)
                else:
                    await query.message.edit_text(f"Some error occurred!!", parse_mode=enums.ParseMode.MARKDOWN)
            except (MessageIdInvalid, MessageNotModified):
                pass

        elif "deletecb" in query.data:
            await query.answer()
            delcon = await delete_connection(str(query.from_user.id), str(query.data.split(":")[1]))
            try:
                if delcon:
                    await query.message.edit_text("Successfully deleted connection")
                else:
                    await query.message.edit_text(f"Some error occurred!!", parse_mode=enums.ParseMode.MARKDOWN)
            except (MessageIdInvalid, MessageNotModified):
                pass

        elif query.data == "backcb":
            await query.answer()
            groupids = await all_connections(str(query.from_user.id))
            if groupids is None:
                try:
                    await query.message.edit_text("There are no active connections!! Connect to some groups first.")
                except (MessageIdInvalid, MessageNotModified):
                    pass
                return

            buttons = []
            for groupid in groupids:
                try:
                    ttl = await client.get_chat(int(groupid))
                    active = await if_active(str(query.from_user.id), str(groupid))
                    act = " - ACTIVE" if active else ""
                    buttons.append([InlineKeyboardButton(text=f"{ttl.title}{act}", callback_data=f"groupcb:{groupid}:{act}")])
                except Exception:
                    pass
            if buttons:
                try:
                    await query.message.edit_text("Your connected group details ;\n\n", reply_markup=InlineKeyboardMarkup(buttons))
                except (MessageIdInvalid, MessageNotModified):
                    pass

        elif "alertmessage" in query.data:
            grp_id = query.message.chat.id
            i = query.data.split(":")[1]
            keyword = query.data.split(":")[2]
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
            title = files.file_name
            size = get_size(files.file_size)
            f_caption = files.caption
            settings = await get_settings(query.message.chat.id)
            
            if CUSTOM_FILE_CAPTION:
                try:
                    f_caption = CUSTOM_FILE_CAPTION.format(file_name="" if title is None else title, file_size="" if size is None else size, file_caption="" if f_caption is None else f_caption)
                except Exception as e:
                    logger.exception(e)
            if f_caption is None:
                f_caption = f"{files.file_name}"

            try:
                if (AUTH_CHANNEL or REQ_CHANNEL) and not await is_subscribed(client, query):
                    await query.answer(url=f"https://t.me/{temp.U_NAME}?start={ident}_{file_id}")
                    return
                elif settings.get("botpm", False):
                    await query.answer(url=f"https://t.me/{temp.U_NAME}?start={ident}_{file_id}")
                    return
                else:
                    await client.send_cached_media(chat_id=query.from_user.id, file_id=file_id, caption=f_caption, protect_content=True if ident == "filep" else False)
                    await query.answer("Check PM, I have sent files in pm", show_alert=True)
            except UserIsBlocked:
                await query.answer("Unblock the bot mahn !", show_alert=True)
            except (PeerIdInvalid, Exception):
                await query.answer(url=f"https://t.me/{temp.U_NAME}?start={ident}_{file_id}")

        elif query.data.startswith("checksub"):
            if (AUTH_CHANNEL or REQ_CHANNEL) and not await is_subscribed(client, query):
                return await query.answer("I Like Your Smartness, But Don't Be Oversmart 😒", show_alert=True)

            ident, file_id = query.data.split("#")
            files_ = await get_file_details(file_id)
            if not files_:
                return await query.answer("No such file exist.")

            files = files_[0]
            title = files.file_name
            size = get_size(files.file_size)
            f_caption = files.caption
            if CUSTOM_FILE_CAPTION:
                try:
                    f_caption = CUSTOM_FILE_CAPTION.format(file_name="" if title is None else title, file_size="" if size is None else size, file_caption="" if f_caption is None else f_caption)
                except Exception as e:
                    logger.exception(e)
            if f_caption is None:
                f_caption = f"{title}"

            await query.answer()
            m = await client.send_cached_media(chat_id=query.from_user.id, file_id=file_id, caption=f_caption, protect_content=True if ident == "checksubp" else False)
            k = await client.send_message(chat_id=query.from_user.id, text=f"<blockquote><b><u>❗️❗️❗️IMPORTANT❗️️❗️❗️</u></b>\n\n⚠️ File will be deleted in 30 Minutes\n\n📌 Save or forward it.</blockquote>")

            async def delete_and_notify():
                await asyncio.sleep(DELETE_TIME)
                try:
                    await m.delete()
                    await k.edit_text(f"<b>Hey <i>{query.from_user.first_name}</i>\n\nYour Request Has Been Deleted 👍 \n(Due To Avoid Copyrights Issue😌)\n\nIF YOU WANT THAT FILE, REQUEST AGAIN ❤️ In Our Group</b>")
                except Exception:
                    pass
            asyncio.create_task(delete_and_notify())

        elif query.data == "pages":
            await query.answer()

        elif query.data == "start":
            buttons = [
                [InlineKeyboardButton("✈️ Group 1", url="https://t.me/Sandalwood_Kannada_Group"), InlineKeyboardButton("✈️ Group 2", url="http://t.me/Kannada_Filmy_Group"), InlineKeyboardButton("✈️ Group 3", url="https://t.me/+GLsPkRgLGGszMzY1")],
            ]
            if query.from_user.id in ADMINS or str(query.from_user.id) in ADMINS:
                buttons.append([InlineKeyboardButton("ℹ️ 𝙷𝚎𝚕𝚙", callback_data="help"), InlineKeyboardButton("😊 𝙰𝚋𝚘𝚞𝚝", callback_data="about")])
            buttons.append([InlineKeyboardButton("🔗 New Releases & OTT Updates", url="https://t.me/sandalwood_kannada_moviesz")])
            try:
                await query.message.edit_text(text=script.START_TXT.format(mention=query.from_user.mention, uname=temp.U_NAME, bname=temp.B_NAME, plane_emoji=MESSAGE_EMOJI_PLANE, link_emoji=MESSAGE_EMOJI_LINK), reply_markup=InlineKeyboardMarkup(buttons), parse_mode=enums.ParseMode.HTML)
            except (MessageIdInvalid, MessageNotModified):
                pass
            await query.answer("Join: @KR_PICTURE")

        # Basic Navigational Callbacks
        elif query.data == "help":
            buttons = [
                [InlineKeyboardButton("⍟  Auto Fɪʟᴛᴇʀ", callback_data="autofilter"), InlineKeyboardButton("⍟  Manual Filter", callback_data="manuelfilter")],
                [InlineKeyboardButton("⍟  Connection", callback_data="coct"), InlineKeyboardButton("⍟  ForceSub", callback_data="fsubs"), InlineKeyboardButton("⍟  Admin Mod", callback_data="extra")],
                [InlineKeyboardButton("🏘 Hᴏᴍᴇ", callback_data="start"), InlineKeyboardButton("🔐 Cʟᴏsᴇ", callback_data="close_data")],
            ]
            try:
                await query.message.edit_text(text=script.HELP_TXT.format(mention=query.from_user.mention), reply_markup=InlineKeyboardMarkup(buttons), parse_mode=enums.ParseMode.HTML)
            except (MessageIdInvalid, MessageNotModified):
                pass

        elif query.data == "about":
            buttons = [[InlineKeyboardButton("Sᴛᴀᴛᴜs ​", callback_data="stats")], [InlineKeyboardButton("🏘 Hᴏᴍᴇ", callback_data="start"), InlineKeyboardButton("🔐 Cʟᴏsᴇ", callback_data="close_data")]]
            try:
                await query.message.edit_text(text=script.ABOUT_TXT.format(bname=temp.B_NAME), reply_markup=InlineKeyboardMarkup(buttons), parse_mode=enums.ParseMode.HTML)
            except (MessageIdInvalid, MessageNotModified):
                pass

        elif query.data == "fsubs":
            buttons = [[InlineKeyboardButton("⇌ Bᴀᴄᴋ ⇌", callback_data="help")]]
            try:
                await query.message.edit_text(text=script.FRSUB_TXT, reply_markup=InlineKeyboardMarkup(buttons), parse_mode=enums.ParseMode.HTML)
            except (MessageIdInvalid, MessageNotModified):
                pass

        elif query.data == "manuelfilter":
            buttons = [[InlineKeyboardButton("⇌ Bᴀᴄᴋ ⇌", callback_data="help"), InlineKeyboardButton("⏹️ Buttons", callback_data="button")]]
            try:
                await query.message.edit_text(text=script.MANUELFILTER_TXT, reply_markup=InlineKeyboardMarkup(buttons), parse_mode=enums.ParseMode.HTML)
            except (MessageIdInvalid, MessageNotModified):
                pass

        elif query.data == "button":
            buttons = [[InlineKeyboardButton("⇌ Bᴀᴄᴋ ⇌", callback_data="manuelfilter")]]
            try:
                await query.message.edit_text(text=script.BUTTON_TXT, reply_markup=InlineKeyboardMarkup(buttons), parse_mode=enums.ParseMode.HTML)
            except (MessageIdInvalid, MessageNotModified):
                pass

        elif query.data == "autofilter":
            buttons = [[InlineKeyboardButton("⇌ Bᴀᴄᴋ ⇌", callback_data="help")]]
            try:
                await query.message.edit_text(text=script.AUTOFILTER_TXT, reply_markup=InlineKeyboardMarkup(buttons), parse_mode=enums.ParseMode.HTML)
            except (MessageIdInvalid, MessageNotModified):
                pass

        elif query.data == "coct":
            buttons = [[InlineKeyboardButton("⇌ Bᴀᴄᴋ ⇌", callback_data="help")]]
            try:
                await query.message.edit_text(text=script.CONNECTION_TXT, reply_markup=InlineKeyboardMarkup(buttons), parse_mode=enums.ParseMode.HTML)
            except (MessageIdInvalid, MessageNotModified):
                pass

        elif query.data == "extra":
            buttons = [[InlineKeyboardButton("⇌ Bᴀᴄᴋ ⇌", callback_data="help"), InlineKeyboardButton("👮‍♂️ Admin", callback_data="admin")]]
            try:
                await query.message.edit_text(text=script.EXTRAMOD_TXT, reply_markup=InlineKeyboardMarkup(buttons), parse_mode=enums.ParseMode.HTML)
            except (MessageIdInvalid, MessageNotModified):
                pass

        elif query.data == "admin":
            buttons = [[InlineKeyboardButton("⇌ Bᴀᴄᴋ ⇌", callback_data="extra")]]
            try:
                await query.message.edit_text(text=script.ADMIN_TXT, reply_markup=InlineKeyboardMarkup(buttons), parse_mode=enums.ParseMode.HTML)
            except (MessageIdInvalid, MessageNotModified):
                pass

        elif query.data in ["stats", "rfrsh"]:
            if query.data == "rfrsh":
                try:
                    await query.answer("Fetching MongoDb DataBase")
                except QueryIdInvalid:
                    pass
            buttons = [[InlineKeyboardButton("⇌ Bᴀᴄᴋ ⇌", callback_data="help" if query.data == "rfrsh" else "about"), InlineKeyboardButton("♻️", callback_data="rfrsh")]]
            total = await Media.count_documents()
            users = await db.total_users_count()
            chats = await db.total_chat_count()
            monsize = await db.get_db_size()
            free = 536870912 - monsize
            monsize = get_size(monsize)
            free = get_size(free)
            try:
                await query.message.edit_text(text=script.STATUS_TXT.format(total, users, chats, monsize, free), reply_markup=InlineKeyboardMarkup(buttons), parse_mode=enums.ParseMode.HTML)
            except (MessageIdInvalid, MessageNotModified):
                pass

    except QueryIdInvalid:
        pass


# ============================================================
# 🔎 SEARCH LOGIC (auto_filter, advantage_spell_chok, manual_filters)
# ============================================================
async def auto_filter(client, msg, spoll=False):
    if not spoll:
        message = msg
        settings = await get_settings(message.chat.id)

        if not message.text or message.text.startswith("/"): return
        if re.findall(r"((^\/|^,|^!|^\.|^[\U0001F600-\U000E007F]).*)", message.text): return
        if not (2 < len(message.text) < 100): return

        search = message.text
        files, offset, total_results = await get_search_results(search.lower(), max_results=10, offset=0, filter=True)

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

    files.sort(key=lambda x: x.get("file_size", 0) if isinstance(x, dict) else getattr(x, "file_size", 0))

    pre = "filep" if settings.get("file_secure") else "file"
    btn = []

    for file in files:
        file_id = file.get("file_id", "") if isinstance(file, dict) else getattr(file, "file_id", "")
        file_name = file.get("file_name", "Unknown") if isinstance(file, dict) else getattr(file, "file_name", "Unknown")
        file_size = file.get("file_size", 0) if isinstance(file, dict) else getattr(file, "file_size", 0)

        if settings.get("button"):
            btn.append([InlineKeyboardButton(text=f"{get_size(file_size)} | {file_name}", url=f"https://t.me/{temp.U_NAME}?start={pre}_{file_id}")])
        else:
            btn.append([InlineKeyboardButton(text=file_name, url=f"https://t.me/{temp.U_NAME}?start={pre}_{file_id}"), InlineKeyboardButton(text=get_size(file_size), url=f"https://t.me/{temp.U_NAME}?start={pre}_{file_id}")])

    btn.insert(0, [InlineKeyboardButton("•  Bᴀᴄᴋ Uᴘ Cʜᴀɴɴᴇʟ  •", url="https://t.me/KR_PICTURE")])

    if offset:
        key = f"{message.chat.id}-{message.id}"
        BUTTONS[key] = search
        req = message.from_user.id if message.from_user else 0
        btn.append([InlineKeyboardButton(text=f"1/{math.ceil(int(total_results) / 10)}", callback_data="pages"), InlineKeyboardButton(text="NEXT", callback_data=f"next_{req}_{key}_{offset}")])
    else:
        btn.append([InlineKeyboardButton(text="1/1", callback_data="pages")])

    mention = message.from_user.mention if message.from_user else "User"
    cap = f"Hey {mention} 👋🏻\n\n➤ Title : {search}\n➤ Your Files Ready Now 👇"

    try:
        m = await message.reply_text(cap, reply_markup=InlineKeyboardMarkup(btn))
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
    asyncio.create_task(delete_message_after_delay(m, DELETE_TIME))


async def advantage_spell_chok(msg):
    query = re.sub(r"\b(pl(i|e)*?(s|z+|ease|se|ese|(e+)s(e)?)|((send|snd|giv(e)?|gib)(\sme)?)|movie(s)?|new|latest|br((o|u)h?)*|^h(e|a)?(l)*(o)*|mal(ayalam)?|t(h)?amil|file|that|find|und(o)*|kit(t(i|y)?)?o(w)?|thar(u)?(o)*w?|kittum(o)*|aya(k)*(um(o)*)?|full\smovie|any(one)|with\ssubtitle(s)?)", "", msg.text, flags=re.IGNORECASE).strip() + " movie"
    g_s = await search_gagala(query)
    g_s += await search_gagala(msg.text)
    gs_parsed = []

    if not g_s:
        try:
            k_msg = await msg.reply_photo(photo=FILE_NOT_FOUND_PIC, caption=NOT_FOUND_TEXT)
        except RandomIdDuplicate:
            k_msg = None
        except Forbidden as e:
            if "CHAT_SEND_PHOTOS_FORBIDDEN" in str(e):
                try:
                    not_found_msg = await msg.reply_text(text=f"{NOT_FOUND_TEXT}\n\n*(No photo attached due to chat permissions)*")
                    k_msg = not_found_msg
                except Exception:
                    k_msg = None
            else:
                k_msg = None
        except Exception:
            k_msg = None
        if k_msg: asyncio.create_task(delete_message_after_delay(k_msg, DELETE_TIME))
        return

    regex = re.compile(r".*(imdb|wikipedia).*", re.IGNORECASE)
    gs = list(filter(regex.match, g_s))
    gs_parsed = [re.sub(r"\b(\-([a-zA-Z-\s])\-\simdb|(\-\s)?imdb|(\-\s)?wikipedia|\(|\)|\-|reviews|full|all|episode(s)?|film|movie|series)", "", i, flags=re.IGNORECASE) for i in gs]

    if not gs_parsed:
        reg = re.compile(r"watch(\s[a-zA-Z0-9_\s\-\(\)]*)*\|.*", re.IGNORECASE)
        for mv in g_s:
            match = reg.match(mv)
            if match:
                gs_parsed.append(match.group(1))

    user = msg.from_user.id if msg.from_user else 0
    movielist = []
    gs_parsed = list(dict.fromkeys(gs_parsed))
    if len(gs_parsed) > 3:
        gs_parsed = gs_parsed[:3]

    if gs_parsed:
        for mov in gs_parsed:
            imdb_s = await get_poster(mov.strip(), bulk=True)
            if imdb_s:
                movielist += [movie.get("title") for movie in imdb_s]

    movielist += [(re.sub(r"(\-|\(|\)|_)", "", i, flags=re.IGNORECASE)).strip() for i in gs_parsed]
    movielist = list(dict.fromkeys(movielist))

    if not movielist:
        try:
            k_msg = await msg.reply_photo(photo=FILE_NOT_FOUND_PIC, caption=NOT_FOUND_TEXT)
        except RandomIdDuplicate:
            k_msg = None
        except Forbidden as e:
            if "CHAT_SEND_PHOTOS_FORBIDDEN" in str(e):
                try:
                    k_msg = await msg.reply_text(text=f"{NOT_FOUND_TEXT}\n\n*(No photo attached due to chat permissions)*")
                except Exception:
                    k_msg = None
            else:
                k_msg = None
        except Exception:
            k_msg = None

        if k_msg: asyncio.create_task(delete_message_after_delay(k_msg, DELETE_TIME))
        return

    SPELL_CHECK[msg.id] = movielist
    btn = [[InlineKeyboardButton(text=movie.strip(), callback_data=f"spolling#{user}#{idx}")] for idx, movie in enumerate(movielist)]
    btn.append([InlineKeyboardButton(text="Close", callback_data=f"spolling#{user}#close_spellcheck")])
    try:
        await msg.reply("<b>I couldn't find anything related to that. Did you mean any one of these?</b>", reply_markup=InlineKeyboardMarkup(btn))
    except Forbidden:
        pass


async def manual_filters(client, message, text=False):
    group_id = message.chat.id
    name = text or message.text
    reply_id = message.reply_to_message.id if message.reply_to_message else message.id
    keywords = await get_filters(group_id)

    for keyword in reversed(sorted(keywords, key=len)):
        pattern = r"( |^|[^\w])" + re.escape(keyword) + r"( |$|[^\w])"
        if re.search(pattern, name, flags=re.IGNORECASE):
            reply_text, btn, alert, fileid = await find_filter(group_id, keyword)

            if reply_text:
                reply_text = reply_text.replace("\\n", "\n").replace("\\t", "\t")

            if btn is not None:
                try:
                    sent_msg = None
                    if fileid == "None":
                        if btn == "[]":
                            sent_msg = await client.send_message(group_id, reply_text, disable_web_page_preview=True)
                        else:
                            button = ast.literal_eval(btn)
                            sent_msg = await client.send_message(group_id, reply_text, disable_web_page_preview=True, reply_markup=InlineKeyboardMarkup(button), reply_to_message_id=reply_id)
                    elif btn == "[]":
                        sent_msg = await client.send_cached_media(group_id, fileid, caption=reply_text or "", reply_to_message_id=reply_id)
                    else:
                        button = ast.literal_eval(btn)
                        sent_msg = await message.reply_cached_media(fileid, caption=reply_text or "", reply_markup=InlineKeyboardMarkup(button), reply_to_message_id=reply_id)

                    if sent_msg:
                        asyncio.create_task(delete_message_after_delay(sent_msg, DELETE_TIME))

                except Forbidden as e:
                    if "CHAT_SEND_PHOTOS_FORBIDDEN" in str(e) or "CHAT_SEND_MEDIA_FORBIDDEN" in str(e):
                        try:
                            sent_msg = await client.send_message(group_id, text=f"{reply_text}\n\n*(Media blocked by chat permissions)*" if reply_text else "*(Media blocked by chat permissions)*", reply_to_message_id=reply_id)
                            if sent_msg: asyncio.create_task(delete_message_after_delay(sent_msg, DELETE_TIME))
                        except Exception:
                            pass
                except Exception as e:
                    logger.exception(e)
            return True
    return False
