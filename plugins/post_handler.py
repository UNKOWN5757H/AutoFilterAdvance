import asyncio
import html
import math
import os
import re
import traceback
from io import BytesIO
from logging import ERROR, getLogger

import requests
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

post_sessions = {}
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
    if icon_custom_emoji_id is not None:
        kwargs["icon_custom_emoji_id"] = icon_custom_emoji_id
    try:
        return InlineKeyboardButton(**kwargs)
    except TypeError as e:
        err_str = str(e)
        if "icon_custom_emoji_id" in err_str:
            kwargs.pop("icon_custom_emoji_id", None)
        if "style" in err_str:
            kwargs.pop("style", None)
        try:
            return InlineKeyboardButton(**kwargs)
        except TypeError:
            kwargs.pop("style", None)
            kwargs.pop("icon_custom_emoji_id", None)
            return InlineKeyboardButton(**kwargs)


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


@Client.on_message(filters.command("post") & admin_filter, group=-4)
async def post_command(client: Client, message: Message):
    try:
        if len(message.command) == 1:
            return await message.reply_text(
                "Please provide a movie name. Usage: `/post The Dark Knight`"
            )
        movie_name = " ".join(message.command[1:])
        await start_post_session(client, message, message.from_user.id, movie_name)
    except Exception as e:
        await message.reply_text(f"❌ **COMMAND ERROR:**\n`{e}`")


# ⚡ REBUILT /EDITPOST COMMAND (LOCKED MANUAL MODE TO PREVENT CORRUPTION)
@Client.on_message(filters.command("editpost") & admin_filter, group=-4)
async def edit_post_cmd(client: Client, message: Message):
    try:
        if len(message.command) < 2:
            return await message.reply_text(
                "❌ Please provide a post link.\n**Usage:** `/editpost https://t.me/c/1923564465/1410`"
            )
        link = message.command[1]

        if "t.me/c/" in link:
            parts = link.split("/")
            chat_id, msg_id = int("-100" + parts[-2]), int(parts[-1])
        elif "t.me/" in link:
            parts = link.split("/")
            chat_id = parts[-2]
            if not chat_id.startswith("@"):
                chat_id = "@" + chat_id
            msg_id = int(parts[-1])
        else:
            return await message.reply_text("❌ Invalid Telegram link format.")

        status_msg = await message.reply_text(
            "⏳ Fetching and analyzing post from channel..."
        )
        try:
            target_msg = await client.get_messages(chat_id, msg_id)
            if not target_msg or target_msg.empty:
                return await status_msg.edit_text(
                    "❌ Message not found. Make sure the bot is an admin in the channel."
                )
        except Exception as e:
            return await status_msg.edit_text(f"❌ Could not fetch message:\n`{e}`")

        user_id = message.from_user.id
        poster_url, html_text, is_photo_mode = None, "", False

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

        # Simple Fallback extraction for UI representation
        title_match = re.search(r"<b>(.*?)</b>", html_text.split("\n")[0])
        search_name = title_match.group(1).strip() if title_match else "Unknown Movie"

        await status_msg.edit_text(f"⏳ Restoring layout for **{search_name}**...")

        buttons = []
        if target_msg.reply_markup and target_msg.reply_markup.inline_keyboard:
            for row in target_msg.reply_markup.inline_keyboard:
                row_btns = []
                for btn in row:
                    kwargs = {
                        "text": btn.text,
                        "url": btn.url,
                        "callback_data": btn.callback_data,
                    }
                    row_btns.append(
                        InlineKeyboardButton(**{k: v for k, v in kwargs.items() if v})
                    )
                buttons.append(row_btns)

        if user_id in post_sessions and post_sessions[user_id].get(
            "last_preview_message_id"
        ):
            try:
                await client.delete_messages(
                    message.chat.id, post_sessions[user_id]["last_preview_message_id"]
                )
            except Exception:
                pass

        # ⚡ CRITICAL FIX: is_manual_caption locks the exact original HTML text, preventing `{LANGUAGES}` from regenerating inside blockquotes!
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
            "last_preview_message_id": status_msg.id,
            "original_message_id": message.id,
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

        await update_post_preview(client, user_id, message.chat.id, force_resend=True)
    except Exception as e:
        await message.reply_text(f"❌ **EDIT POST ERROR:**\n`{e}`")


