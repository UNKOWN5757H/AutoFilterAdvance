import asyncio
import html
import logging
import os
import re
import traceback
from io import BytesIO

import requests
from pyrogram import Client, filters
from pyrogram.enums import ButtonStyle
from pyrogram.errors import ButtonUrlInvalid, MessageNotModified, MessageTooLong
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    InputMediaPhoto,
)

import info
from info import ADMINS, MOVIE_UPDATE_CHANNEL
from plugins.Imdbposter import get_movie_detailsx
from utils import temp

logger = logging.getLogger(__name__)
post_sessions = {}

USE_GETFILE_BUTTON_BY_DEFAULT = True

DEFAULT_WATERMARK = "<b>Jᴏɪɴ: @Sandalwood_Kannada_Moviesz</b>"
LANGUAGES_FORMAT = "<b>🔊 : {langs}</b>"
RESOLUTIONS_FORMAT = "\n<b>🖥️ : {resolutions}</b>"
GENRES_FORMAT = "\n<b>🎥 : {genres}</b>"
OTT_FORMAT = "\n<b>📺 : #{otts}</b>"

TEMPLATES = {
    "clean_grid": """✅ <b>{title} {year}</b>\n\n<blockquote><b>🔊 : {LANGUAGES}</b>\n<b>🖥️ : {RESOLUTIONS}</b>\n<b>🎥 : {genres}</b>\n<b>📺 : #{OTT_PLATFORMS}</b>\n<b>📟 : Available In Files.</b>\n\n<b>=========================</b></blockquote>""",
    "divider_list": """🎬 <b>{title} {year}</b>\n━━━━━━━━━━━━━━━━━━\n<blockquote><b>🔊 : {LANGUAGES}</b>\n<b>🖥️ : {RESOLUTIONS}</b>\n<b>📺 : {OTT_PLATFORMS}</b></blockquote>""",
}

LANGUAGES = [
    "Kannada", "English", "Gujarati", "Hindi", "Bengali", "Malayalam", "Marathi",
    "Punjabi", "Tamil", "Telugu", "Urdu", "Arabic", "French", "German", "Italian",
    "Japanese", "Korean", "Mandarin", "Portuguese", "Russian", "Spanish", "#NotAvailable",
]
RESOLUTIONS = [
    "144p", "240p", "480p", "720p", "1080p", "1440p", "2160p", "4320p", "BluRay",
    "BDRip", "WEB-DL", "HDRip", "WEBRip", "HDTVRip", "DVDRip", "DVDScr", "TSRip",
    "CAMRip", "HDTC", "HEVC", "#NotAvailable",
]
GENRES = [
    "Action", "Adventure", "Animation", "Biography", "Comedy", "Crime", "Documentary",
    "Drama", "Family", "Fantasy", "History", "Horror", "Music", "Musical", "Mystery",
    "Romance", "Sci-Fi", "Sport", "Thriller", "War", "Western", "Superhero",
    "Psychological", "Suspense", "Noir", "Disaster", "Survival", "Teen", "Slice of Life",
    "Coming of Age", "Martial Arts", "Political", "Legal", "Medical", "Spy", "Erotic",
    "Mythology", "Short", "Experimental", "#NotAvailable",
]
OTT_PLATFORMS = [
    "Aha", "ALTBalaji", "JioHotstar", "ErosNow", "Hoichoi", "JioCinema", "MXPlayer",
    "SonyLIV", "SunNXT", "Voot", "Zee5", "AmazonPrime", "AppleTV+", "Crunchyroll",
    "Discovery+", "HBO Max", "Hulu", "Netflix", "Paramount+", "Peacock", "ManoramaMAX",
    "NotAvailable",
]


# ============================================================
# 🛡️ BULLETPROOF ADMIN FILTERS
# ============================================================
def get_admin_list():
    raw_admins = getattr(info, "ADMINS", [])
    if isinstance(raw_admins, str):
        return [x.strip() for x in raw_admins.replace(",", " ").split() if x.strip()]
    elif isinstance(raw_admins, int):
        return [str(raw_admins)]
    elif isinstance(raw_admins, list):
        return [str(a) for a in raw_admins]
    return []


async def admin_check(_, __, message: Message):
    if not message.from_user:
        return False
    return str(message.from_user.id) in get_admin_list()


admin_filter = filters.create(admin_check)


# ============================================================
# 🌐 MULTI-LAYER FALLBACK IMAGE UPLOADER (FOR PREVIEW MODE)
# ============================================================
def _upload_sync(file_bytes):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
    }
    
    try:
        res = requests.post("http://telegraph.controller.bot/upload", files={'file': ('img.jpg', file_bytes, 'image/jpeg')}, headers=headers, timeout=10)
        if res.status_code == 200:
            data = res.json()
            if isinstance(data, list) and "src" in data[0]:
                return "http://telegraph.controller.bot" + data[0]["src"]
            elif isinstance(data, dict) and "link" in data:
                return data["link"]
    except Exception: pass

    try:
        res = requests.post("https://telegra.ph/upload", files={'file': ('img.jpg', file_bytes, 'image/jpeg')}, headers=headers, timeout=10)
        if res.status_code == 200:
            data = res.json()
            if isinstance(data, list) and "src" in data[0]:
                return "https://telegra.ph" + data[0]["src"]
    except Exception: pass

    try:
        res = requests.post("https://envs.sh", files={'file': ('img.jpg', file_bytes, 'image/jpeg')}, headers=headers, timeout=10)
        if res.status_code == 200 and res.text.startswith("http"):
            return res.text.strip()
    except Exception: pass

    try:
        payload = {"reqtype": "fileupload"}
        res = requests.post("https://catbox.moe/user/api.php", data=payload, files={"fileToUpload": ('img.jpg', file_bytes, 'image/jpeg')}, headers=headers, timeout=15)
        if res.status_code == 200 and res.text.startswith("http"):
            return res.text.strip()
    except Exception: pass

    try:
        res = requests.post("https://uguu.se/upload.php", files={'files[]': ('img.jpg', file_bytes, 'image/jpeg')}, headers=headers, timeout=15)
        if res.status_code == 200:
            return res.json()['files'][0]['url']
    except Exception: pass

    return None


async def upload_image_safely(client: Client, message: Message):
    try:
        file_io = await client.download_media(message, in_memory=True)
        if not file_io: return None, "❌ Failed to download the image from Telegram into memory."
        file_bytes = file_io.getvalue()
        url = await asyncio.to_thread(_upload_sync, file_bytes)
        if not url: return None, "❌ All upload servers failed to process the image."
        return url, None
    except Exception as e:
        logger.error(f"Image Processing Error: {e}")
        return None, f"❌ Internal Error: {e}"


@Client.on_message(filters.command("post") & admin_filter, group=-4)
async def post_command(client: Client, message: Message):
    try:
        if len(message.command) == 1:
            return await message.reply_text("Please provide a movie name. Usage: `/post The Dark Knight`")

        movie_name = " ".join(message.command[1:])
        user_id = message.from_user.id

        await start_post_session(client, message, user_id, movie_name)
    except Exception as e:
        await message.reply_text(f"❌ **COMMAND ERROR:**\n`{e}`")


