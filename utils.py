import asyncio
import os
import re
import urllib.parse
from datetime import datetime
from logging import INFO, getLogger
from typing import List, Union

import aiohttp
import requests
from bs4 import BeautifulSoup
from pyrogram import Client, enums, filters
from pyrogram.errors import (
    FloodWait,
    InputUserDeactivated,
    PeerIdInvalid,
    UserIsBlocked,
    UserNotParticipant,
)
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

import info
from database.join_reqs import join_reqs as _db2
from database.users_chats_db import db as _db
from info import (
    ADMINS,
    AUTH_CHANNEL,
    LONG_IMDB_DESCRIPTION,
    MAX_LIST_ELM,
    REQ_CHANNEL,
    TMDB_API_KEY,
)

logger = getLogger(__name__)
logger.setLevel(INFO)

BTN_URL_REGEX = re.compile(
    r"(\[([^\[]+?)\]\((buttonurl|buttonalert):(?:/{0,2})(.+?)(:same)?\))"
)
SMART_OPEN, SMART_CLOSE, START_CHAR = "“", "”", ("'", '"', "“")

# ⚡ EXACT TELEGRAM SUPPORTED COLORS
try:
    from pyrogram.enums import ButtonStyle

    BTN_PRIMARY, BTN_SUCCESS, BTN_DANGER = (
        getattr(ButtonStyle, "PRIMARY", 1),
        getattr(ButtonStyle, "SUCCESS", 3),
        getattr(ButtonStyle, "DANGER", 4),
    )
except ImportError:
    BTN_PRIMARY, BTN_SUCCESS, BTN_DANGER = 1, 3, 4


class temp(object):
    (
        BANNED_USERS,
        BANNED_CHATS,
        ME,
        CURRENT,
        CANCEL,
        MELCOW,
        U_NAME,
        B_NAME,
        SETTINGS,
    ) = ([], [], None, int(os.environ.get("SKIP", 2)), False, {}, None, None, {})


class TMDBWrapper(dict):
    def __getattr__(self, name):
        return self.get(name)


# ============================================================
# 👑 FULL POWER ADMIN CHECKER (GLOBAL + CHAT + ANONYMOUS)
# ============================================================
def get_admin_list():
    raw_admins = getattr(info, "ADMINS", [])
    if isinstance(raw_admins, (str, int)):
        raw_admins = str(raw_admins).replace(",", " ").split()
    return [int(x) for x in raw_admins if str(x).strip().lstrip("-").isdigit()]


async def is_user_admin(client: Client, message: Message):
    admin_list = get_admin_list()

    # 1. Global Admin Check (Direct User)
    if message.from_user and message.from_user.id in admin_list:
        return True

    # 2. Global Admin Check (Anonymous/Channel sending as Chat)
    if message.sender_chat and message.sender_chat.id in admin_list:
        return True

    # 3. Group Admin Check (Normal & Anonymous Admins)
    if message.chat and message.chat.type in [
        enums.ChatType.GROUP,
        enums.ChatType.SUPERGROUP,
    ]:
        if message.sender_chat and message.sender_chat.id == message.chat.id:
            return True
        if message.from_user:
            try:
                member = await client.get_chat_member(
                    message.chat.id, message.from_user.id
                )
                return member.status in [
                    enums.ChatMemberStatus.ADMINISTRATOR,
                    enums.ChatMemberStatus.OWNER,
                ]
            except Exception:
                pass
    return False


async def cb_user_admin(client: Client, query: CallbackQuery):
    admin_list = get_admin_list()
    if query.from_user and query.from_user.id in admin_list:
        return True
    if query.message.chat and query.message.chat.type in [
        enums.ChatType.GROUP,
        enums.ChatType.SUPERGROUP,
    ]:
        if (
            query.message.sender_chat
            and query.message.sender_chat.id == query.message.chat.id
        ):
            return True
        try:
            member = await client.get_chat_member(
                query.message.chat.id, query.from_user.id
            )
            return member.status in [
                enums.ChatMemberStatus.ADMINISTRATOR,
                enums.ChatMemberStatus.OWNER,
            ]
        except Exception:
            pass
    return False


def _admin_check_sync(_, client: Client, message: Message):
    return asyncio.run(is_user_admin(client, message))


def _cb_admin_check_sync(_, client: Client, query: CallbackQuery):
    return asyncio.run(cb_user_admin(client, query))


admin_filter = filters.create(_admin_check_sync)
cb_admin_filter = filters.create(_cb_admin_check_sync)


