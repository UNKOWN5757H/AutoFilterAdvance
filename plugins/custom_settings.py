import asyncio
from logging import getLogger, ERROR

from pyrogram import Client, enums, filters
from pyrogram.types import Message
from motor.motor_asyncio import AsyncIOMotorClient

import info
from utils import get_settings, save_group_settings

logger = getLogger(__name__)
logger.setLevel(ERROR)

# ⚡ Safely alias DB to prevent Pyrogram scanner crash
_DB_CLIENT = AsyncIOMotorClient(info.DATABASE_URI)
_BOT_DB = _DB_CLIENT[info.DATABASE_NAME]

_b_settings = _BOT_DB["global_bot_settings"]
_g_settings = _BOT_DB["group_welcome_settings"]

# ==========================================
# 🛑 DEFAULT STOPWORDS LIST
# ==========================================
DEFAULT_STOPWORDS = [
    "send", "snd", "give", "gib", "pls", "plz", "please", "need", "want", "upload",
    "uplod", "drop", "share", "find", "search", "provide", "post", "movie", "movies",
    "film", "films", "cinema", "cinemas", "full", "fullmovie", "download", "downlod",
    "link", "links", "file", "files", "print", "audio", "video", "ott", "hd", "hq",
    "bluray", "rip", "watch", "online", "bro", "bhai", "anna", "boss", "admin", "sir",
    "madam", "brodie", "macha", "machha", "guru", "chinnu", "beku",
    "bekithu", "bekittu", "bekagide", "kodi", "kodro", "kalsi", "kalsro", "kalisi",
    "haki", "haku", "hakro", "ideya", "irboda", "bidi", "madu", "yaradru", "chitra",
    "chithra", "chalanachitra", "chalanachithra", "kannadadalli", "sandalwood",
    "kr_picture", "kannada_filmy_group", "telegram"
]

_stopwords_loaded = False

# ==========================================
# 🚀 STARTUP DB INJECTION (Deferred Import)
# ==========================================
@Client.on_message(group=-999)
async def load_stopwords_on_boot(client, message):
    global _stopwords_loaded
    if not _stopwords_loaded:
        from plugins import pm_filter # ⚡ Local Import fixes circular crash
        settings = await get_bot_settings()
        custom_stops = settings.get("custom_stopwords")
        if custom_stops is not None:
            pm_filter.STOPWORDS = custom_stops
        else:
            pm_filter.STOPWORDS = DEFAULT_STOPWORDS.copy()
        _stopwords_loaded = True

# ==========================================
# 🗄️ DATABASE HELPERS
# ==========================================
async def get_bot_settings():
    doc = await _b_settings.find_one({"_id": "bot_config"})
    return doc or {}

async def update_bot_settings(key, value):
    await _b_settings.update_one({"_id": "bot_config"}, {"$set": {key: value}}, upsert=True)

async def get_group_welcome(chat_id):
    doc = await _g_settings.find_one({"_id": chat_id})
    return doc or {}

async def update_group_welcome(chat_id, key, value):
    await _g_settings.update_one({"_id": chat_id}, {"$set": {key: value}}, upsert=True)

async def is_group_admin(client: Client, message: Message):
    if message.from_user.id in info.ADMINS: return True
    try:
        member = await client.get_chat_member(message.chat.id, message.from_user.id)
        return member.status in [enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER]
    except Exception: return False

admin_filter = filters.create(lambda _, __, msg: msg.from_user and msg.from_user.id in info.ADMINS)

# ==========================================
# 🖼️ GLOBAL IMAGE SETTINGS (ADMIN ONLY)
# ==========================================
@Client.on_message(filters.command("setfsubimg") & admin_filter)
async def set_fsub_img(client, message):
    if not message.reply_to_message or not message.reply_to_message.photo:
        return await message.reply_text("⚠️ **Usage:** Reply to a photo with `/setfsubimg`")
    await update_bot_settings("fsub_img", message.reply_to_message.photo.file_id)
    await message.reply_text("✅ **Force Subscribe Image updated!**")

