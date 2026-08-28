from logging import getLogger, ERROR

from pyrogram import Client, filters
from pyrogram.types import Message

import info

logger = getLogger(__name__)
logger.setLevel(ERROR)

# ============================================================
# ⚙️ Initialize Runtime States for Captions
# ============================================================
if not hasattr(info, "CUSTOM_FILE_CAPTION"):
    info.CUSTOM_FILE_CAPTION = None

if not hasattr(info, "CAPTION_PLUS"):
    info.CAPTION_PLUS = None


# ============================================================
# 📝 1. Set Custom File Caption (/customcaption)
# ============================================================
@Client.on_message(filters.command("customcaption") & filters.user(info.ADMINS))
async def set_custom_caption(bot: Client, message: Message):
    """
    Sets or disables the global custom file caption.
    """
    if len(message.command) > 1 and message.command[1].lower() == "off":
        info.CUSTOM_FILE_CAPTION = None
        return await message.reply_text(
            "✅ **Custom File Caption has been DISABLED.**\nFiles will now use their original database captions."
        )

    if not message.reply_to_message:
        return await message.reply_text(
            "⚙️ **Usage:**\n"
            "1️⃣ Send a message with your desired caption format.\n"
            "2️⃣ Reply to that message with `/customcaption`.\n\n"
            "💡 **Available Placeholders:**\n"
            "`{file_name}` - Name of the file\n"
            "`{file_size}` - Size of the file\n"
            "`{file_caption}` - Original file caption\n\n"
            "🛑 To disable: `/customcaption off`"
        )

    replied = message.reply_to_message
    raw_text = None
    if replied.text:
        raw_text = replied.text.markdown
    elif replied.caption:
        raw_text = replied.caption.markdown

    if not raw_text:
        return await message.reply_text(
            "❌ **No text found in the replied message.** Please reply to a text message."
        )

    info.CUSTOM_FILE_CAPTION = raw_text
    await message.reply_text(
        f"✅ **Custom Caption successfully updated!**\n\n**New Format:**\n{raw_text}",
        disable_web_page_preview=True,
    )


# ============================================================
# ➕ 2. Set Additional Caption (Caption Plus) (/captionplus)
# ============================================================
@Client.on_message(filters.command("captionplus") & filters.user(info.ADMINS))
async def set_caption_plus(bot: Client, message: Message):
    """
    Sets or disables an additional caption appended to the end of files.
    """
    if len(message.command) > 1 and message.command[1].lower() == "off":
        info.CAPTION_PLUS = None
        return await message.reply_text(
            "✅ **Additional Caption (Caption Plus) has been DISABLED.**"
        )

    if not message.reply_to_message:
        return await message.reply_text(
            "⚙️ **Usage:**\n"
            "1️⃣ Send a message with your extra text/links.\n"
            "2️⃣ Reply to that message with `/captionplus`.\n\n"
            "💡 *This text will be attached to the bottom of all sent files.*\n\n"
            "🛑 To disable: `/captionplus off`"
        )

    replied = message.reply_to_message
    raw_text = None
    if replied.text:
        raw_text = replied.text.markdown
    elif replied.caption:
        raw_text = replied.caption.markdown

    if not raw_text:
        return await message.reply_text(
            "❌ **No text found in the replied message.** Please reply to a text message."
        )

    info.CAPTION_PLUS = raw_text
    await message.reply_text(
        f"✅ **Caption Plus successfully updated!**\n\n**Additional Text:**\n{raw_text}",
        disable_web_page_preview=True,
    )
