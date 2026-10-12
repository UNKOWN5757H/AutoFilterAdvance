import asyncio
import re
import warnings
from io import BytesIO
from logging import ERROR, getLogger

import aiohttp
import requests
from PIL import Image
from pyrogram import Client, enums, filters
from pyrogram.errors import MediaEmpty, PhotoInvalidDimensions, WebpageMediaEmpty
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

import info
from info import IMAGE_FETCH, TMDB_API_KEY

logger = getLogger(__name__)
logger.setLevel(ERROR)

DEFAULT_IMDB_TEMPLATE = """🎬 **Title:** <a href="{url}">{title}</a> ({year})
⭐️ **Rating:** {rating} / 10
🎭 **Genres:** {genres}
🗣 **Languages:** {languages}
⏰ **Runtime:** {runtime}
📜 **Plot:** {plot}"""

IMDB_TEMPLATE = (
    getattr(info, "IMDB_TEMPLATE", DEFAULT_IMDB_TEMPLATE) or DEFAULT_IMDB_TEMPLATE
)


class SafeDict(dict):
    def __missing__(self, key):
        return "{" + key + "}"


Image.MAX_IMAGE_PIXELS = None
warnings.simplefilter("ignore", Image.DecompressionBombWarning)

# --- TMDB Configuration ---
TMDB_BEARER_TOKEN = (
    "eyJhbGciOiJIUzI1NiJ9.eyJhdWQiOiI2ZGU3YTIyZGU1YjE5YTFjNmUyZGU5ZWEyMzE2ZmQxMCIs"
    "Im5iZiI6MTc0NTMyMjQ2Mi41MzMsInN1YiI6IjY4MDc4MWRlYzVjODAzNWZiMDhhNjExNCIsInNjb3"
    "BlcyI6WyJhcGlfcmVhZCJdLCJ2ZXJzaW9uIjoxfQ.rMMJ2-PBIv8Y7ybxPIEpIlzTEXzuwrm9ruKxAUCAsbw"
)
TMDB_BASE_URL = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE_URL = "https://image.tmdb.org/t/p/original"

_session: aiohttp.ClientSession | None = None


async def get_session():
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15))
    return _session


async def fetch_image(url, size=(860, 1200)):
    if not IMAGE_FETCH or not url:
        return url
    try:
        session = await get_session()
        async with session.get(url) as response:
            if response.status != 200:
                return None
            data = await response.read()
            img = Image.open(BytesIO(data))
            img = img.resize(size, Image.LANCZOS)
            out = BytesIO()
            img.save(out, format="JPEG")
            out.seek(0)
            return out
    except Exception as e:
        logger.error(f"Error in fetch_image: {e}")
    return None


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

    # 1. Global Admin Check
    if message.from_user and message.from_user.id in admin_list:
        return True

    # 2. Anonymous/Channel Admin Check
    if message.sender_chat and message.sender_chat.id in admin_list:
        return True

    # 3. Group Admin Check
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


admin_filter = filters.create(lambda _, c, m: asyncio.run(is_user_admin(c, m)))
cb_admin_filter = filters.create(lambda _, c, q: asyncio.run(cb_user_admin(c, q)))


# ============================================================
# ⚡ TMDB INTERNAL API CALLS
# ============================================================
def _list_to_str_tmdb(data_list, limit=10, key=None):
    if not data_list or not isinstance(data_list, list):
        return None
    items = data_list[:limit]
    if key:
        return ", ".join(
            str(item.get(key, "")) for item in items if item and item.get(key)
        )
    return ", ".join(str(item) for item in items if item)