@Client.on_message(filters.command("setautoimg") & admin_filter)
async def set_auto_img(client, message):
    if not message.reply_to_message or not message.reply_to_message.photo:
        return await message.reply_text("⚠️ **Usage:** Reply to a photo with `/setautoimg`")
    await update_bot_settings("auto_img", message.reply_to_message.photo.file_id)
    await message.reply_text("✅ **Default Auto-Filter Image updated!**")

@Client.on_message(filters.command("remautoimg") & admin_filter)
async def rem_auto_img(client, message):
    await update_bot_settings("auto_img", None)
    await message.reply_text("🗑️ **Default Auto-Filter Image removed.**")

@Client.on_message(filters.command("setfilenotfoundimg") & admin_filter)
async def set_fnf_img(client, message):
    if not message.reply_to_message or not message.reply_to_message.photo:
        return await message.reply_text("⚠️ **Usage:** Reply to a photo with `/setfilenotfoundimg`")
    await update_bot_settings("not_found_img", message.reply_to_message.photo.file_id)
    await message.reply_text("✅ **File Not Found Image updated!**")

@Client.on_message(filters.command("remfilenotfoundimg") & admin_filter)
async def rem_fnf_img(client, message):
    await update_bot_settings("not_found_img", None)
    await message.reply_text("🗑️ **File Not Found Image removed.**")

@Client.on_message(filters.command("defaultfilenotfoundimg") & admin_filter)
async def default_fnf_img(client, message):
    await update_bot_settings("not_found_img", getattr(info, "NOT_FOUND_IMG", None))
    await message.reply_text("✅ **File Not Found Image reset to default.**")

# ==========================================
# 📝 GLOBAL TEXT SETTINGS (ADMIN ONLY)
# ==========================================
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
    await update_bot_settings("not_found_text", getattr(info, "NOT_FOUND_MSG", "🚫 File not found."))
    await message.reply_text("✅ **File Not Found Text reset to default.**")

# ==========================================
# 🛑 DYNAMIC STOPWORDS DB INJECTION
# ==========================================
@Client.on_message(filters.command("addstopwords") & admin_filter)
async def add_stopwords(client, message):
    from plugins import pm_filter # ⚡ Local Import
    if len(message.command) < 2: return await message.reply_text("⚠️ **Usage:** `/addstopwords word1, word2`")
    new_words = [w.strip().lower() for w in message.text.split(None, 1)[1].split(",")]
    
    current_words = pm_filter.STOPWORDS.copy()
    updated_words = list(set(current_words + new_words))
    
    pm_filter.STOPWORDS = updated_words
    await update_bot_settings("custom_stopwords", updated_words)
    await message.reply_text(f"✅ **Added {len(new_words)} stopwords.**\nTotal Active Stopwords: `{len(updated_words)}`")

@Client.on_message(filters.command("stopwords") & admin_filter)
async def show_stopwords(client, message):
    from plugins import pm_filter # ⚡ Local Import
    current_words = pm_filter.STOPWORDS
    
    if not current_words:
        return await message.reply_text("ℹ️ **No stopwords are currently active.**")
    
    words_str = ", ".join(current_words)
    await message.reply_text(f"🛑 **Current Active Stopwords:**\n\n`{words_str}`\n\n**Total:** `{len(current_words)}`")

@Client.on_message(filters.command("remstopwords") & admin_filter)
async def rem_stopwords(client, message):
    from plugins import pm_filter # ⚡ Local Import
    if len(message.command) < 2:
        return await message.reply_text("⚠️ **Usage:** `/remstopwords word1, word2`")
    
    words_to_remove = [w.strip().lower() for w in message.text.split(None, 1)[1].split(",")]
    current_words = pm_filter.STOPWORDS.copy()
    
    if not current_words:
        return await message.reply_text("ℹ️ **There are no stopwords to remove.**")
    
    updated_words = [w for w in current_words if w not in words_to_remove]
    removed_count = len(current_words) - len(updated_words)
    
    pm_filter.STOPWORDS = updated_words
    await update_bot_settings("custom_stopwords", updated_words)
    await message.reply_text(f"✅ **Removed {removed_count} stopwords.**\nTotal Stopwords left: `{len(updated_words)}`")

