import asyncio
import html
import re
import time
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
    if ap_db is None: return {}
    settings = await ap_db.find_one({"id": "ap_config"})
    if not settings:
        return {"enabled": False, "template": DEFAULT_TEMPLATE, "image_mode": "preview"}
    return settings

async def save_ap_settings(key, value):
    if ap_db is not None:
        await ap_db.update_one({"id": "ap_config"}, {"$set": {key: value}}, upsert=True)

# ⚡ ONE MOVIE ONE POST CACHE (1-Hour Cooldown)
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

# ⚡ ADMIN FILTER
id_pattern = re.compile(r"^.\d+$")
ADMIN_USERS = [int(admin) if id_pattern.search(str(admin)) else admin for admin in getattr(info, "ADMINS", [])]

async def admin_check(_, __, message: Message):
    return bool(message.from_user and message.from_user.id in ADMIN_USERS)
admin_filter = filters.create(admin_check)

# ⚡ PM NATIVE LISTENER (For Interactive Editing)
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

class SafeDict(dict):
    def __missing__(self, key): return "{" + key + "}"

def get_html_text(message: Message):
    if message.reply_to_message and message.reply_to_message.text:
        return message.reply_to_message.text.html
    elif len(message.command) > 1:
        html_text = message.text.html
        html_text = re.sub(r'^/\w+(?:@[a-zA-Z0-9_]+)?\s+', '', html_text, count=1)
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


# ⚡ INTERACTIVE IMAGE EDITOR
@Client.on_message(filters.command(["editautopostimage", "setautopostimage"]) & admin_filter)
async def edit_ap_image(client: Client, message: Message):
    ask_msg = await message.reply_text("📸 **Please send the new Photo or Image URL:**\n*(Or type `blank` to remove the image entirely)*")
    try:
        res = await native_listen(client, message.chat.id, message.from_user.id, timeout=120)
        await ask_msg.delete()
        
        if res.text and res.text.lower() == "blank":
            await save_ap_settings("image", None)
            await res.delete()
            return await message.reply_text("✅ **Auto-Post Image Removed.**")
            
        url = res.photo.file_id if res.photo else res.text.strip()
        await res.delete()
        
        ask_mode = await message.reply_text("⚙️ **How should this image be displayed?**\n\nType `1` for **Preview Mode** (Rich Hidden Link)\nType `2` for **Normal Photo** (Attached Media)")
        mode_res = await native_listen(client, message.chat.id, message.from_user.id, timeout=60)
        await ask_mode.delete()
        
        mode = "photo" if "2" in mode_res.text else "preview"
        await mode_res.delete()
        
        await save_ap_settings("image", url)
        await save_ap_settings("image_mode", mode)
        await message.reply_text(f"✅ **Image Saved!**\nDisplay Mode: **{mode.title()}**")
        
    except asyncio.TimeoutError:
        await ask_msg.edit_text("⌛ Timeout. Image edit cancelled.")

@Client.on_message(filters.command("remautopostimage") & admin_filter)
async def rem_autopost_image(client: Client, message: Message):
    await save_ap_settings("image", None)
    await message.reply_text("🗑️ **Auto-Post Image Removed.** The bot will revert to using dynamic TMDB posters.")


