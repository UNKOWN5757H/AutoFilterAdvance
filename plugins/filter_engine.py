import asyncio
import base64
import difflib
import re
import urllib.parse
from logging import ERROR, getLogger

import requests
from motor.motor_asyncio import AsyncIOMotorClient
from pyrogram import Client, filters, enums
from pyrogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import info
from database.ia_filterdb import Media as _Media
from plugins.delete import schedule_file_with_countdown, get_del_setting

logger = getLogger(__name__)
logger.setLevel(ERROR)

# MongoDB VIP Connection
_vip_db = None
try:
    _DB_CLIENT = AsyncIOMotorClient(info.DATABASE_URI)
    _BOT_DB = _DB_CLIENT[info.DATABASE_NAME]
    _vip_db = _BOT_DB["fsub_vips"]
except Exception as e:
    logger.error(f"Failed to init VIP DB in filter_engine: {e}")

async def is_vip(user_id: int) -> bool:
    if _vip_db is not None:
        doc = await _vip_db.find_one({"user_id": user_id})
        return bool(doc)
    return False

# ============================================================
# 🔐 DMCA ANTI-BAN TOKEN ENCRYPTION / DECRYPTION
# ============================================================
def encode_file_token(file_id: str) -> str:
    raw_bytes = file_id.encode("utf-8")
    return base64.urlsafe_b64encode(raw_bytes).decode("utf-8").rstrip("=")

def decode_file_token(token: str) -> str:
    padding = 4 - (len(token) % 4)
    if padding != 4:
        token += "=" * padding
    return base64.urlsafe_b64decode(token.encode("utf-8")).decode("utf-8")

# ============================================================
# 💰 AUTO-MONETIZATION SHORTLINK ENGINE
# ============================================================
async def get_monetized_link(user_id: int, original_url: str) -> str:
    # VIPs bypass shortlinks entirely
    if await is_vip(user_id):
        return original_url

    shortener_api = getattr(info, "SHORTENER_API", "")
    shortener_url = getattr(info, "SHORTENER_URL", "")

    if not (shortener_api and shortener_url):
        return original_url

    try:
        api_endpoint = f"https://{shortener_url}/api?api={shortener_api}&url={urllib.parse.quote(original_url)}"
        res = await asyncio.to_thread(requests.get, api_endpoint, timeout=5)
        data = res.json()
        if data.get("status") == "success" or "shortenedUrl" in data:
            return data.get("shortenedUrl") or data.get("url")
    except Exception:
        pass
    return original_url

# ============================================================
# 🔍 METADATA EXTRACTION (SERIES, QUALITY, LANGUAGES)
# ============================================================
LANGUAGES_MAP = {
    "kannada": "Kannada", "hindi": "Hindi", "english": "English",
    "tamil": "Tamil", "telugu": "Telugu", "malayalam": "Malayalam",
    "bengali": "Bengali", "marathi": "Marathi", "punjabi": "Punjabi"
}
QUALITIES_LIST = ["480p", "720p", "1080p", "1440p", "2160p", "4k"]

def extract_quality(name: str):
    name_low = name.lower()
    for q in QUALITIES_LIST:
        if q in name_low: return q.upper()
    return None

def extract_language(name: str):
    name_low = name.lower()
    for key, label in LANGUAGES_MAP.items():
        if key in name_low: return label
    return None

def extract_season_episode(name: str):
    match = re.search(r"s(\d+)\s*e(\d+)|season\s*(\d+).*episode\s*(\d+)", name, re.IGNORECASE)
    if match:
        s = match.group(1) or match.group(3)
        e = match.group(2) or match.group(4)
        return int(s), int(e)
    match_s = re.search(r"season\s*(\d+)|s(\d+)", name, re.IGNORECASE)
    if match_s:
        s = match_s.group(1) or match_s.group(2)
        return int(s), None
    return None, None

