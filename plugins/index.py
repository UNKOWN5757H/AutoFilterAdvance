import asyncio
import re
import time
from logging import INFO, getLogger

from motor.motor_asyncio import AsyncIOMotorClient
from pyrogram import Client, enums, filters
from pyrogram.errors import (
    ChannelInvalid,
    ChannelPrivate,
    ChatAdminRequired,
    FloodWait,
    MessageNotModified,
    UsernameInvalid,
    UsernameNotModified,
)
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

import info
from database.ia_filterdb import Media, save_batch
from info import ADMINS
from info import INDEX_REQ_CHANNEL as LOG_CHANNEL
from utils import get_size, temp

logger = getLogger(__name__)
logger.setLevel(INFO)

# ============================================================
# ⚙️ MONGODB SETUP FOR RESUME, CLEAN WORDS & INDEX SETTINGS
# ============================================================
resume_db = None
cw_db = None
idx_db = None
try:
    _DB_CLIENT = AsyncIOMotorClient(info.DATABASE_URI)
    _BOT_DB = _DB_CLIENT[info.DATABASE_NAME]
    resume_db = _BOT_DB["index_resume"]
    cw_db = _BOT_DB["clean_words"]
    idx_db = _BOT_DB["index_settings"]
except Exception as e:
    logger.error(f"Failed to init advanced DBs: {e}")


async def save_resume_state(chat_id, last_processed_id):
    if resume_db is not None:
        await resume_db.update_one(
            {"chat_id": chat_id}, {"$set": {"last_id": last_processed_id}}, upsert=True
        )


async def get_resume_state(chat_id):
    if resume_db is not None:
        doc = await resume_db.find_one({"chat_id": chat_id})
        return doc.get("last_id", 0) if doc else 0
    return 0


async def get_clean_words():
    default = ["sandalwood", "mkv", "mp4", "avi", "webm", "zip", "rar"]
    if cw_db is None:
        return default
    try:
        doc = await cw_db.find_one({"id": "words"})
        if doc is None or doc.get("use_default", True):
            return default
        return doc.get("list", [])
    except Exception:
        return default


async def get_idx_settings():
    default_settings = {
        "min_size": 0,
        "blacklist": ["trailer", "promo", "teaser", "sample"],
        "whitelist": [],
        "auto_backup": False,
        "backup_channel": None,
    }
    if idx_db is None:
        return default_settings
    try:
        doc = await idx_db.find_one({"id": "config"})
        if not doc:
            return default_settings
        for k, v in default_settings.items():
            if k not in doc:
                doc[k] = v
        return doc
    except Exception:
        return default_settings


async def save_idx_settings(key, value):
    if idx_db is not None:
        await idx_db.update_one({"id": "config"}, {"$set": {key: value}}, upsert=True)


def clean_filename(name: str, clean_words: list) -> str:
    if not name:
        return "File"
    if any(w.lower() in ["mkv", "sandalwood"] for w in clean_words):
        name = re.sub(r"(?i)\[?@?sandalwood[^\]\s]*\]?", "", name)
        name = re.sub(r"(?i)\b(sandalwood|mkv|mp4|avi|webm|zip|rar)\b", "", name)
    name = re.sub(r"[_.-]", " ", name)
    for word in clean_words:
        if word.lower() in ["mkv", "sandalwood", "mp4", "avi", "webm", "zip", "rar"]:
            continue
        name = re.sub(rf"(?i){re.escape(word)}", "", name)
    return re.sub(r"\s+", " ", name).strip()


# ============================================================
# ⚙️ SAFE CHANNEL CONFIGURATION PARSER
# ============================================================
def parse_channels(chan_var):
    if isinstance(chan_var, list):
        return [int(x) for x in chan_var if str(x).lstrip("-").isdigit()]
    if isinstance(chan_var, str):
        return [int(x) for x in chan_var.split() if x.strip().lstrip("-").isdigit()]
    if isinstance(chan_var, int):
        return [chan_var]
    return []


AUTO_INDEX_CHANNELS = []
try:
    AUTO_INDEX_CHANNELS.extend(parse_channels(info.CHANNELS))
except AttributeError:
    pass

try:
    AUTO_INDEX_CHANNELS.extend(parse_channels(info.INDEX_CHANNELS))
except AttributeError:
    pass

AUTO_INDEX_CHANNELS = list(set(AUTO_INDEX_CHANNELS))
lock = asyncio.Lock()


