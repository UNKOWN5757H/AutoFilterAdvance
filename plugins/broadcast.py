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

DELETE_DELAY = 72 * 3600


async def auto_delete_message(bot: Client, chat_id: int, message_id: int, delay: int):
    await asyncio.sleep(delay)
    try:
        await bot.delete_messages(chat_id=chat_id, message_ids=message_id)
    except Exception:
        pass


async def send_and_schedule_delete(bot: Client, chat_id: int, message):
    try:
        sent_msg = await message.copy(chat_id=chat_id)
        asyncio.create_task(
            auto_delete_message(bot, chat_id, sent_msg.id, DELETE_DELAY)
        )
        return 200
    except FloodWait as e:
        await asyncio.sleep(e.value + 1)
        return await send_and_schedule_delete(bot, chat_id, message)
    except (UserIsBlocked, InputUserDeactivated, PeerIdInvalid, ChatWriteForbidden):
        return 400
    except Exception:
        return 500


@Client.on_message(filters.command("broadcast") & filters.user(ADMINS) & filters.reply)
async def user_broadcast(bot: Client, message):
    users = await db.get_all_users()
    if not users:
        return await message.reply_text("⚠️ **No users found.**")

    status_msg = await message.reply_text(
        f"🚀 **Broadcasting to {len(users)} users...**"
    )
    success, blocked, failed = 0, 0, 0

    for idx, user in enumerate(users, 1):
        status = await send_and_schedule_delete(
            bot, int(user["id"]), message.reply_to_message
        )
        if status == 200:
            success += 1
        elif status == 400:
            blocked += 1
            await db.delete_user(int(user["id"]))
        else:
            failed += 1

        if idx % 20 == 0:
            try:
                await status_msg.edit_text(
                    f"📢 **Progress:** {idx}/{len(users)}\n✅ Sent: {success} | 🚫 Blocked: {blocked}"
                )
            except FloodWait as e:
                await asyncio.sleep(e.value)
            except Exception:
                pass
        await asyncio.sleep(0.5)

    await status_msg.edit_text(
        f"✅ **Broadcast Completed!**\n✅ Sent: {success}\n🚫 Blocked/Deleted: {blocked}\n⚠️ Failed: {failed}\n⏳ *Messages will delete in 72h.*"
    )


@Client.on_message(
    filters.command("group_broadcast") & filters.user(ADMINS) & filters.reply
)
async def group_broadcast(bot: Client, message):
    chats = await db.get_all_chats()
    if not chats:
        return await message.reply_text("⚠️ **No groups found.**")

    status_msg = await message.reply_text(
        f"🚀 **Broadcasting to {len(chats)} groups...**"
    )
    success, left, failed = 0, 0, 0

    for idx, chat in enumerate(chats, 1):
        status = await send_and_schedule_delete(
            bot, int(chat["id"]), message.reply_to_message
        )
        if status == 200:
            success += 1
        elif status == 400:
            left += 1
        else:
            failed += 1

        if idx % 20 == 0:
            try:
                await status_msg.edit_text(
                    f"🏘️ **Progress:** {idx}/{len(chats)}\n✅ Sent: {success} | 🚷 Removed: {left}"
                )
            except Exception:
                pass
        await asyncio.sleep(0.8)

    await status_msg.edit_text(
        f"✅ **Group Broadcast Completed!**\n✅ Sent: {success}\n🚷 Removed: {left}\n⚠️ Failed: {failed}\n⏳ *Messages will delete in 72h.*"
    )
