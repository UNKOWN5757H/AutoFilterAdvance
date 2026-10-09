import asyncio
import time
import requests
from logging import ERROR, getLogger

from motor.motor_asyncio import AsyncIOMotorClient
from pyrogram import Client, enums, filters
from pyrogram.errors import MessageNotModified
from pyrogram.types import Message

import info
from utils import get_settings, save_group_settings

logger = getLogger(__name__)
logger.setLevel(ERROR)

# ============================================================
# ⚙️ DIRECT MONGODB ISOLATION (ZERO CONFLICTS)
# ============================================================
b_settings_db = None
g_welcome_db = None

try:
    _DB_CLIENT = AsyncIOMotorClient(info.DATABASE_URI)
    _BOT_DB = _DB_CLIENT[info.DATABASE_NAME]
    b_settings_db = _BOT_DB["global_bot_settings"]
    g_welcome_db = _BOT_DB["group_welcome_settings"]
except Exception as e:
    logger.error(f"Failed to init custom settings DB: {e}")

async def get_bot_settings():
    if b_settings_db is not None:
        doc = await b_settings_db.find_one({"_id": "bot_config"})
        return doc or {}
    return {}

async def update_bot_settings(key, value):
    if b_settings_db is not None:
        await b_settings_db.update_one({"_id": "bot_config"}, {"$set": {key: value}}, upsert=True)

# ⚡ RESTORED MISSING FUNCTION FOR p_ttishow.py
async def get_group_welcome(chat_id):
    if g_welcome_db is not None:
        doc = await g_welcome_db.find_one({"_id": chat_id})
        return doc or {}
    return {}

async def update_group_welcome(chat_id, key, value):
    if g_welcome_db is not None:
        await g_welcome_db.update_one({"_id": chat_id}, {"$set": {key: value}}, upsert=True)

# ============================================================
# 👑 FOOLPROOF ADMIN CHECKER
# ============================================================
def get_admin_list():
    raw_admins = getattr(info, "ADMINS", [])
    if isinstance(raw_admins, str): return [int(x) for x in raw_admins.replace(",", " ").split() if x.strip().lstrip("-").isdigit()]
    elif isinstance(raw_admins, int): return [raw_admins]
    elif isinstance(raw_admins, list): return [int(x) for x in raw_admins if str(x).strip().lstrip("-").isdigit()]
    return []

async def is_group_admin(client: Client, message: Message):
    if message.from_user.id in get_admin_list(): return True
    try:
        member = await client.get_chat_member(message.chat.id, message.from_user.id)
        return member.status in [enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER]
    except Exception: return False

admin_filter = filters.create(lambda _, __, msg: bool(msg.from_user and msg.from_user.id in get_admin_list()))

# ============================================================
# 🛑 SMART STOPWORDS ENGINE
# ============================================================
DEFAULT_STOPWORDS = [
    "send", "snd", "give", "gib", "pls", "plz", "please", "need", "want", "upload", 
    "uplod", "drop", "share", "find", "search", "provide", "post", "movie", "movies", 
    "film", "films", "cinema", "cinemas", "full", "fullmovie", "download", "downlod", 
    "link", "links", "file", "files", "print", "audio", "video", "ott", "hd", "hq", 
    "bluray", "rip", "watch", "online", "admin", "beku", "bekithu", "bekittu", "bekagide", 
    "kodi", "kodro", "kalsi", "kalsro", "kalisi", "haki", "haku", "hakro", "ideya", 
    "irboda", "bidi", "madu", "yaradru", "chitra", "chithra", "chalanachitra", 
    "chalanachithra", "kannadadalli", "sandalwood", "kr_picture", "kannada_filmy_group", 
    "telegram", "dubbed"
]

ACTIVE_STOPWORDS = DEFAULT_STOPWORDS.copy()
_stopwords_loaded = False

def get_stopwords(): return ACTIVE_STOPWORDS

@Client.on_message(filters.all, group=-999)
async def load_stopwords_on_boot(client, message):
    global _stopwords_loaded, ACTIVE_STOPWORDS
    if not _stopwords_loaded:
        settings = await get_bot_settings()
        custom_stops = settings.get("custom_stopwords")
        if custom_stops is not None: ACTIVE_STOPWORDS = custom_stops
        else: ACTIVE_STOPWORDS = DEFAULT_STOPWORDS.copy()
        _stopwords_loaded = True

