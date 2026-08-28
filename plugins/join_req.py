import asyncio
from logging import ERROR, getLogger

from pyrogram import Client, filters
from pyrogram.types import ChatJoinRequest

from database.join_reqs import join_reqs as _db
from info import ADMINS, REQ_CHANNEL

logger = getLogger(__name__)
logger.setLevel(ERROR)

try:
    req_chat = (
        int(REQ_CHANNEL) if str(REQ_CHANNEL).strip("-").isdigit() else REQ_CHANNEL
    )
    req_filter = filters.chat(req_chat) if req_chat else filters.chat([])
except Exception:
    req_filter = filters.chat([])


@Client.on_chat_join_request(req_filter)
async def join_reqs_handler(bot: Client, join_req: ChatJoinRequest):
    if not _db.isActive():
        return
    user = join_req.from_user
    try:
        await _db.add_user(
            user_id=user.id,
            first_name=user.first_name or "Unknown",
            username=user.username or "None",
            date=join_req.date,
        )
    except Exception as e:
        logger.error(f"Failed to log join request for {user.id}: {e}")


@Client.on_message(
    filters.command("totalrequests") & filters.private & filters.user(ADMINS)
)
async def total_requests(bot: Client, message):
    if not _db.isActive():
        return await message.reply_text(
            "⚠️ Join request tracking is not active (DB inactive)."
        )
    try:
        total = await _db.total_requests()
        await message.reply_text(f"📨 **Total Join Requests:** <code>{total}</code>")
    except Exception as e:
        logger.error(f"Error fetching join requests: {e}")
        await message.reply_text(f"⚠️ Error: <code>{e}</code>")


@Client.on_message(
    filters.command("purgerequests") & filters.private & filters.user(ADMINS)
)
async def purge_requests(bot: Client, message):
    if not _db.isActive():
        return await message.reply_text(
            "⚠️ Join request tracking is not active (DB inactive)."
        )

    confirm_msg = await message.reply_text(
        "⚠️ Are you sure you want to delete all join requests? (y/n)"
    )
    try:
        resp = await bot.listen(message.chat.id, timeout=30)
        if resp.text.lower() == "y":
            count = await _db.clear_all()
            await message.reply_text(
                f"✅ All join requests purged successfully. (<code>{count}</code> deleted)"
            )
        else:
            await message.reply_text("❌ Operation cancelled.")
    except asyncio.TimeoutError:
        await message.reply_text("⌛ Timeout: No response, operation cancelled.")
    except Exception as e:
        logger.error(f"Error clearing join requests: {e}")
        await message.reply_text(f"⚠️ Error clearing requests: <code>{e}</code>")
