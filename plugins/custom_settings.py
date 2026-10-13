import asyncio
import re
from logging import ERROR, getLogger

import requests
from motor.motor_asyncio import AsyncIOMotorClient
from pyrogram import Client, enums, filters
from pyrogram.types import Message

import info
from utils import save_group_settings

logger = getLogger(__name__)
logger.setLevel(ERROR)

# ============================================================
# ⚙️ DIRECT MONGODB ISOLATION (ZERO CONFLICTS)
# ============================================================
try:
    _DB_CLIENT = AsyncIOMotorClient(info.DATABASE_URI)
    _BOT_DB = _DB_CLIENT[info.DATABASE_NAME]
    b_settings_db = _BOT_DB["global_bot_settings"]
    g_welcome_db = _BOT_DB["group_welcome_settings"]
    _active_db = _BOT_DB["active_connections"]
except Exception as e:
    logger.error(f"Failed to init custom settings DB: {e}")
    b_settings_db = g_welcome_db = _active_db = None


async def get_bot_settings():
    if b_settings_db is not None:
        doc = await b_settings_db.find_one({"_id": "bot_config"})
        return doc or {}
    return {}

async def update_bot_settings(key, value):
    if b_settings_db is not None:
        await b_settings_db.update_one({"_id": "bot_config"}, {"$set": {key: value}}, upsert=True)

async def get_group_welcome(chat_id):
    if g_welcome_db is not None:
        doc = await g_welcome_db.find_one({"_id": chat_id})
        return doc or {}
    return {}

async def update_group_welcome(chat_id, key, value):
    if g_welcome_db is not None:
        await g_welcome_db.update_one({"_id": chat_id}, {"$set": {key: value}}, upsert=True)


# ============================================================
# 👑 SMART AUTHORIZATION & CONNECTION ENGINE
# ============================================================
def get_admin_list():
    admin_list = []
    raw_admins = getattr(info, "ADMINS", [])
    if isinstance(raw_admins, int):
        admin_list.append(raw_admins)
    elif isinstance(raw_admins, str):
        admin_list.extend([int(x.strip()) for x in raw_admins.split() if x.strip().replace("-", "").isdigit()])
    elif isinstance(raw_admins, list):
        admin_list.extend([int(x) for x in raw_admins if str(x).strip().replace("-", "").isdigit()])
    return admin_list

async def is_global_admin(user_id: int):
    """Check if the user is a Global Bot Admin (in info.ADMINS)"""
    return user_id in get_admin_list()

async def is_group_admin(client: Client, user_id: int, chat_id: int):
    """Check if the user is an admin of the specified group, OR a Global Admin"""
    if await is_global_admin(user_id):
        return True
    try:
        member = await client.get_chat_member(chat_id, user_id)
        return member.status in [enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER]
    except Exception:
        return False

async def get_active_group(user_id: str):
    """Safely fetch the currently connected active group natively from MongoDB."""
    try:
        if _active_db is not None:
            doc = await _active_db.find_one({"user_id": str(user_id)})
            if doc and "group_id" in doc: return int(doc["group_id"])
        return None
    except Exception as e:
        logger.error(f"Error fetching active connection: {e}")
        return None

async def get_target_chat(client: Client, message: Message):
    """Gets target chat ID. If in PM, uses the active connected group."""
    if message.chat.type == enums.ChatType.PRIVATE:
        user_id = message.from_user.id
        connected_chat = await get_active_group(str(user_id))
        if connected_chat:
            return int(connected_chat)
        return None
    return message.chat.id


# ============================================================
# 🛑 SMART STOPWORDS ENGINE (GLOBAL SETTING)
# ============================================================
DEFAULT_STOPWORDS = [
    "send", "snd", "give", "gib", "pls", "plz", "please", "need", "want", "upload", "uplod", "drop",
    "share", "find", "search", "provide", "post", "movie", "movies", "film", "films", "cinema", "cinemas",
    "full", "fullmovie", "download", "downlod", "link", "links", "file", "files", "print", "audio", "ott",
    "hd", "hq", "bluray", "rip", "watch", "online", "admin", "beku", "bekithu", "bekittu", "bekagide",
    "kodi", "kodro", "kalsi", "kalsro", "kalisi", "haki", "haku", "hakro", "ideya", "irboda", "bidi", "madu",
    "yaradru", "kannadadalli", "sandalwood", "kr_picture", "kannada_filmy_group", "telegram", "dubbed"
]

ACTIVE_STOPWORDS = DEFAULT_STOPWORDS.copy()
_stopwords_loaded = False

