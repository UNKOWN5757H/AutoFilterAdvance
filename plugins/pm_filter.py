import ast
import asyncio
import difflib
import hashlib
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


logger = getLogger(__name__)
logger.setLevel(ERROR)

AUTO_DELETE_TASKS = set()
_DEAD_COLLECTIONS: Dict[str, float] = {}

# ============================================================
# 🔤 COMPLETE STYLISH UNICODE FONT STRIPPER / NORMALIZER ENGINE
# ============================================================
_STYLISH_CHAR_MAP: Dict[int, str] = {}

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

for _i in range(26):
    _STYLISH_CHAR_MAP[0x24B6 + _i] = chr(ord("A") + _i)
    _STYLISH_CHAR_MAP[0x24D0 + _i] = chr(ord("a") + _i)
    _STYLISH_CHAR_MAP[0x1F110 + _i] = chr(ord("A") + _i)
    _STYLISH_CHAR_MAP[0x1F130 + _i] = chr(ord("A") + _i)
    _STYLISH_CHAR_MAP[0x1F150 + _i] = chr(ord("A") + _i)
    _STYLISH_CHAR_MAP[0x1F170 + _i] = chr(ord("A") + _i)
    _STYLISH_CHAR_MAP[0x1F1E6 + _i] = chr(ord("A") + _i)

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

for _d_start in (0x1D7CE, 0x1D7D8, 0x1D7E2, 0x1D7EC, 0x1D7F6):
    for _i in range(10):
        _STYLISH_CHAR_MAP[_d_start + _i] = str(_i)


def strip_stylish_fonts(text: str) -> str:
    if not text:
        return ""
    text = text.translate(_STYLISH_CHAR_MAP)
    out_chars: List[str] = []
    for ch in text:
        cp = ord(ch)
        if 0x0900 <= cp <= 0x0D7F:
            out_chars.append(ch)
        elif 0x0300 <= cp <= 0x036F or 0x20D0 <= cp <= 0x20FF or 0xFE00 <= cp <= 0xFE0F:
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
# 🔗 CUSTOM EXTRA BUTTON LINKS (HIDDEN BEHIND CALLBACK BUTTONS)
# ============================================================
EXTRA_BTN_1_URL = getattr(info, "EXTRA_BTN_1_URL", "https://t.me/+lcTawsnhdi0zYWE1")
EXTRA_BTN_2_URL = getattr(info, "EXTRA_BTN_2_URL", "https://t.me/linkz_ki_duniyaa")
LATEST_UPDATES_URL = getattr(info, "LATEST_UPDATES_URL", "https://t.me/+8Mw-Y-fYN6hiZWZl")

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
                out.append(
                    "m" if (0x2A <= next_offset <= 0x2E or next_offset == 0) else "n"
                )
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
                out.append(
                    base_c
                    if (is_devanagari and is_word_end and len(out) > 0)
                    else (base_c + "a")
                )
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

    return re.sub(r"\s+", " ", "".join(out)).strip().lower()


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
    )
    if v1 not in variants:
        variants.append(v1)
    v2_words = [(w[:-1] if len(w) > 4 and w.endswith("a") else w) for w in v1.split()]
    v2 = " ".join(v2_words)
    if v2 and v2 not in variants:
        variants.append(v2)
    return variants


# ============================================================
# 🛡️ PYROGRAM v2.2.26 COMPATIBILITY & HIDDEN-LINK BUTTON ENGINE
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

BTN_PRIMARY = None
BTN_SUCCESS = None
BTN_DANGER = None
_SUPPORTS_BTN_STYLE = False
_BTN_ICON_PARAM: Optional[str] = None
_BTN_ICON_WANTS_INT = False

try:
    from pyrogram.enums import ButtonStyle

    _btn_sig_params = inspect.signature(InlineKeyboardButton.__init__).parameters
    if "style" in _btn_sig_params:
        BTN_PRIMARY = getattr(ButtonStyle, "PRIMARY", None)
        BTN_SUCCESS = getattr(ButtonStyle, "SUCCESS", None)
        BTN_DANGER = getattr(ButtonStyle, "DANGER", None)
        _SUPPORTS_BTN_STYLE = True
    for _cand_icon_param in ("icon_custom_emoji_id", "custom_emoji_id", "icon_id"):
        if _cand_icon_param in _btn_sig_params:
            _BTN_ICON_PARAM = _cand_icon_param
            _ann = str(_btn_sig_params[_cand_icon_param].annotation).lower()
            _BTN_ICON_WANTS_INT = "int" in _ann and "str" not in _ann
            break
except (ImportError, ValueError, TypeError):
    pass

_TG_EMOJI_RE = re.compile(
    r'<tg-emoji\s+emoji-id=["\']?(\d+)["\']?\s*>(.*?)</tg-emoji>',
    re.IGNORECASE | re.DOTALL,
)


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
FUZZY_TITLES_CACHE = TTLCache(maxsize=10, ttl=1800)
RESTRICTED_WRITE_CHATS = TTLCache(maxsize=500, ttl=300)

# Shared hidden-link registry: maps short callback tokens -> target URLs
HIDDEN_LINKS_STORE: Dict[str, str] = {}
_HIDDEN_LINKS_MAX = 15000


def register_hidden_link(url: str) -> str:
    clean_u = str(url or "").strip()
    if clean_u and not clean_u.startswith(("http://", "https://", "tg://")):
        clean_u = "https://" + clean_u.lstrip("/")
    token = hashlib.md5(clean_u.encode("utf-8")).hexdigest()[:12]
    if len(HIDDEN_LINKS_STORE) >= _HIDDEN_LINKS_MAX:
        HIDDEN_LINKS_STORE.pop(next(iter(HIDDEN_LINKS_STORE)), None)
    HIDDEN_LINKS_STORE[token] = clean_u
    return token


def resolve_hidden_link(token: str) -> Optional[str]:
    return HIDDEN_LINKS_STORE.get(str(token or "").strip())


def _clean_button_label(raw_label: str) -> str:
    lbl = re.sub(r"<[^>]+>", "", str(raw_label or "")).strip()
    lbl = re.sub(r"(?i)https?://\S+|t\.me/\S+|www\.\S+", "", lbl).strip(" -|:")
    return lbl or "Open"


def _extract_icon_and_clean_label(
    raw_label: str, icon_id: Optional[Any] = None
) -> Tuple[str, Optional[str]]:
    s = str(raw_label or "")
    resolved_icon = str(icon_id).strip() if icon_id else None
    if not resolved_icon:
        m = _TG_EMOJI_RE.search(s)
        if m:
            resolved_icon = m.group(1).strip()
            s = _TG_EMOJI_RE.sub("" if _BTN_ICON_PARAM else m.group(2), s, count=1)
    elif _TG_EMOJI_RE.search(s):
        s = _TG_EMOJI_RE.sub("", s)
    return _clean_button_label(s), (
        resolved_icon if (resolved_icon and resolved_icon.isdigit()) else None
    )


