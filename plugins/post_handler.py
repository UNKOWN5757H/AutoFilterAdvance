import asyncio
import html
import math
import re
import urllib.parse
from logging import ERROR, getLogger

import requests
from motor.motor_asyncio import AsyncIOMotorClient
from pyrogram import Client, filters
from pyrogram.errors import ButtonUrlInvalid, MessageNotModified, MessageTooLong
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    Message,
)

import info
from info import ADMINS, MOVIE_UPDATE_CHANNEL
from plugins.Imdbposter import get_movie_detailsx
from utils import temp

logger = getLogger(__name__)
logger.setLevel(ERROR)

# ============================================================
# ⚙️ MONGODB DRAFTS SETUP
# ============================================================
drafts_db = None
try:
    _DB_CLIENT = AsyncIOMotorClient(info.DATABASE_URI)
    _BOT_DB = _DB_CLIENT[info.DATABASE_NAME]
    drafts_db = _BOT_DB["post_drafts"]
except Exception as e:
    logger.error(f"Failed to init drafts_db: {e}")


def btn_to_dict(btn: InlineKeyboardButton):
    return {
        "text": getattr(btn, "text", ""),
        "url": getattr(btn, "url", None),
        "callback_data": getattr(btn, "callback_data", None),
        "style": getattr(btn, "style", None),
    }


post_sessions = {}
TEMP_SEARCH = {}
USE_GETFILE_BUTTON_BY_DEFAULT = True

DEFAULT_WATERMARK = "<b>Jᴏɪɴ: @Sandalwood_Kannada_Moviesz</b>"
LANGUAGES_FORMAT = "<b>🔊 : {langs}</b>"
RESOLUTIONS_FORMAT = "<b>🖥️ : {resolutions}</b>"
GENRES_FORMAT = "<b>🎥 : {genres}</b>"
OTT_FORMAT = "<b>📺 : #{otts}</b>"

TEMPLATES = {
    "clean_grid": """✅ <b>{title} {year}</b>\n\n<blockquote>{LANGUAGES}\n{RESOLUTIONS}\n{GENRES}\n{OTT_PLATFORMS}\n<b>📟 : Available In Files.</b>\n\n<b>=========================</b></blockquote>""",
    "divider_list": """🎬 <b>{title} {year}</b>\n━━━━━━━━━━━━━━━━━━\n<blockquote>{LANGUAGES}\n{RESOLUTIONS}\n{OTT_PLATFORMS}</blockquote>""",
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
    "#NotAvailable",
]
RESOLUTIONS = [
    "480p",
    "720p",
    "1080p",
    "1440p",
    "2160p",
    "4k",
    "BluRay",
    "BDRip",
    "WEB-DL",
    "HDRip",
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
    "Horror",
    "Romance",
    "Sci-Fi",
    "Thriller",
    "#NotAvailable",
]
OTT_PLATFORMS = [
    "Aha",
    "ALTBalaji",
    "JioHotstar",
    "JioCinema",
    "MXPlayer",
    "SonyLIV",
    "SunNXT",
    "Voot",
    "Zee5",
    "AmazonPrime",
    "Netflix",
    "NotAvailable",
]

try:
    from pyrogram.enums import ButtonStyle

    BTN_PRIMARY = getattr(ButtonStyle, "PRIMARY", 1)
    BTN_SUCCESS = getattr(ButtonStyle, "SUCCESS", 3)
    BTN_DANGER = getattr(ButtonStyle, "DANGER", 4)
    BTN_SECONDARY = getattr(ButtonStyle, "SECONDARY", 2)
except ImportError:
    BTN_PRIMARY = 1
    BTN_SUCCESS = 3
    BTN_DANGER = 4
    BTN_SECONDARY = 2

from database.users_chats_db import db as _db


def create_btn(
    text, url=None, callback_data=None, style=None, icon_custom_emoji_id=None
):
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


# ⚡ FOOLPROOF ADMIN PARSER
def is_admin(user_id):
    if not user_id:
        return False
    uid_str = str(user_id)
    raw_admins = getattr(info, "ADMINS", [])
    if isinstance(raw_admins, str):
        admin_list = [
            x.strip() for x in raw_admins.replace(",", " ").split() if x.strip()
        ]
    elif isinstance(raw_admins, list):
        admin_list = [str(x).strip() for x in raw_admins]
    else:
        admin_list = [str(raw_admins)]
    return uid_str in admin_list


admin_filter = filters.create(
    lambda _, __, update: is_admin(update.from_user.id if update.from_user else 0)
)

_WAITING_REQUESTS = {}


@Client.on_message(admin_filter, group=-10)
async def custom_listener(client: Client, message: Message):
    key = (message.chat.id, message.from_user.id)
    if key in _WAITING_REQUESTS:
        future = _WAITING_REQUESTS.pop(key)
        if not future.done():
            future.set_result(message)
        message.stop_propagation()


async def native_listen(
    client: Client, chat_id: int, user_id: int, timeout: int = 300
) -> Message:
    loop = asyncio.get_running_loop()
    future = loop.create_future()
    _WAITING_REQUESTS[(chat_id, user_id)] = future
    try:
        return await asyncio.wait_for(future, timeout=timeout)
    except asyncio.TimeoutError:
        _WAITING_REQUESTS.pop((chat_id, user_id), None)
        raise asyncio.TimeoutError


async def save_session_to_db(user_id: int, session: dict):
    if drafts_db is not None:
        try:
            draft = session.copy()
            draft["buttons"] = [
                [btn_to_dict(b) for b in row] for row in session.get("buttons", [])
            ]
            await drafts_db.update_one({"_id": user_id}, {"$set": draft}, upsert=True)
        except Exception as e:
            logger.error(f"Draft Save Error: {e}")