# ============================================================
# 🔄 EDIT EXISTING POST COMMAND & REVERSE ENGINEER TEMPLATE
# ============================================================
@Client.on_message(filters.command("editpost") & admin_filter, group=-4)
async def edit_post_cmd(client: Client, message: Message):
    try:
        if len(message.command) < 2:
            return await message.reply_text("❌ Please provide a post link.\n**Usage:** `/editpost https://t.me/c/1923564465/1410`")
        
        link = message.command[1]
        
        if "t.me/c/" in link:
            parts = link.split("/")
            chat_id = int("-100" + parts[-2])
            msg_id = int(parts[-1])
        elif "t.me/" in link:
            parts = link.split("/")
            chat_id = parts[-2]
            if not chat_id.startswith("@"):
                chat_id = "@" + chat_id
            msg_id = int(parts[-1])
        else:
            return await message.reply_text("❌ Invalid Telegram link format.")

        status_msg = await message.reply_text("⏳ Fetching and analyzing post from channel...")

        try:
            target_msg = await client.get_messages(chat_id, msg_id)
            if not target_msg or target_msg.empty:
                return await status_msg.edit_text("❌ Message not found. Make sure the bot is an admin in the channel.")
        except Exception as e:
            return await status_msg.edit_text(f"❌ Could not fetch message:\n`{e}`")

        user_id = message.from_user.id

        poster_url = None
        html_text = ""
        is_photo_mode = False
        
        # 1. Analyze existing message mode and extract image
        if target_msg.photo:
            html_text = target_msg.caption.html if target_msg.caption else ""
            poster_url = target_msg.photo.file_id
            is_photo_mode = True
        else:
            html_text = target_msg.text.html if target_msg.text else ""
            hidden_link_pattern = r"<a href=['\"](https?://[^'\"]+)['\"]>&#8205;</a>"
            match = re.search(hidden_link_pattern, html_text)
            if match:
                poster_url = match.group(1)
                html_text = re.sub(hidden_link_pattern, "", html_text).strip()

        # 2. Extract Buttons
        buttons = []
        if target_msg.reply_markup and target_msg.reply_markup.inline_keyboard:
            for row in target_msg.reply_markup.inline_keyboard:
                new_row = []
                for btn in row:
                    new_row.append(InlineKeyboardButton(text=btn.text, url=btn.url, callback_data=btn.callback_data))
                buttons.append(new_row)

        # 3. SMART REVERSE-ENGINEERING (Extract Variables from HTML)
        title_match = re.search(r"^[✅🎬]\s*<b>(.*?)(?:\s+(\d{4}))?</b>", html_text)
        
        is_manual = True
        movie_details = {"title": "Edited Post", "year": "", "rating": "", "plot": ""}
        c_langs, c_res, c_gens, c_otts = [], [], [], []
        watermark = ""
        
        if title_match:
            is_manual = False  # Template successfully matched!
            movie_details["title"] = title_match.group(1).strip()
            if title_match.group(2):
                movie_details["year"] = title_match.group(2).strip()

            l_match = re.search(r"🔊\s*:\s*(.*?)</[bB]>", html_text)
            if l_match and l_match.group(1).strip() != "N/A":
                c_langs = [x.strip() for x in l_match.group(1).split(",")]

            r_match = re.search(r"🖥️\s*:\s*(.*?)</[bB]>", html_text)
            if r_match and r_match.group(1).strip() != "N/A":
                c_res = [x.strip() for x in r_match.group(1).split(",")]

            g_match = re.search(r"🎥\s*:\s*(.*?)</[bB]>", html_text)
            if g_match and g_match.group(1).strip() != "N/A":
                c_gens = [x.strip() for x in g_match.group(1).split(",")]

            o_match = re.search(r"📺\s*:\s*#?(.*?)</[bB]>", html_text)
            if o_match and o_match.group(1).strip() != "N/A":
                c_otts = [x.strip() for x in o_match.group(1).split(",")]
                
            w_match = re.search(r"(<b>Jᴏɪɴ:.*?</b>)", html_text)
            if w_match:
                watermark = w_match.group(1)

        if user_id in post_sessions and post_sessions[user_id].get("last_preview_message_id"):
            try: await client.delete_messages(message.chat.id, post_sessions[user_id]["last_preview_message_id"])
            except Exception: pass

        post_sessions[user_id] = {
            "movie_name": "Edit Session",
            "caption": html_text,
            "is_manual_caption": is_manual,
            "buttons": buttons,
            "photo_mode": is_photo_mode,
            "use_landscape": False,
            "custom_languages": c_langs,
            "custom_resolutions": c_res,
            "custom_genres": c_gens,
            "custom_otts": c_otts,
            "last_preview_message_id": status_msg.id,
            "original_message_id": message.id,
            "custom_poster": poster_url,
            "watermark": watermark, 
            "lang_format": LANGUAGES_FORMAT,
            "ott_format": OTT_FORMAT,
            "gen_format": GENRES_FORMAT,
            "res_format": RESOLUTIONS_FORMAT,
            "active_template": "clean_grid",
            "movie_details": movie_details,
            "edit_target": {"chat_id": chat_id, "message_id": msg_id} 
        }

        # Do NOT ask for Image Mode. Telegram blocks mode swapping on existing posts.
        # Immediately display the editable preview.
        await update_post_preview(client, user_id, message.chat.id, force_resend=True)

    except Exception as e:
        await message.reply_text(f"❌ **EDIT POST ERROR:**\n`{e}`")


# ============================================================
# 🔗 QUICK EDIT COMMANDS
# ============================================================

@Client.on_message(filters.command(["edittitle", "edittittle"]) & admin_filter, group=-4)
async def edit_title_cmd(client: Client, message: Message):
    user_id = message.from_user.id
    if user_id not in post_sessions: return await message.reply_text("❌ No active post session.")
    session = post_sessions[user_id]

    if len(message.command) > 1:
        new_title = message.text.split(None, 1)[1].strip()
        if new_title.lower() == "blank": new_title = "BLANK"
        session["movie_details"]["title"] = new_title
        await message.reply_text("✅ Title cleared!" if new_title == "BLANK" else f"✅ Title updated to: **{new_title}**")
        await update_post_preview(client, user_id, message.chat.id, force_resend=False)
    else:
        ask_msg = await message.reply_text("✏️ **Please send the new Title now.**\n*(Type `blank` to remove the title entirely)*")
        try:
            response = await client.listen(chat_id=message.chat.id, user_id=user_id, timeout=120)
            await ask_msg.delete()
            if response.text:
                new_title = response.text.strip()
                if new_title.lower() == "blank": new_title = "BLANK"
                session["movie_details"]["title"] = new_title
                await message.reply_text("✅ Title cleared!" if new_title == "BLANK" else f"✅ Title updated to: **{new_title}**")
                await update_post_preview(client, user_id, message.chat.id, force_resend=False)
            else: await message.reply_text("⚠️ Invalid input. Must be text.")
            try: await response.delete()
            except Exception: pass
        except asyncio.TimeoutError:
            await ask_msg.edit_text("⌛ Timeout. Title edit cancelled.")