# ============================================================
# 🛠️ UNIVERSAL UTILITIES
# ============================================================
def parse_ultra_advanced_query(text):
    text = re.sub(r"[._\-]", " ", text.lower().strip())
    season, episode = None, None
    se_pattern = r"(?:s|season)\s*(\d+)\s*(?:e|ep|episode)\s*(\d+)"
    if se_matches := re.search(se_pattern, text):
        season, episode = int(se_matches.group(1)), int(se_matches.group(2))
        text = re.sub(se_pattern, "", text)
    else:
        if s_match := re.search(r"(?:s|season)\s*(\d+)", text):
            season = int(s_match.group(1))
            text = re.sub(r"(?:s|season)\s*(\d+)", "", text)
        if e_match := re.search(r"(?:e|ep|episode)\s*(\d+)", text):
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

    for word in stopwords + qualities + years + languages:
        text = re.sub(rf"\b{word}\b", "", text)
    return {
        "title_words": [w for w in text.split() if w],
        "season": season,
        "episode": episode,
        "qualities": list(set(qualities)),
        "years": list(set(years)),
        "languages": list(set(languages)),
    }


async def is_subscribed(bot, query):
    if await cb_user_admin(bot, query):
        return True
    if not AUTH_CHANNEL and not REQ_CHANNEL:
        return True
    if _db2.isActive() and await _db2.get_user(query.from_user.id):
        return True
    if not AUTH_CHANNEL:
        return True
    try:
        user = await bot.get_chat_member(AUTH_CHANNEL, query.from_user.id)
        return user.status not in [
            enums.ChatMemberStatus.BANNED,
            enums.ChatMemberStatus.LEFT,
        ]
    except UserNotParticipant:
        return False
    except Exception as e:
        logger.exception(f"Subscription Error: {e}")
        return False