async def expire_post_session(client: Client, user_id: int, delay: int = 1800):
    await asyncio.sleep(delay)
    session = post_sessions.get(user_id)
    if session:
        msg_id = session.get("last_preview_message_id")
        chat_id = session.get("original_chat_id")
        if msg_id and chat_id:
            try:
                await client.delete_messages(chat_id, msg_id)
            except Exception:
                pass
        post_sessions.pop(user_id, None)


# ============================================================
# 🕒 SCHEDULING & AUTO-DELETE TASKS
# ============================================================
async def delete_after_delay(client: Client, chat_id: int, message_id: int, delay: int):
    await asyncio.sleep(delay)
    try:
        await client.delete_messages(chat_id, message_id)
    except Exception:
        pass


async def delayed_post_worker(
    client: Client, session: dict, targets: list, edit_target=None
):
    delay = session.get("schedule", 0)
    auto_del = session.get("auto_delete", 0)

    if delay > 0:
        await asyncio.sleep(delay)

    final_caption, _, poster_to_use = await _build_final_post_content(session, 0)
    final_keyboard = get_final_keyboard(session)
    is_normal_photo = (
        session.get("photo_mode")
        and poster_to_use
        and str(poster_to_use).upper() != "BLANK"
    )

    if edit_target:
        try:
            if is_normal_photo:
                await client.edit_message_media(
                    edit_target["chat_id"],
                    edit_target["message_id"],
                    media=InputMediaPhoto(media=poster_to_use, caption=final_caption),
                    reply_markup=final_keyboard,
                )
            else:
                text_content = (
                    f"{final_caption}\n<a href='{poster_to_use}'>&#8205;</a>"
                    if poster_to_use and str(poster_to_use).upper() != "BLANK"
                    else final_caption
                )
                await client.edit_message_text(
                    edit_target["chat_id"],
                    edit_target["message_id"],
                    text=text_content,
                    reply_markup=final_keyboard,
                    disable_web_page_preview=False,
                )

            if auto_del > 0:
                asyncio.create_task(
                    delete_after_delay(
                        client,
                        edit_target["chat_id"],
                        edit_target["message_id"],
                        auto_del,
                    )
                )
        except Exception as e:
            logger.error(f"Scheduled Edit Failed: {e}")
        return

    for target in targets:
        try:
            sent_msg = None
            if is_normal_photo:
                sent_msg = await client.send_photo(
                    chat_id=target,
                    photo=poster_to_use,
                    caption=final_caption,
                    reply_markup=final_keyboard,
                )
            else:
                text_content = (
                    f"{final_caption}\n<a href='{poster_to_use}'>&#8205;</a>"
                    if poster_to_use and str(poster_to_use).upper() != "BLANK"
                    else final_caption
                )
                sent_msg = await client.send_message(
                    chat_id=target,
                    text=text_content,
                    reply_markup=final_keyboard,
                    disable_web_page_preview=False,
                )

            if sent_msg and auto_del > 0:
                asyncio.create_task(
                    delete_after_delay(client, target, sent_msg.id, auto_del)
                )
            await asyncio.sleep(0.5)
        except Exception as e:
            logger.error(f"Post Failed for {target}: {e}")


# ============================================================
# 🔍 INTERACTIVE TMDB SEARCH SELECTOR
# ============================================================
@Client.on_message(filters.command("post") & admin_filter, group=-4)
async def post_command(client: Client, message: Message):
    if len(message.command) == 1:
        return await message.reply_text(
            "Please provide a movie name. Usage: `/post Vikram`"
        )

    movie_name = " ".join(message.command[1:])
    user_id = message.from_user.id
    status_msg = await message.reply_text("⏳ Searching TMDB...")

    tmdb_key = getattr(info, "TMDB_API_KEY", "")
    if tmdb_key:
        try:
            url = f"https://api.themoviedb.org/3/search/multi?api_key={tmdb_key}&query={urllib.parse.quote(movie_name)}"
            res = await asyncio.to_thread(requests.get, url)
            results = res.json().get("results", [])[:5]

            if results:
                buttons = []
                TEMP_SEARCH[user_id] = []
                for idx, r in enumerate(results):
                    title = r.get("title") or r.get("name")
                    if not title:
                        continue
                    date = r.get("release_date") or r.get("first_air_date") or ""
                    year = date[:4] if date else ""
                    display = f"{title} ({year})" if year else title

                    search_str = f"{title} {year}".strip()
                    TEMP_SEARCH[user_id].append(search_str)
                    buttons.append([create_btn(display, callback_data=f"p_init:{idx}")])

                if buttons:
                    buttons.append([create_btn("❌ Cancel", callback_data="p_cancel")])
                    return await status_msg.edit_text(
                        f"🔍 **Found results for '{movie_name}':**\nSelect the exact movie:",
                        reply_markup=InlineKeyboardMarkup(buttons),
                    )
        except Exception as e:
            logger.error(f"TMDB Search Error: {e}")

    await status_msg.delete()
    await start_post_session(client, message, user_id, movie_name)


@Client.on_callback_query(filters.regex(r"^p_init:|^p_cancel$") & admin_filter)
async def tmdb_selector_callback(client: Client, query: CallbackQuery):
    if query.data == "p_cancel":
        TEMP_SEARCH.pop(query.from_user.id, None)
        return await query.message.edit_text("❌ Cancelled.")

    idx = int(query.data.split(":")[1])
    user_id = query.from_user.id

    if user_id not in TEMP_SEARCH or len(TEMP_SEARCH[user_id]) <= idx:
        return await query.answer("Search session expired.", show_alert=True)

    selected_name = TEMP_SEARCH[user_id][idx]
    TEMP_SEARCH.pop(user_id, None)

    await query.message.delete()
    await start_post_session(client, query.message, user_id, selected_name)


