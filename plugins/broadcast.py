import asyncio
import datetime
import time
from pyrogram import Client, filters
from pyrogram.errors import FloodWait, InputUserDeactivated, UserIsBlocked, PeerIdInvalid, ChatWriteForbidden
from database.users_chats_db import db
from info import ADMINS
from utils import broadcast_messages


# ============================================================
# USER BROADCAST
# ============================================================
@Client.on_message(filters.command("broadcast") & filters.user(ADMINS) & filters.reply)
async def user_broadcast(bot: Client, message):
    """
    Broadcast a replied message to all private users.
    Usage: Reply to a message with /broadcast
    """
    b_msg = message.reply_to_message
    if not b_msg:
        return await message.reply_text("⚠️ Reply to the message you want to broadcast. ")

    users = await db.get_all_users()
    total_users = len(users)

    if total_users == 0:
        return await message.reply_text("⚠️ No users found in the database.")

    status_msg = await message.reply_text(f"🚀 Broadcasting to **{total_users} users**....")
    start_time = time.time()

    done = success = blocked = deleted = failed = 0

    for user in users:
        try:
            pti, reason = await broadcast_messages(int(user["id"]), b_msg)

            if pti:
                success += 1
            else:
                if reason == "Blocked":
                    blocked += 1
                elif reason == "Deleted":
                    deleted += 1
                else:
                    failed += 1

        except FloodWait as e:
            await asyncio.sleep(e.value)
        except Exception:
            failed += 1

        done += 1
        if done % 20 == 0:
            await status_msg.edit_text(
                f"📢 **Broadcast Progress**\n\n"
                f"👥 Total Users: {total_users}\n"
                f"✅ Sent: {success}\n"
                f"🚫 Blocked: {blocked}\n"
                f"🗑️ Deleted: {deleted}\n"
                f"⚠️ Failed: {failed}\n"
                f"📦 Completed: {done}/{total_users}"
            )

        await asyncio.sleep(0.5)

    time_taken = datetime.timedelta(seconds=int(time.time() - start_time))
    await status_msg.edit_text(
        f"✅ **User Broadcast Completed!**\n\n"
        f"🕒 Duration: `{time_taken}`\n"
        f"👥 Total Users: {total_users}\n"
        f"✅ Successful: {success}\n"
        f"🚫 Blocked: {blocked}\n"
        f"🗑️ Deleted: {deleted}\n"
        f"⚠️ Failed: {failed}"
    )


# ============================================================
# GROUP BROADCAST
# ============================================================
@Client.on_message(filters.command("group_broadcast") & filters.user(ADMINS) & filters.reply)
async def group_broadcast(bot: Client, message):
    """
    Broadcast a replied message to all groups/channels.
    Usage: Reply to a message with /group_broadcast
    """
    b_msg = message.reply_to_message
    if not b_msg:
        return await message.reply_text("⚠️ Reply to the message you want to broadcast.")

    chats = await db.get_all_chats()
    total_chats = len(chats)

    if total_chats == 0:
        return await message.reply_text("⚠️ No groups found in the database.")

    status_msg = await message.reply_text(f"🚀 Broadcasting to **{total_chats} groups/chats**...")
    start_time = time.time()

    done = success = left = failed = 0

    for chat in chats:
        try:
            await b_msg.copy(chat_id=int(chat["id"]))
            success += 1

        except FloodWait as e:
            await asyncio.sleep(e.value)
        except ChatWriteForbidden:
            left += 1
            # Remove chat since bot is no longer a member
            await db.enable_chat(int(chat["id"]))
        except Exception:
            failed += 1

        done += 1
        if done % 20 == 0:
            await status_msg.edit_text(
                f"🏘️ **Group Broadcast Progress**\n\n"
                f"💬 Total Chats: {total_chats}\n"
                f"✅ Sent: {success}\n"
                f"🚷 Left: {left}\n"
                f"⚠️ Failed: {failed}\n"
                f"📦 Completed: {done}/{total_chats}"
            )

        await asyncio.sleep(0.8)

    time_taken = datetime.timedelta(seconds=int(time.time() - start_time))
    await status_msg.edit_text(
        f"✅ **Group Broadcast Completed!**\n\n"
        f"🕒 Duration: `{time_taken}`\n"
        f"💬 Total Chats: {total_chats}\n"
        f"✅ Successful: {success}\n"
        f"🚷 Left: {left}\n"
        f"⚠️ Failed: {failed}"
    )
