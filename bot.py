import asyncio
import glob
import logging
import logging.config
import os
from typing import AsyncGenerator, Union

import pyromod  # ⚡ Injects .listen() into Pyrogram globally
from aiohttp import web
from pyrogram import Client, __version__, filters, idle, types
from pyrogram.raw.all import layer
from pyrogram.types import Message

from database.ia_filterdb import Media
from database.plugin_dbs import plugin_db
from database.users_chats_db import db as old_db
from info import API_HASH, API_ID, BOT_TOKEN, LOG_STR, PORT, SESSION
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

# Silence noisy background logs
logging.getLogger("pyrogram").setLevel(logging.ERROR)
logging.getLogger("pyrogram.session.session").setLevel(logging.ERROR)
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

    async def start(self, *args, **kwargs):
        # Pass arguments up to parent
        await super().start(*args, **kwargs)

        # 1. LOAD BANNED USERS/CHATS (Centralized & Legacy)
        b_users = []
        b_chats = []
        try:
            # Fetch disabled chats
            async for chat in old_db.grp.find({"chat_status.is_disabled": True}):
                if chat.get("id"):
                    b_chats.append(chat["id"])

            # Fetch banned users from the new centralized DB
            async for user in plugin_db.ban_col.find({}):
                if user.get("_id"):
                    b_users.append(user["_id"])

            # Fetch legacy banned users from the old users DB
            async for user in old_db.col.find({"ban_status.is_banned": True}):
                u_id = user.get("id")
                if u_id and u_id not in b_users:
                    b_users.append(u_id)
        except Exception as e:
            logger.error(f"Error loading bans: {e}")

        temp.BANNED_USERS = b_users
        temp.BANNED_CHATS = b_chats

        # 2. DATABASE INITIALIZATION
        try:
            await Media.collection.drop_index("file_name_text")
        except Exception:
            pass

        try:
            await Media.ensure_indexes()
        except Exception as e:
            logger.error(f"Error ensuring DB indexes: {e}")

        me = await self.get_me()
        temp.ME = me.id
        temp.U_NAME = me.username
        temp.B_NAME = me.first_name
        self.username = f"@{me.username}"

        logger.info(
            f"{me.first_name} with Pyrogram v{__version__} (Layer {layer}) started on {me.username}."
        )
        logger.info(LOG_STR)

        # 3. RESTART SUCCESS HANDLER
        if os.path.exists("restart.txt"):
            try:
                with open("restart.txt", "r") as f:
                    chat_id_str, msg_id_str = f.read().strip().split("\n")
                await self.edit_message_text(
                    chat_id=int(chat_id_str),
                    message_id=int(msg_id_str),
                    text="✅ **Bot Restarted Successfully!**",
                )
            except Exception as e:
                logger.error(f"Failed to edit restart success message: {e}")
            finally:
                if os.path.exists("restart.txt"):
                    os.remove("restart.txt")

    async def stop(self, *args, **kwargs):
        await super().stop(*args, **kwargs)
        logger.info("Bot stopped. Bye.")

    async def iter_messages(
        self, chat_id: Union[int, str], limit: int, offset: int = 0
    ) -> AsyncGenerator[types.Message, None]:
        current = offset
        while True:
            new_diff = min(200, limit - current)
            if new_diff <= 0:
                return
            messages = await self.get_messages(
                chat_id, list(range(current, current + new_diff + 1))
            )
            for message in messages:
                if not getattr(message, "empty", False):
                    yield message
                current += 1


app = Bot()


# ============================================================
# 🗑️ AUTO DELETE PM MEDIA (30-MINUTES, MEMORY SAFE)
# ============================================================
async def delete_media_task(message: Message, delay: int):
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
    asyncio.create_task(delete_media_task(message, delay=1800))


# ============================================================
# 🌐 AIOHTTP WEB SERVER FOR KOYEB HEALTH CHECKS
# ============================================================
async def health_check(request):
    return web.Response(text="Bot is running and healthy!")


async def start_services():
    # 1. Clean obsolete sessions
    print("🔍 Checking for obsolete session files...")
    active_session = f"{SESSION}.session"
    for file in glob.glob("*.session"):
        if file != active_session:
            try:
                os.remove(file)
                print(f"🗑️ Deleted obsolete session: {file}")
            except Exception as e:
                print(f"⚠️ Could not delete {file}: {e}")

    # 2. Start Web Server (For Koyeb Port Binding)
    web_app = web.Application()
    web_app.router.add_get("/", health_check)
    runner = web.AppRunner(web_app)
    await runner.setup()
    
    # Safe fallback if PORT isn't strictly an integer
    bind_port = int(PORT) if PORT else 8080
    
    site = web.TCPSite(runner, "0.0.0.0", bind_port)
    await site.start()
    logger.info(f"🌐 Web server listening on port {bind_port} for health checks.")

    # 3. Start Bot and Idle
    await app.start()
    await idle()

    # 4. Shutdown cleanly
    await app.stop()
    await runner.cleanup()


# ============================================================
# 🚀 LAUNCH SEQUENCE
# ============================================================
if __name__ == "__main__":
    try:
        # asyncio.run is the modern standard for executing the main loop
        asyncio.run(start_services())
    except KeyboardInterrupt:
        logger.info("Process interrupted. Shutting down...")
