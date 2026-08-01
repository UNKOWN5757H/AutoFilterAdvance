import logging
from pyrogram import Client, filters
from pyrogram.types import Message
import info

logger = logging.getLogger(__name__)

if not hasattr(info, "CUSTOM_FILE_CAPTION"): info.CUSTOM_FILE_CAPTION = None
if not hasattr(info, "CAPTION_PLUS"): info.CAPTION_PLUS = None

@Client.on_message(filters.command("customcaption") & filters.user(info.ADMINS))
async def set_custom_caption(bot: Client, message: Message):
    if len(message.command) > 1 and message.command[1].lower() == "off":
        info.CUSTOM_FILE_CAPTION = None
        return await message.reply_text("✅ **Custom File Caption has been DISABLED.**")

    if not message.reply_to_message:
        return await message.reply_text("⚙️ **Usage:**\nReply to a text message with `/customcaption`.")

    raw_text = message.reply_to_message.text.markdown if message.reply_to_message.text else (message.reply_to_message.caption.markdown if message.reply_to_message.caption else None)
    if not raw_text: return await message.reply_text("❌ **No text found.**")

    info.CUSTOM_FILE_CAPTION = raw_text
    await message.reply_text(f"✅ **Custom Caption updated!**\n\n{raw_text}", disable_web_page_preview=True)

@Client.on_message(filters.command("captionplus") & filters.user(info.ADMINS))
async def set_caption_plus(bot: Client, message: Message):
    if len(message.command) > 1 and message.command[1].lower() == "off":
        info.CAPTION_PLUS = None
        return await message.reply_text("✅ **Caption Plus has been DISABLED.**")

    if not message.reply_to_message:
        return await message.reply_text("⚙️ **Usage:**\nReply to a text message with `/captionplus`.")

    raw_text = message.reply_to_message.text.markdown if message.reply_to_message.text else (message.reply_to_message.caption.markdown if message.reply_to_message.caption else None)
    if not raw_text: return await message.reply_text("❌ **No text found.**")

    info.CAPTION_PLUS = raw_text
    await message.reply_text(f"✅ **Caption Plus updated!**\n\n{raw_text}", disable_web_page_preview=True)
