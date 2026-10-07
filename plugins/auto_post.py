import asyncio
import html
import re
import time
import requests
from logging import ERROR, getLogger
from typing import Dict, Tuple, Optional

from motor.motor_asyncio import AsyncIOMotorClient
from pyrogram import Client, enums, filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, CallbackQuery

import info
from plugins.Imdbposter import get_movie_detailsx
from utils import get_size, temp

logger = getLogger(__name__)
logger.setLevel(ERROR)

ap_db = None
try:
    _DB_CLIENT = AsyncIOMotorClient(info.DATABASE_URI)
    _BOT_DB = _DB_CLIENT[info.DATABASE_NAME]
    ap_db = _BOT_DB["autopost_settings"]
except Exception as e:
    logger.error(f"Failed to init ap_db: {e}")

DEFAULT_TEMPLATE = """✅ <b>{title} {year}</b>

<blockquote><b>🔊 : {LANGUAGES}</b>
<b>🖥️ : {RESOLUTIONS}</b>
<b>🎥 : {GENRES}</b>
<b>📺 : #{OTT_PLATFORMS}</b>
<b>📟 : Available In Files.</b>

<b>=========================</b></blockquote>"""

async def get_ap_settings():
    if ap_db is None: return {}
    settings = await ap_db.find_one({"id": "ap_config"})
    if not settings:
        return {
            "enabled": False, 
            "template": DEFAULT_TEMPLATE, 
            "image_mode": "preview",
            "muc_list": [], 
            "apc_list": []  
        }
    return settings

async def save_ap_settings(key, value):
    if ap_db is not None:
        await ap_db.update_one({"id": "ap_config"}, {"$set": {key: value}}, upsert=True)

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
        if not item: return None
        if time.time() > item[0]:
            self._data.pop(key, None)
            return None
        return item[1]

RECENT_POSTS = TTLCache(maxsize=100, ttl=3600) 
PENDING_AP = {} 

id_pattern = re.compile(r"^.\d+$")
ADMIN_USERS = [int(admin) if id_pattern.search(str(admin)) else admin for admin in getattr(info, "ADMINS", [])]

async def admin_check(_, __, message: Message):
    return bool(message.from_user and message.from_user.id in ADMIN_USERS)
admin_filter = filters.create(admin_check)

_WAITING_REQUESTS = {}

@Client.on_message(admin_filter, group=-11)
async def custom_ap_listener(client: Client, message: Message):
    key = (message.chat.id, message.from_user.id)
    if key in _WAITING_REQUESTS:
        future = _WAITING_REQUESTS.pop(key)
        if not future.done(): future.set_result(message)
        message.stop_propagation()

async def native_listen(client: Client, chat_id: int, user_id: int, timeout: int = 300) -> Message:
    loop = asyncio.get_running_loop()
    future = loop.create_future()
    _WAITING_REQUESTS[(chat_id, user_id)] = future
    try: return await asyncio.wait_for(future, timeout=timeout)
    except asyncio.TimeoutError:
        _WAITING_REQUESTS.pop((chat_id, user_id), None)
        raise asyncio.TimeoutError

try:
    from pyrogram.enums import ButtonStyle
    BTN_PRIMARY = getattr(ButtonStyle, "PRIMARY", 1)
    BTN_SUCCESS = getattr(ButtonStyle, "SUCCESS", 3)
    BTN_DANGER = getattr(ButtonStyle, "DANGER", 4)
except ImportError:
    BTN_PRIMARY = 1
    BTN_SUCCESS = 3
    BTN_DANGER = 4

def create_btn(text, url=None, callback_data=None, style=None):
    kwargs = {"text": text}
    if url: kwargs["url"] = url
    if callback_data: kwargs["callback_data"] = callback_data
    if style is not None: kwargs["style"] = style
    try: return InlineKeyboardButton(**kwargs)
    except TypeError:
        kwargs.pop("style", None)
        return InlineKeyboardButton(**kwargs)

def get_html_text(message: Message):
    if message.reply_to_message and message.reply_to_message.text:
        return message.reply_to_message.text.html
    elif len(message.command) > 1:
        html_text = message.text.html
        html_text = re.sub(r'^/\w+(?:@[a-zA-Z0-9_]+)?\s+', '', html_text, count=1)
        return html_text
    return None

