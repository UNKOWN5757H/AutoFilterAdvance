import asyncio
import re
import urllib.parse
import warnings
from datetime import datetime
from difflib import SequenceMatcher
from io import BytesIO
from logging import getLogger, ERROR

import aiohttp
from PIL import Image

from info import IMAGE_FETCH, MAX_LIST_ELM, TMDB_API_KEY

logger = getLogger(__name__)
logger.setLevel(ERROR)

LONG_IMDB_DESCRIPTION = False

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
                logger.error(f"Failed to fetch image: {response.status} for {url}")
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


async def close_session():
    global _session
    if _session and not _session.closed:
        await _session.close()


def list_to_str(lst):
    if lst:
        return ", ".join(map(str, lst))
    return ""


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
    year = None

    year_match = re.search(r"\b(19\d{2}|20\d{2})\b", q)
    if year_match:
        year = int(year_match.group(1))
        q = q.replace(year_match.group(1), "")

    q = re.sub(
        r"(?i)\b(hdrip|web-dl|webrip|bluray|brrip|dvdrip|dvdscr|tsrip|camrip|hdtc|hevc|x264|x265|1080p|720p|480p|2160p|4k|hindi|kannada|telugu|tamil|malayalam|english|movie|series|season\s*\d+|ep\s*\d+)\b",
        "",
        q,
    )
    q = re.sub(r"[\(\)\[\]\{\}\-_.:]", " ", q)
    q = re.sub(r"\s+", " ", q).strip()

    return q if q else str(query).strip(), year


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

    queries_to_try = [clean_title]
    words = clean_title.split()
    if len(words) > 2:
        queries_to_try.append(" ".join(words[:2]))
    if len(words) > 1:
        queries_to_try.append(words[0])

    queries_to_try = list(dict.fromkeys(queries_to_try))

    multi_results = []
    for target_query in queries_to_try:
        if not target_query:
            continue
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
        except Exception as e:
            logger.debug(f"TMDB search failed for '{target_query}': {e}")
            continue

    if not multi_results and year:
        try:
            params = {
                "query": clean_title,
                "language": "en-US",
                "page": 1,
                "include_adult": "false",
            }
            result = await _tmdb_get("search/multi", params=params, api_key=api_key)
            multi_results = result.get("results", [])
        except Exception:
            pass

    if not multi_results:
        return None, None

    def get_ratio(s1, s2):
        if not s1 or not s2:
            return 0
        return SequenceMatcher(None, str(s1).lower(), str(s2).lower()).ratio()

    valid_candidates = []
    for r in multi_results:
        mtype = r.get("media_type")
        if mtype not in ["movie", "tv"]:
            continue

        title_name = r.get("title") or r.get("name") or ""
        ratio = get_ratio(title_name, clean_title)

        rd_str = r.get("release_date") or r.get("first_air_date") or ""
        match_year = None
        if rd_str and len(rd_str) >= 4:
            try:
                match_year = int(rd_str[:4])
            except ValueError:
                pass

        year_score = 1.0
        if year and match_year:
            diff = abs(match_year - year)
            if diff == 0:
                year_score = 1.2
            elif diff == 1:
                year_score = 0.9
            else:
                year_score = 0.5

        popularity = r.get("popularity", 0)
        final_score = (ratio * 100) * year_score + (popularity / 10)

        valid_candidates.append((mtype, r["id"], final_score))

    if not valid_candidates:
        first = multi_results[0]
        if first.get("media_type") in ["movie", "tv"]:
            return first["media_type"], first["id"]
        return None, None

    valid_candidates.sort(key=lambda x: x[2], reverse=True)
    best = valid_candidates[0]
    return best[0], best[1]


