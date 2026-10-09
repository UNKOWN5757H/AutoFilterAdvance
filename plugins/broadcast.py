import asyncio
import datetime
import time
from logging import ERROR, getLogger

from motor.motor_asyncio import AsyncIOMotorClient
from pyrogram import Client, filters
from pyrogram.errors import (
    ChatWriteForbidden,
    FloodWait,
    InputUserDeactivated,
    MessageTooLong,
    PeerIdInvalid,
    UserDeactivatedBan,
    UserIsBlocked,
)
from pyrogram.types import Message

import info
from database.users_chats_db import db as _db

logger = getLogger(__name__)
logger.setLevel(ERROR)

# ============================================================
# ⚙️ MONGODB PERSISTENT TASKS SETUP
# ============================================================
try:
    _DB_CLIENT = AsyncIOMotorClient(info.DATABASE_URI)
    _BOT_DB = _DB_CLIENT[info.DATABASE_NAME]
    _broadcast_col = _BOT_DB["broadcast_tasks"]
except Exception as e:
    logger.error(f"Failed to init Broadcast DB: {e}")

DELETE_DELAY = getattr(info, "BROADCAST_DELETE_TIME", 24 * 3600)

worker_started = False
_WORKER_TASK = None


# ============================================================
# 👑 FOOLPROOF ADMIN CHECKER
# ============================================================
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


async def admin_check(_, __, message: Message):
    if not message.from_user:
        return False
    return message.from_user.id in get_admin_list()


admin_filter = filters.create(admin_check)


def get_progress_bar(current, total):
    if total == 0:
        return "[░░░░░░░░░░] 0.0%"
    percent = (current / total) * 100
    filled = int(percent / 10)
    return f"[{'█' * filled}{'░' * (10 - filled)}] {percent:.1f}%"


# ============================================================
# 🕰️ PERSISTENT BACKGROUND WORKER
# ============================================================
async def bcast_cleaner_worker(bot: Client):
    """Permanently checks DB for expired broadcast messages to delete."""
    while True:
        try:
            now = time.time()
            cursor = _broadcast_col.find({"delete_at": {"$lte": now}})
            docs = await cursor.to_list(length=100)

            for doc in docs:
                try:
                    await bot.delete_messages(
                        chat_id=doc["chat_id"], message_ids=doc["message_id"]
                    )
                except Exception:
                    pass
                await _broadcast_col.delete_one({"_id": doc["_id"]})
        except Exception:
            pass
        await asyncio.sleep(60)


@Client.on_message(filters.group | filters.private, group=-100)
async def init_worker(bot: Client, message):
    global worker_started, _WORKER_TASK
    if not worker_started:
        worker_started = True
        _WORKER_TASK = asyncio.create_task(bcast_cleaner_worker(bot))


# ============================================================
# 📤 3-LAYER "NEVER FAIL" BROADCAST ENGINE
# ============================================================
async def send_and_schedule_delete(bot: Client, chat_id: int, message: Message):
    """
    3-Layer Fallback Engine:
    Layer 1: Copy Message (Best)
    Layer 2: Forward Message (If copy fails due to strict privacy)
    Layer 3: Send Raw Text/Media (If forward fails)
    Includes silent notification suppression.
    """
    try:
        sent_msg = None
        # LAYER 1: Copy
        try:
            sent_msg = await message.copy(chat_id=chat_id, disable_notification=True)
        except FloodWait as e:
            await asyncio.sleep(e.value + 1)
            sent_msg = await message.copy(chat_id=chat_id, disable_notification=True)
        except Exception:
            # LAYER 2: Forward
            try:
                sent_msg = await message.forward(
                    chat_id=chat_id, disable_notification=True
                )
            except FloodWait as e:
                await asyncio.sleep(e.value + 1)
                sent_msg = await message.forward(
                    chat_id=chat_id, disable_notification=True
                )
            except Exception:
                # LAYER 3: Raw Send
                if message.photo:
                    sent_msg = await bot.send_photo(
                        chat_id,
                        message.photo.file_id,
                        caption=message.caption,
                        disable_notification=True,
                    )
                elif message.video:
                    sent_msg = await bot.send_video(
                        chat_id,
                        message.video.file_id,
                        caption=message.caption,
                        disable_notification=True,
                    )
                elif message.document:
                    sent_msg = await bot.send_document(
                        chat_id,
                        message.document.file_id,
                        caption=message.caption,
                        disable_notification=True,
                    )
                else:
                    sent_msg = await bot.send_message(
                        chat_id, message.text, disable_notification=True
                    )

        if sent_msg:
            # Save to MongoDB for auto-deletion
            await _broadcast_col.insert_one(
                {
                    "chat_id": chat_id,
                    "message_id": sent_msg.id,
                    "delete_at": time.time() + DELETE_DELAY,
                }
            )
            return 200, None
        return 500, "Unknown Error"

    except FloodWait as e:
        await asyncio.sleep(e.value + 1)
        return await send_and_schedule_delete(bot, chat_id, message)
    except (UserIsBlocked, InputUserDeactivated, UserDeactivatedBan):
        return 400, "Blocked/Deleted"
    except PeerIdInvalid:
        return 400, "Invalid"
    except ChatWriteForbidden:
        return 400, "Left"
    except MessageTooLong:
        return 400, "MEDIA_CAPTION_TOO_LONG"
    except Exception as e:
        return 500, str(e)