def _upload_sync(file_bytes):
    headers = {"User-Agent": "Mozilla/5.0"}
    for upload_url in ["http://telegraph.controller.bot/upload", "https://telegra.ph/upload"]:
        try:
            res = requests.post(upload_url, files={"file": ("img.jpg", file_bytes, "image/jpeg")}, headers=headers, timeout=10)
            if res.status_code == 200:
                data = res.json()
                if isinstance(data, list) and "src" in data[0]: return upload_url.replace("/upload", "") + data[0]["src"]
        except Exception: pass
    try:
        res = requests.post("https://envs.sh", files={"file": ("img.jpg", file_bytes, "image/jpeg")}, headers=headers, timeout=10)
        if res.status_code == 200 and res.text.startswith("http"): return res.text.strip()
    except Exception: pass
    return None

async def upload_image_safely(client: Client, message: Message):
    try:
        file_io = await client.download_media(message, in_memory=True)
        if not file_io: return None, "❌ Failed to download the image."
        url = await asyncio.to_thread(_upload_sync, file_io.getvalue())
        if not url: return None, "❌ All upload servers failed."
        return url, None
    except Exception as e: return None, f"❌ Internal Error: {e}"

# ============================================================
# ⚙️ DYNAMIC CHANNELS MANAGEMENT COMMANDS
# ============================================================
@Client.on_message(filters.command("addmovieupdatechannel") & admin_filter)
async def add_muc(client: Client, message: Message):
    if len(message.command) < 2: return await message.reply_text("⚠️ **Usage:** `/addmovieupdatechannel -100xxxxx`")
    try: chat_id = int(message.command[1])
    except ValueError: return await message.reply_text("❌ Invalid Chat ID.")
    
    settings = await get_ap_settings()
    muc_list = settings.get("muc_list", [])
    if chat_id not in muc_list:
        muc_list.append(chat_id)
        await save_ap_settings("muc_list", muc_list)
        await message.reply_text(f"✅ Successfully added `{chat_id}` to Movie Update Channels!")
    else: await message.reply_text("⚠️ Channel already in the list.")

@Client.on_message(filters.command("remmovieupdatechannel") & admin_filter)
async def rem_muc(client: Client, message: Message):
    if len(message.command) < 2: return await message.reply_text("⚠️ **Usage:** `/remmovieupdatechannel -100xxxxx`")
    try: chat_id = int(message.command[1])
    except ValueError: return await message.reply_text("❌ Invalid Chat ID.")
    
    settings = await get_ap_settings()
    muc_list = settings.get("muc_list", [])
    if chat_id in muc_list:
        muc_list.remove(chat_id)
        await save_ap_settings("muc_list", muc_list)
        await message.reply_text(f"🗑️ Successfully removed `{chat_id}` from Movie Update Channels!")
    else: await message.reply_text("⚠️ Channel not found in the list.")

@Client.on_message(filters.command("allmovieupdatechannel") & admin_filter)
async def all_muc(client: Client, message: Message):
    settings = await get_ap_settings()
    muc_list = settings.get("muc_list", [])
    info_list = info.MOVIE_UPDATE_CHANNEL if isinstance(info.MOVIE_UPDATE_CHANNEL, list) else [info.MOVIE_UPDATE_CHANNEL]
    
    text = "🎬 **All Movie Update Channels:**\n\n**From info.py (Static):**\n"
    for ch in info_list:
        if ch: text += f"• `{ch}`\n"
        
    text += "\n**From Database (Dynamic):**\n"
    if not muc_list: text += "• None added yet.\n"
    else:
        for ch in muc_list: text += f"• `{ch}`\n"
            
    await message.reply_text(text)

@Client.on_message(filters.command("addautopostchannel") & admin_filter)
async def add_apc(client: Client, message: Message):
    if len(message.command) < 2: return await message.reply_text("⚠️ **Usage:** `/addautopostchannel -100xxxxx`")
    try: chat_id = int(message.command[1])
    except ValueError: return await message.reply_text("❌ Invalid Chat ID.")
    
    settings = await get_ap_settings()
    apc_list = settings.get("apc_list", [])
    if chat_id not in apc_list:
        apc_list.append(chat_id)
        await save_ap_settings("apc_list", apc_list)
        await message.reply_text(f"✅ Successfully added `{chat_id}` to Auto-Post Channels!")
    else: await message.reply_text("⚠️ Channel already in the list.")