def get_stopwords():
    return ACTIVE_STOPWORDS

@Client.on_message(filters.all, group=-999)
async def load_stopwords_on_boot(client, message):
    global _stopwords_loaded, ACTIVE_STOPWORDS
    if _stopwords_loaded: return
    settings = await get_bot_settings()
    custom_stops = settings.get("custom_stopwords")
    ACTIVE_STOPWORDS = custom_stops if custom_stops is not None else DEFAULT_STOPWORDS.copy()
    _stopwords_loaded = True

@Client.on_message(filters.command("addstopwords"))
async def add_stopwords(client, message):
    global ACTIVE_STOPWORDS
    user_id = message.from_user.id if message.from_user else getattr(message.sender_chat, "id", 0)
    if not await is_global_admin(user_id):
        return await message.reply_text("❌ **Unauthorized:** You must be a Global Bot Admin to use this command.")

    if len(message.command) < 2: return await message.reply_text("⚠️ **Usage:** `/addstopwords word1, word2`")

    new_words = [w.strip().lower() for w in message.text.split(None, 1)[1].split(",") if w.strip()]
    ACTIVE_STOPWORDS = list(set(ACTIVE_STOPWORDS + new_words))
    await update_bot_settings("custom_stopwords", ACTIVE_STOPWORDS)
    await message.reply_text(f"✅ **Added {len(new_words)} stopwords globally.**\nTotal Active: `{len(ACTIVE_STOPWORDS)}`")

@Client.on_message(filters.command("stopwords"))
async def show_stopwords(client, message):
    user_id = message.from_user.id if message.from_user else getattr(message.sender_chat, "id", 0)
    if not await is_global_admin(user_id): return await message.reply_text("❌ **Unauthorized:** You must be a Global Bot Admin.")

    if not ACTIVE_STOPWORDS: return await message.reply_text("ℹ️ **No stopwords are currently active.**")
    await message.reply_text(f"🛑 **Current Active Stopwords:**\n\n`{', '.join(ACTIVE_STOPWORDS)}`\n\n**Total:** `{len(ACTIVE_STOPWORDS)}`")

@Client.on_message(filters.command("remstopwords"))
async def rem_stopwords(client, message):
    global ACTIVE_STOPWORDS
    user_id = message.from_user.id if message.from_user else getattr(message.sender_chat, "id", 0)
    if not await is_global_admin(user_id): return await message.reply_text("❌ **Unauthorized:** You must be a Global Bot Admin.")

    if len(message.command) < 2: return await message.reply_text("⚠️ **Usage:** `/remstopwords word1, word2`")

    words_to_remove = [w.strip().lower() for w in message.text.split(None, 1)[1].split(",") if w.strip()]
    if not ACTIVE_STOPWORDS: return await message.reply_text("ℹ️ **There are no stopwords to remove.**")

    original_count = len(ACTIVE_STOPWORDS)
    ACTIVE_STOPWORDS = [w for w in ACTIVE_STOPWORDS if w not in words_to_remove]
    await update_bot_settings("custom_stopwords", ACTIVE_STOPWORDS)
    await message.reply_text(f"✅ **Removed {original_count - len(ACTIVE_STOPWORDS)} stopwords.**\nTotal Left: `{len(ACTIVE_STOPWORDS)}`")

@Client.on_message(filters.command("remallstopwords"))
async def rem_all_stopwords(client, message):
    global ACTIVE_STOPWORDS
    user_id = message.from_user.id if message.from_user else getattr(message.sender_chat, "id", 0)
    if not await is_global_admin(user_id): return await message.reply_text("❌ **Unauthorized.**")

    ACTIVE_STOPWORDS = []
    await update_bot_settings("custom_stopwords", [])
    await message.reply_text("🗑️ **All stopwords have been completely removed globally.**")

@Client.on_message(filters.command("defaultstopwords"))
async def default_stopwords(client, message):
    global ACTIVE_STOPWORDS
    user_id = message.from_user.id if message.from_user else getattr(message.sender_chat, "id", 0)
    if not await is_global_admin(user_id): return await message.reply_text("❌ **Unauthorized.**")

    ACTIVE_STOPWORDS = DEFAULT_STOPWORDS.copy()
    await update_bot_settings("custom_stopwords", ACTIVE_STOPWORDS)
    await message.reply_text("✅ **Stopwords have been successfully reset to default.**")


