import logging

from pyrogram import Client, filters
from pyrogram.types import Message

import info

logger = logging.getLogger(__name__)

for conf in [
    "INFO_MSG",
    "INFO_IMG",
    "DEL_MSG",
    "DEL_IMG",
    "NOT_FOUND_MSG",
    "NOT_FOUND_IMG",
    "FSUB_MSG",
    "FSUB_IMG",
]:
    if not hasattr(info, conf):
        setattr(info, conf, None)


async def process_setting(message: Message, var_name: str, name: str, is_text: bool):
    if len(message.command) > 1 and message.command[1].lower() == "off":
        setattr(info, var_name, None)
        return await message.reply_text(f"✅ **{name} REMOVED.**")

    if not message.reply_to_message:
        return await message.reply_text(
            f"⚙️ **Usage:** Reply to a {'text' if is_text else 'photo'} with `/{message.command[0]}`"
        )

    replied = message.reply_to_message
    if is_text:
        text = (
            replied.text.markdown
            if replied.text
            else (replied.caption.markdown if replied.caption else None)
        )
        if not text:
            return await message.reply_text("❌ **No text found!**")
        setattr(info, var_name, text)
        await message.reply_text(
            f"✅ **{name} updated!**\n\n{text}", disable_web_page_preview=True
        )
    else:
        if not replied.photo:
            return await message.reply_text("❌ **No photo found!**")
        setattr(info, var_name, replied.photo.file_id)
        await message.reply_photo(
            photo=replied.photo.file_id, caption=f"✅ **{name} updated!**"
        )


@Client.on_message(filters.command("infomsg") & filters.user(info.ADMINS))
async def set_info_msg(bot, message):
    await process_setting(message, "INFO_MSG", "Info Message", True)


@Client.on_message(filters.command("infoimg") & filters.user(info.ADMINS))
async def set_info_img(bot, message):
    await process_setting(message, "INFO_IMG", "Info Image", False)


@Client.on_message(filters.command("delmsg") & filters.user(info.ADMINS))
async def set_del_msg(bot, message):
    await process_setting(message, "DEL_MSG", "Delete Message", True)


@Client.on_message(filters.command("delimg") & filters.user(info.ADMINS))
async def set_del_img(bot, message):
    await process_setting(message, "DEL_IMG", "Delete Image", False)