# ============================================================
# 🛡️ PURE MEDIA EXTRACTOR (Bypasses Memory Locks + Clean DB)
# ============================================================
class SafeMedia:
    def __init__(self, media_obj, file_type, caption, override_name=None):
        self.file_id = getattr(media_obj, "file_id", "")
        self.file_unique_id = getattr(media_obj, "file_unique_id", "")
        self.file_name = (
            override_name if override_name else getattr(media_obj, "file_name", "")
        )
        self.file_size = getattr(media_obj, "file_size", 0)
        self.mime_type = getattr(media_obj, "mime_type", "")
        self.file_type = file_type
        self.caption = caption


# ============================================================
# ⚡ AUTO-INDEX NEW MESSAGES
# ============================================================
@Client.on_message(
    filters.channel
    & (filters.document | filters.video | filters.audio)
    & ~filters.forwarded,
    group=-4,
)
async def auto_index_new_files(bot: Client, message: Message):
    if AUTO_INDEX_CHANNELS and message.chat.id not in AUTO_INDEX_CHANNELS:
        return

    media_obj = getattr(message, message.media.value, None)
    if not media_obj:
        return

    idx_settings = await get_idx_settings()
    if media_obj.file_size < idx_settings.get("min_size", 0):
        return

    raw_name = getattr(media_obj, "file_name", "Unknown")
    raw_caption = message.caption if message.caption else ""

    blacklist = idx_settings.get("blacklist", [])
    if any(
        b_word.lower() in raw_name.lower() or b_word.lower() in raw_caption.lower()
        for b_word in blacklist
    ):
        return

    whitelist = idx_settings.get("whitelist", [])
    if whitelist:
        if not any(
            w_word.lower() in raw_name.lower() or w_word.lower() in raw_caption.lower()
            for w_word in whitelist
        ):
            return

    # 🛡️ Anti-Copyright Shield
    target_media = media_obj
    target_caption = message.caption
    if idx_settings.get("auto_backup") and idx_settings.get("backup_channel"):
        try:
            copied_msg = await message.copy(chat_id=idx_settings.get("backup_channel"))
            target_media = getattr(copied_msg, copied_msg.media.value, media_obj)
            target_caption = copied_msg.caption
        except Exception as e:
            logger.error(f"Auto-backup failed for {message.chat.id}: {e}")

    clean_words = await get_clean_words()
    cleaned_name = clean_filename(
        getattr(target_media, "file_name", "Unknown"), clean_words
    )
    safe_media = SafeMedia(
        target_media, message.media.value, target_caption, cleaned_name
    )

    try:
        await save_batch([safe_media])
        logger.info(
            f"Auto-indexed new file from {message.chat.title} ({message.chat.id})"
        )
    except Exception as e:
        logger.error(f"Auto-index failed for {message.chat.title}: {e}")


# ============================================================
# 🧹 PM FORWARD AUTO-CLEANUP
# ============================================================
@Client.on_message(
    filters.private
    & filters.forwarded
    & (filters.document | filters.video | filters.audio)
    & filters.user(ADMINS)
)
async def pm_forward_indexer(bot: Client, message: Message):
    media_obj = getattr(message, message.media.value, None)
    if not media_obj:
        return

    idx_settings = await get_idx_settings()
    if media_obj.file_size < idx_settings.get("min_size", 0):
        return await message.reply(
            "⚠️ Ignored: File size is smaller than the minimum allowed limit."
        )

    raw_name = getattr(media_obj, "file_name", "Unknown")
    raw_caption = message.caption if message.caption else ""

    blacklist = idx_settings.get("blacklist", [])
    if any(
        b_word.lower() in raw_name.lower() or b_word.lower() in raw_caption.lower()
        for b_word in blacklist
    ):
        return await message.reply("⚠️ Ignored: File contains blacklisted words.")

    whitelist = idx_settings.get("whitelist", [])
    if whitelist:
        if not any(
            w_word.lower() in raw_name.lower() or w_word.lower() in raw_caption.lower()
            for w_word in whitelist
        ):
            return await message.reply(
                "⚠️ Ignored: File does not contain whitelisted words."
            )

    target_media = media_obj
    target_caption = message.caption
    if idx_settings.get("auto_backup") and idx_settings.get("backup_channel"):
        try:
            copied_msg = await message.copy(chat_id=idx_settings.get("backup_channel"))
            target_media = getattr(copied_msg, copied_msg.media.value, media_obj)
            target_caption = copied_msg.caption
        except Exception:
            pass

    clean_words = await get_clean_words()
    cleaned_name = clean_filename(
        getattr(target_media, "file_name", "Unknown"), clean_words
    )
    safe_media = SafeMedia(
        target_media, message.media.value, target_caption, cleaned_name
    )

    try:
        await save_batch([safe_media])
        await message.delete()
    except Exception as e:
        logger.error(f"PM Auto-index failed: {e}")