# ⚡ EDIT ALREADY POSTED MESSAGES IN CHANNEL
@Client.on_message(filters.command(["editautopostchannel"]) & admin_filter)
async def edit_ap_channel(client: Client, message: Message):
    if len(message.command) < 2: 
        return await message.reply_text("⚠️ **Usage:** `/editautopostchannel https://t.me/yourchannel/123`")
    
    link = message.command[1]
    try:
        if "t.me/c/" in link:
            parts = link.split("/")
            chat_id, msg_id = int("-100" + parts[-2]), int(parts[-1])
        elif "t.me/" in link:
            parts = link.split("/")
            chat_id = parts[-2]
            if not chat_id.startswith("@"): chat_id = "@" + chat_id
            msg_id = int(parts[-1])
        else: return await message.reply_text("❌ Invalid Telegram link format.")

        status_msg = await message.reply_text("⏳ Fetching post from channel...")
        target_msg = await client.get_messages(chat_id, msg_id)
        if not target_msg or target_msg.empty: 
            return await status_msg.edit_text("❌ Message not found. Make sure the bot is an admin in the channel.")
            
        html_text = target_msg.text.html if target_msg.text else (target_msg.caption.html if target_msg.caption else "")
        
        # Scrape Title
        title_match = re.search(r"^[✅🎬]\s*<b>(.*?)(?:\s+(\d{4}))?</b>", html_text)
        if not title_match:
            return await status_msg.edit_text("❌ Could not detect the movie name in that post.")
            
        search_name = title_match.group(1).strip()
        await status_msg.edit_text(f"⏳ Rebuilding post for **{search_name}**...")
        
        # We manually trigger the engine logic below
        settings = await get_ap_settings()
        movie_details = await get_movie_detailsx(search_name)
        
        title = movie_details.get("title", search_name) if movie_details else search_name
        year = movie_details.get("year", "N/A") if movie_details else "N/A"
        rating = movie_details.get("rating", "N/A") if movie_details else "N/A"
        tmdb_genres = movie_details.get("genres", []) if movie_details else []
        genres_str = ", ".join(tmdb_genres) if tmdb_genres else ""
        plot = movie_details.get("plot", "N/A") if movie_details else "N/A"
        
        # Try to salvage resolutions and langs from original post
        l_match = re.search(r"🔊\s*:\s*(.*?)</[bB]>", html_text)
        langs_str = l_match.group(1).strip() if l_match and l_match.group(1).strip() != "N/A" else ""
        
        r_match = re.search(r"🖥️\s*:\s*(.*?)</[bB]>", html_text)
        res_str = r_match.group(1).strip() if r_match and r_match.group(1).strip() != "N/A" else ""
        
        o_match = re.search(r"📺\s*:\s*#?(.*?)</[bB]>", html_text)
        otts_str = o_match.group(1).strip() if o_match and o_match.group(1).strip() != "N/A" else ""

        # Formatting
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

        # Safe truncation for Photo mode
        image_mode = settings.get("image_mode", "preview")
        if image_mode == "photo" and len(plot) > 250: plot = plot[:250] + "..."
        
        text = text.replace("{size}", "Available in Files").replace("{rating}", html.escape(str(rating))).replace("{plot}", html.escape(str(plot))).replace("{file_name}", "File")
        text += f"\n\n<b>Jᴏɪɴ: @Sandalwood_Kannada_Moviesz</b>"

        bot_me = await client.get_me()
        bot_username = bot_me.username
        safe_query = re.sub(r"[^a-zA-Z0-9_-]", "_", f"{title} {year}" if str(year) != "N/A" else title).strip("_")[:50]
        deep_link = f"https://t.me/{bot_username}?start=search_{safe_query}"

        direct_text = settings.get("direct_button_text", "Direct Search 🔎")
        btn = InlineKeyboardMarkup([
            [create_btn(text="Group 1 🎬", url="https://t.me/Sandalwood_Kannada_Group"), create_btn(text="Group 2 🎬", url="https://t.me/+GLsPkRgLGGszMzY1")],
            [create_btn(text=direct_text, url=deep_link)]
        ])

        custom_img = settings.get("image")
        poster = custom_img if custom_img else (movie_details.get("poster_url") if movie_details else None)

        if image_mode == "photo" and poster and target_msg.photo:
            await client.edit_message_caption(chat_id=chat_id, message_id=msg_id, caption=text, reply_markup=btn)
        else:
            if poster and image_mode == "preview": text = f"{text}\n<a href='{poster}'>&#8205;</a>"
            await client.edit_message_text(chat_id=chat_id, message_id=msg_id, text=text, reply_markup=btn, disable_web_page_preview=False)
            
        await status_msg.edit_text(f"✅ **Post successfully updated in channel!**")

    except Exception as e:
        await message.reply_text(f"❌ Edit Failed: {e}")


