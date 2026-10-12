import asyncio
from logging import ERROR, getLogger

from pyrogram import Client, StopPropagation, enums, filters
from pyrogram.types import Message

import info

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
# 🚨 DEEP-LINK SEARCH INTERCEPTOR
# ============================================================
@Client.on_message(filters.command("start") & filters.private & admin_filter, group=-99)
async def intercept_direct_search(client: Client, message: Message):
    if len(message.command) > 1 and message.command[1].startswith("search_"):
        query = message.command[1].replace("search_", "").replace("_", " ")
        try:
            # Connects directly to pm_filter.py to execute the search logic
            from plugins.pm_filter import auto_filter

            message.text = query
            await auto_filter(client, message)
        except Exception as e:
            logger.error(f"Failed to intercept search: {e}")
            await message.reply_text(
                f"🔍 **Search Query:** `{query}`\n\nTap the text above to copy it, then send it to me to search!"
            )
        raise StopPropagation