@Client.on_message(filters.command("addstopwords") & admin_filter)
async def add_stopwords(client, message):
    global ACTIVE_STOPWORDS
    if len(message.command) < 2: return await message.reply_text("⚠️ **Usage:** `/addstopwords word1, word2`")
    new_words = [w.strip().lower() for w in message.text.split(None, 1)[1].split(",") if w.strip()]
    ACTIVE_STOPWORDS = list(set(ACTIVE_STOPWORDS + new_words))
    await update_bot_settings("custom_stopwords", ACTIVE_STOPWORDS)
    await message.reply_text(f"✅ **Added {len(new_words)} stopwords.**\nTotal Active Stopwords: `{len(ACTIVE_STOPWORDS)}`")

@Client.on_message(filters.command("stopwords") & admin_filter)
async def show_stopwords(client, message):
    if not ACTIVE_STOPWORDS: return await message.reply_text("ℹ️ **No stopwords are currently active.**")
    words_str = ", ".join(ACTIVE_STOPWORDS)
    await message.reply_text(f"🛑 **Current Active Stopwords:**\n\n`{words_str}`\n\n**Total:** `{len(ACTIVE_STOPWORDS)}`")

@Client.on_message(filters.command("remstopwords") & admin_filter)
async def rem_stopwords(client, message):
    global ACTIVE_STOPWORDS
    if len(message.command) < 2: return await message.reply_text("⚠️ **Usage:** `/remstopwords word1, word2`")
    words_to_remove = [w.strip().lower() for w in message.text.split(None, 1)[1].split(",") if w.strip()]
    if not ACTIVE_STOPWORDS: return await message.reply_text("ℹ️ **There are no stopwords to remove.**")
    original_count = len(ACTIVE_STOPWORDS)
    ACTIVE_STOPWORDS = [w for w in ACTIVE_STOPWORDS if w not in words_to_remove]
    removed_count = original_count - len(ACTIVE_STOPWORDS)
    await update_bot_settings("custom_stopwords", ACTIVE_STOPWORDS)
    await message.reply_text(f"✅ **Removed {removed_count} stopwords.**\nTotal Stopwords left: `{len(ACTIVE_STOPWORDS)}`")

@Client.on_message(filters.command("remallstopwords") & admin_filter)
async def rem_all_stopwords(client, message):
    global ACTIVE_STOPWORDS
    ACTIVE_STOPWORDS = []
    await update_bot_settings("custom_stopwords", [])
    await message.reply_text("🗑️ **All stopwords have been completely removed.**")

@Client.on_message(filters.command("defaultstopwords") & admin_filter)
async def default_stopwords(client, message):
    global ACTIVE_STOPWORDS
    ACTIVE_STOPWORDS = DEFAULT_STOPWORDS.copy()
    await update_bot_settings("custom_stopwords", ACTIVE_STOPWORDS)
    await message.reply_text("✅ **Stopwords have been successfully reset to the repository default list.**")

# ============================================================
# ⚡ 10-LAYER TITANIUM UPLOAD ENGINE (FOR PERMANENT IMAGES)
# ============================================================
def _upload_sync(file_bytes):
    headers = {"User-Agent": "Mozilla/5.0"}
    try: res = requests.post("https://catbox.moe/user/api.php", data={"reqtype": "fileupload"}, files={"fileToUpload": ("img.jpg", file_bytes, "image/jpeg")}, timeout=6)
    except: res = None
    if res and res.status_code == 200 and res.text.startswith("http"): return res.text.strip()
    
    try: res = requests.post("https://graph.org/upload", files={"file": ("img.jpg", file_bytes, "image/jpeg")}, timeout=6)
    except: res = None
    if res and res.status_code == 200: return "https://graph.org" + res.json()[0]["src"]
        
    try: res = requests.post("https://envs.sh", files={"file": ("img.jpg", file_bytes, "image/jpeg")}, headers=headers, timeout=6)
    except: res = None
    if res and res.status_code == 200 and res.text.startswith("http"): return res.text.strip()
        
    try: res = requests.post("https://x0.at", files={"file": ("img.jpg", file_bytes, "image/jpeg")}, headers=headers, timeout=6)
    except: res = None
    if res and res.status_code == 200 and res.text.startswith("http"): return res.text.strip()
        
    try: res = requests.post("https://ttm.sh", files={"file": ("img.jpg", file_bytes, "image/jpeg")}, headers=headers, timeout=6)
    except: res = None
    if res and res.status_code == 200 and res.text.startswith("http"): return res.text.strip()
        
    try: res = requests.post("https://0x0.st", files={"file": ("img.jpg", file_bytes, "image/jpeg")}, headers=headers, timeout=6)
    except: res = None
    if res and res.status_code == 200 and res.text.startswith("http"): return res.text.strip()
        
    try: res = requests.post("https://pixeldrain.com/api/file", files={"file": ("img.jpg", file_bytes, "image/jpeg")}, headers=headers, timeout=6)
    except: res = None
    if res and res.status_code in [200, 201] and res.json().get("success"): return "https://pixeldrain.com/api/file/" + res.json()["id"]
        
    try: res = requests.post("https://file.io", files={"file": ("img.jpg", file_bytes, "image/jpeg")}, headers=headers, timeout=6)
    except: res = None
    if res and res.status_code == 200 and res.json().get("success"): return res.json()["link"]
        
    try: res = requests.post("https://telegra.ph/upload", files={"file": ("img.jpg", file_bytes, "image/jpeg")}, timeout=6)
    except: res = None
    if res and res.status_code == 200: return "https://telegra.ph" + res.json()[0]["src"]

    return None

