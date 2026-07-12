import json
import logging
import os
import asyncio
import urllib.request

from pyrogram import Client, filters
from pyrogram.types import Message

# Safely import ADMINS and BOT_TOKEN
try:
    from info import ADMINS, BOT_TOKEN
except ImportError:
    ADMINS = []
    BOT_TOKEN = None

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
# 🌐 HTTP BYPASS FOR BOT REACTIONS
# ============================================================
def send_reaction_via_api(chat_id: int, message_id: int):
    """Bypasses Pyrogram entirely and uses the official Telegram Bot API."""
    if not BOT_TOKEN:
        print("⚠️ [AUTO-REACT ERROR]: BOT_TOKEN not found in info.py!")
        return

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/setMessageReaction"
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "reaction": [{"type": "emoji", "emoji": "❤️"}]
    }

    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})

    try:
        with urllib.request.urlopen(req) as response:
            pass # Successfully reacted!
    except Exception as e:
        print(f"❌ [HTTP API ERROR]: Failed to react - {e}")


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
# ❤️ AUTO REACTION MODULE
# ============================================================
@Client.on_message((filters.group | filters.channel) & ~filters.bot, group=-5)
async def auto_react_heart(bot: Client, message: Message):
    
    if not react_db.is_enabled:
        return

    # Ignore other bots
    if message.from_user and message.from_user.is_bot:
        return

    try:
        print(f"🚀 [AUTO-REACT]: Attempting HTTP Bot API bypass to send ❤️ to {message.id}...")
        # Offload the HTTP request to a background thread so it doesn't slow down your bot
        await asyncio.to_thread(send_reaction_via_api, message.chat.id, message.id)
        print("✅ [AUTO-REACT]: Success! Reaction sent.")
    except Exception as e:
        logger.error(f"Reaction Bypass Failed: {e}")
