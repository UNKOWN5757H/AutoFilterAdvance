import asyncio
from logging import ERROR, getLogger

import requests
from motor.motor_asyncio import AsyncIOMotorClient
from pyrogram import Client, filters
from pyrogram.types import Message

import info

logger = getLogger(__name__)
logger.setLevel(ERROR)

# ============================================================
# ⚙️ MONGODB PERMANENT STORAGE ENGINE
# ============================================================
_caption_db = None
try:
    _DB_CLIENT = AsyncIOMotorClient(info.DATABASE_URI)
    _BOT_DB = _DB_CLIENT[info.DATABASE_NAME]
    _caption_db = _BOT_DB["custom_captions"]
except Exception as e:
    logger.error(f"Failed to init Caption DB: {e}")


async def save_custom_data(key: str, value: str):
    if _caption_db is not None:
        await _caption_db.update_one(
            {"_id": "settings"}, {"$set": {key: value}}, upsert=True
        )
    setattr(info, key, value)  # Sync to memory for fast access


# ============================================================
# 👑 FOOLPROOF ADMIN CHECKER
# ============================================================
def get_admin_list():
    raw_admins = getattr(info, "ADMINS", [])
    if isinstance(raw_admins, str):
        return [
            int(x)
            for x in raw_admins.replace(",", " ").split()
            if x.strip().lstrip("-").isdigit()
        ]
    elif isinstance(raw_admins, int):
        return [raw_admins]
    elif isinstance(raw_admins, list):
        return [int(x) for x in raw_admins if str(x).strip().lstrip("-").isdigit()]
    return []


admin_filter = filters.create(
    lambda _, __, msg: bool(msg.from_user and msg.from_user.id in get_admin_list())
)


# ============================================================
# ⚡ 10-LAYER TITANIUM UPLOAD ENGINE (ZERO-FAIL)
# ============================================================
def _upload_sync(file_bytes):
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        res = requests.post(
            "https://catbox.moe/user/api.php",
            data={"reqtype": "fileupload"},
            files={"fileToUpload": ("img.jpg", file_bytes, "image/jpeg")},
            timeout=6,
        )
    except:
        res = None
    if res and res.status_code == 200 and res.text.startswith("http"):
        return res.text.strip()

    try:
        res = requests.post(
            "https://graph.org/upload",
            files={"file": ("img.jpg", file_bytes, "image/jpeg")},
            timeout=6,
        )
    except:
        res = None
    if res and res.status_code == 200:
        return "https://graph.org" + res.json()[0]["src"]

    try:
        res = requests.post(
            "https://envs.sh",
            files={"file": ("img.jpg", file_bytes, "image/jpeg")},
            headers=headers,
            timeout=6,
        )
    except:
        res = None
    if res and res.status_code == 200 and res.text.startswith("http"):
        return res.text.strip()

    try:
        res = requests.post(
            "https://x0.at",
            files={"file": ("img.jpg", file_bytes, "image/jpeg")},
            headers=headers,
            timeout=6,
        )
    except:
        res = None
    if res and res.status_code == 200 and res.text.startswith("http"):
        return res.text.strip()

    try:
        res = requests.post(
            "https://ttm.sh",
            files={"file": ("img.jpg", file_bytes, "image/jpeg")},
            headers=headers,
            timeout=6,
        )
    except:
        res = None
    if res and res.status_code == 200 and res.text.startswith("http"):
        return res.text.strip()

    try:
        res = requests.post(
            "https://0x0.st",
            files={"file": ("img.jpg", file_bytes, "image/jpeg")},
            headers=headers,
            timeout=6,
        )
    except:
        res = None
    if res and res.status_code == 200 and res.text.startswith("http"):
        return res.text.strip()

    try:
        res = requests.post(
            "https://pixeldrain.com/api/file",
            files={"file": ("img.jpg", file_bytes, "image/jpeg")},
            headers=headers,
            timeout=6,
        )
    except:
        res = None
    if res and res.status_code in [200, 201] and res.json().get("success"):
        return "https://pixeldrain.com/api/file/" + res.json()["id"]

    try:
        res = requests.post(
            "https://file.io",
            files={"file": ("img.jpg", file_bytes, "image/jpeg")},
            headers=headers,
            timeout=6,
        )
    except:
        res = None
    if res and res.status_code == 200 and res.json().get("success"):
        return res.json()["link"]

    try:
        res = requests.post(
            "https://telegra.ph/upload",
            files={"file": ("img.jpg", file_bytes, "image/jpeg")},
            timeout=6,
        )
    except:
        res = None
    if res and res.status_code == 200:
        return "https://telegra.ph" + res.json()[0]["src"]
    return None