# ============================================================
# 💾 PERSISTENT DRAFTS (RESUME POST)
# ============================================================
@Client.on_message(filters.command("resumepost") & admin_filter, group=-4)
async def resume_post_cmd(client: Client, message: Message):
    if drafts_db is None:
        return await message.reply("❌ DB not configured.")
    user_id = message.from_user.id

    draft = await drafts_db.find_one({"_id": user_id})
    if not draft:
        return await message.reply("⚠️ No saved draft found.")

    reconstructed_buttons = []
    for row in draft.get("buttons", []):
        row_btns = []
        for b_dict in row:
            kwargs = {k: v for k, v in b_dict.items() if v is not None}
            row_btns.append(create_btn(**kwargs))
        reconstructed_buttons.append(row_btns)
    draft["buttons"] = reconstructed_buttons

    if draft.get("last_preview_message_id"):
        try:
            await client.delete_messages(
                draft.get("original_chat_id"), draft.get("last_preview_message_id")
            )
        except Exception:
            pass

    draft["last_preview_message_id"] = None
    post_sessions[user_id] = draft
    asyncio.create_task(expire_post_session(client, user_id, 1800))
    await update_post_preview(client, user_id, message.chat.id, force_resend=True)
    await message.reply("✅ Draft successfully restored from Database!")


# ============================================================
# Core Post Edit Commands
# ============================================================
@Client.on_message(filters.command("editpost") & admin_filter, group=-4)
async def edit_post_cmd(client: Client, message: Message):
    try:
        if len(message.command) < 2:
            return await message.reply_text("❌ Please provide a post link.")
        link = message.command[1]
        parts = link.split("/")
        chat_id = (
            int("-100" + parts[-2])
            if "t.me/c/" in link
            else ("@" + parts[-2] if not parts[-2].startswith("@") else parts[-2])
        )
        msg_id = int(parts[-1])

        status_msg = await message.reply_text("⏳ Fetching post...")
        target_msg = await client.get_messages(chat_id, msg_id)

        poster_url, html_text, is_photo_mode = None, "", False
        if target_msg.photo:
            html_text = target_msg.caption.html if target_msg.caption else ""
            poster_url = target_msg.photo.file_id
            is_photo_mode = True
        else:
            html_text = target_msg.text.html if target_msg.text else ""
            match = re.search(
                r"<a href=['\"](https?://[^'\"]+)['\"]>&#8205;</a>", html_text
            )
            if match:
                poster_url = match.group(1)
                html_text = re.sub(
                    r"<a href=['\"](https?://[^'\"]+)['\"]>&#8205;</a>", "", html_text
                ).strip()

        title_match = re.search(r"<b>(.*?)</b>", html_text.split("\n")[0])
        search_name = title_match.group(1).strip() if title_match else "Unknown Movie"

        buttons = []
        if target_msg.reply_markup and target_msg.reply_markup.inline_keyboard:
            for row in target_msg.reply_markup.inline_keyboard:
                buttons.append(
                    [
                        create_btn(
                            text=b.text, url=b.url, callback_data=b.callback_data
                        )
                        for b in row
                    ]
                )

        user_id = message.from_user.id
        post_sessions[user_id] = {
            "movie_name": search_name,
            "caption": html_text,
            "is_manual_caption": True,
            "buttons": buttons,
            "photo_mode": is_photo_mode,
            "use_landscape": False,
            "custom_languages": [],
            "custom_resolutions": [],
            "custom_genres": [],
            "custom_otts": [],
            "schedule": 0,
            "auto_delete": 0,
            "last_preview_message_id": status_msg.id,
            "original_message_id": message.id,
            "original_chat_id": message.chat.id,
            "custom_poster": poster_url,
            "watermark": "",
            "lang_format": LANGUAGES_FORMAT,
            "ott_format": OTT_FORMAT,
            "gen_format": GENRES_FORMAT,
            "res_format": RESOLUTIONS_FORMAT,
            "active_template": "clean_grid",
            "movie_details": {"title": search_name, "year": ""},
            "edit_target": {"chat_id": chat_id, "message_id": msg_id},
        }
        await save_session_to_db(user_id, post_sessions[user_id])
        asyncio.create_task(expire_post_session(client, user_id, 1800))
        await update_post_preview(client, user_id, message.chat.id, force_resend=True)
    except Exception as e:
        await message.reply_text(f"❌ Error: {e}")


@Client.on_message(
    filters.command(
        ["editposttitle", "editpostyear", "editpostbutton", "editpostimage"]
    )
    & admin_filter,
    group=-4,
)
async def generic_editor_cmds(client: Client, message: Message):
    pass


async def start_post_session(
    client: Client, message: Message, user_id: int, movie_name: str
):
    try:
        if hasattr(message, "reply_text"):
            status_msg = await message.reply_text("⏳ Fetching movie details...")
        else:
            status_msg = await client.send_message(
                message.chat.id, "⏳ Fetching movie details..."
            )

        movie_details = await get_movie_detailsx(movie_name)
        if not movie_details:
            return await status_msg.edit_text("❌ TMDB failed.")

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
            "schedule": 0,
            "auto_delete": 0,
            "last_preview_message_id": status_msg.id,
            "original_message_id": (
                message.id if hasattr(message, "id") else status_msg.id
            ),
            "original_chat_id": message.chat.id,
            "custom_poster": None,
            "watermark": DEFAULT_WATERMARK,
            "lang_format": LANGUAGES_FORMAT,
            "ott_format": OTT_FORMAT,
            "gen_format": GENRES_FORMAT,
            "res_format": RESOLUTIONS_FORMAT,
            "active_template": "clean_grid",
            "movie_details": movie_details,
        }

        asyncio.create_task(expire_post_session(client, user_id, 1800))
        if USE_GETFILE_BUTTON_BY_DEFAULT:
            await handle_add_get_files(client, post_sessions[user_id])

        await save_session_to_db(user_id, post_sessions[user_id])
        await update_post_preview(client, user_id, message.chat.id, force_resend=True)
    except Exception as e:
        await client.send_message(message.chat.id, f"❌ **SESSION ERROR:**\n`{e}`")


