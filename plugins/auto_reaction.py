import json
import logging
import os

from pyrogram import Client, filters
from pyrogram.types import Message

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
        self.is_enabled = True
        self._load()

    def _load(self):
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, "r") as f:
                    data = json.load(f)
                    self.is_enabled = data.get("enabled", True)
            except Exception:
                pass

    def _save(self):
        try:
            with open(self.filepath, "w") as f:
                json.dump({"enabled": self.is_enabled}, f, indent=4)
        except Exception:
            pass

    def set_status(self, status: bool):
        self.is_enabled = status
        self._save()


react_db = ReactionDB()


def is_bot_owner(user_id: int) -> bool:
    admin_list = [int(a) for a in ADMINS if str(a).isdigit()]
    return user_id in admin_list


# ============================================================
# ⚙️ GLOBAL ADMIN COMMANDS
# ============================================================
@Client.on_message(filters.command("enablereaction"))
async def enable_react(bot: Client, message: Message):
    if not message.from_user or not is_bot_owner(message.from_user.id):
        return await message.reply_text("❌ **Only Bot Owners can use this command.**")

    react_db.set_status(True)
    await message.reply_text("✅ **Auto-Reaction has been ENABLED globally!**")


@Client.on_message(filters.command("disablereaction"))
async def disable_react(bot: Client, message: Message):
    if not message.from_user or not is_bot_owner(message.from_user.id):
        return await message.reply_text("❌ **Only Bot Owners can use this command.**")

    react_db.set_status(False)
    await message.reply_text("🚫 **Auto-Reaction has been DISABLED globally.**")


# ============================================================
# ❤️ AUTO REACTION MODULE (Loud Debug Mode)
# ============================================================
# group=-5 guarantees this is the absolute FIRST thing the bot sees
@Client.on_message((filters.group | filters.channel) & ~filters.bot, group=-5)
async def auto_react_heart(bot: Client, message: Message):

    chat_title = getattr(message.chat, "title", "Unknown Chat")
    print(f"👀 [AUTO-REACT DEBUG]: Bot saw a message in {chat_title}")

    if not react_db.is_enabled:
        print(
            "🛑 [AUTO-REACT DEBUG]: Stopped. Reaction is currently DISABLED in the JSON database."
        )
        return

    if message.from_user and message.from_user.is_bot:
        print("🛑 [AUTO-REACT DEBUG]: Stopped. The sender is a bot.")
        return

    try:
        print(
            f"🚀 [AUTO-REACT DEBUG]: Attempting to send ❤️ to message ID {message.id}..."
        )

        # Using the direct API method instead of the message object shortcut
        await bot.send_reaction(
            chat_id=message.chat.id, message_id=message.id, emoji="❤️"
        )
        print("✅ [AUTO-REACT DEBUG]: Success! Telegram accepted the reaction.")

    except Exception as e:
        print(
            f"❌ [AUTO-REACT DEBUG ERROR]: Telegram rejected the reaction! Reason: {e}"
        )
        logger.error(f"Reaction Failed: {e}")
