import asyncio
import datetime
import html
import re
import time
from logging import ERROR, getLogger

from motor.motor_asyncio import AsyncIOMotorClient
from pyrogram import Client, enums, filters
from pyrogram.errors import (
    ChatWriteForbidden,
    FloodWait,
    InputUserDeactivated,
    MessageNotModified,
    MessageTooLong,
    PeerIdInvalid,
    QueryIdInvalid,
    UserDeactivated,
    UserDeactivatedBan,
    UserIsBlocked,
)
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

import info
from database.users_chats_db import db as _db

# Safe optional import for plugin_db
try:
    from database.plugin_dbs import plugin_db as _plugin_db
except ImportError:
    _plugin_db = None

logger = getLogger(__name__)
logger.setLevel(ERROR)

# ============================================================
# ⚙️ MONGODB PERSISTENT TASKS & PROMOS SETUP
# ============================================================
_broadcast_col = None
_promo_col = None
try:
    _DB_CLIENT = AsyncIOMotorClient(info.DATABASE_URI)
    _BOT_DB = _DB_CLIENT[info.DATABASE_NAME]
    _broadcast_col = _BOT_DB["broadcast_tasks"]
    _promo_col = _BOT_DB["promotional_links"]
except Exception as e:
    logger.error(f"Failed to init Broadcast DB: {e}")

DELETE_DELAY = int(getattr(info, "BROADCAST_DELETE_TIME", 24 * 3600))

worker_started = False
_WORKER_TASK = None

# Cancellation flags for active broadcasts
_CANCEL_USER_BCAST = False
_CANCEL_GROUP_BCAST = False


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


async def is_callback_user_admin(client: Client, query: CallbackQuery) -> bool:
    if not query or not query.from_user:
        return False
    if query.from_user.id in get_admin_list():
        return True
    if (
        query.message
        and query.message.chat
        and query.message.chat.type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]
    ):
        try:
            member = await client.get_chat_member(
                query.message.chat.id, query.from_user.id
            )
            return member.status in [
                enums.ChatMemberStatus.ADMINISTRATOR,
                enums.ChatMemberStatus.OWNER,
            ]
        except Exception:
            pass
    return False


async def admin_check(_, client: Client, message: Message) -> bool:
    return await is_user_admin(client, message)


admin_filter = filters.create(admin_check)


def get_progress_bar(current: int, total: int) -> str:
    if total <= 0:
        return "[░░░░░░░░░░] 0.0%"
    percent = min(100.0, (current / total) * 100)
    filled = int(percent / 10)
    return f"[{'█' * filled}{'░' * (10 - filled)}] {percent:.1f}%"


# ============================================================
# 📢 UNBREAKABLE PROMO STORAGE HELPERS (MULTI-DB SYNC)
# ============================================================
async def safe_add_promo(text: str, url: str):
    if _plugin_db is not None and hasattr(_plugin_db, "add_promo"):
        try:
            await _plugin_db.add_promo(text, url)
        except Exception:
            pass
    if _promo_col is not None:
        try:
            await _promo_col.update_one(
                {"url": url},
                {"$set": {"text": text, "url": url, "updated_at": int(time.time())}},
                upsert=True,
            )
        except Exception:
            pass


async def safe_del_promo(url: str) -> bool:
    deleted = False
    if _plugin_db is not None and hasattr(_plugin_db, "del_promo"):
        try:
            if await _plugin_db.del_promo(url):
                deleted = True
        except Exception:
            pass
    if _promo_col is not None:
        try:
            res = await _promo_col.delete_many({"url": url})
            if res.deleted_count > 0:
                deleted = True
        except Exception:
            pass
    return deleted


async def safe_get_all_promos() -> list[dict]:
    promos = []
    seen_urls = set()

    if _plugin_db is not None and hasattr(_plugin_db, "get_all_promos"):
        try:
            db_promos = await _plugin_db.get_all_promos()
            if db_promos:
                for p in db_promos:
                    if isinstance(p, dict) and p.get("url") and p.get("text"):
                        seen_urls.add(p["url"])
                        promos.append({"text": str(p["text"]), "url": str(p["url"])})
        except Exception:
            pass

    if _promo_col is not None:
        try:
            cursor = _promo_col.find({})
            docs = await cursor.to_list(length=100)
            for d in docs:
                u = d.get("url")
                t = d.get("text")
                if u and t and u not in seen_urls:
                    seen_urls.add(u)
                    promos.append({"text": str(t), "url": str(u)})
        except Exception:
            pass

    return promos


