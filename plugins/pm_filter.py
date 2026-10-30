import ast
import asyncio
import difflib
import html
import inspect
import math
import re
import time
import unicodedata
from logging import ERROR, getLogger
from typing import Any, Dict, List, Optional, Tuple

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

# ============================================================
# 🛡️ SAFE OPTIONAL IMPORTS (ZERO STARTUP OR RUNTIME CRASHES)
# ============================================================
try:
    from database.filters_mdb import add_filter, delete_filter, find_filter, get_filters
except Exception:

    async def add_filter(*args, **kwargs):
        return None

    async def delete_filter(*args, **kwargs):
        return None

    async def find_filter(*args, **kwargs):
        return "", "[]", "[]", "None"

    async def get_filters(*args, **kwargs):
        return []


try:
    from database.ia_filterdb import Media as _Media
    from database.ia_filterdb import get_search_results
except Exception:
    _Media = None

    async def get_search_results(*args, **kwargs):
        return [], 0, 0


try:
    from utils import get_settings, get_size, parse_text_and_markup, temp
except Exception:
    from utils import temp

    async def get_settings(chat_id):
        return {}

    def get_size(size):
        return f"{size} B"

    def parse_text_and_markup(text, default_markup=None):
        return text, default_markup


try:
    from database.ia_filterdb import (
        get_all_healthy_read_dbs,
        get_writable_System_db,
        mark_db_error,
    )
except ImportError:
    get_all_healthy_read_dbs = None
    get_writable_System_db = None
    mark_db_error = None

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


# For link shortener
try:
    from plugins.shortner import is_shortener_active, shorten_single_url
except ImportError:
    try:
        from shortner import is_shortener_active, shorten_single_url
    except ImportError:

        async def is_shortener_active() -> bool:
            return False

        async def shorten_single_url(url: str, cfg=None) -> str:
            return url


logger = getLogger(__name__)
logger.setLevel(ERROR)

# Strong reference set so Python's garbage collector never cancels sleeping auto-delete tasks
AUTO_DELETE_TASKS = set()

# Track unhealthy DB collections so a broken DB doesn't cause freezes
_DEAD_COLLECTIONS: Dict[str, float] = {}

# ============================================================
# 🔤 COMPLETE STYLISH UNICODE FONT STRIPPER / NORMALIZER ENGINE
# ============================================================
_STYLISH_CHAR_MAP: Dict[int, str] = {}

# 1. Small Caps & Special Latin Stylized Letters
_SMALL_CAPS_PAIRS = (
    ("ᴀ", "a"),
    ("ʙ", "b"),
    ("ᴄ", "c"),
    ("ᴅ", "d"),
    ("ᴇ", "e"),
    ("ꜰ", "f"),
    ("ɢ", "g"),
    ("ʜ", "h"),
    ("ɪ", "i"),
    ("ᴊ", "j"),
    ("ᴋ", "k"),
    ("ʟ", "l"),
    ("ᴍ", "m"),
    ("ɴ", "n"),
    ("ᴏ", "o"),
    ("ᴘ", "p"),
    ("ǫ", "q"),
    ("ʀ", "r"),
    ("ꜱ", "s"),
    ("ᴛ", "t"),
    ("ᴜ", "u"),
    ("ᴠ", "v"),
    ("ᴡ", "w"),
    ("x", "x"),
    ("ʏ", "y"),
    ("ᴢ", "z"),
    ("ꞯ", "q"),
    ("w", "w"),
    ("ℓ", "l"),
    ("ℏ", "h"),
    ("℘", "p"),
    ("ℑ", "I"),
    ("ℜ", "R"),
    ("ℨ", "Z"),
    ("ℬ", "B"),
    ("ℰ", "E"),
    ("ℱ", "F"),
    ("ℋ", "H"),
    ("ℐ", "I"),
    ("ℒ", "L"),
    ("ℳ", "M"),
    ("ℛ", "R"),
    ("ℯ", "e"),
    ("ℊ", "g"),
    ("ℴ", "o"),
    ("ℂ", "C"),
    ("ℍ", "H"),
    ("ℕ", "N"),
    ("ℙ", "P"),
    ("ℚ", "Q"),
    ("ℝ", "R"),
    ("ℤ", "Z"),
)
for _sc_k, _sc_v in _SMALL_CAPS_PAIRS:
    if len(_sc_k) == 1:
        _STYLISH_CHAR_MAP[ord(_sc_k)] = _sc_v

# 2. Enclosed Alphanumerics: Ⓐ-Ⓩ (0x24B6-0x24CF), ⓐ-ⓩ (0x24D0-0x24E9)
for _i in range(26):
    _STYLISH_CHAR_MAP[0x24B6 + _i] = chr(ord("A") + _i)
    _STYLISH_CHAR_MAP[0x24D0 + _i] = chr(ord("a") + _i)
    # Parenthesized/Squared/Negative Circled/Regional Indicator/Tag Letters
    _STYLISH_CHAR_MAP[0x1F110 + _i] = chr(ord("A") + _i)  # 🄐-🄩
    _STYLISH_CHAR_MAP[0x1F130 + _i] = chr(ord("A") + _i)  # 🄰-🅉
    _STYLISH_CHAR_MAP[0x1F150 + _i] = chr(ord("A") + _i)  # 🅐-🅩
    _STYLISH_CHAR_MAP[0x1F170 + _i] = chr(ord("A") + _i)  # 🅰-🆉
    _STYLISH_CHAR_MAP[0x1F1E6 + _i] = chr(ord("A") + _i)  # 🇦-🇿

# 3. Mathematical Alphanumeric Symbols (Bold, Italic, Script, Fraktur, Double-Struck, Sans, Mono)
_MATH_ALPHA_RANGES = (
    (0x1D400, "A", 26),
    (0x1D41A, "a", 26),
    (0x1D434, "A", 26),
    (0x1D44E, "a", 26),
    (0x1D468, "A", 26),
    (0x1D482, "a", 26),
    (0x1D49C, "A", 26),
    (0x1D4B6, "a", 26),
    (0x1D4D0, "A", 26),
    (0x1D4EA, "a", 26),
    (0x1D504, "A", 26),
    (0x1D51E, "a", 26),
    (0x1D538, "A", 26),
    (0x1D552, "a", 26),
    (0x1D56C, "A", 26),
    (0x1D586, "a", 26),
    (0x1D5A0, "A", 26),
    (0x1D5BA, "a", 26),
    (0x1D5D4, "A", 26),
    (0x1D5EE, "a", 26),
    (0x1D608, "A", 26),
    (0x1D622, "a", 26),
    (0x1D63C, "A", 26),
    (0x1D656, "a", 26),
    (0x1D670, "A", 26),
    (0x1D68A, "a", 26),
)
for _start_cp, _base_ch, _cnt in _MATH_ALPHA_RANGES:
    for _i in range(_cnt):
        _STYLISH_CHAR_MAP[_start_cp + _i] = chr(ord(_base_ch) + _i)

