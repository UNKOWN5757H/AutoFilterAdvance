import ast
import asyncio
import difflib
import html
import inspect
import math
import re
import time
import unicodedata
import urllib.parse
from logging import ERROR, getLogger
from typing import Any, Dict, List, Optional, Set, Tuple

from motor.motor_asyncio import AsyncIOMotorClient
from pyrogram import Client, enums, filters
from pyrogram.errors import (
    ButtonUrlInvalid,
    ChatAdminRequired,
    ChatWriteForbidden,
    FloodWait,
    Forbidden,
    MessageIdInvalid,
    MessageNotModified,
    PeerIdInvalid,
    QueryIdInvalid,
    SlowmodeWait,
    UserIsBlocked,
)
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

import info
from database.filters_mdb import add_filter, delete_filter, find_filter, get_filters
from database.ia_filterdb import Media as _Media
from database.ia_filterdb import get_search_results
from utils import get_settings, get_size, parse_text_and_markup, temp

# Safe optional imports
try:
    from database.plugin_dbs import plugin_db as _plugin_db
except ImportError:
    _plugin_db = None

try:
    from plugins.custom_settings import get_bot_settings, get_stopwords
except ImportError:
    try:
        from custom_settings import get_bot_settings, get_stopwords
    except ImportError:

        async def get_bot_settings():
            return {}

        def get_stopwords():
            return []


try:
    from plugins.uibuttons import (
        get_deleted_file_notify_keyboard as _get_deleted_file_notify_keyboard,
    )
except Exception:
    _get_deleted_file_notify_keyboard = None


logger = getLogger(__name__)
logger.setLevel(ERROR)

# Strong reference set so Python's garbage collector never cancels sleeping auto-delete tasks
AUTO_DELETE_TASKS: Set[asyncio.Task] = set()

# ============================================================
# 🔗 CUSTOM EXTRA BUTTON LINKS (EDIT YOUR LINKS HERE)
# ============================================================
EXTRA_BTN_1_URL = getattr(
    info, "EXTRA_BTN_1_URL", "https://t.me/+lcTawsnhdi0zYWE1"
)  # Link for [🎞] button
EXTRA_BTN_2_URL = getattr(
    info, "EXTRA_BTN_2_URL", "https://t.me/linkz_ki_duniyaa"
)  # Link for [🔞] button

# ============================================================
# 🌐 LANGUAGES, 🎞️ QUALITIES, 📺 SEASONS & 📅 YEARS CONFIG
# ============================================================
LANGUAGES_LIST: List[Tuple[str, str]] = [
    ("Kannada", "kan"),
    ("Tulu", "tul"),
    ("English", "eng"),
    ("Hindi", "hin"),
    ("Tamil", "tam"),
    ("Telugu", "tel"),
    ("Malayalam", "mal"),
    ("Marathi", "mar"),
    ("Gujarati", "guj"),
    ("Bengali", "ben"),
    ("Punjabi", "pun"),
    ("Nepali", "nep"),
]

LANG_MAP: Dict[str, str] = {code: name for name, code in LANGUAGES_LIST}

LANG_PATTERNS: Dict[str, re.Pattern] = {
    "kan": re.compile(r"(?i)\b(kannada|kan|sandalwood)\b"),
    "tul": re.compile(r"(?i)\b(tulu|tul)\b"),
    "eng": re.compile(r"(?i)\b(english|eng|dual\s*audio|multi\s*audio)\b"),
    "hin": re.compile(r"(?i)\b(hindi|hin|bollywood|dual\s*audio|multi\s*audio)\b"),
    "tam": re.compile(r"(?i)\b(tamil|tam|kollywood)\b"),
    "tel": re.compile(r"(?i)\b(telugu|tel|tollywood)\b"),
    "mal": re.compile(r"(?i)\b(malayalam|mal|mollywood)\b"),
    "mar": re.compile(r"(?i)\b(marathi|mar)\b"),
    "guj": re.compile(r"(?i)\b(gujarati|guj)\b"),
    "ben": re.compile(r"(?i)\b(bengali|ben|bangla)\b"),
    "pun": re.compile(r"(?i)\b(punjabi|pun)\b"),
    "nep": re.compile(r"(?i)\b(nepali|nep)\b"),
}

QUALITIES_LIST: List[str] = [
    "144p",
    "240p",
    "360p",
    "480p",
    "540p",
    "720p",
    "1080p",
    "1440p",
    "2160p",
    "4320p",
]

QUAL_PATTERNS: Dict[str, re.Pattern] = {
    "144p": re.compile(r"(?i)\b144p\b"),
    "240p": re.compile(r"(?i)\b240p\b"),
    "360p": re.compile(r"(?i)\b360p\b"),
    "480p": re.compile(r"(?i)\b(480p|dvdrip|sd)\b"),
    "540p": re.compile(r"(?i)\b540p\b"),
    "720p": re.compile(r"(?i)\b(720p|hdrip|hd)\b"),
    "1080p": re.compile(r"(?i)\b(1080p|fhd|full\s*hd)\b"),
    "1440p": re.compile(r"(?i)\b(1440p|2k|qhd)\b"),
    "2160p": re.compile(r"(?i)\b(2160p|4k|uhd)\b"),
    "4320p": re.compile(r"(?i)\b(4320p|8k)\b"),
}

SEASONS_LIST: List[Tuple[str, str]] = [
    (f"Season {i}", f"s{i:02d}") for i in range(1, 13)
]
SEASON_MAP: Dict[str, str] = {code: name for name, code in SEASONS_LIST}
SEASON_PATTERNS: Dict[str, re.Pattern] = {
    f"s{i:02d}": re.compile(rf"(?i)\b(s0?{i}(?:e\d+|\b|\s)|season\s*0?{i}\b)")
    for i in range(1, 13)
}

EPISODES_LIST: List[Tuple[str, str]] = [
    (f"Ep {i:02d}", f"e{i:02d}") for i in range(1, 37)
]
EPISODE_PATTERNS: Dict[str, re.Pattern] = {
    f"e{i:02d}": re.compile(rf"(?i)\b(s\d+e0?{i}\b|e0?{i}\b|ep(?:isode)?\s*0?{i}\b)")
    for i in range(1, 37)
}

YEARS_LIST: List[str] = [str(y) for y in range(2026, 1999, -1)]
YEAR_REGEX_EXTRACT = re.compile(r"\b(19[7-9]\d|20[0-2]\d)\b")

# Pre-compiled regexes for ultra-fast execution
_URL_MENTION_RE = re.compile(r"https?://\S+|t\.me/\S+|@\w+")
_NON_ALNUM_RE = re.compile(r"[^a-zA-Z0-9]")
_MULTI_SPACE_RE = re.compile(r"\s+")
_STRIP_NOISE_RE = re.compile(
    r"(?i)\b(4320p|2160p|1440p|1080p|720p|540p|480p|360p|240p|144p|4k|2k|8k|mkv|mp4|avi|webm|hdrip|web-?dl|webrip|bluray|brrip|dvdrip|camrip|hdts|predvd|x264|x265|hevc|avc|aac\d*|ddp?\d*|dd\d*|ac3|eac3|atmos|\d+ch|10bit|8bit|hdr|sdr|dual\s*audio|multi\s*audio|hindi|kannada|tulu|telugu|tamil|malayalam|marathi|gujarati|bengali|punjabi|nepali|english|subtitles|subs|esub|esubs|episodes?|season\s*\d+|s\d+e\d+|s\d+|e\d+|ep\s*\d+|complete|movie|full|hd|send|me|please|plz|bro|link|give|new)\b"
)
_TITLE_SPLIT_RE = re.compile(
    r"(?i)\b(4320p|2160p|1440p|1080p|720p|540p|480p|360p|240p|144p|4k|2k|8k|hdrip|web-?dl|webrip|bluray|brrip|dvdrip|camrip|hdts|predvd|x264|x265|hevc|avc|aac\d*|ddp?\d*|dd\d*|ac3|eac3|atmos|10bit|8bit|hdr|sdr|dual\s*audio|multi\s*audio|kannada|tulu|telugu|tamil|malayalam|hindi|english|marathi|gujarati|bengali|punjabi|nepali|esub|subtitles|mkv|mp4|avi|s\d+e\d+|s\d+|season\s*\d+)\b"
)
_SUBTITLE_DETECT_RE = re.compile(r"(?i)\b(esubs?|subtitles?|softmux|subs?)\b")
_HEVC_DETECT_RE = re.compile(r"(?i)\b(hevc|x265|10bit)\b")

IGNORE_WORDS_SET = {
    "hello",
    "hey",
    "hii",
    "hlo",
    "hlw",
    "mam",
    "ok",
    "okay",
    "kk",
    "k",
    "tq",
    "ty",
    "yes",
    "no",
    "yo",
    "hmm",
    "hm",
    "gm",
    "gn",
    "admin",
    "owner",
    "help",
    "start",
    "ping",
    "status",
    "nice",
    "super",
    "wow",
}

# ============================================================
# 🔤 INDIAN SCRIPT-TO-ENGLISH TRANSLITERATION ENGINE
# ============================================================
_INDIC_ACRONYM_MAP: Dict[str, str] = {
    "ಕೆಜಿಎಫ್": "kgf",
    "ಕೆ.ಜಿ.ಎಫ್": "kgf",
    "ಕಾಂತಾರ": "kantara",
    "ಕಾಟೇರ": "kaatera",
    "ಯುವ": "yuva",
    "ಬಘೀರ": "bagheera",
    "ಮಾರ್ಟಿನ್": "martin",
    "ಭೈರತಿ ರಣಗಲ್": "bhairathi ranagal",
    "ಮ್ಯಾಕ್ಸ್": "max",
    "ಯುಐ": "ui",
    "ಆರ್ ಆರ್ ಆರ್": "rrr",
    "ಆರ್.ಆರ್.ಆರ್": "rrr",
    "ಎನ್ ಟಿ ಆರ್": "ntr",
    "ಪುಷ್ಪ": "pushpa",
    "ಸಲಾರ್": "salaar",
    "ಕಲ್ಕಿ": "kalki",
    "केजीएफ": "kgf",
    "के.जी.एफ": "kgf",
    "कांतारा": "kantara",
    "आरआरआर": "rrr",
    "पुष्पा": "pushpa",
    "कल्कि": "kalki",
    "जवान": "jawan",
    "पठान": "pathaan",
    "सालार": "salaar",
    "കെജിഎഫ്": "kgf",
    "கேஜிஎப்": "kgf",
    "కేజీఎఫ్": "kgf",
    "కాంతార": "kantara",
    "காந்தாரா": "kantara",
    "കാന്താര": "kantara",
}

_INDIC_OFFSET_VOWELS: Dict[int, str] = {
    0x05: "a",
    0x06: "aa",
    0x07: "i",
    0x08: "ee",
    0x09: "u",
    0x0A: "oo",
    0x0B: "ru",
    0x0C: "l",
    0x0D: "e",
    0x0E: "e",
    0x0F: "ee",
    0x10: "ai",
    0x11: "o",
    0x12: "o",
    0x13: "oo",
    0x14: "au",
    0x60: "ru",
}

_INDIC_OFFSET_MATRAS: Dict[int, str] = {
    0x3E: "a",
    0x3F: "i",
    0x40: "ee",
    0x41: "u",
    0x42: "oo",
    0x43: "ru",
    0x44: "ru",
    0x45: "e",
    0x46: "e",
    0x47: "e",
    0x48: "ai",
    0x49: "o",
    0x4A: "o",
    0x4B: "o",
    0x4C: "au",
    0x55: "",
    0x56: "ai",
    0x57: "au",
}

_INDIC_OFFSET_CONSONANTS: Dict[int, str] = {
    0x15: "k",
    0x16: "kh",
    0x17: "g",
    0x18: "gh",
    0x19: "ng",
    0x1A: "ch",
    0x1B: "chh",
    0x1C: "j",
    0x1D: "jh",
    0x1E: "ny",
    0x1F: "t",
    0x20: "th",
    0x21: "d",
    0x22: "dh",
    0x23: "n",
    0x24: "t",
    0x25: "th",
    0x26: "d",
    0x27: "dh",
    0x28: "n",
    0x29: "n",
    0x2A: "p",
    0x2B: "ph",
    0x2C: "b",
    0x2D: "bh",
    0x2E: "m",
    0x2F: "y",
    0x30: "r",
    0x31: "r",
    0x32: "l",
    0x33: "l",
    0x34: "zh",
    0x35: "v",
    0x36: "sh",
    0x37: "sh",
    0x38: "s",
    0x39: "h",
    0x58: "q",
    0x59: "kh",
    0x5A: "gh",
    0x5B: "z",
    0x5C: "d",
    0x5D: "rh",
    0x5E: "f",
    0x5F: "y",
}

_MALAYALAM_CHILLU: Dict[int, str] = {
    0x7A: "n",
    0x7B: "n",
    0x7C: "r",
    0x7D: "l",
    0x7E: "l",
    0x7F: "k",
}


def has_indic_script(text: str) -> bool:
    return any(0x0900 <= ord(ch) <= 0x0D7F for ch in text)


def transliterate_indic_to_english(text: str) -> str:
    if not text or not has_indic_script(text):
        return text

    norm_text = unicodedata.normalize("NFC", text.strip())
    for k, v in _INDIC_ACRONYM_MAP.items():
        norm_text = norm_text.replace(k, f" {v} ")

    out: List[str] = []
    n = len(norm_text)
    i = 0

    while i < n:
        ch = norm_text[i]
        cp = ord(ch)

        if 0x0900 <= cp <= 0x0D7F:
            offset = cp & 0x7F

            if 0x66 <= offset <= 0x6F:
                out.append(str(offset - 0x66))
                i += 1
                continue

            if (cp & 0xFF80) == 0x0D00 and offset in _MALAYALAM_CHILLU:
                out.append(_MALAYALAM_CHILLU[offset])
                i += 1
                continue

            if offset in (0x01, 0x02):
                next_offset = (
                    (ord(norm_text[i + 1]) & 0x7F)
                    if (i + 1 < n and 0x0900 <= ord(norm_text[i + 1]) <= 0x0D7F)
                    else 0
                )
                if 0x2A <= next_offset <= 0x2E or next_offset == 0:
                    out.append("m")
                else:
                    out.append("n")
                i += 1
                continue

            if offset == 0x03:
                out.append("h")
                i += 1
                continue

            if offset in _INDIC_OFFSET_VOWELS:
                out.append(_INDIC_OFFSET_VOWELS[offset])
                i += 1
                continue

            if offset in _INDIC_OFFSET_CONSONANTS:
                base_c = _INDIC_OFFSET_CONSONANTS[offset]
                next_cp = ord(norm_text[i + 1]) if (i + 1) < n else 0
                next_off = (next_cp & 0x7F) if (0x0900 <= next_cp <= 0x0D7F) else -1

                if next_off == 0x3C:
                    i += 1
                    next_cp = ord(norm_text[i + 1]) if (i + 1) < n else 0
                    next_off = (next_cp & 0x7F) if (0x0900 <= next_cp <= 0x0D7F) else -1

                if next_off == 0x4D:
                    out.append(base_c)
                    i += 2
                    continue

                if next_off in _INDIC_OFFSET_MATRAS:
                    out.append(base_c + _INDIC_OFFSET_MATRAS[next_off])
                    i += 2
                    continue

                is_devanagari = (cp & 0xFF80) == 0x0900
                is_word_end = (i + 1 == n) or not (0x0900 <= next_cp <= 0x0D7F)
                if is_devanagari and is_word_end and len(out) > 0:
                    out.append(base_c)
                else:
                    out.append(base_c + "a")
                i += 1
                continue

            if offset in _INDIC_OFFSET_MATRAS:
                out.append(_INDIC_OFFSET_MATRAS[offset])
                i += 1
                continue

            i += 1
        else:
            out.append(ch)
            i += 1

    result = "".join(out)
    return _MULTI_SPACE_RE.sub(" ", result).strip().lower()


