import asyncio
import logging
import re
from datetime import datetime
from difflib import SequenceMatcher
from io import BytesIO

import aiohttp
from PIL import Image

from info import IMAGE_FETCH, MAX_LIST_ELM, TMDB_API_KEY

logger = logging.getLogger(__name__)
Image.MAX_IMAGE_PIXELS = None

TMDB_BEARER_TOKEN = "eyJhbGciOiJIUzI1NiJ9.eyJhdWQiOiI2ZGU3YTIyZGU1YjE5YTFjNmUyZGU5ZWEyMzE2ZmQxMCIsIm5iZiI6MTc0NTMyMjQ2Mi41MzMsInN1YiI6IjY4MDc4MWRlYzVjODAzNWZiMDhhNjExNCIsInNjb3BlcyI6WyJhcGlfcmVhZCJdLCJ2ZXJzaW9uIjoxfQ.rMMJ2-PBIv8Y7ybxPIEpIlzTEXzuwrm9ruKxAUCAsbw"
TMDB_BASE_URL = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE_URL = "https://image.tmdb.org/t/p/original"

_session = None


async def get_session():
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15))
    return _session


async def _tmdb_get(path, params=None):
    url = f"{TMDB_BASE_URL}/{path.lstrip('/')}"
    _params, _headers = params.copy() if params else {}, {}
    if TMDB_API_KEY:
        _params["api_key"] = TMDB_API_KEY
    elif TMDB_BEARER_TOKEN:
        _headers = {
            "Authorization": f"Bearer {TMDB_BEARER_TOKEN}",
            "Content-Type": "application/json;charset=utf-8",
        }

    session = await get_session()
    async with session.get(url, params=_params, headers=_headers, ssl=False) as resp:
        if resp.status == 200:
            return await resp.json()
        return {}


async def _search_media_id(query: str):
    match = re.search(r"^(.*?)(?:\s+(\d{4}))?$", query.strip())
    title, year = match.groups() if match else (query.strip(), None)
    year = int(year) if year and year.isdigit() else None

    result = await _tmdb_get(
        "search/multi",
        {"query": title, "language": "en-US", "page": 1, "include_adult": "false"},
    )
    multi_results = result.get("results", [])
    if not multi_results:
        return None, None

    def get_ratio(s1, s2):
        return SequenceMatcher(None, (s1 or "").lower(), (s2 or "").lower()).ratio()

    scored = [
        (r, get_ratio(r.get("title") or r.get("name"), title)) for r in multi_results
    ]
    scored.sort(key=lambda x: x[1], reverse=True)

    for r, _ in scored:
        if r.get("media_type") in ["movie", "tv"]:
            return r["media_type"], r["id"]
    return None, None


async def _fetch_tmdb_data(query: str):
    media_type, media_id = await _search_media_id(query)
    if not media_id:
        return None

    details = await _tmdb_get(
        f"{media_type}/{media_id}",
        {"append_to_response": "credits,external_ids,images"},
    )
    crew = details.get("credits", {}).get("crew", [])

    return {
        "title": details.get("title") or details.get("name"),
        "year": (details.get("release_date") or details.get("first_air_date", ""))[:4],
        "release_date": details.get("release_date") or details.get("first_air_date"),
        "rating": details.get("vote_average"),
        "votes": details.get("vote_count"),
        "runtime": f"{details.get('runtime')} min" if details.get("runtime") else None,
        "genres": ", ".join(g["name"] for g in details.get("genres", [])),
        "languages": ", ".join(
            l["english_name"] for l in details.get("spoken_languages", [])
        ),
        "director": ", ".join(c["name"] for c in crew if c.get("job") == "Director"),
        "cast": ", ".join(
            c["name"] for c in details.get("credits", {}).get("cast", [])[:15]
        ),
        "plot": details.get("overview"),
        "poster_url": (
            f"{TMDB_IMAGE_BASE_URL}{details.get('poster_path')}"
            if details.get("poster_path")
            else None
        ),
        "backdrop_url": (
            f"{TMDB_IMAGE_BASE_URL}{details.get('backdrop_path')}"
            if details.get("backdrop_path")
            else None
        ),
        "imdb_id": details.get("external_ids", {}).get("imdb_id"),
        "url": f"https://www.themoviedb.org/{media_type}/{details.get('id')}",
    }


async def get_movie_detailsx(query, id=False, file=None):
    data = await _fetch_tmdb_data(query)
    if not data:
        return None

    for key in (
        "genres",
        "languages",
        "countries",
        "director",
        "writer",
        "producer",
        "composer",
        "cinematographer",
        "cast",
    ):
        if isinstance(data.get(key), str):
            data[key] = [s.strip() for s in data[key].split(",") if s.strip()]
    return data