@Client.on_message(
    filters.command(["editposttitle", "edittitle", "edittittle"]) & admin_filter,
    group=-4,
)
async def edit_title_cmd(client: Client, message: Message):
    user_id = message.from_user.id
    if user_id not in post_sessions:
        return await message.reply_text("❌ No active post session.")
    session = post_sessions[user_id]

    if len(message.command) > 1:
        new_title = message.text.split(None, 1)[1].strip()
        if new_title.lower() == "blank":
            new_title = "BLANK"
        session["movie_details"]["title"] = new_title
        await message.reply_text(
            "✅ Title cleared!"
            if new_title == "BLANK"
            else f"✅ Title updated to: **{new_title}**"
        )
        await update_post_preview(client, user_id, message.chat.id, force_resend=False)
    else:
        ask_msg = await message.reply_text(
            "✏️ **Please send the new Title now.**\n*(Type `blank` to remove the title entirely)*"
        )
        try:
            response = await native_listen(client, message.chat.id, user_id, 120)
            await ask_msg.delete()
            if response.text:
                new_title = response.text.strip()
                if new_title.lower() == "blank":
                    new_title = "BLANK"
                session["movie_details"]["title"] = new_title
                await message.reply_text(
                    "✅ Title cleared!"
                    if new_title == "BLANK"
                    else f"✅ Title updated to: **{new_title}**"
                )
                await update_post_preview(
                    client, user_id, message.chat.id, force_resend=False
                )
            else:
                await message.reply_text("⚠️ Invalid input. Must be text.")
            try:
                await response.delete()
            except Exception:
                pass
        except asyncio.TimeoutError:
            await ask_msg.edit_text("⌛ Timeout. Title edit cancelled.")


@Client.on_message(
    filters.command(["editpostyear", "edityear"]) & admin_filter, group=-4
)
async def edit_year_cmd(client: Client, message: Message):
    user_id = message.from_user.id
    if user_id not in post_sessions:
        return await message.reply_text("❌ No active post session.")
    session = post_sessions[user_id]

    if len(message.command) > 1:
        new_year = message.text.split(None, 1)[1].strip()
        if new_year.lower() == "blank":
            new_year = "BLANK"
        session["movie_details"]["year"] = new_year
        await message.reply_text(
            "✅ Year cleared!"
            if new_year == "BLANK"
            else f"✅ Year updated to: **{new_year}**"
        )
        await update_post_preview(client, user_id, message.chat.id, force_resend=False)
    else:
        ask_msg = await message.reply_text(
            "✏️ **Please send the new Year now.**\n*(Type `blank` to remove the year entirely)*"
        )
        try:
            response = await native_listen(client, message.chat.id, user_id, 120)
            await ask_msg.delete()
            if response.text:
                new_year = response.text.strip()
                if new_year.lower() == "blank":
                    new_year = "BLANK"
                session["movie_details"]["year"] = new_year
                await message.reply_text(
                    "✅ Year cleared!"
                    if new_year == "BLANK"
                    else f"✅ Year updated to: **{new_year}**"
                )
                await update_post_preview(
                    client, user_id, message.chat.id, force_resend=False
                )
            else:
                await message.reply_text("⚠️ Invalid input. Must be text.")
            try:
                await response.delete()
            except Exception:
                pass
        except asyncio.TimeoutError:
            await ask_msg.edit_text("⌛ Timeout. Year edit cancelled.")


@Client.on_message(filters.command(["editpostbutton"]) & admin_filter, group=-4)
async def edit_post_button_cmd(client: Client, message: Message):
    user_id = message.from_user.id
    if user_id not in post_sessions:
        return await message.reply_text("❌ No active post session.")
    if len(message.command) < 2 or "|" not in message.text:
        return await message.reply_text(
            "❌ **Usage:** `/editpostbutton <number> <Text> | <URL>`\nExample: `/editpostbutton 1 Group 1 🎬 | https://newlink.com`"
        )

    try:
        parts = message.text.split(None, 2)
        btn_num = int(parts[1])
        text_part, url_part = parts[2].split("|", 1)
    except Exception:
        return await message.reply_text("❌ Invalid format.")

    session = post_sessions[user_id]
    count, found = 0, False
    for r_idx, row in enumerate(session["buttons"]):
        for c_idx, btn in enumerate(row):
            count += 1
            if count == btn_num:
                btn_args = {"text": text_part.strip(), "url": url_part.strip()}
                if hasattr(btn, "style") and btn.style:
                    btn_args["style"] = btn.style
                if hasattr(btn, "icon_custom_emoji_id") and btn.icon_custom_emoji_id:
                    btn_args["icon_custom_emoji_id"] = btn.icon_custom_emoji_id
                session["buttons"][r_idx][c_idx] = create_btn(**btn_args)
                found = True
                break
        if found:
            break

    if found:
        await message.reply_text(f"✅ Button {btn_num} successfully updated!")
        await update_post_preview(client, user_id, message.chat.id, force_resend=False)
    else:
        await message.reply_text(f"❌ Button {btn_num} not found in the layout.")


