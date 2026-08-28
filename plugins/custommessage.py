from logging import getLogger, ERROR

from pyrogram import Client, filters
from pyrogram.types import Message

import info

logger = getLogger(__name__)
logger.setLevel(ERROR)

# ============================================================
# ⚙️ Initialize Runtime States for Custom Messages & Images
# ============================================================
configs = [
    "INFO_MSG",
    "INFO_IMG",
    "DEL_MSG",
    "DEL_IMG",
    "NOT_FOUND_MSG",
    "NOT_FOUND_IMG",
    "FSUB_MSG",
    "FSUB_IMG",
]

for conf in configs:
    if not hasattr(info, conf):
        setattr(info, conf, None)


async def process_text_setting(message: Message, var_name: str, setting_name: str):
    """Helper to process message extraction for custom texts."""
    if len(message.command) > 1 and message.command[1].lower() == "off":
        setattr(info, var_name, None)
        return await message.reply_text(
            f"✅ **{setting_name} has been REMOVED.**\nSystem will use the default message."
        )

    if not message.reply_to_message:
        return await message.reply_text(
            f"⚙️ **Usage:**\nReply to a text message with `/{message.command[0]}` to set it, or use `/{message.command[0]} off` to disable."
        )

    replied = message.reply_to_message
    raw_text = None
    if replied.text:
        raw_text = replied.text.markdown
    elif replied.caption:
        raw_text = replied.caption.markdown

    if not raw_text:
        return await message.reply_text(
            "❌ **No text found!** Please reply to a message containing text."
        )

    setattr(info, var_name, raw_text)
    await message.reply_text(
        f"✅ **{setting_name} successfully updated!**\n\n**New Message:**\n{raw_text}",
        disable_web_page_preview=True,
    )


async def process_image_setting(message: Message, var_name: str, setting_name: str):
    """Helper to process image extraction for custom images."""
    if len(message.command) > 1 and message.command[1].lower() == "off":
        setattr(info, var_name, None)
        return await message.reply_text(
            f"✅ **{setting_name} has been REMOVED.**\nSystem will use the default image."
        )

    if not message.reply_to_message:
        return await message.reply_text(
            f"⚙️ **Usage:**\nReply to a photo with `/{message.command[0]}` to set it, or use `/{message.command[0]} off` to disable."
        )

    replied = message.reply_to_message
    if not replied.photo:
        return await message.reply_text(
            "❌ **No photo found!** Please reply to a valid image/photo."
        )

    photo_id = replied.photo.file_id
    setattr(info, var_name, photo_id)

    await message.reply_photo(
        photo=photo_id,
        caption=f"✅ **{setting_name} successfully updated to this image!**",
    )


@Client.on_message(filters.command("infomsg") & filters.user(info.ADMINS))
async def set_info_msg(bot: Client, message: Message):
    await process_text_setting(message, "INFO_MSG", "Info Message")

@Client.on_message(filters.command("infoimg") & filters.user(info.ADMINS))
async def set_info_img(bot: Client, message: Message):
    await process_image_setting(message, "INFO_IMG", "Info Image")

@Client.on_message(filters.command("delmsg") & filters.user(info.ADMINS))
async def set_del_msg(bot: Client, message: Message):
    await process_text_setting(message, "DEL_MSG", "Delete Message")

@Client.on_message(filters.command("delimg") & filters.user(info.ADMINS))
async def set_del_img(bot: Client, message: Message):
    await process_image_setting(message, "DEL_IMG", "Delete Image")

@Client.on_message(filters.command("notfoundmsg") & filters.user(info.ADMINS))
async def set_notfound_msg(bot: Client, message: Message):
    await process_text_setting(message, "NOT_FOUND_MSG", "File Not Found Message")

@Client.on_message(filters.command("notfoundimg") & filters.user(info.ADMINS))
async def set_notfound_img(bot: Client, message: Message):
    await process_image_setting(message, "NOT_FOUND_IMG", "File Not Found Image")

@Client.on_message(filters.command("fsubmsg") & filters.user(info.ADMINS))
async def set_fsub_msg(bot: Client, message: Message):
    await process_text_setting(message, "FSUB_MSG", "Force Subscribe Message")

@Client.on_message(filters.command("fsubimg") & filters.user(info.ADMINS))
async def set_fsub_img(bot: Client, message: Message):
    await process_image_setting(message, "FSUB_IMG", "Force Subscribe Image")