async def upload_image_safely(client: Client, message: Message):
    try:
        file_io = await client.download_media(message, in_memory=True)
        if not file_io: return None, "❌ Failed to download the image."
        url = await asyncio.to_thread(_upload_sync, file_io.getvalue())
        if not url: return None, "❌ All 10 cloud uploaders failed."
        return url, None
    except Exception as e: return None, f"❌ Internal Error: {e}"

# ============================================================
# 🖼️ GLOBAL IMAGE SETTINGS (WITH CLOUD UPLOAD & FALLBACK)
# ============================================================
async def process_image_setting(client, message, setting_key, success_msg):
    if not message.reply_to_message or not message.reply_to_message.photo:
        return await message.reply_text("⚠️ **Usage:** Reply to a photo.")
    
    status = await message.reply_text("⏳ Uploading to Cloud (Testing 10 Hosters)...")
    url, err = await upload_image_safely(client, message.reply_to_message)
    
    if url:
        await update_bot_settings(setting_key, url)
        await status.edit_text(f"✅ **{success_msg}**\n*(Saved permanently to cloud)*")
    else:
        file_id = message.reply_to_message.photo.file_id
        await update_bot_settings(setting_key, file_id)
        await status.edit_text(f"⚠️ Cloud blocked. **{success_msg}**\n*(Saved as Telegram File_ID)*")

@Client.on_message(filters.command("setfsubimg") & admin_filter)
async def set_fsub_img(client, message):
    await process_image_setting(client, message, "fsub_img", "Force Subscribe Image updated!")

@Client.on_message(filters.command("setautoimg") & admin_filter)
async def set_auto_img(client, message):
    await process_image_setting(client, message, "auto_img", "Default Auto-Filter Image updated!")

@Client.on_message(filters.command("remautoimg") & admin_filter)
async def rem_auto_img(client, message):
    await update_bot_settings("auto_img", None)
    await message.reply_text("🗑️ **Default Auto-Filter Image removed.**")

@Client.on_message(filters.command("setfilenotfoundimg") & admin_filter)
async def set_fnf_img(client, message):
    await process_image_setting(client, message, "not_found_img", "File Not Found Image updated!")

@Client.on_message(filters.command("remfilenotfoundimg") & admin_filter)
async def rem_fnf_img(client, message):
    await update_bot_settings("not_found_img", None)
    await message.reply_text("🗑️ **File Not Found Image removed.**")

@Client.on_message(filters.command("defaultfilenotfoundimg") & admin_filter)
async def default_fnf_img(client, message):
    await update_bot_settings("not_found_img", getattr(info, "NOT_FOUND_IMG", None))
    await message.reply_text("✅ **File Not Found Image reset to default.**")

# ============================================================
# 📝 GLOBAL TEXT SETTINGS
# ============================================================
@Client.on_message(filters.command("setnotfoundtext") & admin_filter)
async def set_fnf_text(client, message):
    if len(message.command) < 2: return await message.reply_text("⚠️ **Usage:** `/setnotfoundtext <your text>`")
    await update_bot_settings("not_found_text", message.text.split(None, 1)[1])
    await message.reply_text("✅ **File Not Found Text updated!**")

@Client.on_message(filters.command("remnotfoundtext") & admin_filter)
async def rem_fnf_text(client, message):
    await update_bot_settings("not_found_text", None)
    await message.reply_text("🗑️ **File Not Found Text removed.**")