def generate_phonetic_variants(translit_str: str) -> List[str]:
    if not translit_str:
        return []
    variants = [translit_str]
    v1 = (
        translit_str.replace("aa", "a")
        .replace("ee", "i")
        .replace("oo", "u")
        .replace("bh", "b")
        .replace("dh", "d")
        .replace("th", "t")
        .replace("kh", "k")
        .replace("gh", "g")
        .replace("ph", "p")
    )
    if v1 not in variants:
        variants.append(v1)
    v2_words = [(w[:-1] if len(w) > 3 and w.endswith("a") else w) for w in v1.split()]
    v2 = " ".join(v2_words)
    if v2 and v2 not in variants:
        variants.append(v2)
    v3_words = [
        (w[:-1] if len(w) > 3 and w.endswith("a") else w) for w in translit_str.split()
    ]
    v3 = " ".join(v3_words)
    if v3 and v3 not in variants:
        variants.append(v3)
    return variants


# ============================================================
# 🛡️ PYROGRAM v2.2.26 COMPATIBILITY & SAFE SEND HELPERS
# ============================================================
try:
    from pyrogram.types import LinkPreviewOptions
except ImportError:
    LinkPreviewOptions = None

try:
    from pyrogram.types import ReplyParameters
except ImportError:
    ReplyParameters = None

_SEND_MSG_PARAMS = set(inspect.signature(Client.send_message).parameters.keys())
_REPLY_PARAMS = set(inspect.signature(Message.reply_text).parameters.keys())
_EDIT_PARAMS = set(inspect.signature(Message.edit_text).parameters.keys())

BTN_PRIMARY = None
BTN_SUCCESS = None
BTN_DANGER = None
_SUPPORTS_BTN_STYLE = False

try:
    from pyrogram.enums import ButtonStyle

    if "style" in inspect.signature(InlineKeyboardButton.__init__).parameters:
        BTN_PRIMARY = getattr(ButtonStyle, "PRIMARY", None)
        BTN_SUCCESS = getattr(ButtonStyle, "SUCCESS", None)
        BTN_DANGER = getattr(ButtonStyle, "DANGER", None)
        _SUPPORTS_BTN_STYLE = True
except (ImportError, ValueError, TypeError):
    BTN_PRIMARY = BTN_SUCCESS = BTN_DANGER = None
    _SUPPORTS_BTN_STYLE = False


def _normalize_style(style: Any) -> Any:
    if style is None or not _SUPPORTS_BTN_STYLE:
        return None
    if hasattr(style, "value"):
        return style
    if isinstance(style, int):
        return {
            1: BTN_PRIMARY,
            3: BTN_SUCCESS,
            4: BTN_DANGER,
        }.get(style, None)
    return style


def create_btn(
    text: str,
    url: Optional[str] = None,
    callback_data: Optional[str] = None,
    style: Any = None,
) -> InlineKeyboardButton:
    """Creates an InlineKeyboardButton safely. Pass style=None for no colour."""
    kwargs: Dict[str, Any] = {"text": str(text)}
    if url:
        kwargs["url"] = str(url).strip()
    elif callback_data:
        kwargs["callback_data"] = str(callback_data)[:64]

    norm_style = _normalize_style(style)
    if norm_style is not None:
        kwargs["style"] = norm_style
    try:
        return InlineKeyboardButton(**kwargs)
    except Exception:
        kwargs.pop("style", None)
        return InlineKeyboardButton(**kwargs)


# ============================================================
# ⚡ ULTRA-FAST O(1) IN-MEMORY CACHE SYSTEM
# ============================================================
class TTLCache:
    def __init__(self, maxsize: int = 2000, ttl: int = 1800):
        self._data: Dict[str, Tuple[float, Any]] = {}
        self._maxsize, self._ttl = maxsize, ttl

    def set(self, key: str, value: Any):
        now = time.time()
        if key in self._data:
            self._data.pop(key, None)
        elif len(self._data) >= self._maxsize:
            self._cleanup(now)
            if len(self._data) >= self._maxsize:
                oldest_key = next(iter(self._data))
                self._data.pop(oldest_key, None)
        self._data[key] = (now + self._ttl, value)

    def get(self, key: str) -> Optional[Any]:
        item = self._data.get(key)
        if not item:
            return None
        if time.time() > item[0]:
            self._data.pop(key, None)
            return None
        return item[1]

    def _cleanup(self, now: Optional[float] = None):
        now = now or time.time()
        expired = [k for k, (exp, _) in self._data.items() if now > exp]
        for k in expired:
            self._data.pop(k, None)


GLOBAL_SEARCH_CACHE = TTLCache(maxsize=3500, ttl=600)
POOL_SEARCH_CACHE = TTLCache(maxsize=800, ttl=600)
BUTTONS_CACHE = TTLCache(maxsize=3500, ttl=1800)
FILTER_STATE_CACHE = TTLCache(maxsize=3500, ttl=1800)
SUGGESTIONS_CACHE = TTLCache(maxsize=2000, ttl=1800)
DYM_QUERY_CACHE = TTLCache(maxsize=2000, ttl=1800)
USER_LAST_REQ = TTLCache(maxsize=5000, ttl=60)
FUZZY_TITLES_CACHE = TTLCache(maxsize=10, ttl=900)
RESTRICTED_WRITE_CHATS = TTLCache(maxsize=500, ttl=300)


async def safe_reply_text(
    msg: Message,
    text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    parse_mode: enums.ParseMode = enums.ParseMode.HTML,
) -> Optional[Message]:
    """Replies safely without ever crashing or logging errors on 403 CHAT_WRITE_FORBIDDEN."""
    if not msg:
        return None
    try:
        return await msg.reply_text(
            text=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
        )
    except FloodWait as e:
        if e.value <= 15:
            await asyncio.sleep(e.value + 1)
            try:
                return await msg.reply_text(
                    text=text,
                    reply_markup=reply_markup,
                    parse_mode=parse_mode,
                )
            except Exception:
                return None
        return None
    except (
        ChatWriteForbidden,
        Forbidden,
        ChatAdminRequired,
        UserIsBlocked,
        PeerIdInvalid,
        SlowmodeWait,
    ):
        if msg.chat:
            RESTRICTED_WRITE_CHATS.set(str(msg.chat.id), True)
        return None
    except Exception as e:
        if "CHAT_WRITE_FORBIDDEN" in str(e) or "403" in str(e):
            if msg.chat:
                RESTRICTED_WRITE_CHATS.set(str(msg.chat.id), True)
            return None
        logger.error(f"safe_reply_text error: {e}")
        return None


async def safe_reply_photo_or_text(
    msg: Message,
    photo: Optional[str],
    caption: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    parse_mode: enums.ParseMode = enums.ParseMode.HTML,
) -> Optional[Message]:
    """Tries sending a photo reply, and falls back to text if media is restricted."""
    if not msg:
        return None
    if photo and str(photo).lower() != "none":
        try:
            return await msg.reply_photo(
                photo=photo,
                caption=caption,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
            )
        except (ChatWriteForbidden, UserIsBlocked, PeerIdInvalid):
            if msg.chat:
                RESTRICTED_WRITE_CHATS.set(str(msg.chat.id), True)
            return None
        except FloodWait as e:
            if e.value <= 15:
                await asyncio.sleep(e.value + 1)
        except Exception:
            pass
    return await safe_reply_text(
        msg, text=caption, reply_markup=reply_markup, parse_mode=parse_mode
    )


async def safe_answer(
    query: CallbackQuery,
    text: Optional[str] = None,
    show_alert: bool = False,
):
    if not query:
        return
    try:
        if text is not None:
            await query.answer(str(text)[:200], show_alert=show_alert)
        else:
            await query.answer(show_alert=show_alert)
    except (QueryIdInvalid, Exception):
        pass


# ============================================================
# ⚡ GLOBAL CONFIG, FEATURE TOGGLES & MONGODB SETUP
# ============================================================
cw_db = None
pm_feat_db = None
_BOT_DB = None
try:
    _DB_CLIENT = AsyncIOMotorClient(info.DATABASE_URI)
    _BOT_DB = _DB_CLIENT[info.DATABASE_NAME]
    cw_db = _BOT_DB["clean_words"]
    pm_feat_db = _BOT_DB["pm_filter_features"]
except Exception as e:
    logger.error(f"Failed to init cw_db / pm_feat_db: {e}")

DEFAULT_CLEAN_WORDS = ["sandalwood", "mkv", "mp4", "avi", "webm", "zip", "rar"]
_CLEAN_WORDS_CACHE: Tuple[float, list] = (0.0, DEFAULT_CLEAN_WORDS)
_PROMO_CACHE: Tuple[float, List[Dict[str, str]]] = (0.0, [])
_FEATURE_FLAGS_CACHE: Dict[str, Any] = {
    "ts": 0.0,
    "autotranslate": True,
    "multichoice": True,
}


async def get_feature_flags(force_refresh: bool = False) -> Tuple[bool, bool]:
    now = time.time()
    if not force_refresh and (now - _FEATURE_FLAGS_CACHE["ts"]) < 60:
        return (
            bool(_FEATURE_FLAGS_CACHE["autotranslate"]),
            bool(_FEATURE_FLAGS_CACHE["multichoice"]),
        )
    if pm_feat_db is not None:
        try:
            doc = await pm_feat_db.find_one({"_id": "config"})
            if doc:
                _FEATURE_FLAGS_CACHE["autotranslate"] = bool(
                    doc.get("autotranslate", True)
                )
                _FEATURE_FLAGS_CACHE["multichoice"] = bool(doc.get("multichoice", True))
        except Exception as e:
            logger.error(f"get_feature_flags error: {e}")
    _FEATURE_FLAGS_CACHE["ts"] = now
    return (
        bool(_FEATURE_FLAGS_CACHE["autotranslate"]),
        bool(_FEATURE_FLAGS_CACHE["multichoice"]),
    )


async def set_feature_flag(key: str, value: bool):
    _FEATURE_FLAGS_CACHE[key] = bool(value)
    _FEATURE_FLAGS_CACHE["ts"] = time.time()
    if pm_feat_db is not None:
        try:
            await pm_feat_db.update_one(
                {"_id": "config"}, {"$set": {key: bool(value)}}, upsert=True
            )
        except Exception as e:
            logger.error(f"set_feature_flag error for {key}: {e}")


async def get_clean_words() -> list:
    global _CLEAN_WORDS_CACHE
    now = time.time()
    if now - _CLEAN_WORDS_CACHE[0] < 60:
        return _CLEAN_WORDS_CACHE[1]
    if cw_db is None:
        return DEFAULT_CLEAN_WORDS
    try:
        doc = await cw_db.find_one({"id": "words"})
        if doc is None or doc.get("use_default", True):
            words = DEFAULT_CLEAN_WORDS
        else:
            words = doc.get("list", [])
        _CLEAN_WORDS_CACHE = (now, words)
        return words
    except Exception:
        return DEFAULT_CLEAN_WORDS


async def get_active_promos() -> List[Dict[str, str]]:
    """Fetches active promotional buttons added via /addpromo in broadcast.py or plugin_db."""
    global _PROMO_CACHE
    now = time.time()
    if now - _PROMO_CACHE[0] < 60:
        return _PROMO_CACHE[1]

    promos: List[Dict[str, str]] = []
    if _plugin_db is not None and hasattr(_plugin_db, "get_promos"):
        try:
            raw_p = await _plugin_db.get_promos()
            if isinstance(raw_p, list):
                for item in raw_p:
                    if isinstance(item, dict) and item.get("text") and item.get("url"):
                        promos.append(
                            {"text": str(item["text"]), "url": str(item["url"])}
                        )
        except Exception:
            pass

    if not promos and _BOT_DB is not None:
        for col_name in ("promos", "promo_buttons"):
            try:
                cursor = _BOT_DB[col_name].find({})
                docs = await cursor.to_list(length=10)
                for d in docs:
                    if isinstance(d, dict) and d.get("text") and d.get("url"):
                        promos.append({"text": str(d["text"]), "url": str(d["url"])})
                if promos:
                    break
            except Exception:
                continue

    _PROMO_CACHE = (now, promos)
    return promos


def clean_filename(name: str, clean_words: list) -> str:
    if not name:
        return "File"
    if any(w.lower() in ["mkv", "sandalwood"] for w in clean_words):
        name = re.sub(r"(?i)\[?@?sandalwood[^\]\s]*\]?", "", name)
        name = re.sub(r"(?i)\b(sandalwood|mkv|mp4|avi|webm|zip|rar)\b", "", name)
    name = re.sub(r"[_.-]", " ", name)
    for word in clean_words:
        if word.lower() in ["mkv", "sandalwood", "mp4", "avi", "webm", "zip", "rar"]:
            continue
        name = re.sub(rf"(?i){re.escape(word)}", "", name)
    name = _MULTI_SPACE_RE.sub(" ", name).strip()
    return (name[:42] + "..") if len(name) > 45 else (name or "File")


def get_auto_delete_timer(
    var_name: str = "AUTO_DELETE_TIME", default_time: int = 300
) -> int:
    try:
        global_switch = getattr(info, "AUTO_DELETE", True)
        if str(global_switch).strip().lower() in ["false", "off", "0", "no"]:
            return 0
        raw_val = getattr(
            info,
            var_name,
            getattr(
                info,
                "AUTO_DELETE_TIME",
                getattr(info, "FILE_AUTO_DELETE", default_time),
            ),
        )
        if isinstance(raw_val, bool):
            return default_time if raw_val else 0
        val = int(str(raw_val).strip())
        return max(0, val)
    except Exception:
        return default_time


def format_duration(seconds: int) -> str:
    if seconds <= 0:
        return "0 Seconds"
    m, s = divmod(int(seconds), 60)
    if m > 0 and s > 0:
        return f"{m} Minute{'s' if m != 1 else ''} {s} Second{'s' if s != 1 else ''}"
    if m > 0:
        return f"{m} Minute{'s' if m != 1 else ''}"
    return f"{s} Second{'s' if s != 1 else ''}"


async def resolve_auto_delete_timer(
    chat_id: Optional[int] = None, default_time: int = 300
) -> int:
    """
    Reliably resolves the auto-delete timer in seconds across group settings,
    bot_settings DB, plugin_db, temp, and info.py so auto-delete never fails.
    """
    if chat_id:
        try:
            g_set = await get_settings(chat_id) or {}
            if g_set.get("auto_delete") is False:
                return 0
            for k in (
                "button_del",
                "buttondel",
                "button_auto_delete",
                "auto_delete_time",
                "autodelete",
            ):
                val = g_set.get(k)
                if val is not None and not isinstance(val, bool):
                    parsed = int(str(val).strip())
                    if parsed >= 0:
                        return parsed
        except Exception:
            pass

    try:
        b_set = await get_bot_settings() or {}
        for k in (
            "button_del",
            "buttondel",
            "button_auto_delete",
            "auto_delete_time",
            "autodelete",
        ):
            val = b_set.get(k)
            if val is not None and not isinstance(val, bool):
                parsed = int(str(val).strip())
                if parsed >= 0:
                    return parsed
    except Exception:
        pass

    if _plugin_db is not None:
        for attr_name in ("get_buttondel", "get_autodelete"):
            if hasattr(_plugin_db, attr_name):
                try:
                    val = await getattr(_plugin_db, attr_name)()
                    if val is not None and not isinstance(val, bool):
                        parsed = int(str(val).strip())
                        if parsed >= 0:
                            return parsed
                except Exception:
                    pass

    for source in (temp, info):
        for k in (
            "BUTTON_AUTO_DELETE",
            "BUTTON_DEL",
            "BUTTON_DELETE_TIME",
            "AUTO_DELETE_TIME",
            "FILE_AUTO_DELETE",
            "IMDB_DELETETIME",
            "AUTO_DELETE",
        ):
            val = getattr(source, k, None)
            if val is not None and not isinstance(val, bool):
                try:
                    parsed = int(str(val).strip())
                    if parsed > 0:
                        return 300 if parsed < 10 else parsed
                except Exception:
                    continue

    return default_time