async def get_promo_buttons() -> list[InlineKeyboardButton]:
    promos = await safe_get_all_promos()
    return [InlineKeyboardButton(p["text"], url=p["url"]) for p in promos]


def _merge_reply_markup_with_promos(
    base_markup: InlineKeyboardMarkup | None, promo_btns: list[InlineKeyboardButton]
) -> InlineKeyboardMarkup | None:
    rows = []
    existing_urls = set()
    if base_markup and getattr(base_markup, "inline_keyboard", None):
        for r in base_markup.inline_keyboard:
            rows.append(list(r))
            for b in r:
                if getattr(b, "url", None):
                    existing_urls.add(b.url)

    for p_btn in promo_btns:
        if p_btn.url not in existing_urls:
            rows.append([p_btn])

    return InlineKeyboardMarkup(rows) if rows else None


# ============================================================
# 🕰️ PERSISTENT BACKGROUND WORKER
# ============================================================
async def bcast_cleaner_worker(bot: Client):
    """Permanently checks DB for expired broadcast messages to delete."""
    if _broadcast_col is None:
        return
    while True:
        try:
            now = time.time()
            cursor = _broadcast_col.find({"delete_at": {"$lte": now}})
            docs = await cursor.to_list(length=100)

            for doc in docs:
                try:
                    await bot.delete_messages(
                        chat_id=doc["chat_id"], message_ids=doc["message_id"]
                    )
                except Exception:
                    pass
                await _broadcast_col.delete_one({"_id": doc["_id"]})
        except Exception:
            pass
        await asyncio.sleep(60)


@Client.on_message(filters.group | filters.private, group=-100)
async def init_worker(bot: Client, message: Message):
    global worker_started, _WORKER_TASK
    if not worker_started:
        worker_started = True
        _WORKER_TASK = asyncio.create_task(bcast_cleaner_worker(bot))


