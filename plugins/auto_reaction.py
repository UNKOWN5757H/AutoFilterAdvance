import json
import logging
import os

from pyrogram import Client, filters
from pyrogram.types import Message

# Safely import bot owners/admins
try:
    from info import ADMINS
except ImportError:
    ADMINS = []

logger = logging.getLogger(__name__)


# ============================================================
# 💾 Persistent Config for Auto-Reaction
# ============================================================
class ReactionDB:
    def __init__(self, filepath="reaction_data.json"):
        self.filepath = filepath
        self.is_enabled = True  # Enabled by default
        self._load()

    def _load(self):
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, "r") as f:
                    data = json.load(f)
                    self.is_enabled = data.get("enabled", True)
            except Exception as e:
                logger.error(f"Error loading Reaction DB: {e}")

    def _save(self):
        try:
            with open(self.filepath, "w") as f:
                json.dump({"enabled": self.is_enabled}, f, indent=4)
        except Exception as e:
            logger.error(f"Error saving Reaction DB: {e}")

    def set_status(self, status: bool):
        self.is_enabled = status
        self._save()


react_db = ReactionDB()


def is_bot_owner(user_id: int) -> bool:
    """Checks if the user is a global bot admin defined in info.py"""
    admin_list = [int(a) for a in ADMINS if str(a).isdigit()]
    return user_id in admin_list


# ============================================================
# ⚙️ GLOBAL ADMIN COMMANDS (Bot Owners Only)
# ============================================================
@Client.on_message(filters.command("enablereaction"))
async def enable_react(bot: Client, message: Message):
    if not message.from_user or not is_bot_owner(message.from_user.id):
        return await message.reply_text("❌ **Only Bot Owners can use this command.**")

    if react_db.is_enabled:
        return await message.reply_text(
            "⚠️ **Auto-Reaction is already ENABLED globally.**"
        )

    react_db.set_status(True)
    await message.reply_text(
        "✅ **Auto-Reaction has been ENABLED globally!**\nI will now react to messages with ❤️."
    )


@Client.on_message(filters.command("disablereaction"))
async def disable_react(bot: Client, message: Message):
    if not message.from_user or not is_bot_owner(message.from_user.id):
        return await message.reply_text("❌ **Only Bot Owners can use this command.**")

    if not react_db.is_enabled:
        return await message.reply_text(
            "⚠️ **Auto-Reaction is already DISABLED globally.**"
        )

    react_db.set_status(False)
    await message.reply_text(
        "🚫 **Auto-Reaction has been DISABLED globally.**\nI will stop reacting to messages."
    )


# ============================================================
# ❤️ AUTO REACTION MODULE
# ============================================================
# CHANGED: group=-3 ensures this runs instantly before Auto-Filter!
@Client.on_message((filters.group | filters.channel) & ~filters.bot, group=-3)
async def auto_react_heart(bot: Client, message: Message):

    # 1. Check if the bot owner has disabled the feature globally
    if not react_db.is_enabled:
        return

    # 2. Extra safety check: Ignore other bots
    if message.from_user and message.from_user.is_bot:
        return

    try:
        # 3. Send the heart reaction (removed 'emoji=' keyword as some Pyrogram versions reject it)
        await message.react("❤️")

    except Exception as e:
        # CHANGED: We now log the exact error to Koyeb so we aren't guessing!
        chat_title = getattr(message.chat, "title", "Unknown Chat")
        logger.error(f"⚠️ Reaction Failed in {chat_title} ({message.chat.id}): {e}")