class SafeDict(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def _upload_sync(file_bytes):
    headers = {"User-Agent": "Mozilla/5.0"}
    for upload_url in [
        "http://telegraph.controller.bot/upload",
        "https://telegra.ph/upload",
    ]:
        try:
            res = requests.post(
                upload_url,
                files={"file": ("img.jpg", file_bytes, "image/jpeg")},
                headers=headers,
                timeout=10,
            )
            if res.status_code == 200:
                data = res.json()
                if isinstance(data, list) and "src" in data[0]:
                    return upload_url.replace("/upload", "") + data[0]["src"]
        except Exception:
            pass
    try:
        res = requests.post(
            "https://envs.sh",
            files={"file": ("img.jpg", file_bytes, "image/jpeg")},
            headers=headers,
            timeout=10,
        )
        if res.status_code == 200 and res.text.startswith("http"):
            return res.text.strip()
    except Exception:
        pass
    return None


async def upload_image_safely(client: Client, message: Message):
    try:
        file_io = await client.download_media(message, in_memory=True)
        if not file_io:
            return None, "❌ Failed to download the image."
        url = await asyncio.to_thread(_upload_sync, file_io.getvalue())
        if not url:
            return None, "❌ All upload servers failed."
        return url, None
    except Exception as e:
        return None, f"❌ Internal Error: {e}"


async def _build_final_post_content(session: dict, session_id: int):
    movie_details = session.get("movie_details", {})

    if session.get("is_manual_caption") and session.get("caption"):
        text = session["caption"]
        poster_to_use = (
            None
            if session.get("custom_poster") == "BLANK"
            else session.get("custom_poster")
        )
        return text, build_keyboard(session, session_id), poster_to_use

    template_str = TEMPLATES.get(
        session.get("active_template"), TEMPLATES["clean_grid"]
    )

    val_title = html.escape(movie_details.get("title", ""))
    val_year = html.escape(str(movie_details.get("year", "")))
    rating_str = html.escape(str(movie_details.get("rating", "N/A")))
    plot_str = html.escape(str(movie_details.get("plot", "N/A")))

    c_langs, c_res, c_gen, c_ott = (
        session.get("custom_languages", []),
        session.get("custom_resolutions", []),
        session.get("custom_genres", []),
        session.get("custom_otts", []),
    )
    langs_str = (
        "" if c_langs == ["BLANK"] else (", ".join(c_langs) if c_langs else "N/A")
    )
    res_str = "" if c_res == ["BLANK"] else (", ".join(c_res) if c_res else "N/A")
    genres_str = "" if c_gen == ["BLANK"] else (", ".join(c_gen) if c_gen else "N/A")
    otts_str = "" if c_ott == ["BLANK"] else (", ".join(c_ott) if c_ott else "N/A")

    val_langs = (
        session["lang_format"].format_map(
            SafeDict(langs=langs_str, LANGUAGES=langs_str)
        )
        if langs_str != "N/A"
        else ""
    )
    val_res = (
        session["res_format"].format_map(
            SafeDict(resolutions=res_str, RESOLUTIONS=res_str)
        )
        if res_str != "N/A"
        else ""
    )
    val_gens = (
        session["gen_format"].format_map(SafeDict(genres=genres_str, GENRES=genres_str))
        if genres_str != "N/A"
        else ""
    )
    val_otts = (
        session["ott_format"].format_map(
            SafeDict(otts=otts_str, OTT_PLATFORMS=otts_str)
        )
        if otts_str != "N/A"
        else ""
    )

    def render_text(plot_input):
        text = template_str.replace("{title}", val_title).replace("{year}", val_year)
        for tag, val in [
            ("{LANGUAGES}", val_langs),
            ("{RESOLUTIONS}", val_res),
            ("{GENRES}", val_gens),
            ("{OTT_PLATFORMS}", val_otts),
            ("{langs}", val_langs),
            ("{resolutions}", val_res),
            ("{genres}", val_gens),
            ("{otts}", val_otts),
        ]:
            text = (
                text.replace(tag, val)
                if val
                else re.sub(rf"[^\n]*{re.escape(tag)}[^\n]*\n?", "", text)
            )
        text = (
            text.replace("{size}", "Available In Files.")
            .replace("{rating}", rating_str)
            .replace("{plot}", plot_input)
        )
        if session.get("watermark"):
            text += f"\n\n{session['watermark']}"
        return text

    final_text = render_text(plot_str)

    is_normal_photo = session.get("photo_mode")
    if is_normal_photo and len(final_text) > 1024:
        excess = len(final_text) - 1000
        if len(plot_str) > excess + 10:
            short_plot = plot_str[: -(excess + 5)] + "..."
            final_text = render_text(short_plot)
        else:
            final_text = final_text[:1024]

    poster_to_use = (
        None
        if session.get("custom_poster") == "BLANK"
        else (
            session.get("custom_poster")
            or (
                movie_details.get("backdrop_url")
                if session.get("use_landscape")
                else movie_details.get("poster_url")
            )
        )
    )
    return final_text, build_keyboard(session, session_id), poster_to_use


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
            return

    try:
        final_caption, keyboard, poster_to_use = await _build_final_post_content(
            session, session_id
        )
    except Exception:
        return

    try:
        is_normal_photo = (
            session.get("photo_mode")
            and poster_to_use
            and str(poster_to_use).upper() != "BLANK"
        )
        if is_normal_photo:
            if force_resend:
                old_msg_id = session.get("last_preview_message_id")
                sent_msg = await client.send_photo(
                    chat_id,
                    photo=poster_to_use,
                    caption=final_caption,
                    reply_markup=keyboard,
                )
                session["last_preview_message_id"] = sent_msg.id
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
                f"{final_caption}\n<a href='{poster_to_use}'>&#8205;</a>"
                if poster_to_use and str(poster_to_use).upper() != "BLANK"
                else final_caption
            )
            if force_resend:
                old_msg_id = session.get("last_preview_message_id")
                sent_msg = await client.send_message(
                    chat_id,
                    text=text_content,
                    reply_markup=keyboard,
                    disable_web_page_preview=False,
                )
                session["last_preview_message_id"] = sent_msg.id
                if old_msg_id:
                    try:
                        await client.delete_messages(chat_id, old_msg_id)
                    except Exception:
                        pass
            else:
                await client.edit_message_text(
                    chat_id,
                    session["last_preview_message_id"],
                    text=text_content,
                    reply_markup=keyboard,
                    disable_web_page_preview=False,
                )
        await save_session_to_db(session_id, session)
    except Exception:
        pass


