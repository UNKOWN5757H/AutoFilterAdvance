import asyncio
import logging

from pyrogram import Client, enums, filters
from pyrogram.errors import UserNotParticipant
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

import info
from database.join_reqs import JoinReqs

# Database for Join Requests
db = JoinReqs()
logger = logging.getLogger(__name__)

# ============================================================
# 🗄️ FSub Database & Runtime States
# ============================================================
if not hasattr(info, "IS_FSUB_ENABLED"):
    info.IS_FSUB_ENABLED = True

if not hasattr(info, "FSUB_TARGETS"):
    info.FSUB_TARGETS = {}

# Simple FSubDB to track users who passed FSub
class FSubDB:
    def __init__(self):
        self.db_url = getattr(info, "DATABASE_URI", None)
        if self.db_url:
            try:
                from motor.motor_asyncio import AsyncIOMotorClient
                self.client = AsyncIOMotorClient(self.db_url)
                self.database = self.client["BotDatabase"]
                self.col = self.database["fsub_users"]
                self.use_mongo = True
            except ImportError:
                logger.warning("motor is not installed! Using memory for FSub users.")
                self.use_mongo = False
                self.mock_db = set()
        else:
            self.use_mongo = False
            self.mock_db = set()

    async def add_user(self, user_id: int):
        if self.use_mongo:
            await self.col.update_one({"_id": user_id}, {"$set": {"_id": user_id}}, upsert=True)
        else:
            self.mock_db.add(user_id)

    async def get_count(self) -> int:
        if self.use_mongo:
            return await self.col.count_documents({})
        return len(self.mock_db)

    async def clear_all(self):
        if self.use_mongo:
            await self.col.delete_many({})
        else:
            self.mock_db.clear()

fsub_db = FSubDB()

# Cache for invite links to prevent API rate limits (FloodWait)
INVITE_LINKS = {}


async def get_invite_link(bot: Client, chat_id: int | str) -> str:
    """Helper to fetch and cache invite links properly."""
    if not chat_id:
        return ""

    chat_id_str = str(chat_id)
    
    # Check if a custom target was set via /updatefsubtarget
    if chat_id_str in info.FSUB_TARGETS:
        return info.FSUB_TARGETS[chat_id_str]

    if chat_id_str in INVITE_LINKS:
        return INVITE_LINKS[chat_id_str]

    # Handle public channels
    if chat_id_str.startswith("@") or not chat_id_str.startswith("-100"):
        link = f"https://t.me/{chat_id_str.replace('@', '')}"
        INVITE_LINKS[chat_id_str] = link
        return link

    # Handle private channels
    try:
        chat = await bot.get_chat(int(chat_id))
        link = chat.invite_link or (await bot.create_chat_invite_link(int(chat_id))).invite_link
        INVITE_LINKS[chat_id_str] = link
        return link
    except Exception as e:
        logger.error(f"Failed to fetch invite link for {chat_id}: {e}")
        return ""


# ============================================================
# 🧠 Runtime ForceSub Checker
# ============================================================
async def check_user_in_channel(bot: Client, channel_id: int, user_id: int) -> bool:
    """Checks if a user is in a specific channel."""
    try:
        member = await bot.get_chat_member(channel_id, user_id)
        return member.status in [
            enums.ChatMemberStatus.MEMBER,
            enums.ChatMemberStatus.ADMINISTRATOR,
            enums.ChatMemberStatus.OWNER,
        ]
    except UserNotParticipant:
        return False
    except Exception as e:
        logger.error(f"FSub check error for channel {channel_id}: {e}")
        return False


