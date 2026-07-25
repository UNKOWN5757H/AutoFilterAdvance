import asyncio
import glob
import logging
import logging.config
import os
from typing import AsyncGenerator, Union

import pyromod  # ⚡ ADDED: This injects .listen() into Pyrogram globally
from pyrogram import Client, __version__, filters, types
from pyrogram.raw.all import layer
from pyrogram.types import Message

# Import the load_known_titles function we built earlier!
from database.ia_filterdb import Media, load_known_titles
from database.users_chats_db import db
from info import API_HASH, API_ID, BOT_TOKEN, LOG_STR, SESSION
from utils import temp

# ============================================================
# ⚙️ SAFE LOGGING SETUP
# ============================================================
if os.path.exists("logging.conf"):
    logging.config.fileConfig("logging.conf")
else:
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
        # 1. Load banned users/chats into memory
        b_users, b_chats = await db.get_banned()
        temp.BANNED_USERS = b_users
        temp.BANNED_CHATS = b_chats

        await super().start()

        # ============================================================
        # 2. DATABASE INITIALIZATION & CRASH FIX
        # ============================================================
        try:
            # Force drop the old conflicting index before applying the new one
            await Media.collection.drop_index("file_name_text")
            logger.info("🗑️ Successfully dropped the old text index 'file_name_text'.")
        except Exception:
            # If the index is already deleted or doesn't exist, safely ignore
            pass

        # Now safely build the new compound index
        await Media.ensure_indexes()
        # ============================================================

        # 3. Start building the in-memory spellchecker dictionary in the background
        asyncio.create_task(load_known_titles())

        me = await self.get_me()
        temp.ME = me.id
        temp.U_NAME = me.username
        temp.B_NAME = me.first_name
        self.username = f"@{me.username}"

        logger.info(
            f"{me.first_name} with Pyrogram v{__version__} (Layer {layer}) started on {me.username}."
        )
        logger.info(LOG_STR)

        # ============================================================
        # ♻️ SERVER RESTART SUCCESS HANDLER
        # ============================================================
        if os.path.exists("restart.txt"):
            try:
                with open("restart.txt", "r") as f:
                    chat_id_str, msg_id_str = f.read().strip().split("\n")
                    chat_id = int(chat_id_str)
                    msg_id = int(msg_id_str)

                await self.edit_message_text(
                    chat_id=chat_id,
                    message_id=msg_id,
                    text="✅ **Bot Restarted Successfully!**",
                )
            except Exception as e:
                logger.error(f"Failed to edit restart success message: {e}")
            finally:
                if os.path.exists("restart.txt"):
                    os.remove("restart.txt")

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
        FIXED: Added empty check to prevent crashing when hitting deleted messages.
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
                # Pyrogram V2 returns empty message objects for deleted messages
                if not getattr(message, "empty", False):
                    yield message
                current += 1


# Instantiating the app here so root-level handlers can bind to it
app = Bot()


# ============================================================
# 🗑️ AUTO DELETE PM MEDIA (30-MINUTES, MEMORY SAFE)
# ============================================================
async def delete_media_task(message: Message, delay: int):
    """Background task to safely handle delayed deletions without blocking workers."""
    await asyncio.sleep(delay)
    try:
        if message:
            await message.delete()
    except Exception as e:
        logger.error(f"Failed to auto-delete PM media for {message.from_user.id}: {e}")


@app.on_message(
    filters.private
    & (
        filters.document
        | filters.video
        | filters.audio
        | filters.photo
        | filters.voice
        | filters.video_note
    ),
    group=2,
)
async def auto_delete_user_media_pm(client: Client, message: Message):
    user = message.from_user
    if not user or message.outgoing:
        return

    # Detached the sleep timer into a background task.
    # Set to 1800 seconds (30 minutes)
    asyncio.create_task(delete_media_task(message, delay=1800))


# ============================================================
# 🚀 LAUNCH SEQUENCE
# ============================================================
if __name__ == "__main__":

    # --- 🧹 AUTO DELETE OLD SESSION FILES ---
    # FIXED: The previous wildcard (*.session) deleted ALL sessions, including the one
    # the bot needs to run! Now it safely ignores the active bot session.
    print("🔍 Checking for obsolete session files...")
    active_session = f"{SESSION}.session"

    for file in glob.glob("*.session"):
        if file != active_session:
            try:
                os.remove(file)
                print(f"🗑️ Deleted obsolete session: {file}")
            except Exception as e:
                print(f"⚠️ Could not delete {file}: {e}")
    # -----------------------------------------

    app.run()
