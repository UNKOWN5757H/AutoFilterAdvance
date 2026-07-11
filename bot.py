import asyncio
import logging
import logging.config
import os
from typing import AsyncGenerator, Optional, Union

from pyrogram import Client, __version__, filters, types
from pyrogram.raw.all import layer
from pyrogram.types import Message

from database.ia_filterdb import Media
from database.users_chats_db import db
from info import API_HASH, API_ID, BOT_TOKEN, LOG_STR, SESSION
from utils import temp

# ============================================================
# ⚙️ SAFE LOGGING SETUP
# ============================================================
if os.path.exists("logging.conf"):
    logging.config.fileConfig("logging.conf")
else:
    # FIXED: Fallback to prevent instant crashes if the file is missing
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s - %(levelname)s] - %(name)s - %(message)s",
        datefmt="%d-%b-%y %H:%M:%S",
    )

logging.getLogger("pyrogram").setLevel(logging.ERROR)
logging.getLogger("imdbpy").setLevel(logging.ERROR)
logger = logging.getLogger(__name__)


# ============================================================
# 🤖 BOT CLASS
# ============================================================
class Bot(Client):
    def __init__(self):
        super().__init__(
            name=SESSION,
            api_id=API_ID,
            api_hash=API_HASH,
            bot_token=BOT_TOKEN,
            workers=500,
            plugins={"root": "plugins"},
            sleep_threshold=5,
        )

    async def start(self):
        b_users, b_chats = await db.get_banned()
        temp.BANNED_USERS = b_users
        temp.BANNED_CHATS = b_chats
        
        await super().start()
        
        # Ensure MongoDB indexes for the umongo Media collection
        await Media.ensure_indexes()
        
        me = await self.get_me()
        temp.ME = me.id
        temp.U_NAME = me.username
        temp.B_NAME = me.first_name
        self.username = f"@{me.username}"
        
        logger.info(f"{me.first_name} with Pyrogram v{__version__} (Layer {layer}) started on {me.username}.")
        logger.info(LOG_STR)

    async def stop(self, *args):
        await super().stop()
        logger.info("Bot stopped. Bye.")

    async def iter_messages(
        self,
        chat_id: Union[int, str],
        limit: int,
        offset: int = 0,
    ) -> AsyncGenerator[types.Message, None]:
        """
        Iterate through a chat sequentially by message IDs.
        Useful for getting whole chat messages with a single call.
        """
        current = offset
        while True:
            new_diff = min(200, limit - current)
            if new_diff <= 0:
                return
                
            messages = await self.get_messages(
                chat_id, list(range(current, current + new_diff + 1))
            )
            
            for message in messages:
                yield message
                current += 1


# Instantiating the app here so root-level handlers can bind to it
app = Bot()


# ============================================================
# 🗑️ AUTO DELETE PM MEDIA
# ============================================================
# FIXED: Replaced @Client with @app to ensure this registers properly outside of plugins/
@app.on_message(filters.private & ~filters.service)
async def auto_delete_user_media_pm(client: Client, message: Message):
    user = message.from_user
    if not user or message.outgoing:
        return

    # FIXED: Cleaner, safer check without building unneeded lists in memory
    if (
        message.document
        or message.video
        or message.audio
        or message.voice
        or message.photo
        or message.video_note
    ):
        await asyncio.sleep(14400)  # Wait 4 hours
        try:
            await message.delete()
        except Exception as e:
            logger.error(f"Failed to auto-delete PM media for {user.id}: {e}")


if __name__ == "__main__":
    app.run()
