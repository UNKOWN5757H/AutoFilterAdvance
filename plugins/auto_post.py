import asyncio
import html
import re
import time
from logging import ERROR, getLogger
from typing import Dict, Optional, Tuple

from motor.motor_asyncio import AsyncIOMotorClient
from pyrogram import Client, enums, filters
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

import info
from plugins.Imdbposter import get_movie_detailsx
from utils import get_size, temp

logger = getLogger(__name__)
logger.setLevel(ERROR)

# ⚡ DATABASE SETUP FOR AUTO-POST
ap_db = None
try:
    _DB_CLIENT = AsyncIOMotorClient(info.DATABASE_URI)
    _BOT_DB = _DB_CLIENT[info.DATABASE_NAME]
    ap_db = _BOT_DB["autopost_settings"]
except Exception as e:
    logger.error(f"Failed to init ap_db: {e}")

# ⚡ SMART DYNAMIC DEFAULT TEMPLATE
DEFAULT_TEMPLATE = """✅ <b>{title} {year}</b>

<blockquote><b>🔊 : {LANGUAGES}</b>
<b>🖥️ : {RESOLUTIONS}</b>
<b>🎥 : {GENRES}</b>
<b>📺 : #{OTT_PLATFORMS}</b>
<b>📟 : Available In Files.</b>

<b>=========================</b></blockquote>"""


async def get_ap_settings():
    if ap_db is None:
        return {}
    settings = await ap_db.find_one({"id": "ap_config"})
    if not settings:
        return {"enabled": False, "template": DEFAULT_TEMPLATE}
    return settings


async def save_ap_settings(key, value):
    if ap_db is not None:
        await ap_db.update_one({"id": "ap_config"}, {"$set": {key: value}}, upsert=True)


# ⚡ ONE MOVIE ONE POST CACHE
class TTLCache:
    def __init__(self, maxsize: int = 200, ttl: int = 3600):
        self._data: Dict[str, Tuple[float, any]] = {}
        self._maxsize = maxsize
        self._ttl = ttl

    def set(self, key: str, value: any):
        now = time.time()
        self._data = {k: v for k, v in self._data.items() if v[0] > now}
        if len(self._data) >= self._maxsize:
            oldest_key = min(self._data, key=lambda k: self._data[k][0])
            self._data.pop(oldest_key, None)
        self._data[key] = (now + self._ttl, value)

    def get(self, key: str) -> Optional[any]:
        item = self._data.get(key)
        if not item:
            return None
        if time.time() > item[0]:
            self._data.pop(key, None)
            return None
        return item[1]


RECENT_POSTS = TTLCache(maxsize=100, ttl=3600)  # 1 Hour Cooldown per movie
PENDING_AP = {}  # Stores pending posts for PM approval

# ⚡ ADMIN FILTER
id_pattern = re.compile(r"^.\d+$")
ADMIN_USERS = [
    int(admin) if id_pattern.search(str(admin)) else admin
    for admin in getattr(info, "ADMINS", [])
]


async def admin_check(_, __, message: Message):
    return bool(message.from_user and message.from_user.id in ADMIN_USERS)


admin_filter = filters.create(admin_check)

# ⚡ PM NATIVE LISTENER (For Editing)
_WAITING_REQUESTS = {}


@Client.on_message(admin_filter, group=-11)
async def custom_ap_listener(client: Client, message: Message):
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


def create_btn(text, url=None, callback_data=None):
    kwargs = {"text": text}
    if url:
        kwargs["url"] = url
    if callback_data:
        kwargs["callback_data"] = callback_data
    return InlineKeyboardButton(**kwargs)


class SafeDict(dict):
    def __missing__(self, key):
        return "{" + key + "}"