def _process_images(images_data):
    posters_by_lang, backdrops_by_lang = {}, {}
    for img in images_data.get("posters", []):
        lang = img.get("iso_639_1") or "no_lang"
        posters_by_lang.setdefault(lang, []).append(
            f"{TMDB_IMAGE_BASE_URL}{img['file_path']}"
        )
    for img in images_data.get("backdrops", []):
        lang = img.get("iso_639_1") or "no_lang"
        backdrops_by_lang.setdefault(lang, []).append(
            f"{TMDB_IMAGE_BASE_URL}{img['file_path']}"
        )
    posters_by_lang["all"] = [
        f"{TMDB_IMAGE_BASE_URL}{i['file_path']}" for i in images_data.get("posters", [])
    ]
    backdrops_by_lang["all"] = [
        f"{TMDB_IMAGE_BASE_URL}{i['file_path']}"
        for i in images_data.get("backdrops", [])
    ]
    languages = sorted(set(posters_by_lang) | set(backdrops_by_lang))
    return {
        "posters": posters_by_lang,
        "backdrops": backdrops_by_lang,
        "available_languages": languages,
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

    runtime_display = None
    if media_type == "movie":
        runtime = details.get("runtime")
        runtime_display = f"{runtime} min" if runtime else None
    else:
        er = _list_to_str_tmdb(details.get("episode_run_time", []))
        runtime_display = f"{er} min" if er else None

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


async def get_movie_details(query, bulk=False, id=False, file=None):
    try:
        data = await _fetch_tmdb_data(str(query), api_key=TMDB_API_KEY or None)
        if data:
            if bulk:
                return [data]
            return data
    except Exception as e:
        logger.error(f"Fallback get_movie_details failed: {e}")
    return None


async def get_movie_detailsx(query, id=False, file=None):
    q = str(query).strip()
    try:
        data = await _fetch_tmdb_data(q, api_key=TMDB_API_KEY or None)
        if not data:
            logger.warning(f"TMDB returned no results for '{q}'")
            return None
    except Exception as e:
        logger.error(f"TMDB direct call failed for '{q}': {e}")
        return None

    details = {}
    details["title"] = data.get("title") or data.get("localized_title")
    details["year"] = data.get("year") if data.get("year") else None
    details["release_date"] = data.get("release_date")
    details["rating"] = (
        round(float(data.get("rating", 0)), 1)
        if data.get("rating") is not None
        else None
    )
    details["votes"] = int(data.get("votes", 0)) if data.get("votes") else 0
    details["runtime"] = data.get("runtime")
    details["certificates"] = data.get("certificates")
    details["tmdb_url"] = data.get("url")

    for key in ("genres", "languages", "countries"):
        raw = data.get(key)
        details[key] = [s.strip() for s in raw.split(",")] if raw else []

    for role in (
        "director",
        "writer",
        "producer",
        "composer",
        "cinematographer",
        "cast",
    ):
        raw = data.get(role)
        details[role] = [s.strip() for s in raw.split(",")] if raw else []

    details["plot"] = data.get("plot") or "No plot description available."
    details["tagline"] = data.get("tagline")
    details["box_office"] = data.get("box_office") if data.get("box_office") else None

    raw_dist = data.get("distributors")
    details["distributors"] = (
        [d.strip() for d in raw_dist.split(",")] if raw_dist else []
    )
    details["imdb_id"] = data.get("imdb_id")
    details["tmdb_id"] = data.get("tmdb_id")

    posters = data.get("images", {}).get("posters", {})
    original_language = data.get("images", {}).get("original_language")
    poster_url = data.get("poster_url")
    if not poster_url:
        for key in ("en", original_language, "xx"):
            if key and posters.get(key):
                poster_url = posters[key][0]
                break
    details["poster_url"] = (
        poster_url.replace("/original/", "/w1280/") if poster_url else None
    )

    backdrops = data.get("images", {}).get("backdrops", {})
    backdrop_url = None
    for key in ("en", original_language, "xx", "no_lang"):
        if key and backdrops.get(key):
            backdrop_url = backdrops[key][0]
            break
    details["backdrop_url"] = (
        backdrop_url.replace("/original/", "/w1280/") if backdrop_url else None
    )

    return details