@Client.on_message(
    filters.command(["editpostbuttoncolour", "editbuttoncolour"]) & admin_filter,
    group=-4,
)
async def edit_button_colour_cmd(client: Client, message: Message):
    user_id = message.from_user.id
    if user_id not in post_sessions:
        return await message.reply_text("❌ No active post session.")
    if len(message.command) < 3:
        return await message.reply_text(
            "❌ **Usage:** `/editpostbuttoncolour <button_number> <colour>`\n\n**Example:** `/editpostbuttoncolour 1 green`\n**Colours:** `green`, `red`, `blue`"
        )

    try:
        btn_num = int(message.command[1])
    except ValueError:
        return await message.reply_text("❌ Button number must be an integer.")

    color_str = message.command[2].lower()
    color_map = {"green": BTN_SUCCESS, "red": BTN_DANGER, "blue": BTN_PRIMARY}
    if color_str not in color_map:
        return await message.reply_text(
            "❌ Invalid colour. Choose from: `green`, `red`, `blue`."
        )

    session = post_sessions[user_id]
    if not session.get("buttons"):
        return await message.reply_text("❌ No buttons currently in the layout.")

    count, found = 0, False
    for r_idx, row in enumerate(session["buttons"]):
        for c_idx, btn in enumerate(row):
            count += 1
            if count == btn_num:
                btn_args = {"text": btn.text}
                if hasattr(btn, "url") and btn.url:
                    btn_args["url"] = btn.url
                if hasattr(btn, "callback_data") and btn.callback_data:
                    btn_args["callback_data"] = btn.callback_data
                if hasattr(btn, "icon_custom_emoji_id") and btn.icon_custom_emoji_id:
                    btn_args["icon_custom_emoji_id"] = btn.icon_custom_emoji_id
                btn_args["style"] = color_map[color_str]
                session["buttons"][r_idx][c_idx] = create_btn(**btn_args)
                found = True
                break
        if found:
            break

    if not found:
        return await message.reply_text(
            f"❌ Button number {btn_num} not found. You only have {count} buttons."
        )
    await message.reply_text(
        f"✅ Button {btn_num} colour changed to {color_str.title()}!"
    )
    await update_post_preview(client, user_id, message.chat.id, force_resend=False)


@Client.on_message(
    filters.command(["editpostdirect", "editdirect"]) & admin_filter, group=-4
)
async def edit_direct_url(client: Client, message: Message):
    user_id = message.from_user.id
    if user_id not in post_sessions:
        return await message.reply_text("❌ No active post session.")
    session = post_sessions[user_id]

    if len(message.command) > 1:
        new_url = message.text.split(None, 1)[1].strip()
    else:
        ask_msg = await message.reply_text(
            "✏️ **Please send the new URL now.**\n*(Type `blank` to remove the Direct Search button entirely)*"
        )
        try:
            response = await native_listen(client, message.chat.id, user_id, 120)
            await ask_msg.delete()
            if response.text:
                new_url = response.text.strip()
            else:
                return await message.reply_text(
                    "⚠️ Invalid input. Must be a URL or 'blank'."
                )
            try:
                await response.delete()
            except Exception:
                pass
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
            for r_idx, row in enumerate(session["buttons"]):
                for c_idx, btn in enumerate(row):
                    if btn.text == "Direct Search 🔎":
                        btn_args = {"text": btn.text, "url": new_url}
                        if hasattr(btn, "style") and btn.style:
                            btn_args["style"] = btn.style
                        if (
                            hasattr(btn, "icon_custom_emoji_id")
                            and btn.icon_custom_emoji_id
                        ):
                            btn_args["icon_custom_emoji_id"] = btn.icon_custom_emoji_id
                        session["buttons"][r_idx][c_idx] = create_btn(**btn_args)
                        button_updated = True
        if button_updated:
            await message.reply_text(
                f"✅ **'Direct Search' button URL updated successfully!**\n\n🔗 **New URL:** `{new_url}`"
            )

    if button_updated:
        await update_post_preview(client, user_id, message.chat.id, force_resend=False)
    else:
        await message.reply_text(
            "❌ **Button not found!** Ensure you have the 'Direct Search 🔎' button added to your layout first."
        )