def _get_btn_icon_id(btn: InlineKeyboardButton) -> Optional[str]:
    for attr in ("icon_custom_emoji_id", "custom_emoji_id", "icon_id"):
        val = getattr(btn, attr, None)
        if val:
            return str(val).strip()
    return None


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
    icon_custom_emoji_id: Optional[Any] = None,
) -> InlineKeyboardButton:
    clean_text, resolved_icon = _extract_icon_and_clean_label(
        text, icon_custom_emoji_id
    )
    kwargs: Dict[str, Any] = {"text": clean_text}

    if callback_data:
        kwargs["callback_data"] = str(callback_data)[:64]
    elif url:
        token = register_hidden_link(url)
        kwargs["callback_data"] = f"olink#{token}"
    else:
        kwargs["callback_data"] = "noop"

    norm_style = _normalize_style(style)
    if norm_style is not None:
        kwargs["style"] = norm_style

    if _BTN_ICON_PARAM and resolved_icon:
        kwargs[_BTN_ICON_PARAM] = (
            int(resolved_icon) if _BTN_ICON_WANTS_INT else str(resolved_icon)
        )

    try:
        return InlineKeyboardButton(**kwargs)
    except Exception:
        if _BTN_ICON_PARAM and _BTN_ICON_PARAM in kwargs:
            alt_val = (
                str(resolved_icon)
                if isinstance(kwargs[_BTN_ICON_PARAM], int)
                else int(resolved_icon)
            )
            kwargs[_BTN_ICON_PARAM] = alt_val
            try:
                return InlineKeyboardButton(**kwargs)
            except Exception:
                kwargs.pop(_BTN_ICON_PARAM, None)
        kwargs.pop("style", None)
        return InlineKeyboardButton(**kwargs)


def sanitize_markup_hide_links(
    markup: Optional[InlineKeyboardMarkup],
) -> Optional[InlineKeyboardMarkup]:
    if not markup or not getattr(markup, "inline_keyboard", None):
        return markup
    new_rows: List[List[InlineKeyboardButton]] = []
    for row in markup.inline_keyboard:
        new_row: List[InlineKeyboardButton] = []
        for b in row:
            st = getattr(b, "style", None)
            ic = _get_btn_icon_id(b)
            if getattr(b, "url", None):
                new_row.append(
                    create_btn(
                        text=b.text, url=b.url, style=st, icon_custom_emoji_id=ic
                    )
                )
            else:
                new_row.append(
                    create_btn(
                        text=b.text,
                        callback_data=getattr(b, "callback_data", "noop"),
                        style=st,
                        icon_custom_emoji_id=ic,
                    )
                )
        if new_row:
            new_rows.append(new_row)
    return InlineKeyboardMarkup(new_rows) if new_rows else None


async def safe_reply_text(
    msg: Message,
    text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    parse_mode: enums.ParseMode = enums.ParseMode.HTML,
) -> Optional[Message]:
    if not msg:
        return None
    reply_markup = sanitize_markup_hide_links(reply_markup)
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
    if not msg:
        return None
    reply_markup = sanitize_markup_hide_links(reply_markup)
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
    url: Optional[str] = None,
):
    if not query:
        return
    try:
        kwargs: Dict[str, Any] = {"show_alert": show_alert}
        if text is not None:
            kwargs["text"] = str(text)[:200]
        if url is not None:
            kwargs["url"] = url
        await query.answer(**kwargs)
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
    ")",
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


async def resolve_auto_delete_timer(
    chat_id: Optional[int] = None, default_time: int = 300
) -> int:
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
    return bool(user_id and int(user_id) in get_admin_list())