@Client.on_message(filters.command("remautopostchannel") & admin_filter)
async def rem_apc(client: Client, message: Message):
    if len(message.command) < 2: return await message.reply_text("⚠️ **Usage:** `/remautopostchannel -100xxxxx`")
    try: chat_id = int(message.command[1])
    except ValueError: return await message.reply_text("❌ Invalid Chat ID.")
    
    settings = await get_ap_settings()
    apc_list = settings.get("apc_list", [])
    if chat_id in apc_list:
        apc_list.remove(chat_id)
        await save_ap_settings("apc_list", apc_list)
        await message.reply_text(f"🗑️ Successfully removed `{chat_id}` from Auto-Post Channels!")
    else: await message.reply_text("⚠️ Channel not found in the list.")

@Client.on_message(filters.command("allautopostchannel") & admin_filter)
async def all_apc(client: Client, message: Message):
    settings = await get_ap_settings()
    apc_list = settings.get("apc_list", [])
    info_list = info.AUTOPOSTCHANNEL if isinstance(info.AUTOPOSTCHANNEL, list) else [info.AUTOPOSTCHANNEL]
    
    text = "🧬 **All Auto-Post Channels:**\n\n**From info.py (Static):**\n"
    for ch in info_list:
        if ch: text += f"• `{ch}`\n"
        
    text += "\n**From Database (Dynamic):**\n"
    if not apc_list: text += "• None added yet.\n"
    else:
        for ch in apc_list: text += f"• `{ch}`\n"
            
    await message.reply_text(text)


# ============================================================
# ⚙️ AUTO-POST CONFIGURATION COMMANDS
# ============================================================
@Client.on_message(filters.command("autopost") & admin_filter)
async def toggle_autopost(client: Client, message: Message):
    if len(message.command) < 2:
        settings = await get_ap_settings()
        status = "🟢 ON" if settings.get("enabled") else "🔴 OFF"
        return await message.reply_text(f"**Auto-Post Status:** {status}\n\nUse `/autopost on` or `/autopost off` to toggle.")
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
        return await message.reply_text("⚠️ **Usage:** `/editautopost <text>`\nPlaceholders: `{title}`, `{year}`, `{size}`, `{rating}`, `{LANGUAGES}`, `{RESOLUTIONS}`, `{GENRES}`, `{OTT_PLATFORMS}`")
    await save_ap_settings("template", text)
    await message.reply_text(f"✅ **Main Template Updated!**\n\n{text}")

@Client.on_message(filters.command(["editautoposttittle", "editautoposttitle"]) & admin_filter)
async def cmd_edit_title(client: Client, message: Message):
    text = get_html_text(message)
    if not text: return await message.reply_text("⚠️ **Usage:** `/editautoposttitle <format>`")
    await save_ap_settings("format_title", text)
    await message.reply_text(f"✅ **Title Format Updated!**\n\n{text}")

@Client.on_message(filters.command(["editautopostyear"]) & admin_filter)
async def cmd_edit_year(client: Client, message: Message):
    text = get_html_text(message)
    if not text: return await message.reply_text("⚠️ **Usage:** `/editautopostyear <format>`")
    await save_ap_settings("format_year", text)
    await message.reply_text(f"✅ **Year Format Updated!**\n\n{text}")

@Client.on_message(filters.command(["editautopostlanguages"]) & admin_filter)
async def cmd_edit_langs(client: Client, message: Message):
    text = get_html_text(message)
    if not text: return await message.reply_text("⚠️ **Usage:** `/editautopostlanguages <format>`")
    await save_ap_settings("format_languages", text)
    await message.reply_text(f"✅ **Languages Format Updated!**\n\n{text}")

@Client.on_message(filters.command(["editautopostresolutions"]) & admin_filter)
async def cmd_edit_res(client: Client, message: Message):
    text = get_html_text(message)
    if not text: return await message.reply_text("⚠️ **Usage:** `/editautopostresolutions <format>`")
    await save_ap_settings("format_resolutions", text)
    await message.reply_text(f"✅ **Resolutions Format Updated!**\n\n{text}")

@Client.on_message(filters.command(["editautopostgenres"]) & admin_filter)
async def cmd_edit_genres(client: Client, message: Message):
    text = get_html_text(message)
    if not text: return await message.reply_text("⚠️ **Usage:** `/editautopostgenres <format>`")
    await save_ap_settings("format_genres", text)
    await message.reply_text(f"✅ **Genres Format Updated!**\n\n{text}")