# ============================================================
# 📤 3-LAYER "NEVER FAIL" BROADCAST ENGINE
# ============================================================
async def send_and_schedule_delete(
    bot: Client,
    chat_id: int,
    message: Message,
    custom_markup: InlineKeyboardMarkup | None = None,
    pin_msg: bool = False,
):
    """
    3-Layer Fallback Engine:
    Layer 1: Copy Message (with merged promo/original inline keyboard)
    Layer 2: Forward Message
    Layer 3: Send Raw Media/Text
    """
    try:
        sent_msg = None
        markup_to_use = custom_markup or message.reply_markup

        # LAYER 1: Copy
        try:
            sent_msg = await message.copy(
                chat_id=chat_id,
                reply_markup=markup_to_use,
                disable_notification=True,
            )
        except FloodWait as e:
            await asyncio.sleep(e.value + 1)
            sent_msg = await message.copy(
                chat_id=chat_id,
                reply_markup=markup_to_use,
                disable_notification=True,
            )
        except Exception:
            # LAYER 2: Forward
            try:
                sent_msg = await message.forward(
                    chat_id=chat_id, disable_notification=True
                )
            except FloodWait as e:
                await asyncio.sleep(e.value + 1)
                sent_msg = await message.forward(
                    chat_id=chat_id, disable_notification=True
                )
            except Exception:
                # LAYER 3: Raw Send
                cap_html = (
                    getattr(message.caption, "html", str(message.caption))
                    if message.caption
                    else None
                )
                txt_html = (
                    getattr(message.text, "html", str(message.text))
                    if message.text
                    else None
                )
                if message.photo:
                    sent_msg = await bot.send_photo(
                        chat_id,
                        message.photo.file_id,
                        caption=cap_html,
                        reply_markup=markup_to_use,
                        disable_notification=True,
                        parse_mode=enums.ParseMode.HTML,
                    )
                elif message.video:
                    sent_msg = await bot.send_video(
                        chat_id,
                        message.video.file_id,
                        caption=cap_html,
                        reply_markup=markup_to_use,
                        disable_notification=True,
                        parse_mode=enums.ParseMode.HTML,
                    )
                elif message.document:
                    sent_msg = await bot.send_document(
                        chat_id,
                        message.document.file_id,
                        caption=cap_html,
                        reply_markup=markup_to_use,
                        disable_notification=True,
                        parse_mode=enums.ParseMode.HTML,
                    )
                elif message.audio:
                    sent_msg = await bot.send_audio(
                        chat_id,
                        message.audio.file_id,
                        caption=cap_html,
                        reply_markup=markup_to_use,
                        disable_notification=True,
                        parse_mode=enums.ParseMode.HTML,
                    )
                elif message.animation:
                    sent_msg = await bot.send_animation(
                        chat_id,
                        message.animation.file_id,
                        caption=cap_html,
                        reply_markup=markup_to_use,
                        disable_notification=True,
                        parse_mode=enums.ParseMode.HTML,
                    )
                elif message.sticker:
                    sent_msg = await bot.send_sticker(
                        chat_id,
                        message.sticker.file_id,
                        reply_markup=markup_to_use,
                        disable_notification=True,
                    )
                elif txt_html:
                    sent_msg = await bot.send_message(
                        chat_id,
                        txt_html,
                        reply_markup=markup_to_use,
                        disable_notification=True,
                        parse_mode=enums.ParseMode.HTML,
                    )

        if sent_msg:
            if pin_msg:
                try:
                    await sent_msg.pin(disable_notification=True, both_sides=True)
                except Exception:
                    pass

            if _broadcast_col is not None and DELETE_DELAY > 0:
                await _broadcast_col.insert_one(
                    {
                        "chat_id": chat_id,
                        "message_id": sent_msg.id,
                        "delete_at": time.time() + DELETE_DELAY,
                    }
                )
            return 200, None
        return 500, "Unknown Error"

    except FloodWait as e:
        await asyncio.sleep(e.value + 1)
        return await send_and_schedule_delete(
            bot, chat_id, message, custom_markup=custom_markup, pin_msg=pin_msg
        )
    except (
        UserIsBlocked,
        InputUserDeactivated,
        UserDeactivated,
        UserDeactivatedBan,
    ):
        return 400, "Blocked/Deleted"
    except PeerIdInvalid:
        return 400, "Invalid"
    except ChatWriteForbidden:
        return 400, "Left"
    except MessageTooLong:
        return 400, "MEDIA_CAPTION_TOO_LONG"
    except Exception as e:
        return 500, str(e)


