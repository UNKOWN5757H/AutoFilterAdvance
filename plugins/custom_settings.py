import asyncio
import html
import re
from logging import ERROR, getLogger

import requests
from motor.motor_asyncio import AsyncIOMotorClient
from pyrogram import Client, enums, filters
from pyrogram.types import Message

import info
from utils import save_group_settings

# Optional standard connection database fallback
try:
    from database.connections_mdb import active_connection as _std_active_connection
except ImportError:
    _std_active_connection = None

logger = getLogger(__name__)
logger.setLevel(ERROR)

# ============================================================
# ⚙️ DIRECT MONGODB ISOLATION (ZERO CONFLICTS)
# ============================================================
b_settings_db = g_welcome_db = _active_db = _std_conn_db = _custom_cap_db = None
try:
    _DB_CLIENT = AsyncIOMotorClient(info.DATABASE_URI)
    _BOT_DB = _DB_CLIENT[info.DATABASE_NAME]
    b_settings_db = _BOT_DB["global_bot_settings"]
    g_welcome_db = _BOT_DB["group_welcome_settings"]
    _active_db = _BOT_DB["active_connections"]
    _std_conn_db = _BOT_DB["CONNECTION"]
    _custom_cap_db = _BOT_DB["custom_captions"]
except Exception as e:
    logger.error(f"Failed to init custom settings DB: {e}")

# Map custom_settings keys to info.py runtime attributes so all plugins stay in sync
_INFO_ATTR_MAP = {
    "fsub_img": "FSUB_IMG",
    "auto_img": "AUTO_IMG",
    "not_found_img": "NOT_FOUND_IMG",
    "not_found_text": "NOT_FOUND_MSG",
}


async def get_bot_settings():
    if b_settings_db is not None:
        doc = await b_settings_db.find_one({"_id": "bot_config"})
        return doc or {}
    return {}


async def update_bot_settings(key: str, value):
    if b_settings_db is not None:
        await b_settings_db.update_one(
            {"_id": "bot_config"}, {"$set": {key: value}}, upsert=True
        )
    # Also sync to runtime `info` module and `custom_captions` collection
    info_attr = _INFO_ATTR_MAP.get(key)
    if info_attr:
        setattr(info, info_attr, value)
        if _custom_cap_db is not None:
            try:
                await _custom_cap_db.update_one(
                    {"_id": "settings"}, {"$set": {info_attr: value}}, upsert=True
                )
            except Exception:
                pass


async def get_group_welcome(chat_id: int):
    if g_welcome_db is not None:
        doc = await g_welcome_db.find_one({"_id": int(chat_id)})
        return doc or {}
    return {}


async def update_group_welcome(chat_id: int, key: str, value):
    chat_id = int(chat_id)
    if g_welcome_db is not None:
        await g_welcome_db.update_one(
            {"_id": chat_id}, {"$set": {key: value}}, upsert=True
        )
    # Sync with group settings if applicable
    try:
        if key == "welcome":
            await save_group_settings(chat_id, "welcome", bool(value))
        elif key == "text":
            await save_group_settings(chat_id, "welcome_text", value)
        elif key == "img":
            await save_group_settings(chat_id, "welcome_img", value)
    except Exception:
        pass


# ============================================================
# 👑 SMART AUTHORIZATION & CONNECTION ENGINE
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
    """Check if the user is a Global Bot Admin (in info.ADMINS)."""
    return int(user_id) in get_admin_list() if user_id else False


async def is_group_admin(client: Client, user_id: int, chat_id: int) -> bool:
    """Check if the user is an admin of the specified group, OR a Global Admin."""
    if await is_global_admin(user_id):
        return True
    if not user_id or not chat_id:
        return False
    try:
        member = await client.get_chat_member(int(chat_id), int(user_id))
        return member.status in [
            enums.ChatMemberStatus.ADMINISTRATOR,
            enums.ChatMemberStatus.OWNER,
        ]
    except Exception:
        return False