@Client.on_message(filters.command(["editautopostottplatforms"]) & admin_filter)
async def cmd_edit_otts(client: Client, message: Message):
    text = get_html_text(message)
    if not text: return await message.reply_text("⚠️ **Usage:** `/editautopostottplatforms <format>`")
    await save_ap_settings("format_otts", text)
    await message.reply_text(f"✅ **OTT Platforms Format Updated!**\n\n{text}")

@Client.on_message(filters.command("editautopostdirect") & admin_filter)
async def cmd_edit_ap_direct(client: Client, message: Message):
    text = get_html_text(message)
    if not text: return await message.reply_text("⚠️ **Usage:** `/editautopostdirect Download Now 📥`")
    await save_ap_settings("direct_button_text", text)
    await message.reply_text(f"✅ **Direct Search Button Text Updated!** -> {text}")


@Client.on_message(filters.command("setapbtn1") & admin_filter)
async def set_ap_btn1(client: Client, message: Message):
    if len(message.command) < 2 or "|" not in message.text: return await message.reply_text("⚠️ **Usage:** `/setapbtn1 Group 1 🎬 | https://t.me/yourgroup`")
    args = message.text.split(None, 1)[1].split("|")
    await save_ap_settings("btn1", {"text": args[0].strip(), "url": args[1].strip()})
    await message.reply_text(f"✅ **Button 1 Updated!**\nText: {args[0].strip()}\nURL: {args[1].strip()}")

@Client.on_message(filters.command("setapbtn2") & admin_filter)
async def set_ap_btn2(client: Client, message: Message):
    if len(message.command) < 2 or "|" not in message.text: return await message.reply_text("⚠️ **Usage:** `/setapbtn2 Group 2 🎬 | https://t.me/yourgroup`")
    args = message.text.split(None, 1)[1].split("|")
    await save_ap_settings("btn2", {"text": args[0].strip(), "url": args[1].strip()})
    await message.reply_text(f"✅ **Button 2 Updated!**\nText: {args[0].strip()}\nURL: {args[1].strip()}")

@Client.on_message(filters.command("setapbtn3") & admin_filter)
async def set_ap_btn3(client: Client, message: Message):
    if len(message.command) < 2 or "|" not in message.text: return await message.reply_text("⚠️ **Usage:** `/setapbtn3 Direct Search 🔎 | {deep_link}`")
    args = message.text.split(None, 1)[1].split("|")
    await save_ap_settings("btn3", {"text": args[0].strip(), "url": args[1].strip()})
    await message.reply_text(f"✅ **Button 3 Updated!**\nText: {args[0].strip()}\nURL: {args[1].strip()}")

@Client.on_message(filters.command("remapbtn1") & admin_filter)
async def rem_ap_btn1(client: Client, message: Message):
    await save_ap_settings("btn1", None)
    await message.reply_text("🗑️ **Button 1 Removed.**")

@Client.on_message(filters.command("remapbtn2") & admin_filter)
async def rem_ap_btn2(client: Client, message: Message):
    await save_ap_settings("btn2", None)
    await message.reply_text("🗑️ **Button 2 Removed.**")

@Client.on_message(filters.command("remapbtn3") & admin_filter)
async def rem_ap_btn3(client: Client, message: Message):
    await save_ap_settings("btn3", None)
    await message.reply_text("🗑️ **Button 3 Removed.**")

@Client.on_message(filters.command("setautopostimage") & admin_filter)
async def set_autopost_image(client: Client, message: Message):
    ask_msg = await message.reply_text("📸 **Please send the new default Photo or Image URL:**\n*(Or type `blank` to remove the image entirely)*")
    try:
        res = await native_listen(client, message.chat.id, message.from_user.id, timeout=120)
        await ask_msg.delete()
        
        if res.text and res.text.lower() == "blank":
            await save_ap_settings("image", None)
            await res.delete()
            return await message.reply_text("✅ **Default Auto-Post Image Removed.**")
            
        ask_mode = await message.reply_text("⚙️ **How should this image be displayed globally?**\n\nType `1` for **Preview Mode** (Rich Hidden Link)\nType `2` for **Normal Photo** (Attached Media)")
        mode_res = await native_listen(client, message.chat.id, message.from_user.id, timeout=60)
        await ask_mode.delete()
        
        mode = "photo" if "2" in mode_res.text else "preview"
        
        if mode == "preview" and res.photo:
            status_msg = await message.reply_text("⏳ Uploading to secure server for preview...")
            url, err = await upload_image_safely(client, res)
            if not url:
                return await status_msg.edit_text(err)
            await status_msg.delete()
        else:
            url = res.photo.file_id if res.photo else res.text.strip()
            
        await res.delete()
        await mode_res.delete()
        
        await save_ap_settings("image", url)
        await save_ap_settings("image_mode", mode)
        await message.reply_text(f"✅ **Global Image Saved!**\nDisplay Mode: **{mode.title()}**")
        
    except asyncio.TimeoutError:
        await ask_msg.edit_text("⌛ Timeout. Image edit cancelled.")