# ============================================================
# ⚡ 10-LAYER TITANIUM UPLOAD ENGINE (FOR PERMANENT IMAGES)
# ============================================================
def _upload_sync(file_bytes):
    headers = {"User-Agent": "Mozilla/5.0"}
    for url, files_dict, data_dict in [
        ("https://catbox.moe/user/api.php", {"fileToUpload": ("img.jpg", file_bytes, "image/jpeg")}, {"reqtype": "fileupload"}),
        ("https://graph.org/upload", {"file": ("img.jpg", file_bytes, "image/jpeg")}, None),
        ("https://envs.sh", {"file": ("img.jpg", file_bytes, "image/jpeg")}, None),
        ("https://x0.at", {"file": ("img.jpg", file_bytes, "image/jpeg")}, None),
        ("https://ttm.sh", {"file": ("img.jpg", file_bytes, "image/jpeg")}, None),
        ("https://0x0.st", {"file": ("img.jpg", file_bytes, "image/jpeg")}, None),
        ("https://pixeldrain.com/api/file", {"file": ("img.jpg", file_bytes, "image/jpeg")}, None),
        ("https://file.io", {"file": ("img.jpg", file_bytes, "image/jpeg")}, None),
        ("https://telegra.ph/upload", {"file": ("img.jpg", file_bytes, "image/jpeg")}, None)
    ]:
        try:
            res = requests.post(url, data=data_dict, files=files_dict, headers=headers, timeout=6)
            if res.status_code in [200, 201]:
                if url in ["https://graph.org/upload", "https://telegra.ph/upload"]: return url.rsplit("/", 1)[0] + res.json()[0]["src"]
                elif "pixeldrain" in url and res.json().get("success"): return "https://pixeldrain.com/api/file/" + res.json()["id"]
                elif "file.io" in url and res.json().get("success"): return res.json()["link"]
                elif res.text.startswith("http"): return res.text.strip()
        except Exception: continue
    return None

async def upload_image_safely(client: Client, message: Message):
    try:
        file_io = await client.download_media(message, in_memory=True)
        if not file_io: return None, "❌ Failed to download the image."
        url = await asyncio.to_thread(_upload_sync, file_io.getvalue())
        if not url: return None, "❌ All cloud uploaders failed."
        return url, None
    except Exception as e: return None, f"❌ Internal Error: {e}"


# ============================================================
# 🖼️ GLOBAL IMAGE SETTINGS (GLOBAL ADMINS ONLY)
# ============================================================
async def process_global_image_setting(client: Client, message: Message, setting_key: str, success_msg: str):
    user_id = message.from_user.id if message.from_user else getattr(message.sender_chat, "id", 0)
    if not await is_global_admin(user_id): return await message.reply_text("❌ **Unauthorized:** You must be a Global Bot Admin to use this.")

    if not message.reply_to_message or not message.reply_to_message.photo: return await message.reply_text(f"⚠️ **Usage:** Reply to a photo with `/{message.command[0]}`")

    status = await message.reply_text("⏳ Uploading to Cloud...")
    url, err = await upload_image_safely(client, message.reply_to_message)

    if url:
        await update_bot_settings(setting_key, url)
        await status.edit_text(f"✅ **{success_msg}**\n*(Saved permanently to cloud)*")
    else:
        file_id = message.reply_to_message.photo.file_id
        await update_bot_settings(setting_key, file_id)
        await status.edit_text(f"⚠️ Cloud blocked. **{success_msg}**\n*(Saved as Telegram File_ID)*")

@Client.on_message(filters.command("setfsubimg"))
async def set_fsub_img(client, message): await process_global_image_setting(client, message, "fsub_img", "Force Subscribe Image updated!")

@Client.on_message(filters.command("setautoimg"))
async def set_auto_img(client, message): await process_global_image_setting(client, message, "auto_img", "Default Auto-Filter Image updated!")

@Client.on_message(filters.command("setfilenotfoundimg"))
async def set_fnf_img(client, message): await process_global_image_setting(client, message, "not_found_img", "File Not Found Image updated!")

@Client.on_message(filters.command("remautoimg"))
async def rem_auto_img(client, message):
    user_id = message.from_user.id if message.from_user else getattr(message.sender_chat, "id", 0)
    if not await is_global_admin(user_id): return await message.reply_text("❌ **Unauthorized.**")
    await update_bot_settings("auto_img", None)
    await message.reply_text("🗑️ **Default Auto-Filter Image removed.**")

@Client.on_message(filters.command("remfilenotfoundimg"))
async def rem_fnf_img(client, message):
    user_id = message.from_user.id if message.from_user else getattr(message.sender_chat, "id", 0)
    if not await is_global_admin(user_id): return await message.reply_text("❌ **Unauthorized.**")
    await update_bot_settings("not_found_img", None)
    await message.reply_text("🗑️ **File Not Found Image removed.**")