@Client.on_message(filters.command("defaultnotfoundtext") & admin_filter)
async def def_fnf_text(client, message):
    await update_bot_settings("not_found_text", getattr(info, "NOT_FOUND_MSG", "<b>🚫 File not found.</b>"))
    await message.reply_text("✅ **File Not Found Text reset to default.**")

# ============================================================
# 🪄 SPELL CHECK (GROUP ADMINS)
# ============================================================
@Client.on_message(filters.command("enablespellcheck") & filters.group)
async def enable_spell_check(client, message):
    if not await is_group_admin(client, message): return await message.reply_text("❌ Admin only!")
    await save_group_settings(message.chat.id, "spell_check", True)
    await message.reply_text("✅ **Spell Check Enabled for this group.**")

@Client.on_message(filters.command("disablespellcheck") & filters.group)
async def disable_spell_check(client, message):
    if not await is_group_admin(client, message): return await message.reply_text("❌ Admin only!")
    await save_group_settings(message.chat.id, "spell_check", False)
    await message.reply_text("🚫 **Spell Check Disabled for this group.**")

# ============================================================
# 👋 WELCOME SETTINGS (COMMANDS)
# ============================================================
@Client.on_message(filters.command("enablewelcome") & filters.group)
async def enable_welc(client, message):
    if not await is_group_admin(client, message): return await message.reply_text("❌ Admin only!")
    await update_group_welcome(message.chat.id, "welcome", True)
    await message.reply_text("✅ **Welcome Messages Enabled for this group.**")

@Client.on_message(filters.command("disablewelcome") & filters.group)
async def disable_welc(client, message):
    if not await is_group_admin(client, message): return await message.reply_text("❌ Admin only!")
    await update_group_welcome(message.chat.id, "welcome", False)
    await message.reply_text("🚫 **Welcome Messages Disabled for this group.**")

@Client.on_message(filters.command("setwelcometxt") & filters.group)
async def set_welc_txt(client, message):
    if not await is_group_admin(client, message): return await message.reply_text("❌ Admin only!")
    if len(message.command) < 2: return await message.reply_text("⚠️ **Usage:** `/setwelcometxt <text>`\n\n💡 **Variables:**\n`{mention}` - User ping\n`{title}` - Group Name\n`{count}` - Member count")
    await update_group_welcome(message.chat.id, "text", message.text.split(None, 1)[1])
    await message.reply_text("✅ **Welcome Text updated!**")

@Client.on_message(filters.command("setwelcomeimg") & filters.group)
async def set_welc_img(client, message):
    if not await is_group_admin(client, message): return await message.reply_text("❌ Admin only!")
    if not message.reply_to_message or not message.reply_to_message.photo:
        return await message.reply_text("⚠️ **Usage:** Reply to a photo with `/setwelcomeimg`")
    
    status = await message.reply_text("⏳ Uploading to Cloud...")
    url, err = await upload_image_safely(client, message.reply_to_message)
    if url:
        await update_group_welcome(message.chat.id, "img", url)
        await status.edit_text("✅ **Welcome Image updated (Cloud Saved)!**")
    else:
        await update_group_welcome(message.chat.id, "img", message.reply_to_message.photo.file_id)
        await status.edit_text("⚠️ Cloud blocked. **Welcome Image updated (File ID Saved)!**")

@Client.on_message(filters.command("setwelcome") & filters.group)
async def set_welcome_both(client, message):
    if not await is_group_admin(client, message): return await message.reply_text("❌ Admin only!")
    if not message.reply_to_message or not message.reply_to_message.photo:
        return await message.reply_text("⚠️ **Usage:** Reply to a photo containing a caption with `/setwelcome`")

    txt = message.reply_to_message.caption
    status = await message.reply_text("⏳ Processing...")
    
    url, err = await upload_image_safely(client, message.reply_to_message)
    img_data = url if url else message.reply_to_message.photo.file_id

    await update_group_welcome(message.chat.id, "img", img_data)
    if txt: await update_group_welcome(message.chat.id, "text", txt)
    await update_group_welcome(message.chat.id, "welcome", True)
    
    await status.edit_text("✅ **Welcome Image & Text set, and Welcome Engine enabled!**")

@Client.on_message(filters.command("delwelcome") & filters.group)
async def del_welcome(client, message):
    if not await is_group_admin(client, message): return await message.reply_text("❌ Admin only!")
    await update_group_welcome(message.chat.id, "img", None)
    await update_group_welcome(message.chat.id, "text", None)
    await update_group_welcome(message.chat.id, "welcome", False)
    await message.reply_text("🗑️ **Welcome settings deleted and disabled.**")
