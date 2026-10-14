import asyncio
import inspect
import time
from logging import ERROR, getLogger
from typing import Dict

from motor.motor_asyncio import AsyncIOMotorClient
from pyrogram import Client, StopPropagation, enums, filters
from pyrogram.errors import MessageNotModified, QueryIdInvalid
from pyrogram.types import (
    CallbackQuery,
    ChatPermissions,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

import info

logger = getLogger(__name__)
logger.setLevel(ERROR)

# ============================================================
# ⚙️ ISOLATED MONGODB ENGINE
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


async def set_fa_config(chat_id: int, limit: int, mode: str):
    if fa_config_db is not None:
        await fa_config_db.update_one(
            {"chat_id": int(chat_id)},
            {"$set": {"limit": int(limit), "mode": str(mode)}},
            upsert=True,
        )


async def get_fa_config(chat_id: int):
    if fa_config_db is not None:
        doc = await fa_config_db.find_one({"chat_id": int(chat_id)})
        if doc:
            return {"limit": int(doc.get("limit", 0)), "mode": doc.get("mode", "all")}
    return {"limit": 0, "mode": "all"}


async def add_user_score(chat_id: int, user_id: int, count: int):
    if fa_users_db is not None and count > 0:
        timestamps = [int(time.time())] * count
        await fa_users_db.update_one(
            {"chat_id": int(chat_id), "user_id": int(user_id)},
            {"$push": {"adds": {"$each": timestamps}}},
            upsert=True,
        )


async def get_user_score(chat_id: int, user_id: int) -> int:
    if fa_users_db is not None:
        doc = await fa_users_db.find_one(
            {"chat_id": int(chat_id), "user_id": int(user_id)}
        )
        if doc and "adds" in doc:
            return len(doc["adds"])
    return 0


async def mark_new_user(chat_id: int, user_id: int):
    if fa_users_db is not None:
        await fa_users_db.update_one(
            {"chat_id": int(chat_id), "user_id": int(user_id)},
            {"$set": {"is_new": True}},
            upsert=True,
        )


async def is_new_user(chat_id: int, user_id: int) -> bool:
    if fa_users_db is not None:
        doc = await fa_users_db.find_one(
            {"chat_id": int(chat_id), "user_id": int(user_id)}
        )
        return bool(doc.get("is_new", False)) if doc else False
    return False


# ============================================================
# 🛡️ SAFE CHAT PERMISSIONS BUILDER (CROSS-VERSION COMPATIBLE)
# ============================================================
_VALID_PERM_PARAMS = set(
    inspect.signature(ChatPermissions.__init__).parameters.keys()
) - {"self"}


def build_chat_permissions(can_send: bool) -> ChatPermissions:
    desired = {
        "can_send_messages": can_send,
        "can_send_media_messages": can_send,
        "can_send_other_messages": can_send,
        "can_add_web_page_previews": can_send,
        "can_send_audios": can_send,
        "can_send_documents": can_send,
        "can_send_photos": can_send,
        "can_send_videos": can_send,
        "can_send_video_notes": can_send,
        "can_send_voice_notes": can_send,
        "can_send_polls": can_send,
        "can_invite_users": True,
    }
    valid_kwargs = {k: v for k, v in desired.items() if k in _VALID_PERM_PARAMS}
    return ChatPermissions(**valid_kwargs)


async def _delete_later(msg: Message, delay: int):
    await asyncio.sleep(delay)
    try:
        await msg.delete()
    except Exception:
        pass


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
        if len(self._data) >= self._maxsize:
            self._data.clear()
        self._data[key] = now + self._ttl
        return False

    def _cleanup(self, now: float):
        expired = [k for k, exp in self._data.items() if now >= exp]
        for k in expired:
            del self._data[k]


WARN_CACHE = TTLCache(ttl=60)


# ============================================================
# 👑 FULL POWER ADMIN CHECKER (GLOBAL + CHAT + ANONYMOUS)
# ============================================================
def get_admin_list():
    raw_admins = getattr(info, "ADMINS", [])
    if isinstance(raw_admins, (str, int)):
        raw_admins = str(raw_admins).replace(",", " ").split()
    elif isinstance(raw_admins, (list, tuple, set)):
        raw_admins = list(raw_admins)
    else:
        raw_admins = []
    return [int(x) for x in raw_admins if str(x).strip().lstrip("-").isdigit()]


async def is_user_admin(client: Client, message: Message) -> bool:
    if not message:
        return False
    admin_list = get_admin_list()

    # 1. Global Admin Check (Direct User)
    if message.from_user and message.from_user.id in admin_list:
        return True

    # 2. Global Admin Check (Anonymous/Channel sending as Chat)
    if message.sender_chat and message.sender_chat.id in admin_list:
        return True

    # 3. Group Admin Check (Normal & Anonymous Admins)
    if message.chat and message.chat.type in [
        enums.ChatType.GROUP,
        enums.ChatType.SUPERGROUP,
    ]:
        if message.sender_chat and message.sender_chat.id == message.chat.id:
            return True

        if message.from_user:
            try:
                member = await client.get_chat_member(
                    message.chat.id, message.from_user.id
                )
                return member.status in [
                    enums.ChatMemberStatus.ADMINISTRATOR,
                    enums.ChatMemberStatus.OWNER,
                ]
            except Exception:
                pass

    return False


async def is_callback_user_admin(
    client: Client, query: CallbackQuery, chat_id: int = None
) -> bool:
    """Checks if the user clicking the inline button is a Global Admin or Group Admin."""
    if not query or not query.from_user:
        return False
    user_id = query.from_user.id
    if user_id in get_admin_list():
        return True

    target_chat_id = chat_id or (query.message.chat.id if query.message else None)
    if target_chat_id:
        try:
            member = await client.get_chat_member(int(target_chat_id), user_id)
            return member.status in [
                enums.ChatMemberStatus.ADMINISTRATOR,
                enums.ChatMemberStatus.OWNER,
            ]
        except Exception:
            pass
    return False


async def admin_check(_, client: Client, message: Message):
    return await is_user_admin(client, message)


admin_filter = filters.create(admin_check)


# ============================================================
# ⚙️ CONFIGURATION COMMANDS
# ============================================================
@Client.on_message(filters.command("setforceadd") & filters.group & admin_filter)
async def set_force_add(bot: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text(
            "⚙️ <b>Usage:</b> <code>/setforceadd &lt;number&gt;</code>\n"
            "<b>Example:</b> <code>/setforceadd 5</code>",
            parse_mode=enums.ParseMode.HTML,
        )

    try:
        limit = int(message.command[1])
        if limit < 0:
            raise ValueError
    except ValueError:
        return await message.reply_text(
            "❌ <b>Please provide a valid positive number.</b>",
            parse_mode=enums.ParseMode.HTML,
        )

    grp_id = message.chat.id
    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "👥 Force Add for ALL Members",
                    callback_data=f"fa_set_{limit}_all_{grp_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    "🆕 Force Add for ONLY NEW Members",
                    callback_data=f"fa_set_{limit}_new_{grp_id}",
                )
            ],
        ]
    )

    await message.reply_text(
        "🎯 <b>Who should this requirement apply to?</b>\n\n"
        "<i>(Select an option below)</i>",
        reply_markup=kb,
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_callback_query(filters.regex(r"^fa_set_(\d+)_([a-z]+)_(-?\d+)$"))
async def set_forceadd_callback(bot: Client, query: CallbackQuery):
    limit = int(query.matches[0].group(1))
    mode = query.matches[0].group(2)
    grp_id = int(query.matches[0].group(3))

    if not await is_callback_user_admin(bot, query, chat_id=grp_id):
        return await query.answer(
            "❌ Unauthorized: Only group admins can configure Force Add!",
            show_alert=True,
        )

    await set_fa_config(grp_id, limit, mode)
    mode_text = (
        "ALL MEMBERS" if mode == "all" else "ONLY NEW MEMBERS (who join from now on)"
    )

    await query.answer("✅ Force Add Configured!")
    try:
        await query.message.edit_text(
            f"✅ <b>Force Add Configured Successfully!</b>\n\n"
            f"🔢 <b>Limit:</b> <code>{limit} members</code>\n"
            f"🎯 <b>Target:</b> <code>{mode_text}</code>\n"
            f"<i>(Engine is now 100% Active)</i>",
            parse_mode=enums.ParseMode.HTML,
        )
    except MessageNotModified:
        pass


@Client.on_message(filters.command("remforceadd") & filters.group & admin_filter)
async def remove_force_add(bot: Client, message: Message):
    await set_fa_config(message.chat.id, 0, "all")
    await message.reply_text(
        "🗑️ <b>Force Add requirement has been completely removed.</b>",
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(filters.command("getforceadd") & filters.group)
async def get_force_add(bot: Client, message: Message):
    settings = await get_fa_config(message.chat.id)
    if settings["limit"] == 0:
        await message.reply_text(
            "ℹ️ <b>Force Add is currently DISABLED in this group.</b>",
            parse_mode=enums.ParseMode.HTML,
        )
    else:
        target = "Everyone" if settings["mode"] == "all" else "Only New Members"
        await message.reply_text(
            f"ℹ️ <b>Current Requirement:</b> Users must add <code>{settings['limit']}</code> members.\n"
            f"🎯 <b>Applies to:</b> <code>{target}</code>",
            parse_mode=enums.ParseMode.HTML,
        )


# ============================================================
# 📊 LEADERBOARD & STATS LOGIC
# ============================================================
async def generate_leaderboard(
    bot: Client, message: Message, title: str, time_limit_seconds: int = None
):
    if fa_users_db is None:
        return await message.reply_text(
            "❌ <b>Database Error.</b>", parse_mode=enums.ParseMode.HTML
        )

    pipeline = [{"$match": {"chat_id": message.chat.id}}]

    if time_limit_seconds:
        cutoff = int(time.time()) - time_limit_seconds
        pipeline.append(
            {
                "$project": {
                    "user_id": 1,
                    "valid_adds": {
                        "$filter": {
                            "input": {"$ifNull": ["$adds", []]},
                            "as": "timestamp",
                            "cond": {"$gte": ["$$timestamp", cutoff]},
                        }
                    },
                }
            }
        )
        pipeline.append(
            {
                "$project": {
                    "user_id": 1,
                    "score": {"$size": {"$ifNull": ["$valid_adds", []]}},
                }
            }
        )
    else:
        pipeline.append(
            {"$project": {"user_id": 1, "score": {"$size": {"$ifNull": ["$adds", []]}}}}
        )

    pipeline.extend(
        [{"$match": {"score": {"$gt": 0}}}, {"$sort": {"score": -1}}, {"$limit": 10}]
    )
    cursor = fa_users_db.aggregate(pipeline)
    top_users = await cursor.to_list(length=10)

    if not top_users:
        return await message.reply_text(
            f"📊 <b>{title}</b>\n\nNo members have added anyone yet!",
            parse_mode=enums.ParseMode.HTML,
        )

    text = f"📊 <b>{title} (Top 10)</b>\n\n"
    for i, data in enumerate(top_users, 1):
        uid, score = data["user_id"], data["score"]
        try:
            user = await bot.get_users(uid)
            user_name = user.mention if user else f"User {uid}"
        except Exception:
            user_name = f"User <code>{uid}</code>"
        text += f"<b>{i}.</b> {user_name} ➔ <code>{score}</code> added\n"

    await message.reply_text(
        text, disable_web_page_preview=True, parse_mode=enums.ParseMode.HTML
    )


@Client.on_message(filters.command("topaddall") & filters.group)
async def top_add_all(bot: Client, message: Message):
    await generate_leaderboard(bot, message, "All-Time Top Adders", None)


@Client.on_message(filters.command("topadd24") & filters.group)
async def top_add_24(bot: Client, message: Message):
    await generate_leaderboard(bot, message, "Top Adders (Past 24 Hours)", 86400)


@Client.on_message(filters.command("topadd7") & filters.group)
async def top_add_7(bot: Client, message: Message):
    await generate_leaderboard(bot, message, "Top Adders (Past 7 Days)", 604800)


@Client.on_message(filters.command("resetadddaily") & filters.group & admin_filter)
async def reset_add_daily(bot: Client, message: Message):
    if fa_users_db is not None:
        cutoff = int(time.time()) - 86400
        await fa_users_db.update_many(
            {"chat_id": message.chat.id}, {"$pull": {"adds": {"$lt": cutoff}}}
        )
        await message.reply_text(
            "♻️ <b>Daily limits reset!</b> Leaderboards for past 24h have been wiped.",
            parse_mode=enums.ParseMode.HTML,
        )


@Client.on_message(filters.command("resetadd") & filters.group & admin_filter)
async def reset_all_adds(bot: Client, message: Message):
    if fa_users_db is not None:
        await fa_users_db.update_many(
            {"chat_id": message.chat.id}, {"$set": {"adds": []}}
        )
        await message.reply_text(
            "💥 <b>TOTAL RESET!</b> All members' scores are now 0. Everyone must add members again.",
            parse_mode=enums.ParseMode.HTML,
        )


@Client.on_message(filters.command("myadds") & filters.group)
async def my_adds(bot: Client, message: Message):
    if not message.from_user:
        return
    settings = await get_fa_config(message.chat.id)
    if settings["limit"] == 0:
        return await message.reply_text(
            "ℹ️ <b>Force Add is not active in this group.</b>",
            parse_mode=enums.ParseMode.HTML,
        )

    current_adds = await get_user_score(message.chat.id, message.from_user.id)
    if current_adds >= settings["limit"]:
        await message.reply_text(
            f"✅ You have added <b>{current_adds}</b> members. You are cleared to chat freely!",
            parse_mode=enums.ParseMode.HTML,
        )
    else:
        await message.reply_text(
            f"⚠️ You have added <b>{current_adds}/{settings['limit']}</b> members.",
            parse_mode=enums.ParseMode.HTML,
        )


# ============================================================
# 🎯 THE ENGINE: TRACKER & ENFORCER
# ============================================================
@Client.on_message(filters.new_chat_members & filters.group, group=10)
async def track_added_members(bot: Client, message: Message):
    for u in message.new_chat_members:
        if not u.is_bot:
            await mark_new_user(message.chat.id, u.id)

    if not message.from_user:
        return

    settings = await get_fa_config(message.chat.id)
    if settings["limit"] == 0:
        return

    adder_id = message.from_user.id
    added_others = [
        u for u in message.new_chat_members if u.id != adder_id and not u.is_bot
    ]

    if not added_others:
        return

    await add_user_score(message.chat.id, adder_id, len(added_others))
    current_adds = await get_user_score(message.chat.id, adder_id)

    if current_adds >= settings["limit"]:
        try:
            await bot.restrict_chat_member(
                chat_id=message.chat.id,
                user_id=adder_id,
                permissions=build_chat_permissions(can_send=True),
            )
            msg = await bot.send_message(
                chat_id=message.chat.id,
                text=(
                    f"🎉 <b>Congratulations {message.from_user.mention}!</b>\n\n"
                    f"You've added <b>{current_adds}</b> members and met the group requirement. "
                    f"<b>You can now chat freely!</b>"
                ),
                parse_mode=enums.ParseMode.HTML,
            )
            asyncio.create_task(_delete_later(msg, 15))
        except Exception:
            pass


@Client.on_message(
    filters.group
    & ~filters.service
    & ~filters.new_chat_members
    & ~filters.left_chat_member,
    group=-1,
)
async def enforce_force_add(bot: Client, message: Message):
    if await is_user_admin(bot, message):
        return

    user = message.from_user
    if not user or user.is_bot:
        return
    chat_id, user_id = message.chat.id, user.id

    settings = await get_fa_config(chat_id)
    limit = settings["limit"]
    if limit == 0:
        return

    if settings["mode"] == "new" and not await is_new_user(chat_id, user_id):
        return

    text = message.text or message.caption
    if text and text.startswith("/"):
        return

    current_adds = await get_user_score(chat_id, user_id)

    if current_adds < limit:
        try:
            await message.delete()
        except Exception:
            pass

        try:
            await bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=user_id,
                permissions=build_chat_permissions(can_send=False),
            )
        except Exception:
            pass

        warn_key = f"warn_{chat_id}_{user_id}"
        if not WARN_CACHE.is_rate_limited(warn_key):
            try:
                warn_msg = await bot.send_message(
                    chat_id=chat_id,
                    text=(
                        f"🛑 <b>Hold on, {user.mention}!</b>\n\n"
                        f"You must add <b>{limit - current_adds} more member(s)</b> to this group before you can send messages.\n\n"
                        f"🔇 <b>You have been restricted from messaging.</b>"
                    ),
                    reply_markup=InlineKeyboardMarkup(
                        [
                            [
                                InlineKeyboardButton(
                                    "📊 How many users have I added?",
                                    callback_data="forceadd_check",
                                )
                            ]
                        ]
                    ),
                    parse_mode=enums.ParseMode.HTML,
                )
                asyncio.create_task(_delete_later(warn_msg, 60))
            except Exception as e:
                logger.error(f"ForceAdd warning error: {e}")

        raise StopPropagation


@Client.on_callback_query(filters.regex(r"^forceadd_check$"))
async def check_adds_button(bot: Client, query: CallbackQuery):
    if not query.message or not query.from_user:
        return
    chat_id, user_id = query.message.chat.id, query.from_user.id
    settings = await get_fa_config(chat_id)

    try:
        if settings["limit"] == 0:
            return await query.answer(
                "Force Add is not active in this group.", show_alert=True
            )

        current_adds = await get_user_score(chat_id, user_id)
        if current_adds >= settings["limit"]:
            await query.answer(
                f"✅ You have added {current_adds} members.\nYou are cleared to chat freely!",
                show_alert=True,
            )
        else:
            await query.answer(
                f"⚠️ You have added {current_adds}/{settings['limit']} members.\n\nYou need {settings['limit'] - current_adds} more to chat.",
                show_alert=True,
            )
    except QueryIdInvalid:
        pass
