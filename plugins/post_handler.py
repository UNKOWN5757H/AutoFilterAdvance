import asyncio
import logging
import re

from pyrogram import Client, filters
from pyrogram.enums import ButtonStyle
from pyrogram.errors import ButtonUrlInvalid, MessageNotModified, MessageTooLong
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from info import ABOVE_PREVIEW, ADMINS, MOVIE_UPDATE_CHANNEL
from plugins.Imdbposter import get_movie_detailsx
from utils import temp

logger = logging.getLogger(__name__)
post_sessions = {}
USE_GETFILE_BUTTON_BY_DEFAULT = True
DEFAULT_WATERMARK = (
    "Join [Sandalwood New Movies](https://t.me/sandalwood_kannada_moviesz)"
)

TEMPLATES = {
    "clean_grid": """✅ <b>{title} ({year})</b>\n\n<blockquote><b>🔊 : {LANGUAGES}</b>\n<b>🖥️ : {RESOLUTIONS}</b>\n<b>🎥 : {genres}</b>\n<b>📺 : #{OTT_PLATFORMS}</b>\n<b>📟 : Available In Files.</b>\n\n<b>=========================</b></blockquote>""",
    "divider_list": """🎬 <b>{title} ({year})</b>\n━━━━━━━━━━━━━━━━━━\n<blockquote><b>🔊 : {LANGUAGES}</b>\n<b>🖥️ : {RESOLUTIONS}</b>\n<b>📺 : {OTT_PLATFORMS}</b></blockquote>""",
}

LANGUAGES = [
    "Kannada",
    "English",
    "Hindi",
    "Malayalam",
    "Tamil",
    "Telugu",
    "#NotAvailable",
]
RESOLUTIONS = [
    "480p",
    "720p",
    "1080p",
    "2160p",
    "4K",
    "WEB-DL",
    "HDRip",
    "HEVC",
    "#NotAvailable",
]
GENRES = [
    "Action",
    "Adventure",
    "Animation",
    "Comedy",
    "Crime",
    "Drama",
    "Fantasy",
    "Horror",
    "Romance",
    "Sci-Fi",
    "Thriller",
    "#NotAvailable",
]
OTT_PLATFORMS = [
    "Aha",
    "JioHotstar",
    "JioCinema",
    "SonyLIV",
    "Zee5",
    "Amazon Prime Video",
    "Netflix",
    "NotAvailable",
]


class SafeDict(dict):
    def __missing__(self, key):
        return "{" + key + "}"


@Client.on_message(filters.command("post") & filters.user(ADMINS), group=-4)
async def post_command(client: Client, message: Message):
    if len(message.command) == 1:
        return await message.reply_text("Usage: `/post The Dark Knight`")
    movie_name = " ".join(message.command[1:])
    movie_details = await get_movie_detailsx(movie_name)

    if not movie_details:
        return await message.reply_text("Could not fetch details for the movie.")

    if message.from_user.id in post_sessions and post_sessions[
        message.from_user.id
    ].get("last_preview_message_id"):
        try:
            await client.delete_messages(
                message.chat.id,
                post_sessions[message.from_user.id]["last_preview_message_id"],
            )
        except Exception:
            pass

    post_sessions[message.from_user.id] = {
        "movie_name": movie_name,
        "caption": None,
        "is_manual_caption": False,
        "buttons": [],
        "photo_mode": False,
        "use_landscape": bool(movie_details.get("backdrop_url")),
        "custom_languages": [],
        "custom_resolutions": [],
        "custom_genres": [],
        "custom_otts": [],
        "last_preview_message_id": None,
        "original_message_id": message.id,
        "custom_poster": None,
        "watermark": DEFAULT_WATERMARK,
        "lang_format": "<b>🔊 : {langs}</b>",
        "ott_format": "\n<b>📺 : #{otts}</b>",
        "gen_format": "\n<b>🎥 : {genres}</b>",
        "res_format": "\n<b>🖥️ : {resolutions}</b>",
        "active_template": "clean_grid",
        "movie_details": movie_details,
    }

    url = (
        f"https://telegram.me/{temp.U_NAME}?start=search_{movie_name.replace(' ', '_')}"
    )
    post_sessions[message.from_user.id]["buttons"].append(
        [InlineKeyboardButton(text="Direct Search 🔎", url=url)]
    )

    await update_post_preview(
        client, message.from_user.id, message.chat.id, force_resend=True
    )


