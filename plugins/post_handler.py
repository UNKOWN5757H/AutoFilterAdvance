import asyncio
import html
import logging
import re
import traceback

from pyrogram import Client, filters
from pyrogram.enums import ButtonStyle  # ⚡ RESTORED: ButtonStyle import
from pyrogram.errors import ButtonUrlInvalid, MessageNotModified, MessageTooLong
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

import info
from info import ADMINS, MOVIE_UPDATE_CHANNEL
from plugins.Imdbposter import get_movie_detailsx
from utils import temp

logger = logging.getLogger(__name__)
post_sessions = {}

USE_GETFILE_BUTTON_BY_DEFAULT = True

DEFAULT_WATERMARK = (
    "<b>Jᴏɪɴ: @Sandalwood_Kannada_Moviesz</b>"
)
LANGUAGES_FORMAT = "<b>🔊 : {langs}</b>"
RESOLUTIONS_FORMAT = "\n<b>🖥️ : {resolutions}</b>"
GENRES_FORMAT = "\n<b>🎥 : {genres}</b>"
OTT_FORMAT = "\n<b>📺 : #{otts}</b>"

TEMPLATES = {
    "clean_grid": """✅ <b>{title} {year}</b>\n\n<blockquote><b>🔊 : {LANGUAGES}</b>\n<b>🖥️ : {RESOLUTIONS}</b>\n<b>🎥 : {genres}</b>\n<b>📺 : #{OTT_PLATFORMS}</b>\n<b>📟 : Available In Files.</b>\n\n<b>=========================</b></blockquote>""",
    "divider_list": """🎬 <b>{title} {year}</b>\n━━━━━━━━━━━━━━━━━━\n<blockquote><b>🔊 : {LANGUAGES}</b>\n<b>🖥️ : {RESOLUTIONS}</b>\n<b>📺 : {OTT_PLATFORMS}</b></blockquote>""",
}

LANGUAGES = [
    "Kannada",
    "English",
    "Gujarati",
    "Hindi",
    "Bengali",
    "Malayalam",
    "Marathi",
    "Punjabi",
    "Tamil",
    "Telugu",
    "Urdu",
    "Arabic",
    "French",
    "German",
    "Italian",
    "Japanese",
    "Korean",
    "Mandarin",
    "Portuguese",
    "Russian",
    "Spanish",
    "#NotAvailable",
]
RESOLUTIONS = [
    "144p",
    "240p",
    "480p",
    "720p",
    "1080p",
    "1440p",
    "2160p",
    "4320p",
    "BluRay",
    "BDRip",
    "WEB-DL",
    "HDRip",
    "WEBRip",
    "HDTVRip",
    "DVDRip",
    "DVDScr",
    "TSRip",
    "CAMRip",
    "HDTC",
    "HEVC",
    "#NotAvailable",
]
GENRES = [
    "Action",
    "Adventure",
    "Animation",
    "Biography",
    "Comedy",
    "Crime",
    "Documentary",
    "Drama",
    "Family",
    "Fantasy",
    "History",
    "Horror",
    "Music",
    "Musical",
    "Mystery",
    "Romance",
    "Sci-Fi",
    "Sport",
    "Thriller",
    "War",
    "Western",
    "Superhero",
    "Psychological",
    "Suspense",
    "Noir",
    "Disaster",
    "Survival",
    "Teen",
    "Slice of Life",
    "Coming of Age",
    "Martial Arts",
    "Political",
    "Legal",
    "Medical",
    "Spy",
    "Erotic",
    "Mythology",
    "Short",
    "Experimental",
    "#NotAvailable",
]
OTT_PLATFORMS = [
    "Aha",
    "ALTBalaji",
    "JioHotstar",
    "ErosNow",
    "Hoichoi",
    "JioCinema",
    "MXPlayer",
    "SonyLIV",
    "SunNXT",
    "Voot",
    "Zee5",
    "AmazonPrime",
    "AppleTV+",
    "Crunchyroll",
    "Discovery+",
    "HBO Max",
    "Hulu",
    "Netflix",
    "Paramount+",
    "Peacock",
    "ManoramaMAX",
    "NotAvailable",
]


try:
    ADMIN_LIST = [int(a) for a in info.ADMINS]
except Exception:
    ADMIN_LIST = []


