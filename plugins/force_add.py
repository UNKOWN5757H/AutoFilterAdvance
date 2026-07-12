import asyncio
import json
import logging
import os

from pyrogram import Client, StopPropagation, filters
from pyrogram.types import Message

# Safely import ADMINS to prevent crashes if info.py is missing or misconfigured
try:
    from info import ADMINS
except ImportError:
    ADMINS = []

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
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, "r") as f:
                    data = json.load(f)
                    self.chat_limits = {
                        int(k): v for k, v in data.get("limits", {}).items()
                    }
                    self.user_adds = data.get("adds", {})
            except Exception as e:
                logger.error(f"Error loading DB: {e}")

    def _save(self):
        try:
            with open(self.filepath, "w") as f:
                json.dump(
                    {"limits": self.chat_limits, "adds": self.user_adds}, f, indent=4
                )
        except Exception as e:
            logger.error(f"Error saving DB: {e}")

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


async def is_admin(bot: Client, chat_id: int, user_id: int) -> bool:
    """Bulletproof admin check for both Pyrogram V1 and V2."""
    # 1. Safely check info.py ADMINS (handles both strings and ints)
    admin_list = [int(a) for a in ADMINS if str(a).isdigit()]
    if user_id in admin_list:
        return True

    # 2. Check group administrators
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        # Using getattr and strings makes this work on ANY Pyrogram version
        status = str(getattr(member, "status", "")).lower()
        return any(role in status for role in ["administrator", "creator", "owner"])
    except Exception as e:
        logger.error(f"Failed to check admin status for {user_id}: {e}")
        return False


# ============================================================
# ⚙️ ADMIN COMMANDS
# ============================================================
@Client.on_message(filters.command("setforceadd") & filters.group)
async def set_force_add(bot: Client, message: Message):
    if not message.from_user:
        return await message.reply_text("❌ Anonymous admins cannot use this command.")

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
        f"✅ **Force Add limit set to {limit}!**\n*(Saved permanently)*"
    )


@Client.on_message(filters.command("remforceadd") & filters.group)
async def remove_force_add(bot: Client, message: Message):
    if not message.from_user:
        return

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
        await message.reply_text(
            f"ℹ️ **Current Force Add Requirement:** `Users must add {limit} members.`"
        )


# ============================================================
# 🧑‍💻 USER COMMAND: Check their own progress
# ============================================================
@Client.on_message(filters.command("myadds") & filters.group)
async def my_adds(bot: Client, message: Message):
    if not message.from_user:
        return

    limit = db.get_limit(message.chat.id)
    if limit == 0:
        return await message.reply_text("ℹ️ Force Add is not active in this group.")

    current_adds = db.get_user_adds(message.chat.id, message.from_user.id)
    if current_adds >= limit:
        await message.reply_text(
            f"✅ You have added **{current_adds}** members. You are cleared to chat freely!"
        )
    else:
        await message.reply_text(
            f"⚠️ You have added **{current_adds}/{limit}** members. You need {limit - current_adds} more."
        )


# ============================================================
# 📥 TRACKER & 🛡️ ENFORCER (Combined for stability)
# ============================================================
@Client.on_message(filters.new_chat_members & filters.group)
async def track_added_members(bot: Client, message: Message):
    if not message.from_user:
        return

    limit = db.get_limit(message.chat.id)
    if limit == 0:
        return

    adder_id = message.from_user.id
    added_users = message.new_chat_members

    added_others = [u for u in added_users if u.id != adder_id and not u.is_bot]
    if not added_others:
        return

    db.increment_adds(message.chat.id, adder_id, len(added_others))
    current_adds = db.get_user_adds(message.chat.id, adder_id)

    if current_adds >= limit:
        msg = await message.reply_text(
            f"🎉 Thank you {message.from_user.mention}! You've met the requirement. You can now chat freely!"
        )
        await asyncio.sleep(8)
        try:
            await msg.delete()
        except Exception:
            pass


@Client.on_message(filters.group & ~filters.service, group=-1)
async def enforce_force_add(bot: Client, message: Message):
    if not message.from_user:
        return

    chat_id = message.chat.id
    user_id = message.from_user.id
    limit = db.get_limit(chat_id)

    if limit == 0:
        return

    # CRITICAL: Bypass ALL bot commands (whether text or caption) so they don't get deleted
    text = message.text or message.caption
    if text and text.startswith("/"):
        return

    if await is_admin(bot, chat_id, user_id):
        return

    current_adds = db.get_user_adds(chat_id, user_id)
    if current_adds < limit:
        try:
            await message.delete()
            warn_msg = await message.reply_text(
                f"🛑 **Hold on, {message.from_user.mention}!**\n\n"
                f"You must add **{limit - current_adds} more member(s)** to this group before you can send messages.\n"
                f"*(Currently added: {current_adds}/{limit})*"
            )
            raise StopPropagation
        except StopPropagation:
            raise
        except Exception:
            pass
        finally:
            if "warn_msg" in locals():

                async def delete_warning():
                    await asyncio.sleep(8)
                    try:
                        await warn_msg.delete()
                    except Exception:
                        pass

                asyncio.create_task(delete_warning())