# ============================================================
# 👤 USER BROADCAST (/broadcast, /bcast, /pinbroadcast)
# ============================================================
@Client.on_message(
    filters.command(["broadcast", "bcast", "pinbroadcast"])
    & admin_filter
    & filters.incoming
)
async def user_broadcast(bot: Client, message: Message):
    global _CANCEL_USER_BCAST
    b_msg = message.reply_to_message
    if not b_msg:
        return await message.reply_text(
            "⚙️ <b>Usage:</b>\n"
            "Reply to any message (text, photo, video, file, or sticker) with:\n"
            "• <code>/broadcast</code> — Broadcast to all users\n"
            "• <code>/pinbroadcast</code> — Broadcast and pin in user PMs",
            parse_mode=enums.ParseMode.HTML,
        )

    _CANCEL_USER_BCAST = False
    pin_mode = message.command[0].lower() == "pinbroadcast" or (
        len(message.command) > 1 and "pin" in message.command[1].lower()
    )

    cancel_kb = InlineKeyboardMarkup(
        [[InlineKeyboardButton("🛑 Stop Broadcast", callback_data="bcast_cancel:user")]]
    )
    status_msg = await message.reply_text(
        "⏳ <b>Fetching user database...</b>",
        reply_markup=cancel_kb,
        parse_mode=enums.ParseMode.HTML,
    )

    try:
        users_cursor = await _db.get_all_users()
        users = (
            await users_cursor.to_list(length=None)
            if hasattr(users_cursor, "to_list")
            else list(users_cursor)
        )
    except Exception as e:
        return await status_msg.edit_text(
            f"❌ <b>Database Error:</b> <code>{html.escape(str(e))}</code>",
            parse_mode=enums.ParseMode.HTML,
        )

    total_users = len(users)
    if total_users == 0:
        return await status_msg.edit_text(
            "⚠️ <b>No users found in the database.</b>",
            parse_mode=enums.ParseMode.HTML,
        )

    promo_btns = await get_promo_buttons()
    merged_markup = _merge_reply_markup_with_promos(b_msg.reply_markup, promo_btns)

    await status_msg.edit_text(
        f"🚀 <b>Broadcasting to <code>{total_users}</code> users...</b>",
        reply_markup=cancel_kb,
        parse_mode=enums.ParseMode.HTML,
    )
    start_time = time.time()
    done = success = blocked = failed = 0

    for user in users:
        if _CANCEL_USER_BCAST:
            time_taken = datetime.timedelta(seconds=int(time.time() - start_time))
            return await status_msg.edit_text(
                f"🛑 <b>User Broadcast Cancelled by Admin!</b>\n\n"
                f"🕒 <b>Elapsed:</b> <code>{time_taken}</code>\n"
                f"📦 <b>Processed:</b> <code>{done}/{total_users}</code>\n"
                f"✅ <b>Sent:</b> <code>{success}</code>\n"
                f"🚫 <b>Removed (Dead):</b> <code>{blocked}</code>\n"
                f"⚠️ <b>Failed:</b> <code>{failed}</code>",
                parse_mode=enums.ParseMode.HTML,
            )

        raw_uid = user.get("id") or user.get("user_id")
        if not raw_uid:
            done += 1
            failed += 1
            continue

        try:
            user_id = int(raw_uid)
        except (ValueError, TypeError):
            done += 1
            failed += 1
            continue

        status, _ = await send_and_schedule_delete(
            bot, user_id, b_msg, custom_markup=merged_markup, pin_msg=pin_mode
        )

        if status == 200:
            success += 1
        elif status == 400:
            blocked += 1
            try:
                await _db.delete_user(user_id)
            except Exception:
                pass
        else:
            failed += 1

        done += 1
        if done % 25 == 0 or done == total_users:
            try:
                progress = get_progress_bar(done, total_users)
                await status_msg.edit_text(
                    f"📢 <b>User Broadcast Progress</b>\n<code>{progress}</code>\n\n"
                    f"👥 <b>Total:</b> <code>{total_users}</code>\n"
                    f"✅ <b>Sent:</b> <code>{success}</code>\n"
                    f"🚫 <b>Dead/Blocked:</b> <code>{blocked}</code>\n"
                    f"⚠️ <b>Failed:</b> <code>{failed}</code>\n"
                    f"📦 <b>Processed:</b> <code>{done}/{total_users}</code>",
                    reply_markup=cancel_kb,
                    parse_mode=enums.ParseMode.HTML,
                )
            except FloodWait as e:
                await asyncio.sleep(e.value + 1)
            except Exception:
                pass

        await asyncio.sleep(0.05)

    time_taken = datetime.timedelta(seconds=int(time.time() - start_time))
    hours, minutes = DELETE_DELAY // 3600, (DELETE_DELAY % 3600) // 60
    time_str = f"{hours} hours" if hours > 0 else f"{minutes} minutes"

    await status_msg.edit_text(
        f"✅ <b>User Broadcast Completed!</b>\n\n"
        f"🕒 <b>Duration:</b> <code>{time_taken}</code>\n"
        f"👥 <b>Total:</b> <code>{total_users}</code>\n"
        f"✅ <b>Successful:</b> <code>{success}</code>\n"
        f"🚫 <b>Removed (Dead):</b> <code>{blocked}</code>\n"
        f"⚠️ <b>Failed:</b> <code>{failed}</code>\n\n"
        f"⏳ <i>These messages will vanish silently in {time_str}.</i>",
        parse_mode=enums.ParseMode.HTML,
    )