# Safe Admin Filter
async def admin_check(_, __, message: Message):
    if not message.from_user:
        return False
    return (
        message.from_user.id in info.ADMINS or str(message.from_user.id) in info.ADMINS
    )


admin_filter = filters.create(admin_check)


@Client.on_message(filters.command("post") & filters.user(ADMIN_LIST), group=-4)
async def post_command(client: Client, message: Message):
    try:
        if len(message.command) == 1:
            return await message.reply_text(
                "Please provide a movie name. Usage: `/post The Dark Knight`"
            )

        movie_name = " ".join(message.command[1:])
        user_id = message.from_user.id

        await start_post_session(client, message, user_id, movie_name)
    except Exception as e:
        await message.reply_text(f"❌ **COMMAND ERROR:**\n`{e}`")


# ============================================================
# 🔗 EDIT DIRECT URL COMMAND
# ============================================================
@Client.on_message(filters.command("editdirect") & filters.user(ADMIN_LIST), group=-4)
async def edit_direct_url(client: Client, message: Message):
    user_id = message.from_user.id
    if user_id not in post_sessions:
        return await message.reply_text(
            "❌ You don't have an active post session right now."
        )

    if len(message.command) < 2:
        return await message.reply_text(
            "❌ Please provide a URL.\n\n**Usage:** `/editdirect https://t.me/your_bot?start=custom_link`"
        )

    new_url = message.command[1]
    session = post_sessions[user_id]

    button_updated = False

    if session.get("buttons"):
        for row in session["buttons"]:
            for btn in row:
                if btn.text == "Direct Search 🔎":
                    btn.url = new_url
                    button_updated = True

    if button_updated:
        await message.reply_text(
            f"✅ **'Direct Search' button URL updated successfully!**\n\n🔗 **New URL:** `{new_url}`"
        )
        # Refresh the preview to show the changes immediately
        await update_post_preview(client, user_id, message.chat.id, force_resend=False)
    else:
        await message.reply_text(
            "❌ **Button not found!** Ensure you have the 'Direct Search 🔎' button added to your layout first."
        )


async def start_post_session(
    client: Client, message: Message, user_id: int, movie_name: str
):
    try:
        status_msg = await message.reply_text("⏳ Fetching movie details...")

        movie_details = await get_movie_detailsx(movie_name)
        if not movie_details:
            return await status_msg.edit_text(
                "❌ Could not fetch details for the movie from TMDB."
            )

        if user_id in post_sessions and post_sessions[user_id].get(
            "last_preview_message_id"
        ):
            try:
                await client.delete_messages(
                    message.chat.id, post_sessions[user_id]["last_preview_message_id"]
                )
            except Exception:
                pass

        post_sessions[user_id] = {
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
            "last_preview_message_id": status_msg.id,
            "original_message_id": message.id,
            "custom_poster": None,
            "watermark": DEFAULT_WATERMARK,
            "lang_format": LANGUAGES_FORMAT,
            "ott_format": OTT_FORMAT,
            "gen_format": GENRES_FORMAT,
            "res_format": RESOLUTIONS_FORMAT,
            "active_template": "clean_grid",
            "movie_details": movie_details,
        }

        if USE_GETFILE_BUTTON_BY_DEFAULT:
            await handle_add_get_files(client, post_sessions[user_id])

        await update_post_preview(client, user_id, message.chat.id, force_resend=True)
    except Exception as e:
        await message.reply_text(f"❌ **SESSION ERROR:**\n`{e}`")


class SafeDict(dict):
    def __missing__(self, key):
        return "{" + key + "}"