# ============================================================
# 👑 SMART AUTHORIZATION & UNBREAKABLE CONNECTION ENGINE
# ============================================================
def get_admin_list():
    raw_admins = getattr(info, "ADMINS", [])
    if isinstance(raw_admins, (str, int)):
        raw_admins = str(raw_admins).replace(",", " ").split()
    elif isinstance(raw_admins, (list, tuple, set)):
        raw_admins = list(raw_admins)
    else:
        raw_admins = []
    return [int(x) for x in raw_admins if str(x).strip().lstrip("-").isdigit()]


async def is_global_admin(user_id: int) -> bool:
    if not user_id:
        return False
    return int(user_id) in get_admin_list()


async def is_user_banned(user_id: int) -> bool:
    if not user_id:
        return False
    if hasattr(temp, "BANNED_USERS") and int(user_id) in temp.BANNED_USERS:
        return True
    if _plugin_db is not None and hasattr(_plugin_db, "is_banned"):
        try:
            return bool(await _plugin_db.is_banned(int(user_id)))
        except Exception:
            pass
    return False


async def get_active_connection(user_id: str) -> Optional[int]:
    uid_str = str(user_id)

    if _BOT_DB is not None:
        try:
            doc = await _BOT_DB["active_connections"].find_one({"user_id": uid_str})
            if doc and doc.get("group_id"):
                return int(doc["group_id"])
        except Exception:
            pass

    try:
        from database.connections_mdb import active_connection

        conn = await active_connection(uid_str)
        if conn:
            return int(conn)
    except Exception:
        pass

    try:
        from database.connections_mdb import all_connections, if_active

        groupids = await all_connections(uid_str)
        if groupids:
            for gid in groupids:
                if await if_active(uid_str, str(gid)):
                    return int(gid)
            return int(groupids[-1])
    except Exception:
        pass

    if _BOT_DB is not None:
        try:
            doc = await _BOT_DB["CONNECTION"].find_one({"_id": uid_str})
            if doc and doc.get("active_group"):
                return int(doc["active_group"])
        except Exception:
            pass

    return None


async def get_target_chat(client: Client, message: Message) -> Optional[int]:
    if message.chat.type == enums.ChatType.PRIVATE:
        if not message.from_user:
            return None
        return await get_active_connection(str(message.from_user.id))
    return message.chat.id


async def verify_admin(
    client: Client, message: Message, target_chat_id: Optional[int] = None
) -> bool:
    uid = (
        message.from_user.id
        if message.from_user
        else getattr(message.sender_chat, "id", 0)
    )
    if await is_global_admin(uid):
        return True

    if message.chat.type == enums.ChatType.PRIVATE:
        if not target_chat_id:
            return False
        try:
            member = await client.get_chat_member(int(target_chat_id), uid)
            return member.status in [
                enums.ChatMemberStatus.ADMINISTRATOR,
                enums.ChatMemberStatus.OWNER,
            ]
        except Exception:
            return False

    if message.chat.type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
        if message.sender_chat and message.sender_chat.id == message.chat.id:
            return True
        if message.from_user:
            try:
                member = await client.get_chat_member(message.chat.id, uid)
                return member.status in [
                    enums.ChatMemberStatus.ADMINISTRATOR,
                    enums.ChatMemberStatus.OWNER,
                ]
            except Exception:
                return False
    return False


async def safe_save_filter(group_id, keyword, reply_text, btn, fileid, alert="[]"):
    try:
        params = list(inspect.signature(add_filter).parameters.keys())
        if len(params) >= 6 and params[4] == "alert":
            await add_filter(group_id, keyword, reply_text, btn, alert, fileid)
        else:
            await add_filter(group_id, keyword, reply_text, btn, fileid, alert)
    except Exception:
        await add_filter(group_id, keyword, reply_text, btn, fileid, alert)


# ============================================================
# 🧠 ADVANCED FILTER STATE MANAGEMENT
# ============================================================
def get_filter_state(key: str) -> dict:
    state = FILTER_STATE_CACHE.get(key)
    if not state or not isinstance(state, dict):
        return {
            "lang": None,
            "qual": None,
            "year": None,
            "season": None,
            "ep": None,
            "sort": "rel",
            "from_dym": False,
        }
    return state


def set_filter_state(
    key: str,
    lang: Optional[str] = "__keep__",
    qual: Optional[str] = "__keep__",
    year: Optional[str] = "__keep__",
    season: Optional[str] = "__keep__",
    ep: Optional[str] = "__keep__",
    sort: Optional[str] = "__keep__",
    from_dym: Optional[bool] = None,
):
    prev = get_filter_state(key)
    FILTER_STATE_CACHE.set(
        key,
        {
            "lang": prev.get("lang") if lang == "__keep__" else lang,
            "qual": prev.get("qual") if qual == "__keep__" else qual,
            "year": prev.get("year") if year == "__keep__" else year,
            "season": prev.get("season") if season == "__keep__" else season,
            "ep": prev.get("ep") if ep == "__keep__" else ep,
            "sort": prev.get("sort", "rel") if sort == "__keep__" else sort,
            "from_dym": prev.get("from_dym", False) if from_dym is None else from_dym,
        },
    )


def build_effective_search_query(base_query: str, state: dict) -> str:
    parts = [base_query]
    lang_code = state.get("lang")
    qual_val = state.get("qual")
    year_val = state.get("year")
    season_val = state.get("season")
    ep_val = state.get("ep")

    if lang_code and lang_code in LANG_MAP:
        parts.append(LANG_MAP[lang_code].lower())
    if qual_val:
        parts.append(qual_val.lower())
    if year_val:
        parts.append(str(year_val))
    if season_val:
        parts.append(season_val.lower())
    if ep_val:
        parts.append(ep_val.lower())
    return " ".join(p for p in parts if p).strip()


# ============================================================
# 🔮 ULTRA-ACCURATE MULTI-STAGE SEARCH & SUGGESTION ENGINE
# ============================================================
def sanitize_search_query(text: str, allow_translit: bool = True) -> str:
    if not text:
        return ""
    if allow_translit and has_indic_script(text):
        text = transliterate_indic_to_english(text)

    raw_q = _URL_MENTION_RE.sub("", text.strip().lower())
    basic_q = _MULTI_SPACE_RE.sub(" ", _NON_ALNUM_RE.sub(" ", raw_q)).strip()

    q = _STRIP_NOISE_RE.sub("", raw_q)
    q = _NON_ALNUM_RE.sub(" ", q)
    try:
        active_stops = get_stopwords()
        if active_stops:
            q = re.sub(
                r"\b("
                + "|".join(re.escape(w) for w in active_stops if w.strip())
                + r")\b",
                " ",
                q,
                flags=re.IGNORECASE,
            )
    except Exception:
        pass
    cleaned = _MULTI_SPACE_RE.sub(" ", q).strip()
    return cleaned if cleaned else basic_q


def extract_inline_filters(
    raw_text: str,
) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str], Optional[str]]:
    detected_lang = None
    detected_qual = None
    detected_year = None
    detected_season = None
    detected_ep = None

    for code, pattern in LANG_PATTERNS.items():
        if pattern.search(raw_text):
            detected_lang = code
            break
    for qual, pattern in QUAL_PATTERNS.items():
        if pattern.search(raw_text):
            detected_qual = qual
            break
    if yr_match := YEAR_REGEX_EXTRACT.search(raw_text):
        detected_year = yr_match.group(1)
    for scode, pattern in SEASON_PATTERNS.items():
        if pattern.search(raw_text):
            detected_season = scode
            break
    for ecode, pattern in EPISODE_PATTERNS.items():
        if pattern.search(raw_text):
            detected_ep = ecode
            break
    return detected_lang, detected_qual, detected_year, detected_season, detected_ep


async def safe_search_db(query: str, max_results: int = 10, offset: int = 0):
    try:
        return await get_search_results(
            query, max_results=max_results, offset=offset, filter=True
        )
    except TypeError:
        return await get_search_results(query, max_results=max_results, offset=offset)
    except Exception as e:
        logger.error(f"DB search error for '{query}': {e}")
        return [], 0, 0


def _file_text(file_obj) -> str:
    fname = (
        file_obj.get("file_name", "")
        if isinstance(file_obj, dict)
        else getattr(file_obj, "file_name", "")
    )
    fcap = (
        file_obj.get("caption", "")
        if isinstance(file_obj, dict)
        else getattr(file_obj, "caption", "")
    )
    return f"{fname or ''} {fcap or ''}".lower()


def _score_file_relevance(file_obj, query_str: str) -> Tuple[int, int]:
    fname = str(
        file_obj.get("file_name", "")
        if isinstance(file_obj, dict)
        else getattr(file_obj, "file_name", "")
    ).lower()
    fsize = int(
        file_obj.get("file_size", 0)
        if isinstance(file_obj, dict)
        else getattr(file_obj, "file_size", 0)
    )
    clean_fname = _MULTI_SPACE_RE.sub(" ", _NON_ALNUM_RE.sub(" ", fname)).strip()

    q_lower = query_str.lower().strip()
    tokens = [t for t in q_lower.split() if t]
    score = 0

    if clean_fname.startswith(q_lower):
        score += 120
    elif re.search(rf"\b{re.escape(q_lower)}\b", clean_fname):
        score += 90
    elif q_lower in clean_fname:
        score += 60

    if tokens:
        matched_tokens = sum(
            1 for t in tokens if re.search(rf"\b{re.escape(t)}\b", clean_fname)
        )
        if matched_tokens == len(tokens):
            score += 50
        else:
            score += matched_tokens * 15

    return (score, fsize)


def _sort_files(files: list, base_query: str, sort_mode: str) -> None:
    if sort_mode == "asc":
        files.sort(
            key=lambda x: int(
                x.get("file_size", 0)
                if isinstance(x, dict)
                else getattr(x, "file_size", 0)
            )
        )
    elif sort_mode == "desc":
        files.sort(
            key=lambda x: int(
                x.get("file_size", 0)
                if isinstance(x, dict)
                else getattr(x, "file_size", 0)
            ),
            reverse=True,
        )
    else:
        files.sort(key=lambda x: _score_file_relevance(x, base_query), reverse=True)


async def get_movie_pool(base_query: str) -> list:
    """Fetches and caches up to 250 files for a movie so filtering & dynamic menus are instant."""
    ck = base_query.lower().strip()
    cached = POOL_SEARCH_CACHE.get(ck)
    if cached is not None:
        return cached
    pool, _, _ = await safe_search_db(base_query, max_results=250, offset=0)
    if pool:
        POOL_SEARCH_CACHE.set(ck, pool)
    return pool or []


async def get_available_attributes(base_query: str) -> Dict[str, Set[str]]:
    """Scans the movie pool to discover which languages, qualities, years, seasons, and episodes exist."""
    pool = await get_movie_pool(base_query)
    avail: Dict[str, Set[str]] = {
        "langs": set(),
        "quals": set(),
        "years": set(),
        "seasons": set(),
        "eps": set(),
    }
    if not pool:
        return avail

    for f in pool:
        txt = _file_text(f)
        for code, pat in LANG_PATTERNS.items():
            if pat.search(txt):
                avail["langs"].add(code)
        for qual, pat in QUAL_PATTERNS.items():
            if pat.search(txt):
                avail["quals"].add(qual)
        for yr in YEAR_REGEX_EXTRACT.findall(txt):
            avail["years"].add(yr)
        for scode, pat in SEASON_PATTERNS.items():
            if pat.search(txt):
                avail["seasons"].add(scode)
        for ecode, pat in EPISODE_PATTERNS.items():
            if pat.search(txt):
                avail["eps"].add(ecode)

    return avail


async def smart_filtered_search(
    base_query: str, state: dict, max_results: int = 10, offset: int = 0
) -> Tuple[list, int, int]:
    lang_code = state.get("lang")
    qual_val = state.get("qual")
    year_val = state.get("year")
    season_val = state.get("season")
    ep_val = state.get("ep")
    sort_mode = state.get("sort", "rel")

    has_filters = any([lang_code, qual_val, year_val, season_val, ep_val])

    if not has_filters and sort_mode == "rel":
        files, next_offset, total = await safe_search_db(
            base_query, max_results=max_results, offset=offset
        )
        _sort_files(files, base_query, sort_mode)
        return files, next_offset, total

    if has_filters and sort_mode == "rel":
        effective_query = build_effective_search_query(base_query, state)
        direct_files, next_offset, total = await safe_search_db(
            effective_query, max_results=max_results, offset=offset
        )
        if direct_files:
            _sort_files(direct_files, base_query, sort_mode)
            return direct_files, next_offset, total

    pool = await get_movie_pool(base_query)
    if not pool:
        return [], 0, 0

    lang_regex = LANG_PATTERNS.get(lang_code) if lang_code else None
    qual_regex = QUAL_PATTERNS.get(qual_val) if qual_val else None
    season_regex = SEASON_PATTERNS.get(season_val) if season_val else None
    ep_regex = EPISODE_PATTERNS.get(ep_val) if ep_val else None
    year_regex = re.compile(rf"\b{re.escape(str(year_val))}\b") if year_val else None

    matched = []
    for f in pool:
        combined_txt = _file_text(f)
        if lang_regex and not lang_regex.search(combined_txt):
            continue
        if qual_regex and not qual_regex.search(combined_txt):
            continue
        if year_regex and not year_regex.search(combined_txt):
            continue
        if season_regex and not season_regex.search(combined_txt):
            continue
        if ep_regex and not ep_regex.search(combined_txt):
            continue
        matched.append(f)

    _sort_files(matched, base_query, sort_mode)
    total_matched = len(matched)
    sliced = matched[offset : offset + max_results]
    new_next_offset = (
        offset + max_results if (offset + max_results) < total_matched else 0
    )
    return sliced, new_next_offset, total_matched


def _extract_clean_movie_title(raw_filename: str) -> str:
    """Extracts a clean movie title without audio/codec suffixes like 'Aac 40', 'Dd5 1', 'Ddp5'."""
    if not raw_filename:
        return ""
    s = re.sub(r"https?://\S+|t\.me/\S+|@\w+|\[[^\]]*\]|\([^)]*\)", " ", raw_filename)
    s = re.sub(r"[_.-]", " ", s)
    s = _TITLE_SPLIT_RE.split(s)[0]
    s = _NON_ALNUM_RE.sub(" ", s)
    s = re.sub(r"\b(?!(?:19|20)\d{2}\b)\d{1,3}\b$", "", s.strip())
    s = _MULTI_SPACE_RE.sub(" ", s).strip()
    if len(s) < 2:
        return sanitize_search_query(raw_filename)
    words = s.split()
    return " ".join(words[:5]).lower()