def build_keyboard(session: dict, session_id: int):
    rows = []
    if session.get("buttons"):
        rows.extend(session["buttons"])

    mode_btn = []
    if not session.get("edit_target"):
        mode_btn.append(
            create_btn(
                f"Mode: {'Normal Img' if session.get('photo_mode') else 'Preview Img'}",
                callback_data=f"post:toggle_mode:{session_id}",
            )
        )
    mode_btn.append(
        create_btn(
            f"Poster: {'Landscape' if session['use_landscape'] else 'Portrait'}",
            callback_data=f"post:toggle_poster:{session_id}",
        )
    )

    sched_val = session.get("schedule", 0)
    del_val = session.get("auto_delete", 0)
    timing_row = [
        create_btn(
            f"⏰ Sched: {sched_val}s" if sched_val else "⏰ Sched: OFF",
            callback_data=f"post:set_schedule:{session_id}",
        ),
        create_btn(
            f"🗑️ Auto-Del: {del_val}s" if del_val else "🗑️ Auto-Del: OFF",
            callback_data=f"post:set_autodelete:{session_id}",
        ),
    ]

    rows.extend(
        [
            [
                create_btn(
                    "✏️ Buttons", callback_data=f"post:buttons_menu:{session_id}"
                ),
                create_btn(
                    "✏️ Caption", callback_data=f"post:edit_caption:{session_id}"
                ),
            ],
            [
                create_btn("🖼️ Poster", callback_data=f"post:set_poster:{session_id}"),
                create_btn(
                    "✨ Templates", callback_data=f"post:templates:{session_id}"
                ),
                create_btn(
                    "💧 Watermark", callback_data=f"post:set_watermark:{session_id}"
                ),
            ],
            [
                create_btn("🔊", callback_data=f"post:languages:{session_id}"),
                create_btn("🖥️", callback_data=f"post:resolutions:{session_id}"),
                create_btn("🎥", callback_data=f"post:genres:{session_id}"),
                create_btn("📺", callback_data=f"post:otts:{session_id}"),
            ],
            timing_row,
            mode_btn,
            [
                create_btn(
                    "✅ Post",
                    callback_data=f"post:finalize:{session_id}",
                    style=BTN_SUCCESS,
                ),
                create_btn(
                    "❌ Cancel",
                    callback_data=f"post:cancel:{session_id}",
                    style=BTN_DANGER,
                ),
            ],
        ]
    )
    return InlineKeyboardMarkup(rows)


try:
    from plugins.auto_post import get_ap_settings
except ImportError:

    async def get_ap_settings():
        return {}


async def show_target_selection(
    client: Client, query: CallbackQuery, session_id: int, page: int = 1
):
    all_chats_dict = {}
    settings = await get_ap_settings()
    db_titles = {}
    raw_chats = await _db.get_all_chats()
    db_chats = (
        [c async for c in raw_chats]
        if hasattr(raw_chats, "__aiter__")
        else list(raw_chats)
    )
    for chat in db_chats:
        chat_id = chat.get("id") or chat.get("chat_id")
        if chat_id:
            db_titles[int(chat_id)] = (
                chat.get("title") or chat.get("name") or str(chat_id)
            )

    def _safe_parse(var):
        if isinstance(var, str):
            return [int(x) for x in var.split() if x.strip()]
        if isinstance(var, list):
            return [int(x) for x in var if str(x).strip()]
        return [int(var)] if var else []

    info_muc = _safe_parse(getattr(info, "MOVIE_UPDATE_CHANNEL", []))
    db_muc = settings.get("muc_list", [])

    # Live Fetching of Channel Titles if Missing
    for ch in set(info_muc + db_muc):
        if ch:
            if int(ch) not in db_titles:
                try:
                    c_info = await client.get_chat(ch)
                    db_titles[int(ch)] = c_info.title
                except Exception:
                    pass
            all_chats_dict[int(ch)] = f"🌟 {db_titles.get(int(ch), str(ch))[:20]}"

    info_apc = _safe_parse(getattr(info, "AUTOPOSTCHANNEL", []))
    db_apc = settings.get("apc_list", [])
    for ch in set(info_apc + db_apc):
        if ch and int(ch) not in all_chats_dict:
            if int(ch) not in db_titles:
                try:
                    c_info = await client.get_chat(ch)
                    db_titles[int(ch)] = c_info.title
                except Exception:
                    pass
            all_chats_dict[int(ch)] = f"🌟 {db_titles.get(int(ch), str(ch))[:20]}"

    for chat in db_chats:
        chat_id = chat.get("id") or chat.get("chat_id")
        if chat_id and int(chat_id) not in all_chats_dict:
            all_chats_dict[int(chat_id)] = (
                f"📢 {db_titles.get(int(chat_id), str(chat_id))[:20]}"
            )

    chat_list = list(all_chats_dict.items())
    page_size = 10
    total_pages = max(1, math.ceil(len(chat_list) / page_size))
    page = max(1, min(page, total_pages))

    start_idx = (page - 1) * page_size
    current_chats = chat_list[start_idx : start_idx + page_size]

    buttons = [
        [
            create_btn(
                "📢 Post to All Configured Channels",
                callback_data=f"post:send_all:{session_id}",
                style=BTN_SUCCESS,
            )
        ]
    ]
    for chat_id, title in current_chats:
        buttons.append(
            [
                create_btn(
                    title,
                    callback_data=f"post:send_to:{session_id}:{chat_id}",
                    style=BTN_PRIMARY,
                )
            ]
        )

    nav_row = []
    if page > 1:
        nav_row.append(
            create_btn(
                "⬅️ Prev",
                callback_data=f"post:target_page:{session_id}:{page-1}",
                style=BTN_SECONDARY,
            )
        )
    if page < total_pages:
        nav_row.append(
            create_btn(
                "Next ➡️",
                callback_data=f"post:target_page:{session_id}:{page+1}",
                style=BTN_SECONDARY,
            )
        )

    if nav_row:
        buttons.append(nav_row)
    buttons.append(
        [
            create_btn(
                "🔙 Back to Editor",
                callback_data=f"post:back_editor:{session_id}",
                style=BTN_DANGER,
            )
        ]
    )

    try:
        await query.edit_message_reply_markup(InlineKeyboardMarkup(buttons))
    except MessageNotModified:
        pass


