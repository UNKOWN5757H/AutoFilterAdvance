import re
from os import environ

id_pattern = re.compile(r"^-?\d+$")


def is_enabled(value, default: bool) -> bool:
    val = str(value).strip().lower()
    if val in ("true", "yes", "1", "enable", "y"):
        return True
    if val in ("false", "no", "0", "disable", "n"):
        return False
    return default


def _safe_int(env_key: str, default: int) -> int:
    raw = environ.get(env_key, "").strip()
    if raw and id_pattern.match(raw):
        return int(raw)
    return int(default)


def _safe_int_list(env_key: str, default_str: str = "") -> list:
    raw = environ.get(env_key, default_str).strip()
    return [
        int(x) if id_pattern.match(x) else x
        for x in raw.replace(",", " ").split()
        if x.strip()
    ]


# ============================================================
# 🤖 CORE TELEGRAM CREDENTIALS & SERVER SETTINGS
# ============================================================
SESSION = environ.get("SESSION", "VersionQ").strip() or "VersionQ"
API_ID = _safe_int("API_ID", 2468192)
API_HASH = environ.get("API_HASH", "4906b3f8f198ec0e24edb2c197677678").strip()
BOT_TOKEN = environ.get("BOT_TOKEN", "").strip()
PORT = _safe_int("PORT", 8080)

# ⚡ HIGH-SPEED CONCURRENCY & INDEXING
WORKERS = _safe_int("WORKERS", 100)
INDEX_SPEED = float(environ.get("INDEX_SPEED", "0.0") or 0.0)
INDEX_BATCH_SIZE = _safe_int("INDEX_BATCH_SIZE", 200)
AUTO_INDEX = is_enabled(environ.get("AUTO_INDEX", "True"), True)

# 🤖 MULTI-BOT MASTER-WORKER SETTINGS (/bots)
MULTI_BOT_ENABLED = is_enabled(environ.get("MULTI_BOT_ENABLED", "True"), True)
MAX_WORKER_BOTS = _safe_int("MAX_WORKER_BOTS", 10)
WORKER_BOT_TOKENS = [
    tok.strip()
    for tok in re.split(r"[\s,]+", environ.get("WORKER_BOT_TOKENS", "").strip())
    if tok.strip()
]

CACHE_TIME = _safe_int("CACHE_TIME", 300)
USE_CAPTION_FILTER = is_enabled(environ.get("USE_CAPTION_FILTER", "False"), False)
PICS = (environ.get("PICS", "https://iili.io/COHUHil.jpg")).split()

# ============================================================
# ⏳ GLOBAL AUTO-DELETE SETTINGS (IN SECONDS)
# ============================================================
FILE_AUTO_DELETE = _safe_int("FILE_AUTO_DELETE", 1800)
BUTTON_AUTO_DELETE = _safe_int("BUTTON_AUTO_DELETE", 300)
BUTTON_DEL = BUTTON_AUTO_DELETE
BUTTON_DELETE_TIME = BUTTON_AUTO_DELETE
AUTO_DELETE_TIME = _safe_int("AUTO_DELETE_TIME", 300)
IMDB_DELETETIME = AUTO_DELETE_TIME
BROADCAST_DELETE_TIME = _safe_int("BROADCAST_DELETE_TIME", 86400)
AUTO_DELETE = is_enabled(environ.get("AUTO_DELETE", "True"), True)

# ============================================================
# 🛠️ SYSTEM, REACTIONS & ANTI-FLOOD DEFAULTS
# ============================================================
REPAIR_MODE = is_enabled(environ.get("REPAIR_MODE", "False"), False)
ENABLE_REACTION = is_enabled(environ.get("ENABLE_REACTION", "True"), True)
REACTIONS = ["❤️", "🔥", "👍", "🎉", "🤩", "⚡", "💯", "🥰", "👏", "🍿"]

FLOOD_LIMIT = _safe_int("FLOOD_LIMIT", 5)
FLOOD_TIME = _safe_int("FLOOD_TIME", 5)
FLOOD_ACTION = environ.get("FLOOD_ACTION", "delete").strip().lower()

# ============================================================
# 🔗 LINK SHORTENER & EXTRA BUTTON URLS (HIDDEN BEHIND CALLBACKS)
# ============================================================
SHORTLINK = is_enabled(environ.get("SHORTLINK", "False"), False)
SHORTLINK_URL = environ.get("SHORTLINK_URL", "").strip()
SHORTLINK_API = environ.get("SHORTLINK_API", "").strip()