# ============================================================
# ⚙️ HTML FORMAT EXTRACTOR (SUPPORTS BOLD, QUOTE, MONO)
# ============================================================
def get_html_text(message: Message):
    if message.reply_to_message and message.reply_to_message.text:
        return message.reply_to_message.text.html
    elif len(message.command) > 1:
        html_text = message.text.html
        html_text = re.sub(r"^/\w+(?:@[a-zA-Z0-9_]+)?\s+", "", html_text, count=1)
        return html_text
    return None


# ============================================================
# ⚙️ AUTO-POST CONFIGURATION COMMANDS
# ============================================================
@Client.on_message(filters.command("autopost") & admin_filter)
async def toggle_autopost(client: Client, message: Message):
    if len(message.command) < 2:
        settings = await get_ap_settings()
        status = "🟢 ON" if settings.get("enabled") else "🔴 OFF"
        return await message.reply_text(
            f"**Auto-Post Status:** {status}\n\nUse `/autopost on` or `/autopost off` to toggle."
        )
    cmd = message.command[1].lower()
    if cmd == "on":
        await save_ap_settings("enabled", True)
        await message.reply_text("✅ **Auto-Post Engine ON!**")
    elif cmd == "off":
        await save_ap_settings("enabled", False)
        await message.reply_text("🔴 **Auto-Post Engine OFF!**")


@Client.on_message(filters.command(["editautopost", "setautoposttext"]) & admin_filter)
async def set_autopost_text(client: Client, message: Message):
    text = get_html_text(message)
    if not text:
        return await message.reply_text(
            "⚠️ **Usage:** `/editautopost <text>`\nPlaceholders: `{title}`, `{year}`, `{size}`, `{rating}`, `{LANGUAGES}`, `{RESOLUTIONS}`, `{GENRES}`, `{OTT_PLATFORMS}`"
        )
    await save_ap_settings("template", text)
    await message.reply_text(f"✅ **Template Updated!**\n\n{text}")


@Client.on_message(
    filters.command(["editautoposttittle", "editautoposttitle"]) & admin_filter
)
async def cmd_edit_title(client: Client, message: Message):
    text = get_html_text(message)
    if not text:
        return await message.reply_text("⚠️ **Usage:** `/editautoposttitle <format>`")
    await save_ap_settings("format_title", text)
    await message.reply_text(f"✅ **Title Format Updated!**\n\n{text}")


@Client.on_message(filters.command(["editautopostyear"]) & admin_filter)
async def cmd_edit_year(client: Client, message: Message):
    text = get_html_text(message)
    if not text:
        return await message.reply_text("⚠️ **Usage:** `/editautopostyear <format>`")
    await save_ap_settings("format_year", text)
    await message.reply_text(f"✅ **Year Format Updated!**\n\n{text}")


@Client.on_message(filters.command(["editautopostlanguages"]) & admin_filter)
async def cmd_edit_langs(client: Client, message: Message):
    text = get_html_text(message)
    if not text:
        return await message.reply_text(
            "⚠️ **Usage:** `/editautopostlanguages <format>`"
        )
    await save_ap_settings("format_languages", text)
    await message.reply_text(f"✅ **Languages Format Updated!**\n\n{text}")


@Client.on_message(filters.command(["editautopostresolutions"]) & admin_filter)
async def cmd_edit_res(client: Client, message: Message):
    text = get_html_text(message)
    if not text:
        return await message.reply_text(
            "⚠️ **Usage:** `/editautopostresolutions <format>`"
        )
    await save_ap_settings("format_resolutions", text)
    await message.reply_text(f"✅ **Resolutions Format Updated!**\n\n{text}")


@Client.on_message(filters.command(["editautopostgenres"]) & admin_filter)
async def cmd_edit_genres(client: Client, message: Message):
    text = get_html_text(message)
    if not text:
        return await message.reply_text("⚠️ **Usage:** `/editautopostgenres <format>`")
    await save_ap_settings("format_genres", text)
    await message.reply_text(f"✅ **Genres Format Updated!**\n\n{text}")