# ============================================================
# 🎛️ GLOBAL ADVANCED CONTROLS
# ============================================================
@Client.on_message(filters.command("setskip") & filters.user(ADMINS))
async def set_skip_number(bot: Client, message: Message):
    if len(message.command) > 1:
        try:
            skip = int(message.command[1])
            if skip < 0:
                return await message.reply("⚠️ Skip number must be 0 or greater.")
            temp.CURRENT = skip
            await message.reply(f"✅ Successfully set default SKIP number to `{skip}`.")
        except ValueError:
            await message.reply("⚠️ Skip number must be an integer.")
    else:
        await message.reply("⚠️ Usage: `/setskip 100`")


@Client.on_message(filters.command("setindexspeed") & filters.user(ADMINS))
async def set_index_speed(bot: Client, message: Message):
    if len(message.command) > 1:
        try:
            speed = float(message.command[1])
            temp.INDEX_SPEED = speed
            await message.reply(
                f"✅ Fetch delay set to `{speed}` seconds to prevent FloodWait."
            )
        except ValueError:
            await message.reply("⚠️ Speed must be a number (e.g., 1 or 0.5).")
    else:
        await message.reply("⚠️ Usage: `/setindexspeed 1.5`")


@Client.on_message(filters.command("currentskip") & filters.user(ADMINS))
async def current_skip_number(bot: Client, message: Message):
    current = getattr(temp, "CURRENT", 0)
    await message.reply(f"ℹ️ The current default SKIP number is: `{current}`")


@Client.on_message(filters.command("deleteskip") & filters.user(ADMINS))
async def delete_skip_number(bot: Client, message: Message):
    temp.CURRENT = 0
    await message.reply("✅ Successfully reset the SKIP number to `0`.")


@Client.on_message(filters.command("setminsize") & filters.user(ADMINS))
async def set_min_size(bot: Client, message: Message):
    if len(message.command) > 1:
        try:
            mb_size = int(message.command[1])
            byte_size = mb_size * 1024 * 1024
            await save_idx_settings("min_size", byte_size)
            await message.reply(
                f"✅ **Minimum Size Limit Set!**\nFiles smaller than `{mb_size} MB` will be ignored during indexing."
            )
        except ValueError:
            await message.reply("⚠️ Size must be an integer (in MB).")
    else:
        await message.reply("⚠️ Usage: `/setminsize 50` (to set 50MB limit)")


# --- BLACKLIST COMMANDS ---
@Client.on_message(filters.command("setblacklist") & filters.user(ADMINS))
async def set_blacklist(bot: Client, message: Message):
    if len(message.command) > 1:
        words = message.text.split(None, 1)[1]
        words_list = [w.strip().lower() for w in words.split(",") if w.strip()]
        settings = await get_idx_settings()
        updated_list = list(set(settings.get("blacklist", []) + words_list))
        await save_idx_settings("blacklist", updated_list)
        await message.reply(
            f"✅ **Blacklist Updated!**\nAdded: `{', '.join(words_list)}`"
        )
    else:
        await message.reply("⚠️ Usage: `/setblacklist promo, trailer`")


@Client.on_message(filters.command("remblacklist") & filters.user(ADMINS))
async def rem_blacklist(bot: Client, message: Message):
    if len(message.command) > 1:
        word = message.command[1].strip().lower()
        settings = await get_idx_settings()
        current_list = settings.get("blacklist", [])
        if word in current_list:
            current_list.remove(word)
            await save_idx_settings("blacklist", current_list)
            await message.reply(f"🗑️ Removed `{word}` from blacklist.")
        else:
            await message.reply("⚠️ Word not found in blacklist.")
    else:
        await message.reply("⚠️ Usage: `/remblacklist promo`")


@Client.on_message(filters.command("allblacklist") & filters.user(ADMINS))
async def all_blacklist(bot: Client, message: Message):
    settings = await get_idx_settings()
    current_list = settings.get("blacklist", [])
    if not current_list:
        return await message.reply("ℹ️ Blacklist is currently empty.")
    await message.reply(
        f"🚫 **Current Blacklist Words:**\n\n`{', '.join(current_list)}`"
    )


# --- WHITELIST COMMANDS ---
@Client.on_message(filters.command("setwhitelist") & filters.user(ADMINS))
async def set_whitelist(bot: Client, message: Message):
    if len(message.command) > 1:
        words = message.text.split(None, 1)[1]
        words_list = [w.strip().lower() for w in words.split(",") if w.strip()]
        settings = await get_idx_settings()
        updated_list = list(set(settings.get("whitelist", []) + words_list))
        await save_idx_settings("whitelist", updated_list)
        await message.reply(
            f"✅ **Whitelist Updated!**\nAdded: `{', '.join(words_list)}`\n*(Bot will NOW ONLY index files containing these words)*"
        )
    else:
        await message.reply("⚠️ Usage: `/setwhitelist 1080p, Kannada`")


