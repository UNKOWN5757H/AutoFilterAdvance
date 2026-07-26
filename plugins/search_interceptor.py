import logging

from pyrogram import Client, filters
from pyrogram.types import Message

logger = logging.getLogger(__name__)


# We use group=-1 so this runs BEFORE the default /start command in plugins/commands.py
@Client.on_message(filters.command("start") & filters.private, group=-1)
async def intercept_direct_search(client: Client, message: Message):
    # Check if the start command contains our custom 'search-' payload
    if len(message.command) > 1 and message.command[1].startswith("search_"):

        # 1. Extract the movie name from the payload (e.g., "The-Dark-Knight-2008" -> "The Dark Knight 2008")
        query = message.command[1].replace("search_", "").replace("_", " ")

        # 2. Trick the bot into thinking the user just typed the movie name normally
        message.text = query

        try:
            # 3. Import your bot's existing auto-filter function
            from plugins.pm_filter import auto_filter

            # 4. Trigger the filter search manually!
            await auto_filter(client, message)

        except Exception as e:
            logger.error(f"Failed to intercept search: {e}")
            # Fallback just in case the import fails
            await message.reply_text(
                f"🔍 **Search Query:** `{query}`\n\nTap the text above to copy it, then send it to me to search!"
            )

        # 5. Stop the default /start command from running so it doesn't show "No such file exist"
        message.stop_propagation()