async def _build_final_post_content(session: dict, session_id: int):
    movie_details = session["movie_details"]
    if not movie_details:
        return None, None, None

    template_str = TEMPLATES.get(
        session.get("active_template"), TEMPLATES["clean_grid"]
    )

    langs_str = ", ".join(session.get("custom_languages", [])) or "N/A"
    res_str = ", ".join(session.get("custom_resolutions", [])) or "N/A"
    genres_str = ", ".join(session.get("custom_genres", [])) or "N/A"
    otts_str = ", ".join(session.get("custom_otts", [])) or "N/A"

    rating_str = (
        html.escape(str(movie_details.get("rating", "N/A")))
        .replace("{", "(")
        .replace("}", ")")
    )
    plot_str = (
        html.escape(str(movie_details.get("plot", "N/A")))
        .replace("{", "(")
        .replace("}", ")")
    )
    clean_title = (
        html.escape(str(movie_details.get("title", "N/A")))
        .replace("{", "(")
        .replace("}", ")")
        .replace("[", "")
        .replace("]", "")
    )
    clean_year = (
        html.escape(str(movie_details.get("year", "N/A")))
        .replace("{", "(")
        .replace("}", ")")
        .replace("[", "")
        .replace("]", "")
    )

    if not session.get("is_manual_caption"):
        format_args = SafeDict(
            title=clean_title,
            year=clean_year,
            rating=rating_str,
            plot=plot_str,
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

    final_caption = base_caption

    if (
        session.get("custom_languages")
        and "{LANGUAGES}" not in template_str
        and "{langs}" not in template_str
    ):
        final_caption += "\n" + session["lang_format"].format_map(
            SafeDict(langs=langs_str, LANGUAGES=langs_str)
        )
    if (
        session.get("custom_resolutions")
        and "{RESOLUTIONS}" not in template_str
        and "{resolutions}" not in template_str
    ):
        final_caption += session["res_format"].format_map(
            SafeDict(resolutions=res_str, RESOLUTIONS=res_str)
        )
    if (
        session.get("custom_genres")
        and "{GENRES}" not in template_str
        and "{genres}" not in template_str
    ):
        final_caption += session["gen_format"].format_map(
            SafeDict(genres=genres_str, GENRES=genres_str)
        )
    if (
        session.get("custom_otts")
        and "{OTT_PLATFORMS}" not in template_str
        and "{otts}" not in template_str
    ):
        final_caption += session["ott_format"].format_map(
            SafeDict(otts=otts_str, OTT_PLATFORMS=otts_str)
        )
    if session.get("watermark"):
        final_caption += f"\n\n{session['watermark']}"

    keyboard = build_keyboard(session, session_id)
    poster_to_use = session.get("custom_poster") or (
        movie_details.get("backdrop_url")
        if session.get("use_landscape")
        else movie_details.get("poster_url")
    )

    return final_caption, keyboard, poster_to_use


async def update_post_preview(
    client: Client, session_id: int, chat_id: int, force_resend: bool = False
):
    session = post_sessions.get(session_id)
    if not session:
        return

    is_new = not session.get("last_preview_message_id")

    if is_new or force_resend:
        if not is_new:
            try:
                await client.delete_messages(
                    chat_id, session["last_preview_message_id"]
                )
            except Exception:
                pass
        try:
            status_msg = await client.send_message(
                chat_id,
                "<i>Generating preview...</i>",
                reply_to_message_id=session["original_message_id"],
            )
            session["last_preview_message_id"] = status_msg.id
        except Exception:
            try:
                status_msg = await client.send_message(
                    chat_id, "<i>Generating preview...</i>"
                )
                session["last_preview_message_id"] = status_msg.id
            except Exception:
                return

    try:
        final_caption, keyboard, poster_to_use = await _build_final_post_content(
            session, session_id
        )
    except Exception as e:
        try:
            await client.send_message(chat_id, f"❌ **BUILD CONTENT ERROR:**\n`{e}`")
        except Exception:
            pass
        return

    if not final_caption:
        try:
            return await client.edit_message_text(
                chat_id,
                session["last_preview_message_id"],
                "Could not format details for this movie.",
            )
        except Exception:
            return

    try:
        if session["photo_mode"] and poster_to_use:
            if force_resend:
                old_msg_id = session.get("last_preview_message_id")
                sent_message = await client.send_photo(
                    chat_id,
                    photo=poster_to_use,
                    caption=final_caption,
                    reply_markup=keyboard,
                    reply_to_message_id=session["original_message_id"],
                )
                session["last_preview_message_id"] = sent_message.id
                if old_msg_id:
                    try:
                        await client.delete_messages(chat_id, old_msg_id)
                    except Exception:
                        pass
            else:
                await client.edit_message_caption(
                    chat_id,
                    session["last_preview_message_id"],
                    caption=final_caption,
                    reply_markup=keyboard,
                )
        else:
            text_content = (
                f"<a href='{poster_to_use}'>&#8205;</a>{final_caption}"
                if poster_to_use
                else final_caption
            )
            if force_resend:
                old_msg_id = session.get("last_preview_message_id")
                sent_message = await client.send_message(
                    chat_id,
                    text_content,
                    reply_markup=keyboard,
                    reply_to_message_id=session["original_message_id"],
                )
                session["last_preview_message_id"] = sent_message.id
                if old_msg_id:
                    try:
                        await client.delete_messages(chat_id, old_msg_id)
                    except Exception:
                        pass
            else:
                await client.edit_message_text(
                    chat_id,
                    session["last_preview_message_id"],
                    text_content,
                    reply_markup=keyboard,
                    disable_web_page_preview=False,
                )
    except Exception as e:
        try:
            await client.send_message(chat_id, f"❌ **PREVIEW SEND ERROR:**\n`{e}`")
        except Exception:
            pass


def build_keyboard(session: dict, session_id: int):
    rows = []
    if session.get("buttons"):
        rows.extend(session["buttons"])
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


@Client.on_callback_query(filters.regex(r"^post:"), group=-4)
async def post_callbacks(client: Client, query: CallbackQuery):
    try:
        data_parts = query.data.split(":")
        action = data_parts[1]

        try:
            session_id = int(data_parts[2])
        except ValueError:
            return await query.answer("Invalid Session ID.", show_alert=True)

        extra_data = data_parts[3:]

        if query.from_user.id != session_id:
            return await query.answer("This is not for you!", show_alert=True)

        session = post_sessions.get(session_id)
        if not session:
            await query.answer("Session expired or was cancelled.", show_alert=True)
            try:
                return await query.message.delete()
            except Exception:
                return

        force_resend = False

        if action == "back":
            await query.answer()

        elif action in [
            "languages",
            "resolutions",
            "templates",
            "buttons_menu",
            "remove_buttons_menu",
            "genres",
            "otts",
        ]:
            await query.answer()
            if action == "languages":
                await show_selection_menu(query, session_id, "languages")
            elif action == "resolutions":
                await show_selection_menu(query, session_id, "resolutions")
            elif action == "genres":
                await show_selection_menu(query, session_id, "genres")
            elif action == "otts":
                await show_selection_menu(query, session_id, "otts")
            elif action == "templates":
                await handle_templates_menu(query, session_id)
            elif action == "buttons_menu":
                await handle_buttons_menu(query, session_id)
            elif action == "remove_buttons_menu":
                await handle_remove_buttons_menu(query, session_id)
            return

        elif action in ["select_lang", "select_res", "select_gen", "select_ott"]:
            await query.answer()
            item = extra_data[0]
            if action == "select_lang":
                if item not in session["custom_languages"]:
                    session["custom_languages"].append(item)
                else:
                    session["custom_languages"].remove(item)
                await show_selection_menu(query, session_id, "languages")
            elif action == "select_res":
                if item not in session["custom_resolutions"]:
                    session["custom_resolutions"].append(item)
                else:
                    session["custom_resolutions"].remove(item)
                await show_selection_menu(query, session_id, "resolutions")
            elif action == "select_gen":
                if item not in session["custom_genres"]:
                    session["custom_genres"].append(item)
                else:
                    session["custom_genres"].remove(item)
                await show_selection_menu(query, session_id, "genres")
            elif action == "select_ott":
                if item not in session["custom_otts"]:
                    session["custom_otts"].append(item)
                else:
                    session["custom_otts"].remove(item)
                await show_selection_menu(query, session_id, "otts")
            return

        else:
            if action == "edit_buttons":
                await handle_edit_buttons(client, query, session_id)
                return
            elif action == "add_get_files":
                added = await handle_add_get_files(client, session)
                await query.answer(
                    (
                        "✅ 'Get Files' button added!"
                        if added
                        else "⚠️ Button already exists!"
                    ),
                    show_alert=not added,
                )
            elif action == "edit_caption":
                await handle_edit_caption(client, query, session_id)
                return
            elif action == "set_poster":
                await handle_set_poster(client, query, session_id)
                force_resend = True
                return
            elif action == "remove_button":
                await handle_remove_button(session, extra_data)
                await handle_remove_buttons_menu(query, session_id)
                return
            elif action == "select_template":
                await handle_select_template(session, extra_data[0])
            elif action == "toggle_preview":
                force_resend = await handle_toggle_preview(query, session)
            elif action == "toggle_poster":
                force_resend = await handle_toggle_poster(session)
            elif action == "set_watermark":
                await handle_set_watermark(client, query, session_id)
                return
            elif action == "format_lang":
                await handle_format_lang(client, query, session_id)
                return
            elif action == "format_res":
                await handle_format_res(client, query, session_id)
                return
            elif action == "format_gen":
                await handle_format_gen(client, query, session_id)
                return
            elif action == "format_ott":
                await handle_format_ott(client, query, session_id)
                return
            elif action == "finalize":
                return await finalize_and_post(client, query, session_id)
            elif action == "cancel":
                return await handle_cancel(client, query, session_id)

        await update_post_preview(
            client, session_id, query.message.chat.id, force_resend
        )
    except Exception as e:
        await query.message.reply_text(f"❌ **CALLBACK ERROR:**\n`{e}`")


async def show_selection_menu(query: CallbackQuery, session_id: int, menu_type: str):
    session = post_sessions[session_id]

    if menu_type == "languages":
        items, selected, action_prefix, format_action = (
            LANGUAGES,
            session["custom_languages"],
            "select_lang",
            "format_lang",
        )
    elif menu_type == "resolutions":
        items, selected, action_prefix, format_action = (
            RESOLUTIONS,
            session["custom_resolutions"],
            "select_res",
            "format_res",
        )
    elif menu_type == "genres":
        items, selected, action_prefix, format_action = (
            GENRES,
            session["custom_genres"],
            "select_gen",
            "format_gen",
        )
    elif menu_type == "otts":
        items, selected, action_prefix, format_action = (
            OTT_PLATFORMS,
            session["custom_otts"],
            "select_ott",
            "format_ott",
        )
    else:
        return

    buttons = [
        InlineKeyboardButton(
            f"✅ {i}" if i in selected else i,
            callback_data=f"post:{action_prefix}:{session_id}:{i}",
        )
        for i in items
    ]
    keyboard = [buttons[i : i + 3] for i in range(0, len(buttons), 3)]
    keyboard.append(
        [
            InlineKeyboardButton(
                "⚙️ Change Format", callback_data=f"post:{format_action}:{session_id}"
            )
        ]
    )
    keyboard.append(
        [InlineKeyboardButton("✅ Done", callback_data=f"post:back:{session_id}")]
    )

    try:
        await query.edit_message_reply_markup(InlineKeyboardMarkup(keyboard))
    except MessageNotModified:
        pass


async def get_user_input(client, query, session, prompt_text):
    try:
        ask_msg = await query.message.reply_text(
            prompt_text, reply_to_message_id=session.get("original_message_id")
        )
    except Exception:
        ask_msg = await query.message.reply_text(prompt_text)

    try:
        response = await client.listen(
            chat_id=query.message.chat.id, user_id=query.from_user.id, timeout=300
        )
        try:
            await ask_msg.delete()
        except Exception:
            pass
        if response:
            try:
                await response.delete()
            except Exception:
                pass
            return response
    except asyncio.TimeoutError:
        try:
            await ask_msg.edit("Timeout (5 minutes). The operation was cancelled.")
            await asyncio.sleep(3)
            await ask_msg.delete()
        except Exception:
            pass
    return None


async def handle_buttons_menu(query, session_id):
    buttons = [
        [
            InlineKeyboardButton(
                "➕ Add/Edit Layout", callback_data=f"post:edit_buttons:{session_id}"
            )
        ],
        [
            InlineKeyboardButton(
                "📥 Add 'Get Files' Button",
                callback_data=f"post:add_get_files:{session_id}",
            )
        ],
        [
            InlineKeyboardButton(
                "🗑️ Remove a Button",
                callback_data=f"post:remove_buttons_menu:{session_id}",
            )
        ],
        [InlineKeyboardButton("Back", callback_data=f"post:back:{session_id}")],
    ]
    try:
        await query.edit_message_reply_markup(InlineKeyboardMarkup(buttons))
    except MessageNotModified:
        pass


async def handle_edit_buttons(client: Client, query: CallbackQuery, session_id: int):
    session = post_sessions[session_id]
    prompt = "Send the button layout. Format:\n`Button 1 - URL1 | Button 2 - URL2` (for same row)\n`Button 3 - URL3` (for new row)"
    response = await get_user_input(client, query, session, prompt)

    if response and response.text:
        new_layout = []
        for row_str in response.text.strip().split("\n"):
            row_btns = []
            for btn_str in row_str.split("|"):
                if " - " in btn_str:
                    text, url = btn_str.split(" - ", 1)
                    clean_url = url.strip()
                    if not clean_url.startswith(("http://", "https://", "tg://")):
                        clean_url = "https://" + clean_url
                    clean_text = (
                        text.replace("[", "")
                        .replace("]", "")
                        .replace("(", "")
                        .replace(")", "")
                        .strip()
                    )
                    row_btns.append(InlineKeyboardButton(clean_text, url=clean_url))
            if row_btns:
                new_layout.append(row_btns)
        session["buttons"] = new_layout
    await update_post_preview(
        client, session_id, query.message.chat.id, force_resend=False
    )


# ============================================================
# 🔗 GENERATES YOUR BUTTONS DYNAMICALLY
# ============================================================
async def handle_add_get_files(client: Client, session: dict) -> bool:
    movie_details = session["movie_details"]
    if movie_details:
        title = (
            str(movie_details.get("title", "movie"))
            .replace("(", "")
            .replace(")", "")
            .replace("[", "")
            .replace("]", "")
        )
        year = (
            str(movie_details.get("year", ""))
            .replace("(", "")
            .replace(")", "")
            .replace("[", "")
            .replace("]", "")
        )
        movie_year = f"{title} {year}".strip()

        safe_query = re.sub(r"[^a-zA-Z0-9_-]", "_", movie_year)
        safe_query = re.sub(r"_+", "_", safe_query).strip("_")
        safe_query = safe_query[:50]

        bot_username = temp.U_NAME or "MovieBot"
        url = f"https://t.me/{bot_username}?start=search_{safe_query}"

        for row in session["buttons"]:
            for btn in row:
                if btn.url == url:
                    return False

        # ⚡ RESTORED: Colored Buttons and Emojis are back!
        session["buttons"].append(
            [
                InlineKeyboardButton(
                    text="Group 1 🎬",
                    url="https://t.me/Sandalwood_Kannada_Group",
                    icon_custom_emoji_id=5258096772776991776,
                    style=ButtonStyle.PRIMARY,
                ),
                InlineKeyboardButton(
                    text="Group 2 🎬",
                    url="https://t.me/+GLsPkRgLGGszMzY1",
                    icon_custom_emoji_id=5258096772776991776,
                    style=ButtonStyle.PRIMARY,
                ),
            ]
        )
        session["buttons"].append(
            [
                InlineKeyboardButton(
                    text="Direct Search 🔎",
                    url=url,
                    icon_custom_emoji_id=5258503720928288433,
                    style=ButtonStyle.SUCCESS,
                )
            ]
        )
        return True
    return False


async def handle_edit_caption(client: Client, query: CallbackQuery, session_id: int):
    session = post_sessions[session_id]
    response = await get_user_input(
        client, query, session, "Send the new caption text."
    )
    if response and response.text:
        session["caption"] = response.text
        session["is_manual_caption"] = True
    await update_post_preview(
        client, session_id, query.message.chat.id, force_resend=False
    )


async def handle_set_poster(client: Client, query: CallbackQuery, session_id: int):
    session = post_sessions[session_id]
    response = await get_user_input(
        client,
        query,
        session,
        "Send a photo or an image URL. Send `/reset` to use the default poster.",
    )
    if response:
        if response.photo:
            session["custom_poster"] = response.photo.file_id
            if not session["photo_mode"]:
                session["photo_mode"] = True
                try:
                    await query.answer(
                        "Switched to Photo mode as you uploaded an image.",
                        show_alert=True,
                    )
                except Exception:
                    pass
        elif response.text and response.text.startswith("http"):
            session["custom_poster"] = response.text
        elif response.text and response.text == "/reset":
            session["custom_poster"] = None
    return True


async def handle_set_watermark(client, query, session_id: int):
    session = post_sessions[session_id]
    prompt_text = "Send the watermark text. HTML is supported.\n\n• Send `/reset` to remove the watermark.\n• Send `/default` to use the default watermark."
    response = await get_user_input(client, query, session, prompt_text)
    if response and response.text:
        if response.text == "/reset":
            session["watermark"] = ""
        elif response.text == "/default":
            session["watermark"] = DEFAULT_WATERMARK
        else:
            session["watermark"] = response.text
    await update_post_preview(
        client, session_id, query.message.chat.id, force_resend=False
    )


async def handle_format_lang(client, query, session_id: int):
    session = post_sessions[session_id]
    response = await get_user_input(
        client,
        query,
        session,
        f"Send the format for languages. Must include `{{langs}}` as a placeholder. Send `/reset` for default.\n\n Current: {html.escape(session['lang_format'])}",
    )
    if response and response.text:
        if response.text == "/reset":
            session["lang_format"] = LANGUAGES_FORMAT
        elif "{langs}" not in response.text:
            try:
                await query.message.reply_text(
                    "⚠️ Invalid format! The format must contain `{langs}` placeholder.",
                    quote=True,
                )
            except Exception:
                pass
        else:
            session["lang_format"] = response.text
    await update_post_preview(
        client, session_id, query.message.chat.id, force_resend=False
    )


async def handle_format_res(client, query, session_id: int):
    session = post_sessions[session_id]
    response = await get_user_input(
        client,
        query,
        session,
        f"Send the format for qualities. Must include `{{resolutions}}` as a placeholder. Send `/reset` for default.\n\n Current: {html.escape(session['res_format'])}",
    )
    if response and response.text:
        if response.text == "/reset":
            session["res_format"] = RESOLUTIONS_FORMAT
        elif "{resolutions}" not in response.text:
            try:
                await query.message.reply_text(
                    "⚠️ Invalid format! The format must contain `{resolutions}` placeholder.",
                    quote=True,
                )
            except Exception:
                pass
        else:
            session["res_format"] = response.text
    await update_post_preview(
        client, session_id, query.message.chat.id, force_resend=False
    )


async def handle_format_gen(client, query, session_id: int):
    session = post_sessions[session_id]
    response = await get_user_input(
        client,
        query,
        session,
        f"Send the format for genres. Must include `{{genres}}` as a placeholder. Send `/reset` for default.\n\n Current: {html.escape(session['gen_format'])}",
    )
    if response and response.text:
        if response.text == "/reset":
            session["gen_format"] = GENRES_FORMAT
        elif "{genres}" not in response.text:
            try:
                await query.message.reply_text(
                    "⚠️ Invalid format! The format must contain `{genres}` placeholder.",
                    quote=True,
                )
            except Exception:
                pass
        else:
            session["gen_format"] = response.text
    await update_post_preview(
        client, session_id, query.message.chat.id, force_resend=False
    )


async def handle_format_ott(client, query, session_id: int):
    session = post_sessions[session_id]
    response = await get_user_input(
        client,
        query,
        session,
        f"Send the format for OTT. Must include `{{otts}}` as a placeholder. Send `/reset` for default.\n\n Current: {html.escape(session['ott_format'])}",
    )
    if response and response.text:
        if response.text == "/reset":
            session["ott_format"] = OTT_FORMAT
        elif "{otts}" not in response.text:
            try:
                await query.message.reply_text(
                    "⚠️ Invalid format! The format must contain `{otts}` placeholder.",
                    quote=True,
                )
            except Exception:
                pass
        else:
            session["ott_format"] = response.text
    await update_post_preview(
        client, session_id, query.message.chat.id, force_resend=False
    )


async def handle_templates_menu(query, session_id: int):
    session = post_sessions[session_id]
    buttons = []
    for name in TEMPLATES:
        text = f"✅ {name}" if session.get("active_template") == name else name
        buttons.append(
            [
                InlineKeyboardButton(
                    text,
                    callback_data=f"post:select_template:{query.from_user.id}:{name}",
                )
            ]
        )
    buttons.append(
        [InlineKeyboardButton("Back", callback_data=f"post:back:{query.from_user.id}")]
    )
    try:
        await query.edit_message_reply_markup(InlineKeyboardMarkup(buttons))
    except MessageNotModified:
        pass


async def handle_select_template(session, template_name):
    session["active_template"] = template_name
    session["is_manual_caption"] = False
    session["caption"] = None


async def handle_remove_buttons_menu(query, session_id: int):
    session = post_sessions[session_id]
    buttons = []
    for i, row in enumerate(session["buttons"]):
        for j, btn in enumerate(row):
            buttons.append(
                [
                    InlineKeyboardButton(
                        f"❌ {btn.text}",
                        callback_data=f"post:remove_button:{query.from_user.id}:{i}:{j}",
                    )
                ]
            )
    if not buttons:
        buttons.append(
            [InlineKeyboardButton("No buttons to remove", callback_data="noop")]
        )
    buttons.append(
        [InlineKeyboardButton("Back", callback_data=f"post:back:{query.from_user.id}")]
    )
    try:
        await query.edit_message_reply_markup(InlineKeyboardMarkup(buttons))
    except MessageNotModified:
        pass


async def handle_remove_button(session, extra_data):
    try:
        row_i, col_i = int(extra_data[0]), int(extra_data[1])
        session["buttons"][row_i].pop(col_i)
        if not session["buttons"][row_i]:
            session["buttons"].pop(row_i)
    except (IndexError, ValueError):
        pass


async def handle_toggle_preview(query: CallbackQuery, session: dict):
    if session.get("custom_poster") and not session["custom_poster"].startswith("http"):
        try:
            await query.answer(
                "Cannot switch to Text mode with an uploaded photo.", show_alert=True
            )
        except Exception:
            pass
        return False
    session["photo_mode"] = not session["photo_mode"]
    return True


async def handle_toggle_poster(session):
    session["use_landscape"] = not session["use_landscape"]
    return True


async def handle_cancel(client: Client, query: CallbackQuery, session_id: int, _=None):
    if session := post_sessions.pop(session_id, None):
        if session.get("last_preview_message_id"):
            try:
                await client.delete_messages(
                    query.message.chat.id, session["last_preview_message_id"]
                )
            except Exception:
                pass
    try:
        await query.message.reply_to_message.reply_text("Post creation cancelled.")
    except Exception:
        pass


def get_final_keyboard(session: dict):
    rows = []
    if session.get("buttons"):
        rows.extend(session["buttons"])
    return InlineKeyboardMarkup(rows) if rows else None


async def finalize_and_post(
    client: Client, query: CallbackQuery, session_id: int, _=None
):
    session = post_sessions.pop(session_id, None)
    if not session:
        return

    try:
        await client.delete_messages(
            query.message.chat.id, session["last_preview_message_id"]
        )
    except Exception:
        pass

    try:
        status_msg = await query.message.reply_to_message.reply_text(
            "<i>Finalizing and posting...</i>"
        )
    except Exception:
        status_msg = None

    final_caption, _, poster_to_use = await _build_final_post_content(
        session, session_id
    )
    final_keyboard = get_final_keyboard(session)

    if not final_caption:
        if status_msg:
            try:
                await status_msg.edit(
                    "Could not fetch movie details to post. Aborting."
                )
            except Exception:
                pass
        return

    if not MOVIE_UPDATE_CHANNEL:
        if status_msg:
            try:
                await status_msg.edit(
                    "❌ **MOVIE_UPDATE_CHANNEL is not set in config!**"
                )
            except Exception:
                pass
        return

    mode = "Photo" if session["photo_mode"] and poster_to_use else "Text"
    try:
        if mode == "Photo":
            await client.send_photo(
                chat_id=MOVIE_UPDATE_CHANNEL,
                photo=poster_to_use,
                caption=final_caption,
                reply_markup=final_keyboard,
            )
        else:
            text_content = (
                f"<a href='{poster_to_use}'>&#8205;</a>{final_caption}"
                if poster_to_use
                else final_caption
            )
            await client.send_message(
                chat_id=MOVIE_UPDATE_CHANNEL,
                text=text_content,
                reply_markup=final_keyboard,
                disable_web_page_preview=False,
            )

        if status_msg:
            try:
                await status_msg.edit("✅ Post has been sent to the update channel.")
            except Exception:
                pass
    except ButtonUrlInvalid:
        if status_msg:
            try:
                await status_msg.edit(
                    "❌ **Post Failed:** One of the button URLs is invalid. Ensure all URLs start with `http://` or `https://`."
                )
            except Exception:
                pass
    except MessageTooLong:
        if status_msg:
            try:
                await status_msg.edit(
                    "<b>Post Failed</b>\n\nThe final caption is too long for a Telegram message. Please shorten the plot."
                )
            except Exception:
                pass
    except Exception as e:
        if status_msg:
            try:
                await status_msg.edit(
                    f"Failed to post to update channel.\n<b>Error:</b> <code>{e}</code>"
                )
            except Exception:
                pass