@Client.on_message(filters.command("remwhitelist") & filters.user(ADMINS))
async def rem_whitelist(bot: Client, message: Message):
    if len(message.command) > 1:
        word = message.command[1].strip().lower()
        settings = await get_idx_settings()
        current_list = settings.get("whitelist", [])
        if word in current_list:
            current_list.remove(word)
            await save_idx_settings("whitelist", current_list)
            await message.reply(f"🗑️ Removed `{word}` from whitelist.")
        else:
            await message.reply("⚠️ Word not found in whitelist.")
    else:
        await message.reply("⚠️ Usage: `/remwhitelist 1080p`")


@Client.on_message(filters.command("allwhitelist") & filters.user(ADMINS))
async def all_whitelist(bot: Client, message: Message):
    settings = await get_idx_settings()
    current_list = settings.get("whitelist", [])
    if not current_list:
        return await message.reply(
            "ℹ️ Whitelist is currently empty (Bot accepts everything)."
        )
    await message.reply(
        f"🎯 **Current Whitelist Words:**\n\n`{', '.join(current_list)}`\n\n*(Bot ONLY indexes files containing these)*"
    )


# --- ANTI-COPYRIGHT BACKUP COMMANDS ---
@Client.on_message(filters.command("setbackupchannel") & filters.user(ADMINS))
async def set_backup_channel(bot: Client, message: Message):
    if len(message.command) > 1:
        try:
            chat_id = int(message.command[1])
            await save_idx_settings("backup_channel", chat_id)
            await message.reply(
                f"✅ **Backup Channel Set!**\nFiles will be forwarded to `{chat_id}` if Auto-Backup is ON."
            )
        except ValueError:
            await message.reply("❌ Invalid Chat ID.")
    else:
        await message.reply("⚠️ Usage: `/setbackupchannel -100xxxxxx`")


@Client.on_message(filters.command("autobackup") & filters.user(ADMINS))
async def toggle_autobackup(bot: Client, message: Message):
    settings = await get_idx_settings()
    if len(message.command) < 2:
        status = "🟢 ON" if settings.get("auto_backup") else "🔴 OFF"
        chan = settings.get("backup_channel", "Not Set")
        return await message.reply(
            f"**Auto-Backup Status:** {status}\n**Target Channel:** `{chan}`\n\nUse `/autobackup on` or `off`."
        )

    cmd = message.command[1].lower()
    if cmd == "on":
        if not settings.get("backup_channel"):
            return await message.reply(
                "⚠️ Please set a backup channel first using `/setbackupchannel`"
            )
        await save_idx_settings("auto_backup", True)
        await message.reply(
            "🛡️ **Anti-Copyright Auto-Backup is now ON!**\n*(Note: Indexing large channels will be slower due to Telegram forward limits)*"
        )
    elif cmd == "off":
        await save_idx_settings("auto_backup", False)
        await message.reply("🔴 **Auto-Backup OFF!**")


# ============================================================
# 🧹 DATABASE CLEANUP TOOLS
# ============================================================
@Client.on_message(filters.command("cleanduplicates") & filters.user(ADMINS))
async def clean_duplicates(bot: Client, message: Message):
    msg = await message.reply(
        "⏳ **Scanning Database for Duplicate Files...**\n*(This might take a minute depending on your DB size)*"
    )
    try:
        pipeline = [
            {
                "$group": {
                    "_id": "$file_unique_id",
                    "count": {"$sum": 1},
                    "ids": {"$push": "$_id"},
                }
            },
            {"$match": {"count": {"$gt": 1}}},
        ]
        cursor = Media.aggregate(pipeline)

        duplicates_found = 0
        deleted_count = 0

        async for doc in cursor:
            duplicates_found += 1
            ids_to_delete = doc["ids"][1:]
            await Media.delete_many({"_id": {"$in": ids_to_delete}})
            deleted_count += len(ids_to_delete)

        if deleted_count > 0:
            await msg.edit(
                f"✅ **Duplicate Scan Complete!**\n\nFound `{duplicates_found}` duplicated movies.\n🗑️ Deleted `{deleted_count}` redundant entries.\n💾 **Storage Saved!**"
            )
        else:
            await msg.edit(
                "✅ **Duplicate Scan Complete!**\n\nYour database is completely clean. No duplicates found."
            )
    except Exception as e:
        await msg.edit(f"❌ **Error during cleanup:** `{e}`")


