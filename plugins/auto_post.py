import asyncio
import html
import re
from logging import ERROR, getLogger

from motor.motor_asyncio import AsyncIOMotorClient
from pyrogram import Client, enums, filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

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
DEFAULT_TEMPLATE = """{title} {year}

<blockquote>{LANGUAGES}
{RESOLUTIONS}
{GENRES}
{OTT_PLATFORMS}
<b>📟 : Available In Files.</b>

<b>=========================</b></blockquote>"""

async def get_ap_settings():
    if ap_db is None: return {}
    settings = await ap_db.find_one({"id": "ap_config"})
    if not settings:
        return {"enabled": False, "template": DEFAULT_TEMPLATE}
    return settings

async def save_ap_settings(key, value):
    if ap_db is not None:
        await ap_db.update_one({"id": "ap_config"}, {"$set": {key: value}}, upsert=True)

# ⚡ ADMIN FILTER
id_pattern = re.compile(r"^.\d+$")
ADMIN_USERS = [int(admin) if id_pattern.search(str(admin)) else admin for admin in getattr(info, "ADMINS", [])]

async def admin_check(_, __, message: Message):
    return bool(message.from_user and message.from_user.id in ADMIN_USERS)
admin_filter = filters.create(admin_check)

# ⚡ CRASH-PROOF BUTTON BUILDER
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


# ============================================================
# ⚙️ HTML FORMAT EXTRACTOR (SUPPORTS BOLD, QUOTE, MONO)
# ============================================================
def get_html_text(message: Message):
    """Extracts raw HTML (bold, italics, quotes) perfectly from the message."""
    if message.reply_to_message and message.reply_to_message.text:
        return message.reply_to_message.text.html
    elif len(message.command) > 1:
        html_text = message.text.html
        # Safely strip out the command word to leave only the formatted text
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
        await message.reply_text("✅ **Auto-Post Engine is now ON!**\nFiles added to your File Store Channel will be posted automatically.")
    elif cmd == "off":
        await save_ap_settings("enabled", False)
        await message.reply_text("🔴 **Auto-Post Engine is now OFF!**")


@Client.on_message(filters.command(["editautopost", "setautoposttext"]) & admin_filter)
async def set_autopost_text(client: Client, message: Message):
    text = get_html_text(message)
    if not text:
        return await message.reply_text(
            "⚠️ **Usage:** `/editautopost <text>` or reply to a message.\n\n"
            "**Supported Placeholders:**\n"
            "`{title}` - Main Title\n"
            "`{year}` - Release Year\n"
            "`{size}` - File Size\n"
            "`{rating}` - IMDB Rating\n"
            "`{plot}` - Storyline\n"
            "`{file_name}` - Raw File Name\n\n"
            "**Dynamic Line Placeholders (Auto-Hides if empty):**\n"
            "`{LANGUAGES}`\n`{RESOLUTIONS}`\n`{GENRES}`\n`{OTT_PLATFORMS}`"
        )
    await save_ap_settings("template", text)
    await message.reply_text(f"✅ **Auto-Post Main Template Updated!**\n\n{text}", disable_web_page_preview=True)


@Client.on_message(filters.command(["editautoposttittle", "editautoposttitle"]) & admin_filter)
async def cmd_edit_title(client: Client, message: Message):
    text = get_html_text(message)
    if not text: return await message.reply_text("⚠️ **Usage:** `/editautoposttitle <format>`\nExample: `/editautoposttitle ✅ <b>{title}</b>`")
    await save_ap_settings("format_title", text)
    await message.reply_text(f"✅ **Auto-Post Title Format Updated!**\n\n{text}")


@Client.on_message(filters.command(["editautopostyear"]) & admin_filter)
async def cmd_edit_year(client: Client, message: Message):
    text = get_html_text(message)
    if not text: return await message.reply_text("⚠️ **Usage:** `/editautopostyear <format>`\nExample: `/editautopostyear (<b>{year}</b>)`")
    await save_ap_settings("format_year", text)
    await message.reply_text(f"✅ **Auto-Post Year Format Updated!**\n\n{text}")


