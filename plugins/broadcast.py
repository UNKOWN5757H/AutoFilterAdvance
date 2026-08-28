import asyncio
import datetime
import time

from pyrogram import Client, filters
from pyrogram.errors import ChatWriteForbidden, FloodWait, InputUserDeactivated, PeerIdInvalid, UserIsBlocked

from database.users_chats_db import db
from info import ADMINS

DELETE_DELAY = 72 * 3600

async def auto_delete_message(bot: Client, chat_id: int, message_id: int, delay: int):
    await asyncio.sleep(delay)
    try: await bot.delete_messages(chat_id=chat_id, message_ids=message_id)
    except Exception: pass

async def send_and_schedule_delete(bot: Client, chat_id: int, message, is_group: bool = False):
    try:
        sent_msg = await message.copy(chat_id=chat_id)
        asyncio.create_task(auto_delete_message(bot, chat_id, sent_msg.id, DELETE_DELAY))
        return 200, None
    except FloodWait as e:
        await asyncio.sleep(e.value + 1)
        return await send_and_schedule_delete(bot, chat_id, message, is_group)
    except (UserIsBlocked, InputUserDeactivated): return 400, "Blocked/Deleted"
    except PeerIdInvalid: return 400, "Invalid"
    except ChatWriteForbidden: return 400, "Left"
    except Exception: return 500, "Error"

@Client.on_message(filters.command("broadcast") & filters.user(ADMINS) & filters.reply)
async def user_broadcast(bot: Client, message):
    b_msg = message.reply_to_message
    if not b_msg: return await message.reply_text("⚠️ **Reply to the message you want to broadcast.**")

    users = await db.get_all_users()
    total_users = len(users)

    if total_users == 0: return await message.reply_text("⚠️ **No users found in the database.**")

    status_msg = await message.reply_text(f"🚀 **Broadcasting to {total_users} users...**")
    start_time = time.time()
    done = success = blocked = failed = 0

    for user in users:
        user_id = int(user["id"])
        status, _ = await send_and_schedule_delete(bot, user_id, b_msg, is_group=False)

        if status == 200: success += 1
        elif status == 400:
            blocked += 1
            await db.delete_user(user_id)
        else: failed += 1

        done += 1
        if done % 20 == 0:
            try:
                await status_msg.edit_text(f"📢 **Broadcast Progress**\n\n👥 Total Users: {total_users}\n✅ Sent: {success}\n🚫 Blocked/Deleted: {blocked}\n⚠️ Failed: {failed}\n📦 Completed: {done}/{total_users}")
            except FloodWait as e: await asyncio.sleep(e.value)
            except Exception: pass
        await asyncio.sleep(0.5)

    time_taken = datetime.timedelta(seconds=int(time.time() - start_time))
    await status_msg.edit_text(f"✅ **User Broadcast Completed!**\n\n🕒 Duration: `{time_taken}`\n👥 Total Users: {total_users}\n✅ Successful: {success}\n🚫 Blocked/Deleted: {blocked}\n⚠️ Failed: {failed}\n\n⏳ *Messages will be automatically deleted in 72 hours.*")

@Client.on_message(filters.command("group_broadcast") & filters.user(ADMINS) & filters.reply)
async def group_broadcast(bot: Client, message):
    b_msg = message.reply_to_message
    if not b_msg: return await message.reply_text("⚠️ **Reply to the message you want to broadcast.**")

    chats = await db.get_all_chats()
    total_chats = len(chats)

    if total_chats == 0: return await message.reply_text("⚠️ **No groups found in the database.**")

    status_msg = await message.reply_text(f"🚀 **Broadcasting to {total_chats} groups/chats...**")
    start_time = time.time()
    done = success = left = failed = 0

    for chat in chats:
        chat_id = int(chat["id"])
        status, reason = await send_and_schedule_delete(bot, chat_id, b_msg, is_group=True)

        if status == 200: success += 1
        elif status == 400 and reason == "Left":
            left += 1
            if hasattr(db, "disable_chat"): await db.disable_chat(chat_id, "Left Group")
        else: failed += 1

        done += 1
        if done % 20 == 0:
            try:
                await status_msg.edit_text(f"🏘️ **Group Broadcast Progress**\n\n💬 Total Chats: {total_chats}\n✅ Sent: {success}\n🚷 Bot Removed: {left}\n⚠️ Failed: {failed}\n📦 Completed: {done}/{total_chats}")
            except FloodWait as e: await asyncio.sleep(e.value)
            except Exception: pass
        await asyncio.sleep(0.8)

    time_taken = datetime.timedelta(seconds=int(time.time() - start_time))
    await status_msg.edit_text(f"✅ **Group Broadcast Completed!**\n\n🕒 Duration: `{time_taken}`\n💬 Total Chats: {total_chats}\n✅ Successful: {success}\n🚷 Bot Removed: {left}\n⚠️ Failed: {failed}\n\n⏳ *Messages will be automatically deleted in 72 hours.*")
