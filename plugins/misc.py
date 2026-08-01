import os
from datetime import datetime
from pyrogram import Client, enums, filters
from pyrogram.errors import UserNotParticipant
from pyrogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from info import IMDB_TEMPLATE
from utils import extract_user, get_file_id, get_poster

@Client.on_message(filters.command("id"))
async def show_id(client, message):
    chat_type = message.chat.type
    if chat_type == enums.ChatType.PRIVATE:
        user = message.from_user
        await message.reply_text(f"<b>👤 Name:</b> {user.first_name} {user.last_name or ''}\n<b>💬 Username:</b> @{user.username or 'None'}\n<b>🆔 Telegram ID:</b> <code>{user.id}</code>\n<b>🌐 DC:</b> <code>{user.dc_id or 'N/A'}</code>", quote=True)
    else:
        text = f"<b>🆔 Chat ID:</b> <code>{message.chat.id}</code>\n"
        reply = message.reply_to_message
        if reply:
            text += f"<b>👤 User ID:</b> <code>{message.from_user.id if message.from_user else 'Anonymous'}</code>\n<b>↪️ Replied User ID:</b> <code>{reply.from_user.id if reply.from_user else 'Anonymous'}</code>\n"
            file_id, _, media_type = get_file_id(reply)
        else:
            text += f"<b>👤 User ID:</b> <code>{message.from_user.id if message.from_user else 'Anonymous'}</code>\n"
            file_id, _, media_type = get_file_id(message)
        if file_id: text += f"<b>{media_type.capitalize()} ID:</b> <code>{file_id}</code>\n"
        await message.reply_text(text, quote=True)

@Client.on_message(filters.command("info"))
async def who_is(client, message):
    status = await message.reply_text("🔍 Fetching user info...")
    user = await extract_user(message, message.text.split(None, 1)[1] if len(message.command) > 1 else None)
    if not user: return await status.edit("⚠️ No valid user found.")

    text = f"<b>👤 Name:</b> {user.first_name} {user.last_name or ''}\n<b>🆔 Telegram ID:</b> <code>{user.id}</code>\n<b>🌐 DC:</b> <code>{user.dc_id or 'N/A'}</code>\n<b>💬 Username:</b> @{user.username or 'None'}\n<b>🔗 Link:</b> <a href='tg://user?id={user.id}'>Click Here</a>\n"
    
    if message.chat.type in (enums.ChatType.SUPERGROUP, enums.ChatType.CHANNEL):
        try:
            member = await message.chat.get_member(user.id)
            text += f"<b>📅 Joined Chat On:</b> <code>{(member.joined_date or datetime.now()).strftime('%Y-%m-%d %H:%M:%S')}</code>\n"
        except UserNotParticipant: pass

    markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔐 Close", callback_data="close_data")]])
    if user.photo:
        try:
            photo_path = await client.download_media(user.photo.big_file_id)
            await message.reply_photo(photo=photo_path, caption=text, reply_markup=markup, parse_mode=enums.ParseMode.HTML)
            os.remove(photo_path)
        except Exception:
            await message.reply_text(text, reply_markup=markup, parse_mode=enums.ParseMode.HTML)
    else:
        await message.reply_text(text, reply_markup=markup, parse_mode=enums.ParseMode.HTML)
    await status.delete()

@Client.on_message(filters.command(["imdb", "search"]))
async def imdb_search(client, message):
    if len(message.command) < 2: return await message.reply("🎬 **Usage:** `/imdb Movie Name`")
    wait_msg = await message.reply("🔎 **Searching IMDb...**")
    try:
        movies = await get_poster(message.text.split(None, 1)[1], bulk=True)
        if not movies: return await wait_msg.edit("❌ **No results found.**")
    except Exception as e: return await wait_msg.edit(f"⚠️ **Error:** `{e}`")

    buttons = [[InlineKeyboardButton(f"{m.get('title')} ({m.get('year')})", callback_data=f"imdb#{m.movieID}")] for m in movies]
    await wait_msg.edit("🎥 **Results:**", reply_markup=InlineKeyboardMarkup(buttons))

@Client.on_callback_query(filters.regex("^imdb"))
async def imdb_callback(client, query):
    _, movie_id = query.data.split("#")
    imdb = await get_poster(query=movie_id, id=True)
    if not imdb: return await query.message.edit("❌ **No results found.**")

    buttons = [[InlineKeyboardButton(f"{imdb['title']}", url=imdb["url"])]]
    caption = IMDB_TEMPLATE.format(
        query=imdb["title"], title=imdb["title"], votes=imdb.get("votes", "N/A"), aka=imdb.get("aka", "N/A"),
        seasons=imdb.get("seasons", "N/A"), box_office=imdb.get("box_office", "N/A"), localized_title=imdb.get("localized_title", "N/A"),
        kind=imdb.get("kind", "N/A"), imdb_id=imdb.get("imdb_id", "N/A"), cast=imdb.get("cast", "N/A"), runtime=imdb.get("runtime", "N/A"),
        countries=imdb.get("countries", "N/A"), certificates=imdb.get("certificates", "N/A"), languages=imdb.get("languages", "N/A"),
        director=imdb.get("director", "N/A"), writer=imdb.get("writer", "N/A"), producer=imdb.get("producer", "N/A"),
        composer=imdb.get("composer", "N/A"), cinematographer=imdb.get("cinematographer", "N/A"), music_team=imdb.get("music_team", "N/A"),
        distributors=imdb.get("distributors", "N/A"), release_date=imdb.get("release_date", "N/A"), year=imdb.get("year", "N/A"),
        genres=imdb.get("genres", "N/A"), poster=imdb.get("poster", "N/A"), plot=imdb.get("plot", "N/A"), rating=imdb.get("rating", "N/A"), url=imdb["url"]
    )
    try:
        if imdb.get("poster"):
            try: await query.message.reply_photo(photo=imdb["poster"], caption=caption, reply_markup=InlineKeyboardMarkup(buttons))
            except Exception: await query.message.reply_photo(photo=imdb["poster"].replace(".jpg", "._V1_UX360.jpg"), caption=caption, reply_markup=InlineKeyboardMarkup(buttons))
            await query.message.delete()
        else:
            await query.message.edit(caption, reply_markup=InlineKeyboardMarkup(buttons), disable_web_page_preview=False)
    except Exception:
        await query.message.edit(caption, disable_web_page_preview=False)
    await query.answer()