@Client.on_message(filters.command("edityear") & admin_filter, group=-4)
async def edit_year_cmd(client: Client, message: Message):
    user_id = message.from_user.id
    if user_id not in post_sessions: return await message.reply_text("❌ No active post session.")
    session = post_sessions[user_id]

    if len(message.command) > 1:
        new_year = message.text.split(None, 1)[1].strip()
        if new_year.lower() == "blank": new_year = "BLANK"
        session["movie_details"]["year"] = new_year
        await message.reply_text("✅ Year cleared!" if new_year == "BLANK" else f"✅ Year updated to: **{new_year}**")
        await update_post_preview(client, user_id, message.chat.id, force_resend=False)
    else:
        ask_msg = await message.reply_text("✏️ **Please send the new Year now.**\n*(Type `blank` to remove the year entirely)*")
        try:
            response = await client.listen(chat_id=message.chat.id, user_id=user_id, timeout=120)
            await ask_msg.delete()
            if response.text:
                new_year = response.text.strip()
                if new_year.lower() == "blank": new_year = "BLANK"
                session["movie_details"]["year"] = new_year
                await message.reply_text("✅ Year cleared!" if new_year == "BLANK" else f"✅ Year updated to: **{new_year}**")
                await update_post_preview(client, user_id, message.chat.id, force_resend=False)
            else: await message.reply_text("⚠️ Invalid input. Must be text.")
            try: await response.delete()
            except Exception: pass
        except asyncio.TimeoutError:
            await ask_msg.edit_text("⌛ Timeout. Year edit cancelled.")


@Client.on_message(filters.command(["editbuttoncolour", "Editbuttoncolour"]) & admin_filter, group=-4)
async def edit_button_colour_cmd(client: Client, message: Message):
    user_id = message.from_user.id
    if user_id not in post_sessions: return await message.reply_text("❌ No active post session.")
        
    if len(message.command) < 3:
        return await message.reply_text("❌ **Usage:** `/editbuttoncolour <button_number> <colour>`\n\n**Example:** `/editbuttoncolour 1 green`\n**Colours:** `green`, `red`, `blue`")

    try: btn_num = int(message.command[1])
    except ValueError: return await message.reply_text("❌ Button number must be an integer.")

    color_str = message.command[2].lower()
    color_map = {"green": ButtonStyle.SUCCESS, "red": ButtonStyle.DANGER, "blue": ButtonStyle.PRIMARY}
    if color_str not in color_map: return await message.reply_text("❌ Invalid colour. Choose from: `green`, `red`, `blue`.")

    session = post_sessions[user_id]
    if not session.get("buttons"): return await message.reply_text("❌ No buttons currently in the layout.")

    count, found = 0, False
    for r_idx, row in enumerate(session["buttons"]):
        for c_idx, btn in enumerate(row):
            count += 1
            if count == btn_num:
                session["buttons"][r_idx][c_idx].style = color_map[color_str]
                found = True
                break
        if found: break
            
    if not found: return await message.reply_text(f"❌ Button number {btn_num} not found. You only have {count} buttons.")
    await message.reply_text(f"✅ Button {btn_num} colour changed to {color_str.title()}!")
    await update_post_preview(client, user_id, message.chat.id, force_resend=False)


@Client.on_message(filters.command("editdirect") & admin_filter, group=-4)
async def edit_direct_url(client: Client, message: Message):
    user_id = message.from_user.id
    if user_id not in post_sessions: return await message.reply_text("❌ No active post session.")
    session = post_sessions[user_id]

    if len(message.command) > 1:
        new_url = message.text.split(None, 1)[1].strip()
    else:
        ask_msg = await message.reply_text("✏️ **Please send the new URL now.**\n*(Type `blank` to remove the Direct Search button entirely)*")
        try:
            response = await client.listen(chat_id=message.chat.id, user_id=user_id, timeout=120)
            await ask_msg.delete()
            if response.text: new_url = response.text.strip()
            else: return await message.reply_text("⚠️ Invalid input. Must be a URL or 'blank'.")
            try: await response.delete()
            except Exception: pass
        except asyncio.TimeoutError:
            return await ask_msg.edit_text("⌛ Timeout. URL edit cancelled.")

    button_updated = False
    if new_url.lower() == "blank":
        if session.get("buttons"):
            for row in session["buttons"]:
                row[:] = [btn for btn in row if btn.text != "Direct Search 🔎"]
            session["buttons"] = [row for row in session["buttons"] if row]
            button_updated = True
            await message.reply_text("✅ 'Direct Search' button removed entirely!")
    else:
        if session.get("buttons"):
            for row in session["buttons"]:
                for btn in row:
                    if btn.text == "Direct Search 🔎":
                        btn.url = new_url
                        button_updated = True
        if button_updated:
            await message.reply_text(f"✅ **'Direct Search' button URL updated successfully!**\n\n🔗 **New URL:** `{new_url}`")

    if button_updated: await update_post_preview(client, user_id, message.chat.id, force_resend=False)
    else: await message.reply_text("❌ **Button not found!** Ensure you have the 'Direct Search 🔎' button added to your layout first.")


@Client.on_message(filters.command("editlangs") & admin_filter, group=-4)
async def edit_langs_cmd(client: Client, message: Message):
    user_id = message.from_user.id
    if user_id not in post_sessions: return await message.reply_text("❌ No active post session.")
    session = post_sessions[user_id]

    if len(message.command) > 1:
        text_input = message.text.split(None, 1)[1].strip()
        new_langs = ["BLANK"] if text_input.lower() == "blank" else [lang.strip() for lang in text_input.split(",")]
    else:
        ask_msg = await message.reply_text("✏️ **Please send languages separated by commas now.**\n*(Type `blank` to remove the languages line entirely)*")
        try:
            response = await client.listen(chat_id=message.chat.id, user_id=user_id, timeout=120)
            await ask_msg.delete()
            if response.text:
                text_input = response.text.strip()
                new_langs = ["BLANK"] if text_input.lower() == "blank" else [lang.strip() for lang in text_input.split(",")]
            else: return await message.reply_text("⚠️ Invalid input. Must be text.")
            try: await response.delete()
            except Exception: pass
        except asyncio.TimeoutError:
            return await ask_msg.edit_text("⌛ Timeout. Edit cancelled.")

    session["custom_languages"] = new_langs
    await message.reply_text("✅ Languages line removed!" if new_langs == ["BLANK"] else f"✅ Languages updated to: **{', '.join(new_langs)}**")
    await update_post_preview(client, user_id, message.chat.id, force_resend=False)


@Client.on_message(filters.command("editresolutions") & admin_filter, group=-4)
async def edit_resolutions_cmd(client: Client, message: Message):
    user_id = message.from_user.id
    if user_id not in post_sessions: return await message.reply_text("❌ No active post session.")
    session = post_sessions[user_id]

    if len(message.command) > 1:
        text_input = message.text.split(None, 1)[1].strip()
        new_res = ["BLANK"] if text_input.lower() == "blank" else [res.strip() for res in text_input.split(",")]
    else:
        ask_msg = await message.reply_text("✏️ **Please send resolutions separated by commas now.**\n*(Type `blank` to remove the resolutions line entirely)*")
        try:
            response = await client.listen(chat_id=message.chat.id, user_id=user_id, timeout=120)
            await ask_msg.delete()
            if response.text:
                text_input = response.text.strip()
                new_res = ["BLANK"] if text_input.lower() == "blank" else [res.strip() for res in text_input.split(",")]
            else: return await message.reply_text("⚠️ Invalid input. Must be text.")
            try: await response.delete()
            except Exception: pass
        except asyncio.TimeoutError:
            return await ask_msg.edit_text("⌛ Timeout. Edit cancelled.")

    session["custom_resolutions"] = new_res
    await message.reply_text("✅ Resolutions line removed!" if new_res == ["BLANK"] else f"✅ Resolutions updated to: **{', '.join(new_res)}**")
    await update_post_preview(client, user_id, message.chat.id, force_resend=False)