GRP_LNK = environ.get("GRP_LNK", "https://t.me/Sandalwood_Kannada_Group").strip()
LATEST_UPDATES_URL = environ.get(
    "LATEST_UPDATES_URL", "https://t.me/+8Mw-Y-fYN6hiZWZl"
).strip()
EXTRA_BTN_1_URL = environ.get(
    "EXTRA_BTN_1_URL", "https://t.me/+lcTawsnhdi0zYWE1"
).strip()
EXTRA_BTN_2_URL = environ.get(
    "EXTRA_BTN_2_URL", "https://t.me/linkz_ki_duniyaa"
).strip()

# ============================================================
# 👑 ADMINS, CHANNELS & AUTH GROUPS
# ============================================================
ADMINS = _safe_int_list("ADMINS", "2098589219")
CHANNELS = _safe_int_list("CHANNELS", "-1002055023335")
auth_users = _safe_int_list("AUTH_USERS", "2098589219")
AUTH_USERS = (auth_users + ADMINS) if auth_users else []
auth_grp = environ.get("AUTH_GROUP", "").strip()
AUTH_GROUPS = (
    [int(ch) for ch in auth_grp.split() if id_pattern.match(ch)] if auth_grp else None
)

# ============================================================
# 💾 MULTI-DATABASE CONFIGURATION
# ============================================================
DATABASE_URI = environ.get(
    "DATABASE_URI",
    "mongodb+srv://Rashmika1:Rashmika@cluster0.2rfx8ak.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0",
).strip()
SECOND_DATABASE_URI = environ.get("SECOND_DATABASE_URI", "").strip()
THIRD_DATABASE_URI = environ.get("THIRD_DATABASE_URI", "").strip()

DATABASE_NAME = environ.get("DATABASE_NAME", "ClusterQ").strip()
SECOND_DATABASE_NAME = environ.get("SECOND_DATABASE_NAME", "auto2").strip()
THIRD_DATABASE_NAME = environ.get("THIRD_DATABASE_NAME", "auto3").strip()
COLLECTION_NAME = environ.get("COLLECTION_NAME", "VersionQ").strip()

MAX_DB_SIZE_MB = _safe_int("MAX_DB_SIZE_MB", 480)

# ============================================================
# 📱 FORCE SUBSCRIBE CONFIGURATION
# ============================================================
_auth_ch = environ.get("AUTH_CHANNEL", "sandalwood_kannada_moviesz").strip()
AUTH_CHANNEL = int(_auth_ch) if _auth_ch and id_pattern.match(_auth_ch) else None

_req_ch = environ.get("REQ_CHANNEL", "+pCz5eoun5Zk5YzRl").strip()
REQ_CHANNEL = int(_req_ch) if _req_ch and id_pattern.match(_req_ch) else False

JOIN_REQS_DB = environ.get("JOIN_REQS_DB", SECOND_DATABASE_URI or DATABASE_URI).strip()
IS_FSUB_ENABLED = is_enabled(environ.get("IS_FSUB_ENABLED", "True"), True)
FSUB_MAX_COUNT = _safe_int("FSUB_MAX_COUNT", 0)
FSUB_CHANNELS = {}

# ============================================================
# 📢 CHANNELS, CAPTIONS & UI DEFAULTS
# ============================================================
LOG_CHANNEL = _safe_int("LOG_CHANNEL", -1001693006436)
SUPPORT_CHAT = environ.get("SUPPORT_CHAT", "Kannada_Filmy_Group").strip()
P_TTI_SHOW_OFF = is_enabled(environ.get("P_TTI_SHOW_OFF", "True"), False)
IMDB = is_enabled(environ.get("IMDB", "False"), False)
SINGLE_BUTTON = is_enabled(environ.get("SINGLE_BUTTON", "True"), True)

CUSTOM_FILE_CAPTION = environ.get(
    "CUSTOM_FILE_CAPTION",
    "<b>𝗝𝗼𝗶𝗻 𝗢𝘂𝗿 𝗖𝗵𝗮𝗻𝗻𝗲𝗹𝘀 ⚡️\n𝐌𝐚𝐢𝐧 𝐂𝐡𝐚𝐧𝐧𝐞𝐥 👇\nhttps://t.me/sandalwood_kannada_moviesz \n𝐑𝐞𝐪𝐮𝐞𝐬𝐭 𝐌𝐨𝐯𝐢𝐞𝐬 👇\nhttps://t.me/Sandalwood_Kannada_Group</b>",
)
BATCH_FILE_CAPTION = environ.get("BATCH_FILE_CAPTION", CUSTOM_FILE_CAPTION)
CAPTION_PLUS = environ.get("CAPTION_PLUS", None)

