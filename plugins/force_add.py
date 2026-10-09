import asyncio
import time
from logging import ERROR, getLogger
from typing import Dict, Tuple

from motor.motor_asyncio import AsyncIOMotorClient
from pyrogram import Client, StopPropagation, enums, filters
from pyrogram.errors import MessageNotModified, UserAdminInvalid, ChatAdminRequired
from pyrogram.types import (
    ChatPermissions,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    CallbackQuery
)

import info

logger = getLogger(__name__)
logger.setLevel(ERROR)

# ============================================================
# ⚙️ ISOLATED MONGODB ENGINE (Guarantees 100% Functionality)
# ============================================================
fa_config_db = None
fa_users_db = None

try:
    _DB_CLIENT = AsyncIOMotorClient(info.DATABASE_URI)
    _BOT_DB = _DB_CLIENT[info.DATABASE_NAME]
    fa_config_db = _BOT_DB["forceadd_config"]
    fa_users_db = _BOT_DB["forceadd_users"]
except Exception as e:
    logger.error(f"Failed to init Force Add DB: {e}")

# Database Helper Functions
async def set_fa_config(chat_id: int, limit: int, mode: str):
    if fa_config_db is not None:
        await fa_config_db.update_one({"chat_id": chat_id}, {"$set": {"limit": limit, "mode": mode}}, upsert=True)

async def get_fa_config(chat_id: int):
    if fa_config_db is not None:
        doc = await fa_config_db.find_one({"chat_id": chat_id})
        if doc: return doc
    return {"limit": 0, "mode": "all"}

async def add_user_score(chat_id: int, user_id: int, count: int):
    if fa_users_db is not None:
        timestamps = [int(time.time())] * count
        await fa_users_db.update_one(
            {"chat_id": chat_id, "user_id": user_id},
            {"$push": {"adds": {"$each": timestamps}}},
            upsert=True
        )

async def get_user_score(chat_id: int, user_id: int):
    if fa_users_db is not None:
        doc = await fa_users_db.find_one({"chat_id": chat_id, "user_id": user_id})
        if doc and "adds" in doc: return len(doc["adds"])
    return 0

async def mark_new_user(chat_id: int, user_id: int):
    if fa_users_db is not None:
        await fa_users_db.update_one({"chat_id": chat_id, "user_id": user_id}, {"$set": {"is_new": True}}, upsert=True)

async def is_new_user(chat_id: int, user_id: int):
    if fa_users_db is not None:
        doc = await fa_users_db.find_one({"chat_id": chat_id, "user_id": user_id})
        return doc.get("is_new", False) if doc else False
    return False

# ============================================================
# 🛡️ ANTI-SPAM WARNING CACHE
# ============================================================
class TTLCache:
    def __init__(self, maxsize: int = 5000, ttl: int = 60):
        self._data: Dict[str, float] = {}
        self._maxsize = maxsize
        self._ttl = ttl

    def is_rate_limited(self, key: str) -> bool:
        now = time.time()
        if key in self._data and now < self._data[key]:
            return True
        self._cleanup(now)
        if len(self._data) >= self._maxsize: self._data.clear()
        self._data[key] = now + self._ttl
        return False

    def _cleanup(self, now):
        expired = [k for k, exp in self._data.items() if now >= exp]
        for k in expired: del self._data[k]

WARN_CACHE = TTLCache(ttl=60) # Warns the user only once every 60 seconds to prevent group spam!

# ============================================================
# 👑 ADMIN & PERMISSION CHECKS
# ============================================================
def get_admin_list():
    raw_admins = getattr(info, "ADMINS", [])
    if isinstance(raw_admins, str): return [int(x) for x in raw_admins.replace(",", " ").split() if x.strip().lstrip("-").isdigit()]
    elif isinstance(raw_admins, int): return [raw_admins]
    elif isinstance(raw_admins, list): return [int(x) for x in raw_admins if str(x).strip().lstrip("-").isdigit()]
    return []

async def is_admin(bot: Client, chat_id: int, user_id: int) -> bool:
    if user_id in get_admin_list(): return True
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in [enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER]
    except Exception: return False


# ============================================================
# ⚙️ CONFIGURATION COMMANDS
# ============================================================
@Client.on_message(filters.command("setforceadd") & filters.group)
async def set_force_add(bot: Client, message: Message):
    if not await is_admin(bot, message.chat.id, message.from_user.id):
        return await message.reply_text("❌ **Only group admins can use this command.**")
        
    if len(message.command) < 2:
        return await message.reply_text("⚙️ **Usage:** `/setforceadd <number>`\nExample: `/setforceadd 5`")
        
    try:
        limit = int(message.command[1])
        if limit < 0: raise ValueError
    except ValueError:
        return await message.reply_text("❌ Please provide a valid positive number.")
        
    admin_id = message.from_user.id
    grp_id = message.chat.id
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 Force Add for ALL Members", callback_data=f"fa_set_{limit}_all_{admin_id}_{grp_id}")],
        [InlineKeyboardButton("🆕 Force Add for ONLY NEW Members", callback_data=f"fa_set_{limit}_new_{admin_id}_{grp_id}")]
    ])
    
    await message.reply_text("🎯 **Who should this requirement apply to?**\n\n*(Select an option below)*", reply_markup=kb)