# ============================================================
# 🎬 AUTO-FILTER & TYPO-PROOF FUZZY SEARCH
# ============================================================
@Client.on_message(filters.text & filters.group & ~filters.bot, group=1)
async def auto_filter_group_engine(client: Client, message: Message):
    if message.text.startswith("/"): return
    query_str = message.text.strip()
    if len(query_str) < 2: return

    # Query matching documents
    raw_query = {"file_name": {"$regex": re.escape(query_str), "$options": "i"}}
    cursor = _Media.collection.find(raw_query).limit(50)
    files = await cursor.to_list(length=50)

    # Typo-proof fuzzy search fallback if no direct matches are found
    if not files:
        sample_docs = await _Media.collection.find({}, {"file_name": 1}).limit(200).to_list(length=200)
        names = [d.get("file_name", "") for d in sample_docs]
        matches = difflib.get_close_matches(query_str, names, n=1, cutoff=0.5)

        if matches:
            suggested = matches[0]
            btn = [[InlineKeyboardButton(f"🔍 Search '{suggested}'", callback_data=f"search_fuzzy:{suggested[:30]}")] ]
            return await message.reply_text(
                f"🤔 **Movie Not Found!**\n\nDid you mean: **{suggested}**?",
                reply_markup=InlineKeyboardMarkup(btn)
            )
        return

    # Check for multi-season episodic series
    series_detected = False
    seasons = set()
    for f in files:
        s, _ = extract_season_episode(f.get("file_name", ""))
        if s is not None:
            series_detected = True
            seasons.add(s)

    # Netflix-Style Series Folder View
    if series_detected and len(seasons) > 1:
        season_btns = []
        for s in sorted(seasons):
            season_btns.append(InlineKeyboardButton(f"📺 Season {s}", callback_data=f"filter_season:{query_str[:25]}:{s}"))
        keyboard = [season_btns[i:i+3] for i in range(0, len(season_btns), 3)]
        return await message.reply_text(
            f"🎬 **{query_str.title()}**\n\nThis title includes multiple seasons. Select one below:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    # Standard Filter View with Dynamic Filter Badges
    await render_file_results(client, message, files, query_str)

async def render_file_results(client: Client, message: Message, files: list, query_str: str, lang_filter: str = None, qual_filter: str = None):
    bot_user = (await client.get_me()).username
    filtered_files = []

    for f in files:
        fn = f.get("file_name", "")
        f_lang = extract_language(fn)
        f_qual = extract_quality(fn)
        if lang_filter and f_lang != lang_filter: continue
        if qual_filter and f_qual != qual_filter: continue
        filtered_files.append(f)

    if not filtered_files:
        filtered_files = files  # Fall back to showing all files if filters match nothing

    buttons = []
    for f in filtered_files[:10]:
        file_name = f.get("file_name", "File")
        file_id = f.get("_id")
        file_size_mb = f.get("file_size", 0) / (1024 * 1024)
        token = encode_file_token(str(file_id))

        # Secure start link with DMCA-safe token
        direct_link = f"https://t.me/{bot_user}?start=file_{token}"
        final_url = await get_monetized_link(message.from_user.id if message.from_user else 0, direct_link)
        buttons.append([InlineKeyboardButton(f"📁 [{file_size_mb:.1f}MB] {file_name[:40]}", url=final_url)])

    # Language and Quality selector row
    filter_row = [
        InlineKeyboardButton("🔊 Languages", callback_data=f"opt_lang:{query_str[:25]}"),
        InlineKeyboardButton("🖥️ Quality", callback_data=f"opt_qual:{query_str[:25]}")
    ]
    buttons.append(filter_row)

    msg = await message.reply_text(
        f"🔎 **Search Results for:** `{query_str}`\nFiles found: `{len(filtered_files)}`",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

    # Attach live countdown auto-delete timer
    delay = await get_del_setting("FILE_AUTO_DELETE", 1800)
    await schedule_file_with_countdown(client, msg, delay, base_buttons=buttons)

# ============================================================
# 🎛️ INLINE FILTER CALLBACK HANDLERS
# ============================================================
@Client.on_callback_query(filters.regex(r"^opt_lang:(.*)"))
async def select_language_cb(client: Client, query: CallbackQuery):
    q_str = query.matches[0].group(1)
    btns = [
        [InlineKeyboardButton("Kannada", callback_data=f"flt_l:{q_str}:Kannada"), InlineKeyboardButton("Hindi", callback_data=f"flt_l:{q_str}:Hindi")],
        [InlineKeyboardButton("English", callback_data=f"flt_l:{q_str}:English"), InlineKeyboardButton("Tamil", callback_data=f"flt_l:{q_str}:Tamil")],
        [InlineKeyboardButton("🔙 Reset Filter", callback_data=f"search_fuzzy:{q_str}")]
    ]
    await query.message.edit_reply_markup(InlineKeyboardMarkup(btns))

@Client.on_callback_query(filters.regex(r"^opt_qual:(.*)"))
async def select_quality_cb(client: Client, query: CallbackQuery):
    q_str = query.matches[0].group(1)
    btns = [
        [InlineKeyboardButton("480p", callback_data=f"flt_q:{q_str}:480P"), InlineKeyboardButton("720p", callback_data=f"flt_q:{q_str}:720P")],
        [InlineKeyboardButton("1080p", callback_data=f"flt_q:{q_str}:1080P"), InlineKeyboardButton("4K / 2160p", callback_data=f"flt_q:{q_str}:4K")],
        [InlineKeyboardButton("🔙 Reset Filter", callback_data=f"search_fuzzy:{q_str}")]
    ]
    await query.message.edit_reply_markup(InlineKeyboardMarkup(btns))

@Client.on_callback_query(filters.regex(r"^flt_l:(.*?):(.*)"))
async def apply_lang_filter(client: Client, query: CallbackQuery):
    q_str = query.matches[0].group(1)
    lang = query.matches[0].group(2)
    files = await _Media.collection.find({"file_name": {"$regex": re.escape(q_str), "$options": "i"}}).to_list(50)
    await render_file_results(client, query.message, files, q_str, lang_filter=lang)
    await query.answer(f"Filtered by {lang}")

@Client.on_callback_query(filters.regex(r"^flt_q:(.*?):(.*)"))
async def apply_qual_filter(client: Client, query: CallbackQuery):
    q_str = query.matches[0].group(1)
    qual = query.matches[0].group(2)
    files = await _Media.collection.find({"file_name": {"$regex": re.escape(q_str), "$options": "i"}}).to_list(50)
    await render_file_results(client, query.message, files, q_str, qual_filter=qual)
    await query.answer(f"Filtered by {qual}")

@Client.on_callback_query(filters.regex(r"^search_fuzzy:(.*)"))
async def search_fuzzy_cb(client: Client, query: CallbackQuery):
    q_str = query.matches[0].group(1)
    files = await _Media.collection.find({"file_name": {"$regex": re.escape(q_str), "$options": "i"}}).to_list(50)
    await render_file_results(client, query.message, files, q_str)
    await query.answer()

# ============================================================
# 🚀 DMCA SECURE DISPATCHER (?start=file_<token>)
# ============================================================
@Client.on_message(filters.command("start") & filters.private)
async def secure_dmca_dispatch(client: Client, message: Message):
    if len(message.command) > 1 and message.command[1].startswith("file_"):
        token = message.command[1].replace("file_", "")
        try:
            target_id = decode_file_token(token)
            doc = await _Media.collection.find_one({"_id": target_id})
            if not doc:
                return await message.reply_text("❌ **File not found or link has expired.**")

            raw_file_id = doc.get("file_id")
            caption = f"🎬 **File:** `{doc.get('file_name')}`\n\n⚡ *Delivered securely.*"

            # Fresh cached dispatch avoids copyright/origin forward headers
            msg = await client.send_cached_media(
                chat_id=message.chat.id,
                file_id=raw_file_id,
                caption=caption
            )

            # Apply countdown auto-delete timer
            delay = await get_del_setting("FILE_AUTO_DELETE", 1800)
            await schedule_file_with_countdown(client, msg, delay)

        except Exception as e:
            logger.error(f"Secure Dispatch Error: {e}")
            await message.reply_text("⚠️ **Error delivering file.** The link may be corrupted.")
