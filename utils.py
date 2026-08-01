import asyncio
import logging
import os
import re
from datetime import datetime
from typing import List, Union

import requests
from bs4 import BeautifulSoup
from imdb import IMDb
from pyrogram import enums
from pyrogram.errors import (
    FloodWait,
    InputUserDeactivated,
    PeerIdInvalid,
    UserIsBlocked,
    UserNotParticipant,
)
from pyrogram.types import InlineKeyboardButton, Message

from database.join_reqs import join_reqs as db2
from database.users_chats_db import db
from info import ADMINS, AUTH_CHANNEL, LONG_IMDB_DESCRIPTION, MAX_LIST_ELM, REQ_CHANNEL

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

BTN_URL_REGEX = re.compile(
    r"(\[([^\[]+?)\]\((buttonurl|buttonalert):(?:/{0,2})(.+?)(:same)?\))"
)
imdb = IMDb()

SMART_OPEN = "“"
SMART_CLOSE = "”"
START_CHAR = ("'", '"', SMART_OPEN)


class temp(object):
    BANNED_USERS = []
    BANNED_CHATS = []
    ME = None
    CURRENT = int(os.environ.get("SKIP", 2))
    CANCEL = False
    MELCOW = {}
    U_NAME = None
    B_NAME = None
    SETTINGS = {}


def parse_ultra_advanced_query(text):
    text = text.lower().strip()
    text = re.sub(r"[._\-]", " ", text)
    season, episode = None, None
    se_pattern = r"(?:s|season)\s*(\d+)\s*(?:e|ep|episode)\s*(\d+)"
    se_matches = re.search(se_pattern, text)

    if se_matches:
        season, episode = int(se_matches.group(1)), int(se_matches.group(2))
        text = re.sub(se_pattern, "", text)
    else:
        s_match = re.search(r"(?:s|season)\s*(\d+)", text)
        if s_match:
            season = int(s_match.group(1))
            text = re.sub(r"(?:s|season)\s*(\d+)", "", text)
        e_match = re.search(r"(?:e|ep|episode)\s*(\d+)", text)
        if e_match:
            episode = int(e_match.group(1))
            text = re.sub(r"(?:e|ep|episode)\s*(\d+)", "", text)

    qualities = re.findall(
        r"\b(480p|720p|1080p|1440p|2160p|4k|mkv|mp4|hdrip|web\s*dl|bluray)\b", text
    )
    years = re.findall(r"\b(19\d{2}|20\d{2})\b", text)
    languages = re.findall(
        r"\b(hindi|tamil|telugu|malayalam|kannada|english|dual|multi)\b", text
    )

    stopwords = [
        "movie",
        "full",
        "watch",
        "online",
        "download",
        "print",
        "hq",
        "dubbed",
        "subtitles",
        "subs",
        "part",
        "audio",
        "video",
        "kr_picture",
        "sandalwood",
        "exclusive",
        "official",
        "team",
        "kannada_filmy_group",
        "telegram",
        "join",
        "link",
    ]
    to_remove = stopwords + qualities + years + languages
    for word in to_remove:
        text = re.sub(rf"\b{word}\b", "", text)
    title_words = [w for w in text.split() if w]

    return {
        "title_words": title_words,
        "season": season,
        "episode": episode,
        "qualities": list(set(qualities)),
        "years": list(set(years)),
        "languages": list(set(languages)),
    }


async def is_subscribed(bot, query):
    user_id = query.from_user.id
    if user_id in ADMINS:
        return True
    if not AUTH_CHANNEL and not REQ_CHANNEL:
        return True
    if db2.isActive() and await db2.get_user(user_id):
        return True
    if not AUTH_CHANNEL:
        return True
    try:
        user = await bot.get_chat_member(AUTH_CHANNEL, user_id)
        return user.status not in [
            enums.ChatMemberStatus.BANNED,
            enums.ChatMemberStatus.LEFT,
        ]
    except UserNotParticipant:
        return False
    except Exception as e:
        logger.exception(f"Subscription Error: {e}")
        return False


