import logging
from pyrogram import Client, StopPropagation, filters
from pyrogram.types import Message

logger = logging.getLogger(__name__)

@Client.on_message(filters.command("start") & filters.private, group=-99)
async def intercept_direct_search(client: Client, message: Message):
    if len(message.command) > 1 and message.command[1].startswith("search_"):
        query = message.command[1].replace("search_", "").replace("_", " ")
        try:
            from plugins.pm_filter import auto_filter
            message.text = query
            await auto_filter(client, message)
        except Exception as e:
            logger.error(f"Search intercept failed: {e}")
            await message.reply_text(f"🔍 **Search Query:** `{query}`\n\nTap the text above to copy it, then send it to me to search!")
        
        # Stop the standard /start command from running so it doesn't say "File not found"
        raise StopPropagation