async def get_active_group(user_id: int):
    """Safely fetch the currently connected active group across all connection schemas."""
    # 1. Try standard connections_mdb helper first
    if callable(_std_active_connection):
        try:
            conn = await _std_active_connection(str(user_id))
            if conn:
                return int(conn)
        except Exception:
            pass

    # 2. Try custom active_connections collection
    try:
        if _active_db is not None:
            doc = await _active_db.find_one(
                {
                    "$or": [
                        {"user_id": str(user_id)},
                        {"user_id": int(user_id)},
                        {"_id": str(user_id)},
                        {"_id": int(user_id)},
                    ]
                }
            )
            if doc:
                gid = (
                    doc.get("group_id") or doc.get("active_group") or doc.get("chat_id")
                )
                if gid:
                    return int(gid)
    except Exception as e:
        logger.error(f"Error fetching active connection: {e}")

    # 3. Try standard CONNECTION collection directly
    try:
        if _std_conn_db is not None:
            doc = await _std_conn_db.find_one(
                {"$or": [{"_id": str(user_id)}, {"_id": int(user_id)}]}
            )
            if doc and doc.get("active_group"):
                return int(doc["active_group"])
    except Exception:
        pass

    return None


async def get_target_chat(client: Client, message: Message):
    """Gets target chat ID. Supports group execution, connected PM, or explicit -100... chat ID argument."""
    # Check if first command argument is a chat ID (e.g. /enablewelcome -100123456789)
    if message.command and len(message.command) > 1:
        first_arg = message.command[1].strip()
        if first_arg.startswith("-100") and first_arg.lstrip("-").isdigit():
            return int(first_arg)

    if message.chat.type == enums.ChatType.PRIVATE:
        if not message.from_user:
            return None
        connected_chat = await get_active_group(message.from_user.id)
        if connected_chat:
            return int(connected_chat)
        return None
    return message.chat.id


def extract_text_payload(message: Message) -> str:
    """Extracts HTML text from either a replied message or command arguments."""
    if message.reply_to_message:
        replied = message.reply_to_message
        raw = replied.text or replied.caption
        if raw:
            return getattr(raw, "html", str(raw))
    if message.text and len(message.command) > 1:
        raw_html = getattr(message.text, "html", str(message.text))
        cleaned = re.sub(r"^/\w+(?:@[a-zA-Z0-9_]+)?\s+", "", raw_html, count=1)
        # Strip leading chat_id if provided as first argument
        cleaned = re.sub(r"^-100\d+\s*", "", cleaned, count=1)
        return cleaned.strip() or None
    return None


# ============================================================
# 🛑 SMART STOPWORDS ENGINE (GLOBAL SETTING)
# ============================================================
DEFAULT_STOPWORDS = [
    "send",
    "snd",
    "give",
    "gib",
    "pls",
    "plz",
    "please",
    "need",
    "want",
    "upload",
    "uplod",
    "drop",
    "share",
    "find",
    "search",
    "provide",
    "post",
    "movie",
    "movies",
    "film",
    "films",
    "cinema",
    "cinemas",
    "full",
    "fullmovie",
    "download",
    "downlod",
    "link",
    "links",
    "file",
    "files",
    "print",
    "audio",
    "ott",
    "hd",
    "hq",
    "bluray",
    "rip",
    "watch",
    "online",
    "admin",
    "beku",
    "bekithu",
    "bekittu",
    "bekagide",
    "kodi",
    "kodro",
    "kalsi",
    "kalsro",
    "kalisi",
    "haki",
    "haku",
    "hakro",
    "ideya",
    "irboda",
    "bidi",
    "madu",
    "yaradru",
    "kannadadalli",
    "sandalwood",
    "kr_picture",
    "kannada_filmy_group",
    "telegram",
    "dubbed",
]

ACTIVE_STOPWORDS = DEFAULT_STOPWORDS.copy()
_stopwords_loaded = False


def get_stopwords():
    return ACTIVE_STOPWORDS