def _fetch_imdb_data(query, bulk=False, id=False, file=None):
    try:
        if not id:
            query = query.strip().lower()
            year_match = re.findall(r"\b(19\d{2}|20\d{2})\b", query, re.IGNORECASE)
            year = year_match[0] if year_match else None
            title = query.replace(year, "").strip() if year else query

            movieid = imdb.search_movie(title, results=10)
            if not movieid:
                return None

            filtered = (
                [k for k in movieid if str(k.get("year")) == str(year)]
                if year
                else movieid
            )
            if not filtered:
                filtered = movieid

            movieid_filtered = [
                k for k in filtered if k.get("kind") in ["movie", "tv series"]
            ]
            if not movieid_filtered:
                movieid_filtered = filtered

            if bulk:
                return movieid_filtered
            movieid = movieid_filtered[0].movieID
        else:
            movieid = query

        movie = imdb.get_movie(movieid)
        date = movie.get("original air date") or movie.get("year") or "N/A"
        plot = (
            movie.get("plot outline")
            if LONG_IMDB_DESCRIPTION
            else (movie.get("plot")[0] if movie.get("plot") else "")
        )
        if plot and len(plot) > 800:
            plot = plot[0:800] + "..."

        return {
            "title": movie.get("title"),
            "votes": movie.get("votes"),
            "aka": list_to_str(movie.get("akas")),
            "seasons": movie.get("number of seasons"),
            "box_office": movie.get("box office"),
            "localized_title": movie.get("localized title"),
            "kind": movie.get("kind"),
            "imdb_id": f"tt{movie.get('imdbID')}",
            "cast": list_to_str(movie.get("cast")),
            "runtime": list_to_str(movie.get("runtimes")),
            "countries": list_to_str(movie.get("countries")),
            "certificates": list_to_str(movie.get("certificates")),
            "languages": list_to_str(movie.get("languages")),
            "director": list_to_str(movie.get("director")),
            "writer": list_to_str(movie.get("writer")),
            "producer": list_to_str(movie.get("producer")),
            "composer": list_to_str(movie.get("composer")),
            "cinematographer": list_to_str(movie.get("cinematographer")),
            "music_team": list_to_str(movie.get("music department")),
            "distributors": list_to_str(movie.get("distributors")),
            "release_date": date,
            "year": movie.get("year"),
            "genres": list_to_str(movie.get("genres")),
            "poster": movie.get("full-size cover url"),
            "plot": plot,
            "rating": str(movie.get("rating", "N/A")),
            "url": f"https://www.imdb.com/title/tt{movieid}",
        }
    except Exception as e:
        logger.error(f"IMDb Error: {e}")
        return None


async def get_poster(query, bulk=False, id=False, file=None):
    return await asyncio.to_thread(_fetch_imdb_data, query, bulk, id, file)


async def broadcast_messages(user_id, message):
    try:
        await message.copy(chat_id=user_id)
        return True, "Success"
    except FloodWait as e:
        await asyncio.sleep(e.value)
        return await broadcast_messages(user_id, message)
    except InputUserDeactivated:
        await db.delete_user(int(user_id))
        return False, "Deleted"
    except UserIsBlocked:
        return False, "Blocked"
    except PeerIdInvalid:
        await db.delete_user(int(user_id))
        return False, "Error"
    except Exception:
        return False, "Error"


def _fetch_gagala(text):
    usr_agent = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/61.0.3163.100 Safari/537.36"
    }
    try:
        response = requests.get(
            f"https://www.google.com/search?q={text.replace(' ', '+')}",
            headers=usr_agent,
            timeout=5,
        )
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        return [title.getText() for title in soup.find_all("h3") if title.getText()]
    except Exception as e:
        logger.error(f"Google Scrape Error: {e}")
        return []


async def search_gagala(text):
    return await asyncio.to_thread(_fetch_gagala, text)


async def get_settings(group_id):
    settings = temp.SETTINGS.get(group_id)
    if not settings:
        settings = await db.get_settings(group_id)
        temp.SETTINGS[group_id] = settings
    return settings


async def save_group_settings(group_id, key, value):
    current = await get_settings(group_id)
    current[key] = value
    temp.SETTINGS[group_id] = current
    await db.update_settings(group_id, current)


def get_size(size):
    units = ["Bytes", "KB", "MB", "GB", "TB", "PB", "EB"]
    size = float(size)
    i = 0
    while size >= 1024.0 and i < len(units) - 1:
        i += 1
        size /= 1024.0
    return "%.2f %s" % (size, units[i])