def _sanitize_and_extract(query: str):
    q = str(query).strip()
    year_match = re.search(r"\b(19\d{2}|20\d{2})\b", q)
    year = int(year_match.group(1)) if year_match else None
    if year:
        q = q.replace(year_match.group(1), "")
    q = re.sub(
        r"(?i)\b(hdrip|web-dl|webrip|bluray|brrip|dvdrip|dvdscr|tsrip|camrip|hdtc|hevc|x264|x265|1080p|720p|480p|2160p|4k|hindi|kannada|telugu|tamil|malayalam|english|movie|series|season\s*\d+|ep\s*\d+)\b",
        "",
        q,
    )
    q = re.sub(r"[\(\)\[\]\{\}\-_.:]", " ", q)
    return re.sub(r"\s+", " ", q).strip() or str(query).strip(), year


async def _tmdb_get(path, params=None, api_key=None):
    url = f"{TMDB_BASE_URL}/{path.lstrip('/')}"
    _params = params.copy() if params else {}
    _headers = {}
    key_to_use = api_key or TMDB_API_KEY
    if key_to_use:
        _params["api_key"] = key_to_use
    elif TMDB_BEARER_TOKEN:
        _headers = {
            "Authorization": f"Bearer {TMDB_BEARER_TOKEN}",
            "Content-Type": "application/json;charset=utf-8",
        }

    session = await get_session()
    async with session.get(url, params=_params, headers=_headers, ssl=False) as resp:
        resp.raise_for_status()
        return await resp.json()


async def _fetch_media_details(media_type: str, media_id: int, api_key=None):
    params = {
        "append_to_response": "credits,external_ids,alternative_titles,release_dates,images"
    }
    return await _tmdb_get(f"{media_type}/{media_id}", params=params, api_key=api_key)


async def _search_media_id(query: str, api_key=None):
    clean_title, year = _sanitize_and_extract(query)
    queries_to_try = list(
        dict.fromkeys(
            [
                clean_title,
                (
                    " ".join(clean_title.split()[:2])
                    if len(clean_title.split()) > 2
                    else ""
                ),
                clean_title.split()[0] if len(clean_title.split()) > 1 else "",
            ]
        )
    )

    multi_results = []
    for target_query in [q for q in queries_to_try if q]:
        params = {
            "query": target_query,
            "language": "en-US",
            "page": 1,
            "include_adult": "false",
        }
        if year:
            params["year"] = year
        try:
            result = await _tmdb_get("search/multi", params=params, api_key=api_key)
            multi_results = result.get("results", [])
            if multi_results:
                break
        except Exception:
            continue

    if not multi_results and year:
        try:
            params = {
                "query": clean_title,
                "language": "en-US",
                "page": 1,
                "include_adult": "false",
            }
            multi_results = (
                await _tmdb_get("search/multi", params=params, api_key=api_key)
            ).get("results", [])
        except Exception:
            pass

    if not multi_results:
        return None, None

    valid_candidates = []
    for r in multi_results:
        mtype = r.get("media_type")
        if mtype not in ["movie", "tv"]:
            continue

        ratio = (
            __import__("difflib")
            .SequenceMatcher(
                None,
                str(r.get("title") or r.get("name") or "").lower(),
                clean_title.lower(),
            )
            .ratio()
        )
        rd_str = r.get("release_date") or r.get("first_air_date") or ""
        match_year = int(rd_str[:4]) if rd_str and len(rd_str) >= 4 else None

        year_score = 1.0
        if year and match_year:
            diff = abs(match_year - year)
            year_score = 1.2 if diff == 0 else 0.9 if diff == 1 else 0.5

        final_score = (ratio * 100) * year_score + (r.get("popularity", 0) / 10)
        valid_candidates.append((mtype, r["id"], final_score))

    if not valid_candidates:
        first = multi_results[0]
        return (
            (first["media_type"], first["id"])
            if first.get("media_type") in ["movie", "tv"]
            else (None, None)
        )

    valid_candidates.sort(key=lambda x: x[2], reverse=True)
    return valid_candidates[0][0], valid_candidates[0][1]


