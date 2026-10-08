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
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

import info
from database.ia_filterdb import Media, save_batch
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


# ⚡ FOOLPROOF ADMIN PARSER
def get_admin_list():
    raw_admins = getattr(info, "ADMINS", [])
    if isinstance(raw_admins, str):
        return [x.strip() for x in raw_admins.replace(",", " ").split() if x.strip()]
    elif isinstance(raw_admins, int):
        return [str(raw_admins)]
    elif isinstance(raw_admins, list):
        return [str(a) for a in raw_admins]
    return []


admin_filter = filters.create(
    lambda _, __, message: bool(
        message.from_user and str(message.from_user.id) in get_admin_list()
    )
)


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


def parse_channels(chan_var):
    if isinstance(chan_var, list):
        return [int(x) for x in chan_var if str(x).lstrip("-").isdigit()]
    if isinstance(chan_var, str):
        return [
            int(x)
            for x in chan_var.replace(",", " ").split()
            if x.strip().lstrip("-").isdigit()
        ]
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


@Client.on_message(
    filters.channel
    & (filters.document | filters.video | filters.audio)
    & ~filters.forwarded,
    group=-5,
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
    except Exception as e:
        logger.error(f"Auto-index failed for {message.chat.title}: {e}")


# ============================================================
# ⚡ INTELLIGENT PM MEDIA FORWARD HANDLER (Fixes Single Save Issue)
# ============================================================
@Client.on_message(
    filters.private & (filters.document | filters.video | filters.audio) & admin_filter,
    group=-5,
)
async def pm_media_handler(bot: Client, message: Message):
    if (
        message.forward_from_chat
        and message.forward_from_chat.type == enums.ChatType.CHANNEL
    ):
        # User forwarded from a channel. Ask if they want to index the whole channel or save single.
        chat_id = message.forward_from_chat.username or message.forward_from_chat.id
        last_msg_id = message.forward_from_message_id

        buttons = [
            [
                InlineKeyboardButton(
                    "Index Whole Channel",
                    callback_data=f"idx#ac#{chat_id}#{last_msg_id}#{message.from_user.id}#all",
                )
            ],
            [
                InlineKeyboardButton(
                    "Save Only This File", callback_data=f"save_single#{message.id}"
                )
            ],
            [InlineKeyboardButton("Cancel", callback_data="close_data")],
        ]
        await message.reply(
            "📂 **File received from a channel.**\n\nWhat would you like to do?",
            reply_markup=InlineKeyboardMarkup(buttons),
        )
    else:
        # Directly uploaded or forwarded from a user/group. Save single immediately.
        await save_single_file(bot, message)


@Client.on_callback_query(filters.regex(r"^save_single#"), group=-5)
async def save_single_callback(bot: Client, query: CallbackQuery):
    msg_id = int(query.data.split("#")[1])
    try:
        original_message = await bot.get_messages(query.message.chat.id, msg_id)
        await query.message.delete()
        if original_message:
            await save_single_file(bot, original_message)
    except Exception as e:
        await query.answer("Failed to process file.", show_alert=True)


async def save_single_file(bot: Client, message: Message):
    media_obj = getattr(message, message.media.value, None)
    if not media_obj:
        return

    idx_settings = await get_idx_settings()
    if media_obj.file_size < idx_settings.get("min_size", 0):
        return await message.reply(
            "⚠️ Ignored: File size is smaller than minimum limit."
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
        # Note: quote=True is completely removed to prevent Pyrogram v2.2.26 crash
        await message.reply(
            f"✅ **Successfully Saved to Database!**\n\n`{cleaned_name}`"
        )
    except Exception as e:
        logger.error(f"PM Auto-index failed: {e}")
        await message.reply(f"❌ **Failed to index:** `{e}`")


# ============================================================
# 🎛️ ADVANCED COMMAND CONTROLS
# ============================================================
@Client.on_message(filters.command("setskip") & admin_filter, group=-5)
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


@Client.on_message(filters.command("setindexspeed") & admin_filter, group=-5)
async def set_index_speed(bot: Client, message: Message):
    if len(message.command) > 1:
        try:
            speed = float(message.command[1])
            temp.INDEX_SPEED = speed
            await message.reply(f"✅ Fetch delay set to `{speed}` seconds.")
        except ValueError:
            await message.reply("⚠️ Speed must be a number.")
    else:
        await message.reply("⚠️ Usage: `/setindexspeed 1.5`")


@Client.on_message(filters.command("currentskip") & admin_filter, group=-5)
async def current_skip_number(bot: Client, message: Message):
    current = getattr(temp, "CURRENT", 0)
    await message.reply(f"ℹ️ The current default SKIP number is: `{current}`")


@Client.on_message(filters.command("deleteskip") & admin_filter, group=-5)
async def delete_skip_number(bot: Client, message: Message):
    temp.CURRENT = 0
    await message.reply("✅ Successfully reset SKIP number to `0`.")


@Client.on_message(filters.command("setminsize") & admin_filter, group=-5)
async def set_min_size(bot: Client, message: Message):
    if len(message.command) > 1:
        try:
            mb_size = int(message.command[1])
            byte_size = mb_size * 1024 * 1024
            await save_idx_settings("min_size", byte_size)
            await message.reply(f"✅ Minimum size set to `{mb_size} MB`.")
        except ValueError:
            await message.reply("⚠️ Size must be an integer.")
    else:
        await message.reply("⚠️ Usage: `/setminsize 50`")


@Client.on_message(filters.command("setblacklist") & admin_filter, group=-5)
async def set_blacklist(bot: Client, message: Message):
    if len(message.command) > 1:
        words = message.text.split(None, 1)[1]
        words_list = [w.strip().lower() for w in words.split(",") if w.strip()]
        settings = await get_idx_settings()
        updated_list = list(set(settings.get("blacklist", []) + words_list))
        await save_idx_settings("blacklist", updated_list)
        await message.reply(f"✅ Blacklist added: `{', '.join(words_list)}`")
    else:
        await message.reply("⚠️ Usage: `/setblacklist promo, trailer`")


@Client.on_message(filters.command("remblacklist") & admin_filter, group=-5)
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
            await message.reply("⚠️ Word not found.")
    else:
        await message.reply("⚠️ Usage: `/remblacklist promo`")


@Client.on_message(filters.command("allblacklist") & admin_filter, group=-5)
async def all_blacklist(bot: Client, message: Message):
    settings = await get_idx_settings()
    current_list = settings.get("blacklist", [])
    if not current_list:
        return await message.reply("ℹ️ Blacklist is empty.")
    await message.reply(f"🚫 **Blacklist Words:**\n\n`{', '.join(current_list)}`")


@Client.on_message(filters.command("setwhitelist") & admin_filter, group=-5)
async def set_whitelist(bot: Client, message: Message):
    if len(message.command) > 1:
        words = message.text.split(None, 1)[1]
        words_list = [w.strip().lower() for w in words.split(",") if w.strip()]
        settings = await get_idx_settings()
        updated_list = list(set(settings.get("whitelist", []) + words_list))
        await save_idx_settings("whitelist", updated_list)
        await message.reply(f"✅ Whitelist added: `{', '.join(words_list)}`")
    else:
        await message.reply("⚠️ Usage: `/setwhitelist 1080p, Kannada`")


@Client.on_message(filters.command("remwhitelist") & admin_filter, group=-5)
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
            await message.reply("⚠️ Word not found.")
    else:
        await message.reply("⚠️ Usage: `/remwhitelist 1080p`")


@Client.on_message(filters.command("allwhitelist") & admin_filter, group=-5)
async def all_whitelist(bot: Client, message: Message):
    settings = await get_idx_settings()
    current_list = settings.get("whitelist", [])
    if not current_list:
        return await message.reply("ℹ️ Whitelist is empty.")
    await message.reply(f"🎯 **Whitelist Words:**\n\n`{', '.join(current_list)}`")


@Client.on_message(filters.command("setbackupchannel") & admin_filter, group=-5)
async def set_backup_channel(bot: Client, message: Message):
    if len(message.command) > 1:
        try:
            chat_id = int(message.command[1])
            await save_idx_settings("backup_channel", chat_id)
            await message.reply(f"✅ Backup channel set to `{chat_id}`.")
        except ValueError:
            await message.reply("❌ Invalid Chat ID.")
    else:
        await message.reply("⚠️ Usage: `/setbackupchannel -100xxxxxx`")


@Client.on_message(filters.command("autobackup") & admin_filter, group=-5)
async def toggle_autobackup(bot: Client, message: Message):
    settings = await get_idx_settings()
    if len(message.command) < 2:
        status = "🟢 ON" if settings.get("auto_backup") else "🔴 OFF"
        chan = settings.get("backup_channel", "Not Set")
        return await message.reply(
            f"**Auto-Backup Status:** {status}\n**Channel:** `{chan}`"
        )

    cmd = message.command[1].lower()
    if cmd == "on":
        if not settings.get("backup_channel"):
            return await message.reply(
                "⚠️ Set backup channel first using `/setbackupchannel`"
            )
        await save_idx_settings("auto_backup", True)
        await message.reply("🛡️ **Auto-Backup Shield is ON!**")
    elif cmd == "off":
        await save_idx_settings("auto_backup", False)
        await message.reply("🔴 **Auto-Backup OFF!**")


@Client.on_message(filters.command("cleanduplicates") & admin_filter, group=-5)
async def clean_duplicates(bot: Client, message: Message):
    msg = await message.reply("⏳ Scanning DB for duplicates...")
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
        duplicates_found, deleted_count = 0, 0
        async for doc in cursor:
            duplicates_found += 1
            ids_to_delete = doc["ids"][1:]
            await Media.delete_many({"_id": {"$in": ids_to_delete}})
            deleted_count += len(ids_to_delete)
        await msg.edit(
            f"✅ **Cleanup Complete!**\nDuplicates found: `{duplicates_found}`\nDeleted: `{deleted_count}`"
        )
    except Exception as e:
        await msg.edit(f"❌ Error: `{e}`")


@Client.on_message(filters.command("cleandeadlinks") & admin_filter, group=-5)
async def clean_dead_links(bot: Client, message: Message):
    limit = 500
    if len(message.command) > 1:
        try:
            limit = int(message.command[1])
        except ValueError:
            pass

    msg = await message.reply(f"⏳ Checking last `{limit}` files for dead links...")
    deleted, checked = 0, 0
    cursor = Media.find().sort("file_id", -1).limit(limit)
    async for file in cursor:
        checked += 1
        if checked % 50 == 0:
            try:
                await msg.edit(
                    f"⏳ Scanning... Checked: `{checked}` / `{limit}` | Deleted: `{deleted}`"
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
        f"✅ **Dead Link Scan Complete!**\nChecked: `{checked}`\nRemoved: `{deleted}` broken links."
    )


# ============================================================
# 🧭 CALLBACK HANDLERS & PROCESSORS
# ============================================================
@Client.on_callback_query(filters.regex(r"^(idx|idx_cancel|close_data)"), group=-5)
async def index_files(bot: Client, query: CallbackQuery):
    if query.data == "close_data":
        await query.message.delete()
        return await query.answer()

    if query.data.startswith("idx_cancel"):
        try:
            _, chat_id = query.data.split("#")
            chat_id = int(chat_id)
            if not hasattr(temp, "INDEX_CANCEL"):
                temp.INDEX_CANCEL = {}
            temp.INDEX_CANCEL[chat_id] = True
            await query.message.edit("❌ Indexing Cancelled.")
            return await query.answer("Cancelling Indexing...", show_alert=True)
        except Exception:
            return await query.answer("Cancel signal sent.", show_alert=True)

    data_parts = query.data.split("#")
    if len(data_parts) == 6:
        _, action, chat, lst_msg_id, from_user, filter_type = data_parts
    else:
        return await query.answer("Invalid callback data structure.", show_alert=True)

    if lock.locked():
        return await query.answer("Another index process is running.", show_alert=True)

    msg = query.message
    await query.answer("Starting Indexing...⏳", show_alert=True)

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

    skip_val = getattr(temp, "CURRENT", 0)
    asyncio.create_task(
        index_files_to_db(int(lst_msg_id), chat, msg, bot, skip_val, filter_type)
    )


async def process_index_request(
    bot: Client, message: Message, chat_id, last_msg_id, filter_type="all"
):
    try:
        chat_obj = await bot.get_chat(chat_id)
        chat_id = chat_obj.id
    except (ChannelInvalid, ChannelPrivate, UsernameInvalid, UsernameNotModified):
        return await message.reply("⚠️ Invalid Link/Channel or Bot is not Admin there.")
    except Exception as e:
        return await message.reply(f"⚠️ Error: `{e}`")

    skip_count = getattr(temp, "CURRENT", 0)
    buttons = [
        [
            InlineKeyboardButton(
                "Yes, Start Indexing",
                callback_data=f"idx#ac#{chat_id}#{last_msg_id}#{message.from_user.id}#{filter_type}",
            )
        ],
        [InlineKeyboardButton("Close", callback_data="close_data")],
    ]
    return await message.reply(
        f"**Ready to Index ({filter_type.title()})**\n\n"
        f"**Chat ID:** <code>{chat_id}</code>\n"
        f"**Last Message:** <code>{last_msg_id}</code>\n"
        f"**Skip Count:** <code>{skip_count}</code>",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


@Client.on_message(
    filters.command(["index", "indexvideo", "indexdoc", "indexaudio"]) & admin_filter,
    group=-5,
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
        return await message.reply(f"**Usage:** `/{cmd} <chat_id> <last_message_id>`")

    chat_id = message.command[1]
    if chat_id.lstrip("-").isdigit():
        chat_id = int(chat_id)

    try:
        last_msg_id = int(message.command[2])
    except ValueError:
        return await message.reply("⚠️ Last message ID must be an integer.")

    await process_index_request(bot, message, chat_id, last_msg_id, filter_type)


@Client.on_message(filters.command("resumeindex") & admin_filter, group=-5)
async def resume_index_command(bot: Client, message: Message):
    if len(message.command) != 2:
        return await message.reply("**Usage:** `/resumeindex <chat_id>`")

    chat_id_str = message.command[1]
    chat_id = int(chat_id_str) if chat_id_str.lstrip("-").isnumeric() else chat_id_str

    last_processed = await get_resume_state(chat_id)
    if last_processed <= 0:
        return await message.reply("⚠️ No crash-resume state found.")

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


# ⚡ CATCHES ANY TEXT/LINKS SENT BY ADMIN TO TRIGGER INDEXING
@Client.on_message(
    filters.text
    & filters.regex(
        r"(https://)?(t\.me/|telegram\.me/|telegram\.dog/)(c/)?(\d+|[a-zA-Z_0-9]+)/(\d+)$"
    )
    & admin_filter,
    group=-5,
)
async def send_for_index(bot: Client, message: Message):
    text = message.text
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

    await process_index_request(bot, message, chat_id, last_msg_id, "all")


# ⚡ IF USER FORWARDS A PURE TEXT MESSAGE FROM CHANNEL, ALSO TRIGGER INDEX
@Client.on_message(
    filters.private & filters.forwarded & filters.text & admin_filter, group=-5
)
async def pm_forward_text_indexer(bot: Client, message: Message):
    if (
        message.forward_from_chat
        and message.forward_from_chat.type == enums.ChatType.CHANNEL
    ):
        chat_id = message.forward_from_chat.username or message.forward_from_chat.id
        last_msg_id = message.forward_from_message_id
        await process_index_request(bot, message, chat_id, last_msg_id, "all")


async def index_files_to_db(
    lst_msg_id,
    chat,
    msg: Message,
    bot: Client,
    skip_number: int = 0,
    filter_type: str = "all",
):
    total_files, duplicate, errors, deleted, no_media, unsupported = 0, 0, 0, 0, 0, 0
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
                            f"**⛔ Cancelled!** Saved: `{total_files}` files."
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
                    except Exception:
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
                        try:
                            await msg.edit_text(
                                text=f"⚡ **Indexing ({filter_type})...**\nFetched: `{fetched_count}` | Saved: `{total_files}`",
                                reply_markup=reply,
                            )
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
                        b.lower() in raw_name.lower()
                        or b.lower() in raw_caption.lower()
                        for b in blacklist
                    ):
                        unsupported += 1
                        continue

                    if whitelist:
                        if not any(
                            w.lower() in raw_name.lower()
                            or w.lower() in raw_caption.lower()
                            for w in whitelist
                        ):
                            unsupported += 1
                            continue

                    target_media = media_obj
                    target_caption = raw_caption
                    if auto_backup and backup_channel:
                        try:
                            copied_msg = await message.copy(chat_id=backup_channel)
                            target_media = getattr(
                                copied_msg, copied_msg.media.value, media_obj
                            )
                            target_caption = copied_msg.caption
                            await asyncio.sleep(1)
                        except Exception:
                            pass

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
                    except Exception:
                        errors += len(media_to_save)

                await save_resume_state(chat, last_processed)
                if delay_speed > 0:
                    await asyncio.sleep(delay_speed)

        except Exception as e:
            try:
                await msg.edit(f"⚠️ Error: `{e}`")
            except Exception:
                pass
        else:
            if not temp.INDEX_CANCEL.get(chat):
                try:
                    await msg.edit(
                        f"🎉 **Indexing Complete!**\nSaved: `{total_files}` files | Duplicates: `{duplicate}`"
                    )
                except Exception:
                    pass