async def get_cached_db_titles() -> List[str]:
    db_titles = FUZZY_TITLES_CACHE.get("titles")
    if db_titles is not None:
        return db_titles

    try:
        media_col = getattr(_Media, "collection", _Media)
        sample_docs = (
            await media_col.find({}, {"file_name": 1})
            .sort("_id", -1)
            .limit(4500)
            .to_list(length=4500)
        )
        title_set = set()
        for d in sample_docs:
            fn = d.get("file_name", "")
            if not fn:
                continue
            clean_t = _extract_clean_movie_title(fn)
            if clean_t and len(clean_t) >= 2:
                title_set.add(clean_t)
                no_yr = YEAR_REGEX_EXTRACT.sub("", clean_t).strip()
                no_yr = _MULTI_SPACE_RE.sub(" ", no_yr)
                if no_yr and len(no_yr) >= 2:
                    title_set.add(no_yr)

        db_titles = sorted(title_set)
        FUZZY_TITLES_CACHE.set("titles", db_titles)
        return db_titles
    except Exception as e:
        logger.error(f"get_cached_db_titles error: {e}")
        return []


# ============================================================
# 💡 "DID YOU MEAN?" MULTI-CHOICE SUGGESTIONS FINDER
# ============================================================
def _consonant_skeleton(s: str) -> str:
    s_clean = re.sub(r"[^a-z0-9]", "", s.lower())
    s_clean = re.sub(r"(.)\1+", r"\1", s_clean)
    if len(s_clean) <= 2:
        return s_clean
    return s_clean[0] + re.sub(r"[aeiou]", "", s_clean[1:])


async def get_did_you_mean_suggestions(
    query: str, max_suggestions: int = 5, allow_translit: bool = True
) -> List[str]:
    clean_q = sanitize_search_query(query, allow_translit=allow_translit)
    if not clean_q:
        return []

    db_titles = await get_cached_db_titles()
    if not db_titles:
        return []

    q_lower = clean_q.lower()
    q_skel = _consonant_skeleton(q_lower)
    q_tokens = q_lower.split()

    scored_candidates: List[Tuple[float, str]] = []

    for title in db_titles:
        t_lower = title.lower().strip()
        if not t_lower:
            continue

        ratio = difflib.SequenceMatcher(None, q_lower, t_lower).ratio()

        t_tokens = t_lower.split()
        first_word_ratio = (
            difflib.SequenceMatcher(None, q_tokens[0], t_tokens[0]).ratio()
            if (q_tokens and t_tokens)
            else 0.0
        )

        t_skel = _consonant_skeleton(
            t_tokens[0] if len(q_tokens) == 1 and t_tokens else t_lower
        )
        skel_ratio = (
            difflib.SequenceMatcher(None, q_skel, t_skel).ratio()
            if (q_skel and t_skel)
            else 0.0
        )

        prefix_bonus = (
            0.15 if (t_lower.startswith(q_lower[:3]) and len(q_lower) >= 3) else 0.0
        )

        best_score = (
            max(ratio, first_word_ratio * 0.95, skel_ratio * 0.92) + prefix_bonus
        )
        if best_score >= 0.46:
            scored_candidates.append((best_score, t_lower))

    scored_candidates.sort(key=lambda x: x[0], reverse=True)

    unique_suggestions: List[str] = []
    seen_roots = set()

    for _, cand in scored_candidates:
        if len(unique_suggestions) >= max_suggestions:
            break
        root_key = re.sub(r"\b\d+\b", "", cand).strip()
        root_key = _MULTI_SPACE_RE.sub(" ", root_key)
        if not root_key or root_key in seen_roots:
            continue

        c_files, _, _ = await safe_search_db(cand, max_results=1, offset=0)
        if not c_files and root_key != cand:
            c_files, _, _ = await safe_search_db(root_key, max_results=1, offset=0)
            if c_files:
                cand = root_key

        if c_files:
            seen_roots.add(root_key)
            unique_suggestions.append(cand)

    return unique_suggestions


def _build_dym_view(
    mention: str, raw_search: str, req: int, key: str, suggestions: List[str]
) -> Tuple[str, InlineKeyboardMarkup]:
    safe_typed = html.escape(raw_search.strip()) if raw_search else "Movie"
    dym_text = (
        f"<b>Hᴇʏ {mention} 👋🏻\n\n"
        f"🚫 Nᴏ Eхᴀᴄᴛ Mᴀᴛᴄʜ Fᴏʀ : <code>{safe_typed}</code>\n\n"
        f"💡 Dɪᴅ Yᴏᴜ Mᴇᴀɴ Oɴᴇ Oғ Tʜᴇsᴇ Mᴏᴠɪᴇs? 👇</b>"
    )
    dym_btns = []
    row = []
    for idx, sug_title in enumerate(suggestions):
        row.append(
            create_btn(
                text=f"🎬 {sug_title.title()}",
                callback_data=f"dym#{req}#{key}#{idx}",
            )
        )
        if len(row) == 2:
            dym_btns.append(row)
            row = []
    if row:
        dym_btns.append(row)

    google_q = urllib.parse.quote_plus(f"{raw_search.strip()} movie")
    dym_btns.append(
        [
            create_btn(
                text="🔎 Check Spelling on Google",
                url=f"https://www.google.com/search?q={google_q}",
            ),
            create_btn(
                text="❌ Close",
                callback_data=f"fclose#{req}",
                style=BTN_DANGER,
            ),
        ]
    )
    return dym_text, InlineKeyboardMarkup(dym_btns)


async def god_tier_search(
    query: str, allow_translit: bool = True, allow_fuzzy: bool = True
) -> Tuple[list, int, int, str, bool]:
    """
    7-Stage Deep Search Engine:
    1. Indic Phonetic Variants
    2. Exact Sanitized Query
    3. Raw Alphanumeric Query
    4. Year-Stripped Query
    5. Token-Subset Progressive Fallback (handles extra words / actor names)
    6. Prefix / First-Keyword Anchor Match
    7. Fuzzy SequenceMatcher & Consonant Skeleton Match
    """
    was_transliterated = bool(allow_translit and has_indic_script(query))
    translit_variants = (
        generate_phonetic_variants(transliterate_indic_to_english(query))
        if was_transliterated
        else []
    )

    clean_query = sanitize_search_query(query, allow_translit=allow_translit)
    if not clean_query and not translit_variants:
        return [], 0, 0, query, False

    # Stage 1: Indic Script Phonetic Variants
    if translit_variants:
        for variant in translit_variants:
            v_clean = sanitize_search_query(variant, allow_translit=False)
            if not v_clean:
                continue
            files, offset, total = await safe_search_db(
                v_clean, max_results=10, offset=0
            )
            if files:
                files.sort(
                    key=lambda x: _score_file_relevance(x, v_clean), reverse=True
                )
                return files, offset, total, v_clean, True

    is_short_query = len(clean_query) <= 2

    # Stage 2: Direct Sanitized Query
    files, offset, total = await safe_search_db(clean_query, max_results=10, offset=0)
    if files:
        files.sort(key=lambda x: _score_file_relevance(x, clean_query), reverse=True)
        return files, offset, total, clean_query, was_transliterated

    # Stage 3: Raw Alphanumeric Query
    raw_alnum = _MULTI_SPACE_RE.sub(" ", _NON_ALNUM_RE.sub(" ", query.lower())).strip()
    if raw_alnum and raw_alnum != clean_query:
        files, offset, total = await safe_search_db(raw_alnum, max_results=10, offset=0)
        if files:
            files.sort(key=lambda x: _score_file_relevance(x, raw_alnum), reverse=True)
            return files, offset, total, raw_alnum, was_transliterated

    # Stage 4: Year-Stripped Query
    no_year_query = YEAR_REGEX_EXTRACT.sub("", clean_query).strip()
    no_year_query = _MULTI_SPACE_RE.sub(" ", no_year_query)
    if no_year_query and no_year_query != clean_query and len(no_year_query) > 2:
        files, offset, total = await safe_search_db(
            no_year_query, max_results=10, offset=0
        )
        if files:
            files.sort(
                key=lambda x: _score_file_relevance(x, no_year_query), reverse=True
            )
            return files, offset, total, no_year_query, was_transliterated

    # Stage 5: Progressive Multi-Word Token Reduction (e.g. "kantara chapter 1 trailer" -> "kantara chapter 1")
    tokens = [t for t in no_year_query.split() if len(t) >= 2]
    if len(tokens) >= 2:
        for length in range(len(tokens) - 1, 0, -1):
            sub_q = " ".join(tokens[:length])
            if len(sub_q) < 3:
                continue
            files, offset, total = await safe_search_db(sub_q, max_results=10, offset=0)
            if files:
                files.sort(
                    key=lambda x: _score_file_relevance(x, clean_query), reverse=True
                )
                return files, offset, total, sub_q, True

    if is_short_query or not allow_fuzzy:
        return [], 0, 0, query, False

    # Stage 6 & 7: Fuzzy Title + Consonant Skeleton Correction
    try:
        db_titles = await get_cached_db_titles()
        if matches := difflib.get_close_matches(
            no_year_query or clean_query, db_titles, n=2, cutoff=0.70
        ):
            for corrected_query in matches:
                c_files, c_offset, c_total = await safe_search_db(
                    corrected_query, max_results=10, offset=0
                )
                if c_files:
                    c_files.sort(
                        key=lambda x: _score_file_relevance(x, corrected_query),
                        reverse=True,
                    )
                    return c_files, c_offset, c_total, corrected_query, True
    except Exception as e:
        logger.error(f"Fuzzy search fallback error: {e}")

    return [], 0, 0, clean_query or query, False


# ============================================================
# 🧩 KEYBOARD BUILDER FOR AUTO-FILTER RESULTS
# ============================================================
async def build_result_buttons(
    files: list,
    offset: int,
    total_results: int,
    req: int,
    key: str,
    settings: dict,
    bot_username: str,
    current_offset: int = 0,
) -> List[List[InlineKeyboardButton]]:
    pre = "filep" if settings.get("file_secure", False) else "file"
    clean_words = await get_clean_words()
    state = get_filter_state(key)

    active_lang = LANG_MAP.get(state.get("lang") or "")
    active_qual = state.get("qual")
    active_year = state.get("year")
    active_season = state.get("season")
    active_ep = state.get("ep")
    sort_mode = state.get("sort", "rel")

    has_active_filter = any(
        [active_lang, active_qual, active_year, active_season, active_ep]
    ) or (sort_mode != "rel")
    from_dym = bool(state.get("from_dym") and SUGGESTIONS_CACHE.get(key))

    lang_btn_text = f"🔊 {active_lang}" if active_lang else "🔊"
    qual_btn_text = f"🎥 {active_qual}" if active_qual else "🎥"
    seas_btn_text = f"📺 {active_season.upper()}" if active_season else "📺"
    ep_btn_text = f"🎞️ {active_ep.upper()}" if active_ep else "🎞️"
    year_btn_text = f"📅 {active_year}" if active_year else "📅"
    sort_btn_text = {"rel": "🔃 Sort", "asc": "⬆️ Size", "desc": "⬇️ Size"}.get(
        sort_mode, "🔃 Sort"
    )

    btn = [
        # Row 1: Blue button: 🎖️Lᴀᴛᴇsᴛ Mᴏᴠɪᴇ Uᴘᴅᴀᴛᴇs🎖️
        [
            create_btn(
                text="🎖️Lᴀᴛᴇsᴛ Mᴏᴠɪᴇ Uᴘᴅᴀᴛᴇs🎖️",
                url="https://t.me/+8Mw-Y-fYN6hiZWZl",
                style=BTN_PRIMARY,
            )
        ],
        # Row 2: Language, Quality, Season, Year, Extra Links (No colour)
        [
            create_btn(
                text=lang_btn_text,
                callback_data=f"flang#{req}#{key}",
            ),
            create_btn(
                text=qual_btn_text,
                callback_data=f"fqual#{req}#{key}",
            ),
            create_btn(
                text=seas_btn_text,
                callback_data=f"fseas#{req}#{key}",
            ),
            create_btn(
                text=year_btn_text,
                callback_data=f"fyear#{req}#{key}",
            ),
        ],
        # Row 3: Episode Filter, Sort Toggle & Extra Channel Buttons
        [
            create_btn(
                text=ep_btn_text,
                callback_data=f"feps#{req}#{key}",
            ),
            create_btn(
                text=sort_btn_text,
                callback_data=f"fsort#{req}#{key}",
            ),
            create_btn(
                text="🎞",
                url=EXTRA_BTN_1_URL,
            ),
            create_btn(
                text="🔞",
                url=EXTRA_BTN_2_URL,
            ),
        ],
    ]

    if has_active_filter:
        btn.append(
            [
                create_btn(
                    text="⬅️ Back to Normal Results",
                    callback_data=f"freset#{req}#{key}",
                )
            ]
        )

    # Attach any active Promotional Links configured via /addpromo
    promos = await get_active_promos()
    for p in promos[:2]:
        btn.append([create_btn(text=p["text"], url=p["url"])])

    for file in files:
        file_id = str(
            file.get("file_id", "")
            if isinstance(file, dict)
            else getattr(file, "file_id", "")
        )
        raw_name = str(
            file.get("file_name", "Unknown")
            if isinstance(file, dict)
            else getattr(file, "file_name", "Unknown")
        )
        file_size = int(
            file.get("file_size", 0)
            if isinstance(file, dict)
            else getattr(file, "file_size", 0)
        )

        # Smart compact badges for Subtitles & HEVC
        badges = []
        if _HEVC_DETECT_RE.search(raw_name):
            badges.append("HEVC")
        if _SUBTITLE_DETECT_RE.search(raw_name):
            badges.append("ESub")
        badge_prefix = f"[{'/'.join(badges)}] " if badges else ""

        display_name = clean_filename(raw_name, clean_words)
        size_str = get_size(file_size)
        url_payload = f"https://t.me/{bot_username}?start={pre}_{file_id}"

        if settings.get("button", False):
            btn.append(
                [
                    create_btn(
                        text=f"{size_str} | {badge_prefix}{display_name}",
                        url=url_payload,
                    )
                ]
            )
        else:
            btn.append(
                [
                    create_btn(
                        text=f"{badge_prefix}{display_name}",
                        url=url_payload,
                    ),
                    create_btn(text=f"{size_str}", url=url_payload),
                ]
            )

    try:
        total_results = int(total_results)
    except Exception:
        total_results = len(files)

    total_pages = math.ceil(total_results / 10) if total_results > 0 else 1
    current_page = math.ceil(current_offset / 10) + 1 if current_offset > 0 else 1
    off_set = (
        0
        if 0 < current_offset <= 10
        else None if current_offset == 0 else current_offset - 10
    )
    # Clicking the page button opens the interactive Page Jump Picker if total_pages > 1
    page_cb = (
        f"fpages#{req}#{key}#{current_page}#{total_pages}"
        if total_pages > 1
        else f"pages#{current_page}#{total_pages}#{total_results}"
    )

    nav_row: List[InlineKeyboardButton] = []

    if off_set is not None:
        nav_row.append(
            create_btn(
                "⬅️ BACK",
                callback_data=f"next_{req}_{key}_{off_set}",
                style=BTN_PRIMARY,
            )
        )
    elif from_dym:
        nav_row.append(
            create_btn(
                "⬅️ Back",
                callback_data=f"dymback#{req}#{key}",
                style=None,
            )
        )

    nav_row.append(
        create_btn(
            text=f"📄 {current_page}/{total_pages}",
            callback_data=page_cb,
            style=BTN_PRIMARY,
        )
    )

    if offset:
        nav_row.append(
            create_btn(
                "NEXT ➡️",
                callback_data=f"next_{req}_{key}_{offset}",
                style=BTN_PRIMARY,
            )
        )

    if from_dym and off_set is not None:
        nav_row.append(
            create_btn(
                "🔙 Choices",
                callback_data=f"dymback#{req}#{key}",
                style=None,
            )
        )
    else:
        nav_row.append(
            create_btn(
                "❌",
                callback_data=f"fclose#{req}",
                style=BTN_DANGER,
            )
        )

    btn.append(nav_row)
    return btn