@Client.on_message(filters.command("editgenres") & admin_filter, group=-4)
async def edit_genres_cmd(client: Client, message: Message):
    user_id = message.from_user.id
    if user_id not in post_sessions: return await message.reply_text("❌ No active post session.")
    session = post_sessions[user_id]

    if len(message.command) > 1:
        text_input = message.text.split(None, 1)[1].strip()
        new_genres = ["BLANK"] if text_input.lower() == "blank" else [gen.strip() for gen in text_input.split(",")]
    else:
        ask_msg = await message.reply_text("✏️ **Please send genres separated by commas now.**\n*(Type `blank` to remove the genres line entirely)*")
        try:
            response = await client.listen(chat_id=message.chat.id, user_id=user_id, timeout=120)
            await ask_msg.delete()
            if response.text:
                text_input = response.text.strip()
                new_genres = ["BLANK"] if text_input.lower() == "blank" else [gen.strip() for gen in text_input.split(",")]
            else: return await message.reply_text("⚠️ Invalid input. Must be text.")
            try: await response.delete()
            except Exception: pass
        except asyncio.TimeoutError:
            return await ask_msg.edit_text("⌛ Timeout. Edit cancelled.")

    session["custom_genres"] = new_genres
    await message.reply_text("✅ Genres line removed!" if new_genres == ["BLANK"] else f"✅ Genres updated to: **{', '.join(new_genres)}**")
    await update_post_preview(client, user_id, message.chat.id, force_resend=False)


@Client.on_message(filters.command("editotts") & admin_filter, group=-4)
async def edit_otts_cmd(client: Client, message: Message):
    user_id = message.from_user.id
    if user_id not in post_sessions: return await message.reply_text("❌ No active post session.")
    session = post_sessions[user_id]

    if len(message.command) > 1:
        text_input = message.text.split(None, 1)[1].strip()
        new_otts = ["BLANK"] if text_input.lower() == "blank" else [ott.strip() for ott in text_input.split(",")]
    else:
        ask_msg = await message.reply_text("✏️ **Please send OTT platforms separated by commas now.**\n*(Type `blank` to remove the OTTs line entirely)*")
        try:
            response = await client.listen(chat_id=message.chat.id, user_id=user_id, timeout=120)
            await ask_msg.delete()
            if response.text:
                text_input = response.text.strip()
                new_otts = ["BLANK"] if text_input.lower() == "blank" else [ott.strip() for ott in text_input.split(",")]
            else: return await message.reply_text("⚠️ Invalid input. Must be text.")
            try: await response.delete()
            except Exception: pass
        except asyncio.TimeoutError:
            return await ask_msg.edit_text("⌛ Timeout. Edit cancelled.")

    session["custom_otts"] = new_otts
    await message.reply_text("✅ OTT line removed!" if new_otts == ["BLANK"] else f"✅ OTTs updated to: **{', '.join(new_otts)}**")
    await update_post_preview(client, user_id, message.chat.id, force_resend=False)


@Client.on_message(filters.command("editimage") & admin_filter, group=-4)
async def edit_image_cmd(client: Client, message: Message):
    """Sets a rich preview image via Telegraph uploader."""
    user_id = message.from_user.id
    if user_id not in post_sessions: return await message.reply_text("❌ No active post session.")
    session = post_sessions[user_id]

    ask_msg = await message.reply_text("📸 **Please send the new photo or a direct image URL for PREVIEW MODE.**\n*(Or type `/reset` to use the default poster, or `blank` to remove the image completely)*")
    try:
        response = await client.listen(chat_id=message.chat.id, user_id=user_id, timeout=120)
        await ask_msg.delete()
        
        if response.photo:
            # Prevent using file_ids in Preview Mode href links if it is an imported post
            if session.get("edit_target") and not session.get("photo_mode"):
                status_msg = await message.reply_text("⏳ Uploading to secure image host for preview...")
                url, err = await upload_image_safely(client, response)
                if url:
                    session["custom_poster"] = url
                    await status_msg.edit_text("✅ Image successfully uploaded and set as rich preview!")
                else:
                    await status_msg.edit_text(err)
                    return
            else:
                status_msg = await message.reply_text("⏳ Uploading to secure image host for preview...")
                url, err = await upload_image_safely(client, response)
                if url:
                    session["custom_poster"] = url
                    if not session.get("edit_target"): session["photo_mode"] = False
                    await status_msg.edit_text("✅ Image successfully uploaded and set as rich preview!")
                else:
                    await status_msg.edit_text(err)
                    return
        elif response.text:
            text_input = response.text.strip().lower()
            if text_input == "/reset":
                session["custom_poster"] = None
                if not session.get("edit_target"): session["photo_mode"] = False
                await message.reply_text("✅ Image reset to default TMDB poster!")
            elif text_input == "blank":
                session["custom_poster"] = "BLANK"
                await message.reply_text("✅ Image completely removed from preview!")
            elif response.text.startswith("http"):
                session["custom_poster"] = response.text.strip()
                if not session.get("edit_target"): session["photo_mode"] = False
                await message.reply_text("✅ Image updated from URL!")
            else:
                return await message.reply_text("⚠️ Invalid input. Must be a photo, a URL, `blank`, or `/reset`.")
                
        try: await response.delete()
        except Exception: pass
    except asyncio.TimeoutError:
        await ask_msg.edit_text("⌛ Timeout. Image edit cancelled.")
        return

    await update_post_preview(client, user_id, message.chat.id, force_resend=True)


@Client.on_message(filters.command("editnormalimage") & admin_filter, group=-4)
async def edit_normal_image_cmd(client: Client, message: Message):
    """Sets a native Telegram photo (Normal Image Mode) directly."""
    user_id = message.from_user.id
    if user_id not in post_sessions: return await message.reply_text("❌ No active post session.")
    session = post_sessions[user_id]

    ask_msg = await message.reply_text("📸 **Please send the Normal Photo or a direct image URL now.**\n*(Or type `/reset` to use the default TMDB poster, or `blank` to remove the image completely)*")
    try:
        response = await client.listen(chat_id=message.chat.id, user_id=user_id, timeout=120)
        await ask_msg.delete()
        
        if response.photo:
            # Block raw telegram photos if trying to edit a preview mode channel post
            if session.get("edit_target") and not session.get("photo_mode"):
                return await message.reply_text("❌ This imported post is in Preview Mode. You cannot use a raw Telegram file. Please send a URL or use /editimage instead.")
                
            session["custom_poster"] = response.photo.file_id
            if not session.get("edit_target"): session["photo_mode"] = True
            await message.reply_text("✅ Normal Image updated successfully!")
        elif response.text:
            text_input = response.text.strip().lower()
            if text_input == "/reset":
                session["custom_poster"] = None
                if not session.get("edit_target"): session["photo_mode"] = True
                await message.reply_text("✅ Image reset to default TMDB poster (Normal Mode)!")
            elif text_input == "blank":
                session["custom_poster"] = "BLANK"
                await message.reply_text("✅ Image completely removed!")
            elif response.text.startswith("http"):
                session["custom_poster"] = response.text.strip()
                if not session.get("edit_target"): session["photo_mode"] = True
                await message.reply_text("✅ Normal Image updated from URL!")
            else:
                return await message.reply_text("⚠️ Invalid input.")
                
        try: await response.delete()
        except Exception: pass
    except asyncio.TimeoutError:
        await ask_msg.edit_text("⌛ Timeout. Image edit cancelled.")
        return

    await update_post_preview(client, user_id, message.chat.id, force_resend=True)