@Client.on_callback_query(filters.regex(r"^fa_set_(\d+)_([a-z]+)_(\d+)_(-?\d+)$"))
async def set_forceadd_callback(bot: Client, query: CallbackQuery):
    limit, mode, admin_id, grp_id = int(query.matches[0].group(1)), query.matches[0].group(2), int(query.matches[0].group(3)), int(query.matches[0].group(4))
    
    if query.from_user.id != admin_id:
        return await query.answer("❌ Only the admin who ran the command can choose this.", show_alert=True)
        
    await set_fa_config(grp_id, limit, mode)
    mode_text = "ALL MEMBERS" if mode == "all" else "ONLY NEW MEMBERS (who join from now on)"
    
    try:
        await query.message.edit_text(f"✅ **Force Add Configured Successfully!**\n\n🔢 **Limit:** `{limit} members`\n🎯 **Target:** `{mode_text}`\n*(Engine is now 100% Active)*")
    except MessageNotModified: pass
    await query.answer()

@Client.on_message(filters.command("remforceadd") & filters.group)
async def remove_force_add(bot: Client, message: Message):
    if not await is_admin(bot, message.chat.id, message.from_user.id): return
    await set_fa_config(message.chat.id, 0, "all")
    await message.reply_text("🗑️ **Force Add requirement has been completely removed.**")

@Client.on_message(filters.command("getforceadd") & filters.group)
async def get_force_add(bot: Client, message: Message):
    settings = await get_fa_config(message.chat.id)
    if settings["limit"] == 0:
        await message.reply_text("ℹ️ **Force Add is currently DISABLED in this group.**")
    else:
        target = "Everyone" if settings["mode"] == "all" else "Only New Members"
        await message.reply_text(f"ℹ️ **Current Requirement:** Users must add {settings['limit']} members.\n🎯 **Applies to:** {target}")


# ============================================================
# 📊 LEADERBOARD & STATS LOGIC
# ============================================================
async def generate_leaderboard(bot: Client, message: Message, title: str, time_limit_seconds: int = None):
    if fa_users_db is None: return await message.reply("Database Error.")
    
    pipeline = [{"$match": {"chat_id": message.chat.id}}]
    
    if time_limit_seconds:
        cutoff = int(time.time()) - time_limit_seconds
        pipeline.append({
            "$project": {
                "user_id": 1,
                "valid_adds": {
                    "$filter": {
                        "input": "$adds",
                        "as": "timestamp",
                        "cond": {"$gte": ["$$timestamp", cutoff]}
                    }
                }
            }
        })
        pipeline.append({"$project": {"user_id": 1, "score": {"$size": {"$ifNull": ["$valid_adds", []]}}}})
    else:
        pipeline.append({"$project": {"user_id": 1, "score": {"$size": {"$ifNull": ["$adds", []]}}}})
        
    pipeline.extend([{"$match": {"score": {"$gt": 0}}}, {"$sort": {"score": -1}}, {"$limit": 10}])
    
    cursor = fa_users_db.aggregate(pipeline)
    top_users = await cursor.to_list(length=10)
    
    if not top_users:
        return await message.reply_text(f"📊 **{title}**\n\nNo members have added anyone yet!")
        
    text = f"📊 **{title} (Top 10)**\n\n"
    for i, data in enumerate(top_users, 1):
        uid, score = data["user_id"], data["score"]
        try:
            user = await bot.get_users(uid)
            user_name = user.mention if user else f"User {uid}"
        except Exception: user_name = f"User {uid}"
        text += f"**{i}.** {user_name} ➔ `{score}` added\n"
        
    await message.reply_text(text, disable_web_page_preview=True)

@Client.on_message(filters.command("topaddall") & filters.group)
async def top_add_all(bot: Client, message: Message):
    await generate_leaderboard(bot, message, "All-Time Top Adders", None)

@Client.on_message(filters.command("topadd24") & filters.group)
async def top_add_24(bot: Client, message: Message):
    await generate_leaderboard(bot, message, "Top Adders (Past 24 Hours)", 86400)

@Client.on_message(filters.command("topadd7") & filters.group)
async def top_add_7(bot: Client, message: Message):
    await generate_leaderboard(bot, message, "Top Adders (Past 7 Days)", 604800)

@Client.on_message(filters.command("resetadddaily") & filters.group)
async def reset_add_daily(bot: Client, message: Message):
    if not await is_admin(bot, message.chat.id, message.from_user.id): return
    if fa_users_db is not None:
        cutoff = int(time.time()) - 86400
        await fa_users_db.update_many({"chat_id": message.chat.id}, {"$pull": {"adds": {"$lt": cutoff}}})
        await message.reply_text("♻️ **Daily limits reset!** Leaderboards for past 24h have been wiped.")