# ============================================================
# ⏳ RELIABLE AUTO-DELETE ENGINE (GROUP + PM)
# ============================================================
async def _delete_single_message(
    client: Client, chat_id: int, msg_obj: Optional[Message]
):
    if msg_obj is None:
        return
    msg_id = getattr(msg_obj, "id", None) or getattr(msg_obj, "message_id", None)
    try:
        await msg_obj.delete()
        return
    except FloodWait as e:
        await asyncio.sleep(e.value + 1)
        try:
            await msg_obj.delete()
            return
        except Exception:
            pass
    except Exception:
        pass

    if msg_id:
        try:
            await client.delete_messages(chat_id=chat_id, message_ids=msg_id)
        except FloodWait as e:
            await asyncio.sleep(e.value + 1)
            try:
                await client.delete_messages(chat_id=chat_id, message_ids=msg_id)
            except Exception:
                pass
        except Exception:
            pass


async def _auto_delete_worker(
    client: Client, chat_id: int, is_pm: bool, delay: int, *messages
):
    await asyncio.sleep(delay)

    for m in messages:
        if m is not None:
            await _delete_single_message(client, chat_id, m)

    if is_pm:
        notify_text = (
            "<b>Successfully deleted your file, if you want request again in group.</b>"
        )
        markup = (
            _get_deleted_file_notify_keyboard()
            if callable(_get_deleted_file_notify_keyboard)
            else InlineKeyboardMarkup(
                [
                    [
                        create_btn(
                            "Movie Request 📝",
                            url="https://t.me/Sandalwood_Kannada_Group",
                        )
                    ]
                ]
            )
        )
        try:
            await client.send_message(
                chat_id,
                text=notify_text,
                reply_markup=markup,
                parse_mode=enums.ParseMode.HTML,
            )
        except Exception:
            pass


def schedule_auto_delete(
    client: Client, chat_id: int, is_pm: bool, delay: int, *messages
):
    if delay <= 0:
        return
    task = asyncio.create_task(
        _auto_delete_worker(client, chat_id, is_pm, delay, *messages)
    )
    AUTO_DELETE_TASKS.add(task)
    task.add_done_callback(AUTO_DELETE_TASKS.discard)


async def _send_not_found(
    client: Client,
    msg: Message,
    img: Optional[str],
    text: str,
    raw_search: str = "",
    multichoice_on: bool = True,
    autotranslate_on: bool = True,
):
    if RESTRICTED_WRITE_CHATS.get(str(msg.chat.id)):
        return

    k_msg = None
    req = msg.from_user.id if msg.from_user else 0
    key = f"{msg.chat.id}-{msg.id}"

    suggestions = (
        await get_did_you_mean_suggestions(
            raw_search, max_suggestions=5, allow_translit=autotranslate_on
        )
        if (raw_search and multichoice_on)
        else []
    )

    if suggestions:
        SUGGESTIONS_CACHE.set(key, suggestions)
        DYM_QUERY_CACHE.set(key, raw_search.strip())
        mention = msg.from_user.mention if msg.from_user else "User"
        dym_text, dym_markup = _build_dym_view(
            mention, raw_search, req, key, suggestions
        )
        k_msg = await safe_reply_text(
            msg,
            text=dym_text,
            reply_markup=dym_markup,
            parse_mode=enums.ParseMode.HTML,
        )
    else:
        try:
            final_text, final_markup = parse_text_and_markup(text)
        except Exception:
            final_text, final_markup = text, None
        final_text = final_text or "<b>🚫 File not found.</b>"
        if final_markup is None and raw_search:
            google_q = urllib.parse.quote_plus(f"{raw_search.strip()} movie")
            final_markup = InlineKeyboardMarkup(
                [
                    [
                        create_btn(
                            text="🔎 Check Spelling on Google",
                            url=f"https://www.google.com/search?q={google_q}",
                        )
                    ]
                ]
            )
        k_msg = await safe_reply_photo_or_text(
            msg,
            photo=img,
            caption=final_text,
            reply_markup=final_markup,
            parse_mode=enums.ParseMode.HTML,
        )

    delete_timer = await resolve_auto_delete_timer(msg.chat.id, default_time=300)
    if delete_timer > 0 and k_msg:
        schedule_auto_delete(client, msg.chat.id, False, delete_timer, k_msg, msg)


# ============================================================
# 📁 CORE AUTO FILTER ENGINE
# ============================================================
async def auto_filter(client: Client, msg: Message):
    try:
        if (
            not msg
            or not msg.text
            or msg.text.startswith(("/", "!", "#", ".", ",", "?", "@"))
        ):
            return

        if msg.chat and RESTRICTED_WRITE_CHATS.get(str(msg.chat.id)):
            return

        search = _URL_MENTION_RE.sub("", msg.text).strip()
        if not search or len(search) < 2:
            return

        if search.lower() in IGNORE_WORDS_SET:
            return

        autotranslate_on, multichoice_on = await get_feature_flags()

        try:
            b_set = await get_bot_settings() or {}
        except Exception:
            b_set = {}

        try:
            settings = await get_settings(msg.chat.id) or {}
        except Exception:
            settings = {}

        spell_check_on = bool(settings.get("spell_check", True))

        if has_indic_script(search) and not autotranslate_on:
            fnf_img = b_set.get("not_found_img", getattr(info, "NOT_FOUND_IMG", None))
            fnf_txt = b_set.get(
                "not_found_text",
                getattr(info, "NOT_FOUND_MSG", "<b>🚫 File not found.</b>"),
            )
            return await _send_not_found(
                client,
                msg,
                fnf_img,
                fnf_txt,
                raw_search="",
                multichoice_on=False,
                autotranslate_on=False,
            )

        (
            inline_lang,
            inline_qual,
            inline_year,
            inline_season,
            inline_ep,
        ) = extract_inline_filters(search)

        cache_key = (
            f"{search.lower()}|at:{int(autotranslate_on)}|sp:{int(spell_check_on)}"
        )
        cached_data = GLOBAL_SEARCH_CACHE.get(cache_key)

        if cached_data:
            files, offset, total_results, search_query, was_corrected = cached_data
        else:
            files, offset, total_results, search_query, was_corrected = (
                await god_tier_search(
                    search,
                    allow_translit=autotranslate_on,
                    allow_fuzzy=spell_check_on,
                )
            )
            if files:
                GLOBAL_SEARCH_CACHE.set(
                    cache_key,
                    (files, offset, total_results, search_query, was_corrected),
                )

        if not files:
            fnf_img = b_set.get("not_found_img", getattr(info, "NOT_FOUND_IMG", None))
            fnf_txt = b_set.get(
                "not_found_text",
                getattr(info, "NOT_FOUND_MSG", "<b>🚫 File not found.</b>"),
            )
            return await _send_not_found(
                client,
                msg,
                fnf_img,
                fnf_txt,
                raw_search=search,
                multichoice_on=bool(multichoice_on and spell_check_on),
                autotranslate_on=autotranslate_on,
            )

        key = f"{msg.chat.id}-{msg.id}"
        BUTTONS_CACHE.set(key, search_query)

        if any([inline_lang, inline_qual, inline_year, inline_season, inline_ep]):
            inline_state = {
                "lang": inline_lang,
                "qual": inline_qual,
                "year": inline_year,
                "season": inline_season,
                "ep": inline_ep,
                "sort": "rel",
                "from_dym": False,
            }
            f_files, f_offset, f_total = await smart_filtered_search(
                search_query, inline_state, max_results=10, offset=0
            )
            if f_files:
                files, offset, total_results = f_files, f_offset, f_total
                set_filter_state(
                    key,
                    lang=inline_lang,
                    qual=inline_qual,
                    year=inline_year,
                    season=inline_season,
                    ep=inline_ep,
                    sort="rel",
                    from_dym=False,
                )
            else:
                set_filter_state(
                    key,
                    lang=None,
                    qual=None,
                    year=None,
                    season=None,
                    ep=None,
                    sort="rel",
                    from_dym=False,
                )
        else:
            set_filter_state(
                key,
                lang=None,
                qual=None,
                year=None,
                season=None,
                ep=None,
                sort="rel",
                from_dym=False,
            )

        try:
            total_results = int(total_results)
        except Exception:
            total_results = len(files)

        if not getattr(temp, "U_NAME", None):
            me = await client.get_me()
            temp.U_NAME = me.username
            temp.B_NAME = me.first_name
            temp.ME = me.id
        bot_username = temp.U_NAME or "bot"
        mention = msg.from_user.mention if msg.from_user else "User"

        safe_orig_title = html.escape(search.title())
        safe_corr_title = html.escape(search_query.title())
        was_indic = bool(autotranslate_on and has_indic_script(search))

        if was_indic:
            cap = (
                f"<b>Hᴇʏ {mention} 👋🏻\n\n"
                f"🔤 Tʀᴀɴsʟɪᴛᴇʀᴀᴛᴇᴅ : <code>{html.escape(search)}</code> ➔ <code>{safe_corr_title}</code>\n"
                f"➤ Yᴏᴜʀ Fɪʟᴇꜱ Rᴇᴀᴅʏ Nᴏᴡ 👇</b>"
            )
        elif was_corrected:
            cap = (
                f"<b>Hᴇʏ {mention} 👋🏻\n\n"
                f"🪄 Aᴜᴛᴏ-Cᴏʀʀᴇᴄᴛᴇᴅ : <del>{safe_orig_title}</del> ➔ <code>{safe_corr_title}</code>\n"
                f"➤ Yᴏᴜʀ Fɪʟᴇꜱ Rᴇᴀᴅʏ Nᴏᴡ 👇</b>"
            )
        else:
            cap = (
                f"<b>Hᴇʏ {mention} 👋🏻\n\n"
                f"➤ Tɪᴛʟᴇ : <code>{safe_corr_title}</code>\n"
                f"➤ Yᴏᴜʀ Fɪʟᴇꜱ Rᴇᴀᴅʏ Nᴏᴡ 👇</b>"
            )

        req = msg.from_user.id if msg.from_user else 0

        btn = await build_result_buttons(
            files=files,
            offset=offset,
            total_results=total_results,
            req=req,
            key=key,
            settings=settings,
            bot_username=bot_username,
            current_offset=0,
        )

        default_markup = InlineKeyboardMarkup(btn)
        try:
            final_caption, final_markup = parse_text_and_markup(cap, default_markup)
            final_caption = final_caption or cap
            final_markup = final_markup or default_markup
        except Exception:
            final_caption, final_markup = cap, default_markup

        auto_img = b_set.get("auto_img", getattr(info, "AUTO_IMG", None))
        m = await safe_reply_photo_or_text(
            msg,
            photo=auto_img,
            caption=final_caption,
            reply_markup=final_markup,
            parse_mode=enums.ParseMode.HTML,
        )
        if not m:
            return

        delete_timer = await resolve_auto_delete_timer(msg.chat.id, default_time=300)
        if delete_timer > 0:
            schedule_auto_delete(client, msg.chat.id, False, delete_timer, m, msg)

    except Exception as e:
        logger.error(f"Fatal error in auto_filter: {e}")


# ============================================================
# ⚡ UNIFIED GROUP MESSAGE HANDLER (CUSTOM FILTERS + AUTO FILTER)
# ============================================================
@Client.on_message(filters.group & filters.text & filters.incoming)
async def give_filter(client: Client, message: Message):
    if not message.text or message.text.startswith(("/", "!", "#", ".", ",", "?", "@")):
        return

    if message.chat and RESTRICTED_WRITE_CHATS.get(str(message.chat.id)):
        return

    if getattr(info, "REPAIR_MODE", False) and not await verify_admin(
        client, message, message.chat.id
    ):
        return

    user_id = message.from_user.id if message.from_user else 0
    if user_id and await is_user_banned(user_id):
        return

    if user_id != 0:
        if (last_req := USER_LAST_REQ.get(str(user_id))) and (
            time.time() - last_req
        ) < 1.5:
            return
        USER_LAST_REQ.set(str(user_id), time.time())

    try:
        matched_manual = await manual_filters(client, message)
        if matched_manual:
            return
        await auto_filter(client, message)
    except Exception as e:
        logger.error(f"give_filter top-level error: {e}")


# ============================================================
# ⚙️ AUTO-TRANSLATE & MULTI-CHOICE ADMIN COMMANDS + CALLBACKS
# ============================================================
def _build_feature_toggle_markup(
    feat_key: str, is_enabled: bool
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                create_btn(
                    text=f"{'✅ ' if is_enabled else ''}Enable",
                    callback_data=f"pmfeat#{feat_key}#on",
                ),
                create_btn(
                    text=f"{'🚫 ' if not is_enabled else ''}Disable",
                    callback_data=f"pmfeat#{feat_key}#off",
                ),
            ]
        ]
    )


@Client.on_message(
    filters.command(["autotranslate", "enautotranslate", "diautotranslate"])
    & filters.incoming,
    group=-2,
)
async def autotranslate_cmd_handler(client: Client, message: Message):
    target_chat_id = await get_target_chat(client, message)
    if not await verify_admin(client, message, target_chat_id):
        return await safe_reply_text(
            message,
            "❌ <b>Unauthorized:</b> Admin access required.",
            parse_mode=enums.ParseMode.HTML,
        )

    cmd = message.command[0].lower()
    cur_trans, _ = await get_feature_flags(force_refresh=True)

    if cmd == "enautotranslate":
        new_state = True
    elif cmd == "diautotranslate":
        new_state = False
    else:
        if len(message.command) > 1:
            arg = message.command[1].strip().lower()
            if arg in ["on", "enable", "true", "yes", "1"]:
                new_state = True
            elif arg in ["off", "disable", "false", "no", "0"]:
                new_state = False
            else:
                new_state = not cur_trans
        else:
            new_state = not cur_trans

    await set_feature_flag("autotranslate", new_state)
    status_badge = "🟢 ENABLED" if new_state else "🔴 DISABLED"
    out_msg = await safe_reply_text(
        message,
        f"🔤 <b>Auto-Translate (Indic Script ➔ English):</b> <code>{status_badge}</code>\n\n"
        f"<i>When enabled, movie names typed in Kannada, Hindi, Telugu, Tamil, or Malayalam script are automatically transliterated to English!</i>",
        reply_markup=_build_feature_toggle_markup("autotranslate", new_state),
        parse_mode=enums.ParseMode.HTML,
    )
    delete_timer = await resolve_auto_delete_timer(message.chat.id, default_time=300)
    schedule_auto_delete(client, message.chat.id, False, delete_timer, out_msg, message)


@Client.on_message(
    filters.command(["multichoice", "enmultichoice", "dimultichoice"])
    & filters.incoming,
    group=-2,
)
async def multichoice_cmd_handler(client: Client, message: Message):
    target_chat_id = await get_target_chat(client, message)
    if not await verify_admin(client, message, target_chat_id):
        return await safe_reply_text(
            message,
            "❌ <b>Unauthorized:</b> Admin access required.",
            parse_mode=enums.ParseMode.HTML,
        )

    cmd = message.command[0].lower()
    _, cur_mc = await get_feature_flags(force_refresh=True)

    if cmd == "enmultichoice":
        new_state = True
    elif cmd == "dimultichoice":
        new_state = False
    else:
        if len(message.command) > 1:
            arg = message.command[1].strip().lower()
            if arg in ["on", "enable", "true", "yes", "1"]:
                new_state = True
            elif arg in ["off", "disable", "false", "no", "0"]:
                new_state = False
            else:
                new_state = not cur_mc
        else:
            new_state = not cur_mc

    await set_feature_flag("multichoice", new_state)
    status_badge = "🟢 ENABLED" if new_state else "🔴 DISABLED"
    out_msg = await safe_reply_text(
        message,
        f"💡 <b>Multi-Choice ('Did You Mean?' Suggestions):</b> <code>{status_badge}</code>\n\n"
        f"<i>When enabled, misspelled movie queries display up to 5 clickable movie title suggestions instead of File Not Found!</i>",
        reply_markup=_build_feature_toggle_markup("multichoice", new_state),
        parse_mode=enums.ParseMode.HTML,
    )
    delete_timer = await resolve_auto_delete_timer(message.chat.id, default_time=300)
    schedule_auto_delete(client, message.chat.id, False, delete_timer, out_msg, message)