@Client.on_message(
    filters.command(["editpostlangs", "editlangs"]) & admin_filter, group=-4
)
async def edit_langs_cmd(client: Client, message: Message):
    user_id = message.from_user.id
    if user_id not in post_sessions:
        return await message.reply_text("❌ No active post session.")
    session = post_sessions[user_id]

    if len(message.command) > 1:
        text_input = message.text.split(None, 1)[1].strip()
        new_langs = (
            ["BLANK"]
            if text_input.lower() == "blank"
            else [lang.strip() for lang in text_input.split(",")]
        )
    else:
        ask_msg = await message.reply_text(
            "✏️ **Please send languages separated by commas now.**\n*(Type `blank` to remove the languages line entirely)*"
        )
        try:
            response = await native_listen(client, message.chat.id, user_id, 120)
            await ask_msg.delete()
            if response.text:
                text_input = response.text.strip()
                new_langs = (
                    ["BLANK"]
                    if text_input.lower() == "blank"
                    else [lang.strip() for lang in text_input.split(",")]
                )
            else:
                return await message.reply_text("⚠️ Invalid input. Must be text.")
            try:
                await response.delete()
            except Exception:
                pass
        except asyncio.TimeoutError:
            return await ask_msg.edit_text("⌛ Timeout. Edit cancelled.")

    session["custom_languages"] = new_langs
    await message.reply_text(
        "✅ Languages line removed!"
        if new_langs == ["BLANK"]
        else f"✅ Languages updated to: **{', '.join(new_langs)}**"
    )
    await update_post_preview(client, user_id, message.chat.id, force_resend=False)


@Client.on_message(
    filters.command(["editpostresolutions", "editresolutions"]) & admin_filter, group=-4
)
async def edit_resolutions_cmd(client: Client, message: Message):
    user_id = message.from_user.id
    if user_id not in post_sessions:
        return await message.reply_text("❌ No active post session.")
    session = post_sessions[user_id]

    if len(message.command) > 1:
        text_input = message.text.split(None, 1)[1].strip()
        new_res = (
            ["BLANK"]
            if text_input.lower() == "blank"
            else [res.strip() for res in text_input.split(",")]
        )
    else:
        ask_msg = await message.reply_text(
            "✏️ **Please send resolutions separated by commas now.**\n*(Type `blank` to remove the resolutions line entirely)*"
        )
        try:
            response = await native_listen(client, message.chat.id, user_id, 120)
            await ask_msg.delete()
            if response.text:
                text_input = response.text.strip()
                new_res = (
                    ["BLANK"]
                    if text_input.lower() == "blank"
                    else [res.strip() for res in text_input.split(",")]
                )
            else:
                return await message.reply_text("⚠️ Invalid input. Must be text.")
            try:
                await response.delete()
            except Exception:
                pass
        except asyncio.TimeoutError:
            return await ask_msg.edit_text("⌛ Timeout. Edit cancelled.")

    session["custom_resolutions"] = new_res
    await message.reply_text(
        "✅ Resolutions line removed!"
        if new_res == ["BLANK"]
        else f"✅ Resolutions updated to: **{', '.join(new_res)}**"
    )
    await update_post_preview(client, user_id, message.chat.id, force_resend=False)


@Client.on_message(
    filters.command(["editpostgenres", "editgenres"]) & admin_filter, group=-4
)
async def edit_genres_cmd(client: Client, message: Message):
    user_id = message.from_user.id
    if user_id not in post_sessions:
        return await message.reply_text("❌ No active post session.")
    session = post_sessions[user_id]

    if len(message.command) > 1:
        text_input = message.text.split(None, 1)[1].strip()
        new_genres = (
            ["BLANK"]
            if text_input.lower() == "blank"
            else [gen.strip() for gen in text_input.split(",")]
        )
    else:
        ask_msg = await message.reply_text(
            "✏️ **Please send genres separated by commas now.**\n*(Type `blank` to remove the genres line entirely)*"
        )
        try:
            response = await native_listen(client, message.chat.id, user_id, 120)
            await ask_msg.delete()
            if response.text:
                text_input = response.text.strip()
                new_genres = (
                    ["BLANK"]
                    if text_input.lower() == "blank"
                    else [gen.strip() for gen in text_input.split(",")]
                )
            else:
                return await message.reply_text("⚠️ Invalid input. Must be text.")
            try:
                await response.delete()
            except Exception:
                pass
        except asyncio.TimeoutError:
            return await ask_msg.edit_text("⌛ Timeout. Edit cancelled.")

    session["custom_genres"] = new_genres
    await message.reply_text(
        "✅ Genres line removed!"
        if new_genres == ["BLANK"]
        else f"✅ Genres updated to: **{', '.join(new_genres)}**"
    )
    await update_post_preview(client, user_id, message.chat.id, force_resend=False)