async def _build_final_post_content(session: dict, session_id: int):
    movie_details = session["movie_details"]
    template_str = TEMPLATES.get(
        session.get("active_template"), TEMPLATES["clean_grid"]
    )

    langs_str = ", ".join(session.get("custom_languages", [])) or "N/A"
    res_str = ", ".join(session.get("custom_resolutions", [])) or "N/A"
    genres_str = ", ".join(session.get("custom_genres", [])) or "N/A"
    otts_str = ", ".join(session.get("custom_otts", [])) or "N/A"

    if not session.get("is_manual_caption"):
        format_args = SafeDict(
            title=str(movie_details.get("title", "N/A")),
            year=str(movie_details.get("year", "N/A")),
            rating=str(movie_details.get("rating", "N/A")),
            plot=str(movie_details.get("plot", "N/A")),
            LANGUAGES=langs_str,
            RESOLUTIONS=res_str,
            GENRES=genres_str,
            OTT_PLATFORMS=otts_str,
            langs=langs_str,
            resolutions=res_str,
            genres=genres_str,
            otts=otts_str,
        )
        base_caption = template_str.format_map(format_args)
    else:
        base_caption = session.get("caption", "")

    if session.get("watermark"):
        base_caption += f"\n\n{session['watermark']}"

    keyboard = build_keyboard(session, session_id)
    poster_to_use = session.get("custom_poster") or (
        movie_details.get("backdrop_url")
        if session.get("use_landscape")
        else movie_details.get("poster_url")
    )
    return base_caption, keyboard, poster_to_use


def build_keyboard(session: dict, session_id: int):
    rows = session.get("buttons", []).copy()
    rows.extend(
        [
            [
                InlineKeyboardButton(
                    "✏️ Buttons", callback_data=f"post:buttons_menu:{session_id}"
                ),
                InlineKeyboardButton(
                    "✏️ Caption", callback_data=f"post:edit_caption:{session_id}"
                ),
            ],
            [
                InlineKeyboardButton(
                    "🖼️ Poster", callback_data=f"post:set_poster:{session_id}"
                ),
                InlineKeyboardButton(
                    "✨ Templates", callback_data=f"post:templates:{session_id}"
                ),
                InlineKeyboardButton(
                    "💧 Watermark", callback_data=f"post:set_watermark:{session_id}"
                ),
            ],
            [
                InlineKeyboardButton(
                    "🔊", callback_data=f"post:languages:{session_id}"
                ),
                InlineKeyboardButton(
                    "🖥️", callback_data=f"post:resolutions:{session_id}"
                ),
                InlineKeyboardButton("🎥", callback_data=f"post:genres:{session_id}"),
                InlineKeyboardButton("📺", callback_data=f"post:otts:{session_id}"),
            ],
            [
                InlineKeyboardButton(
                    f"Mode: {'Photo' if session['photo_mode'] else 'Text'}",
                    callback_data=f"post:toggle_preview:{session_id}",
                ),
                InlineKeyboardButton(
                    f"Poster: {'Landscape' if session['use_landscape'] else 'Portrait'}",
                    callback_data=f"post:toggle_poster:{session_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    "✅ Post", callback_data=f"post:finalize:{session_id}"
                ),
                InlineKeyboardButton(
                    "❌ Cancel", callback_data=f"post:cancel:{session_id}"
                ),
            ],
        ]
    )
    return InlineKeyboardMarkup(rows)


async def update_post_preview(
    client: Client, session_id: int, chat_id: int, force_resend: bool = False
):
    session = post_sessions.get(session_id)
    if not session:
        return

    final_caption, keyboard, poster_to_use = await _build_final_post_content(
        session, session_id
    )
    if not final_caption:
        return

    if not session["last_preview_message_id"] or force_resend:
        if session["last_preview_message_id"]:
            try:
                await client.delete_messages(
                    chat_id, session["last_preview_message_id"]
                )
            except Exception:
                pass
        if session["photo_mode"] and poster_to_use:
            sent_message = await client.send_photo(
                chat_id,
                photo=poster_to_use,
                caption=final_caption,
                reply_markup=keyboard,
            )
        else:
            sent_message = await client.send_message(
                chat_id,
                (
                    f"<a href='{poster_to_use}'>&#8205;</a>{final_caption}"
                    if poster_to_use
                    else final_caption
                ),
                reply_markup=keyboard,
            )
        session["last_preview_message_id"] = sent_message.id
    else:
        try:
            if session["photo_mode"] and poster_to_use:
                await client.edit_message_caption(
                    chat_id,
                    session["last_preview_message_id"],
                    caption=final_caption,
                    reply_markup=keyboard,
                )
            else:
                await client.edit_message_text(
                    chat_id,
                    session["last_preview_message_id"],
                    (
                        f"<a href='{poster_to_use}'>&#8205;</a>{final_caption}"
                        if poster_to_use
                        else final_caption
                    ),
                    reply_markup=keyboard,
                )
        except Exception:
            pass