@Client.on_message(filters.command("defaultfilenotfoundimg"))
async def default_fnf_img(client, message):
    user_id = message.from_user.id if message.from_user else getattr(message.sender_chat, "id", 0)
    if not await is_global_admin(user_id): return await message.reply_text("❌ **Unauthorized.**")
    await update_bot_settings("not_found_img", getattr(info, "NOT_FOUND_IMG", None))
    await message.reply_text("✅ **File Not Found Image reset to default.**")


# ============================================================
# 📝 GLOBAL TEXT SETTINGS (GLOBAL ADMINS ONLY)
# ============================================================
@Client.on_message(filters.command("setnotfoundtext"))
async def set_fnf_text(client, message):
    user_id = message.from_user.id if message.from_user else getattr(message.sender_chat, "id", 0)
    if not await is_global_admin(user_id): return await message.reply_text("❌ **Unauthorized.**")
    if len(message.command) < 2: return await message.reply_text("⚠️ **Usage:** `/setnotfoundtext <your text>`")
    await update_bot_settings("not_found_text", message.text.split(None, 1)[1])
    await message.reply_text("✅ **File Not Found Text updated!**")

@Client.on_message(filters.command("remnotfoundtext"))
async def rem_fnf_text(client, message):
    user_id = message.from_user.id if message.from_user else getattr(message.sender_chat, "id", 0)
    if not await is_global_admin(user_id): return await message.reply_text("❌ **Unauthorized.**")
    await update_bot_settings("not_found_text", None)
    await message.reply_text("🗑️ **File Not Found Text removed.**")

@Client.on_message(filters.command("defaultnotfoundtext"))
async def def_fnf_text(client, message):
    user_id = message.from_user.id if message.from_user else getattr(message.sender_chat, "id", 0)
    if not await is_global_admin(user_id): return await message.reply_text("❌ **Unauthorized.**")
    await update_bot_settings("not_found_text", getattr(info, "NOT_FOUND_MSG", "<b>🚫 File not found.</b>"))
    await message.reply_text("✅ **File Not Found Text reset to default.**")


# ============================================================
# 🪄 SPELL CHECK (SMART PM & GROUP ROUTING)
# ============================================================
@Client.on_message(filters.command("enablespellcheck"))
async def enable_spell_check(client, message):
    user_id = message.from_user.id if message.from_user else getattr(message.sender_chat, "id", 0)
    target_chat_id = await get_target_chat(client, message)

    if not target_chat_id: return await message.reply_text("⚠️ **No active connection!**\nPlease run `/connect <group_id>` first or use this command inside a group.")
    if not await is_group_admin(client, user_id, target_chat_id): return await message.reply_text(f"❌ **Unauthorized:** You must be an Admin of the connected group (`{target_chat_id}`).")

    await save_group_settings(target_chat_id, "spell_check", True)
    await message.reply_text(f"✅ **Spell Check Enabled for chat:** `{target_chat_id}`")

@Client.on_message(filters.command("disablespellcheck"))
async def disable_spell_check(client, message):
    user_id = message.from_user.id if message.from_user else getattr(message.sender_chat, "id", 0)
    target_chat_id = await get_target_chat(client, message)

    if not target_chat_id: return await message.reply_text("⚠️ **No active connection!**\nPlease run `/connect <group_id>` first or use this command inside a group.")
    if not await is_group_admin(client, user_id, target_chat_id): return await message.reply_text(f"❌ **Unauthorized:** You must be an Admin of the connected group (`{target_chat_id}`).")

    await save_group_settings(target_chat_id, "spell_check", False)
    await message.reply_text(f"🚫 **Spell Check Disabled for chat:** `{target_chat_id}`")


# ============================================================
# 👋 WELCOME SETTINGS (SMART PM & GROUP ROUTING)
# ============================================================
@Client.on_message(filters.command("enablewelcome"))
async def enable_welc(client, message):
    user_id = message.from_user.id if message.from_user else getattr(message.sender_chat, "id", 0)
    target_chat_id = await get_target_chat(client, message)

    if not target_chat_id: return await message.reply_text("⚠️ **No active connection!** Please run `/connect <group_id>` first.")
    if not await is_group_admin(client, user_id, target_chat_id): return await message.reply_text("❌ Unauthorized.")

    await update_group_welcome(target_chat_id, "welcome", True)
    await message.reply_text(f"✅ **Welcome Messages Enabled for `{target_chat_id}`.**")

