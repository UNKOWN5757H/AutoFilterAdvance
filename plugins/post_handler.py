import asyncio
import logging
import re
from pyrogram import Client, filters
from pyrogram.enums import ButtonStyle
from pyrogram.errors import ButtonUrlInvalid, MessageNotModified, MessageTooLong
from pyrogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from info import ADMINS, MOVIE_UPDATE_CHANNEL
from plugins.Imdbposter import get_movie_detailsx
from utils import temp

logger = logging.getLogger(__name__)
post_sessions = {}
USE_GETFILE_BUTTON_BY_DEFAULT = True

class SafeDict(dict):
    def __missing__(self, key): return "{" + key + "}"

@Client.on_message(filters.command("post") & filters.user(ADMINS), group=-4)
async def post_command(client: Client, message: Message):
    if len(message.command) == 1: return await message.reply_text("Usage: `/post The Dark Knight`")
    movie_name = " ".join(message.command[1:])
    
    movie_details = await get_movie_detailsx(movie_name)
    if not movie_details: return await message.reply_text("❌ Could not fetch details for the movie.")

    if message.from_user.id in post_sessions and post_sessions[message.from_user.id].get("last_preview_message_id"):
        try: await client.delete_messages(message.chat.id, post_sessions[message.from_user.id]["last_preview_message_id"])
        except Exception: pass

    post_sessions[message.from_user.id] = {
        "movie_name": movie_name, "caption": None, "is_manual_caption": False, "buttons": [],
        "photo_mode": False, "use_landscape": bool(movie_details.get("backdrop_url")),
        "custom_languages": [], "custom_resolutions": [], "custom_genres": [], "custom_otts": [],
        "last_preview_message_id": None, "original_message_id": message.id, "custom_poster": None,
        "watermark": "Join [Sandalwood New Movies](https://t.me/sandalwood_kannada_moviesz)",
        "lang_format": "<b>🔊 : {langs}</b>", "ott_format": "\n<b>📺 : #{otts}</b>",
        "gen_format": "\n<b>🎥 : {genres}</b>", "res_format": "\n<b>🖥️ : {resolutions}</b>",
        "active_template": "clean_grid", "movie_details": movie_details,
    }

    if USE_GETFILE_BUTTON_BY_DEFAULT:
        url = f"https://telegram.me/{temp.U_NAME}?start=search_{movie_name.replace(' ', '_')}"
        post_sessions[message.from_user.id]["buttons"].append([InlineKeyboardButton(text="Direct Search 🔎", url=url)])

    await update_post_preview(client, message.from_user.id, message.chat.id, force_resend=True)

async def _build_final_post_content(session: dict, session_id: int):
    movie_details = session["movie_details"]
    if not movie_details: return None, None, None

    template_str = "✅ <b>{title} ({year})</b>\n\n<blockquote><b>🔊 : {LANGUAGES}</b>\n<b>🖥️ : {RESOLUTIONS}</b>\n<b>🎥 : {genres}</b>\n<b>📺 : #{OTT_PLATFORMS}</b>\n<b>📟 : Available In Files.</b>\n\n<b>=========================</b></blockquote>"
    
    langs_str = ", ".join(session.get("custom_languages", [])) or "N/A"
    res_str = ", ".join(session.get("custom_resolutions", [])) or "N/A"
    genres_str = ", ".join(session.get("custom_genres", [])) or "N/A"
    otts_str = ", ".join(session.get("custom_otts", [])) or "N/A"

    if not session.get("is_manual_caption"):
        format_args = SafeDict(
            title=str(movie_details.get("title", "N/A")), year=str(movie_details.get("year", "N/A")),
            rating=str(movie_details.get("rating", "N/A")), plot=str(movie_details.get("plot", "N/A")),
            LANGUAGES=langs_str, RESOLUTIONS=res_str, GENRES=genres_str, OTT_PLATFORMS=otts_str,
            langs=langs_str, resolutions=res_str, genres=genres_str, otts=otts_str
        )
        base_caption = template_str.format_map(format_args)
    else:
        base_caption = session.get("caption", "")

    if session.get("watermark"): base_caption += f"\n\n{session['watermark']}"

    keyboard = InlineKeyboardMarkup(session["buttons"]) if session["buttons"] else None
    poster_to_use = session.get("custom_poster") or (movie_details.get("backdrop_url") if session.get("use_landscape") else movie_details.get("poster_url"))
    
    return base_caption, keyboard, poster_to_use

async def update_post_preview(client: Client, session_id: int, chat_id: int, force_resend: bool = False):
    session = post_sessions.get(session_id)
    if not session: return

    try:
        final_caption, keyboard, poster_to_use = await _build_final_post_content(session, session_id)
        if not final_caption: return
        
        if force_resend or not session["last_preview_message_id"]:
            if session["last_preview_message_id"]:
                try: await client.delete_messages(chat_id, session["last_preview_message_id"])
                except Exception: pass

            if session["photo_mode"] and poster_to_use:
                sent_msg = await client.send_photo(chat_id, photo=poster_to_use, caption=final_caption, reply_markup=keyboard)
            else:
                sent_msg = await client.send_message(chat_id, f"<a href='{poster_to_use}'>&#8205;</a>{final_caption}" if poster_to_use else final_caption, reply_markup=keyboard)
            session["last_preview_message_id"] = sent_msg.id
        else:
            if session["photo_mode"] and poster_to_use:
                await client.edit_message_caption(chat_id, session["last_preview_message_id"], caption=final_caption, reply_markup=keyboard)
            else:
                await client.edit_message_text(chat_id, session["last_preview_message_id"], f"<a href='{poster_to_use}'>&#8205;</a>{final_caption}" if poster_to_use else final_caption, reply_markup=keyboard)
    except Exception as e: logger.error(f"Post Update Error: {e}")
