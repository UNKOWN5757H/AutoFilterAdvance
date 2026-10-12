import asyncio
import re
import time
from logging import INFO, getLogger

from motor.motor_asyncio import AsyncIOMotorClient
from pyrogram import Client, enums, filters
from pyrogram.errors import (
    ChannelInvalid,
    ChannelPrivate,
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
resume_db = cw_db = idx_db = None
try:
    _DB_CLIENT = AsyncIOMotorClient(info.DATABASE_URI)
    _BOT_DB = _DB_CLIENT[info.DATABASE_NAME]
    resume_db = _BOT_DB["index_resume"]
    cw_db = _BOT_DB["clean_words"]
    idx_db = _BOT_DB["index_settings"]
except Exception as e:
    logger.error(f"Failed to init advanced DBs: {e}")


# ============================================================
# 👑 FULL POWER ADMIN CHECKER (GLOBAL + CHAT + ANONYMOUS)
# ============================================================
def get_admin_list():
    raw_admins = getattr(info, "ADMINS", [])
    if isinstance(raw_admins, (str, int)):
        raw_admins = str(raw_admins).replace(",", " ").split()
    return [int(x) for x in raw_admins if str(x).strip().lstrip("-").isdigit()]


async def is_user_admin(client: Client, message: Message):
    admin_list = get_admin_list()

    if message.from_user and message.from_user.id in admin_list:
        return True
    if message.sender_chat and message.sender_chat.id in admin_list:
        return True
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


async def cb_admin_check(_, client: Client, query: CallbackQuery):
    return await is_user_admin(client, query.message)


admin_filter = filters.create(admin_check)
cb_admin_filter = filters.create(cb_admin_check)


# ============================================================
# 🗄️ DATABASE HELPERS
# ============================================================
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


# ============================================================
# 🤖 AUTO INDEX LISTENER
# ============================================================
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

    raw_name, raw_caption = (
        getattr(media_obj, "file_name", "Unknown"),
        message.caption or "",
    )
    blacklist, whitelist = idx_settings.get("blacklist", []), idx_settings.get(
        "whitelist", []
    )

    if any(
        b.lower() in raw_name.lower() or b.lower() in raw_caption.lower()
        for b in blacklist
    ):
        return
    if whitelist and not any(
        w.lower() in raw_name.lower() or w.lower() in raw_caption.lower()
        for w in whitelist
    ):
        return

    target_media, target_caption = media_obj, message.caption
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
# ⚡ PM MEDIA FORWARD HANDLER
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
        chat_id = message.forward_from_chat.username or message.forward_from_chat.id
        buttons = [
            [
                InlineKeyboardButton(
                    "Index Whole Channel",
                    callback_data=f"idx#ac#{chat_id}#{message.forward_from_message_id}#{message.from_user.id}#all",
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
        await save_single_file(bot, message)


@Client.on_callback_query(filters.regex(r"^save_single#") & cb_admin_filter, group=-5)
async def save_single_callback(bot: Client, query: CallbackQuery):
    msg_id = int(query.data.split("#")[1])
    try:
        original_message = await bot.get_messages(query.message.chat.id, msg_id)
        await query.message.delete()
        if original_message:
            await save_single_file(bot, original_message)
    except Exception:
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

    raw_name, raw_caption = (
        getattr(media_obj, "file_name", "Unknown"),
        message.caption or "",
    )
    blacklist, whitelist = idx_settings.get("blacklist", []), idx_settings.get(
        "whitelist", []
    )

    if any(
        b.lower() in raw_name.lower() or b.lower() in raw_caption.lower()
        for b in blacklist
    ):
        return await message.reply("⚠️ Ignored: File contains blacklisted words.")
    if whitelist and not any(
        w.lower() in raw_name.lower() or w.lower() in raw_caption.lower()
        for w in whitelist
    ):
        return await message.reply(
            "⚠️ Ignored: File does not contain whitelisted words."
        )

    target_media, target_caption = media_obj, message.caption
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


@Client.on_message(filters.command("currentskip") & admin_filter, group=-5)
async def current_skip_number(bot: Client, message: Message):
    current = getattr(temp, "CURRENT", 0)
    await message.reply(f"ℹ️ The current default SKIP number is: `{current}`")


# ============================================================
# 🧭 CALLBACK HANDLERS & PROCESSORS
# ============================================================
@Client.on_callback_query(
    filters.regex(r"^(idx|idx_cancel|close_data)") & cb_admin_filter, group=-5
)
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
        chat_id = (await bot.get_chat(chat_id)).id
    except (ChannelInvalid, ChannelPrivate, UsernameInvalid, UsernameNotModified):
        return await message.reply("⚠️ Invalid Link/Channel or Bot is not Admin there.")
    except Exception as e:
        return await message.reply(f"⚠️ Error: `{e}`")

    skip_count = getattr(temp, "CURRENT", 0)
    buttons = [
        [
            InlineKeyboardButton(
                "Yes, Start Indexing",
                callback_data=f"idx#ac#{chat_id}#{last_msg_id}#{message.from_user.id if message.from_user else 0}#{filter_type}",
            )
        ],
        [InlineKeyboardButton("Close", callback_data="close_data")],
    ]
    return await message.reply(
        f"**Ready to Index ({filter_type.title()})**\n\n**Chat ID:** <code>{chat_id}</code>\n**Last Message:** <code>{last_msg_id}</code>\n**Skip Count:** <code>{skip_count}</code>",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


@Client.on_message(
    filters.command(["index", "indexvideo", "indexdoc", "indexaudio"]) & admin_filter,
    group=-5,
)
async def index_command(bot: Client, message: Message):
    cmd = message.command[0].lower()
    filter_type = (
        "video"
        if cmd == "indexvideo"
        else (
            "document"
            if cmd == "indexdoc"
            else "audio" if cmd == "indexaudio" else "all"
        )
    )

    if (
        message.reply_to_message
        and message.reply_to_message.forward_from_chat
        and message.reply_to_message.forward_from_chat.type == enums.ChatType.CHANNEL
    ):
        chat_id = (
            message.reply_to_message.forward_from_chat.username
            or message.reply_to_message.forward_from_chat.id
        )
        return await process_index_request(
            bot,
            message,
            chat_id,
            message.reply_to_message.forward_from_message_id,
            filter_type,
        )

    if len(message.command) != 3:
        return await message.reply(f"**Usage:** `/{cmd} <chat_id> <last_message_id>`")

    chat_id = (
        int(message.command[1])
        if message.command[1].lstrip("-").isdigit()
        else message.command[1]
    )
    try:
        last_msg_id = int(message.command[2])
    except ValueError:
        return await message.reply("⚠️ Last message ID must be an integer.")

    await process_index_request(bot, message, chat_id, last_msg_id, filter_type)


@Client.on_message(filters.command("resumeindex") & admin_filter, group=-5)
async def resume_index_command(bot: Client, message: Message):
    if len(message.command) != 2:
        return await message.reply("**Usage:** `/resumeindex <chat_id>`")

    chat_id = (
        int(message.command[1])
        if message.command[1].lstrip("-").isnumeric()
        else message.command[1]
    )
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


@Client.on_message(
    filters.text
    & filters.regex(
        r"(https://)?(t\.me/|telegram\.me/|telegram\.dog/)(c/)?(\d+|[a-zA-Z_0-9]+)/(\d+)$"
    )
    & admin_filter,
    group=-5,
)
async def send_for_index(bot: Client, message: Message):
    match = re.match(
        r"(https://)?(t\.me/|telegram\.me/|telegram\.dog/)(c/)?(\d+|[a-zA-Z_0-9]+)/(\d+)$",
        message.text,
    )
    if match:
        chat_id = (
            int(f"-100{match.group(4)}")
            if match.group(4).isnumeric()
            else match.group(4)
        )
        await process_index_request(bot, message, chat_id, int(match.group(5)), "all")


@Client.on_message(
    filters.private & filters.forwarded & filters.text & admin_filter, group=-5
)
async def pm_forward_text_indexer(bot: Client, message: Message):
    if (
        message.forward_from_chat
        and message.forward_from_chat.type == enums.ChatType.CHANNEL
    ):
        chat_id = message.forward_from_chat.username or message.forward_from_chat.id
        await process_index_request(
            bot, message, chat_id, message.forward_from_message_id, "all"
        )


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
    min_size, blacklist, whitelist, auto_backup, backup_channel = (
        idx_settings.get("min_size", 0),
        idx_settings.get("blacklist", []),
        idx_settings.get("whitelist", []),
        idx_settings.get("auto_backup", False),
        idx_settings.get("backup_channel"),
    )
    delay_speed = getattr(temp, "INDEX_SPEED", 0)

    if not hasattr(temp, "INDEX_CANCEL"):
        temp.INDEX_CANCEL = {}
    temp.INDEX_CANCEL[chat] = False

    async with lock:
        try:
            start_id, fetched_count, last_update_time = (
                max(1, skip_number),
                0,
                time.time(),
            )
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

                chunk, messages, max_retries = message_ids[i : i + 200], [], 3
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
                        try:
                            await msg.edit_text(
                                text=f"⚡ **Indexing ({filter_type})...**\nFetched: `{fetched_count}` | Saved: `{total_files}`",
                                reply_markup=InlineKeyboardMarkup(
                                    [
                                        [
                                            InlineKeyboardButton(
                                                "Cancel",
                                                callback_data=f"idx_cancel#{chat}",
                                            )
                                        ]
                                    ]
                                ),
                            )
                        except Exception:
                            pass
                        last_update_time = time.time()

                    if getattr(message, "empty", False):
                        deleted += 1
                        continue
                    if not getattr(message, "media", None):
                        no_media += 1
                        continue
                    if message.media not in [
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
                    if not media_obj or media_obj.file_size < min_size:
                        unsupported += 1
                        continue

                    raw_name, raw_caption = (
                        getattr(media_obj, "file_name", "Unknown"),
                        message.caption or "",
                    )
                    if any(
                        b.lower() in raw_name.lower()
                        or b.lower() in raw_caption.lower()
                        for b in blacklist
                    ):
                        unsupported += 1
                        continue
                    if whitelist and not any(
                        w.lower() in raw_name.lower()
                        or w.lower() in raw_caption.lower()
                        for w in whitelist
                    ):
                        unsupported += 1
                        continue

                    target_media, target_caption = media_obj, raw_caption
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
                    media_to_save.append(
                        SafeMedia(
                            target_media,
                            message.media.value,
                            target_caption,
                            cleaned_name,
                        )
                    )

                if media_to_save:
                    try:
                        result = await save_batch(media_to_save)
                        if isinstance(result, tuple) and len(result) == 3:
                            total_files += result[0]
                            duplicate += result[1]
                            errors += result[2]
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