@Client.on_callback_query(filters.regex(r"^pmfeat#"), group=-2)
async def pm_feature_toggle_callback(bot: Client, query: CallbackQuery):
    uid = query.from_user.id if query.from_user else 0
    if not await is_global_admin(uid):
        if query.message and query.message.chat.type in [
            enums.ChatType.GROUP,
            enums.ChatType.SUPERGROUP,
        ]:
            try:
                member = await bot.get_chat_member(query.message.chat.id, uid)
                if member.status not in [
                    enums.ChatMemberStatus.ADMINISTRATOR,
                    enums.ChatMemberStatus.OWNER,
                ]:
                    return await safe_answer(query, "❌ Admin only!", show_alert=True)
            except Exception:
                return await safe_answer(query, "❌ Admin only!", show_alert=True)
        else:
            return await safe_answer(query, "❌ Admin only!", show_alert=True)

    try:
        _, feat_key, state_str = query.data.split("#", 2)
    except ValueError:
        return await safe_answer(query, "Invalid data!", show_alert=True)

    new_state = state_str == "on"
    await set_feature_flag(feat_key, new_state)
    status_badge = "🟢 ENABLED" if new_state else "🔴 DISABLED"

    if feat_key == "autotranslate":
        text = (
            f"🔤 <b>Auto-Translate (Indic Script ➔ English):</b> <code>{status_badge}</code>\n\n"
            f"<i>When enabled, movie names typed in Kannada, Hindi, Telugu, Tamil, or Malayalam script are automatically transliterated to English!</i>"
        )
    else:
        text = (
            f"💡 <b>Multi-Choice ('Did You Mean?' Suggestions):</b> <code>{status_badge}</code>\n\n"
            f"<i>When enabled, misspelled movie queries display up to 5 clickable movie title suggestions instead of File Not Found!</i>"
        )

    try:
        await query.message.edit_text(
            text=text,
            reply_markup=_build_feature_toggle_markup(feat_key, new_state),
            parse_mode=enums.ParseMode.HTML,
        )
    except (MessageNotModified, MessageIdInvalid, ChatWriteForbidden, Forbidden):
        pass
    await safe_answer(query, f"Updated: {status_badge}")


# ============================================================
# 🌐 DYNAMIC FILTER MENUS, SORT, PAGE JUMP & DYM CALLBACKS
# ============================================================
@Client.on_callback_query(
    filters.regex(
        r"^(flang#|fqual#|fyear#|fseas#|feps#|fsort#|fpages#|fclose#|setlang#|setqual#|setyear#|setseas#|setep#|fback#|freset#|dym#|dymback#)"
    ),
    group=-2,
)
async def filter_menu_callbacks(bot: Client, query: CallbackQuery):
    data = query.data
    parts = data.split("#")
    action = parts[0]

    # ❌ Instant Close Handler
    if action == "fclose":
        req_id = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
        uid = query.from_user.id if query.from_user else 0
        if req_id not in [uid, 0] and not await is_global_admin(uid):
            return await safe_answer(
                query,
                "⚠️ Only the requester or an Admin can close this!",
                show_alert=True,
            )
        await safe_answer(query, "🗑️ Closed!")
        await _delete_single_message(bot, query.message.chat.id, query.message)
        return

    try:
        req = int(parts[1])
        key = parts[2]
    except (IndexError, ValueError):
        return await safe_answer(query, "Invalid button data!", show_alert=True)

    uid = query.from_user.id if query.from_user else 0
    if req not in [uid, 0] and not await is_global_admin(uid):
        return await safe_answer(
            query,
            "⚠️ That's not for you! Request your own movie in the group.",
            show_alert=True,
        )

    # 🔙 User clicked "⬅️ Back" to return to Multi-Choice ("Did You Mean?")
    if action == "dymback":
        suggestions = SUGGESTIONS_CACHE.get(key)
        if not suggestions:
            return await safe_answer(
                query,
                "⌛ Suggestions expired. Please type the movie name again!",
                show_alert=True,
            )
        raw_search = DYM_QUERY_CACHE.get(key) or "Movie"
        mention = query.from_user.mention if query.from_user else "User"
        dym_text, dym_markup = _build_dym_view(
            mention, raw_search, req, key, suggestions
        )
        try:
            if query.message.photo or query.message.video or query.message.document:
                await query.message.edit_caption(
                    caption=dym_text,
                    reply_markup=dym_markup,
                    parse_mode=enums.ParseMode.HTML,
                )
            else:
                await query.message.edit_text(
                    text=dym_text,
                    reply_markup=dym_markup,
                    parse_mode=enums.ParseMode.HTML,
                )
        except (MessageNotModified, MessageIdInvalid, ChatWriteForbidden, Forbidden):
            pass
        return await safe_answer(query, "⬅️ Back to Multi-Choice suggestions!")

    # 💡 User clicked a "Did You Mean?" movie suggestion button
    if action == "dym":
        try:
            sug_idx = int(parts[3])
        except (IndexError, ValueError):
            return await safe_answer(query, "Invalid selection!", show_alert=True)

        suggestions = SUGGESTIONS_CACHE.get(key)
        if not suggestions or sug_idx >= len(suggestions):
            return await safe_answer(
                query,
                "⌛ This suggestion expired. Please type the movie name again!",
                show_alert=True,
            )

        chosen_title = suggestions[sug_idx]
        files, n_offset, total = await safe_search_db(
            chosen_title, max_results=10, offset=0
        )
        if not files:
            return await safe_answer(
                query, "❌ No files found for that suggestion!", show_alert=True
            )

        files.sort(key=lambda x: _score_file_relevance(x, chosen_title), reverse=True)
        BUTTONS_CACHE.set(key, chosen_title)
        set_filter_state(
            key,
            lang=None,
            qual=None,
            year=None,
            season=None,
            ep=None,
            sort="rel",
            from_dym=True,
        )

        settings = await get_settings(query.message.chat.id) or {}
        if not getattr(temp, "U_NAME", None):
            me = await bot.get_me()
            temp.U_NAME = me.username
            temp.B_NAME = me.first_name
            temp.ME = me.id
        bot_username = temp.U_NAME or "bot"

        btn = await build_result_buttons(
            files=files,
            offset=n_offset,
            total_results=total,
            req=req,
            key=key,
            settings=settings,
            bot_username=bot_username,
            current_offset=0,
        )

        mention = query.from_user.mention if query.from_user else "User"
        safe_corr_title = html.escape(chosen_title.title())
        new_cap = (
            f"<b>Hᴇʏ {mention} 👋🏻\n\n"
            f"➤ Tɪᴛʟᴇ : <code>{safe_corr_title}</code>\n"
            f"➤ Yᴏᴜʀ Fɪʟᴇꜱ Rᴇᴀᴅʏ Nᴏᴡ 👇</b>"
        )

        try:
            if query.message.photo or query.message.video or query.message.document:
                await query.message.edit_caption(
                    caption=new_cap,
                    reply_markup=InlineKeyboardMarkup(btn),
                    parse_mode=enums.ParseMode.HTML,
                )
            else:
                await query.message.edit_text(
                    text=new_cap,
                    reply_markup=InlineKeyboardMarkup(btn),
                    parse_mode=enums.ParseMode.HTML,
                )
        except (
            MessageNotModified,
            MessageIdInvalid,
            ButtonUrlInvalid,
            ChatWriteForbidden,
            Forbidden,
        ):
            pass

        return await safe_answer(query, f"🎬 Loaded: {chosen_title.title()}")

    base_search = BUTTONS_CACHE.get(key)
    if not base_search:
        return await safe_answer(
            query,
            "⌛ This search expired. Please type the movie name again!",
            show_alert=True,
        )

    state = get_filter_state(key)

    # 📄 Interactive Page Jump Grid
    if action == "fpages":
        cur_p = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 1
        tot_p = int(parts[4]) if len(parts) > 4 and parts[4].isdigit() else 1
        btn_rows, row = [], []
        max_show = min(tot_p, 20)
        for p in range(1, max_show + 1):
            label = f"📍 {p}" if p == cur_p else str(p)
            target_off = (p - 1) * 10
            row.append(
                create_btn(
                    text=label,
                    callback_data=f"next_{req}_{key}_{target_off}",
                )
            )
            if len(row) == 4:
                btn_rows.append(row)
                row = []
        if row:
            btn_rows.append(row)
        btn_rows.append(
            [create_btn(text="⬅️ Back", callback_data=f"fback#{req}#{key}")]
        )
        try:
            await query.edit_message_reply_markup(
                reply_markup=InlineKeyboardMarkup(btn_rows)
            )
        except Exception:
            pass
        return await safe_answer(query, f"📄 Select a page (1 - {max_show}):")

    avail = await get_available_attributes(base_search)

    # 1. Open Smart Language Selection Menu
    if action == "flang":
        cur_lang = state.get("lang")
        avail_langs = [
            (name, code)
            for name, code in LANGUAGES_LIST
            if not avail["langs"] or code in avail["langs"]
        ] or LANGUAGES_LIST
        btn_rows, row = [], []
        for lang_name, lang_code in avail_langs:
            label = f"✅ {lang_name}" if cur_lang == lang_code else lang_name
            row.append(
                create_btn(
                    text=label,
                    callback_data=f"setlang#{req}#{key}#{lang_code}",
                )
            )
            if len(row) == 2:
                btn_rows.append(row)
                row = []
        if row:
            btn_rows.append(row)

        btn_rows.append(
            [create_btn(text="⬅️ Back", callback_data=f"fback#{req}#{key}")]
        )
        try:
            await query.edit_message_reply_markup(
                reply_markup=InlineKeyboardMarkup(btn_rows)
            )
        except (MessageNotModified, MessageIdInvalid, ChatWriteForbidden, Forbidden):
            pass
        return await safe_answer(query, "🔊 Select your preferred language:")

    # 2. Open Smart Quality Selection Menu
    if action == "fqual":
        cur_qual = state.get("qual")
        avail_quals = [
            q for q in QUALITIES_LIST if not avail["quals"] or q in avail["quals"]
        ] or QUALITIES_LIST
        btn_rows, row = [], []
        for qual_val in avail_quals:
            label = f"✅ {qual_val}" if cur_qual == qual_val else qual_val
            row.append(
                create_btn(
                    text=label,
                    callback_data=f"setqual#{req}#{key}#{qual_val}",
                )
            )
            if len(row) == 2:
                btn_rows.append(row)
                row = []
        if row:
            btn_rows.append(row)

        btn_rows.append(
            [create_btn(text="⬅️ Back", callback_data=f"fback#{req}#{key}")]
        )
        try:
            await query.edit_message_reply_markup(
                reply_markup=InlineKeyboardMarkup(btn_rows)
            )
        except (MessageNotModified, MessageIdInvalid, ChatWriteForbidden, Forbidden):
            pass
        return await safe_answer(query, "🎥 Select your preferred quality:")

    # 3. Open Smart Season Selection Menu
    if action == "fseas":
        cur_seas = state.get("season")
        avail_seasons = [
            (s_name, s_code)
            for s_name, s_code in SEASONS_LIST
            if not avail["seasons"] or s_code in avail["seasons"]
        ] or SEASONS_LIST[:8]
        btn_rows, row = [], []
        for s_name, s_code in avail_seasons:
            label = f"✅ {s_name}" if cur_seas == s_code else s_name
            row.append(
                create_btn(
                    text=label,
                    callback_data=f"setseas#{req}#{key}#{s_code}",
                )
            )
            if len(row) == 2:
                btn_rows.append(row)
                row = []
        if row:
            btn_rows.append(row)

        btn_rows.append(
            [create_btn(text="⬅️ Back", callback_data=f"fback#{req}#{key}")]
        )
        try:
            await query.edit_message_reply_markup(
                reply_markup=InlineKeyboardMarkup(btn_rows)
            )
        except (MessageNotModified, MessageIdInvalid, ChatWriteForbidden, Forbidden):
            pass
        return await safe_answer(query, "📺 Select Season:")

    # 4. Open Smart Episode Selection Menu
    if action == "feps":
        cur_ep = state.get("ep")
        avail_eps = [
            (e_name, e_code)
            for e_name, e_code in EPISODES_LIST
            if not avail["eps"] or e_code in avail["eps"]
        ] or EPISODES_LIST[:16]
        btn_rows, row = [], []
        for e_name, e_code in avail_eps[:24]:
            label = f"✅ {e_name}" if cur_ep == e_code else e_name
            row.append(
                create_btn(
                    text=label,
                    callback_data=f"setep#{req}#{key}#{e_code}",
                )
            )
            if len(row) == 3:
                btn_rows.append(row)
                row = []
        if row:
            btn_rows.append(row)

        btn_rows.append(
            [create_btn(text="⬅️ Back", callback_data=f"fback#{req}#{key}")]
        )
        try:
            await query.edit_message_reply_markup(
                reply_markup=InlineKeyboardMarkup(btn_rows)
            )
        except (MessageNotModified, MessageIdInvalid, ChatWriteForbidden, Forbidden):
            pass
        return await safe_answer(query, "🎞️ Select Episode:")

    # 5. Open Smart Year Selection Menu
    if action == "fyear":
        cur_yr = state.get("year")
        avail_years = (
            sorted(avail["years"], reverse=True) if avail["years"] else YEARS_LIST[:15]
        )
        btn_rows, row = [], []
        for yr in avail_years[:18]:
            label = f"✅ {yr}" if cur_yr == yr else yr
            row.append(
                create_btn(
                    text=label,
                    callback_data=f"setyear#{req}#{key}#{yr}",
                )
            )
            if len(row) == 3:
                btn_rows.append(row)
                row = []
        if row:
            btn_rows.append(row)

        btn_rows.append(
            [create_btn(text="⬅️ Back", callback_data=f"fback#{req}#{key}")]
        )
        try:
            await query.edit_message_reply_markup(
                reply_markup=InlineKeyboardMarkup(btn_rows)
            )
        except (MessageNotModified, MessageIdInvalid, ChatWriteForbidden, Forbidden):
            pass
        return await safe_answer(query, "📅 Select Release Year:")

    # 6. Apply Selected Filter, Sort Order, Back or Reset
    new_lang = state.get("lang")
    new_qual = state.get("qual")
    new_year = state.get("year")
    new_seas = state.get("season")
    new_ep = state.get("ep")
    new_sort = state.get("sort", "rel")

    if action == "freset":
        new_lang = new_qual = new_year = new_seas = new_ep = None
        new_sort = "rel"
    elif action == "fsort":
        new_sort = {"rel": "asc", "asc": "desc", "desc": "rel"}.get(new_sort, "rel")
    elif action == "setlang":
        chosen = parts[3] if len(parts) > 3 else "all"
        new_lang = None if chosen in ("all", new_lang) else chosen
    elif action == "setqual":
        chosen = parts[3] if len(parts) > 3 else "all"
        new_qual = None if chosen in ("all", new_qual) else chosen
    elif action == "setseas":
        chosen = parts[3] if len(parts) > 3 else "all"
        new_seas = None if chosen in ("all", new_seas) else chosen
    elif action == "setep":
        chosen = parts[3] if len(parts) > 3 else "all"
        new_ep = None if chosen in ("all", new_ep) else chosen
    elif action == "setyear":
        chosen = parts[3] if len(parts) > 3 else "all"
        new_year = None if chosen in ("all", new_year) else chosen

    candidate_state = {
        "lang": new_lang,
        "qual": new_qual,
        "year": new_year,
        "season": new_seas,
        "ep": new_ep,
        "sort": new_sort,
        "from_dym": state.get("from_dym", False),
    }
    files, n_offset, total = await smart_filtered_search(
        base_search, candidate_state, max_results=10, offset=0
    )

    if not files:
        missing_label = ""
        if action == "setlang" and new_lang:
            missing_label = LANG_MAP.get(new_lang, new_lang)
        elif action == "setqual" and new_qual:
            missing_label = new_qual
        elif action == "setseas" and new_seas:
            missing_label = SEASON_MAP.get(new_seas, new_seas.upper())
        elif action == "setep" and new_ep:
            missing_label = new_ep.upper()
        elif action == "setyear" and new_year:
            missing_label = str(new_year)
        return await safe_answer(
            query,
            f"❌ No {missing_label} files found for this movie!".strip(),
            show_alert=True,
        )

    set_filter_state(
        key,
        lang=new_lang,
        qual=new_qual,
        year=new_year,
        season=new_seas,
        ep=new_ep,
        sort=new_sort,
        from_dym=state.get("from_dym", False),
    )

    settings = await get_settings(query.message.chat.id) or {}
    if not getattr(temp, "U_NAME", None):
        me = await bot.get_me()
        temp.U_NAME = me.username
        temp.B_NAME = me.first_name
        temp.ME = me.id
    bot_username = temp.U_NAME or "bot"

    btn = await build_result_buttons(
        files=files,
        offset=n_offset,
        total_results=total,
        req=req,
        key=key,
        settings=settings,
        bot_username=bot_username,
        current_offset=0,
    )

    try:
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(btn))
    except (
        MessageNotModified,
        MessageIdInvalid,
        ButtonUrlInvalid,
        ChatWriteForbidden,
        Forbidden,
    ):
        pass

    if action == "freset":
        return await safe_answer(query, "⬅️ Restored normal filter results!")
    if action == "fback":
        return await safe_answer(query, "⬅️ Returned to current results!")
    if action == "fsort":
        sort_toast = {
            "rel": "🎯 Sorted by: Best Relevance",
            "asc": "⬆️ Sorted by: File Size (Smallest First)",
            "desc": "⬇️ Sorted by: File Size (Largest First)",
        }.get(new_sort, "Sorted!")
        return await safe_answer(query, sort_toast)

    active_filters = []
    if new_lang and new_lang in LANG_MAP:
        active_filters.append(LANG_MAP[new_lang])
    if new_qual:
        active_filters.append(new_qual)
    if new_seas:
        active_filters.append(new_seas.upper())
    if new_ep:
        active_filters.append(new_ep.upper())
    if new_year:
        active_filters.append(str(new_year))

    if active_filters:
        await safe_answer(query, f"✅ Filtered by: {' + '.join(active_filters)}")
    else:
        await safe_answer(query, "⬅️ Restored normal filter results!")