@Client.on_message(filters.command("cleandeadlinks") & filters.user(ADMINS))
async def clean_dead_links(bot: Client, message: Message):
    limit = 500
    if len(message.command) > 1:
        try:
            limit = int(message.command[1])
        except ValueError:
            pass

    msg = await message.reply(
        f"⏳ **Starting Dead Link Scanner...**\nChecking the last `{limit}` files in the database.\n*(This runs slowly to prevent Telegram Flood bans)*"
    )

    deleted = 0
    checked = 0
    cursor = Media.find().sort("file_id", -1).limit(limit)

    async for file in cursor:
        checked += 1
        if checked % 50 == 0:
            try:
                await msg.edit(
                    f"⏳ **Dead Link Scanner Running...**\n\nChecked: `{checked}` / `{limit}`\nDeleted: `{deleted}`"
                )
            except MessageNotModified:
                pass

        try:
            await bot.get_file(file["file_id"])
            await asyncio.sleep(0.5)
        except FloodWait as e:
            await asyncio.sleep(e.value + 1)
        except Exception:
            await Media.delete_one({"_id": file["_id"]})
            deleted += 1

    await msg.edit(
        f"✅ **Dead Link Scan Complete!**\n\nChecked: `{checked}` files.\n🗑️ Removed `{deleted}` broken/dead links from the database."
    )


# ============================================================
# 🧭 CALLBACK HANDLERS
# ============================================================
@Client.on_callback_query(filters.regex(r"^(index|idx_cancel)"))
async def index_files(bot: Client, query):
    if query.data.startswith("idx_cancel"):
        try:
            _, chat_id = query.data.split("#")
            chat_id = int(chat_id)
            if not hasattr(temp, "INDEX_CANCEL"):
                temp.INDEX_CANCEL = {}
            temp.INDEX_CANCEL[chat_id] = True
            return await query.answer(
                "Cancelling Indexing for this channel...", show_alert=True
            )
        except Exception:
            return await query.answer("Cancel signal sent.", show_alert=True)

    data_parts = query.data.split("#")

    if len(data_parts) == 7:
        _, action, chat, lst_msg_id, from_user, skip_val, filter_type = data_parts
        try:
            skip_val = int(skip_val)
        except ValueError:
            skip_val = 0
    elif len(data_parts) == 6:
        _, action, chat, lst_msg_id, from_user, skip_val = data_parts
        try:
            skip_val = int(skip_val)
        except ValueError:
            skip_val = 0
        filter_type = "all"
    elif len(data_parts) == 5:
        _, action, chat, lst_msg_id, from_user = data_parts
        skip_val, filter_type = 0, "all"
    else:
        return await query.answer("Invalid callback data.", show_alert=True)

    if action == "reject":
        try:
            await query.message.delete()
        except Exception:
            pass
        try:
            await bot.send_message(
                int(from_user),
                f"Your submission for indexing `{chat}` has been declined.",
                reply_to_message_id=int(lst_msg_id),
            )
        except Exception:
            pass
        return

    if lock.locked():
        return await query.answer(
            "Wait until the previous system-wide indexing process completes.",
            show_alert=True,
        )

    msg = query.message
    await query.answer("Starting Process...⏳", show_alert=True)

    if int(from_user) not in ADMINS:
        try:
            await bot.send_message(
                int(from_user),
                f"Your submission for indexing `{chat}` has been accepted and is processing.",
            )
        except Exception:
            pass

    try:
        chat = int(chat)
    except ValueError:
        pass

    try:
        await msg.edit(
            "Starting Indexing Engine...",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("Cancel", callback_data=f"idx_cancel#{chat}")]]
            ),
        )
    except MessageNotModified:
        pass

    asyncio.create_task(
        index_files_to_db(int(lst_msg_id), chat, msg, bot, skip_val, filter_type)
    )