async def start_post_session(client: Client, message: Message, user_id: int, movie_name: str):
    try:
        status_msg = await message.reply_text("⏳ Fetching movie details...")

        movie_details = await get_movie_detailsx(movie_name)
        if not movie_details:
            return await status_msg.edit_text("❌ Could not fetch details for the movie from TMDB.")

        if user_id in post_sessions and post_sessions[user_id].get("last_preview_message_id"):
            try: await client.delete_messages(message.chat.id, post_sessions[user_id]["last_preview_message_id"])
            except Exception: pass

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
    def __missing__(self, key): return "{" + key + "}"


async def _build_final_post_content(session: dict, session_id: int):
    movie_details = session["movie_details"]
    if not movie_details: return None, None, None

    template_str = TEMPLATES.get(session.get("active_template"), TEMPLATES["clean_grid"])

    title_val = movie_details.get("title")
    if str(title_val).upper() == "BLANK": clean_title = ""
    else: clean_title = html.escape(str(title_val if title_val else "N/A")).replace("{", "(").replace("}", ")").replace("[", "").replace("]", "")

    year_val = movie_details.get("year")
    if str(year_val).upper() == "BLANK": clean_year = ""
    else: clean_year = html.escape(str(year_val if year_val else "N/A")).replace("{", "(").replace("}", ")").replace("[", "").replace("]", "")

    rating_str = html.escape(str(movie_details.get("rating") if movie_details.get("rating") else "N/A")).replace("{", "(").replace("}", ")")
    plot_str = html.escape(str(movie_details.get("plot") if movie_details.get("plot") else "N/A")).replace("{", "(").replace("}", ")")

    c_langs = session.get("custom_languages", [])
    langs_str = "" if c_langs == ["BLANK"] else (", ".join(c_langs) if c_langs else "N/A")

    c_res = session.get("custom_resolutions", [])
    res_str = "" if c_res == ["BLANK"] else (", ".join(c_res) if c_res else "N/A")

    c_gen = session.get("custom_genres", [])
    genres_str = "" if c_gen == ["BLANK"] else (", ".join(c_gen) if c_gen else "N/A")

    c_ott = session.get("custom_otts", [])
    otts_str = "" if c_ott == ["BLANK"] else (", ".join(c_ott) if c_ott else "N/A")

    if not session.get("is_manual_caption"):
        format_args = SafeDict(
            title=clean_title, year=clean_year, rating=rating_str, plot=plot_str,
            LANGUAGES=langs_str, RESOLUTIONS=res_str, GENRES=genres_str, OTT_PLATFORMS=otts_str,
            langs=langs_str, resolutions=res_str, genres=genres_str, otts=otts_str,
        )
        base_caption = template_str.format_map(format_args)
        
        base_caption = base_caption.replace("<b>🔊 : </b>\n", "").replace("<b>🖥️ : </b>\n", "").replace("<b>🎥 : </b>\n", "").replace("<b>📺 : #</b>\n", "").replace("<b>📺 : </b>\n", "")
        base_caption = base_caption.replace("✅ <b>  </b>", "✅ <b></b>").replace("✅ <b> ", "✅ <b>").replace(" </b>\n", "</b>\n").replace("🎬 <b> ", "🎬 <b>")
    else:
        base_caption = session.get("caption", "")

    final_caption = base_caption

    if session.get("custom_languages") and session["custom_languages"] != ["BLANK"] and "{LANGUAGES}" not in template_str and "{langs}" not in template_str:
        final_caption += "\n" + session["lang_format"].format_map(SafeDict(langs=langs_str, LANGUAGES=langs_str))
    if session.get("custom_resolutions") and session["custom_resolutions"] != ["BLANK"] and "{RESOLUTIONS}" not in template_str and "{resolutions}" not in template_str:
        final_caption += session["res_format"].format_map(SafeDict(resolutions=res_str, RESOLUTIONS=res_str))
    if session.get("custom_genres") and session["custom_genres"] != ["BLANK"] and "{GENRES}" not in template_str and "{genres}" not in template_str:
        final_caption += session["gen_format"].format_map(SafeDict(genres=genres_str, GENRES=genres_str))
    if session.get("custom_otts") and session["custom_otts"] != ["BLANK"] and "{OTT_PLATFORMS}" not in template_str and "{otts}" not in template_str:
        final_caption += session["ott_format"].format_map(SafeDict(otts=otts_str, OTT_PLATFORMS=otts_str))
        
    if session.get("watermark"):
        final_caption += f"\n\n{session['watermark']}"

    keyboard = build_keyboard(session, session_id)
    
    if session.get("custom_poster") == "BLANK":
        poster_to_use = None
    else:
        poster_to_use = session.get("custom_poster") or (
            movie_details.get("backdrop_url") if session.get("use_landscape") else movie_details.get("poster_url")
        )

    return final_caption, keyboard, poster_to_use


async def update_post_preview(client: Client, session_id: int, chat_id: int, force_resend: bool = False):
    session = post_sessions.get(session_id)
    if not session: return

    is_new = not session.get("last_preview_message_id")

    if is_new or force_resend:
        if not is_new:
            try: await client.delete_messages(chat_id, session["last_preview_message_id"])
            except Exception: pass
        try:
            status_msg = await client.send_message(chat_id, "<i>Generating preview...</i>", reply_to_message_id=session["original_message_id"])
            session["last_preview_message_id"] = status_msg.id
        except Exception:
            try:
                status_msg = await client.send_message(chat_id, "<i>Generating preview...</i>")
                session["last_preview_message_id"] = status_msg.id
            except Exception: return

    try: final_caption, keyboard, poster_to_use = await _build_final_post_content(session, session_id)
    except Exception as e:
        try: await client.send_message(chat_id, f"❌ **BUILD CONTENT ERROR:**\n`{e}`")
        except Exception: pass
        return

    if not final_caption: return

    try:
        is_normal_photo = session.get("photo_mode") and poster_to_use and str(poster_to_use).upper() != "BLANK"

        if is_normal_photo:
            if force_resend:
                old_msg_id = session.get("last_preview_message_id")
                sent_msg = await client.send_photo(
                    chat_id, photo=poster_to_use, caption=final_caption,
                    reply_markup=keyboard, reply_to_message_id=session["original_message_id"]
                )
                session["last_preview_message_id"] = sent_msg.id
                if old_msg_id:
                    try: await client.delete_messages(chat_id, old_msg_id)
                    except Exception: pass
            else:
                try:
                    await client.edit_message_caption(
                        chat_id, session["last_preview_message_id"],
                        caption=final_caption, reply_markup=keyboard
                    )
                except Exception:
                    await update_post_preview(client, session_id, chat_id, force_resend=True)
                    return
        else:
            text_content = f"{final_caption}\n<a href='{poster_to_use}'>&#8205;</a>" if poster_to_use and str(poster_to_use).upper() != "BLANK" else final_caption
            if force_resend:
                old_msg_id = session.get("last_preview_message_id")
                sent_msg = await client.send_message(
                    chat_id, text=text_content, reply_markup=keyboard,
                    reply_to_message_id=session["original_message_id"], disable_web_page_preview=False
                )
                session["last_preview_message_id"] = sent_msg.id
                if old_msg_id:
                    try: await client.delete_messages(chat_id, old_msg_id)
                    except Exception: pass
            else:
                try:
                    await client.edit_message_text(
                        chat_id, session["last_preview_message_id"],
                        text=text_content, reply_markup=keyboard, disable_web_page_preview=False
                    )
                except Exception:
                    await update_post_preview(client, session_id, chat_id, force_resend=True)
                    return
                    
    except Exception as e:
        try: await client.send_message(chat_id, f"❌ **PREVIEW SEND ERROR:**\n`{e}`")
        except Exception: pass