async def is_user_banned(user_id: int) -> bool:
    return bool(
        user_id and hasattr(temp, "BANNED_USERS") and int(user_id) in temp.BANNED_USERS
    )


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
        _RAM_FILTERS_STORE.setdefault(target_key, {})[kw_clean] = dict(
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
# 🔮 PRECISION SEARCH, MULTI-DB FALLBACK & DEDUPLICATION ENGINE
# ============================================================
_ROMAN_TO_DIGIT = (
    (re.compile(r"(?i)\bpart\s+i\b"), "part 1"),
    (re.compile(r"(?i)\bpart\s+ii\b"), "part 2"),
    (re.compile(r"(?i)\bpart\s+iii\b"), "part 3"),
    (re.compile(r"(?i)\bpart\s+iv\b"), "part 4"),
    (re.compile(r"(?i)\bchapter\s+i\b"), "chapter 1"),
    (re.compile(r"(?i)\bchapter\s+ii\b"), "chapter 2"),
    (re.compile(r"(?i)\bchapter\s+iii\b"), "chapter 3"),
    (re.compile(r"(?i)\bvol(?:ume)?\s+i\b"), "vol 1"),
    (re.compile(r"(?i)\bvol(?:ume)?\s+ii\b"), "vol 2"),
    (re.compile(r"(?i)\bvol(?:ume)?\s+iii\b"), "vol 3"),
)

_NOISE_SEARCH_WORDS = re.compile(
    r"(?i)\b(4320p|2160p|1440p|1080p|720p|540p|480p|360p|240p|144p|4k|2k|8k|mkv|mp4|avi|"
    r"hdrip|web-?dl|webrip|bluray|brrip|dvdrip|camrip|hdts|predvd|x264|x265|hevc|avc|aac\d*|"
    r"ddp?\d*|dd\d*|ac3|eac3|atmos|\d+ch|10bit|8bit|hdr|sdr|dual\s*audio|multi\s*audio|"
    r"hindi|kannada|tulu|telugu|tamil|malayalam|marathi|gujarati|bengali|punjabi|nepali|"
    r"english|subtitles|subs|esub|episodes|season\s*\d+|s\d+e\d+|complete|movie|movies|"
    r"full\s*movie|download|link|links|send|please|pls|plz|bro|sir|admin|dubbed|dub|new|latest|"
    r"hd|fhd|uhd|qhd|sd|org|original|uncut|unrated|extended|remastered|proper|repack)\b"
)


def sanitize_search_query(text: str, allow_translit: bool = True) -> str:
    if not text:
        return ""
    text = strip_stylish_fonts(text)
    if allow_translit and has_indic_script(text):
        text = transliterate_indic_to_english(text)

    raw_q = re.sub(r"https?://\S+|t\.me/\S+|@\w+", " ", text.strip().lower())
    for pat, repl in _ROMAN_TO_DIGIT:
        raw_q = pat.sub(repl, raw_q)

    raw_q = re.sub(r"\b([a-z]{3,})(\d)\b", r"\1 \2", raw_q)

    basic_q = re.sub(r"[^a-zA-Z0-9]", " ", raw_q)
    basic_q = re.sub(r"\s+", " ", basic_q).strip()

    q = _NOISE_SEARCH_WORDS.sub(" ", raw_q)
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
    q_clean = query.strip()
    if not q_clean:
        return [], 0, 0

    words = [w for w in re.split(r"\s+", q_clean) if w]
    if not words:
        return [], 0, 0

    and_clauses = []
    for w in words:
        w_reg = re.compile(rf"(?:^|[^a-zA-Z0-9]){re.escape(w)}", re.IGNORECASE)
        if getattr(info, "USE_CAPTION_FILTER", False):
            and_clauses.append({"$or": [{"file_name": w_reg}, {"caption": w_reg}]})
        else:
            and_clauses.append({"file_name": w_reg})
    mongo_filter = {"$and": and_clauses} if len(and_clauses) > 1 else and_clauses[0]

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

    res = ([], 0, 0)
    try:
        res = await get_search_results(
            query,
            max_results=max_results,
            offset=offset,
            filter=True,
            is_autocorrect=True,
        )
    except TypeError:
        try:
            res = await get_search_results(
                query, max_results=max_results, offset=offset, filter=True
            )
        except TypeError:
            try:
                res = await get_search_results(
                    query, max_results=max_results, offset=offset
                )
            except Exception:
                _DEAD_COLLECTIONS["get_search_results"] = time.time() + 300
        except Exception:
            _DEAD_COLLECTIONS["get_search_results"] = time.time() + 300
    except Exception:
        _DEAD_COLLECTIONS["get_search_results"] = time.time() + 300

    if res and res[0]:
        return res

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
    txt = _file_text(file_obj)
    if LANG_PATTERNS["kan"].search(txt):
        return True
    return any(0x0C80 <= ord(ch) <= 0x0CFF for ch in txt)


def _normalize_dedup_name(raw_name: str, clean_words: list) -> str:
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
        size_bucket = fsize // 16384
        dedup_key = (norm_name, size_bucket)

        if norm_name and dedup_key in seen_name_size:
            continue

        if fid:
            seen_ids.add(fid)
        if norm_name:
            seen_name_size.add(dedup_key)
        unique_files.append(f)

    return unique_files


def _score_file_relevance(file_obj, query_str: str) -> Tuple[int, int, int, int]:
    raw_fname = str(
        file_obj.get("file_name", "")
        if isinstance(file_obj, dict)
        else getattr(file_obj, "file_name", "")
    )
    fname = strip_stylish_fonts(raw_fname).lower()
    fsize = int(
        file_obj.get("file_size", 0)
        if isinstance(file_obj, dict)
        else getattr(file_obj, "file_size", 0)
    )
    extracted_title = _extract_clean_movie_title(raw_fname)
    clean_fname = re.sub(r"@[a-zA-Z0-9_.\-]+", " ", fname)
    clean_fname = re.sub(r"[^a-zA-Z0-9]", " ", clean_fname)
    clean_fname = re.sub(r"\s+", " ", clean_fname).strip()

    q_lower = query_str.lower().strip()
    year_m = re.search(r"\b(19\d{2}|20\d{2})\b", q_lower)
    q_year = year_m.group(1) if year_m else ""
    q_no_year = re.sub(r"\b(19\d{2}|20\d{2})\b", "", q_lower).strip()
    q_no_year = re.sub(r"\s+", " ", q_no_year) or q_lower
    tokens = [t for t in q_no_year.split() if t]

    title_match_score = 0
    if extracted_title == q_lower or extracted_title == q_no_year:
        title_match_score += 250
    elif extracted_title.startswith(q_no_year + " ") or clean_fname.startswith(
        q_no_year + " "
    ):
        title_match_score += 170
    elif re.search(rf"\b{re.escape(q_no_year)}\b", extracted_title):
        title_match_score += 110
    elif q_no_year in clean_fname:
        title_match_score += 65

    if q_year and re.search(rf"\b{q_year}\b", clean_fname):
        title_match_score += 60

    matched_tokens = sum(
        1 for t in tokens if re.search(rf"\b{re.escape(t)}\b", clean_fname)
    )
    if tokens and matched_tokens == len(tokens):
        title_match_score += 90
    else:
        title_match_score += matched_tokens * 20

    if extracted_title and not extracted_title.startswith(q_no_year[:3]):
        title_match_score -= 30

    is_kan = 1 if _is_kannada_file(file_obj) else 0
    kannada_priority = 1 if (is_kan and title_match_score >= 80) else 0

    return (kannada_priority, title_match_score, is_kan, fsize)


async def smart_filtered_search(
    base_query: str, state: dict, max_results: int = 10, offset: int = 0
) -> Tuple[list, int, int]:
    lang_code = state.get("lang")
    qual_val = state.get("qual")
    clean_words = await get_clean_words()

    pool_cache_key = f"pool:{base_query}:{lang_code or 'all'}:{qual_val or 'all'}"
    deduped = POOL_SEARCH_CACHE.get(pool_cache_key)

    if deduped is None:
        pool_limit = 140 if (lang_code or qual_val) else 90
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
    if not raw_filename:
        return ""
    s = strip_stylish_fonts(raw_filename)
    s = re.sub(r"(?i)https?://\S+|t\.me/\S+|www\.\S+", " ", s)
    s = re.sub(r"[\[\(\{<]*@[a-zA-Z0-9_.\-]+[\]\)\}>]*", " ", s)
    s = re.sub(r"@\S+|\[[^\]]*\]|\{[^}]*\}", " ", s)
    s = re.sub(r"\((?!(?:19|20)\d{2}\))[^)]*\)", " ", s)
    s = re.sub(r"[_.\-]+", " ", s)
    s = re.split(
        r"(?i)\b(4320p|2160p|1440p|1080p|720p|540p|480p|360p|240p|144p|4k|2k|8k|hdrip|web-?dl|webrip|bluray|brrip|dvdrip|camrip|hdts|predvd|x264|x265|hevc|avc|aac\d*|ddp?\d*|dd\d*|ac3|eac3|atmos|10bit|8bit|hdr|sdr|dual\s*audio|multi\s*audio|kannada|tulu|telugu|tamil|malayalam|hindi|english|marathi|gujarati|bengali|punjabi|nepali|esub|subtitles|mkv|mp4|avi|s\d+e\d+|season\s*\d+|ep\s*\d+|episode\s*\d+|complete|uncut|unrated|org|original)\b",
        s,
    )[0]
    s = re.sub(r"[^a-zA-Z0-9\s]", " ", s)
    s = re.sub(r"\b(19\d{2}|20\d{2})\b.*$", "", s).strip()
    s = re.sub(r"\b(?!(?:19|20)\d{2}\b)\d{2,4}\b$", "", s.strip())
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) < 2:
        return sanitize_search_query(raw_filename)
    words = s.split()
    return " ".join(words[:6]).lower()


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
                    .limit(3000)
                    .to_list(length=3000)
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
                .limit(3000)
                .to_list(length=3000)
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
# 💡 UPGRADED "DID YOU MEAN?" MULTI-CHOICE SUGGESTIONS FINDER
# ============================================================
def _phonetic_key(s: str) -> str:
    s = re.sub(r"[^a-z0-9]", "", s.lower())
    if not s:
        return ""
    for old, new in (
        ("aa", "a"),
        ("ee", "i"),
        ("oo", "u"),
        ("bh", "b"),
        ("dh", "d"),
        ("th", "t"),
        ("kh", "k"),
        ("gh", "g"),
        ("ph", "f"),
        ("sh", "s"),
        ("chh", "ch"),
        ("ck", "k"),
        ("q", "k"),
        ("z", "s"),
        ("v", "w"),
        ("y", "i"),
    ):
        s = s.replace(old, new)
    return re.sub(r"(.)\1+", r"\1", s)


def _consonant_skeleton(s: str) -> str:
    p = _phonetic_key(s)
    if len(p) <= 2:
        return p
    return p[0] + re.sub(r"[aeiou]", "", p[1:])


def _dice_ngram_similarity(a: str, b: str, n: int = 2) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    pa, pb = f" {a} ", f" {b} "
    na = {pa[i : i + n] for i in range(max(1, len(pa) - n + 1))}
    nb = {pb[i : i + n] for i in range(max(1, len(pb) - n + 1))}
    return (2.0 * len(na & nb)) / (len(na) + len(nb))