# ============================================================
# 🚀 THE MAIN AUTO-POST LISTENER ENGINE 
# ============================================================
@Client.on_message(filters.chat(info.FILE_STORE_CHANNEL) & (filters.document | filters.video | filters.audio))
async def auto_post_trigger(client: Client, message: Message):
    settings = await get_ap_settings()
    if not settings.get("enabled", False):
        return

    update_channel = getattr(info, "AUTOPOSTCHANNEL", getattr(info, "MOVIE_UPDATE_CHANNEL", None))
    if not update_channel: return

    try:
        media = message.document or message.video or message.audio
        if not media: return
        
        file_name = getattr(media, "file_name", "Unknown")
        file_size = getattr(media, "file_size", 0)
        size_str = get_size(file_size)

        clean_name = re.sub(r"(?i)\[?@?sandalwood[^\]\s]*\]?", "", file_name)
        clean_name = re.sub(r"[_.-]", " ", clean_name)
        
        # ⚡ EXTRACT LANGUAGES
        lang_matches = re.findall(r"(?i)\b(Kannada|English|Gujarati|Hindi|Bengali|Malayalam|Marathi|Punjabi|Tamil|Telugu|Urdu|Dual Audio|Multi Audio)\b", clean_name)
        langs = list(set([l.title() for l in lang_matches]))
        langs_str = ", ".join(langs) if langs else ""

        # ⚡ EXTRACT TARGET RESOLUTIONS
        res_matches = re.findall(r"(?i)\b(WEB-DL|HDRip|HDTC|1080p|720p|480p|1440p|2160p|4k|BluRay|BDRip|WEBRip|HDTVRip|DVDRip|CAMRip|HEVC)\b", clean_name)
        res = list(set([r.upper() if 'p' not in r.lower() else r.lower() for r in res_matches]))
        res_str = ", ".join(res) if res else ""

        # ⚡ EXTRACT OTT PLATFORMS
        ott_matches = re.findall(r"(?i)\b(Netflix|Amazon Prime|Prime Video|Aha|Zee5|Hotstar|Disney\+?|JioCinema|SonyLIV|SunNXT|Voot|Hulu|HBO|Apple TV|AppleTV|Crunchyroll)\b", clean_name)
        otts = list(set([o.title().replace("Appletv", "Apple TV").replace("Disney+", "Disney") for o in ott_matches]))
        otts_str = ", ".join(otts) if otts else ""

        # Search Query Builder
        search_name = re.sub(r"(?i)\b(1080p|720p|480p|2160p|4k|WEB-DL|HDRip|HDTC|BDRip|BluRay|DVDRip|WEBRip|CAMRip|HEVC|mkv|mp4|avi|hindi|kannada|telugu|tamil|malayalam|english|dual audio|multi audio|dual|multi|subs|episodes|season\s*\d+|s\d+e\d+|Netflix|Prime|Aha|Zee5|Hotstar|JioCinema|SonyLIV|Voot)\b", "", clean_name)
        search_name = re.sub(r"\b(19\d{2}|20\d{2})\b", "", search_name)
        search_name = re.sub(r"\s+", " ", search_name).strip()

        # ⚡ ONE MOVIE ONE POST CACHE
        if RECENT_POSTS.get(search_name): return 
        RECENT_POSTS.set(search_name, True)

        # 🎬 Fetch TMDB Data
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
        
        # ⚡ Safe Regex Line Deletion
        for tag, val in [("{LANGUAGES}", val_langs), ("{RESOLUTIONS}", val_res), ("{GENRES}", val_gens), ("{OTT_PLATFORMS}", val_otts)]:
            if val: text = text.replace(tag, val)
            else: text = re.sub(rf'[^\n]*{re.escape(tag)}[^\n]*\n?', '', text) 

        if image_mode == "photo" and len(plot) > 250: plot = plot[:250] + "..."

        text = text.replace("{size}", size_str).replace("{rating}", html.escape(str(rating))).replace("{plot}", html.escape(str(plot))).replace("{file_name}", html.escape(file_name))
        text += f"\n\n<b>Jᴏɪɴ: @Sandalwood_Kannada_Moviesz</b>"

        # ⚡ PREVIEW LINK INJECTION
        if poster and image_mode == "preview": text = f"{text}\n<a href='{poster}'>&#8205;</a>"

        # ⚡ BUTTONS
        bot_me = await client.get_me()
        bot_username = bot_me.username
        safe_query = re.sub(r"[^a-zA-Z0-9_-]", "_", f"{title} {year}" if str(year) != "N/A" else title).strip("_")[:50]
        deep_link = f"https://t.me/{bot_username}?start=search_{safe_query}"

        direct_text = settings.get("direct_button_text", "Direct Search 🔎")
        btn_layout = [
            [create_btn(text="Group 1 🎬", url="https://t.me/Sandalwood_Kannada_Group", style=BTN_PRIMARY), create_btn(text="Group 2 🎬", url="https://t.me/+GLsPkRgLGGszMzY1", style=BTN_PRIMARY)],
            [create_btn(text=direct_text, url=deep_link, style=BTN_SUCCESS)]
        ]

        # ⚡ SEND PM CONFIRMATION TO ADMIN
        target_admin = message.from_user.id if message.from_user and message.from_user.id in ADMIN_USERS else ADMIN_USERS[0]
        
        pm_markup_layout = []
        pm_markup_layout.extend(btn_layout) # Attach the channel buttons to the PM
        pm_markup_layout.append([create_btn("✅ Post to Channel", callback_data=f"ap_post_1", style=BTN_SUCCESS)])
        pm_markup_layout.append([create_btn("✏️ Edit Text", callback_data=f"ap_edit_1", style=BTN_PRIMARY), create_btn("❌ Cancel", callback_data=f"ap_cancel_1", style=BTN_DANGER)])

        if poster and image_mode == "photo":
            ask_msg = await client.send_photo(chat_id=target_admin, photo=poster, caption=f"**🚨 AUTO-POST TRIGGERED 🚨**\n\n{text}", reply_markup=InlineKeyboardMarkup(pm_markup_layout))
        else:
            ask_msg = await client.send_message(chat_id=target_admin, text=f"**🚨 AUTO-POST TRIGGERED 🚨**\n\n{text}", reply_markup=InlineKeyboardMarkup(pm_markup_layout))

        PENDING_AP[str(ask_msg.id)] = {
            "text": text,
            "buttons": InlineKeyboardMarkup(btn_layout),
            "channel": update_channel,
            "sticker": settings.get("sticker"),
            "poster": poster,
            "image_mode": image_mode
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
        return await query.answer("⌛ This pending post has expired or was already handled.", show_alert=True)

    if action == "post":
        if payload["poster"] and payload["image_mode"] == "photo":
            await client.send_photo(chat_id=payload["channel"], photo=payload["poster"], caption=payload["text"], reply_markup=payload["buttons"])
        else:
            await client.send_message(chat_id=payload["channel"], text=payload["text"], reply_markup=payload["buttons"])
            
        if payload["sticker"]:
            await client.send_sticker(chat_id=payload["channel"], sticker=payload["sticker"])
        
        await query.answer("✅ Successfully Posted!", show_alert=False)
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
                pm_markup_layout.extend(payload["buttons"].inline_keyboard)
                pm_markup_layout.append([create_btn("✅ Post to Channel", callback_data=f"ap_post_1", style=BTN_SUCCESS)])
                pm_markup_layout.append([create_btn("✏️ Edit Text", callback_data=f"ap_edit_1", style=BTN_PRIMARY), create_btn("❌ Cancel", callback_data=f"ap_cancel_1", style=BTN_DANGER)])
                
                if payload["poster"] and payload["image_mode"] == "photo":
                    await query.message.edit_caption(f"**🚨 AUTO-POST TRIGGERED (EDITED) 🚨**\n\n{new_text}", reply_markup=InlineKeyboardMarkup(pm_markup_layout))
                else:
                    await query.message.edit_text(f"**🚨 AUTO-POST TRIGGERED (EDITED) 🚨**\n\n{new_text}", reply_markup=InlineKeyboardMarkup(pm_markup_layout))
            
            await response.delete()
        except asyncio.TimeoutError:
            await prompt_msg.edit_text("⌛ Timeout. Edit cancelled.")