@Client.on_message(
    filters.command(["editpostotts", "editotts"]) & admin_filter, group=-4
)
async def edit_otts_cmd(client: Client, message: Message):
    user_id = message.from_user.id
    if user_id not in post_sessions:
        return await message.reply_text("❌ No active post session.")
    session = post_sessions[user_id]

    if len(message.command) > 1:
        text_input = message.text.split(None, 1)[1].strip()
        new_otts = (
            ["BLANK"]
            if text_input.lower() == "blank"
            else [ott.strip() for ott in text_input.split(",")]
        )
    else:
        ask_msg = await message.reply_text(
            "✏️ **Please send OTT platforms separated by commas now.**\n*(Type `blank` to remove the OTTs line entirely)*"
        )
        try:
            response = await native_listen(client, message.chat.id, user_id, 120)
            await ask_msg.delete()
            if response.text:
                text_input = response.text.strip()
                new_otts = (
                    ["BLANK"]
                    if text_input.lower() == "blank"
                    else [ott.strip() for ott in text_input.split(",")]
                )
            else:
                return await message.reply_text("⚠️ Invalid input. Must be text.")
            try:
                await response.delete()
            except Exception:
                pass
        except asyncio.TimeoutError:
            return await ask_msg.edit_text("⌛ Timeout. Edit cancelled.")

    session["custom_otts"] = new_otts
    await message.reply_text(
        "✅ OTT line removed!"
        if new_otts == ["BLANK"]
        else f"✅ OTTs updated to: **{', '.join(new_otts)}**"
    )
    await update_post_preview(client, user_id, message.chat.id, force_resend=False)


@Client.on_message(
    filters.command(["editpostimage", "editimage", "editipostmage"]) & admin_filter,
    group=-4,
)
async def edit_image_cmd(client: Client, message: Message):
    user_id = message.from_user.id
    if user_id not in post_sessions:
        return await message.reply_text("❌ No active post session.")
    session = post_sessions[user_id]

    ask_msg = await message.reply_text(
        "📸 **Please send the new photo or a direct image URL for PREVIEW MODE.**\n*(Or type `/reset` to use the default poster, or `blank` to remove the image completely)*"
    )
    try:
        response = await native_listen(client, message.chat.id, user_id, 120)
        await ask_msg.delete()

        if response.photo:
            status_msg = await message.reply_text(
                "⏳ Uploading to secure image host for preview..."
            )
            url, err = await upload_image_safely(client, response)
            if url:
                session["custom_poster"] = url
                if not session.get("edit_target"):
                    session["photo_mode"] = False
                try:
                    await status_msg.edit_text(
                        "✅ Image successfully uploaded and set as rich preview!"
                    )
                except Exception:
                    pass
            else:
                try:
                    await status_msg.edit_text(err)
                except Exception:
                    pass
                return
        elif response.text:
            text_input = response.text.strip().lower()
            if text_input == "/reset":
                session["custom_poster"] = None
                if not session.get("edit_target"):
                    session["photo_mode"] = False
                await message.reply_text("✅ Image reset to default TMDB poster!")
            elif text_input == "blank":
                session["custom_poster"] = "BLANK"
                await message.reply_text("✅ Image completely removed from preview!")
            elif response.text.startswith("http"):
                session["custom_poster"] = response.text.strip()
                if not session.get("edit_target"):
                    session["photo_mode"] = False
                await message.reply_text("✅ Image updated from URL!")
            else:
                return await message.reply_text(
                    "⚠️ Invalid input. Must be a photo, a URL, `blank`, or `/reset`."
                )

        try:
            await response.delete()
        except Exception:
            pass
    except asyncio.TimeoutError:
        await ask_msg.edit_text("⌛ Timeout. Image edit cancelled.")
        return
    await update_post_preview(client, user_id, message.chat.id, force_resend=True)


