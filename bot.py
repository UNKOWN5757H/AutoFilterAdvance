import asyncio  # Added to support asyncio.sleep()
import logging
import logging.config

# Get logging configurations
logging.config.fileConfig("logging.conf")
logging.getLogger().setLevel(logging.INFO)
logging.getLogger("pyrogram").setLevel(logging.ERROR)
logging.getLogger("imdbpy").setLevel(logging.ERROR)

from typing import AsyncGenerator, Optional, Union

from pyrogram import Client, __version__, filters, types  # Added filters
from pyrogram.raw.all import layer
from pyrogram.types import Message  # Added Message

from database.ia_filterdb import Media
from database.users_chats_db import db
from info import API_HASH, API_ID, BOT_TOKEN, LOG_STR, SESSION
from utils import temp


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
        await Media.ensure_indexes()
        me = await self.get_me()
        temp.ME = me.id
        temp.U_NAME = me.username
        temp.B_NAME = me.first_name
        self.username = "@" + me.username
        logging.info(
            f"{me.first_name} with for Pyrogram v{__version__} (Layer {layer}) started on {me.username}."
        )
        logging.info(LOG_STR)

    async def stop(self, *args):
        await super().stop()
        logging.info("Bot stopped. Bye.")

    # Moved inside the Bot class where 'self' is valid
    async def iter_messages(
        self,
        chat_id: Union[int, str],
        limit: int,
        offset: int = 0,
    ) -> Optional[AsyncGenerator["types.Message", None]]:
        """Iterate through a chat sequentially.
        This convenience method does the same as repeatedly calling :meth:`~pyrogram.Client.get_messages` in a loop, thus saving
        you from the hassle of setting up boilerplate code. It is useful for getting the whole chat messages with a
        single call.
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


# ----------------------------- Auto delete PM media -------------------------
@Client.on_message(filters.private & ~filters.service)
async def auto_delete_user_media_pm(client: Client, message: Message):
    user = message.from_user
    if not user or message.outgoing:
        return

    if any(
        [
            message.document,
            message.video,
            message.audio,
            message.voice,
            message.photo,
            message.video_note,
        ]
    ):
        await asyncio.sleep(14400)  # Wait 4 hours
        try:
            await message.delete()
        except Exception as e:
            print(f"Delete error: {e}")


if __name__ == "__main__":
    app = Bot()
    app.run()