def split_list(l, n):
    for i in range(0, len(l), n):
        yield l[i : i + n]


def get_file_id(msg: Message):
    if not msg.media:
        return None
    media_type = getattr(msg.media, "value", str(msg.media))
    obj = getattr(msg, media_type, None)
    return obj


def extract_user(message: Message) -> Union[int, str]:
    if message.reply_to_message:
        return (
            message.reply_to_message.from_user.id,
            message.reply_to_message.from_user.first_name,
        )
    elif len(message.command) > 1:
        if (
            len(message.entities) > 1
            and message.entities[1].type == enums.MessageEntityType.TEXT_MENTION
        ):
            return (message.entities[1].user.id, message.entities[1].user.first_name)
        try:
            return (int(message.command[1]), str(message.command[1]))
        except ValueError:
            return (message.command[1], str(message.command[1]))
    return (message.from_user.id, message.from_user.first_name)


def list_to_str(k):
    if not k:
        return "N/A"
    if isinstance(k, str):
        return k
    if MAX_LIST_ELM:
        k = k[: int(MAX_LIST_ELM)]
    return ", ".join(str(elem) for elem in k)


def last_online(from_user):
    time_str = ""
    if from_user.is_bot:
        time_str += "🤖 Bot :("
    elif from_user.status == enums.UserStatus.RECENTLY:
        time_str += "Recently"
    elif from_user.status == enums.UserStatus.LAST_WEEK:
        time_str += "Within the last week"
    elif from_user.status == enums.UserStatus.LAST_MONTH:
        time_str += "Within the last month"
    elif from_user.status == enums.UserStatus.LONG_AGO:
        time_str += "A long time ago :("
    elif from_user.status == enums.UserStatus.ONLINE:
        time_str += "Currently Online"
    elif from_user.status == enums.UserStatus.OFFLINE:
        if hasattr(from_user, "last_online_date") and from_user.last_online_date:
            time_str += from_user.last_online_date.strftime("%a, %d %b %Y, %H:%M:%S")
        else:
            time_str += "Offline"
    return time_str


def parser(text, keyword):
    if "buttonalert" in text:
        text = text.replace("\n", "\\n").replace("\t", "\\t")
    buttons, alerts, note_data = [], [], ""
    prev = 0
    try:
        for i, match in enumerate(BTN_URL_REGEX.finditer(text)):
            n_escapes, to_check = 0, match.start(1) - 1
            while to_check > 0 and text[to_check] == "\\":
                n_escapes += 1
                to_check -= 1

            if n_escapes % 2 == 0:
                note_data += text[prev : match.start(1)]
                prev = match.end(1)
                btn = (
                    InlineKeyboardButton(
                        text=match.group(2), callback_data=f"alertmessage:{i}:{keyword}"
                    )
                    if match.group(3) == "buttonalert"
                    else InlineKeyboardButton(
                        text=match.group(2), url=match.group(4).replace(" ", "")
                    )
                )

                if bool(match.group(5)) and buttons:
                    buttons[-1].append(btn)
                else:
                    buttons.append([btn])

                if match.group(3) == "buttonalert":
                    alerts.append(match.group(4))
            else:
                note_data += text[prev:to_check]
                prev = match.start(1) - 1
        note_data += text[prev:]
        return note_data, buttons, alerts if alerts else None
    except Exception as e:
        logger.error(f"Parser Error: {e}")
        return note_data, buttons, None


def remove_escapes(text: str) -> str:
    res, is_escaped = "", False
    for char in text:
        if is_escaped:
            res += char
            is_escaped = False
        elif char == "\\":
            is_escaped = True
        else:
            res += char
    return res


def humanbytes(size):
    if not size:
        return ""
    power, n = 2**10, 0
    dic = {0: " ", 1: "Ki", 2: "Mi", 3: "Gi", 4: "Ti"}
    while size > power and n < 4:
        size /= power
        n += 1
    return str(round(size, 2)) + " " + dic[n] + "B"


def get_readable_time(seconds):
    periods, result = [("d", 86400), ("h", 3600), ("m", 60), ("s", 1)], []
    for p_name, p_seconds in periods:
        if seconds >= p_seconds:
            p_val, seconds = divmod(seconds, p_seconds)
            result.append(f"{int(p_val)}{p_name}")
    return " ".join(result)