def _process_images(images_data):
    posters_by_lang, backdrops_by_lang = {}, {}
    for img in images_data.get("posters", []):
        posters_by_lang.setdefault(img.get("iso_639_1") or "no_lang", []).append(
            f"{TMDB_IMAGE_BASE_URL}{img['file_path']}"
        )
    for img in images_data.get("backdrops", []):
        backdrops_by_lang.setdefault(img.get("iso_639_1") or "no_lang", []).append(
            f"{TMDB_IMAGE_BASE_URL}{img['file_path']}"
        )

    posters_by_lang["all"] = [
        f"{TMDB_IMAGE_BASE_URL}{i['file_path']}" for i in images_data.get("posters", [])
    ]
    backdrops_by_lang["all"] = [
        f"{TMDB_IMAGE_BASE_URL}{i['file_path']}"
        for i in images_data.get("backdrops", [])
    ]
    return {
        "posters": posters_by_lang,
        "backdrops": backdrops_by_lang,
        "available_languages": sorted(set(posters_by_lang) | set(backdrops_by_lang)),
    }


async def _fetch_tmdb_data(query: str, api_key=None):
    media_type, media_id = await _search_media_id(query, api_key=api_key)
    if not media_id:
        return None

    details = await _fetch_media_details(media_type, media_id, api_key=api_key)
    crew = details.get("credits", {}).get("crew", [])

    certificates = None
    if media_type == "movie" and "release_dates" in details:
        us = [
            r
            for r in details["release_dates"]["results"]
            if r.get("iso_3166_1") == "US"
        ]
        if us and us[0].get("release_dates"):
            certificates = us[0]["release_dates"][0].get("certification")

    runtime_display = (
        f"{details.get('runtime')} min"
        if media_type == "movie" and details.get("runtime")
        else (
            f"{_list_to_str_tmdb(details.get('episode_run_time', []))} min"
            if media_type != "movie"
            else None
        )
    )
    images_structured = _process_images(details.get("images", {}))
    images_structured["original_language"] = details.get("original_language")

    output_data = {
        "query": query,
        "media_type": media_type,
        "media_id": media_id,
        "title": details.get("title") or details.get("name"),
        "localized_title": details.get("original_title")
        or details.get("original_name"),
        "aka": _list_to_str_tmdb(
            details.get("alternative_titles", {}).get("titles", [])
            or details.get("alternative_titles", {}).get("results", []),
            key="title",
        ),
        "kind": media_type,
        "year": (details.get("release_date") or details.get("first_air_date") or "")[
            :4
        ],
        "release_date": details.get("release_date") or details.get("first_air_date"),
        "imdb_id": details.get("external_ids", {}).get("imdb_id"),
        "tmdb_id": details.get("id"),
        "rating": details.get("vote_average"),
        "votes": details.get("vote_count"),
        "runtime": runtime_display,
        "certificates": certificates,
        "genres": _list_to_str_tmdb(details.get("genres", []), key="name"),
        "languages": _list_to_str_tmdb(
            details.get("spoken_languages", []), key="english_name"
        ),
        "countries": _list_to_str_tmdb(
            details.get("production_countries", []), key="name"
        ),
        "director": _list_to_str_tmdb(
            [p for p in crew if p.get("job") == "Director"], key="name"
        ),
        "writer": _list_to_str_tmdb(
            [p for p in crew if p.get("job") in ["Screenplay", "Writer", "Story"]],
            key="name",
        ),
        "producer": _list_to_str_tmdb(
            [p for p in crew if p.get("job") == "Producer"], key="name"
        ),
        "composer": _list_to_str_tmdb(
            [p for p in crew if p.get("job") == "Original Music Composer"], key="name"
        ),
        "cinematographer": _list_to_str_tmdb(
            [p for p in crew if p.get("job") == "Director of Photography"], key="name"
        ),
        "cast": _list_to_str_tmdb(
            details.get("credits", {}).get("cast", []), key="name", limit=15
        ),
        "plot": details.get("overview"),
        "tagline": details.get("tagline"),
        "box_office": (
            f"${details.get('revenue'):,}" if details.get("revenue", 0) > 0 else "N/A"
        ),
        "distributors": _list_to_str_tmdb(
            details.get("production_companies", []), key="name"
        ),
        "poster_url": (
            f"{TMDB_IMAGE_BASE_URL}{details.get('poster_path')}"
            if details.get("poster_path")
            else None
        ),
        "url": f"https://www.themoviedb.org/{media_type}/{details.get('id')}",
        "images": images_structured,
    }
    if media_type == "tv":
        output_data.update(
            {
                "seasons": details.get("number_of_seasons"),
                "episodes": details.get("number_of_episodes"),
            }
        )
    return output_data