async def get_poster(query, bulk=False, id=False, file=None):
    if not TMDB_API_KEY:
        return None
    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=10)
    ) as session:
        try:
            if id:
                query_str, media_type = str(query), "movie"
                if query_str.startswith("tt"):
                    async with session.get(
                        f"https://api.themoviedb.org/3/find/{query_str}?api_key={TMDB_API_KEY}&external_source=imdb_id"
                    ) as resp:
                        if resp.status != 200:
                            return None
                        results = (await resp.json()).get("movie_results", []) + (
                            await resp.json()
                        ).get("tv_results", [])
                        if not results:
                            return None
                        query_str, media_type = str(results[0]["id"]), (
                            "tv" if "name" in results[0] else "movie"
                        )

                async with session.get(
                    f"https://api.themoviedb.org/3/{media_type}/{query_str}?api_key={TMDB_API_KEY}&append_to_response=credits"
                ) as resp:
                    if resp.status != 200:
                        return None
                    movie = await resp.json()
                    title = movie.get("title") or movie.get("name")
                    year = (
                        movie.get("release_date") or movie.get("first_air_date") or ""
                    )[:4]
                    poster_path = movie.get("poster_path")
                    crew, cast_data = movie.get("credits", {}).get(
                        "crew", []
                    ), movie.get("credits", {}).get("cast", [])
                    plot = movie.get("overview", "N/A")
                    if not LONG_IMDB_DESCRIPTION and len(plot) > 800:
                        plot = plot[:800] + "..."

                    return {
                        "title": title,
                        "votes": movie.get("vote_count", 0),
                        "aka": movie.get("original_title")
                        or movie.get("original_name", "N/A"),
                        "seasons": movie.get("number_of_seasons", "N/A"),
                        "box_office": (
                            f"${movie.get('revenue', 0):,}"
                            if movie.get("revenue")
                            else "N/A"
                        ),
                        "localized_title": title,
                        "kind": media_type,
                        "imdb_id": movie.get("imdb_id", query_str),
                        "cast": ", ".join([c["name"] for c in cast_data[:10]]) or "N/A",
                        "runtime": (
                            f"{movie.get('runtime', 'N/A')} min"
                            if movie.get("runtime")
                            else "N/A"
                        ),
                        "countries": ", ".join(
                            [c["name"] for c in movie.get("production_countries", [])]
                        )
                        or "N/A",
                        "certificates": "N/A",
                        "languages": ", ".join(
                            [
                                l.get("english_name", "")
                                for l in movie.get("spoken_languages", [])
                            ]
                        )
                        or "N/A",
                        "director": ", ".join(
                            [c["name"] for c in crew if c.get("job") == "Director"]
                        )
                        or "N/A",
                        "writer": ", ".join(
                            [
                                c["name"]
                                for c in crew
                                if c.get("department") == "Writing"
                            ]
                        )
                        or "N/A",
                        "producer": "N/A",
                        "composer": "N/A",
                        "cinematographer": "N/A",
                        "music_team": "N/A",
                        "distributors": ", ".join(
                            [c["name"] for c in movie.get("production_companies", [])]
                        )
                        or "N/A",
                        "release_date": movie.get("release_date")
                        or movie.get("first_air_date")
                        or "N/A",
                        "year": year or "N/A",
                        "genres": ", ".join(
                            [g["name"] for g in movie.get("genres", [])]
                        )
                        or "N/A",
                        "poster": (
                            f"https://image.tmdb.org/t/p/w500{poster_path}"
                            if poster_path
                            else None
                        ),
                        "plot": plot,
                        "rating": str(round(movie.get("vote_average", 0), 1)),
                        "url": f"https://www.themoviedb.org/{media_type}/{query_str}",
                    }
            else:
                clean_query, year = str(query).strip(), None
                if year_match := re.search(r"\b(19\d{2}|20\d{2})\b", clean_query):
                    year, clean_query = (
                        year_match.group(1),
                        clean_query.replace(year_match.group(1), "").strip(),
                    )
                clean_query = re.sub(
                    r"(?i)\b(hdrip|web-dl|webrip|bluray|brrip|dvdrip|dvdscr|tsrip|camrip|hdtc|hevc|x264|x265|1080p|720p|480p|2160p|4k|hindi|kannada|telugu|tamil|malayalam|english|movie|series)\b",
                    "",
                    clean_query,
                )
                clean_query = re.sub(
                    r"[\(\)\[\]\{\}\-_.:]", " ", clean_query
                ).strip() or str(query)

                url = f"https://api.themoviedb.org/3/search/multi?api_key={TMDB_API_KEY}&query={urllib.parse.quote(clean_query)}&include_adult=true"
                if year:
                    url += f"&year={year}"

                async with session.get(url) as resp:
                    if resp.status != 200:
                        return None
                    results = (await resp.json()).get("results", [])
                    movies = [
                        TMDBWrapper(
                            {
                                "movieID": str(item.get("id")),
                                "title": item.get("title") or item.get("name"),
                                "year": (
                                    item.get("release_date")
                                    or item.get("first_air_date")
                                    or ""
                                )[:4],
                                "kind": item.get("media_type"),
                            }
                        )
                        for item in results
                        if item.get("media_type") in ["movie", "tv"]
                    ]
                    if bulk:
                        return movies[: int(MAX_LIST_ELM)] if MAX_LIST_ELM else movies
                    return (
                        await get_poster(movies[0]["movieID"], id=True)
                        if movies
                        else None
                    )
        except Exception as e:
            logger.error(f"TMDB Fetch Error: {e}")
            return None


async def broadcast_messages(user_id, message):
    try:
        await message.copy(chat_id=user_id)
        return True, "Success"
    except FloodWait as e:
        await asyncio.sleep(e.value)
        return await broadcast_messages(user_id, message)
    except InputUserDeactivated:
        await _db.delete_user(int(user_id))
        return False, "Deleted"
    except UserIsBlocked:
        return False, "Blocked"
    except PeerIdInvalid:
        await _db.delete_user(int(user_id))
        return False, "Error"
    except Exception:
        return False, "Error"


def _fetch_gagala(text):
    try:
        response = requests.get(
            f"https://www.google.com/search?q={text.replace(' ', '+')}",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=5,
        )
        response.raise_for_status()
        return [
            title.getText()
            for title in BeautifulSoup(response.text, "html.parser").find_all("h3")
            if title.getText()
        ]
    except Exception as e:
        logger.error(f"Google Scrape Error: {e}")
        return []


async def search_gagala(text):
    return await asyncio.to_thread(_fetch_gagala, text)


async def get_settings(group_id):
    if not (settings := temp.SETTINGS.get(group_id)):
        settings = await _db.get_settings(group_id)
        temp.SETTINGS[group_id] = settings
    return settings


async def save_group_settings(group_id, key, value):
    current = await get_settings(group_id)
    current[key] = value
    temp.SETTINGS[group_id] = current
    await _db.update_settings(group_id, current)