# ============================================================
# 🎯 PROCESS INDEX REQUESTS
# ============================================================
async def process_index_request(
    bot: Client, message: Message, chat_id, last_msg_id, filter_type="all"
):
    try:
        chat_obj = await bot.get_chat(chat_id)
        chat_id = chat_obj.id
    except (ChannelInvalid, ChannelPrivate, UsernameInvalid, UsernameNotModified):
        return await message.reply(
            "⚠️ Invalid Link/Channel or Bot is not an Admin there."
        )
    except Exception as e:
        return await message.reply(f"⚠️ Error accessing chat: `{e}`")

    try:
        k = await bot.get_messages(chat_id, last_msg_id)
        if not k or getattr(k, "empty", False):
            return await message.reply(
                "⚠️ This may be a group and I am not an admin, or the message does not exist."
            )
    except Exception:
        return await message.reply(
            "⚠️ Make sure that I am an admin in the channel (if the channel is private)."
        )

    if message.from_user and message.from_user.id in ADMINS:
        skip_count = getattr(temp, "CURRENT", 0)
        buttons = [
            [
                InlineKeyboardButton(
                    "Yes, Start Indexing",
                    callback_data=f"index#accept#{chat_id}#{last_msg_id}#{message.from_user.id}#{skip_count}#{filter_type}",
                )
            ],
            [InlineKeyboardButton("Close", callback_data="close_data")],
        ]
        return await message.reply(
            f"**Ready to Index ({filter_type.title()} Filter)**\n\n"
            f"**Chat ID:** <code>{chat_id}</code>\n"
            f"**Last Message:** <code>{last_msg_id}</code>\n"
            f"**Skipping First:** <code>{skip_count}</code> messages\n\n"
            f"*(Close and use `/setskip` if you need a different skip value)*",
            reply_markup=InlineKeyboardMarkup(buttons),
        )

    if chat_obj.username:
        link = f"https://t.me/{chat_obj.username}"
    else:
        try:
            link = (await bot.create_chat_invite_link(chat_id)).invite_link
        except ChatAdminRequired:
            link = str(chat_id)

    buttons = [
        [
            InlineKeyboardButton(
                "Accept Index",
                callback_data=f"index#accept#{chat_id}#{last_msg_id}#{message.from_user.id}#0#{filter_type}",
            )
        ],
        [
            InlineKeyboardButton(
                "Reject Index",
                callback_data=f"index#reject#{chat_id}#{message.id}#{message.from_user.id}",
            )
        ],
    ]

    await bot.send_message(
        LOG_CHANNEL,
        f"#IndexRequest ({filter_type.title()})\n\nBy: {message.from_user.mention} (<code>{message.from_user.id}</code>)\n"
        f"Chat ID: <code>{chat_id}</code>\nLast Msg ID: <code>{last_msg_id}</code>\nLink: {link}",
        reply_markup=InlineKeyboardMarkup(buttons),
    )
    await message.reply(
        "✅ Thank you for the contribution! Please wait for our moderators to verify."
    )


# ============================================================
# 💬 COMMAND LISTENERS
# ============================================================
@Client.on_message(
    filters.command(["index", "indexvideo", "indexdoc", "indexaudio"])
    & filters.incoming
)
async def index_command(bot: Client, message: Message):
    filter_type = "all"
    cmd = message.command[0].lower()
    if cmd == "indexvideo":
        filter_type = "video"
    elif cmd == "indexdoc":
        filter_type = "document"
    elif cmd == "indexaudio":
        filter_type = "audio"

    if (
        message.reply_to_message
        and message.reply_to_message.forward_from_chat
        and message.reply_to_message.forward_from_chat.type == enums.ChatType.CHANNEL
    ):
        chat_id = (
            message.reply_to_message.forward_from_chat.username
            or message.reply_to_message.forward_from_chat.id
        )
        last_msg_id = message.reply_to_message.forward_from_message_id
        return await process_index_request(
            bot, message, chat_id, last_msg_id, filter_type
        )

    if len(message.command) != 3:
        return await message.reply(
            f"**Usage:** `/{cmd} <chat_id> <last_message_id>`\n\n*(Or just forward a message/link to me!)*"
        )

    chat_id = message.command[1]
    try:
        last_msg_id = int(message.command[2])
    except ValueError:
        return await message.reply("⚠️ Last message ID must be an integer.")

    if chat_id.isnumeric() or (chat_id.startswith("-100") and chat_id[4:].isnumeric()):
        chat_id = int(chat_id)

    await process_index_request(bot, message, chat_id, last_msg_id, filter_type)


@Client.on_message(filters.command("resumeindex") & filters.user(ADMINS))
async def resume_index_command(bot: Client, message: Message):
    if len(message.command) != 2:
        return await message.reply("**Usage:** `/resumeindex <chat_id>`")

    chat_id_str = message.command[1]
    if chat_id_str.isnumeric() or (
        chat_id_str.startswith("-100") and chat_id_str[4:].isnumeric()
    ):
        chat_id = int(chat_id_str)
    else:
        chat_id = chat_id_str

    last_processed = await get_resume_state(chat_id)
    if last_processed <= 0:
        return await message.reply("⚠️ No crash-resume state found for this channel.")

    status = await message.reply("⏳ Fetching highest message ID...")
    try:
        last_msg_id = last_processed + 1000
        async for m in bot.get_chat_history(chat_id, limit=1):
            last_msg_id = m.id
            break
        await status.delete()
        temp.CURRENT = last_processed
        await process_index_request(bot, message, chat_id, last_msg_id, "all")
    except Exception as e:
        await status.edit_text(f"❌ Failed to resume: {e}")