# 4. Mathematical Digits (Bold, Double-Struck, Sans-Serif, Sans-Bold, Monospace)
for _d_start in (0x1D7CE, 0x1D7D8, 0x1D7E2, 0x1D7EC, 0x1D7F6):
    for _i in range(10):
        _STYLISH_CHAR_MAP[_d_start + _i] = str(_i)


def strip_stylish_fonts(text: str) -> str:
    """
    Converts/removes ALL fancy/stylish Unicode fonts (Mathematical Bold, Italic, Script,
    Fraktur, Sans-Serif, Monospace, Fullwidth, Circled, Squared, Negative Squared,
    Regional Indicator flags, Small-Caps, and Combining Strikethrough/Underline marks)
    into clean standard English letters and numbers while preserving Indic scripts.
    """
    if not text:
        return ""

    # Step 1: Direct codepoint translation for Math, Small-Caps, Circled & Squared fonts
    text = text.translate(_STYLISH_CHAR_MAP)

    # Step 2: Strip combining diacritical overlays (e.g., strikethrough s̶t̶y̶l̶e̶, underline)
    # while keeping Indic vowel/consonant signs (0x0900 - 0x0D7F) intact
    out_chars: List[str] = []
    for ch in text:
        cp = ord(ch)
        if 0x0900 <= cp <= 0x0D7F:
            out_chars.append(ch)
        elif 0x0300 <= cp <= 0x036F or 0x20D0 <= cp <= 0x20FF or 0xFE00 <= cp <= 0xFE0F:
            # Skip combining decorative marks & variation selectors
            continue
        elif cp > 127:
            norm_ch = unicodedata.normalize("NFKC", ch).translate(_STYLISH_CHAR_MAP)
            norm_kd = unicodedata.normalize("NFKD", norm_ch)
            ascii_only = "".join(c for c in norm_kd if ord(c) < 128)
            if ascii_only:
                out_chars.append(ascii_only)
        else:
            out_chars.append(ch)

    return "".join(out_chars)


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
# 🌐 LANGUAGES & 🎞️ QUALITIES CONFIGURATION
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
    return re.sub(r"\s+", " ", result).strip().lower()


def generate_phonetic_variants(translit_str: str) -> List[str]:
    if not translit_str:
        return []
    variants = [translit_str]
    v1 = translit_str.replace("aa", "a").replace("ee", "i").replace("oo", "u")
    if v1 not in variants:
        variants.append(v1)
    v2_words = [(w[:-1] if len(w) > 4 and w.endswith("a") else w) for w in v1.split()]
    v2 = " ".join(v2_words)
    if v2 and v2 not in variants:
        variants.append(v2)
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
# ⚡ ULTRA-FAST IN-MEMORY CACHE SYSTEM (ZERO DB LATENCY)
# ============================================================
class TTLCache:
    def __init__(self, maxsize: int = 2000, ttl: int = 1800):
        self._data: Dict[str, Tuple[float, Any]] = {}
        self._maxsize, self._ttl = maxsize, ttl

    def set(self, key: str, value: Any):
        if len(self._data) >= self._maxsize:
            self._cleanup()
            if len(self._data) >= self._maxsize:
                oldest_key = next(iter(self._data))
                self._data.pop(oldest_key, None)
        self._data[key] = (time.time() + self._ttl, value)

    def get(self, key: str) -> Optional[Any]:
        if not (item := self._data.get(key)):
            return None
        if time.time() > item[0]:
            self._data.pop(key, None)
            return None
        return item[1]

    def _cleanup(self):
        now = time.time()
        for k in [k for k, (exp, _) in list(self._data.items()) if now > exp]:
            self._data.pop(k, None)


GLOBAL_SEARCH_CACHE = TTLCache(maxsize=5000, ttl=900)
POOL_SEARCH_CACHE = TTLCache(maxsize=3000, ttl=900)
MANUAL_FILTERS_CACHE = TTLCache(maxsize=1000, ttl=120)
AUTO_DELETE_TIMER_CACHE = TTLCache(maxsize=1000, ttl=120)
BUTTONS_CACHE = TTLCache(maxsize=4000, ttl=1800)
FILTER_STATE_CACHE = TTLCache(maxsize=4000, ttl=1800)
SUGGESTIONS_CACHE = TTLCache(maxsize=2000, ttl=1800)
DYM_QUERY_CACHE = TTLCache(maxsize=2000, ttl=1800)
USER_LAST_REQ = TTLCache(maxsize=5000, ttl=30)
FUZZY_TITLES_CACHE = TTLCache(maxsize=10, ttl=1800)
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
        if e.value <= 10:
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
        try:
            return await msg.reply_text(
                text=re.sub(r"<[^>]+>", "", text or ""),
                reply_markup=reply_markup,
            )
        except Exception as err:
            logger.error(f"safe_reply_text error: {err}")
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
    if photo and str(photo).strip().lower() not in ["none", "null", "false", ""]:
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
            if e.value <= 10:
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
    _DB_CLIENT = AsyncIOMotorClient(
        info.DATABASE_URI,
        serverSelectionTimeoutMS=4000,
        connectTimeoutMS=4000,
        socketTimeoutMS=8000,
    )
    _BOT_DB = _DB_CLIENT[info.DATABASE_NAME]
    cw_db = _BOT_DB["clean_words"]
    pm_feat_db = _BOT_DB["pm_filter_features"]
except Exception as e:
    logger.error(f"Failed to init cw_db / pm_feat_db: {e}")

DEFAULT_CLEAN_WORDS = [
    "@",
    "sandalwood",
    "mkv",
    "mp4",
    "dub",
    "dubbed",
    "(",
    "(",
    "{",
    "}",
    "#",
    "[",
    "]",
    "Movie",
    "Movies",
    "latest",
    "new",
    "avi",
    "webm",
    "zip",
    "rar",
]
_CLEAN_WORDS_CACHE: Tuple[float, list] = (0.0, DEFAULT_CLEAN_WORDS)
_PROMO_CACHE: Tuple[float, List[Dict[str, str]]] = (0.0, [])
_FEATURE_FLAGS_CACHE: Dict[str, Any] = {
    "ts": 0.0,
    "autotranslate": True,
    "multichoice": True,
}


def _get_writable_col(col_name: str, fallback_col: Any):
    if callable(get_writable_System_db):
        try:
            target_db = get_writable_System_db()
            if target_db is not None:
                return target_db[col_name]
        except Exception:
            pass
    return fallback_col


