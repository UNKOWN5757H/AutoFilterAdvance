import asyncio

from pyrogram import Client, filters
from pyrogram.types import ChatJoinRequest

from database.join_reqs import join_reqs as db
from info import ADMINS, REQ_CHANNEL

try:
    req_chat = (
        int(REQ_CHANNEL) if str(REQ_CHANNEL).strip("-").isdigit() else REQ_CHANNEL
    )
    req_filter = filters.chat(req_chat) if req_chat else filters.chat([])
except Exception:
    req_filter = filters.chat([])


@Client.on_chat_join_request(req_filter)
async def join_reqs_handler(bot: Client, join_req: ChatJoinRequest):
    if not db.isActive():
        return
    user = join_req.from_user
    try:
        await db.add_user(
            user.id,
            user.first_name or "Unknown",
            user.username or "None",
            join_req.date,
        )
    except Exception:
        pass


@Client.on_message(
    filters.command("totalrequests") & filters.private & filters.user(ADMINS)
)
async def total_requests(bot: Client, message):
    if not db.isActive():
        return await message.reply_text("⚠️ Join request DB is inactive.")
    total = await db.total_requests()
    await message.reply_text(f"📨 **Total Join Requests:** `{total}`")


@Client.on_message(
    filters.command("purgerequests") & filters.private & filters.user(ADMINS)
)
async def purge_requests(bot: Client, message):
    if not db.isActive():
        return await message.reply_text("⚠️ Join request DB is inactive.")

    confirm_msg = await message.reply_text("⚠️ Delete ALL join requests? (y/n)")
    try:
        resp = await bot.listen(message.chat.id, timeout=30)
        if resp.text.lower() == "y":
            count = await db.clear_all()
            await message.reply_text(
                f"✅ All join requests purged (`{count}` deleted)."
            )
        else:
            await message.reply_text("❌ Cancelled.")
    except asyncio.TimeoutError:
        await confirm_msg.edit("⌛ Timeout: Operation cancelled.")
