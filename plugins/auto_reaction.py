import asyncio
from logging import ERROR, getLogger

from pyrogram import Client, enums, filters
from pyrogram.types import Message

import info
from database.plugin_dbs import plugin_db as _plugin_db

logger = getLogger(__name__)
logger.setLevel(ERROR)


# ============================================================
# 👑 FULL POWER ADMIN CHECKER (GLOBAL + CHAT + ANONYMOUS)
# ============================================================
def get_admin_list():
    raw_admins = getattr(info, "ADMINS", [])
    if isinstance(raw_admins, (str, int)):
        raw_admins = str(raw_admins).replace(",", " ").split()
    return [int(x) for x in raw_admins if str(x).strip().lstrip("-").isdigit()]


async def is_user_admin(client: Client, message: Message):
    admin_list = get_admin_list()

    # 1. Global Admin Check (Direct User)
    if message.from_user and message.from_user.id in admin_list:
        return True

    # 2. Global Admin Check (Anonymous/Channel sending as Chat)
    if message.sender_chat and message.sender_chat.id in admin_list:
        return True

    # 3. Group Admin Check (Normal & Anonymous Admins)
    if message.chat and message.chat.type in [
        enums.ChatType.GROUP,
        enums.ChatType.SUPERGROUP,
    ]:
        if message.sender_chat and message.sender_chat.id == message.chat.id:
            return True

        if message.from_user:
            try:
                member = await client.get_chat_member(
                    message.chat.id, message.from_user.id
                )
                return member.status in [
                    enums.ChatMemberStatus.ADMINISTRATOR,
                    enums.ChatMemberStatus.OWNER,
                ]
            except Exception:
                pass

    return False


async def admin_check(_, client: Client, message: Message):
    return await is_user_admin(client, message)


admin_filter = filters.create(admin_check)


# ============================================================
# ⚙️ CONFIGURATION COMMANDS
# ============================================================
@Client.on_message(filters.command("enablereaction") & admin_filter)
async def enable_react(bot: Client, message: Message):
    await _plugin_db.set_reaction_status(True)
    await message.reply_text("✅ **Auto-Reaction has been ENABLED globally!**")


@Client.on_message(filters.command("disablereaction") & admin_filter)
async def disable_react(bot: Client, message: Message):
    await _plugin_db.set_reaction_status(False)
    await message.reply_text("🚫 **Auto-Reaction has been DISABLED globally.**")


# ============================================================
# ❤️ AUTO REACTION ENGINE
# ============================================================
@Client.on_message((filters.group | filters.channel) & ~filters.bot, group=-5)
async def auto_react_heart(bot: Client, message: Message):
    is_enabled = await _plugin_db.get_reaction_status()
    if not is_enabled or (message.from_user and message.from_user.is_bot):
        return

    text = message.text or message.caption
    if text and str(text).startswith("/"):
        return

    try:
        # ⚡ ZERO-FAIL NATIVE PYROGRAM REACTION
        await bot.send_reaction(
            chat_id=message.chat.id, message_id=message.id, emoji="❤️"
        )
    except Exception:
        pass