def build_keyboard(session: dict, session_id: int):
    rows = []
    if session.get("buttons"):
        rows.extend(session["buttons"])
    
    # Hide Mode Toggle if we are editing an existing imported post!
    mode_btn = []
    if not session.get("edit_target"):
        mode_btn.append(
            InlineKeyboardButton(
                f"Mode: {'Normal Img' if session.get('photo_mode') else 'Preview Img'}",
                callback_data=f"post:toggle_mode:{session_id}",
            )
        )
    mode_btn.append(
        InlineKeyboardButton(
            f"Poster: {'Landscape' if session['use_landscape'] else 'Portrait'}",
            callback_data=f"post:toggle_poster:{session_id}",
        )
    )

    rows.extend(
        [
            [
                InlineKeyboardButton("✏️ Buttons", callback_data=f"post:buttons_menu:{session_id}"),
                InlineKeyboardButton("✏️ Caption", callback_data=f"post:edit_caption:{session_id}"),
            ],
            [
                InlineKeyboardButton("🖼️ Poster", callback_data=f"post:set_poster:{session_id}"),
                InlineKeyboardButton("✨ Templates", callback_data=f"post:templates:{session_id}"),
                InlineKeyboardButton("💧 Watermark", callback_data=f"post:set_watermark:{session_id}"),
            ],
            [
                InlineKeyboardButton("🔊", callback_data=f"post:languages:{session_id}"),
                InlineKeyboardButton("🖥️", callback_data=f"post:resolutions:{session_id}"),
                InlineKeyboardButton("🎥", callback_data=f"post:genres:{session_id}"),
                InlineKeyboardButton("📺", callback_data=f"post:otts:{session_id}"),
            ],
            mode_btn,
            [
                InlineKeyboardButton("✅ Post", callback_data=f"post:finalize:{session_id}"),
                InlineKeyboardButton("❌ Cancel", callback_data=f"post:cancel:{session_id}"),
            ],
        ]
    )
    return InlineKeyboardMarkup(rows)


@Client.on_callback_query(filters.regex(r"^post:"), group=-4)
async def post_callbacks(client: Client, query: CallbackQuery):
    try:
        data_parts = query.data.split(":")
        action = data_parts[1]

        try: session_id = int(data_parts[2])
        except ValueError: return await query.answer("Invalid Session ID.", show_alert=True)

        extra_data = data_parts[3:]

        if query.from_user.id != session_id:
            return await query.answer("This is not for you!", show_alert=True)

        session = post_sessions.get(session_id)
        if not session:
            await query.answer("Session expired or was cancelled.", show_alert=True)
            try: return await query.message.delete()
            except Exception: return

        force_resend = False

        if action == "back":
            await query.answer()

        elif action in [
            "languages", "resolutions", "templates", "buttons_menu",
            "remove_buttons_menu", "genres", "otts",
        ]:
            await query.answer()
            if action == "languages": await show_selection_menu(query, session_id, "languages")
            elif action == "resolutions": await show_selection_menu(query, session_id, "resolutions")
            elif action == "genres": await show_selection_menu(query, session_id, "genres")
            elif action == "otts": await show_selection_menu(query, session_id, "otts")
            elif action == "templates": await handle_templates_menu(query, session_id)
            elif action == "buttons_menu": await handle_buttons_menu(query, session_id)
            elif action == "remove_buttons_menu": await handle_remove_buttons_menu(query, session_id)
            return

        elif action in ["select_lang", "select_res", "select_gen", "select_ott"]:
            await query.answer()
            item = extra_data[0]
            if action == "select_lang":
                if "BLANK" in session["custom_languages"]: session["custom_languages"] = []
                if item not in session["custom_languages"]: session["custom_languages"].append(item)
                else: session["custom_languages"].remove(item)
                await show_selection_menu(query, session_id, "languages")
            elif action == "select_res":
                if "BLANK" in session["custom_resolutions"]: session["custom_resolutions"] = []
                if item not in session["custom_resolutions"]: session["custom_resolutions"].append(item)
                else: session["custom_resolutions"].remove(item)
                await show_selection_menu(query, session_id, "resolutions")
            elif action == "select_gen":
                if "BLANK" in session["custom_genres"]: session["custom_genres"] = []
                if item not in session["custom_genres"]: session["custom_genres"].append(item)
                else: session["custom_genres"].remove(item)
                await show_selection_menu(query, session_id, "genres")
            elif action == "select_ott":
                if "BLANK" in session["custom_otts"]: session["custom_otts"] = []
                if item not in session["custom_otts"]: session["custom_otts"].append(item)
                else: session["custom_otts"].remove(item)
                await show_selection_menu(query, session_id, "otts")
            return

        else:
            if action == "edit_buttons":
                await handle_edit_buttons(client, query, session_id)
                return
            elif action == "add_get_files":
                added = await handle_add_get_files(client, session)
                await query.answer("✅ 'Get Files' button added!" if added else "⚠️ Button already exists!", show_alert=not added)
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
            elif action == "toggle_poster":
                session["use_landscape"] = not session["use_landscape"]
                force_resend = True
            elif action == "toggle_mode":
                if not session.get("edit_target"):
                    session["photo_mode"] = not session.get("photo_mode")
                    force_resend = True
                else:
                    await query.answer("You cannot switch image modes on an imported channel post!", show_alert=True)
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

        await update_post_preview(client, session_id, query.message.chat.id, force_resend)
    except Exception as e:
        await query.message.reply_text(f"❌ **CALLBACK ERROR:**\n`{e}`")


async def show_selection_menu(query: CallbackQuery, session_id: int, menu_type: str):
    session = post_sessions[session_id]

    if menu_type == "languages":
        items, selected, action_prefix, format_action = LANGUAGES, session["custom_languages"], "select_lang", "format_lang"
    elif menu_type == "resolutions":
        items, selected, action_prefix, format_action = RESOLUTIONS, session["custom_resolutions"], "select_res", "format_res"
    elif menu_type == "genres":
        items, selected, action_prefix, format_action = GENRES, session["custom_genres"], "select_gen", "format_gen"
    elif menu_type == "otts":
        items, selected, action_prefix, format_action = OTT_PLATFORMS, session["custom_otts"], "select_ott", "format_ott"
    else: return

    buttons = [InlineKeyboardButton(f"✅ {i}" if i in selected else i, callback_data=f"post:{action_prefix}:{session_id}:{i}") for i in items]
    keyboard = [buttons[i : i + 3] for i in range(0, len(buttons), 3)]
    keyboard.append([InlineKeyboardButton("⚙️ Change Format", callback_data=f"post:{format_action}:{session_id}")])
    keyboard.append([InlineKeyboardButton("✅ Done", callback_data=f"post:back:{session_id}")])

    try: await query.edit_message_reply_markup(InlineKeyboardMarkup(keyboard))
    except MessageNotModified: pass


