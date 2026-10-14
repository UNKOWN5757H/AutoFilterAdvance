import asyncio
import html
import re
import time
from logging import ERROR, getLogger

from motor.motor_asyncio import AsyncIOMotorClient
from pyrogram import Client, enums, filters
from pyrogram.errors import FloodWait, MessageNotModified, QueryIdInvalid
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

import info
from database.ia_filterdb import Media as _Media
from database.ia_filterdb import unpack_new_file_id

logger = getLogger(__name__)
logger.setLevel(ERROR)

# ============================================================
# ⚙️ MONGODB STORAGE & PERSISTENT COUNTDOWN QUEUE
# ============================================================
_del_db = None
_countdown_col = None

try:
    _DB_CLIENT = AsyncIOMotorClient(info.DATABASE_URI)
    _BOT_DB = _DB_CLIENT[info.DATABASE_NAME]
    _del_db = _BOT_DB["deletion_settings"]
    _countdown_col = _BOT_DB["countdown_tasks"]
except Exception as e:
    logger.error(f"Failed to init Deletion Settings DB: {e}")


def get_media_collection():
    """Safely returns the underlying Motor collection whether Media is a umongo Document or raw collection."""
    return getattr(_Media, "collection", _Media)


async def get_del_setting(key: str, default: int) -> int:
    if _del_db is not None:
        doc = await _del_db.find_one({"_id": "timers"})
        if doc and key in doc:
            return int(doc[key])
    return int(getattr(info, key, default))


async def save_del_setting(key: str, value: int):
    setattr(info, key, value)
    if key == "FILE_AUTO_DELETE":
        setattr(info, "AUTO_DELETE_TIME", value)
        setattr(info, "AUTO_DELETE", value > 0)
    if _del_db is not None:
        await _del_db.update_one({"_id": "timers"}, {"$set": {key: value}}, upsert=True)


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


async def admin_check(_, client: Client, message: Message):
    return await is_user_admin(client, message)


admin_filter = filters.create(admin_check)


