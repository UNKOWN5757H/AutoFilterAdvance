import asyncio
import re
import time
from logging import INFO, getLogger

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

from database.ia_filterdb import save_batch
from info import ADMINS
from info import INDEX_REQ_CHANNEL as LOG_CHANNEL
from utils import temp

logger = getLogger(__name__)
logger.setLevel(INFO)


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
    from info import CHANNELS

    AUTO_INDEX_CHANNELS.extend(parse_channels(CHANNELS))
except ImportError:
    pass

try:
    from info import INDEX_CHANNELS

    AUTO_INDEX_CHANNELS.extend(parse_channels(INDEX_CHANNELS))
except ImportError:
    pass

AUTO_INDEX_CHANNELS = list(set(AUTO_INDEX_CHANNELS))
lock = asyncio.Lock()


# ============================================================
# 🛡️ DYNAMIC MEDIA PROXY (Bypasses Pyrogram V2 Strict Memory)
# ============================================================
class MediaProxy:
    """Creates a safe bridge to pass read-only Pyrogram data to MongoDB."""

    def __init__(self, media_obj, file_type, caption):
        self._media = media_obj
        self.file_type = file_type
        self.caption = caption

    def __getattr__(self, name):
        return getattr(self._media, name)


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

    # Wrap securely
    safe_media = MediaProxy(media_obj, message.media.value, message.caption)

    try:
        await save_batch([safe_media])
        logger.info(
            f"Auto-indexed new file from {message.chat.title} ({message.chat.id})"
        )
    except Exception as e:
        logger.error(f"Auto-index failed for {message.chat.title}: {e}")


# ============================================================
# 🎛️ SKIP CONTROLS
# ============================================================
@Client.on_message(filters.command("setskip") & filters.user(ADMINS))
async def set_skip_number(bot: Client, message: Message):
    if len(message.command) > 1:
        try:
            skip = int(message.command[1])
            temp.CURRENT = skip
            await message.reply(
                f"✅ Successfully set default SKIP number to `{skip}`.\nThis will be used for your next `/index` command."
            )
        except ValueError:
            await message.reply("⚠️ Skip number must be an integer.")
    else:
        await message.reply("⚠️ Usage: `/setskip 100`")


@Client.on_message(filters.command("currentskip") & filters.user(ADMINS))
async def current_skip_number(bot: Client, message: Message):
    current = getattr(temp, "CURRENT", 0)
    await message.reply(f"ℹ️ The current default SKIP number is: `{current}`")


@Client.on_message(filters.command("deleteskip") & filters.user(ADMINS))
async def delete_skip_number(bot: Client, message: Message):
    temp.CURRENT = 0
    await message.reply("✅ Successfully reset the SKIP number to `0`.")


# ============================================================
# 🧭 CALLBACK HANDLERS
# ============================================================
@Client.on_callback_query(filters.regex(r"^(index|idx_cancel)"))
async def index_files(bot: Client, query):
    # Process Cancel Request
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

    # Process Index Start/Reject
    data_parts = query.data.split("#")

    if len(data_parts) == 6:
        _, action, chat, lst_msg_id, from_user, skip_val = data_parts
        skip_val = int(skip_val)
    elif len(data_parts) == 5:
        _, action, chat, lst_msg_id, from_user = data_parts
        skip_val = 0
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

    # Launch Database Injection Payload Detached from UI
    asyncio.create_task(index_files_to_db(int(lst_msg_id), chat, msg, bot, skip_val))


# ============================================================
# 🎯 PROCESS INDEX REQUESTS
# ============================================================
async def process_index_request(bot: Client, message: Message, chat_id, last_msg_id):
    try:
        chat_obj = await bot.get_chat(chat_id)
        chat_id = chat_obj.id
    except (ChannelInvalid, ChannelPrivate, UsernameInvalid, UsernameNotModified):
        return await message.reply(
            "⚠️ Invalid Link/Channel or Bot is not an Admin there."
        )
    except Exception as e:
        return await message.reply(f"⚠️ Error accessing chat: `{e}`")

    # If Admin triggers, instantly show Start button (Bypassing the broken bot.listen)
    if message.from_user and message.from_user.id in ADMINS:
        skip_count = getattr(temp, "CURRENT", 0)
        buttons = [
            [
                InlineKeyboardButton(
                    "Yes, Start Indexing",
                    callback_data=f"index#accept#{chat_id}#{last_msg_id}#{message.from_user.id}#{skip_count}",
                )
            ],
            [InlineKeyboardButton("Close", callback_data="close_data")],
        ]
        return await message.reply(
            f"**Ready to Index Channel/Group**\n\n"
            f"**Chat ID:** <code>{chat_id}</code>\n"
            f"**Last Message:** <code>{last_msg_id}</code>\n"
            f"**Skipping First:** <code>{skip_count}</code> messages\n\n"
            f"*(If you want to skip more, use `/setskip` first)*",
            reply_markup=InlineKeyboardMarkup(buttons),
        )

    # Standard User Request
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
                callback_data=f"index#accept#{chat_id}#{last_msg_id}#{message.from_user.id}#0",
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
        f"#IndexRequest\n\nBy: {message.from_user.mention} (<code>{message.from_user.id}</code>)\n"
        f"Chat ID: <code>{chat_id}</code>\nLast Msg ID: <code>{last_msg_id}</code>\nLink: {link}",
        reply_markup=InlineKeyboardMarkup(buttons),
    )
    await message.reply(
        "✅ Thank you for the contribution! Please wait for our moderators to verify."
    )


