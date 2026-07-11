import asyncio
import logging

from pyrogram import Client, enums, filters
from pyrogram.errors import UserNotParticipant
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

import info  # Used to dynamically manage FSub states
from database.join_reqs import JoinReqs

db = JoinReqs()
logger = logging.getLogger(__name__)

# Initialize runtime state for FSub if it doesn't exist in info.py
if not hasattr(info, "IS_FSUB_ENABLED"):
    info.IS_FSUB_ENABLED = True

# Cache for invite links to prevent API rate limits (FloodWait)
INVITE_LINKS = {}


async def get_invite_link(bot: Client, chat_id: int | str) -> str:
    """Helper to fetch and cache invite links properly."""
    if not chat_id:
        return ""

    chat_id = str(chat_id)
    if chat_id in INVITE_LINKS:
        return INVITE_LINKS[chat_id]

    # Handle public channels
    if chat_id.startswith("@") or not chat_id.startswith("-100"):
        link = f"https://t.me/{chat_id.replace('@', '')}"
        INVITE_LINKS[chat_id] = link
        return link

    # Handle private channels
    try:
        chat = await bot.get_chat(int(chat_id))
        link = (
            chat.invite_link
            or (await bot.create_chat_invite_link(int(chat_id))).invite_link
        )
        INVITE_LINKS[chat_id] = link
        return link
    except Exception as e:
        logger.error(f"Failed to fetch invite link for {chat_id}: {e}")
        return ""


# ============================================================
# 🧠 Runtime ForceSub Checker
# ============================================================
async def ForceSub(
    bot: Client, message: Message, file_id: str = None, mode: str = None
) -> bool:
    """Checks if user is subscribed to AUTH_CHANNEL or REQ_CHANNEL."""
    user = message.from_user

    # Bypass if admin, or if FSub is globally disabled
    if not user or user.id in info.ADMINS or not getattr(info, "IS_FSUB_ENABLED", True):
        return True

    # No channels configured
    if not info.AUTH_CHANNEL and not info.REQ_CHANNEL:
        return True

    try:
        not_joined_buttons = []
        is_participant = False

        # 1. Check AUTH_CHANNEL
        if info.AUTH_CHANNEL:
            try:
                member = await bot.get_chat_member(int(info.AUTH_CHANNEL), user.id)
                if member.status in [
                    enums.ChatMemberStatus.MEMBER,
                    enums.ChatMemberStatus.ADMINISTRATOR,
                    enums.ChatMemberStatus.OWNER,
                ]:
                    is_participant = True
            except UserNotParticipant:
                link = await get_invite_link(bot, info.AUTH_CHANNEL)
                if link:
                    not_joined_buttons.append(
                        [InlineKeyboardButton("🔐 Join Main Channel", url=link)]
                    )
            except Exception as e:
                logger.error(f"AUTH_CHANNEL FSub check error: {e}")

        # 2. Check REQ_CHANNEL
        if info.REQ_CHANNEL and not is_participant:
            try:
                member = await bot.get_chat_member(int(info.REQ_CHANNEL), user.id)
                if member.status in [
                    enums.ChatMemberStatus.MEMBER,
                    enums.ChatMemberStatus.ADMINISTRATOR,
                    enums.ChatMemberStatus.OWNER,
                ]:
                    is_participant = True
            except UserNotParticipant:
                link = await get_invite_link(bot, info.REQ_CHANNEL)
                if link:
                    not_joined_buttons.append(
                        [InlineKeyboardButton("📨 Join Request Channel", url=link)]
                    )
            except Exception as e:
                logger.error(f"REQ_CHANNEL FSub check error: {e}")

        # Passed checks
        if is_participant or not not_joined_buttons:
            return True

        # Send Prompt
        not_joined_buttons.append(
            [
                InlineKeyboardButton(
                    "✅ I've Joined", callback_data=f"refresh_fsub_{file_id or 0}"
                )
            ]
        )
        await message.reply_text(
            "🔒 **You must join our update channel(s) to use this bot.**\n\n"
            "Once you’ve joined, click **‘I’ve Joined’** to access your files.",
            reply_markup=InlineKeyboardMarkup(not_joined_buttons),
            disable_web_page_preview=True,
        )
        return False

    except Exception as e:
        logger.exception(f"[ForceSub Error] {e}")
        return True  # Fail-safe


# ============================================================
# ⚙️ (1) & (2) Enable / Disable Force Subscribe
# ============================================================
@Client.on_message(filters.command("enablefsub") & filters.user(info.ADMINS))
async def enable_fsub(bot: Client, message: Message):
    info.IS_FSUB_ENABLED = True
    await message.reply_text("✅ **Force Subscribe has been ENABLED.**")


@Client.on_message(filters.command("disablefsub") & filters.user(info.ADMINS))
async def disable_fsub(bot: Client, message: Message):
    info.IS_FSUB_ENABLED = False
    await message.reply_text("❌ **Force Subscribe has been DISABLED.**")