@Client.on_message(filters.command(["editautopostottplatforms"]) & admin_filter)
async def cmd_edit_otts(client: Client, message: Message):
    text = get_html_text(message)
    if not text:
        return await message.reply_text(
            "⚠️ **Usage:** `/editautopostottplatforms <format>`"
        )
    await save_ap_settings("format_otts", text)
    await message.reply_text(f"✅ **OTT Platforms Format Updated!**\n\n{text}")


@Client.on_message(filters.command("editautopostdirect") & admin_filter)
async def cmd_edit_ap_direct(client: Client, message: Message):
    text = get_html_text(message)
    if not text:
        return await message.reply_text(
            "⚠️ **Usage:** `/editautopostdirect Download Now 📥`"
        )
    await save_ap_settings("direct_button_text", text)
    await message.reply_text(f"✅ **Direct Search Button Text Updated!** -> {text}")


# ============================================================
# 🚀 THE AUTO-POST LISTENER ENGINE
# ============================================================
@Client.on_message(
    filters.chat(info.FILE_STORE_CHANNEL)
    & (filters.document | filters.video | filters.audio)
)
async def auto_post_trigger(client: Client, message: Message):
    settings = await get_ap_settings()
    if not settings.get("enabled", False):
        return

    update_channel = getattr(
        info, "AUTOPOSTCHANNEL", getattr(info, "MOVIE_UPDATE_CHANNEL", None)
    )
    if not update_channel:
        return

    try:
        media = message.document or message.video or message.audio
        if not media:
            return

        file_name = getattr(media, "file_name", "Unknown")
        file_size = getattr(media, "file_size", 0)
        size_str = get_size(file_size)

        clean_name = re.sub(r"(?i)\[?@?sandalwood[^\]\s]*\]?", "", file_name)
        clean_name = re.sub(r"[_.-]", " ", clean_name)

        # ⚡ EXTRACT LANGUAGES
        lang_matches = re.findall(
            r"(?i)\b(Kannada|English|Gujarati|Hindi|Bengali|Malayalam|Marathi|Punjabi|Tamil|Telugu|Urdu|Dual Audio|Multi Audio)\b",
            clean_name,
        )
        langs = list(set([l.title() for l in lang_matches]))
        langs_str = ", ".join(langs) if langs else ""

        # ⚡ EXTRACT TARGET RESOLUTIONS (Web-DL, HDRip, HDTC, etc)
        res_matches = re.findall(
            r"(?i)\b(WEB-DL|HDRip|HDTC|1080p|720p|480p|1440p|2160p|4k|BluRay|BDRip|WEBRip|HDTVRip|DVDRip|CAMRip|HEVC)\b",
            clean_name,
        )
        res = list(
            set([r.upper() if "p" not in r.lower() else r.lower() for r in res_matches])
        )
        res_str = ", ".join(res) if res else ""

        # ⚡ EXTRACT OTT PLATFORMS
        ott_matches = re.findall(
            r"(?i)\b(Netflix|Amazon Prime|Prime Video|Aha|Zee5|Hotstar|Disney\+?|JioCinema|SonyLIV|SunNXT|Voot|Hulu|HBO|Apple TV|AppleTV|Crunchyroll)\b",
            clean_name,
        )
        otts = list(
            set(
                [
                    o.title()
                    .replace("Appletv", "Apple TV")
                    .replace("Disney+", "Disney")
                    for o in ott_matches
                ]
            )
        )
        otts_str = ", ".join(otts) if otts else ""

        # Strip everything to get a clean TMDB search query
        search_name = re.sub(
            r"(?i)\b(1080p|720p|480p|2160p|4k|WEB-DL|HDRip|HDTC|BDRip|BluRay|DVDRip|WEBRip|CAMRip|HEVC|mkv|mp4|avi|hindi|kannada|telugu|tamil|malayalam|english|dual audio|multi audio|dual|multi|subs|episodes|season\s*\d+|s\d+e\d+|Netflix|Prime|Aha|Zee5|Hotstar|JioCinema|SonyLIV|Voot)\b",
            "",
            clean_name,
        )
        search_name = re.sub(r"\b(19\d{2}|20\d{2})\b", "", search_name)
        search_name = re.sub(r"\s+", " ", search_name).strip()

        # ⚡ ONE MOVIE ONE POST CACHE
        if RECENT_POSTS.get(search_name):
            return  # Skip if we already prompted for this movie recently
        RECENT_POSTS.set(search_name, True)

        # 🎬 Fetch Official Data
        movie_details = await get_movie_detailsx(search_name)
        title = (
            movie_details.get("title", search_name) if movie_details else search_name
        )
        year = movie_details.get("year", "N/A") if movie_details else "N/A"
        rating = movie_details.get("rating", "N/A") if movie_details else "N/A"

        # Merge TMDB genres
        tmdb_genres = movie_details.get("genres", []) if movie_details else []
        genres_str = ", ".join(tmdb_genres) if tmdb_genres else ""
        plot = movie_details.get("plot", "N/A") if movie_details else "N/A"

        custom_img = settings.get("image")
        poster = (
            custom_img
            if custom_img
            else (movie_details.get("poster_url") if movie_details else None)
        )

        fmt_title = settings.get("format_title", "✅ <b>{title}</b>")
        fmt_year = settings.get("format_year", "<b>{year}</b>")
        fmt_langs = settings.get("format_languages", "<b>🔊 : {langs}</b>")
        fmt_res = settings.get("format_resolutions", "<b>🖥️ : {resolutions}</b>")
        fmt_gens = settings.get("format_genres", "<b>🎥 : {genres}</b>")
        fmt_otts = settings.get("format_otts", "<b>📺 : #{otts}</b>")

        val_title = fmt_title.replace("{title}", html.escape(title))
        val_year = (
            fmt_year.replace("{year}", html.escape(str(year)))
            if str(year) != "N/A"
            else ""
        )
        val_langs = (
            fmt_langs.replace("{langs}", langs_str).replace("{LANGUAGES}", langs_str)
            if langs_str
            else ""
        )
        val_res = (
            fmt_res.replace("{resolutions}", res_str).replace("{RESOLUTIONS}", res_str)
            if res_str
            else ""
        )
        val_gens = (
            fmt_gens.replace("{genres}", genres_str).replace("{GENRES}", genres_str)
            if genres_str
            else ""
        )
        val_otts = (
            fmt_otts.replace("{otts}", otts_str).replace("{OTT_PLATFORMS}", otts_str)
            if otts_str
            else ""
        )

        template_str = settings.get("template", DEFAULT_TEMPLATE)
        text = template_str.replace("{title}", val_title).replace("{year}", val_year)

        # Smart Hide Empty Lines
        for tag, val in [
            ("{LANGUAGES}", val_langs),
            ("{RESOLUTIONS}", val_res),
            ("{GENRES}", val_gens),
            ("{OTT_PLATFORMS}", val_otts),
        ]:
            if val:
                text = text.replace(tag, val)
            else:
                text = text.replace(tag + "\n", "").replace(tag, "")

        text = (
            text.replace("{size}", size_str)
            .replace("{rating}", html.escape(str(rating)))
            .replace("{plot}", html.escape(str(plot)))
            .replace("{file_name}", html.escape(file_name))
        )
        text += f"\n\n<b>Jᴏɪɴ: @Sandalwood_Kannada_Moviesz</b>"

        # ⚡ RICH PREVIEW LINK INJECTION (No Physical Photo)
        if poster:
            text = f"{text}\n<a href='{poster}'>&#8205;</a>"

        # Buttons
        bot_me = await client.get_me()
        bot_username = bot_me.username
        safe_query = re.sub(
            r"[^a-zA-Z0-9_-]", "_", f"{title} {year}" if str(year) != "N/A" else title
        ).strip("_")[:50]
        deep_link = f"https://t.me/{bot_username}?start=search_{safe_query}"

        direct_text = settings.get("direct_button_text", "Direct Search 🔎")
        btn = InlineKeyboardMarkup(
            [
                [
                    create_btn(
                        text="Group 1 🎬", url="https://t.me/Sandalwood_Kannada_Group"
                    ),
                    create_btn(text="Group 2 🎬", url="https://t.me/+GLsPkRgLGGszMzY1"),
                ],
                [create_btn(text=direct_text, url=deep_link)],
            ]
        )

        # ⚡ SEND PM CONFIRMATION TO ADMIN
        target_admin = (
            message.from_user.id
            if message.from_user and message.from_user.id in ADMIN_USERS
            else ADMIN_USERS[0]
        )

        pm_markup = InlineKeyboardMarkup(
            [
                [create_btn("✅ Post to Channel", callback_data=f"ap_post_1")],
                [
                    create_btn("✏️ Edit Text", callback_data=f"ap_edit_1"),
                    create_btn("❌ Cancel", callback_data=f"ap_cancel_1"),
                ],
            ]
        )

        ask_msg = await client.send_message(
            chat_id=target_admin,
            text=f"**🚨 AUTO-POST TRIGGERED 🚨**\n\n{text}",
            reply_markup=pm_markup,
        )

        PENDING_AP[str(ask_msg.id)] = {
            "text": text,
            "buttons": btn,
            "channel": update_channel,
            "sticker": settings.get("sticker"),
        }

    except Exception as e:
        logger.error(f"Auto-Post Engine Failed: {e}")