# ============================================================
# 🎛️ INLINE CALLBACK HANDLERS (PAGINATION & PAGES)
# ============================================================
@Client.on_callback_query(
    filters.regex(r"^(next_|pages|delallconfirm|delallcancel)"),
    group=-2,
)
async def pagination_handler(bot: Client, query: CallbackQuery):
    data = query.data

    if data.startswith("pages"):
        parts = data.split("#")
        if len(parts) == 4:
            _, cur_p, tot_p, tot_f = parts
            return await safe_answer(
                query,
                f"📄 Page {cur_p} of {tot_p} • Total Files: {tot_f}",
                show_alert=False,
            )
        return await safe_answer(query, "📄 Current Page Indicator", show_alert=False)

    if data == "delallcancel":
        await safe_answer(query, "Cancelled.")
        try:
            await query.message.delete()
        except Exception:
            pass
        return

    if data.startswith("delallconfirm#"):
        target_chat_id = int(data.split("#")[1])
        uid = query.from_user.id if query.from_user else 0
        if not await is_global_admin(uid):
            try:
                member = await bot.get_chat_member(target_chat_id, uid)
                if member.status not in [
                    enums.ChatMemberStatus.ADMINISTRATOR,
                    enums.ChatMemberStatus.OWNER,
                ]:
                    return await safe_answer(query, "❌ Unauthorized!", show_alert=True)
            except Exception:
                return await safe_answer(query, "❌ Unauthorized!", show_alert=True)

        keywords = await get_filters(target_chat_id)
        for kw in keywords:
            await delete_filter(query.message, kw, target_chat_id)
        await safe_answer(query, "✅ All filters deleted!", show_alert=True)
        try:
            return await query.message.edit_text(
                f"🗑️ <b>Deleted all filters for chat:</b> <code>{target_chat_id}</code>",
                parse_mode=enums.ParseMode.HTML,
            )
        except Exception:
            return

    try:
        _, req, key, offset_str = data.split("_", 3)
    except ValueError:
        return await safe_answer(query, "Invalid button data!", show_alert=True)

    if int(req) not in [query.from_user.id, 0] and not await is_global_admin(
        query.from_user.id
    ):
        return await safe_answer(
            query,
            "⚠️ That's not for you! Request your own movie in the group.",
            show_alert=True,
        )

    offset = int(offset_str) if offset_str.isdigit() else 0
    if not (base_search := BUTTONS_CACHE.get(key)):
        return await safe_answer(
            query,
            "⌛ This search expired. Please type the movie name again!",
            show_alert=True,
        )

    state = get_filter_state(key)
    files, n_offset, total = await smart_filtered_search(
        base_search, state, max_results=10, offset=offset
    )
    if not files:
        return await safe_answer(query, "No more files found.", show_alert=True)

    settings = await get_settings(query.message.chat.id) or {}
    if not getattr(temp, "U_NAME", None):
        me = await bot.get_me()
        temp.U_NAME = me.username
        temp.B_NAME = me.first_name
        temp.ME = me.id
    bot_username = temp.U_NAME or "bot"

    btn = await build_result_buttons(
        files=files,
        offset=n_offset,
        total_results=total,
        req=int(req),
        key=key,
        settings=settings,
        bot_username=bot_username,
        current_offset=offset,
    )

    try:
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(btn))
    except (
        MessageNotModified,
        MessageIdInvalid,
        ButtonUrlInvalid,
        ChatWriteForbidden,
        Forbidden,
    ):
        pass
    except FloodWait as e:
        await asyncio.sleep(e.value + 1)
        try:
            await query.edit_message_reply_markup(
                reply_markup=InlineKeyboardMarkup(btn)
            )
        except Exception:
            pass
    await safe_answer(query)


# ============================================================
# 🎨 KEYBOARD AND BUTTON PARSERS (MANUAL FILTERS)
# ============================================================
def build_keyboard(btn_str: str):
    if not btn_str or btn_str in ["[]", "None", "False", ""]:
        return None
    try:
        button_layout = []
        for row in ast.literal_eval(btn_str):
            btn_row = []
            for b in row:
                if isinstance(b, dict):
                    b_copy = b.copy()
                    style_val = b_copy.pop("style", None)
                    btn_row.append(
                        create_btn(
                            text=b_copy.get("text", "Button"),
                            url=b_copy.get("url"),
                            callback_data=b_copy.get("callback_data"),
                            style=style_val,
                        )
                    )
                else:
                    btn_row.append(b)
            button_layout.append(btn_row)
        return button_layout
    except Exception as e:
        logger.error(f"Button parsing error: {e}")
        return None


def parse_markdown_buttons(text: str):
    if not text:
        return "", "[]"
    buttons, clean_lines = [], []
    for line in text.split("\n"):
        row_btns = []
        matches = sorted(
            list(re.finditer(r"\[([^\[\]]+)\]\(([^()]+)\)", line))
            + list(re.finditer(r"\[([^\[\]]+)\|([^()]+)\]", line)),
            key=lambda m: m.start(),
        )
        for match in matches:
            url_val = match.group(2).strip()
            if not url_val.startswith(("http://", "https://", "tg://")):
                url_val = "https://" + url_val
            row_btns.append({"text": match.group(1).strip(), "url": url_val})
        if row_btns:
            buttons.append(row_btns)
        if clean_line := re.sub(
            r"\[([^\[\]]+)\|([^()]+)\]",
            "",
            re.sub(r"\[([^\[\]]+)\]\(([^()]+)\)", "", line),
        ).strip():
            clean_lines.append(clean_line)
        elif not matches:
            clean_lines.append("")
    return "\n".join(clean_lines).strip(), (str(buttons) if buttons else "[]")


# ============================================================
# 🎯 FILTER COMMANDS (HIGH PRIORITY GROUP=-2 SO THEY NEVER FAIL)
# ============================================================
@Client.on_message(filters.command("filter") & filters.incoming, group=-2)
async def add_filter_cmd(client: Client, message: Message):
    target_chat_id = await get_target_chat(client, message)
    if not target_chat_id:
        return await safe_reply_text(
            message,
            "⚠️ <b>No active connection!</b>\nPlease run <code>/connect &lt;group_id&gt;</code> first.",
            parse_mode=enums.ParseMode.HTML,
        )
    if not await verify_admin(client, message, target_chat_id):
        return await safe_reply_text(
            message,
            f"❌ <b>You are not authorized for chat:</b> <code>{target_chat_id}</code>",
            parse_mode=enums.ParseMode.HTML,
        )

    if not message.reply_to_message:
        return await safe_reply_text(
            message,
            "⚠️ <b>Reply to a message (text or media) to set it as a filter.</b>\n"
            "⚙️ <b>Usage:</b> <code>/filter &lt;keyword&gt;</code>",
            parse_mode=enums.ParseMode.HTML,
        )
    if len(message.command) < 2:
        return await safe_reply_text(
            message,
            "⚙️ <b>Usage:</b> <code>/filter &lt;keyword&gt;</code>",
            parse_mode=enums.ParseMode.HTML,
        )

    keyword = message.text.split(None, 1)[1].lower().strip()
    replied = message.reply_to_message
    raw_content = (
        replied.text.html
        if replied.text and hasattr(replied.text, "html")
        else (
            replied.caption.html
            if replied.caption and hasattr(replied.caption, "html")
            else (replied.text or replied.caption or "")
        )
    )
    text, btn = parse_markdown_buttons(raw_content)

    if btn == "[]" and replied.reply_markup and replied.reply_markup.inline_keyboard:
        existing_btns = []
        for row in replied.reply_markup.inline_keyboard:
            row_btns = []
            for b in row:
                b_dict = {"text": b.text}
                if b.url:
                    b_dict["url"] = b.url
                elif b.callback_data:
                    b_dict["callback_data"] = b.callback_data
                st = getattr(b, "style", None)
                if st:
                    b_dict["style"] = st.value if hasattr(st, "value") else int(st)
                row_btns.append(b_dict)
            if row_btns:
                existing_btns.append(row_btns)
        if existing_btns:
            btn = str(existing_btns)

    fileid = "None"
    for media_attr in ["photo", "video", "document", "audio", "animation", "sticker"]:
        if media_obj := getattr(replied, media_attr, None):
            fileid = media_obj.file_id
            break

    await safe_save_filter(target_chat_id, keyword, text, btn, fileid, "[]")
    out_msg = await safe_reply_text(
        message,
        f"✅ <b>Filter successfully added!</b>\n\n"
        f"🔑 <b>Keyword:</b> <code>{html.escape(keyword)}</code>\n"
        f"🆔 <b>Chat ID:</b> <code>{target_chat_id}</code>",
        parse_mode=enums.ParseMode.HTML,
    )
    delete_timer = await resolve_auto_delete_timer(message.chat.id, default_time=300)
    schedule_auto_delete(client, message.chat.id, False, delete_timer, out_msg, message)


@Client.on_message(filters.command("addfilter") & filters.incoming, group=-2)
async def add_premade_filter_cmd(client: Client, message: Message):
    target_chat_id = await get_target_chat(client, message)
    if not target_chat_id:
        return await safe_reply_text(
            message,
            "⚠️ <b>No active connection!</b>\nPlease run <code>/connect &lt;group_id&gt;</code> first.",
            parse_mode=enums.ParseMode.HTML,
        )
    if not await verify_admin(client, message, target_chat_id):
        return await safe_reply_text(
            message,
            f"❌ <b>You are not authorized for chat:</b> <code>{target_chat_id}</code>",
            parse_mode=enums.ParseMode.HTML,
        )

    if not message.reply_to_message:
        return await safe_reply_text(
            message,
            "⚠️ <b>Reply to a message containing inline buttons.</b>",
            parse_mode=enums.ParseMode.HTML,
        )
    if len(message.command) < 2:
        return await safe_reply_text(
            message,
            "⚙️ <b>Usage:</b> <code>/addfilter &lt;keyword&gt;</code>",
            parse_mode=enums.ParseMode.HTML,
        )

    keyword = message.text.split(None, 1)[1].lower().strip()
    replied = message.reply_to_message

    buttons = []
    if replied.reply_markup and replied.reply_markup.inline_keyboard:
        for row in replied.reply_markup.inline_keyboard:
            row_btns = []
            for btn in row:
                btn_dict = {"text": btn.text}
                if btn.url:
                    btn_dict["url"] = btn.url
                elif btn.callback_data:
                    btn_dict["callback_data"] = btn.callback_data
                st = getattr(btn, "style", None)
                if st:
                    btn_dict["style"] = st.value if hasattr(st, "value") else int(st)
                row_btns.append(btn_dict)
            if row_btns:
                buttons.append(row_btns)

    fileid = "None"
    for media_attr in ["photo", "video", "document", "audio", "animation", "sticker"]:
        if media_obj := getattr(replied, media_attr, None):
            fileid = media_obj.file_id
            break

    raw_content = (
        replied.text.html
        if replied.text and hasattr(replied.text, "html")
        else (
            replied.caption.html
            if replied.caption and hasattr(replied.caption, "html")
            else (replied.text or replied.caption or "")
        )
    )

    await safe_save_filter(
        target_chat_id,
        keyword,
        raw_content,
        str(buttons) if buttons else "[]",
        fileid,
        "[]",
    )
    out_msg = await safe_reply_text(
        message,
        f"✅ <b>Filter with buttons added!</b>\n\n<b>Keyword:</b> <code>{html.escape(keyword)}</code>",
        parse_mode=enums.ParseMode.HTML,
    )
    delete_timer = await resolve_auto_delete_timer(message.chat.id, default_time=300)
    schedule_auto_delete(client, message.chat.id, False, delete_timer, out_msg, message)


