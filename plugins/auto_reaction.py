import asyncio
from logging import ERROR, getLogger
from pyrogram import Client, filters
from pyrogram.types import Message
import info
from database.plugin_dbs import plugin_db as _plugin_db

logger = getLogger(__name__)
logger.setLevel(ERROR)

def get_admin_list():
    raw_admins = getattr(info, "ADMINS", [])
    if isinstance(raw_admins, str): return [int(x) for x in raw_admins.replace(",", " ").split() if x.strip().lstrip("-").isdigit()]
    elif isinstance(raw_admins, int): return [raw_admins]
    elif isinstance(raw_admins, list): return [int(x) for x in raw_admins if str(x).strip().lstrip("-").isdigit()]
    return []

admin_filter = filters.create(lambda _, __, msg: bool(msg.from_user and msg.from_user.id in get_admin_list()))

@Client.on_message(filters.command("enablereaction") & admin_filter)
async def enable_react(bot: Client, message: Message):
    await _plugin_db.set_reaction_status(True)
    await message.reply_text("✅ **Auto-Reaction has been ENABLED globally!**")

@Client.on_message(filters.command("disablereaction") & admin_filter)
async def disable_react(bot: Client, message: Message):
    await _plugin_db.set_reaction_status(False)
    await message.reply_text("🚫 **Auto-Reaction has been DISABLED globally.**")

@Client.on_message((filters.group | filters.channel) & ~filters.bot, group=-5)
async def auto_react_heart(bot: Client, message: Message):
    is_enabled = await _plugin_db.get_reaction_status()
    if not is_enabled or (message.from_user and message.from_user.is_bot): return
    if (message.text or message.caption) and str(message.text or message.caption).startswith("/"): return

    try:
        # ⚡ ZERO-FAIL NATIVE PYROGRAM REACTION
        await client.send_reaction(chat_id=message.chat.id, message_id=message.id, emoji="❤️")
    except Exception: pass
