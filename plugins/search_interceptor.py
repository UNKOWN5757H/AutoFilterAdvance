import re
from logging import ERROR, getLogger

from pyrogram import Client, StopPropagation, filters
from pyrogram.types import Message

logger = getLogger(__name__)
logger.setLevel(ERROR)


# ============================================================
# 🚨 CLEAN DEEP-LINK SEARCH INTERCEPTOR
# ============================================================
# Note: No admin_filter here! All users must be able to click
# the channel buttons and get their files.
@Client.on_message(filters.command("start") & filters.private, group=-99)
async def intercept_direct_search(client: Client, message: Message):
    if len(message.command) > 1 and message.command[1].startswith("search_"):

        # 1. Extract the query: "search_Khalifa__The_Ruler_2026" -> "Khalifa__The_Ruler_2026"
        raw_query = message.command[1].replace("search_", "")

        # 2. Convert underscores back to spaces: "Khalifa  The Ruler 2026"
        query = re.sub(r"_+", " ", raw_query).strip()

        try:
            # 3. Connects directly to pm_filter.py to execute the search logic
            from plugins.pm_filter import auto_filter

            # Pretend the user typed the movie name manually
            message.text = query

            # Trigger the auto filter search
            await auto_filter(client, message)

        except Exception as e:
            logger.error(f"Failed to intercept search: {e}")
            await message.reply_text(
                f"🔍 **Search Query:** `{query}`\n\nTap the text above to copy it, then send it to me to search!"
            )

        # 4. Stop the default /start message from sending since we already sent the files
        raise StopPropagation
