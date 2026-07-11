import asyncio
import logging
import json
import os

from pyrogram import Client, filters, enums
from pyrogram.types import Message

from info import ADMINS  

logger = logging.getLogger(__name__)

# ============================================================
# 💾 Persistent JSON Database Manager 
# ============================================================
class ForceAddDB:
    def __init__(self, filepath="force_add_data.json"):
        self.filepath = filepath
        self.chat_limits = {}
        self.user_adds = {}
        self._load()

    def _load(self):
        """Loads data from the JSON file on startup."""
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, "r") as f:
                    data = json.load(f)
                    # JSON keys are always strings, so we convert chat_ids back to ints
                    self.chat_limits = {int(k): v for k, v in data.get("limits", {}).items()}
                    self.user_adds = data.get("adds", {})
            except Exception as e:
                logger.error(f"Error loading ForceAdd DB: {e}")

    def _save(self):
        """Saves data to the JSON file immediately."""
        try:
            with open(self.filepath, "w") as f:
                json.dump({
                    "limits": self.chat_limits, 
                    "adds": self.user_adds
                }, f, indent=4)
        except Exception as e:
            logger.error(f"Error saving ForceAdd DB: {e}")

    def set_limit(self, chat_id: int, limit: int):
        self.chat_limits[chat_id] = limit
        self._save()

    def get_limit(self, chat_id: int) -> int:
        return self.chat_limits.get(chat_id, 0)

    def get_user_adds(self, chat_id: int, user_id: int) -> int:
        return self.user_adds.get(f"{chat_id}_{user_id}", 0)

    def increment_adds(self, chat_id: int, user_id: int, count: int):
        key = f"{chat_id}_{user_id}"
        self.user_adds[key] = self.user_adds.get(key, 0) + count
        self._save()

db = ForceAddDB()
ADMIN_CACHE = {}

async def is_admin(bot: Client, chat_id: int, user_id: int) -> bool:
    """Helper to check if a user is an admin."""
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
# ⚙️ ADMIN COMMANDS
# ============================================================
@Client.on_message(filters.command("setforceadd") & filters.group)
async def set_force_add(bot: Client, message: Message):
    if not await is_admin(bot, message.chat.id, message.from_user.id):
        return await message.reply_text("❌ **Only admins can use this command.**")

    if len(message.command) < 2:
        return await message.reply_text("⚙️ **Usage:** `/setforceadd <number>`\nExample: `/setforceadd 5`")

    try:
        limit = int(message.command[1])
        if limit < 0: raise ValueError
    except ValueError:
        return await message.reply_text("❌ Please provide a valid positive number.")

    db.set_limit(message.chat.id, limit)
    await message.reply_text(f"✅ **Force Add limit set to {limit}!**\n*(Saved permanently)*")


@Client.on_message(filters.command("remforceadd") & filters.group)
async def remove_force_add(bot: Client, message: Message):
    if not await is_admin(bot, message.chat.id, message.from_user.id):
        return await message.reply_text("❌ **Only admins can use this command.**")

    db.set_limit(message.chat.id, 0)
    await message.reply_text("🗑️ **Force Add requirement has been removed.**")


@Client.on_message(filters.command("getforceadd") & filters.group)
async def get_force_add(bot: Client, message: Message):
    limit = db.get_limit(message.chat.id)
    if limit == 0:
        await message.reply_text("ℹ️ **Force Add is currently DISABLED.**")
    else:
        await message.reply_text(f"ℹ️ **Current Force Add Requirement:** `Users must add {limit} members.`")


# ============================================================
# 🧑‍💻 USER COMMAND: Check their own progress
# ============================================================
@Client.on_message(filters.command("myadds") & filters.group)
async def my_adds(bot: Client, message: Message):
    limit = db.get_limit(message.chat.id)
    if limit == 0:
        return await message.reply_text("ℹ️ Force Add is not active in this group.")
        
    current_adds = db.get_user_adds(message.chat.id, message.from_user.id)
    if current_adds >= limit:
        await message.reply_text(f"✅ You have added **{current_adds}** members. You are cleared to chat freely!")
    else:
        await message.reply_text(f"⚠️ You have added **{current_adds}/{limit}** members. You need {limit - current_adds} more.")


# ============================================================
# 📥 TRACKER: Listen for New Chat Members
# ============================================================
@Client.on_message(filters.new_chat_members & filters.group)
async def track_added_members(bot: Client, message: Message):
    limit = db.get_limit(message.chat.id)
    if limit == 0:
        return

    adder_id = message.from_user.id
    added_users = message.new_chat_members
    
    # Filter out users who joined via a link (where they "added themselves") and bots
    added_others = [u for u in added_users if u.id != adder_id and not u.is_bot]
    
    if not added_others:
        return

    db.increment_adds(message.chat.id, adder_id, len(added_others))
    current_adds = db.get_user_adds(message.chat.id, adder_id)
    
    if current_adds >= limit:
        msg = await message.reply_text(f"🎉 Thank you {message.from_user.mention}! You've met the requirement of adding {limit} members. You can now chat!")
        await asyncio.sleep(5)
        await msg.delete()


# ============================================================
# 🛡️ ENFORCER: Delete messages if requirements aren't met
# ============================================================
@Client.on_message(filters.group & ~filters.service, group=-1)
async def enforce_force_add(bot: Client, message: Message):
    if not message.from_user:
        return

    chat_id = message.chat.id
    user_id = message.from_user.id
    limit = db.get_limit(chat_id)

    if limit == 0 or await is_admin(bot, chat_id, user_id):
        return

    current_adds = db.get_user_adds(chat_id, user_id)
    if current_adds < limit:
        try:
            # Attempt to delete their message
            await message.delete()
            
            # Send warning message
            warn_msg = await message.reply_text(
                f"🛑 **Hold on, {message.from_user.mention}!**\n\n"
                f"You must add **{limit - current_adds} more member(s)** to this group before you can send messages.\n"
                f"*(Currently added: {current_adds}/{limit})*"
            )
            # Delete the warning after 8 seconds to prevent spam
            await asyncio.sleep(8)
            await warn_msg.delete()
            
        except Exception as e:
            logger.error(f"ForceAdd Error: Could not delete message. Is the bot an admin? Error: {e}")