@Client.on_callback_query(filters.regex(r"^post:") & admin_filter, group=-4)
async def post_callbacks(client: Client, query: CallbackQuery):
    try:
        data_parts = query.data.split(":")
        action = data_parts[1]
        session_id = int(data_parts[2])
        extra_data = data_parts[3:]

        session = post_sessions.get(session_id)
        if not session:
            return await query.answer("Session expired.", show_alert=True)
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
            arr_map = {
                "select_lang": "custom_languages",
                "select_res": "custom_resolutions",
                "select_gen": "custom_genres",
                "select_ott": "custom_otts",
            }
            k = arr_map[action]
            if "BLANK" in session[k]:
                session[k] = []
            if item not in session[k]:
                session[k].append(item)
            else:
                session[k].remove(item)
            await save_session_to_db(session_id, session)

            if action == "select_lang":
                await show_selection_menu(query, session_id, "languages")
            elif action == "select_res":
                await show_selection_menu(query, session_id, "resolutions")
            elif action == "select_gen":
                await show_selection_menu(query, session_id, "genres")
            elif action == "select_ott":
                await show_selection_menu(query, session_id, "otts")
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

        elif action == "select_template":
            session["active_template"] = extra_data[0]
            session["is_manual_caption"] = False
            session["caption"] = None

        elif action == "edit_caption":
            await handle_edit_caption(client, query, session_id)
            return
        elif action == "set_poster":
            await handle_set_poster(client, query, session_id)
            return
        elif action == "set_watermark":
            await handle_set_watermark(client, query, session_id)
            return

        elif action == "edit_buttons":
            await handle_edit_buttons(client, query, session_id)
            return
        elif action == "remove_button":
            await handle_remove_button(session, extra_data)
            await handle_remove_buttons_menu(query, session_id)
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

        elif action == "set_schedule":
            await handle_set_schedule(client, query, session_id)
            return
        elif action == "set_autodelete":
            await handle_set_autodelete(client, query, session_id)
            return

        elif action == "toggle_poster":
            session["use_landscape"] = not session["use_landscape"]
            force_resend = True
        elif action == "toggle_mode":
            if not session.get("edit_target"):
                session["photo_mode"] = not session.get("photo_mode")
                force_resend = True
            else:
                return await query.answer(
                    "Cannot switch image modes on imported post!", show_alert=True
                )

        elif action == "cancel":
            return await handle_cancel(client, query, session_id)

        elif action == "finalize":
            for row in session.get("buttons", []):
                for btn in row:
                    if btn.url and not btn.url.startswith(
                        ("http://", "https://", "tg://")
                    ):
                        return await query.answer(
                            f"❌ Invalid Link Found: {btn.url}\nPlease edit your buttons first.",
                            show_alert=True,
                        )
            if session.get("edit_target"):
                return await execute_post(
                    client, query, session_id, session["edit_target"]["chat_id"]
                )
            else:
                return await show_target_selection(client, query, session_id, 1)

        elif action == "target_page":
            return await show_target_selection(
                client, query, session_id, int(extra_data[0])
            )
        elif action == "send_to":
            return await execute_post(client, query, session_id, int(extra_data[0]))
        elif action == "send_all":
            return await execute_post_all(client, query, session_id)
        elif action == "back_editor":
            return await update_post_preview(
                client, session_id, query.message.chat.id, force_resend=False
            )

        await save_session_to_db(session_id, session)
        await update_post_preview(
            client, session_id, query.message.chat.id, force_resend
        )
    except Exception as e:
        try:
            await query.message.reply_text(f"❌ **CALLBACK ERROR:**\n`{e}`")
        except Exception:
            pass


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
        create_btn(
            f"✅ {i}" if i in selected else i,
            callback_data=f"post:{action_prefix}:{session_id}:{i}",
        )
        for i in items
    ]
    keyboard = [buttons[i : i + 3] for i in range(0, len(buttons), 3)]
    keyboard.append(
        [
            create_btn(
                "⚙ Change Format", callback_data=f"post:{format_action}:{session_id}"
            )
        ]
    )
    keyboard.append([create_btn("✅ Done", callback_data=f"post:back:{session_id}")])
    try:
        await query.edit_message_reply_markup(InlineKeyboardMarkup(keyboard))
    except MessageNotModified:
        pass