@Client.on_message(
    filters.command(["editpostnormalimage", "editnormalimage"]) & admin_filter, group=-4
)
async def edit_normal_image_cmd(client: Client, message: Message):
    user_id = message.from_user.id
    if user_id not in post_sessions:
        return await message.reply_text("❌ No active post session.")
    session = post_sessions[user_id]

    ask_msg = await message.reply_text(
        "📸 **Please send the Normal Photo or a direct image URL now.**\n*(Or type `/reset` to use the default TMDB poster, or `blank` to remove the image completely)*"
    )
    try:
        response = await native_listen(client, message.chat.id, user_id, 120)
        await ask_msg.delete()

        if response.photo:
            if session.get("edit_target") and not session.get("photo_mode"):
                return await message.reply_text(
                    "❌ This imported post is in Preview Mode. You cannot use a raw Telegram file. Please send a URL or use `/editpostimage` instead."
                )
            session["custom_poster"] = response.photo.file_id
            if not session.get("edit_target"):
                session["photo_mode"] = True
            await message.reply_text("✅ Normal Image updated successfully!")
        elif response.text:
            text_input = response.text.strip().lower()
            if text_input == "/reset":
                session["custom_poster"] = None
                if not session.get("edit_target"):
                    session["photo_mode"] = True
                await message.reply_text(
                    "✅ Image reset to default TMDB poster (Normal Mode)!"
                )
            elif text_input == "blank":
                session["custom_poster"] = "BLANK"
                await message.reply_text("✅ Image completely removed!")
            elif response.text.startswith("http"):
                session["custom_poster"] = response.text.strip()
                if not session.get("edit_target"):
                    session["photo_mode"] = True
                await message.reply_text("✅ Normal Image updated from URL!")
            else:
                return await message.reply_text("⚠️ Invalid input.")

        try:
            await response.delete()
        except Exception:
            pass
    except asyncio.TimeoutError:
        await ask_msg.edit_text("⌛ Timeout. Image edit cancelled.")
        return
    await update_post_preview(client, user_id, message.chat.id, force_resend=True)


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
    movie_details = session.get("movie_details", {})

    # ⚡ EXCLUSIVE MANUAL MODE: Restores imported old post identically.
    if session.get("is_manual_caption") and session.get("caption"):
        text = session["caption"]
        poster_to_use = (
            None
            if session.get("custom_poster") == "BLANK"
            else session.get("custom_poster")
        )
        keyboard = build_keyboard(session, session_id)
        return text, keyboard, poster_to_use

    template_str = TEMPLATES.get(
        session.get("active_template"), TEMPLATES["clean_grid"]
    )

    clean_title = movie_details.get("title", "")
    clean_year = movie_details.get("year", "")
    rating_str = movie_details.get("rating", "N/A")
    plot_str = movie_details.get("plot", "N/A")

    c_langs = session.get("custom_languages", [])
    langs_str = (
        "" if c_langs == ["BLANK"] else (", ".join(c_langs) if c_langs else "N/A")
    )

    c_res = session.get("custom_resolutions", [])
    res_str = "" if c_res == ["BLANK"] else (", ".join(c_res) if c_res else "N/A")

    c_gen = session.get("custom_genres", [])
    genres_str = "" if c_gen == ["BLANK"] else (", ".join(c_gen) if c_gen else "N/A")

    c_ott = session.get("custom_otts", [])
    otts_str = "" if c_ott == ["BLANK"] else (", ".join(c_ott) if c_ott else "N/A")

    val_title = clean_title
    val_year = str(clean_year)
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

    text = template_str.replace("{title}", html.escape(val_title)).replace(
        "{year}", html.escape(val_year)
    )

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
        if val:
            text = text.replace(tag, val)
        else:
            text = re.sub(rf"[^\n]*{re.escape(tag)}[^\n]*\n?", "", text)

    text = (
        text.replace("{size}", "Available In Files.")
        .replace("{rating}", html.escape(str(rating_str)))
        .replace("{plot}", html.escape(str(plot_str)))
    )

    if session.get("watermark"):
        text += f"\n\n{session['watermark']}"

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
    keyboard = build_keyboard(session, session_id)

    return text, keyboard, poster_to_use


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
                    reply_to_message_id=session["original_message_id"],
                )
                session["last_preview_message_id"] = sent_msg.id
                if old_msg_id:
                    try:
                        await client.delete_messages(chat_id, old_msg_id)
                    except Exception:
                        pass
            else:
                try:
                    await client.edit_message_caption(
                        chat_id,
                        session["last_preview_message_id"],
                        caption=final_caption,
                        reply_markup=keyboard,
                    )
                except Exception:
                    await update_post_preview(
                        client, session_id, chat_id, force_resend=True
                    )
                    return
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
                    reply_to_message_id=session["original_message_id"],
                    disable_web_page_preview=False,
                )
                session["last_preview_message_id"] = sent_msg.id
                if old_msg_id:
                    try:
                        await client.delete_messages(chat_id, old_msg_id)
                    except Exception:
                        pass
            else:
                try:
                    await client.edit_message_text(
                        chat_id,
                        session["last_preview_message_id"],
                        text=text_content,
                        reply_markup=keyboard,
                        disable_web_page_preview=False,
                    )
                except Exception:
                    await update_post_preview(
                        client, session_id, chat_id, force_resend=True
                    )
                    return
    except Exception as e:
        try:
            await client.send_message(chat_id, f"❌ **PREVIEW SEND ERROR:**\n`{e}`")
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


