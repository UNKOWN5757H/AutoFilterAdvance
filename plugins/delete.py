import asyncio
import re
import time
from logging import ERROR, getLogger

from motor.motor_asyncio import AsyncIOMotorClient
from pyrogram import Client, filters
from pyrogram.errors import FloodWait, MessageNotModified
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

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


async def get_del_setting(key: str, default: int) -> int:
    if _del_db is not None:
        doc = await _del_db.find_one({"_id": "timers"})
        if doc and key in doc:
            return int(doc[key])
    return int(getattr(info, key, default))


async def save_del_setting(key: str, value: int):
    setattr(info, key, value)
    if _del_db is not None:
        await _del_db.update_one({"_id": "timers"}, {"$set": {key: value}}, upsert=True)


def get_admin_list():
    raw_admins = getattr(info, "ADMINS", [])
    if isinstance(raw_admins, str):
        return [
            int(x)
            for x in raw_admins.replace(",", " ").split()
            if x.strip().lstrip("-").isdigit()
        ]
    elif isinstance(raw_admins, int):
        return [raw_admins]
    elif isinstance(raw_admins, list):
        return [int(x) for x in raw_admins if str(x).strip().lstrip("-").isdigit()]
    return []


admin_filter = filters.create(
    lambda _, __, msg: bool(msg.from_user and msg.from_user.id in get_admin_list())
)


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
                    expiry = task["delete_at"]
                    remaining = int(expiry - now)

                    if remaining <= 0:
                        try:
                            await client.delete_messages(chat_id, msg_id)
                        except Exception:
                            pass
                        await _countdown_col.delete_one({"_id": task["_id"]})
                        continue

                    # Update button interval (every 30 seconds to respect Telegram rate limits)
                    last_update = task.get("last_updated", 0)
                    if now - last_update >= 30:
                        timer_label = format_countdown_string(remaining)
                        original_buttons = task.get("buttons", [])

                        # Rebuild keyboard with live timer button as the bottom row
                        new_keyboard = []
                        for row in original_buttons:
                            new_keyboard.append(
                                [
                                    InlineKeyboardButton(
                                        b["text"],
                                        url=b.get("url"),
                                        callback_data=b.get("callback_data"),
                                    )
                                    for b in row
                                ]
                            )
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
                            pass
                        except FloodWait as e:
                            await asyncio.sleep(e.value + 1)
                        except Exception:
                            # Message already deleted by user/admin
                            await _countdown_col.delete_one({"_id": task["_id"]})
        except Exception as e:
            logger.error(f"Countdown worker error: {e}")
        await asyncio.sleep(10)


@Client.on_message(group=-99)
async def start_countdown_worker(client: Client, message: Message):
    global _COUNTDOWN_WORKER_STARTED
    if not _COUNTDOWN_WORKER_STARTED:
        _COUNTDOWN_WORKER_STARTED = True
        asyncio.create_task(countdown_live_worker(client))


async def schedule_file_with_countdown(
    client: Client, sent_message: Message, delay_seconds: int, base_buttons: list = None
):
    if not sent_message or delay_seconds <= 0:
        return
    if _countdown_col is None:
        return

    now = time.time()
    serialized_btns = []
    if base_buttons:
        for row in base_buttons:
            row_data = []
            for btn in row:
                row_data.append(
                    {
                        "text": btn.text,
                        "url": getattr(btn, "url", None),
                        "callback_data": getattr(btn, "callback_data", None),
                    }
                )
            serialized_btns.append(row_data)

    await _countdown_col.insert_one(
        {
            "chat_id": sent_message.chat.id,
            "message_id": sent_message.id,
            "delete_at": now + delay_seconds,
            "last_updated": now,
            "buttons": serialized_btns,
        }
    )


@Client.on_callback_query(filters.regex("^noop_countdown$"))
async def noop_countdown_cb(client: Client, query):
    await query.answer(
        "⚠️ This file will be automatically deleted when the timer ends. Forward or save it now!",
        show_alert=True,
    )