@Client.on_message(filters.command("remautopostimage") & admin_filter)
async def rem_autopost_image(client: Client, message: Message):
    await save_ap_settings("image", None)
    await message.reply_text("🗑️ **Default Auto-Post Image Removed.** The bot will revert to using dynamic TMDB posters.")

@Client.on_message(filters.command("setautopoststicker") & admin_filter)
async def set_autopost_sticker(client: Client, message: Message):
    if not message.reply_to_message or not message.reply_to_message.sticker:
        return await message.reply_text("⚠️ **Please reply directly to a sticker** with `/setautopoststicker`.")
    await save_ap_settings("sticker", message.reply_to_message.sticker.file_id)
    await message.reply_text("✅ **Auto-Post Sticker Saved!**")

@Client.on_message(filters.command("remautopoststicker") & admin_filter)
async def rem_autopost_sticker(client: Client, message: Message):
    await save_ap_settings("sticker", None)
    await message.reply_text("🗑️ **Auto-Post Sticker Removed.**")


@Client.on_message(filters.chat(info.FILE_STORE_CHANNEL) & (filters.document | filters.video | filters.audio))
async def auto_post_trigger(client: Client, message: Message):
    settings = await get_ap_settings()
    if not settings.get("enabled", False):
        return

    info_apc = info.AUTOPOSTCHANNEL if isinstance(info.AUTOPOSTCHANNEL, list) else [info.AUTOPOSTCHANNEL]
    db_apc = settings.get("apc_list", [])
    update_channels = list(set([int(ch) for ch in info_apc + db_apc if ch]))
    
    if not update_channels:
        info_muc = info.MOVIE_UPDATE_CHANNEL if isinstance(info.MOVIE_UPDATE_CHANNEL, list) else [info.MOVIE_UPDATE_CHANNEL]
        db_muc = settings.get("muc_list", [])
        update_channels = list(set([int(ch) for ch in info_muc + db_muc if ch]))
        
    if not update_channels: return

    try:
        media = message.document or message.video or message.audio
        if not media: return
        
        file_name = getattr(media, "file_name", "Unknown")
        file_size = getattr(media, "file_size", 0)
        size_str = get_size(file_size)

        clean_name = re.sub(r"(?i)\[?@?sandalwood[^\]\s]*\]?", "", file_name)
        clean_name = re.sub(r"[_.-]", " ", clean_name)
        
        lang_matches = re.findall(r"(?i)\b(Kannada|English|Gujarati|Hindi|Bengali|Malayalam|Marathi|Punjabi|Tamil|Telugu|Urdu|Dual Audio|Multi Audio)\b", clean_name)
        langs = list(set([l.title() for l in lang_matches]))
        langs_str = ", ".join(langs) if langs else ""

        res_matches = re.findall(r"(?i)\b(WEB-DL|HDRip|HDTC|1080p|720p|480p|1440p|2160p|4k|BluRay|BDRip|WEBRip|HDTVRip|DVDRip|CAMRip|HEVC)\b", clean_name)
        res = list(set([r.upper() if 'p' not in r.lower() else r.lower() for r in res_matches]))
        res_str = ", ".join(res) if res else ""

        ott_matches = re.findall(r"(?i)\b(Netflix|Amazon Prime|Prime Video|Aha|Zee5|Hotstar|Disney\+?|JioCinema|SonyLIV|SunNXT|Voot|Hulu|HBO|Apple TV|AppleTV|Crunchyroll)\b", clean_name)
        otts = list(set([o.title().replace("Appletv", "Apple TV").replace("Disney+", "Disney") for o in ott_matches]))
        otts_str = ", ".join(otts) if otts else ""

        search_name = re.sub(r"(?i)\b(1080p|720p|480p|2160p|4k|WEB-DL|HDRip|HDTC|BDRip|BluRay|DVDRip|WEBRip|CAMRip|HEVC|mkv|mp4|avi|hindi|kannada|telugu|tamil|malayalam|english|dual audio|multi audio|dual|multi|subs|episodes|season\s*\d+|s\d+e\d+|Netflix|Prime|Aha|Zee5|Hotstar|JioCinema|SonyLIV|Voot)\b", "", clean_name)
        search_name = re.sub(r"\b(19\d{2}|20\d{2})\b", "", search_name)
        search_name = re.sub(r"\s+", " ", search_name).strip()

        if RECENT_POSTS.get(search_name): return 
        RECENT_POSTS.set(search_name, True)

        movie_details = await get_movie_detailsx(search_name)
        title = movie_details.get("title", search_name) if movie_details else search_name
        year = movie_details.get("year", "N/A") if movie_details else "N/A"
        rating = movie_details.get("rating", "N/A") if movie_details else "N/A"
        
        tmdb_genres = movie_details.get("genres", []) if movie_details else []
        genres_str = ", ".join(tmdb_genres) if tmdb_genres else ""
        plot = movie_details.get("plot", "N/A") if movie_details else "N/A"
        
        custom_img = settings.get("image")
        poster = custom_img if custom_img else (movie_details.get("poster_url") if movie_details else None)
        image_mode = settings.get("image_mode", "preview")

        fmt_title = settings.get("format_title", "✅ <b>{title}</b>")
        fmt_year = settings.get("format_year", "<b>{year}</b>")
        fmt_langs = settings.get("format_languages", "<b>🔊 : {langs}</b>")
        fmt_res = settings.get("format_resolutions", "<b>🖥️ : {resolutions}</b>")
        fmt_gens = settings.get("format_genres", "<b>🎥 : {genres}</b>")
        fmt_otts = settings.get("format_otts", "<b>📺 : #{otts}</b>")

        val_title = fmt_title.replace("{title}", html.escape(title))
        val_year = fmt_year.replace("{year}", html.escape(str(year))) if str(year) != "N/A" else ""
        val_langs = fmt_langs.replace("{langs}", langs_str).replace("{LANGUAGES}", langs_str) if langs_str else ""
        val_res = fmt_res.replace("{resolutions}", res_str).replace("{RESOLUTIONS}", res_str) if res_str else ""
        val_gens = fmt_gens.replace("{genres}", genres_str).replace("{GENRES}", genres_str) if genres_str else ""
        val_otts = fmt_otts.replace("{otts}", otts_str).replace("{OTT_PLATFORMS}", otts_str) if otts_str else ""

        template_str = settings.get("template", DEFAULT_TEMPLATE)
        text = template_str.replace("{title}", val_title).replace("{year}", val_year)
        
        for tag, val in [("{LANGUAGES}", val_langs), ("{RESOLUTIONS}", val_res), ("{GENRES}", val_gens), ("{OTT_PLATFORMS}", val_otts)]:
            if val: text = text.replace(tag, val)
            else: text = re.sub(rf'[^\n]*{re.escape(tag)}[^\n]*\n?', '', text) 

        if image_mode == "photo" and len(plot) > 250: plot = plot[:250] + "..."

        text = text.replace("{size}", size_str).replace("{rating}", html.escape(str(rating))).replace("{plot}", html.escape(str(plot))).replace("{file_name}", html.escape(file_name))
        text += f"\n\n<b>Jᴏɪɴ: @Sandalwood_Kannada_Moviesz</b>"

        if poster and image_mode == "preview": text = f"{text}\n<a href='{poster}'>&#8205;</a>"

        bot_me = await client.get_me()
        bot_username = bot_me.username
        safe_query = re.sub(r"[^a-zA-Z0-9_-]", "_", f"{title} {year}" if str(year) != "N/A" else title).strip("_")[:50]
        deep_link = f"https://t.me/{bot_username}?start=search_{safe_query}"

        btn1 = settings.get("btn1", {"text": "Group 1 🎬", "url": "https://t.me/Sandalwood_Kannada_Group"})
        btn2 = settings.get("btn2", {"text": "Group 2 🎬", "url": "https://t.me/+GLsPkRgLGGszMzY1"})
        btn3 = settings.get("btn3", {"text": "Direct Search 🔎", "url": "{deep_link}"})

        btn_layout = []
        if btn1 or btn2:
            row = []
            if btn1: row.append(create_btn(btn1["text"], url=btn1["url"].replace("{deep_link}", deep_link), style=BTN_PRIMARY))
            if btn2: row.append(create_btn(btn2["text"], url=btn2["url"].replace("{deep_link}", deep_link), style=BTN_PRIMARY))
            btn_layout.append(row)
        if btn3:
            btn_layout.append([create_btn(btn3["text"], url=btn3["url"].replace("{deep_link}", deep_link), style=BTN_SUCCESS)])

        target_admin = message.from_user.id if message.from_user and message.from_user.id in ADMIN_USERS else ADMIN_USERS[0]
        
        pm_markup_layout = []
        pm_markup_layout.extend(btn_layout) 
        pm_markup_layout.append([create_btn("✅ Post to Channel", callback_data=f"ap_post_1", style=BTN_SUCCESS)])
        pm_markup_layout.append([
            create_btn("✏️ Edit Text", callback_data=f"ap_edit_1", style=BTN_PRIMARY),
            create_btn("📸 Edit Image", callback_data=f"ap_editimg_1", style=BTN_PRIMARY)
        ])
        pm_markup_layout.append([create_btn("❌ Cancel", callback_data=f"ap_cancel_1", style=BTN_DANGER)])

        if poster and image_mode == "photo":
            ask_msg = await client.send_photo(chat_id=target_admin, photo=poster, caption=f"**🚨 AUTO-POST TRIGGERED 🚨**\n\n{text}", reply_markup=InlineKeyboardMarkup(pm_markup_layout))
        else:
            ask_msg = await client.send_message(chat_id=target_admin, text=f"**🚨 AUTO-POST TRIGGERED 🚨**\n\n{text}", reply_markup=InlineKeyboardMarkup(pm_markup_layout))

        PENDING_AP[str(ask_msg.id)] = {
            "text": text,
            "buttons": InlineKeyboardMarkup(btn_layout),
            "channels": update_channels, 
            "sticker": settings.get("sticker"),
            "poster": poster,
            "image_mode": image_mode
        }

    except Exception as e:
        logger.error(f"Auto-Post Engine Failed: {e}")