@Client.on_message(filters.command("resetadd") & filters.group)
async def reset_all_adds(bot: Client, message: Message):
    if not await is_admin(bot, message.chat.id, message.from_user.id): return
    if fa_users_db is not None:
        await fa_users_db.update_many({"chat_id": message.chat.id}, {"$set": {"adds": []}})
        await message.reply_text("💥 **TOTAL RESET!** All members' scores are now 0. Everyone must add members again.")

@Client.on_message(filters.command("myadds") & filters.group)
async def my_adds(bot: Client, message: Message):
    settings = await get_fa_config(message.chat.id)
    if settings["limit"] == 0:
        return await message.reply_text("ℹ️ Force Add is not active in this group.")
        
    current_adds = await get_user_score(message.chat.id, message.from_user.id)
    if current_adds >= settings["limit"]:
        await message.reply_text(f"✅ You have added **{current_adds}** members. You are cleared to chat freely!")
    else:
        await message.reply_text(f"⚠️ You have added **{current_adds}/{settings['limit']}** members.")


# ============================================================
# 🎯 THE ENGINE: TRACKER & ENFORCER
# ============================================================
@Client.on_message(filters.new_chat_members & filters.group, group=10)
async def track_added_members(bot: Client, message: Message):
    if not message.from_user: return
    
    # 1. Mark New Users
    for u in message.new_chat_members:
        await mark_new_user(message.chat.id, u.id)
        
    # 2. Process Additions
    settings = await get_fa_config(message.chat.id)
    if settings["limit"] == 0: return
    
    adder_id = message.from_user.id
    added_others = [u for u in message.new_chat_members if u.id != adder_id and not u.is_bot]
    
    if not added_others: return
    
    await add_user_score(message.chat.id, adder_id, len(added_others))
    current_adds = await get_user_score(message.chat.id, adder_id)

    # 3. Unlock Chat if Limit Met
    if current_adds >= settings["limit"]:
        try:
            # Unrestrict completely
            await bot.restrict_chat_member(
                message.chat.id, adder_id,
                permissions=ChatPermissions(
                    can_send_messages=True, can_send_media_messages=True,
                    can_send_other_messages=True, can_add_web_page_previews=True,
                    can_invite_users=True,
                )
            )
            msg = await message.reply_text(f"🎉 **Congratulations {message.from_user.mention}!**\n\nYou've added {current_adds} members and met the group requirement. **You can now chat freely!**")
            await asyncio.sleep(15)
            await msg.delete()
        except Exception: pass


@Client.on_message(filters.group & ~filters.service & ~filters.new_chat_members & ~filters.left_chat_member, group=-1)
async def enforce_force_add(bot: Client, message: Message):
    if not message.from_user: return
    chat_id, user_id = message.chat.id, message.from_user.id
    
    settings = await get_fa_config(chat_id)
    limit = settings["limit"]
    if limit == 0: return
    
    if settings["mode"] == "new":
        if not await is_new_user(chat_id, user_id): return

    text = message.text or message.caption
    if text and text.startswith("/"): return
    
    if await is_admin(bot, chat_id, user_id): return
    
    current_adds = await get_user_score(chat_id, user_id)
    
    if current_adds < limit:
        # SILENT MESSAGE DELETION
        try: await message.delete()
        except Exception: pass
        
        # PERMANENT RESTRICTION (Until fulfilled)
        try:
            await bot.restrict_chat_member(
                chat_id=chat_id, user_id=user_id,
                permissions=ChatPermissions(can_send_messages=False, can_invite_users=True),
                until_date=0 # 0 means permanently restricted until they add users
            )
        except Exception: pass
        
        # SMART ANTI-SPAM WARNING
        warn_key = f"warn_{chat_id}_{user_id}"
        if not WARN_CACHE.is_rate_limited(warn_key):
            try:
                warn_msg = await message.reply_text(
                    f"🛑 **Hold on, {message.from_user.mention}!**\n\nYou must add **{limit - current_adds} more member(s)** to this group before you can send messages.\n\n🔇 **You have been restricted from messaging.**",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📊 How many users have I added?", callback_data="forceadd_check")]])
                )
                await asyncio.sleep(60)
                await warn_msg.delete()
            except Exception: pass
            
        raise StopPropagation # Stop further processing by other plugins


@Client.on_callback_query(filters.regex("^forceadd_check$"))
async def check_adds_button(bot: Client, query: CallbackQuery):
    chat_id, user_id = query.message.chat.id, query.from_user.id
    settings = await get_fa_config(chat_id)
    
    if settings["limit"] == 0:
        return await query.answer("Force Add is not active in this group.", show_alert=True)
        
    current_adds = await get_user_score(chat_id, user_id)
    if current_adds >= settings["limit"]:
        await query.answer(f"✅ You have added {current_adds} members.\nYou are cleared to chat freely!", show_alert=True)
    else:
        await query.answer(f"⚠️ You have added {current_adds}/{settings['limit']} members.\n\nYou need {settings['limit'] - current_adds} more to chat.", show_alert=True)
