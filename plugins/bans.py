import logging
from pyrogram import Client, filters
from pyrogram.types import Message

import info

logger = logging.getLogger(__name__)

# ============================================================
# 🗄️ Banned Users Database Handler
# ============================================================
class BanDB:
    def __init__(self):
        self.db_url = getattr(info, "DATABASE_URI", None)
        if self.db_url:
            try:
                from motor.motor_asyncio import AsyncIOMotorClient
                self.client = AsyncIOMotorClient(self.db_url)
                self.database = self.client["BotDatabase"]
                self.col = self.database["banned_users"]
                self.use_mongo = True
            except ImportError:
                logger.warning("motor is not installed! Using memory for Banned users.")
                self.use_mongo = False
                self.mock_db = set()
        else:
            self.use_mongo = False
            self.mock_db = set()

    async def ban_user(self, user_id: int):
        if self.use_mongo:
            await self.col.update_one({"_id": user_id}, {"$set": {"_id": user_id}}, upsert=True)
        else:
            self.mock_db.add(user_id)

    async def unban_user(self, user_id: int):
        if self.use_mongo:
            await self.col.delete_one({"_id": user_id})
        else:
            self.mock_db.discard(user_id)

    async def is_banned(self, user_id: int) -> bool:
        if self.use_mongo:
            user = await self.col.find_one({"_id": user_id})
            return bool(user)
        return user_id in self.mock_db
        
    async def get_ban_count(self) -> int:
        if self.use_mongo:
            return await self.col.count_documents({})
        return len(self.mock_db)

ban_db = BanDB()


# ============================================================
# 🚫 1. Ban User
# ============================================================
@Client.on_message(filters.command("ban") & filters.user(info.ADMINS))
async def ban_user_cmd(bot: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text("⚙️ **Usage:** `/ban [user_id]`")
        
    try:
        user_id = int(message.command[1])
        
        # Prevent banning other admins or the bot itself
        if user_id in info.ADMINS:
            return await message.reply_text("❌ **You cannot ban a bot administrator!**")
        if user_id == bot.me.id:
            return await message.reply_text("❌ **I cannot ban myself!**")
            
        await ban_db.ban_user(user_id)
        await message.reply_text(f"🚫 **User `{user_id}` has been successfully BANNED.**\nThey can no longer use this bot.")
        
    except ValueError:
        await message.reply_text("❌ **Invalid User ID!** Please provide a valid numerical ID.")
    except Exception as e:
        await message.reply_text(f"❌ **Error:** `{e}`")


# ============================================================
# ✅ 2. Unban User
# ============================================================
@Client.on_message(filters.command("unban") & filters.user(info.ADMINS))
async def unban_user_cmd(bot: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text("⚙️ **Usage:** `/unban [user_id]`")
        
    try:
        user_id = int(message.command[1])
        
        is_banned = await ban_db.is_banned(user_id)
        if not is_banned:
            return await message.reply_text(f"⚠️ **User `{user_id}` is not currently banned.**")
            
        await ban_db.unban_user(user_id)
        await message.reply_text(f"✅ **User `{user_id}` has been successfully UNBANNED.**\nThey can now use the bot again.")
        
    except ValueError:
        await message.reply_text("❌ **Invalid User ID!** Please provide a valid numerical ID.")
    except Exception as e:
        await message.reply_text(f"❌ **Error:** `{e}`")


# ============================================================
# 📊 3. Check Banned Users (Bonus)
# ============================================================
@Client.on_message(filters.command("bannedusers") & filters.user(info.ADMINS))
async def check_banned_users(bot: Client, message: Message):
    try:
        count = await ban_db.get_ban_count()
        await message.reply_text(f"📊 **Total Banned Users:** `{count}`")
    except Exception as e:
        await message.reply_text(f"❌ **Error:** `{e}`")