@Client.on_message(filters.command("disablewelcome"))
async def disable_welc(client, message):
    user_id = message.from_user.id if message.from_user else getattr(message.sender_chat, "id", 0)
    target_chat_id = await get_target_chat(client, message)

    if not target_chat_id: return await message.reply_text("⚠️ **No active connection!** Please run `/connect <group_id>` first.")
    if not await is_group_admin(client, user_id, target_chat_id): return await message.reply_text("❌ Unauthorized.")

    await update_group_welcome(target_chat_id, "welcome", False)
    await message.reply_text(f"🚫 **Welcome Messages Disabled for `{target_chat_id}`.**")

@Client.on_message(filters.command("setwelcometxt"))
async def set_welc_txt(client, message):
    user_id = message.from_user.id if message.from_user else getattr(message.sender_chat, "id", 0)
    target_chat_id = await get_target_chat(client, message)

    if not target_chat_id: return await message.reply_text("⚠️ **No active connection!** Please run `/connect <group_id>` first.")
    if not await is_group_admin(client, user_id, target_chat_id): return await message.reply_text("❌ Unauthorized.")

    if len(message.command) < 2: return await message.reply_text("⚠️ **Usage:** `/setwelcometxt <Your text>`\n\n💡 Variables: `{mention}`, `{title}`, `{count}`")

    text_val = message.text.split(None, 1)[1]
    await update_group_welcome(target_chat_id, "text", text_val)
    await message.reply_text(f"✅ **Welcome Text updated for `{target_chat_id}`!**")

@Client.on_message(filters.command("setwelcomeimg"))
async def set_welc_img(client, message):
    user_id = message.from_user.id if message.from_user else getattr(message.sender_chat, "id", 0)
    target_chat_id = await get_target_chat(client, message)

    if not target_chat_id: return await message.reply_text("⚠️ **No active connection!** Please run `/connect <group_id>` first.")
    if not await is_group_admin(client, user_id, target_chat_id): return await message.reply_text("❌ Unauthorized.")

    if not message.reply_to_message or not message.reply_to_message.photo: return await message.reply_text("⚠️ **Usage:** Reply to a photo with `/setwelcomeimg`")

    status = await message.reply_text("⏳ Uploading to Cloud...")
    url, err = await upload_image_safely(client, message.reply_to_message)
    if url:
        await update_group_welcome(target_chat_id, "img", url)
        await status.edit_text(f"✅ **Welcome Image updated for `{target_chat_id}` (Cloud Saved)!**")
    else:
        await update_group_welcome(target_chat_id, "img", message.reply_to_message.photo.file_id)
        await status.edit_text(f"⚠️ Cloud blocked. **Welcome Image updated for `{target_chat_id}` (File ID Saved)!**")

@Client.on_message(filters.command("setwelcome"))
async def set_welcome_both(client, message):
    user_id = message.from_user.id if message.from_user else getattr(message.sender_chat, "id", 0)
    target_chat_id = await get_target_chat(client, message)

    if not target_chat_id: return await message.reply_text("⚠️ **No active connection!** Please run `/connect <group_id>` first.")
    if not await is_group_admin(client, user_id, target_chat_id): return await message.reply_text("❌ Unauthorized.")

    if not message.reply_to_message or not message.reply_to_message.photo: return await message.reply_text("⚠️ **Usage:** Reply to a photo containing a caption with `/setwelcome`")

    txt = message.reply_to_message.caption
    status = await message.reply_text("⏳ Processing...")

    url, err = await upload_image_safely(client, message.reply_to_message)
    img_data = url if url else message.reply_to_message.photo.file_id

    await update_group_welcome(target_chat_id, "img", img_data)
    if txt: await update_group_welcome(target_chat_id, "text", txt)
    await update_group_welcome(target_chat_id, "welcome", True)

    await status.edit_text(f"✅ **Welcome Image & Text set for `{target_chat_id}`!**")

@Client.on_message(filters.command("delwelcome"))
async def del_welcome(client, message):
    user_id = message.from_user.id if message.from_user else getattr(message.sender_chat, "id", 0)
    target_chat_id = await get_target_chat(client, message)

    if not target_chat_id: return await message.reply_text("⚠️ **No active connection!** Please run `/connect <group_id>` first.")
    if not await is_group_admin(client, user_id, target_chat_id): return await message.reply_text("❌ Unauthorized.")

    await update_group_welcome(target_chat_id, "img", None)
    await update_group_welcome(target_chat_id, "text", None)
    await update_group_welcome(target_chat_id, "welcome", False)
    await message.reply_text(f"🗑️ **Welcome settings deleted and disabled for `{target_chat_id}`.**")