async def handle_templates_menu(query, session_id: int):
    session = post_sessions[session_id]
    buttons = []
    for name in TEMPLATES:
        text = f"✅ {name}" if session.get("active_template") == name else name
        buttons.append(
            [
                create_btn(
                    text, callback_data=f"post:select_template:{session_id}:{name}"
                )
            ]
        )
    buttons.append([create_btn("Back", callback_data=f"post:back:{session_id}")])
    try:
        await query.edit_message_reply_markup(InlineKeyboardMarkup(buttons))
    except MessageNotModified:
        pass


async def handle_buttons_menu(query, session_id):
    buttons = [
        [
            create_btn(
                "➕ Add/Edit Layout", callback_data=f"post:edit_buttons:{session_id}"
            )
        ],
        [
            create_btn(
                "📥 Add 'Get Files' Button",
                callback_data=f"post:add_get_files:{session_id}",
            )
        ],
        [
            create_btn(
                "🗑️ Remove a Button",
                callback_data=f"post:remove_buttons_menu:{session_id}",
            )
        ],
        [create_btn("Back", callback_data=f"post:back:{session_id}")],
    ]
    try:
        await query.edit_message_reply_markup(InlineKeyboardMarkup(buttons))
    except MessageNotModified:
        pass


async def handle_remove_buttons_menu(query, session_id: int):
    session = post_sessions[session_id]
    buttons = []
    for i, row in enumerate(session["buttons"]):
        for j, btn in enumerate(row):
            buttons.append(
                [
                    create_btn(
                        f"❌ {btn.text}",
                        callback_data=f"post:remove_button:{session_id}:{i}:{j}",
                    )
                ]
            )
    if not buttons:
        buttons.append([create_btn("No buttons to remove", callback_data="noop")])
    buttons.append([create_btn("Back", callback_data=f"post:back:{session_id}")])
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


async def get_user_input(client, query, session, prompt_text):
    try:
        ask_msg = await query.message.reply_text(
            prompt_text, reply_to_message_id=session.get("original_message_id")
        )
    except Exception:
        ask_msg = await query.message.reply_text(prompt_text)
    try:
        response = await native_listen(
            client, query.message.chat.id, query.from_user.id, 120
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
        pass
    return None


async def format_updater(
    client: Client,
    query: CallbackQuery,
    session_id: int,
    format_key: str,
    tag: str,
    default_format: str,
):
    session = post_sessions[session_id]
    response = await get_user_input(
        client,
        query,
        session,
        f"Send format. Must include `{tag}`. Send `/reset` for default.",
    )
    if response and response.text:
        if response.text == "/reset":
            session[format_key] = default_format
        elif tag not in response.text:
            try:
                await query.message.reply_text(f"⚠️ Must contain `{tag}`")
            except Exception:
                pass
        else:
            session[format_key] = response.text
    await update_post_preview(
        client, session_id, query.message.chat.id, force_resend=False
    )


async def handle_format_lang(client, query, session_id):
    await format_updater(
        client, query, session_id, "lang_format", "{langs}", LANGUAGES_FORMAT
    )


async def handle_format_res(client, query, session_id):
    await format_updater(
        client, query, session_id, "res_format", "{resolutions}", RESOLUTIONS_FORMAT
    )


async def handle_format_gen(client, query, session_id):
    await format_updater(
        client, query, session_id, "gen_format", "{genres}", GENRES_FORMAT
    )


async def handle_format_ott(client, query, session_id):
    await format_updater(client, query, session_id, "ott_format", "{otts}", OTT_FORMAT)


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
        "📸 Send a photo or an image URL.\n*(Or type `/reset` or `blank`)*",
    )
    if response:
        if response.photo:
            status_msg = await query.message.reply_text("⏳ Uploading...")
            url, err = await upload_image_safely(client, response)
            if url:
                session["custom_poster"] = url
                if not session.get("edit_target"):
                    session["photo_mode"] = False
                try:
                    await status_msg.edit_text("✅ Image set!")
                except Exception:
                    pass
        elif response.text:
            text_input = response.text.strip().lower()
            if text_input == "/reset":
                session["custom_poster"] = None
                if not session.get("edit_target"):
                    session["photo_mode"] = False
            elif text_input == "blank":
                session["custom_poster"] = "BLANK"
            elif response.text.startswith("http"):
                session["custom_poster"] = response.text.strip()
                if not session.get("edit_target"):
                    session["photo_mode"] = False
    await update_post_preview(
        client, session_id, query.message.chat.id, force_resend=False
    )


async def handle_set_watermark(client, query, session_id: int):
    session = post_sessions[session_id]
    response = await get_user_input(
        client,
        query,
        session,
        "Send watermark. Send `blank` or `/reset` to remove. Send `/default` for default.",
    )
    if response and response.text:
        text_input = response.text.strip().lower()
        if text_input in ["/reset", "blank"]:
            session["watermark"] = ""
        elif text_input == "/default":
            session["watermark"] = DEFAULT_WATERMARK
        else:
            session["watermark"] = response.text
    await update_post_preview(
        client, session_id, query.message.chat.id, force_resend=False
    )


async def handle_set_schedule(client, query, session_id):
    session = post_sessions[session_id]
    response = await get_user_input(
        client,
        query,
        session,
        "⏰ Send schedule delay in **seconds** (e.g., `3600` for 1 hour).\nOr type `off`.",
    )
    if response and response.text:
        text_val = response.text.strip().lower()
        if text_val == "off":
            session["schedule"] = 0
        elif text_val.isdigit():
            session["schedule"] = int(text_val)
        await save_session_to_db(session_id, session)
    await update_post_preview(
        client, session_id, query.message.chat.id, force_resend=False
    )