def format_countdown_string(seconds_left: int) -> str:
    if seconds_left <= 0:
        return "⏳ Deleting now..."
    m, s = divmod(seconds_left, 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"⏳ Deleting in: {h}h {m}m"
    return f"⏳ Deleting in: {m}m {s}s"


# ============================================================
# ⏱️ ACTIVE LIVE COUNTDOWN BACKGROUND WORKER
# ============================================================
_COUNTDOWN_WORKER_STARTED = False


async def countdown_live_worker(client: Client):
    while True:
        try:
            if _countdown_col is not None:
                now = time.time()
                tasks = await _countdown_col.find().to_list(length=100)
                for task in tasks:
                    chat_id = task["chat_id"]
                    msg_id = task["message_id"]
                    remaining = int(task["delete_at"] - now)

                    if remaining <= 0:
                        try:
                            await client.delete_messages(chat_id, msg_id)
                        except Exception:
                            pass
                        await _countdown_col.delete_one({"_id": task["_id"]})
                        continue

                    last_update = task.get("last_updated", 0)
                    if now - last_update >= 30:
                        timer_label = format_countdown_string(remaining)
                        original_buttons = task.get("buttons", [])

                        new_keyboard = []
                        for row in original_buttons:
                            btn_row = []
                            for b in row:
                                if b.get("url"):
                                    btn_row.append(
                                        InlineKeyboardButton(b["text"], url=b["url"])
                                    )
                                elif b.get("callback_data"):
                                    btn_row.append(
                                        InlineKeyboardButton(
                                            b["text"], callback_data=b["callback_data"]
                                        )
                                    )
                            if btn_row:
                                new_keyboard.append(btn_row)
                        new_keyboard.append(
                            [
                                InlineKeyboardButton(
                                    timer_label, callback_data="noop_countdown"
                                )
                            ]
                        )

                        try:
                            await client.edit_message_reply_markup(
                                chat_id,
                                msg_id,
                                reply_markup=InlineKeyboardMarkup(new_keyboard),
                            )
                            await _countdown_col.update_one(
                                {"_id": task["_id"]}, {"$set": {"last_updated": now}}
                            )
                        except MessageNotModified:
                            await _countdown_col.update_one(
                                {"_id": task["_id"]}, {"$set": {"last_updated": now}}
                            )
                        except FloodWait as e:
                            await asyncio.sleep(e.value + 1)
                        except Exception:
                            await _countdown_col.delete_one({"_id": task["_id"]})
        except Exception as e:
            logger.error(f"Countdown worker error: {e}")
        await asyncio.sleep(10)


@Client.on_message(filters.all, group=-99)
async def start_countdown_worker(client: Client, message: Message):
    global _COUNTDOWN_WORKER_STARTED
    if not _COUNTDOWN_WORKER_STARTED:
        _COUNTDOWN_WORKER_STARTED = True
        try:
            saved_timer = await get_del_setting("FILE_AUTO_DELETE", 1800)
            setattr(info, "FILE_AUTO_DELETE", saved_timer)
            setattr(info, "AUTO_DELETE_TIME", saved_timer)
        except Exception:
            pass
        asyncio.create_task(countdown_live_worker(client))


async def schedule_file_with_countdown(
    client: Client, sent_message: Message, delay_seconds: int, base_buttons: list = None
):
    if not sent_message or delay_seconds <= 0 or _countdown_col is None:
        return

    now = time.time()
    serialized_btns = []
    if base_buttons:
        for row in base_buttons:
            row_data = [
                {
                    "text": btn.text,
                    "url": getattr(btn, "url", None),
                    "callback_data": getattr(btn, "callback_data", None),
                }
                for btn in row
            ]
            serialized_btns.append(row_data)

    await _countdown_col.insert_one(
        {
            "chat_id": sent_message.chat.id,
            "message_id": sent_message.id,
            "delete_at": now + delay_seconds,
            "last_updated": 0,
            "buttons": serialized_btns,
        }
    )


@Client.on_callback_query(filters.regex(r"^noop_countdown$"))
async def noop_countdown_cb(client: Client, query: CallbackQuery):
    try:
        await query.answer(
            "⚠️ This file will be automatically deleted when the timer ends. Forward or save it now!",
            show_alert=True,
        )
    except QueryIdInvalid:
        pass


# ============================================================
# 🧹 DUPLICATE FILE PURGER ENGINE (/purgeduplicates)
# ============================================================
def get_resolution_score(filename: str) -> int:
    name = (filename or "").lower()
    if any(q in name for q in ["2160p", "4k", "uhd"]):
        return 4
    if any(q in name for q in ["1440p", "2k"]):
        return 3
    if any(q in name for q in ["1080p", "fhd"]):
        return 2
    if any(q in name for q in ["720p", "hd"]):
        return 1
    return 0


@Client.on_message(filters.command("purgeduplicates") & admin_filter)
async def purge_duplicates_cmd(client: Client, message: Message):
    media_col = get_media_collection()
    if media_col is None:
        return await message.reply_text(
            "❌ <b>Media database collection is unavailable.</b>",
            parse_mode=enums.ParseMode.HTML,
        )

    status = await message.reply_text(
        "🔍 <b>Scanning database for duplicate files...</b>\n"
        "<i>This might take some time on large databases.</i>",
        parse_mode=enums.ParseMode.HTML,
    )

    try:
        pipeline = [
            {
                "$group": {
                    "_id": "$file_name",
                    "count": {"$sum": 1},
                    "docs": {
                        "$push": {
                            "id": "$_id",
                            "size": "$file_size",
                            "name": "$file_name",
                        }
                    },
                }
            },
            {"$match": {"count": {"$gt": 1}}},
        ]

        cursor = media_col.aggregate(pipeline, allowDiskUse=True)
        duplicate_groups = await cursor.to_list(length=None)

        if not duplicate_groups:
            return await status.edit_text(
                "✅ <b>Database is squeaky clean!</b> No duplicate files found.",
                parse_mode=enums.ParseMode.HTML,
            )

        total_duplicates = 0
        deleted_ids = []

        for group in duplicate_groups:
            docs = group.get("docs", [])
            docs.sort(
                key=lambda d: (
                    get_resolution_score(d.get("name", "")),
                    d.get("size", 0) or 0,
                ),
                reverse=True,
            )
            to_remove = docs[1:]
            for d in to_remove:
                deleted_ids.append(d["id"])
                total_duplicates += 1

        for i in range(0, len(deleted_ids), 500):
            batch = deleted_ids[i : i + 500]
            await media_col.delete_many({"_id": {"$in": batch}})

        await status.edit_text(
            f"🧹 <b>Duplicate File Purge Completed!</b>\n\n"
            f"📁 <b>Duplicate Sets Found:</b> <code>{len(duplicate_groups)}</code>\n"
            f"🗑️ <b>Redundant Copies Removed:</b> <code>{total_duplicates}</code>\n"
            f"✨ <b>Preserved:</b> Best quality copies (Highest resolution & bitrates).",
            parse_mode=enums.ParseMode.HTML,
        )
    except Exception as e:
        logger.exception("purgeduplicates failed")
        await status.edit_text(
            f"❌ <b>Error while purging duplicates:</b>\n<code>{html.escape(str(e))}</code>",
            parse_mode=enums.ParseMode.HTML,
        )


# ============================================================
# 🗑️ STANDARD DELETION & CONFIGURATION COMMANDS
# ============================================================
@Client.on_message(filters.command("delete") & admin_filter)
async def delete_single_file(bot: Client, message: Message):
    media_col = get_media_collection()
    if media_col is None:
        return await message.reply_text(
            "❌ <b>Media database collection is unavailable.</b>",
            parse_mode=enums.ParseMode.HTML,
        )

    try:
        if len(message.command) == 2:
            file_id = message.command[1].strip()
            status_msg = await message.reply_text(
                "🧹 <b>Deleting file from DB...</b>",
                parse_mode=enums.ParseMode.HTML,
            )
            result = await media_col.delete_many(
                {"$or": [{"_id": file_id}, {"file_id": file_id}]}
            )
            if result.deleted_count:
                return await status_msg.edit_text(
                    f"✅ <b>File <code>{html.escape(file_id)}</code> deleted successfully.</b>",
                    parse_mode=enums.ParseMode.HTML,
                )
            return await status_msg.edit_text(
                "⚠️ <b>File not found in database.</b>",
                parse_mode=enums.ParseMode.HTML,
            )

        reply = message.reply_to_message
        if not (reply and reply.media):
            return await message.reply_text(
                "⚙️ <b>Usage:</b>\n"
                "• <code>/delete &lt;file_id&gt;</code>\n"
                "• Or reply to a media file with <code>/delete</code>",
                parse_mode=enums.ParseMode.HTML,
            )

        status_msg = await message.reply_text(
            "⏳ <b>Processing...</b>", parse_mode=enums.ParseMode.HTML
        )
        media = getattr(reply, reply.media.value, None) if reply.media else None
        if not media or not hasattr(media, "file_id"):
            return await status_msg.edit_text(
                "❌ <b>This is not a supported file format.</b>",
                parse_mode=enums.ParseMode.HTML,
            )

        file_id, _ = unpack_new_file_id(media.file_id)
        res = await media_col.delete_many(
            {"$or": [{"_id": file_id}, {"file_id": file_id}, {"_id": media.file_id}]}
        )
        if res.deleted_count:
            return await status_msg.edit_text(
                "✅ <b>File successfully deleted from database.</b>",
                parse_mode=enums.ParseMode.HTML,
            )

        raw_fname = str(getattr(media, "file_name", "") or "")
        clean_fname = re.sub(r"(_|\-|\.|\+)", " ", raw_fname)
        name_candidates = list({raw_fname, clean_fname} - {""})

        query = {"file_size": getattr(media, "file_size", 0)}
        if name_candidates:
            query["file_name"] = {"$in": name_candidates}

        res = await media_col.delete_many(query)
        if res.deleted_count:
            await status_msg.edit_text(
                f"✅ <b>Deleted {res.deleted_count} matching file(s) from database.</b>",
                parse_mode=enums.ParseMode.HTML,
            )
        else:
            await status_msg.edit_text(
                "⚠️ <b>File not found in database.</b>",
                parse_mode=enums.ParseMode.HTML,
            )
    except Exception as e:
        logger.exception("delete_file failed")
        await message.reply_text(
            f"❌ <b>Error while deleting:</b>\n<code>{html.escape(str(e))}</code>",
            parse_mode=enums.ParseMode.HTML,
        )


@Client.on_message(filters.command("delmulti") & admin_filter)
async def delete_multiple_files(bot: Client, message: Message):
    media_col = get_media_collection()
    if media_col is None:
        return await message.reply_text(
            "❌ <b>Media database collection is unavailable.</b>",
            parse_mode=enums.ParseMode.HTML,
        )

    if len(message.command) < 2:
        return await message.reply_text(
            "⚙️ <b>Usage:</b> <code>/delmulti &lt;keyword/name&gt;</code>",
            parse_mode=enums.ParseMode.HTML,
        )

    keyword = message.text.split(None, 1)[1].strip()
    escaped_kw = html.escape(keyword)
    status_msg = await message.reply_text(
        f"⏳ <b>Searching and deleting files matching:</b> <code>{escaped_kw}</code>...",
        parse_mode=enums.ParseMode.HTML,
    )

    try:
        # Build safe regex that won't crash on brackets/parentheses and matches spaces/dots/underscores
        tokens = [re.escape(t) for t in keyword.split() if t]
        safe_pattern = r"[\s\.\_\-\+]+".join(tokens) if tokens else re.escape(keyword)
        query = {"file_name": {"$regex": safe_pattern, "$options": "i"}}
        result = await media_col.delete_many(query)

        if result.deleted_count > 0:
            await status_msg.edit_text(
                f"✅ <b>Successfully deleted <code>{result.deleted_count}</code> files matching:</b> <code>{escaped_kw}</code>",
                parse_mode=enums.ParseMode.HTML,
            )
        else:
            await status_msg.edit_text(
                f"⚠️ <b>No files found matching:</b> <code>{escaped_kw}</code>",
                parse_mode=enums.ParseMode.HTML,
            )
    except Exception as e:
        logger.exception("delete_multiple_files failed")
        await status_msg.edit_text(
            f"❌ <b>Error while deleting files:</b>\n<code>{html.escape(str(e))}</code>",
            parse_mode=enums.ParseMode.HTML,
        )


@Client.on_message(filters.command("autodelete") & admin_filter)
async def set_autodelete_timer(bot: Client, message: Message):
    current = await get_del_setting("FILE_AUTO_DELETE", 1800)
    if len(message.command) < 2:
        return await message.reply_text(
            f"⚙️ <b>Usage:</b> <code>/autodelete [seconds]</code>\n\n"
            f"⏱ <b>Current File Auto-Delete:</b> <code>{current}</code> seconds.",
            parse_mode=enums.ParseMode.HTML,
        )

    try:
        seconds = int(message.command[1])
        if seconds < 0:
            raise ValueError
        await save_del_setting("FILE_AUTO_DELETE", seconds)
        if seconds == 0:
            await message.reply_text(
                "✅ <b>File Auto-Delete has been DISABLED permanently.</b>",
                parse_mode=enums.ParseMode.HTML,
            )
        else:
            await message.reply_text(
                f"✅ <b>File Auto-Delete permanently set to:</b> <code>{seconds}</code> seconds.",
                parse_mode=enums.ParseMode.HTML,
            )
    except ValueError:
        await message.reply_text(
            "❌ <b>Invalid duration!</b> Please provide a valid positive integer (seconds).",
            parse_mode=enums.ParseMode.HTML,
        )