# ============================================================
# 🧹 DUPLICATE FILE PURGER ENGINE (/purgeduplicates)
# ============================================================
def get_resolution_score(filename: str) -> int:
    name = filename.lower()
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
    status = await message.reply_text(
        "🔍 **Scanning database for duplicate files...**\nThis might take some time on large databases."
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

        cursor = _Media.collection.aggregate(pipeline)
        duplicate_groups = await cursor.to_list(length=None)

        if not duplicate_groups:
            return await status.edit_text(
                "✅ **Database is squeaky clean!** No duplicate files found."
            )

        total_duplicates = 0
        deleted_ids = []

        for group in duplicate_groups:
            docs = group["docs"]
            # Sort: highest resolution first, then largest file size
            docs.sort(
                key=lambda d: (
                    get_resolution_score(d.get("name", "")),
                    d.get("size", 0),
                ),
                reverse=True,
            )
            # Retain docs[0] (highest quality copy), remove the rest
            to_remove = docs[1:]
            for d in to_remove:
                deleted_ids.append(d["id"])
                total_duplicates += 1

        # Chunk deletions into batches of 500 to prevent database bottlenecks
        for i in range(0, len(deleted_ids), 500):
            batch = deleted_ids[i : i + 500]
            await _Media.collection.delete_many({"_id": {"$in": batch}})

        await status.edit_text(
            f"🧹 **Duplicate File Purge Completed!**\n\n"
            f"📁 **Duplicate Sets Found:** `{len(duplicate_groups)}`\n"
            f"🗑️ **Redundant Copies Removed:** `{total_duplicates}`\n"
            f"✨ **Preserved:** Best quality copies (Highest resolution & bitrates)."
        )
    except Exception as e:
        logger.exception("purgeduplicates failed")
        await status.edit_text(f"❌ **Error while purging duplicates:**\n`{e}`")


# ============================================================
# 🗑️ STANDARD DELETION & CONFIGURATION COMMANDS
# ============================================================
@Client.on_message(filters.command("delete") & admin_filter)
async def delete_single_file(bot: Client, message: Message):
    try:
        if len(message.command) == 2:
            file_id = message.command[1].strip()
            status_msg = await message.reply_text("🧹 **Deleting file from DB...**")
            result = await _Media.collection.delete_one({"_id": file_id})
            if result.deleted_count:
                return await status_msg.edit_text(
                    f"✅ **File `{file_id}` deleted successfully.**"
                )
            return await status_msg.edit_text("⚠️ **File not found in database.**")

        reply = message.reply_to_message
        if not (reply and reply.media):
            return await message.reply_text(
                "⚙️ **Usage:**\n`/delete <file_id>`\nOr reply to a file with `/delete`"
            )

        status_msg = await message.reply_text("⏳ **Processing...**")
        media = getattr(reply, reply.media.value, None) if reply.media else None
        if not media:
            return await status_msg.edit_text(
                "❌ **This is not a supported file format.**"
            )

        file_id, _ = unpack_new_file_id(media.file_id)
        res = await _Media.collection.delete_one({"_id": file_id})
        if res.deleted_count:
            return await status_msg.edit_text(
                "✅ **File successfully deleted from database.**"
            )

        file_name = re.sub(r"(_|\-|\.|\+)", " ", str(getattr(media, "file_name", "")))
        res = await _Media.collection.delete_many(
            {
                "file_name": file_name,
                "file_size": getattr(media, "file_size", 0),
                "mime_type": getattr(media, "mime_type", ""),
            }
        )

        if res.deleted_count:
            await status_msg.edit_text(
                f"✅ **Deleted {res.deleted_count} duplicate files from database.**"
            )
        else:
            await status_msg.edit_text("⚠️ **File not found in database.**")
    except Exception as e:
        logger.exception("delete_file failed")
        await message.reply_text(f"❌ **Error while deleting:**\n`{e}`")


@Client.on_message(filters.command("delmulti") & admin_filter)
async def delete_multiple_files(bot: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text("⚙️ **Usage:** `/delmulti <keyword/name>`")
    keyword = message.text.split(None, 1)[1]
    status_msg = await message.reply_text(
        f"⏳ **Searching and deleting files matching:** `{keyword}`..."
    )

    try:
        query = {"file_name": {"$regex": keyword, "$options": "i"}}
        result = await _Media.collection.delete_many(query)

        if result.deleted_count > 0:
            await status_msg.edit_text(
                f"✅ **Successfully deleted `{result.deleted_count}` files matching:** `{keyword}`"
            )
        else:
            await status_msg.edit_text(f"⚠️ **No files found matching:** `{keyword}`")
    except Exception as e:
        logger.exception("delete_multiple_files failed")
        await status_msg.edit_text(f"❌ **Error while deleting files:**\n`{e}`")


@Client.on_message(filters.command("autodelete") & admin_filter)
async def set_autodelete_timer(bot: Client, message: Message):
    current = await get_del_setting("FILE_AUTO_DELETE", 1800)
    if len(message.command) < 2:
        return await message.reply_text(
            f"⚙️ **Usage:** `/autodelete [seconds]`\n\n⏱ **Current File Auto-Delete:** `{current}` seconds."
        )
    try:
        seconds = int(message.command[1])
        if seconds < 0:
            raise ValueError
        await save_del_setting("FILE_AUTO_DELETE", seconds)
        if seconds == 0:
            await message.reply_text(
                "✅ **File Auto-Delete has been DISABLED permanently.**"
            )
        else:
            await message.reply_text(
                f"✅ **File Auto-Delete permanently set to:** `{seconds}` seconds."
            )
    except ValueError:
        await message.reply_text(
            "❌ **Invalid duration!** Please provide a valid positive integer (seconds)."
        )


@Client.on_message(filters.command("buttondel") & admin_filter)
async def set_buttondel_timer(bot: Client, message: Message):
    current = await get_del_setting("BUTTON_AUTO_DELETE", 1800)
    if len(message.command) < 2:
        return await message.reply_text(
            f"⚙️ **Usage:** `/buttondel [seconds]`\n\n⏱ **Current Button Auto-Delete:** `{current}` seconds."
        )
    try:
        seconds = int(message.command[1])
        if seconds < 0:
            raise ValueError
        await save_del_setting("BUTTON_AUTO_DELETE", seconds)
        if seconds == 0:
            await message.reply_text(
                "✅ **Group Button Auto-Delete has been DISABLED permanently.**"
            )
        else:
            await message.reply_text(
                f"✅ **Group Button Auto-Delete permanently set to:** `{seconds}` seconds."
            )
    except ValueError:
        await message.reply_text(
            "❌ **Invalid duration!** Please provide a valid positive integer (seconds)."
        )
