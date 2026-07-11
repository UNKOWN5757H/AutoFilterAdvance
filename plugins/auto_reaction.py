import logging
import random

from pyrogram import Client, filters, enums
from pyrogram.types import Message

# Replace with your actual config import if you have global admins
from info import ADMINS  

logger = logging.getLogger(__name__)

# ============================================================
# 💾 Lightweight DB Manager 
# ============================================================
class AutoReactDB:
    def __init__(self):
        # Stores reaction emojis per chat: {chat_id: ["👍", "🔥", "❤️"]}
        self.chat_reactions = {}

    def set_reactions(self, chat_id: int, emojis: list):
        self.chat_reactions[chat_id] = emojis

    def get_reactions(self, chat_id: int) -> list:
        return self.chat_reactions.get(chat_id, [])

    def remove_reactions(self, chat_id: int):
        if chat_id in self.chat_reactions:
            del self.chat_reactions[chat_id]

db = AutoReactDB()
ADMIN_CACHE = {}

async def is_admin(bot: Client, chat_id: int, user_id: int) -> bool:
    """Helper to check if user is a group/channel admin with caching."""
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
# ⚙️ /setreaction — Set emojis for Groups or Channels
# ============================================================
@Client.on_message(filters.command("setreaction"))
async def set_auto_reaction(bot: Client, message: Message):
    args = message.command[1:]
    
    if not args:
        return await message.reply_text(
            "⚙️ **Usage:**\n"
            "• **In a Group:** `/setreaction 👍 🔥`\n"
            "• **For a Channel (Send in bot's PM):** `/setreaction @YourChannel 👍 🔥`\n"
            "*(You can also use the channel ID like -100123456789)*"
        )

    target_chat = args[0]
    target_chat_id = message.chat.id
    emojis = args

    # Check if the user is trying to configure a remote channel/group
    if target_chat.startswith("-100") or target_chat.startswith("@"):
        try:
            chat = await bot.get_chat(target_chat)
            target_chat_id = chat.id
            emojis = args[1:]
        except Exception as e:
            return await message.reply_text(f"❌ Could not access `{target_chat}`. Make sure I am an admin there!")

    # Block configuring in PM without a target ID
    if message.chat.type == enums.ChatType.PRIVATE and target_chat_id == message.chat.id:
        return await message.reply_text("❌ You are in a Private Message. Please provide a Channel/Group ID. Example: `/setreaction @MyChannel 👍`")

    if not emojis:
        return await message.reply_text("❌ Please provide at least one emoji to react with.")

    # Admin verification
    if message.from_user:
        if not await is_admin(bot, target_chat_id, message.from_user.id):
            return await message.reply_text("❌ **You must be an admin of the target chat to do this.**")

    db.set_reactions(target_chat_id, emojis)
    emoji_display = " ".join(emojis)
    await message.reply_text(f"✅ **Auto-reaction enabled!**\n\n🎯 Target: `{target_chat_id}`\n✨ Emojis: {emoji_display}")


# ============================================================
# ➖ /removereaction — Disable auto-reactions
# ============================================================
@Client.on_message(filters.command("removereaction"))
async def remove_auto_reaction(bot: Client, message: Message):
    args = message.command[1:]
    target_chat_id = message.chat.id

    if args and (args[0].startswith("-100") or args[0].startswith("@")):
        try:
            chat = await bot.get_chat(args[0])
            target_chat_id = chat.id
        except Exception:
            return await message.reply_text(f"❌ Could not access `{args[0]}`.")

    if message.chat.type == enums.ChatType.PRIVATE and target_chat_id == message.chat.id:
        return await message.reply_text("❌ Please provide a Channel/Group ID. Example: `/removereaction @MyChannel`")

    if message.from_user:
        if not await is_admin(bot, target_chat_id, message.from_user.id):
            return await message.reply_text("❌ **Only admins can use this command.**")

    db.remove_reactions(target_chat_id)
    await message.reply_text(f"🗑️ **Auto-reaction has been disabled for `{target_chat_id}`.**")


# ============================================================
# 🔍 /getreaction — Check active reactions
# ============================================================
@Client.on_message(filters.command("getreaction"))
async def get_auto_reaction(bot: Client, message: Message):
    args = message.command[1:]
    target_chat_id = message.chat.id

    if args and (args[0].startswith("-100") or args[0].startswith("@")):
        try:
            chat = await bot.get_chat(args[0])
            target_chat_id = chat.id
        except Exception:
            return await message.reply_text(f"❌ Could not access `{args[0]}`.")

    if message.chat.type == enums.ChatType.PRIVATE and target_chat_id == message.chat.id:
        return await message.reply_text("❌ Please provide a Channel/Group ID. Example: `/getreaction @MyChannel`")

    emojis = db.get_reactions(target_chat_id)
    
    if not emojis:
        await message.reply_text(f"ℹ️ **Auto-reaction is currently DISABLED for `{target_chat_id}`.**")
    else:
        emoji_display = " ".join(emojis)
        await message.reply_text(f"ℹ️ **Current Auto-Reactions for `{target_chat_id}`:** {emoji_display}")


# ============================================================
# 📥 THE REACTOR: Applies the reactions to incoming messages
# ============================================================
@Client.on_message((filters.group | filters.channel) & ~filters.service, group=120)
async def auto_react_handler(bot: Client, message: Message):
    emojis = db.get_reactions(message.chat.id)
    
    if not emojis:
        return

    chosen_emoji = random.choice(emojis)

    try:
        await message.react(emoji=chosen_emoji)
    except Exception as e:
        logger.debug(f"Failed to react to message {message.id} in {message.chat.id}: {e}")