async def get_user_input(client, query, session, prompt_text):
    try: ask_msg = await query.message.reply_text(prompt_text, reply_to_message_id=session.get("original_message_id"))
    except Exception: ask_msg = await query.message.reply_text(prompt_text)

    try:
        response = await client.listen(chat_id=query.message.chat.id, user_id=query.from_user.id, timeout=300)
        try: await ask_msg.delete()
        except Exception: pass
        
        if response:
            try: await response.delete()
            except Exception: pass
            return response
    except asyncio.TimeoutError:
        try:
            await ask_msg.edit("Timeout (5 minutes). The operation was cancelled.")
            await asyncio.sleep(3)
            await ask_msg.delete()
        except Exception: pass
    return None


async def handle_buttons_menu(query, session_id):
    buttons = [
        [InlineKeyboardButton("➕ Add/Edit Layout", callback_data=f"post:edit_buttons:{session_id}")],
        [InlineKeyboardButton("📥 Add 'Get Files' Button", callback_data=f"post:add_get_files:{session_id}")],
        [InlineKeyboardButton("🗑️ Remove a Button", callback_data=f"post:remove_buttons_menu:{session_id}")],
        [InlineKeyboardButton("Back", callback_data=f"post:back:{session_id}")],
    ]
    try: await query.edit_message_reply_markup(InlineKeyboardMarkup(buttons))
    except MessageNotModified: pass


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
                    clean_text = text.replace("[", "").replace("]", "").replace("(", "").replace(")", "").strip()
                    row_btns.append(InlineKeyboardButton(clean_text, url=clean_url))
            if row_btns: new_layout.append(row_btns)
        session["buttons"] = new_layout
    await update_post_preview(client, session_id, query.message.chat.id, force_resend=False)


# ============================================================
# 🔗 GENERATES YOUR BUTTONS DYNAMICALLY
# ============================================================
async def handle_add_get_files(client: Client, session: dict) -> bool:
    movie_details = session["movie_details"]
    if movie_details:
        title = str(movie_details.get("title", "movie")).replace("(", "").replace(")", "").replace("[", "").replace("]", "")
        year = str(movie_details.get("year", "")).replace("(", "").replace(")", "").replace("[", "").replace("]", "")
        movie_year = f"{title} {year}".strip()

        safe_query = re.sub(r"[^a-zA-Z0-9_-]", "_", movie_year)
        safe_query = re.sub(r"_+", "_", safe_query).strip("_")
        safe_query = safe_query[:50]

        bot_username = temp.U_NAME or "MovieBot"
        url = f"https://t.me/{bot_username}?start=search_{safe_query}"

        for row in session["buttons"]:
            for btn in row:
                if btn.url == url: return False

        session["buttons"].append([
            InlineKeyboardButton(text="Group 1 🎬", url="https://t.me/Sandalwood_Kannada_Group", icon_custom_emoji_id=5258096772776991776, style=ButtonStyle.PRIMARY),
            InlineKeyboardButton(text="Group 2 🎬", url="https://t.me/+GLsPkRgLGGszMzY1", icon_custom_emoji_id=5258096772776991776, style=ButtonStyle.PRIMARY),
        ])
        session["buttons"].append([
            InlineKeyboardButton(text="Direct Search 🔎", url=url, icon_custom_emoji_id=5258503720928288433, style=ButtonStyle.SUCCESS)
        ])
        return True
    return False


async def handle_edit_caption(client: Client, query: CallbackQuery, session_id: int):
    session = post_sessions[session_id]
    response = await get_user_input(client, query, session, "Send the new caption text.")
    if response and response.text:
        session["caption"] = response.text
        session["is_manual_caption"] = True
    await update_post_preview(client, session_id, query.message.chat.id, force_resend=False)


async def handle_set_poster(client: Client, query: CallbackQuery, session_id: int):
    session = post_sessions[session_id]
    response = await get_user_input(client, query, session, "📸 Send a photo or an image URL.\n*(Or type `/reset` to use the default poster, or `blank` to remove the image)*")
    if response:
        if response.photo:
            if session.get("edit_target") and not session.get("photo_mode"):
                status_msg = await query.message.reply_text("⏳ Uploading to secure image host for preview...")
                url, err = await upload_image_safely(client, response)
                if url:
                    session["custom_poster"] = url
                    try: await status_msg.edit_text("✅ Image successfully uploaded and set as rich preview!")
                    except Exception: pass
                else:
                    try: await status_msg.edit_text(err)
                    except Exception: pass
            else:
                status_msg = await query.message.reply_text("⏳ Uploading image for preview...")
                url, err = await upload_image_safely(client, response)
                if url:
                    session["custom_poster"] = url
                    if not session.get("edit_target"): session["photo_mode"] = False
                    try: await status_msg.edit_text("✅ Image set as rich preview!")
                    except Exception: pass
                else:
                    try: await status_msg.edit_text(err)
                    except Exception: pass
                
        elif response.text:
            text_input = response.text.strip().lower()
            if text_input == "/reset":
                session["custom_poster"] = None
                if not session.get("edit_target"): session["photo_mode"] = False
            elif text_input == "blank": session["custom_poster"] = "BLANK"
            elif response.text.startswith("http"):
                session["custom_poster"] = response.text.strip()
                if not session.get("edit_target"): session["photo_mode"] = False
    return True


async def handle_set_watermark(client, query, session_id: int):
    session = post_sessions[session_id]
    prompt_text = "Send the watermark text. HTML is supported.\n\n• Send `blank` or `/reset` to remove the watermark.\n• Send `/default` to use the default watermark."
    response = await get_user_input(client, query, session, prompt_text)
    if response and response.text:
        text_input = response.text.strip().lower()
        if text_input in ["/reset", "blank"]: session["watermark"] = ""
        elif text_input == "/default": session["watermark"] = DEFAULT_WATERMARK
        else: session["watermark"] = response.text
    await update_post_preview(client, session_id, query.message.chat.id, force_resend=False)


async def handle_format_lang(client, query, session_id: int):
    session = post_sessions[session_id]
    response = await get_user_input(client, query, session, f"Send the format for languages. Must include `{{langs}}` as a placeholder. Send `/reset` for default.\n\n Current: {html.escape(session['lang_format'])}")
    if response and response.text:
        if response.text == "/reset": session["lang_format"] = LANGUAGES_FORMAT
        elif "{langs}" not in response.text:
            try: await query.message.reply_text("⚠️ Invalid format! The format must contain `{langs}` placeholder.", quote=True)
            except Exception: pass
        else: session["lang_format"] = response.text
    await update_post_preview(client, session_id, query.message.chat.id, force_resend=False)


