import asyncio
import logging

import aiohttp
from pyrogram import Client, filters
from pyrogram.types import Message

# Safely import ADMINS and BOT_TOKEN
try:
    from info import ADMINS, BOT_TOKEN
except ImportError:
    ADMINS = []
    BOT_TOKEN = None

# ⚡ FIXED: Uses the new plugin_db for reaction state instead of local JSON
from database.plugin_dbs import plugin_db

logger = logging.getLogger(__name__)


def is_bot_owner(user_id: int) -> bool:
    admin_list = [int(a) for a in ADMINS if str(a).isdigit()]
    return user_id in admin_list


# ============================================================
# ⚡ THE FIX: GLOBAL HTTP SESSION (Zero Resource Leak)
# ============================================================
# We create ONE session and reuse it, so the bot never lags!
HTTP_SESSION = None


async def get_http_session():
    global HTTP_SESSION
    if HTTP_SESSION is None or HTTP_SESSION.closed:
        HTTP_SESSION = aiohttp.ClientSession()
    return HTTP_SESSION


async def send_reaction_background(chat_id: int, message_id: int):
    """Silently fires the reaction through a shared connection pool."""
    if not BOT_TOKEN:
        return

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/setMessageReaction"
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "reaction": [{"type": "emoji", "emoji": "❤️"}],
    }

    try:
        session = await get_http_session()
        # timeout=2 ensures that if Telegram is slow, the bot doesn't wait around
        async with session.post(url, json=payload, timeout=2) as response:
            pass
    except Exception:
        # Silently fail so it doesn't spam your logs on network hiccups
        pass


# ============================================================
# ⚙️ GLOBAL ADMIN COMMANDS
# ============================================================
@Client.on_message(filters.command("enablereaction"))
async def enable_react(bot: Client, message: Message):
    if not message.from_user or not is_bot_owner(message.from_user.id):
        return await message.reply_text("❌ **Only Bot ADMINS can use this command.**")

    await plugin_db.set_reaction_status(True)
    await message.reply_text("✅ **Auto-Reaction has been ENABLED globally!**")


@Client.on_message(filters.command("disablereaction"))
async def disable_react(bot: Client, message: Message):
    if not message.from_user or not is_bot_owner(message.from_user.id):
        return await message.reply_text("❌ **Only Bot ADMINS can use this command.**")

    await plugin_db.set_reaction_status(False)
    await message.reply_text("🚫 **Auto-Reaction has been DISABLED globally.**")


# ============================================================
# ❤️ AUTO REACTION MODULE
# ============================================================
@Client.on_message((filters.group | filters.channel) & ~filters.bot, group=-5)
async def auto_react_heart(bot: Client, message: Message):

    is_enabled = await plugin_db.get_reaction_status()
    if not is_enabled:
        return

    if message.from_user and message.from_user.is_bot:
        return

    # SMALL OPTIMIZATION: Do not react to commands (like /start or /myadds)
    # to save API limits for actual movie requests!
    text = message.text or message.caption
    if text and text.startswith("/"):
        return

    # Instantly pushes the reaction to the global session without blocking!
    asyncio.create_task(send_reaction_background(message.chat.id, message.id))
