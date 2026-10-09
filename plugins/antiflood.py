import asyncio
import time
from collections import defaultdict
from logging import ERROR, getLogger

from pyrogram import Client, enums, filters
from pyrogram.types import ChatPermissions, Message

import info

logger = getLogger(__name__)
logger.setLevel(ERROR)


def get_admin_list():
    raw_admins = getattr(info, "ADMINS", [])
    if isinstance(raw_admins, str):
        return [
            int(x)
            for x in raw_admins.replace(",", " ").split()
            if x.strip().lstrip("-").isdigit()
        ]
    elif isinstance(raw_admins, int):
        return [raw_admins]
    elif isinstance(raw_admins, list):
        return [int(x) for x in raw_admins if str(x).strip().lstrip("-").isdigit()]
    return []


# User tracking: {user_id: [timestamps]}
USER_MESSAGE_LOG = defaultdict(list)
MUTED_USERS = {}

FLOOD_WINDOW_SECONDS = 3
MAX_MESSAGES_PER_WINDOW = 5
MUTE_DURATION_SECONDS = 600  # 10 minutes


@Client.on_message(filters.incoming & ~filters.service, group=-50)
async def ironclad_antiflood_shield(client: Client, message: Message):
    if not message.from_user:
        return
    user_id = message.from_user.id

    # Bot admins are always exempt
    if user_id in get_admin_list():
        return

    now = time.time()

    # Verify if user is currently muted by the shield
    if user_id in MUTED_USERS:
        unmute_time = MUTED_USERS[user_id]
        if now < unmute_time:
            try:
                await message.delete()
            except Exception:
                pass
            message.stop_propagation()
            return
        else:
            del MUTED_USERS[user_id]

    # Clean history older than the sliding window
    user_timestamps = USER_MESSAGE_LOG[user_id]
    USER_MESSAGE_LOG[user_id] = [
        t for t in user_timestamps if now - t <= FLOOD_WINDOW_SECONDS
    ]
    USER_MESSAGE_LOG[user_id].append(now)

    if len(USER_MESSAGE_LOG[user_id]) > MAX_MESSAGES_PER_WINDOW:
        MUTED_USERS[user_id] = now + MUTE_DURATION_SECONDS
        USER_MESSAGE_LOG[user_id].clear()

        # Delete the trigger message
        try:
            await message.delete()
        except Exception:
            pass

        # Apply mute if message is from a group
        if message.chat.type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
            try:
                await client.restrict_chat_member(
                    chat_id=message.chat.id,
                    user_id=user_id,
                    permissions=ChatPermissions(can_send_messages=False),
                    until_date=int(now + MUTE_DURATION_SECONDS),
                )
                warn = await message.reply_text(
                    f"🛑 **Anti-Flood Triggered!**\n\n{message.from_user.mention} has sent too many requests and has been muted for **10 minutes**."
                )
                await asyncio.sleep(10)
                await warn.delete()
            except Exception:
                pass
        else:
            # Send warning in private chat
            try:
                warn = await message.reply_text(
                    "🛑 **Anti-Flood Shield Triggered!**\nYou sent too many commands. Please wait 10 minutes before sending more messages."
                )
                await asyncio.sleep(10)
                await warn.delete()
            except Exception:
                pass

        message.stop_propagation()
