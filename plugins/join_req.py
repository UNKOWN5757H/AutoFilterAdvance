import asyncio
from logging import ERROR, getLogger

from pyrogram import Client, filters
from pyrogram.types import ChatJoinRequest, Message

import info

# ⚡ Aliased DB to prevent Pyrogram scanner crash
from database.join_reqs import join_reqs as _db

logger = getLogger(__name__)
logger.setLevel(ERROR)


# ============================================================
# 👑 FOOLPROOF ADMIN & LISTENER ENGINE
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


admin_filter = filters.create(
    lambda _, __, msg: bool(msg.from_user and msg.from_user.id in get_admin_list())
)

_WAITING_REQUESTS = {}


@Client.on_message(admin_filter, group=-13)
async def custom_listener(client: Client, message: Message):
    key = (message.chat.id, message.from_user.id)
    if key in _WAITING_REQUESTS:
        future = _WAITING_REQUESTS.pop(key)
        if not future.done():
            future.set_result(message)
        message.stop_propagation()


async def native_listen(
    client: Client, chat_id: int, user_id: int, timeout: int = 120
) -> Message:
    loop = asyncio.get_running_loop()
    future = loop.create_future()
    _WAITING_REQUESTS[(chat_id, user_id)] = future
    try:
        return await asyncio.wait_for(future, timeout=timeout)
    except asyncio.TimeoutError:
        _WAITING_REQUESTS.pop((chat_id, user_id), None)
        raise asyncio.TimeoutError


# ============================================================
# 🚪 JOIN REQUEST CATCHER
# ============================================================
@Client.on_chat_join_request()
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


# ============================================================
# 📊 JOIN REQUEST COMMANDS
# ============================================================
@Client.on_message(filters.command("totalrequests") & filters.private & admin_filter)
async def total_requests(bot: Client, message: Message):
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


@Client.on_message(filters.command("purgerequests") & filters.private & admin_filter)
async def purge_requests(bot: Client, message: Message):
    if not _db.isActive():
        return await message.reply_text(
            "⚠️ Join request tracking is not active (DB inactive)."
        )

    ask_msg = await message.reply_text(
        "⚠️ **Are you sure you want to delete all join requests? (y/n)**"
    )
    try:
        resp = await native_listen(
            bot, message.chat.id, message.from_user.id, timeout=60
        )

        try:
            await ask_msg.delete()
        except Exception:
            pass
        if resp:
            try:
                await resp.delete()
            except Exception:
                pass

        if not resp or not resp.text:
            return

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