@Client.on_message(filters.all, group=-999)
async def load_stopwords_on_boot(client: Client, message: Message):
    global _stopwords_loaded, ACTIVE_STOPWORDS
    if _stopwords_loaded:
        return
    _stopwords_loaded = True
    try:
        settings = await get_bot_settings()
        custom_stops = settings.get("custom_stopwords")
        if custom_stops is not None:
            ACTIVE_STOPWORDS = list(custom_stops)
        # Sync saved global images/texts into info module on boot
        for db_key, info_attr in _INFO_ATTR_MAP.items():
            if db_key in settings and settings[db_key] is not None:
                setattr(info, info_attr, settings[db_key])
    except Exception as e:
        logger.error(f"Boot settings load error: {e}")


@Client.on_message(filters.command("addstopwords") & filters.incoming)
async def add_stopwords(client: Client, message: Message):
    global ACTIVE_STOPWORDS
    user_id = (
        message.from_user.id
        if message.from_user
        else getattr(message.sender_chat, "id", 0)
    )
    if not await is_global_admin(user_id):
        return await message.reply_text(
            "❌ <b>Unauthorized:</b> You must be a Global Bot Admin to use this command.",
            parse_mode=enums.ParseMode.HTML,
        )

    if len(message.command) < 2:
        return await message.reply_text(
            "⚠️ <b>Usage:</b> <code>/addstopwords word1, word2</code>",
            parse_mode=enums.ParseMode.HTML,
        )

    raw_input = message.text.split(None, 1)[1]
    new_words = [w.strip().lower() for w in re.split(r"[,\n]+", raw_input) if w.strip()]
    ACTIVE_STOPWORDS = sorted(list(set(ACTIVE_STOPWORDS + new_words)))
    await update_bot_settings("custom_stopwords", ACTIVE_STOPWORDS)
    await message.reply_text(
        f"✅ <b>Added {len(new_words)} stopwords globally.</b>\n"
        f"📊 <b>Total Active:</b> <code>{len(ACTIVE_STOPWORDS)}</code>",
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(filters.command("stopwords") & filters.incoming)
async def show_stopwords(client: Client, message: Message):
    user_id = (
        message.from_user.id
        if message.from_user
        else getattr(message.sender_chat, "id", 0)
    )
    if not await is_global_admin(user_id):
        return await message.reply_text(
            "❌ <b>Unauthorized:</b> You must be a Global Bot Admin.",
            parse_mode=enums.ParseMode.HTML,
        )

    if not ACTIVE_STOPWORDS:
        return await message.reply_text(
            "ℹ️ <b>No stopwords are currently active.</b>",
            parse_mode=enums.ParseMode.HTML,
        )
    escaped_words = html.escape(", ".join(ACTIVE_STOPWORDS))
    await message.reply_text(
        f"🛑 <b>Current Active Stopwords:</b>\n\n"
        f"<code>{escaped_words}</code>\n\n"
        f"<b>Total:</b> <code>{len(ACTIVE_STOPWORDS)}</code>",
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(filters.command("remstopwords") & filters.incoming)
async def rem_stopwords(client: Client, message: Message):
    global ACTIVE_STOPWORDS
    user_id = (
        message.from_user.id
        if message.from_user
        else getattr(message.sender_chat, "id", 0)
    )
    if not await is_global_admin(user_id):
        return await message.reply_text(
            "❌ <b>Unauthorized:</b> You must be a Global Bot Admin.",
            parse_mode=enums.ParseMode.HTML,
        )

    if len(message.command) < 2:
        return await message.reply_text(
            "⚠️ <b>Usage:</b> <code>/remstopwords word1, word2</code>",
            parse_mode=enums.ParseMode.HTML,
        )

    raw_input = message.text.split(None, 1)[1]
    words_to_remove = {
        w.strip().lower() for w in re.split(r"[,\n]+", raw_input) if w.strip()
    }
    if not ACTIVE_STOPWORDS:
        return await message.reply_text(
            "ℹ️ <b>There are no stopwords to remove.</b>",
            parse_mode=enums.ParseMode.HTML,
        )

    original_count = len(ACTIVE_STOPWORDS)
    ACTIVE_STOPWORDS = [w for w in ACTIVE_STOPWORDS if w not in words_to_remove]
    await update_bot_settings("custom_stopwords", ACTIVE_STOPWORDS)
    await message.reply_text(
        f"✅ <b>Removed {original_count - len(ACTIVE_STOPWORDS)} stopwords.</b>\n"
        f"📊 <b>Total Left:</b> <code>{len(ACTIVE_STOPWORDS)}</code>",
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(filters.command("remallstopwords") & filters.incoming)
async def rem_all_stopwords(client: Client, message: Message):
    global ACTIVE_STOPWORDS
    user_id = (
        message.from_user.id
        if message.from_user
        else getattr(message.sender_chat, "id", 0)
    )
    if not await is_global_admin(user_id):
        return await message.reply_text(
            "❌ <b>Unauthorized.</b>", parse_mode=enums.ParseMode.HTML
        )

    ACTIVE_STOPWORDS = []
    await update_bot_settings("custom_stopwords", [])
    await message.reply_text(
        "🗑️ <b>All stopwords have been completely removed globally.</b>",
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(filters.command("defaultstopwords") & filters.incoming)
async def default_stopwords(client: Client, message: Message):
    global ACTIVE_STOPWORDS
    user_id = (
        message.from_user.id
        if message.from_user
        else getattr(message.sender_chat, "id", 0)
    )
    if not await is_global_admin(user_id):
        return await message.reply_text(
            "❌ <b>Unauthorized.</b>", parse_mode=enums.ParseMode.HTML
        )

    ACTIVE_STOPWORDS = DEFAULT_STOPWORDS.copy()
    await update_bot_settings("custom_stopwords", ACTIVE_STOPWORDS)
    await message.reply_text(
        "✅ <b>Stopwords have been successfully reset to default.</b>",
        parse_mode=enums.ParseMode.HTML,
    )


# ============================================================
# ⚡ 10-LAYER TITANIUM UPLOAD ENGINE (FOR PERMANENT IMAGES)
# ============================================================
def _upload_sync(file_bytes):
    headers = {"User-Agent": "Mozilla/5.0"}
    for url, files_dict, data_dict in [
        (
            "https://catbox.moe/user/api.php",
            {"fileToUpload": ("img.jpg", file_bytes, "image/jpeg")},
            {"reqtype": "fileupload"},
        ),
        (
            "https://graph.org/upload",
            {"file": ("img.jpg", file_bytes, "image/jpeg")},
            None,
        ),
        ("https://envs.sh", {"file": ("img.jpg", file_bytes, "image/jpeg")}, None),
        ("https://x0.at", {"file": ("img.jpg", file_bytes, "image/jpeg")}, None),
        ("https://ttm.sh", {"file": ("img.jpg", file_bytes, "image/jpeg")}, None),
        ("https://0x0.st", {"file": ("img.jpg", file_bytes, "image/jpeg")}, None),
        (
            "https://telegra.ph/upload",
            {"file": ("img.jpg", file_bytes, "image/jpeg")},
            None,
        ),
    ]:
        try:
            res = requests.post(
                url, data=data_dict, files=files_dict, headers=headers, timeout=8
            )
            if res.status_code in [200, 201]:
                if url in ["https://graph.org/upload", "https://telegra.ph/upload"]:
                    return url.rsplit("/", 1)[0] + res.json()[0]["src"]
                elif res.text.strip().startswith("http"):
                    return res.text.strip()
        except Exception:
            continue
    return None


async def upload_image_safely(client: Client, message: Message):
    try:
        file_io = await client.download_media(message, in_memory=True)
        if not file_io:
            return None, "❌ Failed to download the image."
        url = await asyncio.to_thread(_upload_sync, file_io.getvalue())
        if not url:
            return None, "❌ All cloud uploaders failed."
        return url, None
    except Exception as e:
        return None, f"❌ Internal Error: {e}"


# ============================================================
# 🖼️ GLOBAL IMAGE SETTINGS (GLOBAL ADMINS ONLY)
# ============================================================
async def process_global_image_setting(
    client: Client, message: Message, setting_key: str, success_msg: str
):
    user_id = (
        message.from_user.id
        if message.from_user
        else getattr(message.sender_chat, "id", 0)
    )
    if not await is_global_admin(user_id):
        return await message.reply_text(
            "❌ <b>Unauthorized:</b> You must be a Global Bot Admin to use this.",
            parse_mode=enums.ParseMode.HTML,
        )

    if not message.reply_to_message or not message.reply_to_message.photo:
        return await message.reply_text(
            f"⚠️ <b>Usage:</b> Reply to a photo with <code>/{message.command[0]}</code>",
            parse_mode=enums.ParseMode.HTML,
        )

    status = await message.reply_text(
        "⏳ <b>Uploading to Cloud...</b>", parse_mode=enums.ParseMode.HTML
    )
    url, _ = await upload_image_safely(client, message.reply_to_message)

    if url:
        await update_bot_settings(setting_key, url)
        await status.edit_text(
            f"✅ <b>{success_msg}</b>\n<i>(Saved permanently to cloud)</i>",
            parse_mode=enums.ParseMode.HTML,
        )
    else:
        file_id = message.reply_to_message.photo.file_id
        await update_bot_settings(setting_key, file_id)
        await status.edit_text(
            f"⚠️ Cloud blocked. <b>{success_msg}</b>\n<i>(Saved as Telegram File_ID)</i>",
            parse_mode=enums.ParseMode.HTML,
        )


@Client.on_message(filters.command("setfsubimg") & filters.incoming)
async def set_fsub_img(client: Client, message: Message):
    await process_global_image_setting(
        client, message, "fsub_img", "Force Subscribe Image updated!"
    )


@Client.on_message(filters.command("setautoimg") & filters.incoming)
async def set_auto_img(client: Client, message: Message):
    await process_global_image_setting(
        client, message, "auto_img", "Default Auto-Filter Image updated!"
    )


@Client.on_message(filters.command("setfilenotfoundimg") & filters.incoming)
async def set_fnf_img(client: Client, message: Message):
    await process_global_image_setting(
        client, message, "not_found_img", "File Not Found Image updated!"
    )


@Client.on_message(filters.command("remautoimg") & filters.incoming)
async def rem_auto_img(client: Client, message: Message):
    user_id = (
        message.from_user.id
        if message.from_user
        else getattr(message.sender_chat, "id", 0)
    )
    if not await is_global_admin(user_id):
        return await message.reply_text(
            "❌ <b>Unauthorized.</b>", parse_mode=enums.ParseMode.HTML
        )
    await update_bot_settings("auto_img", None)
    await message.reply_text(
        "🗑️ <b>Default Auto-Filter Image removed.</b>",
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(filters.command("remfilenotfoundimg") & filters.incoming)
async def rem_fnf_img(client: Client, message: Message):
    user_id = (
        message.from_user.id
        if message.from_user
        else getattr(message.sender_chat, "id", 0)
    )
    if not await is_global_admin(user_id):
        return await message.reply_text(
            "❌ <b>Unauthorized.</b>", parse_mode=enums.ParseMode.HTML
        )
    await update_bot_settings("not_found_img", None)
    await message.reply_text(
        "🗑️ <b>File Not Found Image removed.</b>",
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(filters.command("defaultfilenotfoundimg") & filters.incoming)
async def default_fnf_img(client: Client, message: Message):
    user_id = (
        message.from_user.id
        if message.from_user
        else getattr(message.sender_chat, "id", 0)
    )
    if not await is_global_admin(user_id):
        return await message.reply_text(
            "❌ <b>Unauthorized.</b>", parse_mode=enums.ParseMode.HTML
        )
    await update_bot_settings("not_found_img", getattr(info, "NOT_FOUND_IMG", None))
    await message.reply_text(
        "✅ <b>File Not Found Image reset to default.</b>",
        parse_mode=enums.ParseMode.HTML,
    )


# ============================================================
# 📝 GLOBAL TEXT SETTINGS (GLOBAL ADMINS ONLY)
# ============================================================
@Client.on_message(filters.command("setnotfoundtext") & filters.incoming)
async def set_fnf_text(client: Client, message: Message):
    user_id = (
        message.from_user.id
        if message.from_user
        else getattr(message.sender_chat, "id", 0)
    )
    if not await is_global_admin(user_id):
        return await message.reply_text(
            "❌ <b>Unauthorized.</b>", parse_mode=enums.ParseMode.HTML
        )

    text_val = extract_text_payload(message)
    if not text_val:
        return await message.reply_text(
            "⚠️ <b>Usage:</b> <code>/setnotfoundtext &lt;your text&gt;</code> or reply to a message.",
            parse_mode=enums.ParseMode.HTML,
        )
    await update_bot_settings("not_found_text", text_val)
    await message.reply_text(
        "✅ <b>File Not Found Text updated!</b>", parse_mode=enums.ParseMode.HTML
    )


@Client.on_message(filters.command("remnotfoundtext") & filters.incoming)
async def rem_fnf_text(client: Client, message: Message):
    user_id = (
        message.from_user.id
        if message.from_user
        else getattr(message.sender_chat, "id", 0)
    )
    if not await is_global_admin(user_id):
        return await message.reply_text(
            "❌ <b>Unauthorized.</b>", parse_mode=enums.ParseMode.HTML
        )
    await update_bot_settings("not_found_text", None)
    await message.reply_text(
        "🗑️ <b>File Not Found Text removed.</b>", parse_mode=enums.ParseMode.HTML
    )


@Client.on_message(filters.command("defaultnotfoundtext") & filters.incoming)
async def def_fnf_text(client: Client, message: Message):
    user_id = (
        message.from_user.id
        if message.from_user
        else getattr(message.sender_chat, "id", 0)
    )
    if not await is_global_admin(user_id):
        return await message.reply_text(
            "❌ <b>Unauthorized.</b>", parse_mode=enums.ParseMode.HTML
        )
    await update_bot_settings(
        "not_found_text", getattr(info, "NOT_FOUND_MSG", "<b>🚫 File not found.</b>")
    )
    await message.reply_text(
        "✅ <b>File Not Found Text reset to default.</b>",
        parse_mode=enums.ParseMode.HTML,
    )


# ============================================================
# 🪄 SPELL CHECK (SMART PM & GROUP ROUTING)
# ============================================================
@Client.on_message(filters.command("enablespellcheck") & filters.incoming)
async def enable_spell_check(client: Client, message: Message):
    user_id = (
        message.from_user.id
        if message.from_user
        else getattr(message.sender_chat, "id", 0)
    )
    target_chat_id = await get_target_chat(client, message)

    if not target_chat_id:
        return await message.reply_text(
            "⚠️ <b>No active connection!</b>\nPlease run <code>/connect &lt;group_id&gt;</code> first or use this command inside a group.",
            parse_mode=enums.ParseMode.HTML,
        )
    if not await is_group_admin(client, user_id, target_chat_id):
        return await message.reply_text(
            f"❌ <b>Unauthorized:</b> You must be an Admin of the target group (<code>{target_chat_id}</code>).",
            parse_mode=enums.ParseMode.HTML,
        )

    await save_group_settings(target_chat_id, "spell_check", True)
    await message.reply_text(
        f"✅ <b>Spell Check Enabled for chat:</b> <code>{target_chat_id}</code>",
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(filters.command("disablespellcheck") & filters.incoming)
async def disable_spell_check(client: Client, message: Message):
    user_id = (
        message.from_user.id
        if message.from_user
        else getattr(message.sender_chat, "id", 0)
    )
    target_chat_id = await get_target_chat(client, message)

    if not target_chat_id:
        return await message.reply_text(
            "⚠️ <b>No active connection!</b>\nPlease run <code>/connect &lt;group_id&gt;</code> first or use this command inside a group.",
            parse_mode=enums.ParseMode.HTML,
        )
    if not await is_group_admin(client, user_id, target_chat_id):
        return await message.reply_text(
            f"❌ <b>Unauthorized:</b> You must be an Admin of the target group (<code>{target_chat_id}</code>).",
            parse_mode=enums.ParseMode.HTML,
        )

    await save_group_settings(target_chat_id, "spell_check", False)
    await message.reply_text(
        f"🚫 <b>Spell Check Disabled for chat:</b> <code>{target_chat_id}</code>",
        parse_mode=enums.ParseMode.HTML,
    )


# ============================================================
# 👋 WELCOME SETTINGS & AUTO-GREETER (SMART PM & GROUP ROUTING)
# ============================================================
@Client.on_message(filters.command("enablewelcome") & filters.incoming)
async def enable_welc(client: Client, message: Message):
    user_id = (
        message.from_user.id
        if message.from_user
        else getattr(message.sender_chat, "id", 0)
    )
    target_chat_id = await get_target_chat(client, message)

    if not target_chat_id:
        return await message.reply_text(
            "⚠️ <b>No active connection!</b> Please run <code>/connect &lt;group_id&gt;</code> first or use this inside a group.",
            parse_mode=enums.ParseMode.HTML,
        )
    if not await is_group_admin(client, user_id, target_chat_id):
        return await message.reply_text(
            "❌ <b>Unauthorized.</b>", parse_mode=enums.ParseMode.HTML
        )

    await update_group_welcome(target_chat_id, "welcome", True)
    await message.reply_text(
        f"✅ <b>Welcome Messages Enabled for <code>{target_chat_id}</code>.</b>",
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(filters.command("disablewelcome") & filters.incoming)
async def disable_welc(client: Client, message: Message):
    user_id = (
        message.from_user.id
        if message.from_user
        else getattr(message.sender_chat, "id", 0)
    )
    target_chat_id = await get_target_chat(client, message)

    if not target_chat_id:
        return await message.reply_text(
            "⚠️ <b>No active connection!</b> Please run <code>/connect &lt;group_id&gt;</code> first or use this inside a group.",
            parse_mode=enums.ParseMode.HTML,
        )
    if not await is_group_admin(client, user_id, target_chat_id):
        return await message.reply_text(
            "❌ <b>Unauthorized.</b>", parse_mode=enums.ParseMode.HTML
        )

    await update_group_welcome(target_chat_id, "welcome", False)
    await message.reply_text(
        f"🚫 <b>Welcome Messages Disabled for <code>{target_chat_id}</code>.</b>",
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(filters.command("setwelcometxt") & filters.incoming)
async def set_welc_txt(client: Client, message: Message):
    user_id = (
        message.from_user.id
        if message.from_user
        else getattr(message.sender_chat, "id", 0)
    )
    target_chat_id = await get_target_chat(client, message)

    if not target_chat_id:
        return await message.reply_text(
            "⚠️ <b>No active connection!</b> Please run <code>/connect &lt;group_id&gt;</code> first or use this inside a group.",
            parse_mode=enums.ParseMode.HTML,
        )
    if not await is_group_admin(client, user_id, target_chat_id):
        return await message.reply_text(
            "❌ <b>Unauthorized.</b>", parse_mode=enums.ParseMode.HTML
        )

    text_val = extract_text_payload(message)
    if not text_val:
        return await message.reply_text(
            "⚠️ <b>Usage:</b> <code>/setwelcometxt &lt;Your text&gt;</code> or reply to a text message.\n\n"
            "💡 <b>Variables:</b> <code>{mention}</code>, <code>{title}</code>, <code>{count}</code>",
            parse_mode=enums.ParseMode.HTML,
        )

    await update_group_welcome(target_chat_id, "text", text_val)
    await update_group_welcome(target_chat_id, "welcome", True)
    await message.reply_text(
        f"✅ <b>Welcome Text updated for <code>{target_chat_id}</code>!</b>",
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(filters.command("setwelcomeimg") & filters.incoming)
async def set_welc_img(client: Client, message: Message):
    user_id = (
        message.from_user.id
        if message.from_user
        else getattr(message.sender_chat, "id", 0)
    )
    target_chat_id = await get_target_chat(client, message)

    if not target_chat_id:
        return await message.reply_text(
            "⚠️ <b>No active connection!</b> Please run <code>/connect &lt;group_id&gt;</code> first or use this inside a group.",
            parse_mode=enums.ParseMode.HTML,
        )
    if not await is_group_admin(client, user_id, target_chat_id):
        return await message.reply_text(
            "❌ <b>Unauthorized.</b>", parse_mode=enums.ParseMode.HTML
        )

    if not message.reply_to_message or not message.reply_to_message.photo:
        return await message.reply_text(
            "⚠️ <b>Usage:</b> Reply to a photo with <code>/setwelcomeimg</code>",
            parse_mode=enums.ParseMode.HTML,
        )

    status = await message.reply_text(
        "⏳ <b>Uploading to Cloud...</b>", parse_mode=enums.ParseMode.HTML
    )
    url, _ = await upload_image_safely(client, message.reply_to_message)
    if url:
        await update_group_welcome(target_chat_id, "img", url)
        await status.edit_text(
            f"✅ <b>Welcome Image updated for <code>{target_chat_id}</code> (Cloud Saved)!</b>",
            parse_mode=enums.ParseMode.HTML,
        )
    else:
        await update_group_welcome(
            target_chat_id, "img", message.reply_to_message.photo.file_id
        )
        await status.edit_text(
            f"⚠️ Cloud blocked. <b>Welcome Image updated for <code>{target_chat_id}</code> (File ID Saved)!</b>",
            parse_mode=enums.ParseMode.HTML,
        )


@Client.on_message(filters.command("setwelcome") & filters.incoming)
async def set_welcome_both(client: Client, message: Message):
    user_id = (
        message.from_user.id
        if message.from_user
        else getattr(message.sender_chat, "id", 0)
    )
    target_chat_id = await get_target_chat(client, message)

    if not target_chat_id:
        return await message.reply_text(
            "⚠️ <b>No active connection!</b> Please run <code>/connect &lt;group_id&gt;</code> first or use this inside a group.",
            parse_mode=enums.ParseMode.HTML,
        )
    if not await is_group_admin(client, user_id, target_chat_id):
        return await message.reply_text(
            "❌ <b>Unauthorized.</b>", parse_mode=enums.ParseMode.HTML
        )

    if not message.reply_to_message or not message.reply_to_message.photo:
        return await message.reply_text(
            "⚠️ <b>Usage:</b> Reply to a photo containing a caption with <code>/setwelcome</code>",
            parse_mode=enums.ParseMode.HTML,
        )

    raw_cap = message.reply_to_message.caption
    txt = getattr(raw_cap, "html", str(raw_cap)) if raw_cap else None
    status = await message.reply_text(
        "⏳ <b>Processing...</b>", parse_mode=enums.ParseMode.HTML
    )

    url, _ = await upload_image_safely(client, message.reply_to_message)
    img_data = url if url else message.reply_to_message.photo.file_id

    await update_group_welcome(target_chat_id, "img", img_data)
    if txt:
        await update_group_welcome(target_chat_id, "text", txt)
    await update_group_welcome(target_chat_id, "welcome", True)

    await status.edit_text(
        f"✅ <b>Welcome Image & Text set for <code>{target_chat_id}</code>!</b>",
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(filters.command("delwelcome") & filters.incoming)
async def del_welcome(client: Client, message: Message):
    user_id = (
        message.from_user.id
        if message.from_user
        else getattr(message.sender_chat, "id", 0)
    )
    target_chat_id = await get_target_chat(client, message)

    if not target_chat_id:
        return await message.reply_text(
            "⚠️ <b>No active connection!</b> Please run <code>/connect &lt;group_id&gt;</code> first or use this inside a group.",
            parse_mode=enums.ParseMode.HTML,
        )
    if not await is_group_admin(client, user_id, target_chat_id):
        return await message.reply_text(
            "❌ <b>Unauthorized.</b>", parse_mode=enums.ParseMode.HTML
        )

    await update_group_welcome(target_chat_id, "img", None)
    await update_group_welcome(target_chat_id, "text", None)
    await update_group_welcome(target_chat_id, "welcome", False)
    await message.reply_text(
        f"🗑️ <b>Welcome settings deleted and disabled for <code>{target_chat_id}</code>.</b>",
        parse_mode=enums.ParseMode.HTML,
    )