@Client.on_callback_query(filters.regex(r"^post:"), group=-4)
async def post_callbacks(client: Client, query: CallbackQuery):
    data_parts = query.data.split(":")
    action, session_id = data_parts[1], int(data_parts[2])
    extra_data = data_parts[3:]

    if query.from_user.id != session_id:
        return await query.answer("This is not for you!", show_alert=True)
    session = post_sessions.get(session_id)
    if not session:
        return await query.answer("Session expired.", show_alert=True)

    force_resend = False
    await query.answer()

    if action in ["languages", "resolutions", "genres", "otts"]:
        return await show_selection_menu(query, session_id, action)

    elif action in ["select_lang", "select_res", "select_gen", "select_ott"]:
        item = extra_data[0]
        t_map = {
            "select_lang": ("custom_languages", "languages"),
            "select_res": ("custom_resolutions", "resolutions"),
            "select_gen": ("custom_genres", "genres"),
            "select_ott": ("custom_otts", "otts"),
        }
        lst, ret = t_map[action]
        if item in session[lst]:
            session[lst].remove(item)
        else:
            session[lst].append(item)
        return await show_selection_menu(query, session_id, ret)

    elif action == "edit_buttons":
        ask_msg = await query.message.reply_text(
            "Send the button layout. Format:\n`Btn 1 - URL1 | Btn 2 - URL2`"
        )
        try:
            response = await client.listen(
                chat_id=query.message.chat.id,
                filters=filters.user(query.from_user.id),
                timeout=60,
            )
            new_layout = []
            for row_str in response.text.strip().split("\n"):
                row_btns = []
                for btn_str in row_str.split("|"):
                    if " - " in btn_str:
                        text, url = btn_str.split(" - ", 1)
                        row_btns.append(
                            InlineKeyboardButton(text.strip(), url=url.strip())
                        )
                if row_btns:
                    new_layout.append(row_btns)
            session["buttons"] = new_layout
            await response.delete()
            await ask_msg.delete()
        except asyncio.TimeoutError:
            await ask_msg.delete()

    elif action == "edit_caption":
        ask_msg = await query.message.reply_text("Send the new caption text.")
        try:
            response = await client.listen(
                chat_id=query.message.chat.id,
                filters=filters.user(query.from_user.id),
                timeout=60,
            )
            session["caption"] = response.text
            session["is_manual_caption"] = True
            await response.delete()
            await ask_msg.delete()
        except asyncio.TimeoutError:
            await ask_msg.delete()

    elif action == "toggle_preview":
        session["photo_mode"] = not session["photo_mode"]
        force_resend = True

    elif action == "toggle_poster":
        session["use_landscape"] = not session["use_landscape"]
        force_resend = True

    elif action == "finalize":
        final_caption, _, poster_to_use = await _build_final_post_content(
            session, session_id
        )
        final_keyboard = (
            InlineKeyboardMarkup(session["buttons"]) if session["buttons"] else None
        )

        try:
            await client.delete_messages(
                query.message.chat.id, session["last_preview_message_id"]
            )
        except Exception:
            pass

        if session["photo_mode"] and poster_to_use:
            await client.send_photo(
                MOVIE_UPDATE_CHANNEL,
                photo=poster_to_use,
                caption=final_caption,
                reply_markup=final_keyboard,
            )
        else:
            await client.send_message(
                MOVIE_UPDATE_CHANNEL,
                text=(
                    f"<a href='{poster_to_use}'>&#8205;</a>{final_caption}"
                    if poster_to_use
                    else final_caption
                ),
                reply_markup=final_keyboard,
            )

        post_sessions.pop(session_id, None)
        return await query.message.reply_text("✅ Post sent to update channel.")

    elif action == "cancel":
        try:
            await client.delete_messages(
                query.message.chat.id, session["last_preview_message_id"]
            )
        except Exception:
            pass
        post_sessions.pop(session_id, None)
        return await query.message.reply_text("Post cancelled.")

    await update_post_preview(client, session_id, query.message.chat.id, force_resend)


async def show_selection_menu(query: CallbackQuery, session_id: int, menu_type: str):
    session = post_sessions[session_id]
    m_map = {
        "languages": (LANGUAGES, "custom_languages", "select_lang"),
        "resolutions": (RESOLUTIONS, "custom_resolutions", "select_res"),
        "genres": (GENRES, "custom_genres", "select_gen"),
        "otts": (OTT_PLATFORMS, "custom_otts", "select_ott"),
    }
    items, selected, action_prefix = m_map[menu_type]

    buttons = [
        InlineKeyboardButton(
            f"✅ {i}" if i in session[selected] else i,
            callback_data=f"post:{action_prefix}:{session_id}:{i}",
        )
        for i in items
    ]
    keyboard = [buttons[i : i + 3] for i in range(0, len(buttons), 3)]
    keyboard.append(
        [InlineKeyboardButton("✅ Done", callback_data=f"post:back:{session_id}")]
    )
    await query.edit_message_reply_markup(InlineKeyboardMarkup(keyboard))
