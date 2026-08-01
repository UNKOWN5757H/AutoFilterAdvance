import asyncio
from logging import getLogger

from pyrogram import Client, filters
from pyrogram.types import ChatJoinRequest

from database.join_reqs import join_reqs as db
from info import ADMINS, REQ_CHANNEL

logger = getLogger(__name__)

# Safely handle REQ_CHANNEL parsing for the Pyrogram filter.
try:
    req_chat = (
        int(REQ_CHANNEL) if str(REQ_CHANNEL).strip("-").isdigit() else REQ_CHANNEL
    )
    req_filter = filters.chat(req_chat) if req_chat else filters.chat([])
except Exception:
    req_filter = filters.chat([])


# ============================================================
# 📥 HANDLE NEW JOIN REQUESTS
# ============================================================
@Client.on_chat_join_request(req_filter)
async def join_reqs_handler(bot: Client, join_req: ChatJoinRequest):
    """
    Triggered whenever a user requests to join the ForceSub channel.
    Stores the request in MongoDB safely.
    """
    if not db.isActive():
        logger.warning("⚠️ JoinReqs DB inactive — skipping join request log.")
        return

    user = join_req.from_user
    try:
        await db.add_user(
            user_id=user.id,
            first_name=user.first_name or "Unknown",
            username=user.username or "None",
            date=join_req.date,
        )
        logger.info(f"📥 Stored join request: {user.first_name} ({user.id})")
    except Exception as e:
        logger.exception(f"❌ Failed to log join request for {user.id}: {e}")


# ============================================================
# 📊 /totalrequests — Show total join requests count
# ============================================================
@Client.on_message(
    filters.command("totalrequests") & filters.private & filters.user(ADMINS)
)
async def total_requests(bot: Client, message):
    """Show total stored join requests."""
    if not db.isActive():
        return await message.reply_text(
            "⚠️ Join request tracking is not active (DB inactive)."
        )

    try:
        total = await db.total_requests()
        await message.reply_text(f"📨 **Total Join Requests:** <code>{total}</code>")
    except Exception as e:
        logger.exception(f"❌ Error fetching join requests: {e}")
        await message.reply_text(f"⚠️ Error: <code>{e}</code>")


# ============================================================
# 🧹 /purgerequests — Delete all join requests
# ============================================================
@Client.on_message(
    filters.command("purgerequests") & filters.private & filters.user(ADMINS)
)
async def purge_requests(bot: Client, message):
    """Deletes all join request records."""
    if not db.isActive():
        return await message.reply_text(
            "⚠️ Join request tracking is not active (DB inactive)."
        )

    confirm_msg = await message.reply_text(
        "⚠️ Are you sure you want to delete all join requests? (y/n)"
    )

    try:
        resp = await bot.listen(message.chat.id, timeout=30)
        if resp.text.lower() == "y":
            count = await db.clear_all()
            await message.reply_text(
                f"✅ All join requests purged successfully. (<code>{count}</code> deleted)"
            )
        else:
            await message.reply_text("❌ Operation cancelled.")
    except asyncio.TimeoutError:
        await message.reply_text("⌛ Timeout: No response, operation cancelled.")
    except Exception as e:
        logger.exception(f"❌ Error clearing join requests: {e}")
        await message.reply_text(f"⚠️ Error clearing requests: <code>{e}</code>")