@Client.on_message(filters.command(["editautopostlanguages"]) & admin_filter)
async def cmd_edit_langs(client: Client, message: Message):
    text = get_html_text(message)
    if not text: return await message.reply_text("⚠️ **Usage:** `/editautopostlanguages <format>`\nExample: `/editautopostlanguages <b>🔊 : {langs}</b>`")
    await save_ap_settings("format_languages", text)
    await message.reply_text(f"✅ **Auto-Post Languages Format Updated!**\n\n{text}")


@Client.on_message(filters.command(["editautopostresolutions"]) & admin_filter)
async def cmd_edit_res(client: Client, message: Message):
    text = get_html_text(message)
    if not text: return await message.reply_text("⚠️ **Usage:** `/editautopostresolutions <format>`\nExample: `/editautopostresolutions <b>🖥️ : {resolutions}</b>`")
    await save_ap_settings("format_resolutions", text)
    await message.reply_text(f"✅ **Auto-Post Resolutions Format Updated!**\n\n{text}")


@Client.on_message(filters.command(["editautopostgenres"]) & admin_filter)
async def cmd_edit_genres(client: Client, message: Message):
    text = get_html_text(message)
    if not text: return await message.reply_text("⚠️ **Usage:** `/editautopostgenres <format>`\nExample: `/editautopostgenres <b>🎥 : {genres}</b>`")
    await save_ap_settings("format_genres", text)
    await message.reply_text(f"✅ **Auto-Post Genres Format Updated!**\n\n{text}")


@Client.on_message(filters.command(["editautopostottplatforms"]) & admin_filter)
async def cmd_edit_otts(client: Client, message: Message):
    text = get_html_text(message)
    if not text: return await message.reply_text("⚠️ **Usage:** `/editautopostottplatforms <format>`\nExample: `/editautopostottplatforms <b>📺 : #{otts}</b>`")
    await save_ap_settings("format_otts", text)
    await message.reply_text(f"✅ **Auto-Post OTT Platforms Format Updated!**\n\n{text}")


@Client.on_message(filters.command("setautopostimage") & admin_filter)
async def set_autopost_image(client: Client, message: Message):
    if message.reply_to_message and message.reply_to_message.photo:
        await save_ap_settings("image", message.reply_to_message.photo.file_id)
        await message.reply_text("✅ **Auto-Post Image Saved!** This image will be used for all auto-posts instead of the TMDB poster.")
    elif len(message.command) > 1:
        url = message.text.split(None, 1)[1]
        await save_ap_settings("image", url)
        await message.reply_text("✅ **Auto-Post Image URL Saved!** This image will be used for all auto-posts instead of the TMDB poster.")
    else:
        await message.reply_text("⚠️ **Usage:** `/setautopostimage <URL>` or reply to a photo.")

@Client.on_message(filters.command("remautopostimage") & admin_filter)
async def rem_autopost_image(client: Client, message: Message):
    await save_ap_settings("image", None)
    await message.reply_text("🗑️ **Auto-Post Image Removed.** The bot will revert to using dynamic TMDB posters.")

@Client.on_message(filters.command("setautopoststicker") & admin_filter)
async def set_autopost_sticker(client: Client, message: Message):
    if not message.reply_to_message or not message.reply_to_message.sticker:
        return await message.reply_text("⚠️ **Please reply directly to a sticker** with `/setautopoststicker` to save it.")
    
    sticker_id = message.reply_to_message.sticker.file_id
    await save_ap_settings("sticker", sticker_id)
    await message.reply_text("✅ **Auto-Post Sticker Saved!** It will now be sent below every automated post.")

@Client.on_message(filters.command("remautopoststicker") & admin_filter)
async def rem_autopost_sticker(client: Client, message: Message):
    await save_ap_settings("sticker", None)
    await message.reply_text("🗑️ **Auto-Post Sticker Removed.**")

