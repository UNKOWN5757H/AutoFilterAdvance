import asyncio
import requests
from logging import ERROR, getLogger
from motor.motor_asyncio import AsyncIOMotorClient

from pyrogram import Client, filters
from pyrogram.types import Message
import info

logger = getLogger(__name__)
logger.setLevel(ERROR)

# ============================================================
# ⚙️ MONGODB PERMANENT SETTINGS
# ============================================================
_custom_db = None
try:
    _DB_CLIENT = AsyncIOMotorClient(info.DATABASE_URI)
    _BOT_DB = _DB_CLIENT[info.DATABASE_NAME]
    _custom_db = _BOT_DB["custom_captions"]
except Exception as e:
    logger.error(f"Failed to init custommessage DB: {e}")

async def save_msg_data(key: str, value: str):
    setattr(info, key, value)
    if _custom_db is not None:
        await _custom_db.update_one({"_id": "settings"}, {"$set": {key: value}}, upsert=True)

def get_admin_list():
    raw_admins = getattr(info, "ADMINS", [])
    if isinstance(raw_admins, str): return [int(x) for x in raw_admins.replace(",", " ").split() if x.strip().lstrip("-").isdigit()]
    elif isinstance(raw_admins, int): return [raw_admins]
    elif isinstance(raw_admins, list): return [int(x) for x in raw_admins if str(x).strip().lstrip("-").isdigit()]
    return []

admin_filter = filters.create(lambda _, __, msg: bool(msg.from_user and msg.from_user.id in get_admin_list()))

def _upload_sync(file_bytes):
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        res = requests.post("https://catbox.moe/user/api.php", data={"reqtype": "fileupload"}, files={"fileToUpload": ("img.jpg", file_bytes, "image/jpeg")}, timeout=6)
        if res.status_code == 200 and res.text.startswith("http"): return res.text.strip()
    except Exception: pass
    try:
        res = requests.post("https://graph.org/upload", files={"file": ("img.jpg", file_bytes, "image/jpeg")}, timeout=6)
        if res.status_code == 200: return "https://graph.org" + res.json()[0]["src"]
    except Exception: pass
    return None

async def upload_image_safely(client: Client, message: Message):
    try:
        file_io = await client.download_media(message, in_memory=True)
        if not file_io: return None
        return await asyncio.to_thread(_upload_sync, file_io.getvalue())
    except Exception: return None

async def process_text_setting(message: Message, var_name: str, setting_name: str):
    if len(message.command) > 1 and message.command[1].lower() == "off":
        await save_msg_data(var_name, None)
        return await message.reply_text(f"✅ **{setting_name} has been REMOVED.**\nSystem will use the default message.")

    if not message.reply_to_message:
        return await message.reply_text(f"⚙️ **Usage:**\nReply to a text message with `/{message.command[0]}` to set it, or use `/{message.command[0]} off` to disable.")

    replied = message.reply_to_message
    raw_text = replied.text.markdown if replied.text else (replied.caption.markdown if replied.caption else None)
    if not raw_text:
        return await message.reply_text("❌ **No text found!** Please reply to a message containing text.")

    await save_msg_data(var_name, raw_text)
    await message.reply_text(f"✅ **{setting_name} successfully updated!**\n\n**New Message:**\n{raw_text}", disable_web_page_preview=True)

async def process_image_setting(client: Client, message: Message, var_name: str, setting_name: str):
    if len(message.command) > 1 and message.command[1].lower() == "off":
        await save_msg_data(var_name, None)
        return await message.reply_text(f"✅ **{setting_name} has been REMOVED.**\nSystem will use the default image.")

    if not message.reply_to_message or not message.reply_to_message.photo:
        return await message.reply_text(f"⚙️ **Usage:**\nReply to a photo with `/{message.command[0]}` to set it, or use `/{message.command[0]} off` to disable.")

    status = await message.reply_text("⏳ **Uploading to Cloud...**")
    url = await upload_image_safely(client, message.reply_to_message)
    if url:
        await save_msg_data(var_name, url)
        await status.edit_text(f"✅ **{setting_name} updated to Cloud Image!**")
    else:
        photo_id = message.reply_to_message.photo.file_id
        await save_msg_data(var_name, photo_id)
        await status.edit_text(f"⚠️ Cloud upload failed. **{setting_name} saved as Telegram File ID!**")

@Client.on_message(filters.command("infomsg") & admin_filter)
async def set_info_msg(bot: Client, message: Message): await process_text_setting(message, "INFO_MSG", "Info Message")

@Client.on_message(filters.command("infoimg") & admin_filter)
async def set_info_img(bot: Client, message: Message): await process_image_setting(bot, message, "INFO_IMG", "Info Image")

@Client.on_message(filters.command("delmsg") & admin_filter)
async def set_del_msg(bot: Client, message: Message): await process_text_setting(message, "DEL_MSG", "Delete Message")

@Client.on_message(filters.command("delimg") & admin_filter)
async def set_del_img(bot: Client, message: Message): await process_image_setting(bot, message, "DEL_IMG", "Delete Image")

@Client.on_message(filters.command("notfoundmsg") & admin_filter)
async def set_notfound_msg(bot: Client, message: Message): await process_text_setting(message, "NOT_FOUND_MSG", "File Not Found Message")

@Client.on_message(filters.command("notfoundimg") & admin_filter)
async def set_notfound_img(bot: Client, message: Message): await process_image_setting(bot, message, "NOT_FOUND_IMG", "File Not Found Image")

@Client.on_message(filters.command("fsubmsg") & admin_filter)
async def set_fsub_msg(bot: Client, message: Message): await process_text_setting(message, "FSUB_MSG", "Force Subscribe Message")

@Client.on_message(filters.command("fsubimg") & admin_filter)
async def set_fsub_img(bot: Client, message: Message): await process_image_setting(bot, message, "FSUB_IMG", "Force Subscribe Image")
