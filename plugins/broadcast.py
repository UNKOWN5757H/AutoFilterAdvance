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
    PeerIdInvalid,
    UserIsBlocked,
)

import info
from database.users_chats_db import db as _db
from info import ADMINS

logger = getLogger(__name__)
logger.setLevel(ERROR)

# ⚡ Initialize a dedicated MongoDB collection for persistent deletion tasks
_DB_CLIENT = AsyncIOMotorClient(info.DATABASE_URI)
_BOT_DB = _DB_CLIENT[info.DATABASE_NAME]
_broadcast_col = _BOT_DB["broadcast_tasks"]

# 24 hours in seconds
DELETE_DELAY = 24 * 3600
worker_started = False


# ============================================================
# 🕰️ PERSISTENT BACKGROUND WORKER
# ============================================================
async def bcast_cleaner_worker(bot: Client):
    """Background worker that permanently checks DB for expired broadcast messages to delete."""
    while True:
        try:
            now = time.time()
            # Find messages due for deletion
            cursor = _broadcast_col.find({"delete_at": {"$lte": now}})
            docs = await cursor.to_list(length=100)

            for doc in docs:
                try:
                    await bot.delete_messages(
                        chat_id=doc["chat_id"], message_ids=doc["message_id"]
                    )
                except Exception:
                    pass  # Ignore if chat is deleted, user blocked bot, or message already gone

                # Remove task from DB once processed
                await _broadcast_col.delete_one({"_id": doc["_id"]})

        except Exception as e:
            logger.error(f"Broadcast cleaner error: {e}")

        await asyncio.sleep(60)  # Check the database every 60 seconds


@Client.on_message(group=-100)
async def init_worker(bot: Client, message):
    """Hidden hook to start the background worker once upon receiving any message."""
    global worker_started
    if not worker_started:
        worker_started = True
        asyncio.create_task(bcast_cleaner_worker(bot))


# ============================================================
# 📤 BROADCAST SENDER ENGINE
# ============================================================
async def send_and_schedule_delete(
    bot: Client, chat_id: int, message, is_group: bool = False
):
    try:
        sent_msg = await message.copy(chat_id=chat_id)

        # ⚡ Save task to MongoDB so it survives server restarts!
        await _broadcast_col.insert_one(
            {
                "chat_id": chat_id,
                "message_id": sent_msg.id,
                "delete_at": time.time() + DELETE_DELAY,
            }
        )

        return 200, None
    except FloodWait as e:
        await asyncio.sleep(e.value + 1)
        return await send_and_schedule_delete(bot, chat_id, message, is_group)
    except (UserIsBlocked, InputUserDeactivated):
        return 400, "Blocked/Deleted"
    except PeerIdInvalid:
        return 400, "Invalid"
    except ChatWriteForbidden:
        return 400, "Left"
    except Exception:
        return 500, "Error"


# ============================================================
# 👤 USER BROADCAST
# ============================================================
@Client.on_message(filters.command("broadcast") & filters.user(ADMINS) & filters.reply)
async def user_broadcast(bot: Client, message):
    b_msg = message.reply_to_message
    if not b_msg:
        return await message.reply_text(
            "⚠️ **Reply to the message you want to broadcast.**"
        )

    users = await _db.get_all_users()
    total_users = len(users)

    if total_users == 0:
        return await message.reply_text("⚠️ **No users found in the database.**")

    status_msg = await message.reply_text(
        f"🚀 **Broadcasting to {total_users} users...**"
    )
    start_time = time.time()
    done = success = blocked = failed = 0

    for user in users:
        user_id = int(user["id"])
        status, _ = await send_and_schedule_delete(bot, user_id, b_msg, is_group=False)

        if status == 200:
            success += 1
        elif status == 400:
            blocked += 1
            await _db.delete_user(user_id)
        else:
            failed += 1

        done += 1
        if done % 20 == 0:
            try:
                await status_msg.edit_text(
                    f"📢 **Broadcast Progress**\n\n"
                    f"👥 Total Users: {total_users}\n"
                    f"✅ Sent: {success}\n"
                    f"🚫 Blocked/Deleted: {blocked}\n"
                    f"⚠️ Failed: {failed}\n"
                    f"📦 Completed: {done}/{total_users}"
                )
            except FloodWait as e:
                await asyncio.sleep(e.value)
            except Exception:
                pass
        await asyncio.sleep(0.5)

    time_taken = datetime.timedelta(seconds=int(time.time() - start_time))
    await status_msg.edit_text(
        f"✅ **User Broadcast Completed!**\n\n"
        f"🕒 Duration: `{time_taken}`\n"
        f"👥 Total Users: {total_users}\n"
        f"✅ Successful: {success}\n"
        f"🚫 Blocked/Deleted: {blocked}\n"
        f"⚠️ Failed: {failed}\n\n"
        f"⏳ *Messages will be automatically deleted in exactly 24 hours.*"
    )


# ============================================================
# 🏘️ GROUP BROADCAST
# ============================================================
@Client.on_message(
    filters.command("group_broadcast") & filters.user(ADMINS) & filters.reply
)
async def group_broadcast(bot: Client, message):
    b_msg = message.reply_to_message
    if not b_msg:
        return await message.reply_text(
            "⚠️ **Reply to the message you want to broadcast.**"
        )

    chats = await _db.get_all_chats()
    total_chats = len(chats)

    if total_chats == 0:
        return await message.reply_text("⚠️ **No groups found in the database.**")

    status_msg = await message.reply_text(
        f"🚀 **Broadcasting to {total_chats} groups/chats...**"
    )
    start_time = time.time()
    done = success = left = failed = 0

    for chat in chats:
        chat_id = int(chat["id"])
        status, reason = await send_and_schedule_delete(
            bot, chat_id, b_msg, is_group=True
        )

        if status == 200:
            success += 1
        elif status == 400 and reason == "Left":
            left += 1
            if hasattr(_db, "disable_chat"):
                await _db.disable_chat(chat_id, "Left Group")
        else:
            failed += 1

        done += 1
        if done % 20 == 0:
            try:
                await status_msg.edit_text(
                    f"🏘️ **Group Broadcast Progress**\n\n"
                    f"💬 Total Chats: {total_chats}\n"
                    f"✅ Sent: {success}\n"
                    f"🚷 Bot Removed: {left}\n"
                    f"⚠️ Failed: {failed}\n"
                    f"📦 Completed: {done}/{total_chats}"
                )
            except FloodWait as e:
                await asyncio.sleep(e.value)
            except Exception:
                pass
        await asyncio.sleep(0.8)

    time_taken = datetime.timedelta(seconds=int(time.time() - start_time))
    await status_msg.edit_text(
        f"✅ **Group Broadcast Completed!**\n\n"
        f"🕒 Duration: `{time_taken}`\n"
        f"💬 Total Chats: {total_chats}\n"
        f"✅ Successful: {success}\n"
        f"🚷 Bot Removed: {left}\n"
        f"⚠️ Failed: {failed}\n\n"
        f"⏳ *Messages will be automatically deleted in exactly 24 hours.*"
    )