@Client.on_message(filters.command("remallstopwords") & admin_filter)
async def rem_all_stopwords(client, message):
    from plugins import pm_filter # ⚡ Local Import
    pm_filter.STOPWORDS = []
    await update_bot_settings("custom_stopwords", [])
    await message.reply_text("🗑️ **All stopwords have been completely removed.**")

@Client.on_message(filters.command("defaultstopwords") & admin_filter)
async def default_stopwords(client, message):
    from plugins import pm_filter # ⚡ Local Import
    pm_filter.STOPWORDS = DEFAULT_STOPWORDS.copy()
    await update_bot_settings("custom_stopwords", pm_filter.STOPWORDS)
    await message.reply_text("✅ **Stopwords have been successfully reset to the repository default list.**")

# ==========================================
# 🪄 SPELL CHECK (GROUP ADMINS)
# ==========================================
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

# ==========================================
# 👋 WELCOME SETTINGS (GROUP ADMINS)
# ==========================================
@Client.on_message(filters.command("enablewelcome") & filters.group)
async def enable_welc(client, message):
    if not await is_group_admin(client, message): return await message.reply_text("❌ Admin only!")
    await save_group_settings(message.chat.id, "welcome", True)
    await message.reply_text("✅ **Welcome Messages Enabled for this group.**")

@Client.on_message(filters.command("disablewelcome") & filters.group)
async def disable_welc(client, message):
    if not await is_group_admin(client, message): return await message.reply_text("❌ Admin only!")
    await save_group_settings(message.chat.id, "welcome", False)
    await message.reply_text("🚫 **Welcome Messages Disabled for this group.**")

@Client.on_message(filters.command("setwelcometxt") & filters.group)
async def set_welc_txt(client, message):
    if not await is_group_admin(client, message): return await message.reply_text("❌ Admin only!")
    if len(message.command) < 2: 
        return await message.reply_text("⚠️ **Usage:** `/setwelcometxt <text>`\n\n💡 **Supports Formatting:**\n`**Bold**`, `__Italic__`, `~~Strike~~`, `> Quote`, `||Spoiler||`\n\n💡 **Variables:**\n`{mention}` - User ping\n`{title}` - Group Name\n`{count}` - Member count")
    await update_group_welcome(message.chat.id, "text", message.text.split(None, 1)[1])
    await message.reply_text("✅ **Welcome Text updated!**")

@Client.on_message(filters.command("setwelcomeimg") & filters.group)
async def set_welc_img(client, message):
    if not await is_group_admin(client, message): return await message.reply_text("❌ Admin only!")
    if not message.reply_to_message or not message.reply_to_message.photo:
        return await message.reply_text("⚠️ **Usage:** Reply to a photo with `/setwelcomeimg`")
    await update_group_welcome(message.chat.id, "img", message.reply_to_message.photo.file_id)
    await message.reply_text("✅ **Welcome Image updated!**")

@Client.on_message(filters.command("setwelcome") & filters.group)
async def set_welcome_both(client, message):
    if not await is_group_admin(client, message): return await message.reply_text("❌ Admin only!")
    if not message.reply_to_message or not message.reply_to_message.photo:
        return await message.reply_text("⚠️ **Usage:** Reply to a photo containing a caption with `/setwelcome` to set both image and text at once.")
    
    img = message.reply_to_message.photo.file_id
    txt = message.reply_to_message.caption
    
    await update_group_welcome(message.chat.id, "img", img)
    if txt: await update_group_welcome(message.chat.id, "text", txt)
    await save_group_settings(message.chat.id, "welcome", True)
    await message.reply_text("✅ **Welcome Image & Text set, and Welcome enabled!**")

@Client.on_message(filters.command("delwelcome") & filters.group)
async def del_welcome(client, message):
    if not await is_group_admin(client, message): return await message.reply_text("❌ Admin only!")
    await update_group_welcome(message.chat.id, "img", None)
    await update_group_welcome(message.chat.id, "text", None)
    await save_group_settings(message.chat.id, "welcome", False)
    await message.reply_text("🗑️ **Welcome settings deleted and disabled.**")