# ============================================================
# 🔍 (3) Check ForceSub Status
# ============================================================
@Client.on_message(filters.command("fsub") & filters.user(info.ADMINS))
async def fsub_status(bot: Client, message: Message):
    status = (
        "🟢 **ENABLED**"
        if getattr(info, "IS_FSUB_ENABLED", True)
        else "🔴 **DISABLED**"
    )
    text = f"🔐 **Force Subscription Status:** {status}\n\n"

    if not info.AUTH_CHANNEL and not info.REQ_CHANNEL:
        text += "⚠️ No channels are currently configured."
        return await message.reply_text(text)

    if info.AUTH_CHANNEL:
        try:
            chat = await bot.get_chat(int(info.AUTH_CHANNEL))
            text += (
                f"📢 **Main FSub Channel:** {chat.title}\nID: <code>{chat.id}</code>\n"
            )
        except Exception:
            text += f"📢 **Main FSub Channel:** ID <code>{info.AUTH_CHANNEL}</code> (Bot not admin)\n"

    if info.REQ_CHANNEL:
        try:
            chat = await bot.get_chat(int(info.REQ_CHANNEL))
            text += f"\n📨 **Request FSub Channel:** {chat.title}\nID: <code>{chat.id}</code>\n"
        except Exception:
            text += f"\n📨 **Request FSub Channel:** ID <code>{info.REQ_CHANNEL}</code> (Bot not admin)\n"

    await message.reply_text(text)


# ============================================================
# ➕ (4) Add FSub Channel & (9) Add Request FSub Channel
# ============================================================
@Client.on_message(filters.command("addfsub") & filters.user(info.ADMINS))
async def add_fsub(bot: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text("⚙️ Usage: <code>/addfsub [channel_id]</code>")
    try:
        info.AUTH_CHANNEL = int(message.command[1])
        await message.reply_text(
            f"✅ Main ForceSub channel updated to <code>{info.AUTH_CHANNEL}</code>."
        )
    except ValueError:
        await message.reply_text(
            "❌ Channel ID must be an integer (e.g., -100123456789)."
        )


@Client.on_message(filters.command("addfsubreq") & filters.user(info.ADMINS))
async def add_fsub_req(bot: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text(
            "⚙️ Usage: <code>/addfsubreq [channel_id]</code>"
        )
    try:
        info.REQ_CHANNEL = int(message.command[1])
        await message.reply_text(
            f"✅ Request ForceSub channel updated to <code>{info.REQ_CHANNEL}</code>."
        )
    except ValueError:
        await message.reply_text("❌ Channel ID must be an integer.")


# ============================================================
# ➖ (5), (10), (11) Remove FSub Channels
# ============================================================
@Client.on_message(filters.command("remfsub") & filters.user(info.ADMINS))
async def rem_fsub(bot: Client, message: Message):
    info.AUTH_CHANNEL = None
    await message.reply_text("🗑️ **Main ForceSub channel removed.**")


@Client.on_message(filters.command("remfsubreq") & filters.user(info.ADMINS))
async def rem_fsub_req(bot: Client, message: Message):
    info.REQ_CHANNEL = None
    await message.reply_text("🗑️ **Request ForceSub channel removed.**")


@Client.on_message(filters.command("remallfsub") & filters.user(info.ADMINS))
async def rem_all_fsub(bot: Client, message: Message):
    info.AUTH_CHANNEL = None
    info.REQ_CHANNEL = None
    await message.reply_text(
        "🗑️ **All ForceSub channels (Main & Request) have been removed.**"
    )


# ============================================================
# 📄 (6) Show FSub Channel Details (Links)
# ============================================================
@Client.on_message(filters.command("get_fsub") & filters.user(info.ADMINS))
async def get_fsub(bot: Client, message: Message):
    if not info.AUTH_CHANNEL and not info.REQ_CHANNEL:
        return await message.reply_text("❌ No ForceSub channels configured.")

    text = "🔗 **Active ForceSub Links:**\n\n"
    if info.AUTH_CHANNEL:
        link = await get_invite_link(bot, info.AUTH_CHANNEL)
        text += f"📢 Main Channel: {link}\n"
    if info.REQ_CHANNEL:
        link = await get_invite_link(bot, info.REQ_CHANNEL)
        text += f"📨 Request Channel: {link}\n"

    await message.reply_text(text, disable_web_page_preview=True)


# ============================================================
# 📊 (7) Show Total Requests & (8) Clear Requests
# ============================================================
@Client.on_message(filters.command("ttreq") & filters.user(info.ADMINS))
async def total_requests(bot: Client, message: Message):
    try:
        total = await db.total_requests()
        await message.reply_text(f"📨 **Total Join Requests:** <code>{total}</code>")
    except Exception as e:
        await message.reply_text(
            f"⚠️ Failed to fetch join requests.\nError: <code>{e}</code>"
        )


@Client.on_message(filters.command("clreq") & filters.user(info.ADMINS))
async def clear_requests(bot: Client, message: Message):
    try:
        confirm = await message.reply_text(
            "⚠️ Are you sure? This will delete all join requests. Reply with 'y' to confirm."
        )
        resp = await bot.listen(message.chat.id, timeout=30)

        if resp.text.lower() == "y":
            await db.clear_all()
            await message.reply_text("✅ All join requests cleared successfully.")
        else:
            await message.reply_text("❌ Cancelled.")
    except asyncio.TimeoutError:
        await message.reply_text("⌛ Timeout: Operation cancelled.")
    except Exception as e:
        await message.reply_text(
            f"⚠️ Error clearing requests.\nError: <code>{e}</code>"
        )
