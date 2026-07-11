import asyncio
import logging

from pyrogram import Client, enums, filters
from pyrogram.types import Message

# Replace this import with your actual ADMINS list from your config
from info import ADMINS

logger = logging.getLogger(__name__)


# ============================================================
# 💾 Lightweight DB Manager (Replace with MongoDB/SQL in production)
# ============================================================
class ForceAddDB:
    def __init__(self):
        # Stores required limit per chat: {chat_id: limit}
        self.chat_limits = {}
        # Stores how many users a person has added: {"chat_id_user_id": count}
        self.user_adds = {}

    def set_limit(self, chat_id: int, limit: int):
        self.chat_limits[chat_id] = limit

    def get_limit(self, chat_id: int) -> int:
        return self.chat_limits.get(chat_id, 0)

    def get_user_adds(self, chat_id: int, user_id: int) -> int:
        return self.user_adds.get(f"{chat_id}_{user_id}", 0)

    def increment_adds(self, chat_id: int, user_id: int, count: int):
        key = f"{chat_id}_{user_id}"
        self.user_adds[key] = self.user_adds.get(key, 0) + count


db = ForceAddDB()

# Cache to avoid spamming Telegram's API for admin checks
ADMIN_CACHE = {}


async def is_admin(bot: Client, chat_id: int, user_id: int) -> bool:
    """Check if a user is an admin (with basic caching to prevent rate limits)."""
    if user_id in ADMINS:
        return True

    cache_key = f"{chat_id}_{user_id}"
    if cache_key in ADMIN_CACHE:
        return ADMIN_CACHE[cache_key]

    try:
        member = await bot.get_chat_member(chat_id, user_id)
        is_adm = member.status in [
            enums.ChatMemberStatus.ADMINISTRATOR,
            enums.ChatMemberStatus.OWNER,
        ]
        ADMIN_CACHE[cache_key] = is_adm
        return is_adm
    except Exception:
        return False


# ============================================================
# ⚙️ /setforceadd — Set how many members each user must add
# ============================================================
@Client.on_message(filters.command("setforceadd") & filters.group)
async def set_force_add(bot: Client, message: Message):
    if not await is_admin(bot, message.chat.id, message.from_user.id):
        return await message.reply_text("❌ **Only admins can use this command.**")

    if len(message.command) < 2:
        return await message.reply_text(
            "⚙️ **Usage:** `/setforceadd <number>`\nExample: `/setforceadd 5`"
        )

    try:
        limit = int(message.command[1])
        if limit < 0:
            raise ValueError
    except ValueError:
        return await message.reply_text("❌ Please provide a valid positive number.")

    db.set_limit(message.chat.id, limit)
    await message.reply_text(
        f"✅ **Force Add limit set!**\nUsers must now add **{limit}** members before they can send messages."
    )


# ============================================================
# ➖ /remforceadd — Remove force add members (set to 0)
# ============================================================
@Client.on_message(filters.command("remforceadd") & filters.group)
async def remove_force_add(bot: Client, message: Message):
    if not await is_admin(bot, message.chat.id, message.from_user.id):
        return await message.reply_text("❌ **Only admins can use this command.**")

    db.set_limit(message.chat.id, 0)
    await message.reply_text(
        "🗑️ **Force Add requirement has been removed.**\nEveryone can send messages freely."
    )


# ============================================================
# 🔍 /getforceadd — Show the current value
# ============================================================
@Client.on_message(filters.command("getforceadd") & filters.group)
async def get_force_add(bot: Client, message: Message):
    limit = db.get_limit(message.chat.id)

    if limit == 0:
        await message.reply_text("ℹ️ **Force Add is currently DISABLED (0).**")
    else:
        await message.reply_text(
            f"ℹ️ **Current Force Add Requirement:** `Users must add {limit} members.`"
        )


# ============================================================
# 📥 TRACKER: Listen for New Chat Members
# ============================================================
@Client.on_message(filters.new_chat_members & filters.group)
async def track_added_members(bot: Client, message: Message):
    limit = db.get_limit(message.chat.id)
    if limit == 0:
        return  # Feature is disabled, do nothing

    adder_id = message.from_user.id
    added_users = message.new_chat_members

    # We only count if the user actually added someone else.
    # (If they joined via a public link, message.from_user is themselves).
    added_others = [u for u in added_users if u.id != adder_id and not u.is_bot]

    if not added_others:
        return

    # Increment their score
    db.increment_adds(message.chat.id, adder_id, len(added_others))

    current_adds = db.get_user_adds(message.chat.id, adder_id)
    if current_adds >= limit:
        warning = await message.reply_text(
            f"🎉 Thank you {message.from_user.mention}! You have met the requirement and can now chat freely."
        )
        await asyncio.sleep(5)
        await warning.delete()


# ============================================================
# 🛡️ ENFORCER: Delete messages if requirements aren't met
# ============================================================
@Client.on_message(filters.group & ~filters.service, group=-1)
async def enforce_force_add(bot: Client, message: Message):
    # Ignore messages that don't have a user attached (e.g., anonymous admins)
    if not message.from_user:
        return

    chat_id = message.chat.id
    user_id = message.from_user.id
    limit = db.get_limit(chat_id)

    # If disabled, or if the user is an admin, let them pass
    if limit == 0 or await is_admin(bot, chat_id, user_id):
        return

    # Check if they have met the threshold
    current_adds = db.get_user_adds(chat_id, user_id)
    if current_adds < limit:
        remaining = limit - current_adds
        try:
            # Delete their message
            await message.delete()

            # Warn them, then delete the warning after 8 seconds so the chat doesn't get cluttered
            warn_msg = await message.reply_text(
                f"🛑 **Hold on, {message.from_user.mention}!**\n\n"
                f"You must add **{remaining} more member(s)** to this group before you are allowed to send messages.\n"
                f"*(Currently added: {current_adds}/{limit})*"
            )
            await asyncio.sleep(8)
            await warn_msg.delete()

        except Exception as e:
            logger.error(f"Error enforcing force add: {e}")