@Client.on_message(
    filters.incoming
    & (
        filters.forwarded
        | filters.regex(
            r"(https://)?(t\.me/|telegram\.me/|telegram\.dog/)(c/)?(\d+|[a-zA-Z_0-9]+)/(\d+)$"
        )
    )
)
async def send_for_index(bot: Client, message: Message):
    if message.chat.type == enums.ChatType.PRIVATE and getattr(message, "media", None):
        return

    chat_id = None
    last_msg_id = None

    if (
        message.forward_from_chat
        and message.forward_from_chat.type == enums.ChatType.CHANNEL
    ):
        last_msg_id = message.forward_from_message_id
        chat_id = message.forward_from_chat.username or message.forward_from_chat.id
    else:
        text = message.text or message.caption
        if not text:
            return
        regex = re.compile(
            r"(https://)?(t\.me/|telegram\.me/|telegram\.dog/)(c/)?(\d+|[a-zA-Z_0-9]+)/(\d+)$"
        )
        match = regex.match(text)
        if match:
            chat_id = match.group(4)
            last_msg_id = int(match.group(5))
            if chat_id.isnumeric():
                chat_id = int(f"-100{chat_id}")
        else:
            return

    if message.from_user and message.from_user.id in ADMINS:
        await process_index_request(bot, message, chat_id, last_msg_id, "all")