@Client.on_message(filters.command(["setautopostbutton", "editautopostbutton"]) & admin_filter)
async def set_autopost_button(client: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text(
            "⚠️ **Usage:** `/setautopostbutton <layout>`\n\n"
            "**Format Example:**\n`Group 1 - https://t.me/g1 | Group 2 - https://t.me/g2`\n`Download 📥 - {deep_link}`\n\n"
            "*(Use `{deep_link}` to automatically insert the search link for that specific movie)*"
        )
    
    layout_text = message.text.split(None, 1)[1]
    await save_ap_settings("buttons", layout_text)
    await message.reply_text("✅ **Auto-Post Buttons Updated!**")

@Client.on_message(filters.command("remautopostbutton") & admin_filter)
async def rem_autopost_button(client: Client, message: Message):
    await save_ap_settings("buttons", None)
    await message.reply_text("🗑️ **Auto-Post Buttons Reverted to Default.**")


# ============================================================
# 🚀 THE AUTO-POST LISTENER ENGINE (WITH SMART LINE HIDER)
# ============================================================
@Client.on_message(filters.chat(info.FILE_STORE_CHANNEL) & (filters.document | filters.video | filters.audio))
async def auto_post_trigger(client: Client, message: Message):
    settings = await get_ap_settings()
    if not settings.get("enabled", False):
        return

    update_channel = getattr(info, "MOVIE_UPDATE_CHANNEL", None)
    if not update_channel:
        return

    try:
        media = message.document or message.video or message.audio
        if not media: return
        
        file_name = getattr(media, "file_name", "Unknown")
        file_size = getattr(media, "file_size", 0)
        size_str = get_size(file_size)

        # 🧹 Sanitize filename to find the actual movie name
        clean_name = re.sub(r"(?i)\[?@?sandalwood[^\]\s]*\]?", "", file_name)
        clean_name = re.sub(r"[_.-]", " ", clean_name)
        
        # ⚡ AUTO-EXTRACT LANGUAGES & RESOLUTIONS FROM FILENAME
        lang_matches = re.findall(r"(?i)\b(Kannada|English|Gujarati|Hindi|Bengali|Malayalam|Marathi|Punjabi|Tamil|Telugu|Urdu|Dual Audio|Multi Audio)\b", clean_name)
        langs = list(set([l.title() for l in lang_matches]))
        langs_str = ", ".join(langs) if langs else ""

        res_matches = re.findall(r"(?i)\b(144p|240p|480p|720p|1080p|1440p|2160p|4k|BluRay|BDRip|WEB-DL|HDRip|WEBRip|HDTVRip|DVDRip|CAMRip|HEVC)\b", clean_name)
        res = list(set([r.upper() if 'p' not in r.lower() else r.lower() for r in res_matches]))
        res_str = ", ".join(res) if res else ""

        # Strip qualities and languages to get a clean TMDB search query
        search_name = re.sub(r"(?i)\b(1080p|720p|480p|2160p|4k|mkv|mp4|avi|hdrip|web-?dl|webrip|bluray|brrip|dvdrip|x264|x265|hevc|hindi|kannada|telugu|tamil|malayalam|english|dual audio|multi audio|dual|multi|subs|episodes|season\s*\d+|s\d+e\d+)\b", "", clean_name)
        search_name = re.sub(r"\b(19\d{2}|20\d{2})\b", "", search_name)
        search_name = re.sub(r"\s+", " ", search_name).strip()

        # 🎬 Fetch Official Data
        movie_details = await get_movie_detailsx(search_name)
        
        title = movie_details.get("title", search_name) if movie_details else search_name
        year = movie_details.get("year", "N/A") if movie_details else "N/A"
        rating = movie_details.get("rating", "N/A") if movie_details else "N/A"
        genres_str = ", ".join(movie_details.get("genres", [])) if movie_details and movie_details.get("genres") else ""
        plot = movie_details.get("plot", "N/A") if movie_details else "N/A"
        
        # 📸 IMAGE LOGIC
        custom_img = settings.get("image")
        poster = custom_img if custom_img else (movie_details.get("poster_url") if movie_details else None)

        # 📝 LOAD DYNAMIC FORMATS
        fmt_title = settings.get("format_title", "✅ <b>{title}</b>")
        fmt_year = settings.get("format_year", "<b>{year}</b>")
        fmt_langs = settings.get("format_languages", "<b>🔊 : {langs}</b>")
        fmt_res = settings.get("format_resolutions", "<b>🖥️ : {resolutions}</b>")
        fmt_gens = settings.get("format_genres", "<b>🎥 : {genres}</b>")
        fmt_otts = settings.get("format_otts", "<b>📺 : #{otts}</b>")

        # Process Values
        val_title = fmt_title.replace("{title}", html.escape(title))
        val_year = fmt_year.replace("{year}", html.escape(str(year))) if str(year) != "N/A" else ""
        val_langs = fmt_langs.replace("{langs}", langs_str).replace("{LANGUAGES}", langs_str) if langs_str else ""
        val_res = fmt_res.replace("{resolutions}", res_str).replace("{RESOLUTIONS}", res_str) if res_str else ""
        val_gens = fmt_gens.replace("{genres}", genres_str).replace("{GENRES}", genres_str) if genres_str else ""
        val_otts = "" # Empty for now since auto-post doesn't scan OTT providers

        # Apply to Main Template
        template_str = settings.get("template", DEFAULT_TEMPLATE)
        text = template_str
        text = text.replace("{title}", val_title)
        text = text.replace("{year}", val_year)
        
        # ⚡ Smart Line Hider: Automatically deletes the line entirely if the data is missing
        for tag, val in [("{LANGUAGES}", val_langs), ("{RESOLUTIONS}", val_res), ("{GENRES}", val_gens), ("{OTT_PLATFORMS}", val_otts)]:
            if val:
                text = text.replace(tag, val)
            else:
                text = text.replace(tag + "\n", "").replace(tag, "") # Completely destroys the line and label if blank

        # Final String replacements
        text = text.replace("{size}", size_str)
        text = text.replace("{rating}", html.escape(str(rating)))
        text = text.replace("{plot}", html.escape(str(plot)))
        text = text.replace("{file_name}", html.escape(file_name))

        # Universal Watermark
        text += f"\n\n<b>Jᴏɪɴ: @Sandalwood_Kannada_Moviesz</b>"

        # 🔗 BUTTON LOGIC
        bot_me = await client.get_me()
        bot_username = bot_me.username
        safe_query = re.sub(r"[^a-zA-Z0-9_-]", "_", f"{title} {year}" if str(year) != "N/A" else title).strip("_")[:50]
        deep_link = f"https://t.me/{bot_username}?start=search_{safe_query}"

        custom_buttons_str = settings.get("buttons")
        btn_layout = []
        if custom_buttons_str:
            for row_str in custom_buttons_str.split("\n"):
                row = []
                for btn_str in row_str.split("|"):
                    if "-" in btn_str:
                        btn_txt, btn_url = btn_str.split("-", 1)
                        final_url = btn_url.strip().replace("{deep_link}", deep_link)
                        row.append(create_btn(text=btn_txt.strip(), url=final_url, style=BTN_PRIMARY))
                if row: btn_layout.append(row)
        else:
            btn_layout = [
                [
                    create_btn(text="Group 1 🎬", url="https://t.me/Sandalwood_Kannada_Group", style=BTN_PRIMARY),
                    create_btn(text="Group 2 🎬", url="https://t.me/+GLsPkRgLGGszMzY1", style=BTN_PRIMARY)
                ],
                [
                    create_btn(text="Direct Search 🔎", url=deep_link, style=BTN_SUCCESS)
                ]
            ]
            
        btn = InlineKeyboardMarkup(btn_layout) if btn_layout else None

        # 📤 Send Post to Channel
        if poster:
            await client.send_photo(
                chat_id=update_channel,
                photo=poster,
                caption=text[:1024], # Telegram limit for photos
                reply_markup=btn,
                parse_mode=enums.ParseMode.HTML
            )
        else:
            await client.send_message(
                chat_id=update_channel,
                text=text[:4096],
                reply_markup=btn,
                parse_mode=enums.ParseMode.HTML
            )

        # 🖼️ Send Sticker
        sticker_id = settings.get("sticker")
        if sticker_id:
            await client.send_sticker(chat_id=update_channel, sticker=sticker_id)

    except Exception as e:
        logger.error(f"Auto-Post Engine Failed: {e}")