# ============================================================
# ⚙️ PM APPROVAL CALLBACKS
# ============================================================
@Client.on_callback_query(filters.regex(r"^ap_(post|edit|cancel)_") & admin_filter)
async def ap_approval_callback(client: Client, query: CallbackQuery):
    action = query.data.split("_")[1]
    msg_id = str(query.message.id)

    payload = PENDING_AP.get(msg_id)
    if not payload:
        return await query.answer(
            "⌛ This pending post has expired or was already handled.", show_alert=True
        )

    if action == "post":
        await client.send_message(
            chat_id=payload["channel"],
            text=payload["text"],
            reply_markup=payload["buttons"],
        )
        if payload["sticker"]:
            await client.send_sticker(
                chat_id=payload["channel"], sticker=payload["sticker"]
            )

        await query.message.edit_text(
            f"✅ **SUCCESSFULLY POSTED TO CHANNEL!**\n\n{payload['text']}"
        )
        PENDING_AP.pop(msg_id, None)

    elif action == "cancel":
        await query.message.edit_text("❌ **Auto-Post Cancelled.**")
        PENDING_AP.pop(msg_id, None)

    elif action == "edit":
        await query.answer()
        prompt_msg = await query.message.reply_text(
            "✏️ **Please send the new formatted text for this post now:**\n(Supports HTML. Wait for confirmation...)"
        )
        try:
            response = await native_listen(
                client, query.message.chat.id, query.from_user.id, timeout=120
            )
            await prompt_msg.delete()

            if response.text:
                new_text = response.text.html
                payload["text"] = new_text
                PENDING_AP[msg_id] = payload

                # Refresh the original message with new text
                pm_markup = InlineKeyboardMarkup(
                    [
                        [create_btn("✅ Post to Channel", callback_data=f"ap_post_1")],
                        [
                            create_btn("✏️ Edit Text", callback_data=f"ap_edit_1"),
                            create_btn("❌ Cancel", callback_data=f"ap_cancel_1"),
                        ],
                    ]
                )
                await query.message.edit_text(
                    f"**🚨 AUTO-POST TRIGGERED (EDITED) 🚨**\n\n{new_text}",
                    reply_markup=pm_markup,
                )

            await response.delete()
        except asyncio.TimeoutError:
            await prompt_msg.edit_text("⌛ Timeout. Edit cancelled.")