# ⚡ DYNAMIC CHANNEL SELECTION
try:
    from plugins.auto_post import get_ap_settings
except ImportError:

    async def get_ap_settings():
        return {}


async def show_target_selection(query: CallbackQuery, session_id: int, page: int = 1):
    all_chats_dict = {}
    settings = await get_ap_settings()

    info_muc = (
        info.MOVIE_UPDATE_CHANNEL
        if isinstance(info.MOVIE_UPDATE_CHANNEL, list)
        else [info.MOVIE_UPDATE_CHANNEL]
    )
    db_muc = settings.get("muc_list", [])
    for ch in set([c for c in info_muc + db_muc if c]):
        all_chats_dict[int(ch)] = f"🌟 Default Update Channel"

    info_apc = (
        info.AUTOPOSTCHANNEL
        if isinstance(info.AUTOPOSTCHANNEL, list)
        else [info.AUTOPOSTCHANNEL]
    )
    db_apc = settings.get("apc_list", [])
    for ch in set([c for c in info_apc + db_apc if c]):
        if int(ch) not in all_chats_dict:
            all_chats_dict[int(ch)] = f"🌟 Auto-Post Channel"

    raw_chats = await _db.get_all_chats()
    db_chats = (
        [c async for c in raw_chats]
        if hasattr(raw_chats, "__aiter__")
        else list(raw_chats)
    )
    for chat in db_chats:
        chat_id = chat.get("id") or chat.get("chat_id")
        if chat_id:
            title = chat.get("title") or chat.get("name") or str(chat_id)
            if int(chat_id) not in all_chats_dict:
                all_chats_dict[int(chat_id)] = f"📢 {title[:25]}"

    chat_list = list(all_chats_dict.items())
    page_size = 10
    total_pages = max(1, math.ceil(len(chat_list) / page_size))
    page = max(1, min(page, total_pages))

    start_idx = (page - 1) * page_size
    end_idx = start_idx + page_size
    current_chats = chat_list[start_idx:end_idx]

    buttons = []
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
                if "BLANK" in session["custom_languages"]:
                    session["custom_languages"] = []
                if item not in session["custom_languages"]:
                    session["custom_languages"].append(item)
                else:
                    session["custom_languages"].remove(item)
                await show_selection_menu(query, session_id, "languages")
            elif action == "select_res":
                if "BLANK" in session["custom_resolutions"]:
                    session["custom_resolutions"] = []
                if item not in session["custom_resolutions"]:
                    session["custom_resolutions"].append(item)
                else:
                    session["custom_resolutions"].remove(item)
                await show_selection_menu(query, session_id, "resolutions")
            elif action == "select_gen":
                if "BLANK" in session["custom_genres"]:
                    session["custom_genres"] = []
                if item not in session["custom_genres"]:
                    session["custom_genres"].append(item)
                else:
                    session["custom_genres"].remove(item)
                await show_selection_menu(query, session_id, "genres")
            elif action == "select_ott":
                if "BLANK" in session["custom_otts"]:
                    session["custom_otts"] = []
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
            elif action == "toggle_poster":
                session["use_landscape"] = not session["use_landscape"]
                force_resend = True
            elif action == "toggle_mode":
                if not session.get("edit_target"):
                    session["photo_mode"] = not session.get("photo_mode")
                    force_resend = True
                else:
                    await query.answer(
                        "You cannot switch image modes on an imported channel post!",
                        show_alert=True,
                    )
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
            elif action == "cancel":
                return await handle_cancel(client, query, session_id)

            elif action == "finalize":
                if session.get("edit_target"):
                    return await execute_post(
                        client, query, session_id, session["edit_target"]["chat_id"]
                    )
                else:
                    return await show_target_selection(query, session_id, 1)
            elif action == "target_page":
                return await show_target_selection(
                    query, session_id, int(extra_data[0])
                )
            elif action == "send_to":
                return await execute_post(client, query, session_id, int(extra_data[0]))
            elif action == "back_editor":
                await update_post_preview(
                    client, session_id, query.message.chat.id, force_resend=False
                )
                return

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