def _get_all_filter_dbs() -> List[Any]:
    """Returns all available database instances across primary and secondary clusters."""
    dbs = []
    if callable(get_writable_System_db):
        try:
            w_db = get_writable_System_db()
            if w_db is not None:
                dbs.append(w_db)
        except Exception:
            pass
    if callable(get_all_healthy_read_dbs):
        try:
            for _, r_db in get_all_healthy_read_dbs():
                if r_db is not None and r_db not in dbs:
                    dbs.append(r_db)
        except Exception:
            pass
    if _BOT_DB is not None and _BOT_DB not in dbs:
        dbs.append(_BOT_DB)
    return dbs


# In-memory backup store for manual filters so filters work 100% even if all MongoDB clusters hit 512MB quota
_RAM_FILTERS_STORE: Dict[str, Dict[str, dict]] = {}


async def get_feature_flags(force_refresh: bool = False) -> Tuple[bool, bool]:
    now = time.time()
    if not force_refresh and (now - _FEATURE_FLAGS_CACHE["ts"]) < 120:
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
        except Exception:
            pass
    _FEATURE_FLAGS_CACHE["ts"] = now
    return (
        bool(_FEATURE_FLAGS_CACHE["autotranslate"]),
        bool(_FEATURE_FLAGS_CACHE["multichoice"]),
    )


async def set_feature_flag(key: str, value: bool):
    _FEATURE_FLAGS_CACHE[key] = bool(value)
    _FEATURE_FLAGS_CACHE["ts"] = time.time()
    target_col = _get_writable_col("pm_filter_features", pm_feat_db)
    if target_col is not None:
        try:
            await target_col.update_one(
                {"_id": "config"}, {"$set": {key: bool(value)}}, upsert=True
            )
        except Exception:
            pass