def get_size(size):
    units, size, i = ["Bytes", "KB", "MB", "GB", "TB", "PB", "EB"], float(size), 0
    while size >= 1024.0 and i < len(units) - 1:
        size /= 1024.0
        i += 1
    return "%.2f %s" % (size, units[i])


def split_list(l, n):
    for i in range(0, len(l), n):
        yield l[i : i + n]


def get_file_id(msg: Message):
    if (
        not msg
        or not msg.media
        or getattr(msg.media, "value", str(msg.media)) == "caption"
    ):
        return None, None, None
    obj = getattr(msg, getattr(msg.media, "value", str(msg.media)), None)
    return (
        getattr(obj, "file_id", None),
        getattr(obj, "file_ref", None),
        getattr(msg.media, "value", str(msg.media)) if obj else (None, None, None),
    )


async def extract_user(message: Message, text: str = None):
    client = message._client
    if message.reply_to_message and message.reply_to_message.from_user:
        return message.reply_to_message.from_user
    elif text:
        try:
            return await client.get_users(text)
        except Exception:
            pass
    elif len(message.command) > 1:
        try:
            return await client.get_users(message.command[1])
        except Exception:
            pass
    return message.from_user


def list_to_str(k):
    return (
        "N/A"
        if not k
        else (
            k
            if isinstance(k, str)
            else ", ".join(
                str(elem) for elem in (k[: int(MAX_LIST_ELM)] if MAX_LIST_ELM else k)
            )
        )
    )


def last_online(from_user):
    if from_user.is_bot:
        return "🤖 Bot :("
    if from_user.status == enums.UserStatus.RECENTLY:
        return "Recently"
    if from_user.status == enums.UserStatus.LAST_WEEK:
        return "Within the last week"
    if from_user.status == enums.UserStatus.LAST_MONTH:
        return "Within the last month"
    if from_user.status == enums.UserStatus.LONG_AGO:
        return "A long time ago :("
    if from_user.status == enums.UserStatus.ONLINE:
        return "Currently Online"
    if from_user.status == enums.UserStatus.OFFLINE:
        return (
            getattr(from_user, "last_online_date").strftime("%a, %d %b %Y, %H:%M:%S")
            if getattr(from_user, "last_online_date", None)
            else "Offline"
        )
    return ""


def parser(text, keyword):
    if "buttonalert" in text:
        text = text.replace("\n", "\\n").replace("\t", "\\t")
    buttons, alerts, note_data, prev = [], [], "", 0
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
        return note_data + text[prev:], buttons, alerts if alerts else None
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
    power, n, dic = 2**10, 0, {0: " ", 1: "Ki", 2: "Mi", 3: "Gi", 4: "Ti"}
    while size > power and n < 4:
        size /= power
        n += 1
    return str(round(size, 2)) + " " + dic[n] + "B"


def get_readable_time(seconds):
    result = []
    for p_name, p_seconds in [("d", 86400), ("h", 3600), ("m", 60), ("s", 1)]:
        if seconds >= p_seconds:
            p_val, seconds = divmod(seconds, p_seconds)
            result.append(f"{int(p_val)}{p_name}")
    return " ".join(result)


def parse_text_and_markup(raw_text, static_keyboard=None):
    if not raw_text:
        return "", static_keyboard
    button_pattern = re.compile(r"\[([^\[\]\|]+)\|([^\[\]\|]+)(?:\|([^\[\]\|]+))?\]")
    parsed_lines, dynamic_keyboard = [], []

    for line in raw_text.split("\n"):
        if matches := button_pattern.findall(line):
            row = []
            for match in matches:
                kwargs = {"text": match[0].strip(), "url": match[1].strip()}
                if btn_style := {
                    "blue": BTN_PRIMARY,
                    "green": BTN_SUCCESS,
                    "red": BTN_DANGER,
                }.get((match[2].strip().lower() if match[2] else "normal"), None):
                    kwargs["style"] = btn_style
                try:
                    row.append(InlineKeyboardButton(**kwargs))
                except TypeError:
                    kwargs.pop("style", None)
                    row.append(InlineKeyboardButton(**kwargs))
            if row:
                dynamic_keyboard.append(row)
            if clean_line := button_pattern.sub("", line).strip():
                parsed_lines.append(clean_line)
        else:
            parsed_lines.append(line)

    if static_keyboard and hasattr(static_keyboard, "inline_keyboard"):
        dynamic_keyboard.extend(static_keyboard.inline_keyboard)
    return "\n".join(parsed_lines), (
        InlineKeyboardMarkup(dynamic_keyboard) if dynamic_keyboard else None
    )