async def get_did_you_mean_suggestions(
    query: str, max_suggestions: int = 6, allow_translit: bool = True
) -> List[str]:
    clean_q = sanitize_search_query(query, allow_translit=allow_translit)
    if not clean_q:
        return []

    q_lower = clean_q.lower().strip()
    q_no_year = re.sub(r"\b(19\d{2}|20\d{2})\b", "", q_lower).strip() or q_lower
    q_tokens = [t for t in q_no_year.split() if t]
    if not q_tokens:
        return []

    candidate_pool = set(await get_cached_db_titles())

    live_patterns = []
    for tok in q_tokens[:2]:
        if len(tok) >= 3:
            live_patterns.append(re.escape(tok[:3]))
            p_tok = _phonetic_key(tok)
            if len(p_tok) >= 3 and p_tok[:3] != tok[:3]:
                live_patterns.append(re.escape(p_tok[:3]))
            skel = _consonant_skeleton(tok)
            if len(skel) >= 3:
                live_patterns.append(".*".join(re.escape(c) for c in skel[:4]))

    if live_patterns and callable(get_all_healthy_read_dbs):
        live_reg = re.compile(
            r"(?:^|[^a-zA-Z0-9])(" + "|".join(dict.fromkeys(live_patterns)) + r")",
            re.IGNORECASE,
        )
        for _, target_db in get_all_healthy_read_dbs():
            try:
                docs = (
                    await target_db[info.COLLECTION_NAME]
                    .find({"file_name": live_reg}, {"file_name": 1})
                    .limit(150)
                    .to_list(length=150)
                )
                for d in docs:
                    ct = _extract_clean_movie_title(d.get("file_name", ""))
                    if ct and len(ct) >= 2:
                        candidate_pool.add(ct)
            except Exception:
                continue

    if not candidate_pool:
        return []

    q_phon = _phonetic_key(q_no_year)
    q_skel = _consonant_skeleton(q_no_year)
    scored_candidates: List[Tuple[float, str]] = []

    for title in candidate_pool:
        t_lower = title.lower().strip()
        if not t_lower:
            continue
        t_tokens = t_lower.split()
        if not t_tokens:
            continue

        seq_ratio = difflib.SequenceMatcher(None, q_no_year, t_lower).ratio()
        t_phon = _phonetic_key(t_lower)
        phon_ratio = (
            difflib.SequenceMatcher(None, q_phon, t_phon).ratio()
            if (q_phon and t_phon)
            else 0.0
        )
        t_skel = _consonant_skeleton(t_tokens[0] if len(q_tokens) == 1 else t_lower)
        skel_ratio = (
            difflib.SequenceMatcher(None, q_skel, t_skel).ratio()
            if (q_skel and t_skel)
            else 0.0
        )
        bi_ratio = _dice_ngram_similarity(q_no_year, t_lower, 2)
        tri_ratio = _dice_ngram_similarity(q_no_year, t_lower, 3)

        token_scores = []
        for qt in q_tokens:
            qt_p = _phonetic_key(qt)
            best_tok = 0.0
            for tt in t_tokens:
                tt_p = _phonetic_key(tt)
                r_raw = difflib.SequenceMatcher(None, qt, tt).ratio()
                r_ph = (
                    difflib.SequenceMatcher(None, qt_p, tt_p).ratio()
                    if (qt_p and tt_p)
                    else 0.0
                )
                best_tok = max(best_tok, r_raw, r_ph * 0.98)
            token_scores.append(best_tok)
        avg_tok = sum(token_scores) / len(token_scores) if token_scores else 0.0

        bonus = 0.0
        if len(q_no_year) >= 3 and (
            t_lower.startswith(q_no_year[:3])
            or (q_phon and t_phon.startswith(q_phon[:3]))
        ):
            bonus += 0.12
        if len(q_no_year) >= 3 and (q_no_year in t_lower or t_lower in q_no_year):
            bonus += 0.15

        final_score = (
            max(
                seq_ratio,
                phon_ratio * 0.98,
                skel_ratio * 0.92,
                bi_ratio * 0.94,
                tri_ratio * 0.95,
                avg_tok * 0.94,
            )
            + bonus
        )

        threshold = 0.48 if len(q_no_year) >= 4 else 0.56
        if final_score >= threshold:
            scored_candidates.append((final_score, t_lower))

    scored_candidates.sort(
        key=lambda x: (round(x[0], 3), -abs(len(x[1]) - len(q_no_year))),
        reverse=True,
    )

    unique_suggestions: List[str] = []
    seen_roots = set()

    for _, cand in scored_candidates:
        if len(unique_suggestions) >= max_suggestions:
            break
        root_norm = re.sub(r"\b(?:part|chapter|vol|volume)?\s*\d+\b", "", cand).strip()
        root_norm = re.sub(r"\s+", " ", root_norm) or cand
        phon_root = _phonetic_key(root_norm)
        if not phon_root or phon_root in seen_roots:
            continue
        seen_roots.add(phon_root)
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

    no_chapter = re.sub(
        r"\b(?:chapter|part|vol|volume)\b", "", no_year_query or clean_query
    ).strip()
    no_chapter = re.sub(r"\s+", " ", no_chapter)
    if (
        no_chapter
        and no_chapter not in (clean_query, no_year_query)
        and len(no_chapter) > 2
    ):
        files, offset, total = await smart_filtered_search(
            no_chapter, default_state, max_results=10, offset=0
        )
        if files:
            return files, offset, total, no_chapter, True

    for p_var in generate_phonetic_variants(no_year_query or clean_query):
        if p_var != clean_query and len(p_var) > 2:
            files, offset, total = await smart_filtered_search(
                p_var, default_state, max_results=10, offset=0
            )
            if files:
                return files, offset, total, p_var, True

    if is_short_query or not allow_fuzzy:
        return [], 0, 0, query, False

    try:
        db_titles = await get_cached_db_titles()
        target_q = no_year_query or clean_query
        if matches := difflib.get_close_matches(target_q, db_titles, n=1, cutoff=0.82):
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
# 🧩 KEYBOARD BUILDER (EVERY BUTTON HIDES LINKS — TEXT ONLY!)
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
                url=LATEST_UPDATES_URL,
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
        cb_payload = f"fget#{pre}#{file_id}"

        if settings.get("button", False):
            btn.append(
                [
                    create_btn(
                        text=f"{size_str} | {display_name}",
                        callback_data=cb_payload,
                    )
                ]
            )
        else:
            btn.append(
                [
                    create_btn(
                        text=f"{display_name}",
                        callback_data=cb_payload,
                    ),
                    create_btn(
                        text=f"{size_str}",
                        callback_data=cb_payload,
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
            )
        )

    btn.append(nav_row)
    return btn


# ============================================================
# ⚡ HIDDEN LINK & FILE BUTTON CLICK HANDLERS
# ============================================================
@Client.on_callback_query(filters.regex(r"^(fget#|shrtget#|olink#|noop$)"), group=-2)
async def hidden_button_click_callback(bot: Client, query: CallbackQuery):
    data = query.data
    if data == "noop":
        return await safe_answer(query)

    if not getattr(temp, "U_NAME", None):
        me = await bot.get_me()
        temp.U_NAME = me.username
        temp.B_NAME = me.first_name
        temp.ME = me.id
    bot_username = temp.U_NAME or "bot"

    if data.startswith("olink#"):
        token = data.split("#", 1)[1]
        target_url = resolve_hidden_link(token)
        if not target_url:
            return await safe_answer(
                query, "⌛ Button expired. Please search again!", show_alert=True
            )

        if f"t.me/{bot_username.lower()}?start=" in target_url.lower():
            return await safe_answer(query, url=target_url)

        redirect_url = f"https://t.me/{bot_username}?start=olink_{token}"
        return await safe_answer(query, url=redirect_url)

    try:
        _, pre, file_id = data.split("#", 2)
    except ValueError:
        return await safe_answer(query, "⚠️ Invalid file!", show_alert=True)

    deep_link = f"https://t.me/{bot_username}?start={pre}_{file_id}"
    return await safe_answer(query, url=deep_link)


# ============================================================
# ⏳ RELIABLE AUTO-DELETE ENGINE (GROUP + PM)
# ============================================================
def _get_deleted_file_notify_keyboard() -> InlineKeyboardMarkup:
    req_grp_url = getattr(info, "GRP_LNK", "https://t.me/Sandalwood_Kannada_Group")
    return InlineKeyboardMarkup([[create_btn("Movie Request 📝", url=req_grp_url)]])


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
            raw_search, max_suggestions=6, allow_translit=autotranslate_on
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

        if search.lower() in {
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
        }:
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
            final_markup = sanitize_markup_hide_links(final_markup or default_markup)
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
# ⚡ UNIFIED GROUP & PM MESSAGE HANDLER
# ============================================================
@Client.on_message(
    (filters.group | filters.private) & filters.text & filters.incoming, group=1
)
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

    if message.chat.type == enums.ChatType.PRIVATE:
        try:
            await manual_filters(client, message)
        except Exception as e:
            logger.error(f"PM manual_filters error: {e}")
        return

    try:
        if await manual_filters(client, message):
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
    filters.command(["autotranslate", "enautotranslate", "diautotranslate"]),
    group=-15,
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
    elif len(message.command) > 1:
        arg = message.command[1].strip().lower()
        new_state = (
            True
            if arg in ["on", "enable", "true", "yes", "1"]
            else False if arg in ["off", "disable", "false", "no", "0"] else not cur_trans
        )
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
    filters.command(["multichoice", "enmultichoice", "dimultichoice"]),
    group=-15,
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
    elif len(message.command) > 1:
        arg = message.command[1].strip().lower()
        new_state = (
            True
            if arg in ["on", "enable", "true", "yes", "1"]
            else False if arg in ["off", "disable", "false", "no", "0"] else not cur_mc
        )
    else:
        new_state = not cur_mc

    await set_feature_flag("multichoice", new_state)
    status_badge = "🟢 ENABLED" if new_state else "🔴 DISABLED"
    out_msg = await safe_reply_text(
        message,
        f"💡 <b>Multi-Choice ('Did You Mean?' Suggestions):</b> <code>{status_badge}</code>\n\n"
        f"<i>When enabled, misspelled movie queries display clickable movie title suggestions instead of File Not Found!</i>",
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
            f"<i>When enabled, misspelled movie queries display clickable movie title suggestions instead of File Not Found!</i>"
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
# 🌐 LANGUAGE, 🎞️ QUALITY & 💡 "DID YOU MEAN?" CALLBACK HANDLERS
# ============================================================
@Client.on_callback_query(
    filters.regex(r"^(flang#|fqual#|setlang#|setqual#|fback#|freset#|dym#|dymback#)"),
    group=-2,
)
async def filter_menu_callbacks(bot: Client, query: CallbackQuery):
    parts = query.data.split("#")
    action = parts[0]

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
        dym_state = {"lang": None, "qual": None, "from_dym": True}
        files, n_offset, total = await smart_filtered_search(
            chosen_title, dym_state, max_results=10, offset=0
        )
        if not files:
            return await safe_answer(
                query, "❌ No files found for that suggestion!", show_alert=True
            )

        BUTTONS_CACHE.set(key, chosen_title)
        set_filter_state(key, lang=None, qual=None, from_dym=True)

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

    if action == "flang":
        cur_lang = state.get("lang")
        btn_rows, row = [], []
        for lang_name, lang_code in LANGUAGES_LIST:
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
            [create_btn(text="⬅️ Back", callback_data=f"freset#{req}#{key}")]
        )
        try:
            await query.edit_message_reply_markup(
                reply_markup=InlineKeyboardMarkup(btn_rows)
            )
        except (MessageNotModified, MessageIdInvalid, ChatWriteForbidden, Forbidden):
            pass
        return await safe_answer(query, "🔊 Select your preferred language:")

    if action == "fqual":
        cur_qual = state.get("qual")
        btn_rows, row = [], []
        for qual_val in QUALITIES_LIST:
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
            [create_btn(text="⬅️ Back", callback_data=f"freset#{req}#{key}")]
        )
        try:
            await query.edit_message_reply_markup(
                reply_markup=InlineKeyboardMarkup(btn_rows)
            )
        except (MessageNotModified, MessageIdInvalid, ChatWriteForbidden, Forbidden):
            pass
        return await safe_answer(query, "🎥 Select your preferred quality:")

    new_lang = state.get("lang")
    new_qual = state.get("qual")

    if action in ["freset", "fback"]:
        new_lang = None
        new_qual = None
    elif action == "setlang":
        chosen = parts[3] if len(parts) > 3 else "all"
        new_lang = None if chosen == "all" or chosen == new_lang else chosen
    elif action == "setqual":
        chosen = parts[3] if len(parts) > 3 else "all"
        new_qual = None if chosen == "all" or chosen == new_qual else chosen

    candidate_state = {
        "lang": new_lang,
        "qual": new_qual,
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
        return await safe_answer(
            query,
            f"❌ No {missing_label} files found for this movie!".strip(),
            show_alert=True,
        )

    set_filter_state(
        key, lang=new_lang, qual=new_qual, from_dym=state.get("from_dym", False)
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

    if action in ["freset", "fback"]:
        return await safe_answer(query, "⬅️ Restored normal filter results!")

    active_filters = []
    if new_lang and new_lang in LANG_MAP:
        active_filters.append(LANG_MAP[new_lang])
    if new_qual:
        active_filters.append(new_qual)

    await safe_answer(
        query,
        (
            f"✅ Filtered by: {' + '.join(active_filters)}"
            if active_filters
            else "⬅️ Restored normal filter results!"
        ),
    )


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
        raw_target = data.split("#", 1)[1]
        target_chat_id = (
            int(raw_target) if raw_target.lstrip("-").isdigit() else raw_target
        )
        uid = query.from_user.id if query.from_user else 0
        if not await is_global_admin(uid):
            if isinstance(target_chat_id, int):
                try:
                    member = await bot.get_chat_member(target_chat_id, uid)
                    if member.status not in [
                        enums.ChatMemberStatus.ADMINISTRATOR,
                        enums.ChatMemberStatus.OWNER,
                    ]:
                        return await safe_answer(
                            query, "❌ Unauthorized!", show_alert=True
                        )
                except Exception:
                    return await safe_answer(query, "❌ Unauthorized!", show_alert=True)
            else:
                return await safe_answer(query, "❌ Unauthorized!", show_alert=True)

        await safe_delete_all_filters(query.message, target_chat_id)
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
# 🎨 KEYBOARD AND BUTTON PARSERS (MANUAL FILTERS — LINKS HIDDEN)
# ============================================================
def _clean_extracted_url(raw_url: str) -> str:
    u = str(raw_url or "").strip()
    href_match = re.search(r"href=['\"]([^'\"]+)['\"]", u)
    if href_match:
        u = href_match.group(1).strip()
    u = re.sub(r"<[^>]+>", "", u).strip()
    u = re.sub(r"(?i)^buttonurl:(?://)?", "", u).strip()
    u = re.sub(r"(?i):same$", "", u).strip()
    if u and not u.startswith(("http://", "https://", "tg://", "mailto:")):
        if "." in u or u.startswith("t.me/"):
            u = "https://" + u.lstrip("/")
    return u


def build_keyboard(btn_str: str):
    if not btn_str or btn_str in ["[]", "None", "False", ""]:
        return None
    try:
        data = ast.literal_eval(btn_str) if isinstance(btn_str, str) else btn_str
        if not isinstance(data, list):
            return None
        button_layout = []
        for row in data:
            if isinstance(row, dict):
                row = [row]
            if not isinstance(row, list):
                continue
            btn_row = []
            for b in row:
                if isinstance(b, dict):
                    b_copy = b.copy()
                    style_val = b_copy.pop("style", None)
                    icon_val = b_copy.pop("icon_custom_emoji_id", None)
                    url_val = b_copy.get("url")
                    cb_val = b_copy.get("callback_data")
                    raw_lbl = str(b_copy.get("text", "Button"))
                    if url_val:
                        clean_u = _clean_extracted_url(url_val)
                        if not clean_u.startswith(("http://", "https://", "tg://")):
                            continue
                        btn_row.append(
                            create_btn(
                                text=raw_lbl,
                                url=clean_u,
                                style=style_val,
                                icon_custom_emoji_id=icon_val,
                            )
                        )
                    elif cb_val:
                        btn_row.append(
                            create_btn(
                                text=raw_lbl,
                                callback_data=str(cb_val),
                                style=style_val,
                                icon_custom_emoji_id=icon_val,
                            )
                        )
                elif isinstance(b, InlineKeyboardButton):
                    ic = _get_btn_icon_id(b)
                    if getattr(b, "url", None):
                        btn_row.append(
                            create_btn(
                                text=b.text,
                                url=b.url,
                                style=getattr(b, "style", None),
                                icon_custom_emoji_id=ic,
                            )
                        )
                    else:
                        btn_row.append(b)
            if btn_row:
                button_layout.append(btn_row)
        return button_layout if button_layout else None
    except Exception as e:
        logger.error(f"Button parsing error: {e}")
        return None


def parse_markdown_buttons(text: str):
    if not text:
        return "", "[]"

    buttons, clean_lines = [], []
    pat_md = re.compile(r"\[([^\[\]\n]+)\]\(\s*([^\(\)\n]+?)\s*\)")
    pat_pipe = re.compile(r"\[([^\[\]\|\n]+)\|\s*([^\[\]\n]+?)\s*\]")

    for line in text.split("\n"):
        row_btns = []
        working_line = line

        matches = []
        for m in pat_md.finditer(working_line):
            matches.append((m.start(), m.end(), m.group(1), m.group(2), m.group(0)))
        for m in pat_pipe.finditer(working_line):
            matches.append((m.start(), m.end(), m.group(1), m.group(2), m.group(0)))
        matches.sort(key=lambda x: x[0])

        if matches:
            for _, _, raw_lbl, raw_u, full_token in matches:
                clean_lbl = _clean_button_label(raw_lbl)
                is_same = bool(re.search(r"(?i):same\s*$", raw_u.strip()))
                clean_u = _clean_extracted_url(raw_u)
                if clean_lbl and clean_u.startswith(("http://", "https://", "tg://")):
                    btn_dict = {"text": clean_lbl, "url": clean_u}
                    if is_same and buttons:
                        buttons[-1].append(btn_dict)
                    else:
                        row_btns.append(btn_dict)
                    working_line = working_line.replace(full_token, "", 1)
            if row_btns:
                buttons.append(row_btns)
            stripped_rem = working_line.strip()
            if stripped_rem:
                clean_lines.append(stripped_rem)
            continue

        if (
            " - " in working_line
            and (
                "http://" in working_line
                or "https://" in working_line
                or "t.me/" in working_line
            )
            and "<blockquote" not in working_line.lower()
        ):
            parts_pipe = [p.strip() for p in working_line.split("|") if p.strip()]
            dash_btns = []
            valid_dash_line = True
            for part in parts_pipe:
                if " - " not in part:
                    valid_dash_line = False
                    break
                b_lbl, b_url = part.split(" - ", 1)
                clean_lbl = _clean_button_label(b_lbl)
                clean_u = _clean_extracted_url(b_url)
                if clean_lbl and clean_u.startswith(("http://", "https://", "tg://")):
                    dash_btns.append({"text": clean_lbl, "url": clean_u})
                else:
                    valid_dash_line = False
                    break
            if valid_dash_line and dash_btns:
                buttons.append(dash_btns)
                continue

        clean_lines.append(working_line)

    return "\n".join(clean_lines).strip(), (str(buttons) if buttons else "[]")


def _extract_replied_media(replied: Optional[Message]) -> Tuple[str, str]:
    if not replied:
        return "None", "None"
    for media_attr in (
        "photo",
        "video",
        "document",
        "animation",
        "audio",
        "voice",
        "sticker",
        "video_note",
    ):
        media_obj = getattr(replied, media_attr, None)
        if media_obj and getattr(media_obj, "file_id", None):
            return str(media_obj.file_id), media_attr
    return "None", "None"


def _extract_message_html(msg: Optional[Message]) -> str:
    if not msg:
        return ""
    for attr in ("text", "caption"):
        val = getattr(msg, attr, None)
        if val:
            if hasattr(val, "html"):
                try:
                    return str(val.html)
                except Exception:
                    return str(val)
            return str(val)
    return ""


def _extract_existing_inline_buttons(msg: Optional[Message]) -> List[List[dict]]:
    existing_btns: List[List[dict]] = []
    if (
        not msg
        or not msg.reply_markup
        or not getattr(msg.reply_markup, "inline_keyboard", None)
    ):
        return existing_btns
    for row in msg.reply_markup.inline_keyboard:
        row_btns = []
        for b in row:
            b_dict: Dict[str, Any] = {"text": _clean_button_label(b.text)}
            if b.url:
                b_dict["url"] = b.url
            elif b.callback_data:
                b_dict["callback_data"] = b.callback_data
            st = getattr(b, "style", None)
            if st is not None:
                b_dict["style"] = st.value if hasattr(st, "value") else st
            ic = _get_btn_icon_id(b)
            if ic:
                b_dict["icon_custom_emoji_id"] = ic
            if b.url or b.callback_data:
                row_btns.append(b_dict)
        if row_btns:
            existing_btns.append(row_btns)
    return existing_btns


def _parse_filter_command_input(message: Message) -> Tuple[str, str]:
    raw_full = _extract_message_html(message)
    parts = raw_full.split(None, 1)
    if len(parts) < 2:
        return "", ""
    rest = parts[1].strip()
    if not rest:
        return "", ""

    q_match = re.match(r'^["“”]([^"“”]+)["“”](?:\s+(.*))?$', rest, flags=re.DOTALL)
    if q_match:
        return q_match.group(1).strip().lower(), (q_match.group(2) or "").strip()

    if message.reply_to_message:
        if "\n" in rest:
            first_line, extra_lines = rest.split("\n", 1)
            return first_line.strip().lower(), extra_lines.strip()
        btn_split = re.split(
            r"(\[[^\[\]]+\]\([^\(\)]+\)|\[[^\[\]]+\|[^\[\]]+\])", rest, maxsplit=1
        )
        if len(btn_split) > 1 and btn_split[0].strip():
            return btn_split[0].strip().lower(), "".join(btn_split[1:]).strip()
        return rest.strip().lower(), ""

    kw_parts = rest.split(None, 1)
    keyword = kw_parts[0].strip().lower()
    inline_reply = kw_parts[1].strip() if len(kw_parts) > 1 else ""
    return keyword, inline_reply


# ============================================================
# 🎯 FILTER COMMANDS
# ============================================================
async def _resolve_admin_chat(
    client: Client, message: Message
) -> Tuple[Optional[Any], bool]:
    target_chat_id = await get_target_chat(client, message)
    if not target_chat_id:
        if await verify_admin(client, message, None):
            return "global", True
        await safe_reply_text(
            message,
            "⚠️ <b>No active connection!</b>\nPlease run <code>/connect &lt;group_id&gt;</code> first.",
            parse_mode=enums.ParseMode.HTML,
        )
        return None, False

    if target_chat_id != "global" and not await verify_admin(
        client, message, target_chat_id
    ):
        await safe_reply_text(
            message,
            f"❌ <b>You are not authorized for chat:</b> <code>{target_chat_id}</code>",
            parse_mode=enums.ParseMode.HTML,
        )
        return None, False

    return target_chat_id, True


@Client.on_message(filters.command(["filter", "addfilter"]), group=-15)
async def add_filter_cmd(client: Client, message: Message):
    target_chat_id, ok = await _resolve_admin_chat(client, message)
    if not ok:
        return

    keyword, inline_arg_text = _parse_filter_command_input(message)
    replied = message.reply_to_message

    if not keyword:
        return await safe_reply_text(
            message,
            "⚠️ <b>Reply to a message (text, photo, video, or buttons) to set it as a filter!</b>\n\n"
            "⚙️ <b>Usage:</b>\n"
            "• <code>/filter &lt;keyword&gt;</code> (reply to any message/media)\n"
            "• <code>/addfilter &lt;keyword&gt;</code> (reply to message with buttons)\n"
            "• <code>/filter &lt;keyword&gt; Text [Button](https://t.me/link)</code>",
            parse_mode=enums.ParseMode.HTML,
        )

    if not replied and not inline_arg_text:
        return await safe_reply_text(
            message,
            "⚠️ <b>Reply to a message (text or media) or provide filter text after the keyword.</b>",
            parse_mode=enums.ParseMode.HTML,
        )

    replied_html = _extract_message_html(replied) if replied else ""
    combined_raw = (
        f"{replied_html}\n{inline_arg_text}".strip()
        if (replied_html and inline_arg_text)
        else (replied_html or inline_arg_text)
    )

    text, parsed_btn_str = parse_markdown_buttons(combined_raw)
    parsed_btns = []
    if parsed_btn_str and parsed_btn_str != "[]":
        try:
            parsed_btns = ast.literal_eval(parsed_btn_str)
        except Exception:
            parsed_btns = []

    existing_btns = _extract_existing_inline_buttons(replied)
    all_btns = existing_btns + parsed_btns
    final_btn_str = str(all_btns) if all_btns else "[]"
    fileid, media_type = _extract_replied_media(replied)

    if not text and fileid == "None" and not all_btns:
        return await safe_reply_text(
            message,
            "❌ <b>Cannot save an empty filter. Reply to text, photo, video, or media!</b>",
            parse_mode=enums.ParseMode.HTML,
        )

    await safe_save_filter(
        target_chat_id,
        keyword,
        text,
        final_btn_str,
        fileid,
        "[]",
        media_type=media_type,
    )

    scope_label = (
        "All Connected Groups (Global)"
        if str(target_chat_id) == "global"
        else f"<code>{target_chat_id}</code>"
    )
    media_badge = media_type.upper() if media_type != "None" else "TEXT"
    btn_count = sum(len(r) for r in all_btns)

    out_msg = await safe_reply_text(
        message,
        f"✅ <b>Filter Successfully Saved!</b>\n\n"
        f"🔑 <b>Keyword:</b> <code>{html.escape(keyword)}</code>\n"
        f"📦 <b>Type:</b> <code>{media_badge}</code>\n"
        f"🔘 <b>Buttons:</b> <code>{btn_count}</code>\n"
        f"🎯 <b>Target:</b> {scope_label}",
        parse_mode=enums.ParseMode.HTML,
    )
    delete_timer = await resolve_auto_delete_timer(message.chat.id, default_time=300)
    schedule_auto_delete(client, message.chat.id, False, delete_timer, out_msg, message)


@Client.on_message(
    filters.command(["addfilterbutton", "editfilterbutton", "filterbutton"]),
    group=-15,
)
async def add_or_edit_filter_button_cmd(client: Client, message: Message):
    target_chat_id, ok = await _resolve_admin_chat(client, message)
    if not ok:
        return

    parts = (message.text or "").split(None, 2)
    if len(parts) < 3:
        return await safe_reply_text(
            message,
            "⚙️ <b>Usage:</b>\n"
            "<code>/addfilterbutton &lt;keyword&gt; Button Text - https://t.me/link</code>",
            parse_mode=enums.ParseMode.HTML,
        )

    keyword = parts[1].strip().lower()
    raw_btn_input = parts[2].strip()

    reply_text, btn, alert, fileid, media_type = await safe_find_filter(
        target_chat_id, keyword
    )
    if not reply_text and (not fileid or fileid == "None"):
        return await safe_reply_text(
            message,
            f"❌ <b>Filter <code>{html.escape(keyword)}</code> not found.</b>",
            parse_mode=enums.ParseMode.HTML,
        )

    _, new_btn_str = parse_markdown_buttons(raw_btn_input)
    new_btns = []
    if new_btn_str and new_btn_str != "[]":
        try:
            new_btns = ast.literal_eval(new_btn_str)
        except Exception:
            new_btns = []

    if not new_btns and "|" in raw_btn_input:
        b_lbl, b_url = raw_btn_input.split("|", 1)
        clean_u = _clean_extracted_url(b_url)
        clean_lbl = _clean_button_label(b_lbl)
        if clean_lbl and clean_u.startswith(("http://", "https://", "tg://")):
            new_btns = [[{"text": clean_lbl, "url": clean_u}]]

    if not new_btns:
        return await safe_reply_text(
            message,
            "❌ <b>Invalid button URL format.</b>",
            parse_mode=enums.ParseMode.HTML,
        )

    existing_btns = []
    if btn and btn not in ["[]", "None", "False", ""]:
        try:
            existing_btns = ast.literal_eval(btn)
        except Exception:
            existing_btns = []

    await safe_save_filter(
        target_chat_id,
        keyword,
        reply_text,
        str(existing_btns + new_btns),
        fileid,
        alert,
        media_type=media_type,
    )
    await safe_reply_text(
        message,
        f"✅ <b>Added button(s) to filter <code>{html.escape(keyword)}</code>!</b>",
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(filters.command("filterimage"), group=-15)
async def edit_filter_image_cmd(client: Client, message: Message):
    target_chat_id, ok = await _resolve_admin_chat(client, message)
    if not ok:
        return

    if not message.reply_to_message:
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
    reply_text, btn, alert, old_fileid, _ = await safe_find_filter(
        target_chat_id, keyword
    )
    if not reply_text and (not old_fileid or old_fileid == "None"):
        return await safe_reply_text(
            message,
            f"❌ <b>Filter <code>{html.escape(keyword)}</code> not found.</b>",
            parse_mode=enums.ParseMode.HTML,
        )

    fileid, media_type = _extract_replied_media(message.reply_to_message)
    if fileid == "None":
        return await safe_reply_text(
            message,
            "❌ <b>Could not extract valid media from the replied message.</b>",
            parse_mode=enums.ParseMode.HTML,
        )

    await safe_save_filter(
        target_chat_id, keyword, reply_text, btn, fileid, alert, media_type=media_type
    )
    out_msg = await safe_reply_text(
        message,
        f"✅ <b>Filter image updated!</b>\n\n<b>Keyword:</b> <code>{html.escape(keyword)}</code>",
        parse_mode=enums.ParseMode.HTML,
    )
    delete_timer = await resolve_auto_delete_timer(message.chat.id, default_time=300)
    schedule_auto_delete(client, message.chat.id, False, delete_timer, out_msg, message)


@Client.on_message(
    filters.command(["editfiltercolur", "editfiltercolour"]),
    group=-15,
)
async def edit_filter_colour_cmd(client: Client, message: Message):
    target_chat_id, ok = await _resolve_admin_chat(client, message)
    if not ok:
        return

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

    reply_text, btn, alert, fileid, media_type = await safe_find_filter(
        target_chat_id, keyword
    )
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
        for c_idx, _ in enumerate(row):
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
        target_chat_id,
        keyword,
        reply_text,
        str(button_data),
        fileid,
        alert,
        media_type=media_type,
    )
    out_msg = await safe_reply_text(
        message,
        f"✅ <b>Filter <code>{html.escape(keyword)}</code> Button {btn_num} colour changed to {color_str.title()}!</b>",
        parse_mode=enums.ParseMode.HTML,
    )
    delete_timer = await resolve_auto_delete_timer(message.chat.id, default_time=300)
    schedule_auto_delete(client, message.chat.id, False, delete_timer, out_msg, message)


@Client.on_message(filters.command(["delfilter", "stop"]), group=-15)
async def del_filter_cmd(client: Client, message: Message):
    target_chat_id, ok = await _resolve_admin_chat(client, message)
    if not ok:
        return

    if len(message.command) < 2:
        return await safe_reply_text(
            message,
            "⚙️ <b>Usage:</b> <code>/delfilter &lt;keyword&gt;</code>",
            parse_mode=enums.ParseMode.HTML,
        )
    keyword = message.text.split(None, 1)[1].lower().strip()
    await safe_delete_filter(message, keyword, target_chat_id)
    out_msg = await safe_reply_text(
        message,
        f"🗑️ <b>Filter <code>{html.escape(keyword)}</code> deleted.</b>",
        parse_mode=enums.ParseMode.HTML,
    )
    delete_timer = await resolve_auto_delete_timer(message.chat.id, default_time=300)
    schedule_auto_delete(client, message.chat.id, False, delete_timer, out_msg, message)


@Client.on_message(filters.command(["delall", "deleteall"]), group=-15)
async def del_all_filters_cmd(client: Client, message: Message):
    target_chat_id, ok = await _resolve_admin_chat(client, message)
    if not ok:
        return

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
    filters.command(["listfilters", "filters", "viewfilters"]),
    group=-15,
)
async def list_filters_cmd(client: Client, message: Message):
    target_chat_id, ok = await _resolve_admin_chat(client, message)
    if not ok:
        return

    keywords = await safe_get_all_filters(target_chat_id)
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
# 📤 MULTI-MEDIA FILTER DISPATCHER (LAYER 230 SAFE)
# ============================================================
def _get_reply_kwargs(func: Any, reply_id: Optional[int]) -> dict:
    if not reply_id:
        return {}
    try:
        params = set(inspect.signature(func).parameters.keys())
        if "reply_to_message_id" in params:
            return {"reply_to_message_id": reply_id}
        if "reply_parameters" in params and ReplyParameters is not None:
            return {"reply_parameters": ReplyParameters(message_id=reply_id)}
    except Exception:
        pass
    return {}


async def send_filter_media(
    client: Client,
    chat_id: int,
    fileid: str,
    reply_text: str,
    reply_markup,
    reply_id: int,
    media_type: str = "None",
):
    if RESTRICTED_WRITE_CHATS.get(str(chat_id)):
        return None

    reply_markup = sanitize_markup_hide_links(reply_markup)
    method_map = {
        "photo": (client.send_photo, "photo"),
        "video": (client.send_video, "video"),
        "document": (client.send_document, "document"),
        "animation": (client.send_animation, "animation"),
        "audio": (client.send_audio, "audio"),
        "voice": (client.send_voice, "voice"),
        "sticker": (client.send_sticker, "sticker"),
    }

    if media_type in method_map:
        send_fn, arg_name = method_map[media_type]
        rep_kw = _get_reply_kwargs(send_fn, reply_id)
        try:
            if media_type == "sticker":
                return await send_fn(
                    chat_id=chat_id,
                    sticker=fileid,
                    reply_markup=reply_markup,
                    **rep_kw,
                )
            return await send_fn(
                **{
                    "chat_id": chat_id,
                    arg_name: fileid,
                    "caption": reply_text or "",
                    "reply_markup": reply_markup,
                    "parse_mode": enums.ParseMode.HTML,
                    **rep_kw,
                }
            )
        except (ChatWriteForbidden, Forbidden, UserIsBlocked, PeerIdInvalid):
            RESTRICTED_WRITE_CHATS.set(str(chat_id), True)
            return None
        except Exception:
            try:
                return await send_fn(
                    **{
                        "chat_id": chat_id,
                        arg_name: fileid,
                        "caption": re.sub(r"<[^>]+>", "", reply_text or ""),
                        "reply_markup": reply_markup,
                    }
                )
            except Exception:
                pass

    for use_rep in (True, False):
        rep_kw = (
            _get_reply_kwargs(client.send_cached_media, reply_id) if use_rep else {}
        )
        try:
            return await client.send_cached_media(
                chat_id=chat_id,
                file_id=fileid,
                caption=reply_text or "",
                reply_markup=reply_markup,
                parse_mode=enums.ParseMode.HTML,
                **rep_kw,
            )
        except FloodWait as e:
            if e.value <= 10:
                await asyncio.sleep(e.value + 1)
                continue
            return None
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
            continue

    for m_key, (send_fn, arg_name) in method_map.items():
        if m_key == "sticker":
            continue
        rep_kw = _get_reply_kwargs(send_fn, reply_id)
        for p_mode in (enums.ParseMode.HTML, None):
            try:
                kw_call = {
                    "chat_id": chat_id,
                    arg_name: fileid,
                    "caption": (
                        reply_text
                        if p_mode
                        else re.sub(r"<[^>]+>", "", reply_text or "")
                    ),
                    "reply_markup": reply_markup,
                    **rep_kw,
                }
                if p_mode:
                    kw_call["parse_mode"] = p_mode
                return await send_fn(**kw_call)
            except (ChatWriteForbidden, Forbidden, UserIsBlocked, PeerIdInvalid):
                RESTRICTED_WRITE_CHATS.set(str(chat_id), True)
                return None
            except Exception:
                continue

    return await safe_send_text_filter(
        client,
        chat_id,
        reply_text or "<b>Here is your filter result:</b>",
        reply_markup,
        reply_id,
    )


async def safe_send_text_filter(
    client: Client, chat_id: int, text: str, reply_markup, reply_id: int
):
    if RESTRICTED_WRITE_CHATS.get(str(chat_id)):
        return None

    reply_markup = sanitize_markup_hide_links(reply_markup)
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

    rep_kw = _get_reply_kwargs(client.send_message, reply_id)
    try:
        return await client.send_message(**kw, **rep_kw)
    except (ChatWriteForbidden, Forbidden, UserIsBlocked, PeerIdInvalid, SlowmodeWait):
        RESTRICTED_WRITE_CHATS.set(str(chat_id), True)
        return None
    except Exception:
        try:
            return await client.send_message(**kw)
        except Exception:
            kw.pop("parse_mode", None)
            kw["text"] = re.sub(r"<[^>]+>", "", text or "")
            try:
                return await client.send_message(**kw)
            except Exception as e:
                logger.error(f"Text filter failed: {e}")
                return None


# ============================================================
# ⚡ LIVE GROUP & PM TRIGGER HANDLER (CACHED MANUAL FILTERS)
# ============================================================
async def manual_filters(client: Client, message: Message, text=False) -> bool:
    if getattr(info, "REPAIR_MODE", False) and not await verify_admin(
        client, message, message.chat.id
    ):
        return False

    group_id: Any = message.chat.id
    if message.chat.type == enums.ChatType.PRIVATE:
        active_grp = await get_active_connection(
            str(message.from_user.id if message.from_user else 0)
        )
        group_id = active_grp if active_grp else "global"

    raw_name = text or message.text or message.caption or ""
    if not raw_name:
        return False

    norm_name = strip_stylish_fonts(raw_name)
    reply_id = message.reply_to_message.id if message.reply_to_message else message.id

    grp_key = str(group_id)
    keywords = MANUAL_FILTERS_CACHE.get(grp_key)
    if keywords is None:
        keywords = await safe_get_all_filters(group_id)
        MANUAL_FILTERS_CACHE.set(grp_key, keywords)

    if not keywords:
        return False

    for kw_str in keywords:
        pat = r"( |^|[^\w])" + re.escape(kw_str) + r"( |$|[^\w])"
        if re.search(pat, raw_name, flags=re.IGNORECASE) or re.search(
            pat, norm_name, flags=re.IGNORECASE
        ):
            reply_text, btn, alert, fileid, media_type = await safe_find_filter(
                group_id, kw_str
            )

            fileid_str = str(fileid).strip()
            has_valid_file = bool(
                fileid and fileid_str not in ["None", "[]", "", "False"]
            )
            if not reply_text and not has_valid_file:
                continue

            if reply_text:
                reply_text = reply_text.replace("\\n", "\n").replace("\\t", "\t")

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
                    media_type=media_type,
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