@Client.on_callback_query(filters.regex(r"^ap_(post|edit|editimg|cancel)_") & admin_filter)
async def ap_approval_callback(client: Client, query: CallbackQuery):
    action = query.data.split("_")[1]
    msg_id = str(query.message.id)
    
    payload = PENDING_AP.get(msg_id)
    if not payload:
        return await query.answer("⌛ This pending post has expired or was already handled.", show_alert=True)

    if action == "post":
        for ch_id in payload["channels"]:
            try:
                if payload["poster"] and payload["image_mode"] == "photo":
                    await client.send_photo(chat_id=ch_id, photo=payload["poster"], caption=payload["text"], reply_markup=payload["buttons"])
                else:
                    await client.send_message(chat_id=ch_id, text=payload["text"], reply_markup=payload["buttons"])
                    
                if payload["sticker"]:
                    await client.send_sticker(chat_id=ch_id, sticker=payload["sticker"])
            except Exception as e:
                logger.error(f"Failed to post to channel {ch_id}: {e}")
        
        await query.answer("✅ Successfully Posted to all channels!", show_alert=False)
        try: await query.message.delete()
        except Exception: pass
        PENDING_AP.pop(msg_id, None)

    elif action == "cancel":
        await query.message.edit_text("❌ **Auto-Post Cancelled.**")
        PENDING_AP.pop(msg_id, None)

    elif action == "edit":
        await query.answer()
        prompt_msg = await query.message.reply_text("✏️ **Please send the new formatted text for this post now:**\n(Supports HTML. Wait for confirmation...)")
        try:
            response = await native_listen(client, query.message.chat.id, query.from_user.id, timeout=120)
            await prompt_msg.delete()
            
            if response.text:
                new_text = response.text.html
                if payload["poster"] and payload["image_mode"] == "preview" and "<a href=" not in new_text:
                    new_text = f"{new_text}\n<a href='{payload['poster']}'>&#8205;</a>"
                    
                payload["text"] = new_text
                PENDING_AP[msg_id] = payload
                
                pm_markup_layout = []
                if payload["buttons"] and getattr(payload["buttons"], "inline_keyboard", None):
                    pm_markup_layout.extend(payload["buttons"].inline_keyboard)
                
                pm_markup_layout.append([create_btn("✅ Post to Channel", callback_data=f"ap_post_1", style=BTN_SUCCESS)])
                pm_markup_layout.append([
                    create_btn("✏️ Edit Text", callback_data=f"ap_edit_1", style=BTN_PRIMARY),
                    create_btn("📸 Edit Image", callback_data=f"ap_editimg_1", style=BTN_PRIMARY)
                ])
                pm_markup_layout.append([create_btn("❌ Cancel", callback_data=f"ap_cancel_1", style=BTN_DANGER)])
                
                if payload["poster"] and payload["image_mode"] == "photo":
                    await query.message.edit_caption(f"**🚨 AUTO-POST TRIGGERED (EDITED) 🚨**\n\n{new_text}", reply_markup=InlineKeyboardMarkup(pm_markup_layout))
                else:
                    await query.message.edit_text(f"**🚨 AUTO-POST TRIGGERED (EDITED) 🚨**\n\n{new_text}", reply_markup=InlineKeyboardMarkup(pm_markup_layout))
            
            await response.delete()
        except asyncio.TimeoutError:
            await prompt_msg.edit_text("⌛ Timeout. Edit cancelled.")

    elif action == "editimg":
        await query.answer()
        prompt_msg = await query.message.reply_text("📸 **Please send the new Photo or Image URL for this specific post:**\n*(Wait for confirmation...)*")
        try:
            response = await native_listen(client, query.message.chat.id, query.from_user.id, timeout=120)
            await prompt_msg.delete()
            
            ask_mode = await query.message.reply_text("⚙️ **How should this new image be displayed?**\nType `1` for **Preview Mode** (Hidden Link)\nType `2` for **Normal Photo** (Attached Media)")
            mode_res = await native_listen(client, query.message.chat.id, query.from_user.id, timeout=60)
            await ask_mode.delete()
            new_mode = "photo" if "2" in mode_res.text else "preview"
            
            if new_mode == "preview" and response.photo:
                status_msg = await query.message.reply_text("⏳ Uploading to secure server...")
                new_poster, err = await upload_image_safely(client, response)
                if not new_poster:
                    return await status_msg.edit_text(err)
                await status_msg.delete()
            else:
                new_poster = response.photo.file_id if response.photo else response.text.strip()
                
            await response.delete()
            await mode_res.delete()
            
            payload["poster"] = new_poster
            payload["image_mode"] = new_mode
            
            clean_text = re.sub(r"\n<a href='.*?'>&#8205;</a>", "", payload["text"])
            
            if new_mode == "preview":
                final_text = f"{clean_text}\n<a href='{new_poster}'>&#8205;</a>"
            else:
                final_text = clean_text[:1024]
                
            payload["text"] = final_text
            
            pm_markup_layout = []
            if payload["buttons"] and getattr(payload["buttons"], "inline_keyboard", None):
                pm_markup_layout.extend(payload["buttons"].inline_keyboard)
            
            pm_markup_layout.append([create_btn("✅ Post to Channel", callback_data=f"ap_post_1", style=BTN_SUCCESS)])
            pm_markup_layout.append([
                create_btn("✏️ Edit Text", callback_data=f"ap_edit_1", style=BTN_PRIMARY),
                create_btn("📸 Edit Image", callback_data=f"ap_editimg_1", style=BTN_PRIMARY)
            ])
            pm_markup_layout.append([create_btn("❌ Cancel", callback_data=f"ap_cancel_1", style=BTN_DANGER)])
            
            await query.message.delete()
            
            if new_mode == "photo":
                new_ask_msg = await client.send_photo(
                    chat_id=query.message.chat.id, 
                    photo=new_poster, 
                    caption=f"**🚨 AUTO-POST TRIGGERED (EDITED) 🚨**\n\n{final_text}", 
                    reply_markup=InlineKeyboardMarkup(pm_markup_layout)
                )
            else:
                new_ask_msg = await client.send_message(
                    chat_id=query.message.chat.id, 
                    text=f"**🚨 AUTO-POST TRIGGERED (EDITED) 🚨**\n\n{final_text}", 
                    reply_markup=InlineKeyboardMarkup(pm_markup_layout),
                    disable_web_page_preview=False
                )
                
            PENDING_AP[str(new_ask_msg.id)] = payload
            PENDING_AP.pop(msg_id, None)
            
        except asyncio.TimeoutError:
            await prompt_msg.edit_text("⌛ Timeout. Image edit cancelled.")