# ============================================================
# 🏘️ GROUP BROADCAST (/group_broadcast, /grp_broadcast, /gbcast)
# ============================================================
@Client.on_message(
    filters.command(["group_broadcast", "grp_broadcast", "gbcast"])
    & admin_filter
    & filters.incoming
)
async def group_broadcast(bot: Client, message: Message):
    global _CANCEL_GROUP_BCAST
    b_msg = message.reply_to_message
    if not b_msg:
        return await message.reply_text(
            "⚙️ <b>Usage:</b>\n"
            "Reply to any message with <code>/group_broadcast</code> (or <code>/gbcast</code>) to broadcast it to all connected groups.",
            parse_mode=enums.ParseMode.HTML,
        )

    _CANCEL_GROUP_BCAST = False
    pin_mode = len(message.command) > 1 and "pin" in message.command[1].lower()

    cancel_kb = InlineKeyboardMarkup(
        [[InlineKeyboardButton("🛑 Stop Broadcast", callback_data="bcast_cancel:group")]]
    )
    status_msg = await message.reply_text(
        "⏳ <b>Fetching chat database...</b>",
        reply_markup=cancel_kb,
        parse_mode=enums.ParseMode.HTML,
    )

    try:
        chats_cursor = await _db.get_all_chats()
        chats = (
            await chats_cursor.to_list(length=None)
            if hasattr(chats_cursor, "to_list")
            else list(chats_cursor)
        )
    except Exception as e:
        return await status_msg.edit_text(
            f"❌ <b>Database Error:</b> <code>{html.escape(str(e))}</code>",
            parse_mode=enums.ParseMode.HTML,
        )

    total_chats = len(chats)
    if total_chats == 0:
        return await status_msg.edit_text(
            "⚠️ <b>No groups found in the database.</b>",
            parse_mode=enums.ParseMode.HTML,
        )

    promo_btns = await get_promo_buttons()
    merged_markup = _merge_reply_markup_with_promos(b_msg.reply_markup, promo_btns)

    await status_msg.edit_text(
        f"🚀 <b>Broadcasting to <code>{total_chats}</code> groups...</b>",
        reply_markup=cancel_kb,
        parse_mode=enums.ParseMode.HTML,
    )
    start_time = time.time()
    done = success = left = failed = 0

    for chat in chats:
        if _CANCEL_GROUP_BCAST:
            time_taken = datetime.timedelta(seconds=int(time.time() - start_time))
            return await status_msg.edit_text(
                f"🛑 <b>Group Broadcast Cancelled by Admin!</b>\n\n"
                f"🕒 <b>Elapsed:</b> <code>{time_taken}</code>\n"
                f"📦 <b>Processed:</b> <code>{done}/{total_chats}</code>\n"
                f"✅ <b>Sent:</b> <code>{success}</code>\n"
                f"🚷 <b>Kicked/Left:</b> <code>{left}</code>\n"
                f"⚠️ <b>Failed:</b> <code>{failed}</code>",
                parse_mode=enums.ParseMode.HTML,
            )

        raw_cid = chat.get("id") or chat.get("chat_id")
        if not raw_cid:
            done += 1
            failed += 1
            continue

        try:
            chat_id = int(raw_cid)
        except (ValueError, TypeError):
            done += 1
            failed += 1
            continue

        status, reason = await send_and_schedule_delete(
            bot, chat_id, b_msg, custom_markup=merged_markup, pin_msg=pin_mode
        )

        if status == 200:
            success += 1
        elif status == 400 and reason in ["Left", "Blocked/Deleted"]:
            left += 1
            try:
                await _db.disable_chat(chat_id, "Bot Removed")
            except Exception:
                pass
        else:
            failed += 1

        done += 1
        if done % 15 == 0 or done == total_chats:
            try:
                progress = get_progress_bar(done, total_chats)
                await status_msg.edit_text(
                    f"🏘️ <b>Group Broadcast Progress</b>\n<code>{progress}</code>\n\n"
                    f"💬 <b>Total:</b> <code>{total_chats}</code>\n"
                    f"✅ <b>Sent:</b> <code>{success}</code>\n"
                    f"🚷 <b>Kicked/Left:</b> <code>{left}</code>\n"
                    f"⚠️ <b>Failed:</b> <code>{failed}</code>\n"
                    f"📦 <b>Processed:</b> <code>{done}/{total_chats}</code>",
                    reply_markup=cancel_kb,
                    parse_mode=enums.ParseMode.HTML,
                )
            except FloodWait as e:
                await asyncio.sleep(e.value + 1)
            except Exception:
                pass

        await asyncio.sleep(0.2)

    time_taken = datetime.timedelta(seconds=int(time.time() - start_time))
    hours, minutes = DELETE_DELAY // 3600, (DELETE_DELAY % 3600) // 60
    time_str = f"{hours} hours" if hours > 0 else f"{minutes} minutes"

    await status_msg.edit_text(
        f"✅ <b>Group Broadcast Completed!</b>\n\n"
        f"🕒 <b>Duration:</b> <code>{time_taken}</code>\n"
        f"💬 <b>Total:</b> <code>{total_chats}</code>\n"
        f"✅ <b>Successful:</b> <code>{success}</code>\n"
        f"🚷 <b>Removed From:</b> <code>{left}</code>\n"
        f"⚠️ <b>Failed:</b> <code>{failed}</code>\n\n"
        f"⏳ <i>These messages will vanish silently in {time_str}.</i>",
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_callback_query(filters.regex(r"^bcast_cancel:(user|group)$"))
async def cancel_broadcast_cb(client: Client, query: CallbackQuery):
    global _CANCEL_USER_BCAST, _CANCEL_GROUP_BCAST
    if not await is_callback_user_admin(client, query):
        return await query.answer("❌ Unauthorized: Admins only!", show_alert=True)

    target = query.matches[0].group(1)
    if target == "user":
        _CANCEL_USER_BCAST = True
    else:
        _CANCEL_GROUP_BCAST = True
    await query.answer("🛑 Stopping broadcast...", show_alert=True)


# ============================================================
# 📢 PROMOTIONS MANAGEMENT (/addpromo, /delpromo, /listpromos)
# ============================================================
def _parse_promo_args(raw_args: str) -> tuple[str | None, str | None]:
    """
    Flexibly parses promo button text and URL from:
    1. "Button Text" https://example.com (supports straight or curly quotes)
    2. Button Text | https://example.com
    3. Button Text - https://example.com
    """
    if not raw_args:
        return None, None

    # Normalize smart/curly quotes to standard double quotes
    normalized = (
        raw_args.replace("“", '"')
        .replace("”", '"')
        .replace("‘", "'")
        .replace("’", "'")
        .strip()
    )

    # 1. Double or single quoted text followed by URL
    m = re.search(r'["\']([^"\']+)["\']\s+(https?://\S+|t\.me/\S+)', normalized)
    if m:
        btn_text, btn_url = m.group(1).strip(), m.group(2).strip()
    elif "|" in normalized:
        parts = normalized.split("|", 1)
        btn_text, btn_url = parts[0].strip(), parts[1].strip()
    else:
        # Match last URL token in string
        url_match = re.search(r"(https?://\S+|t\.me/\S+)$", normalized)
        if not url_match:
            return None, None
        btn_url = url_match.group(1).strip()
        btn_text = normalized[: url_match.start()].strip().strip("-").strip()

    if not btn_text or not btn_url:
        return None, None

    if btn_url.startswith("t.me/"):
        btn_url = f"https://{btn_url}"

    return btn_text, btn_url


async def _build_promos_panel() -> tuple[str, InlineKeyboardMarkup]:
    promos = await safe_get_all_promos()
    if not promos:
        text = (
            "⚠️ <b>No active promotional links found in the database.</b>\n\n"
            "💡 <b>Add one using:</b>\n"
            "<code>/addpromo \"Button Text\" https://t.me/your_channel</code>"
        )
        markup = InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔐 Close", callback_data="promo_ctl:close")]]
        )
        return text, markup

    text = "📢 <b>Current Promotional Links:</b>\n\n"
    buttons = []
    for i, p in enumerate(promos, 1):
        p_text = html.escape(p["text"])
        p_url = html.escape(p["url"])
        text += f"<b>{i}. Text:</b> <code>{p_text}</code>\n<b>🔗 URL:</b> {p_url}\n\n"
        buttons.append(
            [
                InlineKeyboardButton(f"🔗 {p['text'][:24]}", url=p["url"]),
                InlineKeyboardButton(
                    f"🗑️ Delete #{i}", callback_data=f"promo_ctl:del:{i - 1}"
                ),
            ]
        )

    buttons.append(
        [
            InlineKeyboardButton("🧹 Clear All", callback_data="promo_ctl:clear_all"),
            InlineKeyboardButton("🔐 Close", callback_data="promo_ctl:close"),
        ]
    )
    return text, InlineKeyboardMarkup(buttons)