async def handle_format_res(client, query, session_id: int):
    session = post_sessions[session_id]
    response = await get_user_input(client, query, session, f"Send the format for qualities. Must include `{{resolutions}}` as a placeholder. Send `/reset` for default.\n\n Current: {html.escape(session['res_format'])}")
    if response and response.text:
        if response.text == "/reset": session["res_format"] = RESOLUTIONS_FORMAT
        elif "{resolutions}" not in response.text:
            try: await query.message.reply_text("⚠️ Invalid format! The format must contain `{resolutions}` placeholder.", quote=True)
            except Exception: pass
        else: session["res_format"] = response.text
    await update_post_preview(client, session_id, query.message.chat.id, force_resend=False)


async def handle_format_gen(client, query, session_id: int):
    session = post_sessions[session_id]
    response = await get_user_input(client, query, session, f"Send the format for genres. Must include `{{genres}}` as a placeholder. Send `/reset` for default.\n\n Current: {html.escape(session['gen_format'])}")
    if response and response.text:
        if response.text == "/reset": session["gen_format"] = GENRES_FORMAT
        elif "{genres}" not in response.text:
            try: await query.message.reply_text("⚠️ Invalid format! The format must contain `{genres}` placeholder.", quote=True)
            except Exception: pass
        else: session["gen_format"] = response.text
    await update_post_preview(client, session_id, query.message.chat.id, force_resend=False)


async def handle_format_ott(client, query, session_id: int):
    session = post_sessions[session_id]
    response = await get_user_input(client, query, session, f"Send the format for OTT. Must include `{{otts}}` as a placeholder. Send `/reset` for default.\n\n Current: {html.escape(session['ott_format'])}")
    if response and response.text:
        if response.text == "/reset": session["ott_format"] = OTT_FORMAT
        elif "{otts}" not in response.text:
            try: await query.message.reply_text("⚠️ Invalid format! The format must contain `{otts}` placeholder.", quote=True)
            except Exception: pass
        else: session["ott_format"] = response.text
    await update_post_preview(client, session_id, query.message.chat.id, force_resend=False)


async def handle_templates_menu(query, session_id: int):
    session = post_sessions[session_id]
    buttons = []
    for name in TEMPLATES:
        text = f"✅ {name}" if session.get("active_template") == name else name
        buttons.append([InlineKeyboardButton(text, callback_data=f"post:select_template:{query.from_user.id}:{name}")])
    buttons.append([InlineKeyboardButton("Back", callback_data=f"post:back:{query.from_user.id}")])
    try: await query.edit_message_reply_markup(InlineKeyboardMarkup(buttons))
    except MessageNotModified: pass


async def handle_select_template(session, template_name):
    session["active_template"] = template_name
    session["is_manual_caption"] = False
    session["caption"] = None


async def handle_remove_buttons_menu(query, session_id: int):
    session = post_sessions[session_id]
    buttons = []
    for i, row in enumerate(session["buttons"]):
        for j, btn in enumerate(row):
            buttons.append([InlineKeyboardButton(f"❌ {btn.text}", callback_data=f"post:remove_button:{query.from_user.id}:{i}:{j}")])
    if not buttons: buttons.append([InlineKeyboardButton("No buttons to remove", callback_data="noop")])
    buttons.append([InlineKeyboardButton("Back", callback_data=f"post:back:{query.from_user.id}")])
    try: await query.edit_message_reply_markup(InlineKeyboardMarkup(buttons))
    except MessageNotModified: pass


async def handle_remove_button(session, extra_data):
    try:
        row_i, col_i = int(extra_data[0]), int(extra_data[1])
        session["buttons"][row_i].pop(col_i)
        if not session["buttons"][row_i]: session["buttons"].pop(row_i)
    except (IndexError, ValueError): pass


async def handle_cancel(client: Client, query: CallbackQuery, session_id: int, _=None):
    if session := post_sessions.pop(session_id, None):
        if session.get("last_preview_message_id"):
            try: await client.delete_messages(query.message.chat.id, session["last_preview_message_id"])
            except Exception: pass
    try: await query.message.reply_to_message.reply_text("Post creation cancelled.")
    except Exception: pass


def get_final_keyboard(session: dict):
    rows = []
    if session.get("buttons"):
        rows.extend(session["buttons"])
    return InlineKeyboardMarkup(rows) if rows else None


async def finalize_and_post(client: Client, query: CallbackQuery, session_id: int, _=None):
    session = post_sessions.pop(session_id, None)
    if not session: return

    try: await client.delete_messages(query.message.chat.id, session["last_preview_message_id"])
    except Exception: pass

    try: status_msg = await query.message.reply_to_message.reply_text("<i>Finalizing and posting...</i>")
    except Exception: status_msg = None

    final_caption, _, poster_to_use = await _build_final_post_content(session, session_id)
    final_keyboard = get_final_keyboard(session)

    if not final_caption:
        if status_msg:
            try: await status_msg.edit("Could not fetch movie details to post. Aborting.")
            except Exception: pass
        return

    is_normal_photo = session.get("photo_mode") and poster_to_use and str(poster_to_use).upper() != "BLANK"

    try:
        edit_target = session.get("edit_target")
        if edit_target:
            if is_normal_photo:
                await client.edit_message_media(
                    chat_id=edit_target["chat_id"],
                    message_id=edit_target["message_id"],
                    media=InputMediaPhoto(media=poster_to_use, caption=final_caption),
                    reply_markup=final_keyboard
                )
            else:
                text_content = f"{final_caption}\n<a href='{poster_to_use}'>&#8205;</a>" if poster_to_use and str(poster_to_use).upper() != "BLANK" else final_caption
                await client.edit_message_text(
                    chat_id=edit_target["chat_id"],
                    message_id=edit_target["message_id"],
                    text=text_content,
                    reply_markup=final_keyboard,
                    disable_web_page_preview=False,
                )
            if status_msg:
                try: await status_msg.edit("✅ Original post has been updated successfully!")
                except Exception: pass
        else:
            if not MOVIE_UPDATE_CHANNEL:
                if status_msg:
                    try: await status_msg.edit("❌ **MOVIE_UPDATE_CHANNEL is not set in config!**")
                    except Exception: pass
                return
            
            if is_normal_photo:
                await client.send_photo(
                    chat_id=MOVIE_UPDATE_CHANNEL,
                    photo=poster_to_use,
                    caption=final_caption,
                    reply_markup=final_keyboard,
                )
            else:
                text_content = f"{final_caption}\n<a href='{poster_to_use}'>&#8205;</a>" if poster_to_use and str(poster_to_use).upper() != "BLANK" else final_caption
                await client.send_message(
                    chat_id=MOVIE_UPDATE_CHANNEL,
                    text=text_content,
                    reply_markup=final_keyboard,
                    disable_web_page_preview=False,
                )

            if status_msg:
                try: await status_msg.edit("✅ Post has been sent to the update channel.")
                except Exception: pass
            
    except ButtonUrlInvalid:
        if status_msg:
            try: await status_msg.edit("❌ **Post Failed:** One of the button URLs is invalid. Ensure all URLs start with `http://` or `https://`.")
            except Exception: pass
    except MessageTooLong:
        if status_msg:
            try: await status_msg.edit("<b>Post Failed</b>\n\nThe final caption is too long for a Telegram message. Please shorten the plot.")
            except Exception: pass
    except Exception as e:
        if status_msg:
            try: await status_msg.edit(f"Failed to post to update channel.\n<b>Error:</b> <code>{e}</code>")
            except Exception: pass