# ============================================================
# 💾 DATABASE BATCH SAVER (WITH SHIELD & WHITELIST)
# ============================================================
async def index_files_to_db(
    lst_msg_id,
    chat,
    msg: Message,
    bot: Client,
    skip_number: int = 0,
    filter_type: str = "all",
):
    total_files = 0
    duplicate = 0
    errors = 0
    deleted = 0
    no_media = 0
    unsupported = 0
    last_processed = skip_number

    clean_words = await get_clean_words()
    idx_settings = await get_idx_settings()
    min_size = idx_settings.get("min_size", 0)
    blacklist = idx_settings.get("blacklist", [])
    whitelist = idx_settings.get("whitelist", [])
    auto_backup = idx_settings.get("auto_backup", False)
    backup_channel = idx_settings.get("backup_channel")
    delay_speed = getattr(temp, "INDEX_SPEED", 0)

    if not hasattr(temp, "INDEX_CANCEL"):
        temp.INDEX_CANCEL = {}
    temp.INDEX_CANCEL[chat] = False

    async with lock:
        try:
            start_id = max(1, skip_number)
            fetched_count = 0
            last_update_time = time.time()
            message_ids = list(range(start_id, lst_msg_id + 1))

            for i in range(0, len(message_ids), 200):
                if temp.INDEX_CANCEL.get(chat):
                    try:
                        await msg.edit(
                            f"**⛔ Successfully Cancelled!!**\n\n"
                            f"Saved <code>{total_files}</code> files to database!\n"
                            f"Duplicate Files Skipped: <code>{duplicate}</code>\n"
                            f"Deleted Messages: <code>{deleted}</code>\n"
                            f"Filtered/Non-Media: <code>{no_media + unsupported}</code>\n"
                            f"Errors: <code>{errors}</code>"
                        )
                    except Exception:
                        pass
                    temp.INDEX_CANCEL[chat] = False
                    return

                chunk = message_ids[i : i + 200]
                messages = []
                max_retries = 3

                while max_retries > 0:
                    try:
                        messages = await bot.get_messages(chat, chunk)
                        break
                    except FloodWait as e:
                        await asyncio.sleep(e.value + 1)
                        max_retries -= 1
                    except Exception as e:
                        logger.error(f"Error fetching chunk: {e}")
                        break

                if not messages:
                    continue

                media_to_save = []
                for message in messages:
                    fetched_count += 1
                    last_processed = message.id

                    if time.time() - last_update_time > 8:
                        reply = InlineKeyboardMarkup(
                            [
                                [
                                    InlineKeyboardButton(
                                        "Cancel", callback_data=f"idx_cancel#{chat}"
                                    )
                                ]
                            ]
                        )
                        status_text = (
                            f"⚡ **Ultra-Speed Indexing ({filter_type})...** ⚡\n\n"
                        )
                        if auto_backup and backup_channel:
                            status_text = f"🛡️ **Anti-Copyright Indexing ({filter_type})...** 🛡️\n\n"
                        try:
                            await msg.edit_text(
                                text=status_text
                                + f"Total fetched: <code>{fetched_count}</code>\n"
                                f"Total saved: <code>{total_files}</code>\n"
                                f"Duplicates: <code>{duplicate}</code>\n"
                                f"Skipped: <code>{deleted + no_media + unsupported}</code>\n"
                                f"Errors: <code>{errors}</code>",
                                reply_markup=reply,
                            )
                        except FloodWait as e:
                            await asyncio.sleep(e.value + 1)
                        except MessageNotModified:
                            pass
                        except Exception:
                            pass
                        last_update_time = time.time()

                    if getattr(message, "empty", False):
                        deleted += 1
                        continue
                    elif not getattr(message, "media", None):
                        no_media += 1
                        continue
                    elif message.media not in [
                        enums.MessageMediaType.VIDEO,
                        enums.MessageMediaType.AUDIO,
                        enums.MessageMediaType.DOCUMENT,
                    ]:
                        unsupported += 1
                        continue

                    if (
                        filter_type == "video"
                        and message.media != enums.MessageMediaType.VIDEO
                    ):
                        unsupported += 1
                        continue
                    if (
                        filter_type == "document"
                        and message.media != enums.MessageMediaType.DOCUMENT
                    ):
                        unsupported += 1
                        continue
                    if (
                        filter_type == "audio"
                        and message.media != enums.MessageMediaType.AUDIO
                    ):
                        unsupported += 1
                        continue

                    media_obj = getattr(message, message.media.value, None)
                    if not media_obj:
                        unsupported += 1
                        continue

                    if media_obj.file_size < min_size:
                        unsupported += 1
                        continue

                    raw_name = getattr(media_obj, "file_name", "Unknown")
                    raw_caption = message.caption if message.caption else ""

                    if any(
                        b_word.lower() in raw_name.lower()
                        or b_word.lower() in raw_caption.lower()
                        for b_word in blacklist
                    ):
                        unsupported += 1
                        continue

                    if whitelist:
                        if not any(
                            w_word.lower() in raw_name.lower()
                            or w_word.lower() in raw_caption.lower()
                            for w_word in whitelist
                        ):
                            unsupported += 1
                            continue

                    # 🛡️ ANTI-COPYRIGHT AUTO-BACKUP
                    target_media = media_obj
                    target_caption = raw_caption
                    if auto_backup and backup_channel:
                        try:
                            copied_msg = await message.copy(chat_id=backup_channel)
                            target_media = getattr(
                                copied_msg, copied_msg.media.value, media_obj
                            )
                            target_caption = copied_msg.caption
                            await asyncio.sleep(
                                1.5
                            )  # Prevent FloodWaits from heavy copying
                        except FloodWait as e:
                            await asyncio.sleep(e.value + 1)
                            try:
                                copied_msg = await message.copy(chat_id=backup_channel)
                                target_media = getattr(
                                    copied_msg, copied_msg.media.value, media_obj
                                )
                                target_caption = copied_msg.caption
                            except Exception:
                                pass
                        except Exception as e:
                            logger.error(f"Auto-backup failed for {message.id}: {e}")

                    cleaned_name = clean_filename(
                        getattr(target_media, "file_name", ""), clean_words
                    )
                    safe_media = SafeMedia(
                        target_media, message.media.value, target_caption, cleaned_name
                    )
                    media_to_save.append(safe_media)

                if media_to_save:
                    try:
                        result = await save_batch(media_to_save)
                        if isinstance(result, tuple) and len(result) == 3:
                            saved, dups, errs = result
                            total_files += saved
                            duplicate += dups
                            errors += errs
                        else:
                            total_files += len(media_to_save)
                    except Exception as e:
                        logger.error(f"Batch Save Error: {e}")
                        errors += len(media_to_save)

                await save_resume_state(chat, last_processed)
                if delay_speed > 0:
                    await asyncio.sleep(delay_speed)

        except Exception as e:
            logger.exception(e)
            try:
                await msg.edit(f"⚠️ Critical Error during Indexing: `{e}`")
            except Exception:
                pass
        else:
            if not temp.INDEX_CANCEL.get(chat):
                try:
                    await msg.edit(
                        f"🎉 **Indexing Complete!**\n\n"
                        f"Successfully saved <code>{total_files}</code> files to database!\n"
                        f"Duplicate Files Skipped: <code>{duplicate}</code>\n"
                        f"Deleted Messages Skipped: <code>{deleted}</code>\n"
                        f"Filtered/Non-Media skipped: <code>{no_media + unsupported}</code>\n"
                        f"Errors Occurred: <code>{errors}</code>"
                    )
                except Exception:
                    pass