async def get_clean_words() -> list:
    global _CLEAN_WORDS_CACHE
    now = time.time()
    if now - _CLEAN_WORDS_CACHE[0] < 120:
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
    if now - _PROMO_CACHE[0] < 120:
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
    """
    Always removes & cleans:
    - Converts/removes all stylish Unicode fonts (e.g. 𝙆𝙖𝙣𝙩𝙖𝙧𝙖 -> Kantara, 𝖬𝗈𝗏𝗂𝖾 -> Movie, Ⓜⓞⓥⓘⓔ -> Movie)
    - Any word starting with '@' (e.g., @Sandalwood_Kannada, [@Channel_Name])
    - URLs & Telegram links
    - Custom clean words & default file extensions
    - All symbols/punctuation while preserving clean alphanumeric + Indic characters
    """
    if not name:
        return "File"

    name = strip_stylish_fonts(str(name))
    name = re.sub(r"(?i)https?://\S+|t\.me/\S+|www\.\S+", " ", name)
    name = re.sub(r"[\[\(\{<]*@[a-zA-Z0-9_.\-]+[\]\)\}>]*", " ", name)
    name = re.sub(r"@\S+", " ", name)

    if any(
        w.lower() in ["mkv", "sandalwood", "mp4", "avi", "webm", "zip", "rar"]
        for w in clean_words
    ):
        name = re.sub(r"(?i)\[?@?sandalwood[^\]\s]*\]?", " ", name)
        name = re.sub(r"(?i)\b(sandalwood|mkv|mp4|avi|webm|zip|rar)\b", " ", name)

    for word in clean_words:
        w_str = strip_stylish_fonts(str(word).strip())
        if not w_str or w_str == "@":
            continue
        if w_str.lower() in ["mkv", "sandalwood", "mp4", "avi", "webm", "zip", "rar"]:
            continue
        name = re.sub(rf"(?i){re.escape(w_str)}", " ", name)

    name = re.sub(r"[_.\-\+\[\]\(\)\{\}\|~`!#$%^&*=\\/:;\"'<>,?]+", " ", name)
    name = re.sub(r"[^\w\s\u0900-\u0D7F]", " ", name)
    name = re.sub(r"\s+", " ", name).strip()

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
    Cached auto-delete timer resolver (avoids 3 MongoDB queries on every group message).
    """
    cache_key = str(chat_id or "global")
    cached_val = AUTO_DELETE_TIMER_CACHE.get(cache_key)
    if cached_val is not None:
        return int(cached_val)

    resolved = default_time
    found = False

    if chat_id:
        try:
            g_set = await get_settings(chat_id) or {}
            if g_set.get("auto_delete") is False:
                AUTO_DELETE_TIMER_CACHE.set(cache_key, 0)
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
                        resolved = parsed
                        found = True
                        break
        except Exception:
            pass

    if not found:
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
                            resolved = 300 if parsed < 10 else parsed
                            found = True
                            break
                    except Exception:
                        continue
            if found:
                break

    AUTO_DELETE_TIMER_CACHE.set(cache_key, resolved)
    return resolved


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
    """Fast in-memory ban check using temp.BANNED_USERS (0ms latency)."""
    if not user_id:
        return False
    if hasattr(temp, "BANNED_USERS") and int(user_id) in temp.BANNED_USERS:
        return True
    return False


async def get_active_connection(user_id: str) -> Optional[int]:
    uid_str = str(user_id)

    for db_inst in _get_all_filter_dbs():
        try:
            doc = await db_inst["active_connections"].find_one({"user_id": uid_str})
            if doc and doc.get("group_id"):
                return int(doc["group_id"])
        except Exception:
            continue

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

    for db_inst in _get_all_filter_dbs():
        try:
            doc = await db_inst["CONNECTION"].find_one({"_id": uid_str})
            if doc and doc.get("active_group"):
                return int(doc["active_group"])
        except Exception:
            continue

    return None


async def get_target_chat(client: Client, message: Message) -> Optional[int]:
    if message.chat.type == enums.ChatType.PRIVATE:
        if not message.from_user:
            return None
        return await get_active_connection(str(message.from_user.id))
    return message.chat.id


async def verify_admin(
    client: Client, message: Message, target_chat_id: Optional[Any] = None
) -> bool:
    uid = (
        message.from_user.id
        if message.from_user
        else getattr(message.sender_chat, "id", 0)
    )
    if await is_global_admin(uid):
        return True

    if message.chat.type == enums.ChatType.PRIVATE:
        if not target_chat_id or str(target_chat_id) == "global":
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


# ============================================================
# 🛡️ QUOTA-PROOF MULTI-DB + RAM MANUAL FILTER STORAGE ENGINE
# ============================================================
async def safe_save_filter(
    group_id: Any,
    keyword: str,
    reply_text: str,
    btn: str,
    fileid: str,
    alert: str = "[]",
    media_type: str = "None",
):
    """
    Saves a manual filter across:
    1. In-memory RAM store (instant 0ms availability, never fails on 512MB DB quota)
    2. All healthy writable MongoDB databases (`manual_filters_v2` collection)
    3. Legacy `database.filters_mdb.add_filter` (wrapped in try/except so quota errors never crash commands)
    """
    gid_str = str(group_id)
    kw_clean = str(keyword).lower().strip()
    MANUAL_FILTERS_CACHE._data.pop(gid_str, None)
    MANUAL_FILTERS_CACHE._data.pop("global", None)

    doc_payload = {
        "group_id": gid_str,
        "text": kw_clean,
        "reply": reply_text or "",
        "btn": btn or "[]",
        "file": fileid or "None",
        "alert": alert or "[]",
        "media_type": media_type or "None",
        "updated_at": time.time(),
    }

    for target_key in {gid_str, "global"}:
        if target_key not in _RAM_FILTERS_STORE:
            _RAM_FILTERS_STORE[target_key] = {}
        _RAM_FILTERS_STORE[target_key][kw_clean] = dict(
            doc_payload, group_id=target_key
        )

    for db_inst in _get_all_filter_dbs():
        try:
            await db_inst["manual_filters_v2"].update_one(
                {"group_id": gid_str, "text": kw_clean},
                {"$set": doc_payload},
                upsert=True,
            )
            if gid_str != "global":
                await db_inst["manual_filters_v2"].update_one(
                    {"group_id": "global", "text": kw_clean},
                    {"$set": dict(doc_payload, group_id="global")},
                    upsert=True,
                )
        except Exception:
            continue

    if gid_str != "global":
        try:
            params = list(inspect.signature(add_filter).parameters.keys())
            if len(params) >= 6 and params[4] == "alert":
                await add_filter(group_id, kw_clean, reply_text, btn, alert, fileid)
            else:
                await add_filter(group_id, kw_clean, reply_text, btn, fileid, alert)
        except Exception:
            pass


async def safe_find_filter(
    group_id: Any, keyword: str
) -> Tuple[str, str, str, str, str]:
    """
    Returns `(reply_text, btn, alert, fileid, media_type)` from RAM, `manual_filters_v2`, or legacy `find_filter`.
    """
    gid_str = str(group_id)
    kw_clean = str(keyword).lower().strip()

    for k_gid in (gid_str, "global"):
        ram_doc = _RAM_FILTERS_STORE.get(k_gid, {}).get(kw_clean)
        if ram_doc:
            return (
                ram_doc.get("reply", ""),
                ram_doc.get("btn", "[]"),
                ram_doc.get("alert", "[]"),
                ram_doc.get("file", "None"),
                ram_doc.get("media_type", "None"),
            )

    for db_inst in _get_all_filter_dbs():
        for k_gid in (gid_str, "global"):
            try:
                doc = await db_inst["manual_filters_v2"].find_one(
                    {"group_id": k_gid, "text": kw_clean}
                )
                if doc:
                    _RAM_FILTERS_STORE.setdefault(k_gid, {})[kw_clean] = doc
                    return (
                        doc.get("reply", ""),
                        doc.get("btn", "[]"),
                        doc.get("alert", "[]"),
                        doc.get("file", "None"),
                        doc.get("media_type", "None"),
                    )
            except Exception:
                continue

    if gid_str != "global":
        try:
            reply_text, btn, alert, fileid = await find_filter(group_id, kw_clean)
            if str(fileid).strip() in ["[]", "None", ""] and str(alert).strip() not in [
                "[]",
                "None",
                "",
            ]:
                fileid, alert = alert, fileid
            if reply_text or (fileid and str(fileid) != "None"):
                return (
                    reply_text or "",
                    btn or "[]",
                    alert or "[]",
                    fileid or "None",
                    "None",
                )
        except Exception:
            pass

    return "", "[]", "[]", "None", "None"


async def safe_get_all_filters(group_id: Any) -> List[str]:
    """Returns all filter keywords for the group + global store across RAM and all healthy DBs."""
    gid_str = str(group_id)
    kw_set = set()

    for k_gid in (gid_str, "global"):
        for k in _RAM_FILTERS_STORE.get(k_gid, {}).keys():
            kw_set.add(k)

    for db_inst in _get_all_filter_dbs():
        try:
            cursor = db_inst["manual_filters_v2"].find(
                {"group_id": {"$in": [gid_str, "global"]}}, {"text": 1}
            )
            docs = await cursor.to_list(length=500)
            for d in docs:
                if d.get("text"):
                    kw_set.add(str(d["text"]).lower().strip())
        except Exception:
            continue

    if gid_str != "global":
        try:
            legacy_kws = await get_filters(group_id)
            for k in legacy_kws or []:
                if k:
                    kw_set.add(str(k).lower().strip())
        except Exception:
            pass

    return sorted(kw_set, key=len, reverse=True)


async def safe_delete_filter(message: Message, keyword: str, group_id: Any) -> bool:
    gid_str = str(group_id)
    kw_clean = str(keyword).lower().strip()
    MANUAL_FILTERS_CACHE._data.pop(gid_str, None)
    MANUAL_FILTERS_CACHE._data.pop("global", None)

    removed = False
    for k_gid in (gid_str, "global"):
        if kw_clean in _RAM_FILTERS_STORE.get(k_gid, {}):
            _RAM_FILTERS_STORE[k_gid].pop(kw_clean, None)
            removed = True

    for db_inst in _get_all_filter_dbs():
        try:
            res = await db_inst["manual_filters_v2"].delete_many(
                {"group_id": {"$in": [gid_str, "global"]}, "text": kw_clean}
            )
            if getattr(res, "deleted_count", 0) > 0:
                removed = True
        except Exception:
            continue

    if gid_str != "global":
        try:
            await delete_filter(message, kw_clean, group_id)
        except Exception:
            pass

    return removed


async def safe_delete_all_filters(message: Message, group_id: Any):
    gid_str = str(group_id)
    MANUAL_FILTERS_CACHE._data.pop(gid_str, None)
    MANUAL_FILTERS_CACHE._data.pop("global", None)
    _RAM_FILTERS_STORE.pop(gid_str, None)
    _RAM_FILTERS_STORE.pop("global", None)

    for db_inst in _get_all_filter_dbs():
        try:
            await db_inst["manual_filters_v2"].delete_many(
                {"group_id": {"$in": [gid_str, "global"]}}
            )
        except Exception:
            continue

    if gid_str != "global":
        try:
            keywords = await get_filters(group_id)
            for kw in keywords or []:
                await delete_filter(message, kw, group_id)
        except Exception:
            pass


def get_filter_state(key: str) -> dict:
    state = FILTER_STATE_CACHE.get(key)
    if not state or not isinstance(state, dict):
        return {"lang": None, "qual": None, "from_dym": False}
    return state


def set_filter_state(
    key: str,
    lang: Optional[str] = None,
    qual: Optional[str] = None,
    from_dym: Optional[bool] = None,
):
    prev = get_filter_state(key)
    FILTER_STATE_CACHE.set(
        key,
        {
            "lang": lang,
            "qual": qual,
            "from_dym": prev.get("from_dym", False) if from_dym is None else from_dym,
        },
    )


def build_effective_search_query(base_query: str, state: dict) -> str:
    parts = [base_query]
    lang_code = state.get("lang")
    qual_val = state.get("qual")
    if lang_code and lang_code in LANG_MAP:
        parts.append(LANG_MAP[lang_code].lower())
    if qual_val:
        parts.append(qual_val.lower())
    return " ".join(p for p in parts if p).strip()


# ============================================================
# 🔮 ULTRA-FAST SEARCH, FALLBACK DB ENGINE & DEDUPLICATION
# ============================================================
def sanitize_search_query(text: str, allow_translit: bool = True) -> str:
    if not text:
        return ""
    text = strip_stylish_fonts(text)
    if allow_translit and has_indic_script(text):
        text = transliterate_indic_to_english(text)

    raw_q = re.sub(r"https?://\S+|t\.me/\S+|@\w+", "", text.strip().lower())
    basic_q = re.sub(r"[^a-zA-Z0-9]", " ", raw_q)
    basic_q = re.sub(r"\s+", " ", basic_q).strip()

    q = re.sub(
        r"(?i)\b(4320p|2160p|1440p|1080p|720p|540p|480p|360p|240p|144p|4k|2k|8k|mkv|mp4|avi|hdrip|web-?dl|webrip|bluray|brrip|dvdrip|x264|x265|hevc|aac\d*|ddp?\d*|\d+ch|10bit|8bit|hdr|sdr|dual audio|multi audio|hindi|kannada|tulu|telugu|tamil|malayalam|marathi|gujarati|bengali|punjabi|nepali|english|subtitles|subs|esub|episodes|season\s*\d+|s\d+e\d+|complete)\b",
        "",
        raw_q,
    )
    q = re.sub(r"[^a-zA-Z0-9]", " ", q)
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
    cleaned = re.sub(r"\s+", " ", q).strip()
    return cleaned if cleaned else basic_q


def extract_inline_lang_and_qual(raw_text: str) -> Tuple[Optional[str], Optional[str]]:
    norm_raw = strip_stylish_fonts(raw_text)
    detected_lang = None
    detected_qual = None
    for code, pattern in LANG_PATTERNS.items():
        if pattern.search(norm_raw):
            detected_lang = code
            break
    for qual, pattern in QUAL_PATTERNS.items():
        if pattern.search(norm_raw):
            detected_qual = qual
            break
    return detected_lang, detected_qual


async def _direct_collection_search(
    query: str, max_results: int = 10, offset: int = 0
) -> Tuple[list, int, int]:
    """
    Fallback direct search on healthy Media collections across all /datadb clusters.
    """
    q_clean = query.strip()
    if not q_clean:
        return [], 0, 0

    words = [re.escape(w) for w in re.split(r"\s+", q_clean) if w]
    if not words:
        return [], 0, 0

    pattern_str = ".*".join(words)
    regex = re.compile(pattern_str, re.IGNORECASE)
    mongo_filter = (
        {"$or": [{"file_name": regex}, {"caption": regex}]}
        if getattr(info, "USE_CAPTION_FILTER", False)
        else {"file_name": regex}
    )

    results = []
    if callable(get_all_healthy_read_dbs):
        for idx, target_db in get_all_healthy_read_dbs():
            try:
                docs = (
                    await target_db[info.COLLECTION_NAME]
                    .find(mongo_filter)
                    .sort("_id", -1)
                    .limit(max_results + offset)
                    .to_list(length=max_results + offset)
                )
                if docs:
                    results.extend(docs)
            except Exception as e:
                if callable(mark_db_error):
                    mark_db_error(idx, e)
                continue
    elif _Media is not None:
        col = getattr(_Media, "collection", _Media)
        try:
            docs = (
                await col.find(mongo_filter)
                .sort("_id", -1)
                .limit(max_results + offset)
                .to_list(length=max_results + offset)
            )
            if docs:
                results.extend(docs)
        except Exception:
            pass

    total = len(results)
    sliced = results[offset : offset + max_results]
    next_off = offset + max_results if (offset + max_results) < total else 0
    return sliced, next_off, total


async def safe_search_db(query: str, max_results: int = 10, offset: int = 0):
    if _DEAD_COLLECTIONS.get("get_search_results", 0.0) > time.time():
        return await _direct_collection_search(
            query, max_results=max_results, offset=offset
        )

    try:
        return await get_search_results(
            query,
            max_results=max_results,
            offset=offset,
            filter=True,
            is_autocorrect=True,
        )
    except TypeError:
        try:
            return await get_search_results(
                query, max_results=max_results, offset=offset, filter=True
            )
        except TypeError:
            try:
                return await get_search_results(
                    query, max_results=max_results, offset=offset
                )
            except Exception:
                _DEAD_COLLECTIONS["get_search_results"] = time.time() + 300
                return await _direct_collection_search(
                    query, max_results=max_results, offset=offset
                )
        except Exception:
            _DEAD_COLLECTIONS["get_search_results"] = time.time() + 300
            return await _direct_collection_search(
                query, max_results=max_results, offset=offset
            )
    except Exception:
        _DEAD_COLLECTIONS["get_search_results"] = time.time() + 300
        return await _direct_collection_search(
            query, max_results=max_results, offset=offset
        )


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
    return strip_stylish_fonts(f"{fname or ''} {fcap or ''}").lower()


def _is_kannada_file(file_obj) -> bool:
    """Detects if a file is Kannada via filename/caption tags or Kannada script."""
    txt = _file_text(file_obj)
    if LANG_PATTERNS["kan"].search(txt):
        return True
    return any(0x0C80 <= ord(ch) <= 0x0CFF for ch in txt)


def _normalize_dedup_name(raw_name: str, clean_words: list) -> str:
    """Normalizes a filename for deduplication (strips stylish fonts, @usernames, extensions, symbols, and case)."""
    s = strip_stylish_fonts(str(raw_name or "")).lower()
    s = re.sub(r"(?i)https?://\S+|t\.me/\S+|www\.\S+", " ", s)
    s = re.sub(r"[\[\(\{<]*@[a-zA-Z0-9_.\-]+[\]\)\}>]*", " ", s)
    s = re.sub(r"@\S+", " ", s)
    s = re.sub(r"\b(sandalwood|mkv|mp4|avi|webm|zip|rar)\b", " ", s)
    for word in clean_words:
        w_str = strip_stylish_fonts(str(word).strip()).lower()
        if w_str and w_str != "@":
            s = re.sub(rf"{re.escape(w_str)}", " ", s)
    s = re.sub(r"[^a-z0-9\u0900-\u0D7F]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _deduplicate_files(files: list, clean_words: list) -> list:
    """
    Removes duplicate files that have the same normalized filename AND same file size
    (or identical file_id).
    """
    unique_files = []
    seen_ids = set()
    seen_name_size = set()

    for f in files:
        fid = str(
            f.get("file_id", f.get("_id", ""))
            if isinstance(f, dict)
            else getattr(f, "file_id", getattr(f, "_id", ""))
        )
        if fid and fid in seen_ids:
            continue

        raw_name = str(
            f.get("file_name", "")
            if isinstance(f, dict)
            else getattr(f, "file_name", "")
        )
        fsize = int(
            f.get("file_size", 0) if isinstance(f, dict) else getattr(f, "file_size", 0)
        )
        norm_name = _normalize_dedup_name(raw_name, clean_words)
        dedup_key = (norm_name, fsize)

        if norm_name and dedup_key in seen_name_size:
            continue

        if fid:
            seen_ids.add(fid)
        if norm_name:
            seen_name_size.add(dedup_key)
        unique_files.append(f)

    return unique_files


def _score_file_relevance(file_obj, query_str: str) -> Tuple[int, int, int]:
    """
    Scores files so that:
    1. Exact/matching movie title with KANNADA language always appears FIRST.
    2. Exact title relevance comes next.
    3. Larger/better quality file size breaks ties.
    """
    fname = strip_stylish_fonts(
        str(
            file_obj.get("file_name", "")
            if isinstance(file_obj, dict)
            else getattr(file_obj, "file_name", "")
        )
    ).lower()
    fsize = int(
        file_obj.get("file_size", 0)
        if isinstance(file_obj, dict)
        else getattr(file_obj, "file_size", 0)
    )
    clean_fname = re.sub(r"@[a-zA-Z0-9_.\-]+", " ", fname)
    clean_fname = re.sub(r"[^a-zA-Z0-9]", " ", clean_fname)
    clean_fname = re.sub(r"\s+", " ", clean_fname).strip()

    q_lower = query_str.lower().strip()
    tokens = [t for t in q_lower.split() if t]

    title_match_score = 0
    if clean_fname.startswith(q_lower):
        title_match_score += 100
    elif q_lower in clean_fname:
        title_match_score += 70
    if tokens and all(re.search(rf"\b{re.escape(t)}\b", clean_fname) for t in tokens):
        title_match_score += 50

    is_kan = 1 if _is_kannada_file(file_obj) else 0
    kannada_priority = 1 if (is_kan and title_match_score > 0) else is_kan

    return (kannada_priority, title_match_score, fsize)


async def smart_filtered_search(
    base_query: str, state: dict, max_results: int = 10, offset: int = 0
) -> Tuple[list, int, int]:
    lang_code = state.get("lang")
    qual_val = state.get("qual")
    clean_words = await get_clean_words()

    pool_cache_key = f"pool:{base_query}:{lang_code or 'all'}:{qual_val or 'all'}"
    deduped = POOL_SEARCH_CACHE.get(pool_cache_key)

    if deduped is None:
        pool_limit = 100 if (lang_code or qual_val) else 60
        pool, _, _ = await safe_search_db(base_query, max_results=pool_limit, offset=0)

        if not pool and (lang_code or qual_val):
            effective_query = build_effective_search_query(base_query, state)
            pool, _, _ = await safe_search_db(
                effective_query, max_results=pool_limit, offset=0
            )

        if not pool:
            return [], 0, 0

        lang_regex = LANG_PATTERNS.get(lang_code) if lang_code else None
        qual_regex = QUAL_PATTERNS.get(qual_val) if qual_val else None

        matched = []
        for f in pool:
            combined_txt = _file_text(f)
            if lang_regex and not lang_regex.search(combined_txt):
                continue
            if qual_regex and not qual_regex.search(combined_txt):
                continue
            matched.append(f)

        deduped = _deduplicate_files(matched, clean_words)
        deduped.sort(key=lambda x: _score_file_relevance(x, base_query), reverse=True)
        POOL_SEARCH_CACHE.set(pool_cache_key, deduped)

    total_matched = len(deduped)
    sliced = deduped[offset : offset + max_results]
    new_next_offset = (
        offset + max_results if (offset + max_results) < total_matched else 0
    )
    return sliced, new_next_offset, total_matched


def _extract_clean_movie_title(raw_filename: str) -> str:
    """Extracts a clean movie title without audio/codec suffixes."""
    if not raw_filename:
        return ""
    s = strip_stylish_fonts(raw_filename)
    s = re.sub(r"https?://\S+|t\.me/\S+|@\w+|\[[^\]]*\]|\([^)]*\)", " ", s)
    s = re.sub(r"[_.-]", " ", s)
    s = re.split(
        r"(?i)\b(4320p|2160p|1440p|1080p|720p|540p|480p|360p|240p|144p|4k|2k|8k|hdrip|web-?dl|webrip|bluray|brrip|dvdrip|camrip|hdts|predvd|x264|x265|hevc|avc|aac\d*|ddp?\d*|dd\d*|ac3|eac3|atmos|10bit|8bit|hdr|sdr|dual\s*audio|multi\s*audio|kannada|tulu|telugu|tamil|malayalam|hindi|english|marathi|gujarati|bengali|punjabi|nepali|esub|subtitles|mkv|mp4|avi)\b",
        s,
    )[0]
    s = re.sub(r"[^a-zA-Z0-9\s]", " ", s)
    s = re.sub(r"\b(?!(?:19|20)\d{2}\b)\d{1,3}\b$", "", s.strip())
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) < 2:
        return sanitize_search_query(raw_filename)
    words = s.split()
    return " ".join(words[:5]).lower()


async def get_cached_db_titles() -> List[str]:
    db_titles = FUZZY_TITLES_CACHE.get("titles")
    if db_titles is not None:
        return db_titles

    title_set = set()
    if callable(get_all_healthy_read_dbs):
        for idx, target_db in get_all_healthy_read_dbs():
            try:
                sample_docs = (
                    await target_db[info.COLLECTION_NAME]
                    .find({}, {"file_name": 1})
                    .sort("_id", -1)
                    .limit(1000)
                    .to_list(length=1000)
                )
                for d in sample_docs:
                    fn = d.get("file_name", "")
                    if not fn:
                        continue
                    clean_t = _extract_clean_movie_title(fn)
                    if clean_t and len(clean_t) >= 2:
                        title_set.add(clean_t)
            except Exception as e:
                if callable(mark_db_error):
                    mark_db_error(idx, e)
                continue
    elif _Media is not None:
        try:
            media_col = getattr(_Media, "collection", _Media)
            sample_docs = (
                await media_col.find({}, {"file_name": 1})
                .sort("_id", -1)
                .limit(1000)
                .to_list(length=1000)
            )
            for d in sample_docs:
                fn = d.get("file_name", "")
                if not fn:
                    continue
                clean_t = _extract_clean_movie_title(fn)
                if clean_t and len(clean_t) >= 2:
                    title_set.add(clean_t)
        except Exception:
            pass

    db_titles = sorted(title_set)
    FUZZY_TITLES_CACHE.set("titles", db_titles)
    return db_titles


# ============================================================
# 💡 FAST "DID YOU MEAN?" MULTI-CHOICE SUGGESTIONS FINDER
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
        if best_score >= 0.48:
            scored_candidates.append((best_score, t_lower))

    scored_candidates.sort(key=lambda x: x[0], reverse=True)

    unique_suggestions: List[str] = []
    seen_roots = set()

    for _, cand in scored_candidates:
        if len(unique_suggestions) >= max_suggestions:
            break
        root_key = re.sub(r"\b\d+\b", "", cand).strip()
        root_key = re.sub(r"\s+", " ", root_key)
        if not root_key or root_key in seen_roots:
            continue
        seen_roots.add(root_key)
        unique_suggestions.append(cand)

    return unique_suggestions


def _build_dym_view(
    mention: str, raw_search: str, req: int, key: str, suggestions: List[str]
) -> Tuple[str, InlineKeyboardMarkup]:
    safe_typed = (
        html.escape(strip_stylish_fonts(raw_search).strip() or raw_search.strip())
        if raw_search
        else "Movie"
    )
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
    return dym_text, InlineKeyboardMarkup(dym_btns)


async def god_tier_search(
    query: str, allow_translit: bool = True, allow_fuzzy: bool = True
) -> Tuple[list, int, int, str, bool]:
    was_transliterated = bool(allow_translit and has_indic_script(query))
    translit_variants = (
        generate_phonetic_variants(transliterate_indic_to_english(query))
        if was_transliterated
        else []
    )

    clean_query = sanitize_search_query(query, allow_translit=allow_translit)
    if not clean_query and not translit_variants:
        return [], 0, 0, query, False

    default_state = {"lang": None, "qual": None, "from_dym": False}

    if translit_variants:
        for variant in translit_variants:
            v_clean = sanitize_search_query(variant, allow_translit=False)
            if not v_clean:
                continue
            files, offset, total = await smart_filtered_search(
                v_clean, default_state, max_results=10, offset=0
            )
            if files:
                return files, offset, total, v_clean, True

    is_short_query = len(clean_query) <= 2

    files, offset, total = await smart_filtered_search(
        clean_query, default_state, max_results=10, offset=0
    )
    if files:
        return files, offset, total, clean_query, was_transliterated

    raw_alnum = re.sub(r"[^a-zA-Z0-9]", " ", strip_stylish_fonts(query).lower())
    raw_alnum = re.sub(r"\s+", " ", raw_alnum).strip()
    if raw_alnum and raw_alnum != clean_query:
        files, offset, total = await smart_filtered_search(
            raw_alnum, default_state, max_results=10, offset=0
        )
        if files:
            return files, offset, total, raw_alnum, was_transliterated

    no_year_query = re.sub(r"\b(19\d{2}|20\d{2})\b", "", clean_query).strip()
    no_year_query = re.sub(r"\s+", " ", no_year_query)
    if no_year_query and no_year_query != clean_query and len(no_year_query) > 2:
        files, offset, total = await smart_filtered_search(
            no_year_query, default_state, max_results=10, offset=0
        )
        if files:
            return files, offset, total, no_year_query, was_transliterated

    if is_short_query or not allow_fuzzy:
        return [], 0, 0, query, False

    try:
        db_titles = await get_cached_db_titles()
        if matches := difflib.get_close_matches(
            clean_query, db_titles, n=1, cutoff=0.72
        ):
            corrected_query = matches[0]
            c_files, c_offset, c_total = await smart_filtered_search(
                corrected_query, default_state, max_results=10, offset=0
            )
            if c_files:
                return c_files, c_offset, c_total, corrected_query, True
    except Exception as e:
        logger.error(f"Fuzzy search fallback error: {e}")

    return [], 0, 0, clean_query or query, False


# ============================================================
# 🧩 KEYBOARD BUILDER FOR AUTO-FILTER RESULTS (FIXED SHORTENER SCOPE)
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
    has_active_filter = bool(active_lang or active_qual)
    from_dym = bool(state.get("from_dym") and SUGGESTIONS_CACHE.get(key))

    lang_btn_text = f"🔊 {active_lang}" if active_lang else "🔊"
    qual_btn_text = f"🎥 {active_qual}" if active_qual else "🎥"

    btn = [
        [
            create_btn(
                text="🎖️Lᴀᴛᴇsᴛ Mᴏᴠɪᴇ Uᴘᴅᴀᴛᴇs🎖️",
                url="https://t.me/+8Mw-Y-fYN6hiZWZl",
                style=BTN_PRIMARY,
            )
        ],
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

    promos = await get_active_promos()
    for p in promos[:2]:
        btn.append([create_btn(text=p["text"], url=p["url"])])

    # FIXED: Always define shortener_on outside the promo loop so it never raises UnboundLocalError
    try:
        shortener_on = bool(await is_shortener_active())
    except Exception:
        shortener_on = False

    for file in files:
        file_id = str(
            file.get("file_id", file.get("_id", ""))
            if isinstance(file, dict)
            else getattr(file, "file_id", getattr(file, "_id", ""))
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

        display_name = clean_filename(raw_name, clean_words)
        size_str = get_size(file_size)
        url_payload = f"https://t.me/{bot_username}?start={pre}_{file_id}"
        cb_payload = f"shrtget#{pre}#{file_id}"

        if settings.get("button", False):
            btn.append(
                [
                    create_btn(
                        text=f"{size_str} | {display_name}",
                        callback_data=cb_payload if shortener_on else None,
                        url=None if shortener_on else url_payload,
                    )
                ]
            )
        else:
            btn.append(
                [
                    create_btn(
                        text=f"{display_name}",
                        callback_data=cb_payload if shortener_on else None,
                        url=None if shortener_on else url_payload,
                    ),
                    create_btn(
                        text=f"{size_str}",
                        callback_data=cb_payload if shortener_on else None,
                        url=None if shortener_on else url_payload,
                    ),
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
    page_cb = f"pages#{current_page}#{total_pages}#{total_results}"

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

    btn.append(nav_row)
    return btn


# For link shortener
@Client.on_callback_query(filters.regex(r"^shrtget#"), group=-2)
async def on_demand_shortener_file_callback(bot: Client, query: CallbackQuery):
    """
    Converts ONLY the single file link that the user clicked!
    """
    try:
        _, pre, file_id = query.data.split("#", 2)
    except ValueError:
        return await safe_answer(query, "⚠️ Invalid file link!", show_alert=True)

    if not getattr(temp, "U_NAME", None):
        me = await bot.get_me()
        temp.U_NAME = me.username
        temp.B_NAME = me.first_name
        temp.ME = me.id
    bot_username = temp.U_NAME or "bot"

    long_url = f"https://t.me/{bot_username}?start={pre}_{file_id}"

    # If shortener was turned off in the meantime, open the bot deep-link directly
    if not await is_shortener_active():
        try:
            return await query.answer(url=long_url)
        except Exception:
            return

    await safe_answer(query, "⏳ Generating your download link...", show_alert=False)
    short_url = await shorten_single_url(long_url)

    mention = query.from_user.mention if query.from_user else "User"
    link_kb = InlineKeyboardMarkup(
        [
            [
                create_btn(
                    text="🔓 Click Here To Get File 📥",
                    url=short_url,
                    style=BTN_SUCCESS,
                )
            ]
        ]
    )

    # Try sending the converted link to the user's PM first; if they haven't started the bot, reply in group
    sent_msg = None
    if query.from_user:
        try:
            sent_msg = await bot.send_message(
                chat_id=query.from_user.id,
                text=(
                    f"<b>Hᴇʏ {mention} 👋🏻\n\n"
                    f"✅ Yᴏᴜʀ Fɪʟᴇ Lɪɴᴋ Iꜱ Rᴇᴀᴅʏ!\n"
                    f"👇 Cʟɪᴄᴋ Tʜᴇ Bᴜᴛᴛᴏɴ Bᴇʟᴏᴡ Tᴏ Oᴘᴇɴ & Gᴇᴛ Yᴏᴜʀ Fɪʟᴇ:</b>"
                ),
                reply_markup=link_kb,
                parse_mode=enums.ParseMode.HTML,
            )
        except Exception:
            sent_msg = None

    if not sent_msg and query.message:
        k_msg = await safe_reply_text(
            query.message,
            text=(
                f"<b>Hᴇʏ {mention} 👋🏻\n\n" f"✅ Yᴏᴜʀ Fɪʟᴇ Lɪɴᴋ Iꜱ Rᴇᴀᴅʏ Bᴇʟᴏᴡ 👇</b>"
            ),
            reply_markup=link_kb,
            parse_mode=enums.ParseMode.HTML,
        )
        delete_timer = await resolve_auto_delete_timer(
            query.message.chat.id, default_time=300
        )
        if delete_timer > 0 and k_msg:
            schedule_auto_delete(bot, query.message.chat.id, False, delete_timer, k_msg)


# ============================================================
# ⏳ RELIABLE AUTO-DELETE ENGINE (GROUP + PM)
# ============================================================
def _get_deleted_file_notify_keyboard() -> InlineKeyboardMarkup:
    req_grp_url = getattr(
        info, "GRP_LNK", "https://t.me/Sandalwood_Kannada_Group"
    )
    return InlineKeyboardMarkup(
        [
            [
                create_btn(
                    "Movie Request 📝",
                    url=req_grp_url,
                )
            ]
        ]
    )


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
        markup = _get_deleted_file_notify_keyboard()
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
# 📁 CORE AUTO FILTER ENGINE (INSTANT RESPONSE)
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

        raw_msg_text = re.sub(r"https?://\S+|t\.me/\S+|@\w+", "", msg.text).strip()
        search = strip_stylish_fonts(raw_msg_text).strip() or raw_msg_text
        if not search:
            return

        if search.lower() in [
            "hello",
            "hey",
            "hlo",
            "hlw",
            "bro",
            "sir",
            "ok",
            "okay",
            "k",
            "thank you",
            "thanks",
            "tq",
            "yes",
            "no",
            "yo",
            "hmm",
            "hm",
            "gm",
            "gn",
            "good morning",
        ]:
            return

        (autotranslate_on, multichoice_on), b_set, settings = await asyncio.gather(
            get_feature_flags(),
            get_bot_settings(),
            get_settings(msg.chat.id),
        )
        b_set = b_set or {}
        settings = settings or {}

        spell_check_on = bool(settings.get("spell_check", True))

        if has_indic_script(search) and not autotranslate_on:
            fnf_img = b_set.get("not_found_img") or getattr(info, "NOT_FOUND_IMG", None)
            fnf_txt = b_set.get("not_found_text") or getattr(
                info, "NOT_FOUND_MSG", "<b>🚫 File not found.</b>"
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

        inline_lang, inline_qual = extract_inline_lang_and_qual(search)

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
            fnf_img = b_set.get("not_found_img") or getattr(info, "NOT_FOUND_IMG", None)
            fnf_txt = b_set.get("not_found_text") or getattr(
                info, "NOT_FOUND_MSG", "<b>🚫 File not found.</b>"
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

        if inline_lang or inline_qual:
            inline_state = {"lang": inline_lang, "qual": inline_qual, "from_dym": False}
            f_files, f_offset, f_total = await smart_filtered_search(
                search_query, inline_state, max_results=10, offset=0
            )
            if f_files:
                files, offset, total_results = f_files, f_offset, f_total
                set_filter_state(
                    key, lang=inline_lang, qual=inline_qual, from_dym=False
                )
            else:
                set_filter_state(key, lang=None, qual=None, from_dym=False)
        else:
            set_filter_state(key, lang=None, qual=None, from_dym=False)

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

        safe_orig_title = html.escape(strip_stylish_fonts(search).title())
        safe_corr_title = html.escape(strip_stylish_fonts(search_query).title())
        was_indic = bool(autotranslate_on and has_indic_script(raw_msg_text))

        if was_indic:
            cap = (
                f"<b>Hᴇʏ {mention} 👋🏻\n\n"
                f"🔤 Tʀᴀɴsʟɪᴛᴇʀᴀᴛᴇᴅ : <code>{html.escape(raw_msg_text)}</code> ➔ <code>{safe_corr_title}</code>\n"
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

        auto_img = b_set.get("auto_img") or getattr(info, "AUTO_IMG", None)
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
# 👉 END OF PART 1 — PASTE PART 2 DIRECTLY BELOW THIS LINE
# ============================================================