async def get_poster(query, bulk=False, id=False, file=None):
    try:
        data = await _fetch_tmdb_data(str(query), api_key=TMDB_API_KEY or None)
        if data:
            return [data] if bulk else data
    except Exception as e:
        logger.error(f"Fallback get_poster failed: {e}")
    return None


async def get_movie_detailsx(query, id=False, file=None):
    q = str(query).strip()
    try:
        data = await _fetch_tmdb_data(q, api_key=TMDB_API_KEY or None)
        if not data:
            return None
    except Exception:
        return None

    details = {
        "title": data.get("title") or data.get("localized_title"),
        "year": data.get("year"),
        "release_date": data.get("release_date"),
        "rating": (
            round(float(data.get("rating", 0)), 1)
            if data.get("rating") is not None
            else None
        ),
        "votes": int(data.get("votes", 0)) if data.get("votes") else 0,
        "runtime": data.get("runtime"),
        "certificates": data.get("certificates"),
        "tmdb_url": data.get("url"),
        "plot": data.get("plot") or "No plot description available.",
        "tagline": data.get("tagline"),
        "box_office": data.get("box_office"),
        "imdb_id": data.get("imdb_id"),
        "tmdb_id": data.get("tmdb_id"),
    }

    for key in ("genres", "languages", "countries"):
        details[key] = (
            [s.strip() for s in data.get(key).split(",")] if data.get(key) else []
        )
    for role in (
        "director",
        "writer",
        "producer",
        "composer",
        "cinematographer",
        "cast",
    ):
        details[role] = (
            [s.strip() for s in data.get(role).split(",")] if data.get(role) else []
        )
    details["distributors"] = (
        [d.strip() for d in data.get("distributors").split(",")]
        if data.get("distributors")
        else []
    )

    posters, original_language, poster_url = (
        data.get("images", {}).get("posters", {}),
        data.get("images", {}).get("original_language"),
        data.get("poster_url"),
    )
    if not poster_url:
        for key in ("en", original_language, "xx"):
            if posters.get(key):
                poster_url = posters[key][0]
                break
    details["poster_url"] = (
        poster_url.replace("/original/", "/w1280/") if poster_url else None
    )

    backdrops, backdrop_url = data.get("images", {}).get("backdrops", {}), None
    for key in ("en", original_language, "xx", "no_lang"):
        if backdrops.get(key):
            backdrop_url = backdrops[key][0]
            break
    details["backdrop_url"] = (
        backdrop_url.replace("/original/", "/w1280/") if backdrop_url else None
    )

    return details