async def get_user_input(client, query, session, prompt_text):
    try:
        ask_msg = await query.message.reply_text(
            prompt_text, reply_to_message_id=session.get("original_message_id")
        )
    except Exception:
        ask_msg = await query.message.reply_text(prompt_text)
    try:
        response = await native_listen(
            client,
            chat_id=query.message.chat.id,
            user_id=query.from_user.id,
            timeout=300,
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
                    row_btns.append(create_btn(clean_text, url=clean_url))
            if row_btns:
                new_layout.append(row_btns)
        session["buttons"] = new_layout
    await update_post_preview(
        client, session_id, query.message.chat.id, force_resend=False
    )


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
        safe_query = re.sub(r"_+", "_", safe_query).strip("_")[:50]

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
                    icon_custom_emoji_id=5258096772776991776,
                    style=BTN_PRIMARY,
                ),
                create_btn(
                    text="Group 2 🎬",
                    url="https://t.me/+GLsPkRgLGGszMzY1",
                    icon_custom_emoji_id=5258096772776991776,
                    style=BTN_PRIMARY,
                ),
            ]
        )
        session["buttons"].append(
            [
                create_btn(
                    text="Direct Search 🔎",
                    url=url,
                    icon_custom_emoji_id=5258503720928288433,
                    style=BTN_SUCCESS,
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
        "📸 Send a photo or an image URL.\n*(Or type `/reset` to use the default poster, or `blank` to remove the image)*",
    )
    if response:
        if response.photo:
            status_msg = await query.message.reply_text(
                "⏳ Uploading image for preview..."
            )
            url, err = await upload_image_safely(client, response)
            if url:
                session["custom_poster"] = url
                if not session.get("edit_target"):
                    session["photo_mode"] = False
                try:
                    await status_msg.edit_text("✅ Image set as rich preview!")
                except Exception:
                    pass
            else:
                try:
                    await status_msg.edit_text(err)
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
    return True


async def handle_set_watermark(client, query, session_id: int):
    session = post_sessions[session_id]
    prompt_text = "Send the watermark text. HTML is supported.\n\n• Send `blank` or `/reset` to remove the watermark.\n• Send `/default` to use the default watermark."
    response = await get_user_input(client, query, session, prompt_text)
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
                    "⚠ Invalid format! The format must contain `{resolutions}` placeholder.",
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
                create_btn(
                    text,
                    callback_data=f"post:select_template:{query.from_user.id}:{name}",
                )
            ]
        )
    buttons.append(
        [create_btn("Back", callback_data=f"post:back:{query.from_user.id}")]
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
                    create_btn(
                        f"❌ {btn.text}",
                        callback_data=f"post:remove_button:{query.from_user.id}:{i}:{j}",
                    )
                ]
            )
    if not buttons:
        buttons.append([create_btn("No buttons to remove", callback_data="noop")])
    buttons.append(
        [create_btn("Back", callback_data=f"post:back:{query.from_user.id}")]
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

    is_normal_photo = (
        session.get("photo_mode")
        and poster_to_use
        and str(poster_to_use).upper() != "BLANK"
    )

    try:
        edit_target = session.get("edit_target")
        if edit_target:
            if is_normal_photo:
                await client.edit_message_media(
                    chat_id=edit_target["chat_id"],
                    message_id=edit_target["message_id"],
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
                    chat_id=edit_target["chat_id"],
                    message_id=edit_target["message_id"],
                    text=text_content,
                    reply_markup=final_keyboard,
                    disable_web_page_preview=False,
                )
            if status_msg:
                try:
                    await status_msg.edit(
                        "✅ Original post has been updated successfully!"
                    )
                except Exception:
                    pass
        else:
            if is_normal_photo:
                await client.send_photo(
                    chat_id=target_chat_id,
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
                await client.send_message(
                    chat_id=target_chat_id,
                    text=text_content,
                    reply_markup=final_keyboard,
                    disable_web_page_preview=False,
                )

            if status_msg:
                try:
                    await status_msg.edit(
                        "✅ Post has been sent to the selected channel successfully!"
                    )
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