async def ForceSub(bot: Client, message: Message, file_id: str = None, mode: str = None) -> bool:
    """Checks if user is subscribed to AUTH_CHANNEL and REQ_CHANNEL."""
    user = message.from_user

    # Bypass if admin, or if FSub is globally disabled
    if not user or user.id in info.ADMINS or not getattr(info, "IS_FSUB_ENABLED", True):
        return True

    # No channels configured
    if not info.AUTH_CHANNEL and not info.REQ_CHANNEL:
        return True

    try:
        not_joined_buttons = []

        # 1. Check AUTH_CHANNEL
        if info.AUTH_CHANNEL:
            is_in_auth = await check_user_in_channel(bot, int(info.AUTH_CHANNEL), user.id)
            if not is_in_auth:
                link = await get_invite_link(bot, info.AUTH_CHANNEL)
                if link:
                    not_joined_buttons.append([InlineKeyboardButton("🔐 Join Main Channel", url=link)])

        # 2. Check REQ_CHANNEL
        if info.REQ_CHANNEL:
            is_in_req = await check_user_in_channel(bot, int(info.REQ_CHANNEL), user.id)
            if not is_in_req:
                link = await get_invite_link(bot, info.REQ_CHANNEL)
                if link:
                    not_joined_buttons.append([InlineKeyboardButton("📨 Join Request Channel", url=link)])

        # Passed all checks
        if not not_joined_buttons:
            await fsub_db.add_user(user.id)  # Log user to db on success
            return True

        # Send Prompt if missing subscriptions
        not_joined_buttons.append(
            [InlineKeyboardButton("✅ I've Joined", callback_data=f"refresh_fsub_{file_id or 0}")]
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
        return True  # Fail-safe bypass


# ============================================================
# ⚙️ Enable / Disable Force Subscribe
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
# 🎯 Update & Remove FSub Targets (NEW)
# ============================================================
@Client.on_message(filters.command("updatefsubtarget") & filters.user(info.ADMINS))
async def update_fsub_target(bot: Client, message: Message):
    if len(message.command) < 3:
        return await message.reply_text("⚙️ Usage: <code>/updatefsubtarget [channel_id] [target_link]</code>")
    
    channel_id = str(message.command[1])
    target = message.command[2]
    
    info.FSUB_TARGETS[channel_id] = target
    await message.reply_text(f"✅ FSub target for <code>{channel_id}</code> successfully updated to:\n{target}")


@Client.on_message(filters.command("rmfsubtarget") & filters.user(info.ADMINS))
async def rm_fsub_target(bot: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text("⚙️ Usage: <code>/rmfsubtarget [channel_id]</code>")
    
    channel_id = str(message.command[1])
    
    if channel_id in info.FSUB_TARGETS:
        del info.FSUB_TARGETS[channel_id]
        # Clear cached link if it exists
        if channel_id in INVITE_LINKS:
            del INVITE_LINKS[channel_id]
        await message.reply_text(f"🗑️ FSub target for <code>{channel_id}</code> has been removed.")
    else:
        await message.reply_text(f"❌ No custom target found for <code>{channel_id}</code>.")


# ============================================================
# 👥 FSub Users DB Management (NEW)
# ============================================================
@Client.on_message(filters.command("checkfsubusers") & filters.user(info.ADMINS))
async def check_fsub_users(bot: Client, message: Message):
    count = await fsub_db.get_count()
    await message.reply_text(f"👥 **Total Force Subscribed Users (DB):** <code>{count}</code>")


@Client.on_message(filters.command("clearfsubusers") & filters.user(info.ADMINS))
async def clear_fsub_users(bot: Client, message: Message):
    try:
        await message.reply_text("⚠️ Are you sure you want to clear all FSub users from the database? Reply with 'y' to confirm.")
        resp = await bot.listen(message.chat.id, timeout=30)

        if resp.text.lower() == "y":
            await fsub_db.clear_all()
            await message.reply_text("✅ All force subscribed users have been cleared from the database.")
        else:
            await message.reply_text("❌ Cancelled.")
    except asyncio.TimeoutError:
        await message.reply_text("⌛ Timeout: Operation cancelled.")
    except Exception as e:
        await message.reply_text(f"⚠️ Error clearing FSub users.\nError: <code>{e}</code>")


# ============================================================
# 🔍 Check ForceSub Status
# ============================================================
@Client.on_message(filters.command("fsub") & filters.user(info.ADMINS))
async def fsub_status(bot: Client, message: Message):
    status = "🟢 **ENABLED**" if getattr(info, "IS_FSUB_ENABLED", True) else "🔴 **DISABLED**"
    text = f"🔐 **Force Subscription Status:** {status}\n\n"

    if not info.AUTH_CHANNEL and not info.REQ_CHANNEL:
        text += "⚠️ No channels are currently configured."
        return await message.reply_text(text)

    if info.AUTH_CHANNEL:
        try:
            chat = await bot.get_chat(int(info.AUTH_CHANNEL))
            text += f"📢 **Main FSub Channel:** {chat.title}\nID: <code>{chat.id}</code>\n"
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
# ➕ Add FSub Channels
# ============================================================
@Client.on_message(filters.command("setfsub") & filters.user(info.ADMINS))
async def add_fsub(bot: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text("⚙️ Usage: <code>/setfsub [channel_id]</code>")
    try:
        info.AUTH_CHANNEL = int(message.command[1])
        await message.reply_text(f"✅ Main ForceSub channel updated to <code>{info.AUTH_CHANNEL}</code>.")
    except ValueError:
        await message.reply_text("❌ Channel ID must be an integer (e.g., -100123456789).")


@Client.on_message(filters.command("setfsubreq") & filters.user(info.ADMINS))
async def add_fsub_req(bot: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text("⚙️ Usage: <code>/setfsubreq [channel_id]</code>")
    try:
        info.REQ_CHANNEL = int(message.command[1])
        await message.reply_text(f"✅ Request ForceSub channel updated to <code>{info.REQ_CHANNEL}</code>.")
    except ValueError:
        await message.reply_text("❌ Channel ID must be an integer.")


# ============================================================
# ➖ Remove FSub Channels
# ============================================================
@Client.on_message(filters.command("rmfsub") & filters.user(info.ADMINS))
async def rem_fsub(bot: Client, message: Message):
    info.AUTH_CHANNEL = None
    await message.reply_text("🗑️ **Main ForceSub channel removed.**")


@Client.on_message(filters.command("remfsubreq") & filters.user(info.ADMINS))
async def rem_fsub_req(bot: Client, message: Message):
    info.REQ_CHANNEL = None
    await message.reply_text("🗑️ **Request ForceSub channel removed.**")


@Client.on_message(filters.command("rmallfsub") & filters.user(info.ADMINS))
async def rem_all_fsub(bot: Client, message: Message):
    info.AUTH_CHANNEL = None
    info.REQ_CHANNEL = None
    await message.reply_text("🗑️ **All ForceSub channels (Main & Request) have been removed.**")


# ============================================================
# 📄 Show FSub Channel Details (Links)
# ============================================================
@Client.on_message(filters.command("getallfsub") & filters.user(info.ADMINS))
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
# 📊 Join Requests Tracking
# ============================================================
@Client.on_message(filters.command("ttreq") & filters.user(info.ADMINS))
async def total_requests(bot: Client, message: Message):
    try:
        total = await db.total_requests()
        await message.reply_text(f"📨 **Total Join Requests:** <code>{total}</code>")
    except Exception as e:
        await message.reply_text(f"⚠️ Failed to fetch join requests.\nError: <code>{e}</code>")


@Client.on_message(filters.command("clreq") & filters.user(info.ADMINS))
async def clear_requests(bot: Client, message: Message):
    try:
        await message.reply_text("⚠️ Are you sure? This will delete all join requests. Reply with 'y' to confirm.")
        resp = await bot.listen(message.chat.id, timeout=30)

        if resp.text.lower() == "y":
            await db.clear_all()
            await message.reply_text("✅ All join requests cleared successfully.")
        else:
            await message.reply_text("❌ Cancelled.")
    except asyncio.TimeoutError:
        await message.reply_text("⌛ Timeout: Operation cancelled.")
    except Exception as e:
        await message.reply_text(f"⚠️ Error clearing requests.\nError: <code>{e}</code>")