async def handle_set_autodelete(client, query, session_id):
    session = post_sessions[session_id]
    response = await get_user_input(
        client,
        query,
        session,
        "🗑️ Send auto-delete time in **seconds** (e.g., `86400` for 24 hours).\nOr type `off`.",
    )
    if response and response.text:
        text_val = response.text.strip().lower()
        if text_val == "off":
            session["auto_delete"] = 0
        elif text_val.isdigit():
            session["auto_delete"] = int(text_val)
        await save_session_to_db(session_id, session)
    await update_post_preview(
        client, session_id, query.message.chat.id, force_resend=False
    )


async def handle_edit_buttons(client: Client, query: CallbackQuery, session_id: int):
    session = post_sessions[session_id]
    response = await get_user_input(
        client,
        query,
        session,
        "Send the button layout. Format:\n`Button 1 - URL1 | Button 2 - URL2`",
    )
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
                    row_btns.append(create_btn(clean_text, url=clean_url))
            if row_btns:
                new_layout.append(row_btns)
        session["buttons"] = new_layout
        await save_session_to_db(session_id, session)
    await update_post_preview(
        client, session_id, query.message.chat.id, force_resend=False
    )


async def handle_add_get_files(client: Client, session: dict) -> bool:
    movie_details = session["movie_details"]
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
    safe_query = re.sub(r"[^a-zA-Z0-9_-]", "_", f"{title} {year}".strip()).strip("_")[
        :50
    ]

    bot_username = temp.U_NAME or "MovieBot"
    url = f"https://t.me/{bot_username}?start=search_{safe_query}"

    for row in session["buttons"]:
        for btn in row:
            if btn.url == url:
                return False

    session["buttons"].append(
        [
            create_btn(
                text="Group 1 🎬",
                url="https://t.me/Sandalwood_Kannada_Group",
                style=BTN_PRIMARY,
            ),
            create_btn(
                text="Group 2 🎬",
                url="https://t.me/+GLsPkRgLGGszMzY1",
                style=BTN_PRIMARY,
            ),
        ]
    )
    session["buttons"].append(
        [create_btn(text="Direct Search 🔎", url=url, style=BTN_SUCCESS)]
    )
    return True


async def handle_cancel(client: Client, query: CallbackQuery, session_id: int):
    if session := post_sessions.pop(session_id, None):
        if session.get("last_preview_message_id"):
            try:
                await client.delete_messages(
                    query.message.chat.id, session["last_preview_message_id"]
                )
            except Exception:
                pass

    reply_base = query.message.reply_to_message or query.message
    try:
        await reply_base.reply_text("❌ Post creation cancelled.")
    except Exception:
        pass


def get_final_keyboard(session: dict):
    rows = []
    if session.get("buttons"):
        rows.extend(session["buttons"])
    return InlineKeyboardMarkup(rows) if rows else None


async def execute_post(
    client: Client, query: CallbackQuery, session_id: int, target_chat_id: int
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

    reply_base = query.message.reply_to_message or query.message
    delay = session.get("schedule", 0)
    if delay > 0:
        try:
            await reply_base.reply_text(
                f"✅ **Post Scheduled!** It will automatically execute after `{delay}` seconds."
            )
        except Exception:
            pass
        asyncio.create_task(
            delayed_post_worker(
                client, session, [target_chat_id], session.get("edit_target")
            )
        )
    else:
        try:
            status_msg = await reply_base.reply_text("<i>Finalizing and posting...</i>")
        except Exception:
            status_msg = None

        await delayed_post_worker(
            client, session, [target_chat_id], session.get("edit_target")
        )

        if status_msg:
            try:
                await status_msg.edit("✅ Post completed successfully!")
            except Exception:
                pass


async def execute_post_all(client: Client, query: CallbackQuery, session_id: int):
    session = post_sessions.pop(session_id, None)
    if not session:
        return
    try:
        await client.delete_messages(
            query.message.chat.id, session["last_preview_message_id"]
        )
    except Exception:
        pass

    settings = await get_ap_settings()

    def _safe_parse(var):
        if isinstance(var, str):
            return [int(x) for x in var.split() if x.strip()]
        if isinstance(var, list):
            return [int(x) for x in var if str(x).strip()]
        return [int(var)] if var else []

    info_muc = _safe_parse(getattr(info, "MOVIE_UPDATE_CHANNEL", []))
    db_muc = settings.get("muc_list", [])
    info_apc = _safe_parse(getattr(info, "AUTOPOSTCHANNEL", []))
    db_apc = settings.get("apc_list", [])

    all_targets = list(set(info_muc + db_muc + info_apc + db_apc))
    reply_base = query.message.reply_to_message or query.message

    if not all_targets:
        try:
            return await reply_base.reply_text("❌ No channels configured.")
        except Exception:
            return

    delay = session.get("schedule", 0)
    if delay > 0:
        try:
            await reply_base.reply_text(
                f"✅ **Broadcast Scheduled!** Will post to `{len(all_targets)}` channels after `{delay}` seconds."
            )
        except Exception:
            pass
        asyncio.create_task(delayed_post_worker(client, session, all_targets))
    else:
        try:
            status_msg = await reply_base.reply_text(
                f"<i>📢 Broadcasting to {len(all_targets)} channels...</i>"
            )
        except Exception:
            status_msg = None

        await delayed_post_worker(client, session, all_targets)

        if status_msg:
            try:
                await status_msg.edit(f"✅ **Broadcast Complete!**")
            except Exception:
                pass