@Client.on_message(filters.command("filterimage") & filters.incoming, group=-2)
async def edit_filter_image_cmd(client: Client, message: Message):
    target_chat_id = await get_target_chat(client, message)
    if not target_chat_id:
        return await safe_reply_text(
            message,
            "⚠️ <b>No active connection!</b>\nPlease run <code>/connect &lt;group_id&gt;</code> first.",
            parse_mode=enums.ParseMode.HTML,
        )
    if not await verify_admin(client, message, target_chat_id):
        return await safe_reply_text(
            message,
            f"❌ <b>You are not authorized for chat:</b> <code>{target_chat_id}</code>",
            parse_mode=enums.ParseMode.HTML,
        )

    if not message.reply_to_message or not message.reply_to_message.media:
        return await safe_reply_text(
            message,
            "⚠️ <b>Reply to a photo, video, or document to set the new image.</b>",
            parse_mode=enums.ParseMode.HTML,
        )
    if len(message.command) < 2:
        return await safe_reply_text(
            message,
            "⚙️ <b>Usage:</b> <code>/filterimage &lt;keyword&gt;</code>",
            parse_mode=enums.ParseMode.HTML,
        )

    keyword = message.text.split(None, 1)[1].lower().strip()
    reply_text, btn, alert, old_fileid = await find_filter(target_chat_id, keyword)

    if not reply_text and (not old_fileid or old_fileid == "None"):
        return await safe_reply_text(
            message,
            f"❌ <b>Filter <code>{html.escape(keyword)}</code> not found.</b>",
            parse_mode=enums.ParseMode.HTML,
        )

    fileid = "None"
    for media_attr in ["photo", "video", "document", "audio", "animation", "sticker"]:
        if media_obj := getattr(message.reply_to_message, media_attr, None):
            fileid = media_obj.file_id
            break

    if fileid == "None":
        return await safe_reply_text(
            message,
            "❌ <b>Could not extract valid media.</b>",
            parse_mode=enums.ParseMode.HTML,
        )

    await safe_save_filter(target_chat_id, keyword, reply_text, btn, fileid, alert)
    out_msg = await safe_reply_text(
        message,
        f"✅ <b>Filter image updated!</b>\n\n<b>Keyword:</b> <code>{html.escape(keyword)}</code>",
        parse_mode=enums.ParseMode.HTML,
    )
    delete_timer = await resolve_auto_delete_timer(message.chat.id, default_time=300)
    schedule_auto_delete(client, message.chat.id, False, delete_timer, out_msg, message)


@Client.on_message(
    filters.command(["editfiltercolur", "editfiltercolour"]) & filters.incoming,
    group=-2,
)
async def edit_filter_colour_cmd(client: Client, message: Message):
    target_chat_id = await get_target_chat(client, message)
    if not target_chat_id:
        return await safe_reply_text(
            message,
            "⚠️ <b>No active connection!</b>\nPlease run <code>/connect &lt;group_id&gt;</code> first.",
            parse_mode=enums.ParseMode.HTML,
        )
    if not await verify_admin(client, message, target_chat_id):
        return await safe_reply_text(
            message,
            f"❌ <b>You are not authorized for chat:</b> <code>{target_chat_id}</code>",
            parse_mode=enums.ParseMode.HTML,
        )

    args = message.command
    if len(args) < 4:
        return await safe_reply_text(
            message,
            "❌ <b>Usage:</b> <code>/editfiltercolour &lt;keyword&gt; &lt;button_number&gt; &lt;colour&gt;</code>\n\n<b>Colours:</b> <code>green</code>, <code>red</code>, <code>blue</code>",
            parse_mode=enums.ParseMode.HTML,
        )

    try:
        btn_num, color_str, keyword = (
            int(args[-2]),
            args[-1].lower(),
            " ".join(args[1:-2]).lower().strip(),
        )
    except ValueError:
        return await safe_reply_text(
            message,
            "❌ <b>Button number must be an integer.</b>",
            parse_mode=enums.ParseMode.HTML,
        )

    color_map = {"green": 3, "red": 4, "blue": 1}
    if color_str not in color_map:
        return await safe_reply_text(
            message,
            "❌ <b>Invalid colour.</b> Choose from: <code>green</code>, <code>red</code>, <code>blue</code>.",
            parse_mode=enums.ParseMode.HTML,
        )

    reply_text, btn, alert, fileid = await find_filter(target_chat_id, keyword)
    if not reply_text and (not fileid or fileid == "None"):
        return await safe_reply_text(
            message,
            f"❌ <b>Filter <code>{html.escape(keyword)}</code> not found.</b>",
            parse_mode=enums.ParseMode.HTML,
        )
    if not btn or btn in ["[]", "None", "False", ""]:
        return await safe_reply_text(
            message,
            f"❌ <b>Filter <code>{html.escape(keyword)}</code> has no buttons.</b>",
            parse_mode=enums.ParseMode.HTML,
        )

    try:
        button_data = ast.literal_eval(btn)
    except Exception:
        return await safe_reply_text(
            message,
            "❌ <b>Corrupted button format.</b>",
            parse_mode=enums.ParseMode.HTML,
        )

    count, found = 0, False
    for r_idx, row in enumerate(button_data):
        for c_idx, b in enumerate(row):
            count += 1
            if count == btn_num:
                button_data[r_idx][c_idx]["style"] = color_map[color_str]
                found = True
                break
        if found:
            break

    if not found:
        return await safe_reply_text(
            message,
            f"❌ <b>Button {btn_num} not found.</b> Filter has {count} buttons.",
            parse_mode=enums.ParseMode.HTML,
        )

    await safe_save_filter(
        target_chat_id, keyword, reply_text, str(button_data), fileid, alert
    )
    out_msg = await safe_reply_text(
        message,
        f"✅ <b>Filter <code>{html.escape(keyword)}</code> Button {btn_num} colour changed to {color_str.title()}!</b>",
        parse_mode=enums.ParseMode.HTML,
    )
    delete_timer = await resolve_auto_delete_timer(message.chat.id, default_time=300)
    schedule_auto_delete(client, message.chat.id, False, delete_timer, out_msg, message)


@Client.on_message(filters.command(["delfilter", "stop"]) & filters.incoming, group=-2)
async def del_filter_cmd(client: Client, message: Message):
    target_chat_id = await get_target_chat(client, message)
    if not target_chat_id:
        return await safe_reply_text(
            message,
            "⚠️ <b>No active connection!</b>\nPlease run <code>/connect &lt;group_id&gt;</code> first.",
            parse_mode=enums.ParseMode.HTML,
        )
    if not await verify_admin(client, message, target_chat_id):
        return await safe_reply_text(
            message,
            f"❌ <b>You are not authorized for chat:</b> <code>{target_chat_id}</code>",
            parse_mode=enums.ParseMode.HTML,
        )

    if len(message.command) < 2:
        return await safe_reply_text(
            message,
            "⚙️ <b>Usage:</b> <code>/delfilter &lt;keyword&gt;</code>",
            parse_mode=enums.ParseMode.HTML,
        )
    keyword = message.text.split(None, 1)[1].lower().strip()
    await delete_filter(message, keyword, target_chat_id)
    out_msg = await safe_reply_text(
        message,
        f"🗑️ <b>Filter <code>{html.escape(keyword)}</code> deleted.</b>",
        parse_mode=enums.ParseMode.HTML,
    )
    delete_timer = await resolve_auto_delete_timer(message.chat.id, default_time=300)
    schedule_auto_delete(client, message.chat.id, False, delete_timer, out_msg, message)


@Client.on_message(
    filters.command(["delall", "deleteall"]) & filters.incoming, group=-2
)
async def del_all_filters_cmd(client: Client, message: Message):
    target_chat_id = await get_target_chat(client, message)
    if not target_chat_id:
        return await safe_reply_text(
            message,
            "⚠️ <b>No active connection!</b>\nPlease run <code>/connect &lt;group_id&gt;</code> first.",
            parse_mode=enums.ParseMode.HTML,
        )
    if not await verify_admin(client, message, target_chat_id):
        return await safe_reply_text(
            message,
            f"❌ <b>You are not authorized for chat:</b> <code>{target_chat_id}</code>",
            parse_mode=enums.ParseMode.HTML,
        )

    buttons = [
        [
            create_btn(
                "🔥 Yes, Delete All",
                callback_data=f"delallconfirm#{target_chat_id}",
            )
        ],
        [create_btn("❌ Cancel", callback_data="delallcancel")],
    ]
    await safe_reply_text(
        message,
        f"⚠️ <b>Are you sure you want to delete ALL filters in <code>{target_chat_id}</code>?</b>",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(
    filters.command(["listfilters", "filters", "viewfilters"]) & filters.incoming,
    group=-2,
)
async def list_filters_cmd(client: Client, message: Message):
    target_chat_id = await get_target_chat(client, message)
    if not target_chat_id:
        return await safe_reply_text(
            message,
            "⚠️ <b>No active connection!</b>\nPlease run <code>/connect &lt;group_id&gt;</code> first.",
            parse_mode=enums.ParseMode.HTML,
        )
    if not await verify_admin(client, message, target_chat_id):
        return await safe_reply_text(
            message,
            f"❌ <b>You are not authorized for chat:</b> <code>{target_chat_id}</code>",
            parse_mode=enums.ParseMode.HTML,
        )

    keywords = await get_filters(target_chat_id)
    if not keywords:
        return await safe_reply_text(
            message,
            f"⚠️ <b>No active filters found in <code>{target_chat_id}</code>.</b>",
            parse_mode=enums.ParseMode.HTML,
        )

    out_msg = await safe_reply_text(
        message,
        f"📋 <b>Current Filters ({len(keywords)}):</b>\n\n"
        + "\n".join([f"• <code>{html.escape(str(kw))}</code>" for kw in keywords]),
        parse_mode=enums.ParseMode.HTML,
    )
    delete_timer = await resolve_auto_delete_timer(message.chat.id, default_time=300)
    schedule_auto_delete(client, message.chat.id, False, delete_timer, out_msg, message)


# ============================================================
# 📤 4-LAYER MULTI-MEDIA FILTER DISPATCHER
# ============================================================
async def send_filter_media(
    client: Client,
    chat_id: int,
    fileid: str,
    reply_text: str,
    reply_markup,
    reply_id: int,
):
    if RESTRICTED_WRITE_CHATS.get(str(chat_id)):
        return None
    try:
        return await client.send_cached_media(
            chat_id,
            fileid,
            caption=reply_text,
            reply_markup=reply_markup,
            reply_to_message_id=reply_id,
            parse_mode=enums.ParseMode.HTML,
        )
    except FloodWait as e:
        await asyncio.sleep(e.value + 1)
        return await send_filter_media(
            client, chat_id, fileid, reply_text, reply_markup, reply_id
        )
    except (
        ChatWriteForbidden,
        Forbidden,
        ChatAdminRequired,
        UserIsBlocked,
        PeerIdInvalid,
    ):
        RESTRICTED_WRITE_CHATS.set(str(chat_id), True)
        return None
    except Exception:
        pass

    try:
        return await client.send_cached_media(
            chat_id,
            fileid,
            caption=reply_text,
            reply_markup=reply_markup,
            parse_mode=enums.ParseMode.HTML,
        )
    except (ChatWriteForbidden, Forbidden, UserIsBlocked, PeerIdInvalid):
        RESTRICTED_WRITE_CHATS.set(str(chat_id), True)
        return None
    except Exception:
        pass

    for send_fn, arg_name in [
        (client.send_photo, "photo"),
        (client.send_video, "video"),
        (client.send_document, "document"),
        (client.send_animation, "animation"),
    ]:
        try:
            return await send_fn(
                **{
                    "chat_id": chat_id,
                    arg_name: fileid,
                    "caption": reply_text,
                    "reply_markup": reply_markup,
                    "parse_mode": enums.ParseMode.HTML,
                }
            )
        except (ChatWriteForbidden, Forbidden, UserIsBlocked, PeerIdInvalid):
            RESTRICTED_WRITE_CHATS.set(str(chat_id), True)
            return None
        except Exception:
            continue

    try:
        return await client.send_message(
            chat_id,
            text=reply_text or "<b>Here is your file:</b>",
            reply_markup=reply_markup,
            parse_mode=enums.ParseMode.HTML,
        )
    except (ChatWriteForbidden, Forbidden, UserIsBlocked, PeerIdInvalid):
        RESTRICTED_WRITE_CHATS.set(str(chat_id), True)
        return None
    except Exception as err:
        logger.error(f"Media filter failed all 4 layers: {err}")
        return None


async def safe_send_text_filter(
    client: Client, chat_id: int, text: str, reply_markup, reply_id: int
):
    if RESTRICTED_WRITE_CHATS.get(str(chat_id)):
        return None

    kw = {
        "chat_id": chat_id,
        "text": text,
        "reply_markup": reply_markup,
        "parse_mode": enums.ParseMode.HTML,
    }
    if "disable_web_page_preview" in _SEND_MSG_PARAMS:
        kw["disable_web_page_preview"] = True
    elif "link_preview_options" in _SEND_MSG_PARAMS and LinkPreviewOptions is not None:
        kw["link_preview_options"] = LinkPreviewOptions(is_disabled=True)

    try:
        if "reply_to_message_id" in _SEND_MSG_PARAMS:
            return await client.send_message(**kw, reply_to_message_id=reply_id)
        elif "reply_parameters" in _SEND_MSG_PARAMS and ReplyParameters is not None:
            return await client.send_message(
                **kw, reply_parameters=ReplyParameters(message_id=reply_id)
            )
        return await client.send_message(**kw)
    except (ChatWriteForbidden, Forbidden, UserIsBlocked, PeerIdInvalid, SlowmodeWait):
        RESTRICTED_WRITE_CHATS.set(str(chat_id), True)
        return None
    except Exception:
        try:
            return await client.send_message(**kw)
        except (ChatWriteForbidden, Forbidden, UserIsBlocked, PeerIdInvalid):
            RESTRICTED_WRITE_CHATS.set(str(chat_id), True)
            return None
        except Exception as e:
            logger.error(f"Text filter failed: {e}")
            return None


# ============================================================
# ⚡ LIVE GROUP TRIGGER HANDLER
# ============================================================
async def manual_filters(client: Client, message: Message, text=False) -> bool:
    if getattr(info, "REPAIR_MODE", False) and not await verify_admin(
        client, message, message.chat.id
    ):
        return False

    group_id = message.chat.id
    if message.chat.type == enums.ChatType.PRIVATE:
        if active_grp := await get_active_connection(
            str(message.from_user.id if message.from_user else 0)
        ):
            group_id = active_grp

    name = text or message.text or message.caption or ""
    if not name:
        return False

    reply_id = message.reply_to_message.id if message.reply_to_message else message.id
    try:
        keywords = await get_filters(group_id)
    except Exception:
        keywords = []

    if not keywords:
        return False

    for keyword in reversed(sorted(keywords, key=lambda x: len(str(x)))):
        kw_str = str(keyword).strip()
        if not kw_str:
            continue

        if re.search(
            r"( |^|[^\w])" + re.escape(kw_str) + r"( |$|[^\w])",
            name,
            flags=re.IGNORECASE,
        ):
            reply_text, btn, alert, fileid = await find_filter(group_id, keyword)
            if str(fileid).strip() in ["[]", "None", ""] and str(alert).strip() not in [
                "[]",
                "None",
                "",
            ]:
                fileid, alert = alert, fileid

            fileid_str = str(fileid).strip()
            has_valid_file = bool(
                fileid and fileid_str not in ["None", "[]", "", "False"]
            )
            if not reply_text and not has_valid_file:
                continue

            if reply_text:
                reply_text = reply_text.replace("\\n", "\n").replace("\\t", "\t")
                if not reply_text.startswith("<b>") and not reply_text.startswith("**"):
                    reply_text = f"<b>{reply_text}</b>"

            button_layout = build_keyboard(btn) or []
            reply_markup = (
                InlineKeyboardMarkup(button_layout) if button_layout else None
            )

            if not has_valid_file:
                sent_msg = await safe_send_text_filter(
                    client, message.chat.id, reply_text or "", reply_markup, reply_id
                )
            else:
                sent_msg = await send_filter_media(
                    client,
                    message.chat.id,
                    fileid,
                    reply_text or "",
                    reply_markup,
                    reply_id,
                )

            if sent_msg:
                delete_timer = await resolve_auto_delete_timer(
                    message.chat.id, default_time=300
                )
                if delete_timer > 0:
                    is_pm = message.chat.type == enums.ChatType.PRIVATE
                    schedule_auto_delete(
                        client, message.chat.id, is_pm, delete_timer, sent_msg, message
                    )
                return True
    return False