async def upload_image_safely(client: Client, message: Message):
    try:
        file_io = await client.download_media(message, in_memory=True)
        if not file_io:
            return None
        url = await asyncio.to_thread(_upload_sync, file_io.getvalue())
        return url
    except Exception:
        return None


# ============================================================
# 📝 PROCESSING ENGINES
# ============================================================
async def process_text_setting(message: Message, var_name: str, setting_name: str):
    if len(message.command) > 1 and message.command[1].lower() == "off":
        await save_custom_data(var_name, None)
        return await message.reply_text(
            f"✅ **{setting_name} has been REMOVED.**\nSystem will use the default message."
        )

    if not message.reply_to_message:
        return await message.reply_text(
            f"⚙️ **Usage:**\nReply to a text message with `/{message.command[0]}` to set it, or use `/{message.command[0]} off` to disable."
        )

    raw_text = (
        message.reply_to_message.text.markdown
        if message.reply_to_message.text
        else (
            message.reply_to_message.caption.markdown
            if message.reply_to_message.caption
            else None
        )
    )

    if not raw_text:
        return await message.reply_text(
            "❌ **No text found!** Please reply to a message containing text."
        )

    await save_custom_data(var_name, raw_text)
    await message.reply_text(
        f"✅ **{setting_name} successfully updated permanently!**\n\n**New Message:**\n{raw_text}",
        disable_web_page_preview=True,
    )


async def process_image_setting(
    client: Client, message: Message, var_name: str, setting_name: str
):
    if len(message.command) > 1 and message.command[1].lower() == "off":
        await save_custom_data(var_name, None)
        return await message.reply_text(
            f"✅ **{setting_name} has been REMOVED.**\nSystem will use the default image."
        )

    if not message.reply_to_message or not message.reply_to_message.photo:
        return await message.reply_text(
            f"⚙️ **Usage:**\nReply to a photo with `/{message.command[0]}` to set it, or use `/{message.command[0]} off` to disable."
        )

    status = await message.reply_text("⏳ **Uploading to Cloud (10-Layer Engine)...**")
    url = await upload_image_safely(client, message.reply_to_message)

    if url:
        await save_custom_data(var_name, url)
        await status.edit_text(
            f"✅ **{setting_name} successfully updated to Cloud Image!**"
        )
    else:
        file_id = message.reply_to_message.photo.file_id
        await save_custom_data(var_name, file_id)
        await status.edit_text(
            f"⚠️ Cloud blocked. **{setting_name} updated using Telegram File ID!**"
        )


# ============================================================
# 🎯 COMMANDS
# ============================================================
@Client.on_message(filters.command("infomsg") & admin_filter)
async def set_info_msg(bot: Client, message: Message):
    await process_text_setting(message, "INFO_MSG", "Info Message")


@Client.on_message(filters.command("infoimg") & admin_filter)
async def set_info_img(bot: Client, message: Message):
    await process_image_setting(bot, message, "INFO_IMG", "Info Image")


@Client.on_message(filters.command("delmsg") & admin_filter)
async def set_del_msg(bot: Client, message: Message):
    await process_text_setting(message, "DEL_MSG", "Delete Message")


@Client.on_message(filters.command("delimg") & admin_filter)
async def set_del_img(bot: Client, message: Message):
    await process_image_setting(bot, message, "DEL_IMG", "Delete Image")


@Client.on_message(filters.command("notfoundmsg") & admin_filter)
async def set_notfound_msg(bot: Client, message: Message):
    await process_text_setting(message, "NOT_FOUND_MSG", "File Not Found Message")


@Client.on_message(filters.command("notfoundimg") & admin_filter)
async def set_notfound_img(bot: Client, message: Message):
    await process_image_setting(bot, message, "NOT_FOUND_IMG", "File Not Found Image")


@Client.on_message(filters.command("fsubmsg") & admin_filter)
async def set_fsub_msg(bot: Client, message: Message):
    await process_text_setting(message, "FSUB_MSG", "Force Subscribe Message")


@Client.on_message(filters.command("fsubimg") & admin_filter)
async def set_fsub_img(bot: Client, message: Message):
    await process_image_setting(bot, message, "FSUB_IMG", "Force Subscribe Image")
