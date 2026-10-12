import asyncio
from logging import ERROR, getLogger

import requests
from motor.motor_asyncio import AsyncIOMotorClient
from pyrogram import Client, enums, filters
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
# 👑 FULL POWER ADMIN CHECKER (GLOBAL + CHAT + ANONYMOUS)
# ============================================================
def get_admin_list():
    raw_admins = getattr(info, "ADMINS", [])
    if isinstance(raw_admins, (str, int)):
        raw_admins = str(raw_admins).replace(",", " ").split()
    return [int(x) for x in raw_admins if str(x).strip().lstrip("-").isdigit()]


async def is_user_admin(client: Client, message: Message):
    admin_list = get_admin_list()

    # 1. Global Admin Check (Direct User)
    if message.from_user and message.from_user.id in admin_list:
        return True

    # 2. Global Admin Check (Anonymous/Channel sending as Chat)
    if message.sender_chat and message.sender_chat.id in admin_list:
        return True

    # 3. Group Admin Check (Normal & Anonymous Admins)
    if message.chat and message.chat.type in [
        enums.ChatType.GROUP,
        enums.ChatType.SUPERGROUP,
    ]:
        # If the sender is the group itself, it's a Group Anonymous Admin
        if message.sender_chat and message.sender_chat.id == message.chat.id:
            return True

        # If it's a Normal Admin in this group
        if message.from_user:
            try:
                member = await client.get_chat_member(
                    message.chat.id, message.from_user.id
                )
                return member.status in [
                    enums.ChatMemberStatus.ADMINISTRATOR,
                    enums.ChatMemberStatus.OWNER,
                ]
            except Exception:
                pass

    return False


async def admin_check(_, client: Client, message: Message):
    return await is_user_admin(client, message)


admin_filter = filters.create(admin_check)


# ============================================================
# ⚡ 10-LAYER TITANIUM UPLOAD ENGINE (ZERO-FAIL)
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
            "https://pixeldrain.com/api/file",
            {"file": ("img.jpg", file_bytes, "image/jpeg")},
            None,
        ),
        ("https://file.io", {"file": ("img.jpg", file_bytes, "image/jpeg")}, None),
        (
            "https://telegra.ph/upload",
            {"file": ("img.jpg", file_bytes, "image/jpeg")},
            None,
        ),
    ]:
        try:
            res = requests.post(
                url, data=data_dict, files=files_dict, headers=headers, timeout=6
            )
            if res.status_code in [200, 201]:
                if url in ["https://graph.org/upload", "https://telegra.ph/upload"]:
                    return url.rsplit("/", 1)[0] + res.json()[0]["src"]
                elif "pixeldrain" in url and res.json().get("success"):
                    return "https://pixeldrain.com/api/file/" + res.json()["id"]
                elif "file.io" in url and res.json().get("success"):
                    return res.json()["link"]
                elif res.text.startswith("http"):
                    return res.text.strip()
        except Exception:
            continue
    return None


async def upload_image_safely(client: Client, message: Message):
    try:
        file_io = await client.download_media(message, in_memory=True)
        if not file_io:
            return None
        return await asyncio.to_thread(_upload_sync, file_io.getvalue())
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
