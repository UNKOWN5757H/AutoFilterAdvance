import asyncio
import datetime
import time

from pyrogram import Client, filters
from pyrogram.errors import (
    ChatWriteForbidden,
    FloodWait,
    InputUserDeactivated,
    PeerIdInvalid,
    UserIsBlocked,
)

from database.users_chats_db import db
from info import ADMINS

# 72 hours in seconds (72 * 60 * 60)
DELETE_DELAY = 72 * 3600


async def auto_delete_message(bot: Client, chat_id: int, message_id: int, delay: int):
    """
    Sleeps for the specified delay (72 hours) in the background,
    then attempts to delete the broadcasted message.
    Note: If the bot is restarted, pending deletions in memory will be lost.
    """
    await asyncio.sleep(delay)
    try:
        await bot.delete_messages(chat_id=chat_id, message_ids=message_id)
    except Exception:
        # Ignore errors if the message is already deleted or bot lacks permissions
        pass


async def send_and_schedule_delete(
    bot: Client, chat_id: int, message, is_group: bool = False
):
    """
    Sends the message and schedules its deletion.
    Returns (status_code, reason).
    """
    try:
        # Copy the message to the target chat
        sent_msg = await message.copy(chat_id=chat_id)

        # Schedule the auto-deletion in the background
        asyncio.create_task(
            auto_delete_message(bot, chat_id, sent_msg.id, DELETE_DELAY)
        )

        return 200, None

    except FloodWait as e:
        # Sleep for the required time + 1 second buffer, then retry
        await asyncio.sleep(e.value + 1)
        return await send_and_schedule_delete(bot, chat_id, message, is_group)

    except (UserIsBlocked, InputUserDeactivated):
        return 400, "Blocked/Deleted"

    except PeerIdInvalid:
        return 400, "Invalid"

    except ChatWriteForbidden:
        return 400, "Left"

    except Exception as e:
        return 500, "Error"


# ============================================================
# USER BROADCAST
# ============================================================
@Client.on_message(filters.command("broadcast") & filters.user(ADMINS) & filters.reply)
async def user_broadcast(bot: Client, message):
    """
    Broadcast a replied message to all private users and auto-delete after 72 hrs.
    Usage: Reply to a message with /broadcast
    """
    b_msg = message.reply_to_message
    if not b_msg:
        return await message.reply_text(
            "⚠️ **Reply to the message you want to broadcast.**"
        )

    users = await db.get_all_users()
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

        status, reason = await send_and_schedule_delete(
            bot, user_id, b_msg, is_group=False
        )

        if status == 200:
            success += 1
        elif status == 400:
            blocked += 1
            # Optional: You can add await db.delete_user(user_id) here to clean up your DB
        else:
            failed += 1

        done += 1

        # Update progress every 20 messages
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

        await asyncio.sleep(0.5)  # Prevent Telegram flood limits

    time_taken = datetime.timedelta(seconds=int(time.time() - start_time))
    await status_msg.edit_text(
        f"✅ **User Broadcast Completed!**\n\n"
        f"🕒 Duration: `{time_taken}`\n"
        f"👥 Total Users: {total_users}\n"
        f"✅ Successful: {success}\n"
        f"🚫 Blocked/Deleted: {blocked}\n"
        f"⚠️ Failed: {failed}\n\n"
        f"⏳ *Messages will be automatically deleted in 72 hours.*"
    )


# ============================================================
# GROUP BROADCAST
# ============================================================
@Client.on_message(
    filters.command("group_broadcast") & filters.user(ADMINS) & filters.reply
)
async def group_broadcast(bot: Client, message):
    """
    Broadcast a replied message to all groups/channels and auto-delete after 72 hrs.
    Usage: Reply to a message with /group_broadcast
    """
    b_msg = message.reply_to_message
    if not b_msg:
        return await message.reply_text(
            "⚠️ **Reply to the message you want to broadcast.**"
        )

    chats = await db.get_all_chats()
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
            # Assuming your DB has a delete_chat method. If it's literally called
            # disable_chat in your DB script, change this to await db.disable_chat(chat_id)
            if hasattr(db, "delete_chat"):
                await db.delete_chat(chat_id)
        else:
            failed += 1

        done += 1

        # Update progress every 20 messages
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

        await asyncio.sleep(0.8)  # Group limits are stricter, higher sleep interval

    time_taken = datetime.timedelta(seconds=int(time.time() - start_time))
    await status_msg.edit_text(
        f"✅ **Group Broadcast Completed!**\n\n"
        f"🕒 Duration: `{time_taken}`\n"
        f"💬 Total Chats: {total_chats}\n"
        f"✅ Successful: {success}\n"
        f"🚷 Bot Removed: {left}\n"
        f"⚠️ Failed: {failed}\n\n"
        f"⏳ *Messages will be automatically deleted in 72 hours.*"
    )