@Client.on_message(
    filters.command("addpromo") & admin_filter & (filters.private | filters.group)
)
async def add_promo_handler(bot: Client, message: Message):
    raw_args = message.text.split(None, 1)[1] if len(message.command) > 1 else ""
    btn_text, btn_url = _parse_promo_args(raw_args)

    if not btn_text or not btn_url:
        return await message.reply_text(
            "⚙️ <b>Usage:</b>\n"
            "• <code>/addpromo \"Button Text\" https://example.com</code>\n"
            "• Or: <code>/addpromo Button Text | https://t.me/channel</code>",
            parse_mode=enums.ParseMode.HTML,
        )

    await safe_add_promo(btn_text, btn_url)
    await message.reply_text(
        f"✅ <b>Promo Added Successfully!</b>\n\n"
        f"<b>Text:</b> <code>{html.escape(btn_text)}</code>\n"
        f"<b>URL:</b> {html.escape(btn_url)}",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton(btn_text, url=btn_url)]]
        ),
        disable_web_page_preview=True,
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(
    filters.command("delpromo") & admin_filter & (filters.private | filters.group)
)
async def del_promo_handler(bot: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text(
            "⚙️ <b>Usage:</b>\n"
            "<code>/delpromo https://example.com</code>\n\n"
            "💡 Or use <code>/listpromos</code> to delete promos interactively with buttons.",
            parse_mode=enums.ParseMode.HTML,
        )

    btn_url = message.command[1].strip()
    if btn_url.startswith("t.me/"):
        btn_url = f"https://{btn_url}"

    deleted = await safe_del_promo(btn_url)
    if deleted:
        await message.reply_text(
            f"🗑️ <b>Promo deleted successfully!</b>\n\n<b>URL:</b> {html.escape(btn_url)}",
            disable_web_page_preview=True,
            parse_mode=enums.ParseMode.HTML,
        )
    else:
        await message.reply_text(
            f"❌ <b>Promo not found!</b>\n\nCould not find any promo matching URL: {html.escape(btn_url)}",
            disable_web_page_preview=True,
            parse_mode=enums.ParseMode.HTML,
        )


@Client.on_message(
    filters.command(["listpromos", "promos"])
    & admin_filter
    & (filters.private | filters.group)
)
async def list_promo_handler(bot: Client, message: Message):
    text, markup = await _build_promos_panel()
    await message.reply_text(
        text,
        reply_markup=markup,
        disable_web_page_preview=True,
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_callback_query(filters.regex(r"^promo_ctl:(close|clear_all|del:\d+)$"))
async def promo_callbacks(client: Client, query: CallbackQuery):
    if not await is_callback_user_admin(client, query):
        return await query.answer("❌ Unauthorized: Admins only!", show_alert=True)

    action = query.matches[0].group(1)
    try:
        if action == "close":
            await query.answer("Closed!")
            return await query.message.delete()

        if action == "clear_all":
            promos = await safe_get_all_promos()
            for p in promos:
                await safe_del_promo(p["url"])
            await query.answer("🧹 All promos cleared!", show_alert=True)

        elif action.startswith("del:"):
            idx = int(action.split(":")[1])
            promos = await safe_get_all_promos()
            if 0 <= idx < len(promos):
                target_url = promos[idx]["url"]
                await safe_del_promo(target_url)
                await query.answer("🗑️ Promo deleted!", show_alert=True)
            else:
                await query.answer("⚠️ Promo already removed!", show_alert=True)

        text, markup = await _build_promos_panel()
        await query.message.edit_text(
            text,
            reply_markup=markup,
            disable_web_page_preview=True,
            parse_mode=enums.ParseMode.HTML,
        )
    except MessageNotModified:
        pass
    except QueryIdInvalid:
        pass
    except Exception as e:
        logger.error(f"Promo callback error: {e}")