NOT_FOUND_MSG = environ.get(
    "NOT_FOUND_MSG",
    "<b>🚫 File not found. Please note👇\n\n✅ Use correct spelling as given in Google.\n\n✅ DO NOT ask for files which are not released in OTT.\n\n✅ Request movies in this format - (Moviename) (Year of release)\nEg. Jai Ganesh 2024</b>",
)
NOT_FOUND_IMG = environ.get(
    "NOT_FOUND_IMG",
    "https://telegra.ph/file/c4f0458d30f61993aad45-086b84e8363b3c582e.jpg",
)

START_IMG = environ.get("START_IMG", None)
HELP_IMG = environ.get("HELP_IMG", None)
ABOUT_IMG = environ.get("ABOUT_IMG", None)
AUTO_IMG = environ.get("AUTO_IMG", None)
INFO_MSG = environ.get("INFO_MSG", None)
INFO_IMG = environ.get("INFO_IMG", None)
DEL_MSG = environ.get(
    "DEL_MSG",
    "<b>Successfully deleted your file, if you want request again in group.</b>",
)
DEL_IMG = environ.get("DEL_IMG", None)
FSUB_MSG = (
    environ.get("FSUB_MSG", "").strip()
    or "<b>⚠️ Please join the channels below to get your file!</b>"
)
FSUB_IMG = environ.get("FSUB_IMG", None)

IMDB_TEMPLATE = environ.get(
    "IMDB_TEMPLATE",
    "<b>Query: {query}</b>\nIMDb Data:\n\n🏷 Title: <a href={url}>{title}</a>\n🎭 Genres: {genres}\n📆 Year: <a href={url}/releaseinfo>{year}</a>\n🌟 Rating: <a href={url}/ratings>{rating}</a> / 10",
)
LONG_IMDB_DESCRIPTION = is_enabled(environ.get("LONG_IMDB_DESCRIPTION", "False"), False)
SPELL_CHECK_REPLY = is_enabled(environ.get("SPELL_CHECK_REPLY", "True"), True)
MAX_LIST_ELM = environ.get("MAX_LIST_ELM", None)
INDEX_REQ_CHANNEL = _safe_int("INDEX_REQ_CHANNEL", LOG_CHANNEL)
FILE_STORE_CHANNEL = [
    x
    for x in _safe_int_list("FILE_STORE_CHANNEL", "-1002961955349")
    if isinstance(x, int)
]
MELCOW_NEW_USERS = is_enabled(environ.get("MELCOW_NEW_USERS", "False"), False)
PROTECT_CONTENT = is_enabled(environ.get("PROTECT_CONTENT", "False"), False)
PUBLIC_FILE_STORE = is_enabled(environ.get("PUBLIC_FILE_STORE", "True"), True)
MOVIE_UPDATE_NOTIFICATION = is_enabled(
    environ.get("MOVIE_UPDATE_NOTIFICATION", "True"), True
)

MOVIE_UPDATE_CHANNEL = [
    x
    for x in _safe_int_list(
        "MOVIE_UPDATE_CHANNEL",
        "-1001923564465 -1002391396205 -1002102723064 -1002032840255 -1002438454087 -1002436948244 -1002459789086 -1002309583611",
    )
    if isinstance(x, int)
]
AUTOPOSTCHANNEL = [
    x for x in _safe_int_list("AUTOPOSTCHANNEL", "-1001923564465") if isinstance(x, int)
]

IMAGE_FETCH = is_enabled(environ.get("IMAGE_FETCH", "True"), True)
LINK_PREVIEW = is_enabled(environ.get("LINK_PREVIEW", "False"), False)
ABOVE_PREVIEW = is_enabled(environ.get("ABOVE_PREVIEW", "True"), True)
TMDB_API_KEY = environ.get("TMDB_API_KEY", "").strip()
TMDB_POSTER = is_enabled(environ.get("TMDB_POSTER", "False"), False)
LANDSCAPE_POSTER = is_enabled(environ.get("LANDSCAPE_POSTER", "True"), True)

LOG_STR = (
    f"Config Loaded | IMDB={IMDB} | P_TTI_SHOW_OFF={P_TTI_SHOW_OFF} | "
    f"SINGLE_BUTTON={SINGLE_BUTTON} | SPELL_CHECK={SPELL_CHECK_REPLY} | "
    f"AUTO_INDEX={AUTO_INDEX} | MULTI_BOT={MULTI_BOT_ENABLED}"
)
