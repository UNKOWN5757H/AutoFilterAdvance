import asyncio
import time
from collections import defaultdict
from logging import ERROR, getLogger

from pyrogram import Client, enums, filters
from pyrogram.errors import (
    ChatAdminRequired,
    FloodWait,
    MessageDeleteForbidden,
    UserAdminInvalid,
)
from pyrogram.types import ChatPermissions, Message

import info

logger = getLogger(__name__)
logger.setLevel(ERROR)

# ============================================================
# ⚙️ FLOOD THRESHOLDS & TRACKERS
# ============================================================
FLOOD_WINDOW_SECONDS = 3
MAX_MESSAGES_PER_WINDOW = 5
MUTE_DURATION_SECONDS = 600  # 10 minutes

USER_MESSAGE_LOG = defaultdict(list)
MUTED_USERS = {}
MUTED_PROCESSING_LOCK = set()

# Cache for group admin checks to avoid spamming get_chat_member
ADMIN_CACHE = {}  # {(chat_id, user_id): (expiry_timestamp, is_admin)}


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
        # If the sender is the group itself, it's a Group Anonymous Admin
        if message.sender_chat and message.sender_chat.id == message.chat.id:
            return True

        # If it's a Normal Admin in this group
        if message.from_user:
            chat_id = message.chat.id
            user_id = message.from_user.id
            cache_key = (chat_id, user_id)
            now = time.time()

            cached = ADMIN_CACHE.get(cache_key)
            if cached and cached[0] > now:
                return cached[1]

            try:
                member = await client.get_chat_member(chat_id, user_id)
                is_admin = member.status in [
                    enums.ChatMemberStatus.ADMINISTRATOR,
                    enums.ChatMemberStatus.OWNER,
                ]
                ADMIN_CACHE[cache_key] = (now + 300, is_admin)  # Cache for 5 minutes
                return is_admin
            except Exception:
                return False

    return False


# ============================================================
# 🧹 RAM GARBAGE COLLECTOR (PREVENTS LEAKS)
# ============================================================
async def memory_cleanup_worker():
    while True:
        await asyncio.sleep(300)  # Runs every 5 minutes
        now = time.time()

        # Clean old mute records
        expired_mutes = [uid for uid, expiry in MUTED_USERS.items() if expiry <= now]
        for uid in expired_mutes:
            del MUTED_USERS[uid]

        # Clean inactive message logs
        inactive_users = [
            uid
            for uid, timestamps in USER_MESSAGE_LOG.items()
            if not timestamps or (now - timestamps[-1]) > 60
        ]
        for uid in inactive_users:
            del USER_MESSAGE_LOG[uid]

        # Clean admin cache
        expired_admin_checks = [k for k, (exp, _) in ADMIN_CACHE.items() if exp <= now]
        for k in expired_admin_checks:
            del ADMIN_CACHE[k]


_GC_STARTED = False


@Client.on_message(group=-150)
async def init_antiflood_gc(client: Client, message: Message):
    global _GC_STARTED
    if not _GC_STARTED:
        _GC_STARTED = True
        asyncio.create_task(memory_cleanup_worker())


# ============================================================
# 🛡️ IRONCLAD ANTI-FLOOD LISTENER
# ============================================================
@Client.on_message(filters.incoming & ~filters.service, group=-50)
async def ironclad_antiflood_shield(client: Client, message: Message):
    user_id = (
        message.from_user.id
        if message.from_user
        else getattr(message.sender_chat, "id", 0)
    )
    if not user_id:
        return

    chat_id = message.chat.id
    chat_type = message.chat.type

    # Verify immunity (Global Admins, Group Admins, Anonymous Admins)
    if await is_user_admin(client, message):
        return

    now = time.time()

    # 1. Silently drop and delete messages if user is already muted
    if user_id in MUTED_USERS:
        if now < MUTED_USERS[user_id]:
            try:
                await message.delete()
            except (MessageDeleteForbidden, FloodWait, Exception):
                pass
            message.stop_propagation()
            return
        else:
            del MUTED_USERS[user_id]

    # 2. Record message timestamps and clear outside the sliding window
    timestamps = USER_MESSAGE_LOG[user_id]
    USER_MESSAGE_LOG[user_id] = [
        t for t in timestamps if now - t <= FLOOD_WINDOW_SECONDS
    ]
    USER_MESSAGE_LOG[user_id].append(now)

    # 3. Threshold check
    if len(USER_MESSAGE_LOG[user_id]) > MAX_MESSAGES_PER_WINDOW:
        if user_id in MUTED_PROCESSING_LOCK:
            message.stop_propagation()
            return

        MUTED_PROCESSING_LOCK.add(user_id)
        MUTED_USERS[user_id] = now + MUTE_DURATION_SECONDS
        USER_MESSAGE_LOG[user_id].clear()

        # Delete trigger message
        try:
            await message.delete()
        except Exception:
            pass

        # Apply group mute or private warning
        if chat_type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
            mention = message.from_user.mention if message.from_user else "User"
            try:
                await client.restrict_chat_member(
                    chat_id=chat_id,
                    user_id=user_id,
                    permissions=ChatPermissions(can_send_messages=False),
                    until_date=int(now + MUTE_DURATION_SECONDS),
                )
                warn = await client.send_message(
                    chat_id=chat_id,
                    text=f"🛑 **Anti-Flood Triggered!**\n\n{mention} has been muted for **10 minutes** for spamming requests.",
                )
                asyncio.create_task(delete_after_delay(warn, 10))
            except (ChatAdminRequired, UserAdminInvalid):
                # If bot lacks restrict rights, notify chat once
                warn = await client.send_message(
                    chat_id=chat_id,
                    text=f"⚠️ {mention}, please slow down! Your requests are being ignored for **10 minutes**.",
                )
                asyncio.create_task(delete_after_delay(warn, 10))
            except FloodWait as e:
                await asyncio.sleep(e.value + 1)
            except Exception as e:
                logger.error(f"Anti-flood group mute failed: {e}")
        else:
            try:
                warn = await client.send_message(
                    chat_id=chat_id,
                    text="🛑 **Anti-Flood Shield Triggered!**\nYou sent too many commands. Please wait 10 minutes before sending more messages.",
                )
                asyncio.create_task(delete_after_delay(warn, 10))
            except Exception:
                pass

        MUTED_PROCESSING_LOCK.discard(user_id)
        message.stop_propagation()


async def delete_after_delay(msg: Message, delay: int):
    await asyncio.sleep(delay)
    try:
        await msg.delete()
    except Exception:
        pass