# ============================================================
# 💬 COMMAND LISTENERS
# ============================================================
@Client.on_message(filters.command("index") & filters.incoming)
async def index_command(bot: Client, message: Message):
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
        return await process_index_request(bot, message, chat_id, last_msg_id)

    if len(message.command) != 3:
        return await message.reply(
            "**Usage:** `/index <chat_id> <last_message_id>`\n\n*(Or just forward a message/link to me!)*"
        )

    chat_id = message.command[1]
    try:
        last_msg_id = int(message.command[2])
    except ValueError:
        return await message.reply("⚠️ Last message ID must be an integer.")

    if chat_id.isnumeric() or (chat_id.startswith("-100") and chat_id[4:].isnumeric()):
        chat_id = int(chat_id)

    await process_index_request(bot, message, chat_id, last_msg_id)


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
    chat_id = None
    last_msg_id = None

    if (
        message.forward_from_chat
        and message.forward_from_chat.type == enums.ChatType.CHANNEL
    ):
        last_msg_id = message.forward_from_message_id
        chat_id = message.forward_from_chat.username or message.forward_from_chat.id
    elif message.text:
        regex = re.compile(
            r"(https://)?(t\.me/|telegram\.me/|telegram\.dog/)(c/)?(\d+|[a-zA-Z_0-9]+)/(\d+)$"
        )
        match = regex.match(message.text)
        if match:
            chat_id = match.group(4)
            last_msg_id = int(match.group(5))
            if chat_id.isnumeric():
                chat_id = int(f"-100{chat_id}")
        else:
            return
    else:
        return

    if message.from_user and message.from_user.id in ADMINS:
        await process_index_request(bot, message, chat_id, last_msg_id)


# ============================================================
# 💾 DATABASE BATCH SAVER
# ============================================================
async def index_files_to_db(
    lst_msg_id, chat, msg: Message, bot: Client, skip_number: int = 0
):
    total_files = 0
    duplicate = 0
    errors = 0
    deleted = 0
    no_media = 0
    unsupported = 0

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
                # Channel Cancellation Check
                if temp.INDEX_CANCEL.get(chat):
                    try:
                        await msg.edit(
                            f"**⛔ Successfully Cancelled!!**\n\n"
                            f"Saved <code>{total_files}</code> files to database!\n"
                            f"Duplicate Files Skipped: <code>{duplicate}</code>\n"
                            f"Deleted Messages: <code>{deleted}</code>\n"
                            f"Non-Media Skipped: <code>{no_media + unsupported}</code>\n"
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
                                text=f"⚡ **Ultra-Speed Indexing...** ⚡\n\n"
                                f"Total fetched: <code>{fetched_count}</code>\n"
                                f"Total saved: <code>{total_files}</code>\n"
                                f"Duplicates: <code>{duplicate}</code>\n"
                                f"Deleted/Text: <code>{deleted + no_media}</code>\n"
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

                    media_obj = getattr(message, message.media.value, None)
                    if not media_obj:
                        unsupported += 1
                        continue

                    # ⚡ Push through Proxy
                    safe_media = MediaProxy(
                        media_obj, message.media.value, getattr(message, "caption", "")
                    )
                    media_to_save.append(safe_media)

                if media_to_save:
                    try:
                        saved, dups, errs = await save_batch(media_to_save)
                        total_files += saved
                        duplicate += dups
                        errors += errs
                    except Exception as e:
                        logger.error(f"Batch Save Error: {e}")
                        errors += len(media_to_save)

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
                        f"Non-Media messages skipped: <code>{no_media + unsupported}</code>\n"
                        f"Errors Occurred: <code>{errors}</code>"
                    )
                except Exception:
                    pass
