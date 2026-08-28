import asyncio
from logging import getLogger, ERROR

import aiohttp
from pyrogram import Client, filters
from pyrogram.types import Message

try:
    from info import ADMINS, BOT_TOKEN
except ImportError:
    ADMINS = []
    BOT_TOKEN = None

from database.plugin_dbs import plugin_db as _plugin_db

logger = getLogger(__name__)
logger.setLevel(ERROR)


def is_bot_owner(user_id: int) -> bool:
    admin_list = [int(a) for a in ADMINS if str(a).isdigit()]
    return user_id in admin_list

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
        async with session.post(url, json=payload, timeout=2) as response:
            pass
    except Exception:
        pass


@Client.on_message(filters.command("enablereaction"))
async def enable_react(bot: Client, message: Message):
    if not message.from_user or not is_bot_owner(message.from_user.id):
        return await message.reply_text("❌ **Only Bot ADMINS can use this command.**")

    await _plugin_db.set_reaction_status(True)
    await message.reply_text("✅ **Auto-Reaction has been ENABLED globally!**")


@Client.on_message(filters.command("disablereaction"))
async def disable_react(bot: Client, message: Message):
    if not message.from_user or not is_bot_owner(message.from_user.id):
        return await message.reply_text("❌ **Only Bot ADMINS can use this command.**")

    await _plugin_db.set_reaction_status(False)
    await message.reply_text("🚫 **Auto-Reaction has been DISABLED globally.**")


@Client.on_message((filters.group | filters.channel) & ~filters.bot, group=-5)
async def auto_react_heart(bot: Client, message: Message):
    is_enabled = await _plugin_db.get_reaction_status()
    if not is_enabled:
        return

    if message.from_user and message.from_user.is_bot:
        return

    text = message.text or message.caption
    if text and text.startswith("/"):
        return

    asyncio.create_task(send_reaction_background(message.chat.id, message.id))