# ============================================================
# 👤 USER BROADCAST
# ============================================================
@Client.on_message(filters.command("broadcast") & admin_filter & filters.reply)
async def user_broadcast(bot: Client, message: Message):
    b_msg = message.reply_to_message
    if not b_msg:
        return await message.reply_text(
            "⚠️ **Reply to the message you want to broadcast.**"
        )

    status_msg = await message.reply_text("⏳ **Fetching user database...**")

    try:
        users_cursor = await _db.get_all_users()
        users = (
            await users_cursor.to_list(length=None)
            if hasattr(users_cursor, "to_list")
            else list(users_cursor)
        )
    except Exception as e:
        return await status_msg.edit_text(f"❌ **Database Error:** `{e}`")

    total_users = len(users)
    if total_users == 0:
        return await status_msg.edit_text("⚠️ **No users found in the database.**")

    await status_msg.edit_text(f"🚀 **Broadcasting to {total_users} users...**")
    start_time = time.time()
    done = success = blocked = failed = 0

    for user in users:
        user_id = int(user.get("id") or user.get("user_id"))
        status, _ = await send_and_schedule_delete(bot, user_id, b_msg)

        if status == 200:
            success += 1
        elif status == 400:
            blocked += 1
            await _db.delete_user(user_id)
        else:
            failed += 1

        done += 1
        if done % 25 == 0 or done == total_users:
            try:
                progress = get_progress_bar(done, total_users)
                await status_msg.edit_text(
                    f"📢 **User Broadcast Progress**\n{progress}\n\n"
                    f"👥 **Total:** `{total_users}`\n"
                    f"✅ **Sent:** `{success}`\n"
                    f"🚫 **Dead/Blocked:** `{blocked}`\n"
                    f"⚠️ **Failed:** `{failed}`\n"
                    f"📦 **Processed:** `{done}/{total_users}`"
                )
            except FloodWait as e:
                await asyncio.sleep(e.value + 1)
            except Exception:
                pass

        await asyncio.sleep(0.3)  # Prevent API bans

    time_taken = datetime.timedelta(seconds=int(time.time() - start_time))
    hours, minutes = DELETE_DELAY // 3600, (DELETE_DELAY % 3600) // 60
    time_str = f"{hours} hours" if hours > 0 else f"{minutes} minutes"

    await status_msg.edit_text(
        f"✅ **User Broadcast Completed!**\n\n"
        f"🕒 **Duration:** `{time_taken}`\n"
        f"👥 **Total:** `{total_users}`\n"
        f"✅ **Successful:** `{success}`\n"
        f"🚫 **Removed (Dead):** `{blocked}`\n"
        f"⚠️ **Failed:** `{failed}`\n\n"
        f"⏳ *These messages will vanish silently in {time_str}.*"
    )


# ============================================================
# 🏘️ GROUP BROADCAST
# ============================================================
@Client.on_message(filters.command("group_broadcast") & admin_filter & filters.reply)
async def group_broadcast(bot: Client, message: Message):
    b_msg = message.reply_to_message
    if not b_msg:
        return await message.reply_text(
            "⚠️ **Reply to the message you want to broadcast.**"
        )

    status_msg = await message.reply_text("⏳ **Fetching chat database...**")

    try:
        chats_cursor = await _db.get_all_chats()
        chats = (
            await chats_cursor.to_list(length=None)
            if hasattr(chats_cursor, "to_list")
            else list(chats_cursor)
        )
    except Exception as e:
        return await status_msg.edit_text(f"❌ **Database Error:** `{e}`")

    total_chats = len(chats)
    if total_chats == 0:
        return await status_msg.edit_text("⚠️ **No groups found in the database.**")

    await status_msg.edit_text(f"🚀 **Broadcasting to {total_chats} groups...**")
    start_time = time.time()
    done = success = left = failed = 0

    for chat in chats:
        chat_id = int(chat.get("id") or chat.get("chat_id"))
        status, reason = await send_and_schedule_delete(bot, chat_id, b_msg)

        if status == 200:
            success += 1
        elif status == 400 and reason in ["Left", "Blocked/Deleted"]:
            left += 1
            try:
                await _db.disable_chat(chat_id, "Bot Removed")
            except Exception:
                pass
        else:
            failed += 1

        done += 1
        if done % 15 == 0 or done == total_chats:
            try:
                progress = get_progress_bar(done, total_chats)
                await status_msg.edit_text(
                    f"🏘️ **Group Broadcast Progress**\n{progress}\n\n"
                    f"💬 **Total:** `{total_chats}`\n"
                    f"✅ **Sent:** `{success}`\n"
                    f"🚷 **Kicked/Left:** `{left}`\n"
                    f"⚠️ **Failed:** `{failed}`\n"
                    f"📦 **Processed:** `{done}/{total_chats}`"
                )
            except FloodWait as e:
                await asyncio.sleep(e.value + 1)
            except Exception:
                pass

        await asyncio.sleep(0.5)

    time_taken = datetime.timedelta(seconds=int(time.time() - start_time))
    hours, minutes = DELETE_DELAY // 3600, (DELETE_DELAY % 3600) // 60
    time_str = f"{hours} hours" if hours > 0 else f"{minutes} minutes"

    await status_msg.edit_text(
        f"✅ **Group Broadcast Completed!**\n\n"
        f"🕒 **Duration:** `{time_taken}`\n"
        f"💬 **Total:** `{total_chats}`\n"
        f"✅ **Successful:** `{success}`\n"
        f"🚷 **Removed From:** `{left}`\n"
        f"⚠️ **Failed:** `{failed}`\n\n"
        f"⏳ *These messages will vanish silently in {time_str}.*"
    )
