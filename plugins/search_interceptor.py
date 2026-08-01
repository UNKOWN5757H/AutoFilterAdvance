import logging

from pyrogram import Client, StopPropagation, filters
from pyrogram.types import Message

logger = logging.getLogger(__name__)


# group=-99 guarantees this runs BEFORE the standard bot /start command
@Client.on_message(filters.command("start") & filters.private, group=-99)
async def intercept_direct_search(client: Client, message: Message):
    # Check if the start command contains our custom 'search_' payload
    if len(message.command) > 1 and message.command[1].startswith("search_"):

        # Extract the movie name (e.g., "search_The_Dark_Knight" -> "The Dark Knight")
        query = message.command[1].replace("search_", "").replace("_", " ")

        try:
            # Import your bot's existing auto-filter function
            from plugins.pm_filter import auto_filter

            # Trick the bot into thinking the user just typed the movie name normally
            message.text = query

            # Trigger the filter search manually
            await auto_filter(client, message)

        except Exception as e:
            logger.error(f"Failed to intercept search: {e}")
            # Fallback if the auto_filter function fails to import
            await message.reply_text(
                f"🔍 **Search Query:** `{query}`\n\nTap the text above to copy it, then send it to me to search!"
            )

        # ⛔ CRITICAL: This completely stops the standard /start command from running
        # so it NEVER shows the "No such file exist" error!
        raise StopPropagation