# ============================================================
# 🎯 IMDB SEARCH COMMANDS (ADMIN PROTECTED)
# ============================================================
@Client.on_message(filters.command(["imdb", "search"]) & admin_filter)
async def imdb_search(client: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text("🎬 **Usage:** `/imdb Movie or Series Name`")

    query = message.text.split(None, 1)[1]
    wait_msg = await message.reply_text("🔎 Searching IMDb...")

    try:
        movies = await get_poster(query, bulk=True)
        if not movies:
            return await wait_msg.edit_text("❌ No results found on IMDb.")

        buttons = []
        for movie in movies[:10]:
            m_id = (
                getattr(movie, "movieID", None)
                or (movie.get("movieID") if isinstance(movie, dict) else None)
                or movie.get("media_id", movie.get("id", ""))
            )
            title = getattr(movie, "title", None) or (
                movie.get("title") if isinstance(movie, dict) else "Unknown"
            )
            year = getattr(movie, "year", None) or (
                movie.get("year") if isinstance(movie, dict) else ""
            )

            if m_id:
                buttons.append(
                    [
                        InlineKeyboardButton(
                            f"{title} ({year})" if year else title,
                            callback_data=f"imdb#{m_id}",
                        )
                    ]
                )

        if not buttons:
            return await wait_msg.edit_text("❌ Could not parse IMDb results.")
        await wait_msg.edit_text(
            "🎥 **Here's what I found:**", reply_markup=InlineKeyboardMarkup(buttons)
        )
    except Exception as e:
        await wait_msg.edit_text(f"⚠️ IMDb search error: `{e}`")


@Client.on_callback_query(filters.regex(r"^imdb#") & cb_admin_filter)
async def imdb_callback(client: Client, query: CallbackQuery):
    try:
        _, movie_id = query.data.split("#")
        await query.answer("Fetching Details...", show_alert=False)

        imdb = await get_poster(query=movie_id, id=True)
        if not imdb:
            return await query.message.edit_text("❌ No IMDb results found.")

        url = imdb.get("url", f"https://www.imdb.com/title/tt{movie_id}/")
        buttons = [[InlineKeyboardButton(f"{imdb.get('title', 'IMDb Link')}", url=url)]]

        format_args = SafeDict(
            query=imdb.get("title", "N/A"),
            title=imdb.get("title", "N/A"),
            votes=imdb.get("votes", "N/A"),
            aka=imdb.get("aka", "N/A"),
            seasons=imdb.get("seasons", "N/A"),
            box_office=imdb.get("box_office", "N/A"),
            localized_title=imdb.get("localized_title", "N/A"),
            kind=imdb.get("kind", "N/A"),
            imdb_id=imdb.get("imdb_id", movie_id),
            cast=imdb.get("cast", "N/A"),
            runtime=imdb.get("runtime", "N/A"),
            countries=imdb.get("countries", "N/A"),
            certificates=imdb.get("certificates", "N/A"),
            languages=imdb.get("languages", "N/A"),
            director=imdb.get("director", "N/A"),
            writer=imdb.get("writer", "N/A"),
            producer=imdb.get("producer", "N/A"),
            composer=imdb.get("composer", "N/A"),
            cinematographer=imdb.get("cinematographer", "N/A"),
            music_team=imdb.get("music_team", "N/A"),
            distributors=imdb.get("distributors", "N/A"),
            release_date=imdb.get("release_date", "N/A"),
            year=imdb.get("year", "N/A"),
            genres=imdb.get("genres", "N/A"),
            poster=imdb.get("poster_url", "N/A"),
            plot=imdb.get("plot", "N/A"),
            rating=imdb.get("rating", "N/A"),
            url=url,
        )

        caption = IMDB_TEMPLATE.format_map(format_args)
        poster = imdb.get("poster_url")

        if poster:
            try:
                await query.message.reply_photo(
                    photo=poster,
                    caption=caption,
                    reply_markup=InlineKeyboardMarkup(buttons),
                )
            except (MediaEmpty, PhotoInvalidDimensions, WebpageMediaEmpty):
                await query.message.reply_photo(
                    photo=poster.replace(".jpg", "._V1_UX360.jpg"),
                    caption=caption,
                    reply_markup=InlineKeyboardMarkup(buttons),
                )
            await query.message.delete()
        else:
            await query.message.edit_text(
                caption,
                reply_markup=InlineKeyboardMarkup(buttons),
                disable_web_page_preview=False,
            )
    except Exception as e:
        logger.error(f"IMDb Callback Error: {e}")
        try:
            await query.message.edit_text(f"⚠️ Error loading details: `{e}`")
        except Exception:
            pass
