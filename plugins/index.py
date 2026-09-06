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
# 🛡️ SAFE MEDIA CLONER (Bypasses Pyrogram V2 Memory Locks)
# ============================================================
class DummyMedia:
    pass


def wrap_media(media_obj, file_type, caption):
    """Safely extracts data from Pyrogram read-only objects for MongoDB."""
    wrapper = DummyMedia()
    wrapper.file_id = getattr(media_obj, "file_id", "")
    wrapper.file_unique_id = getattr(media_obj, "file_unique_id", "")
    wrapper.file_name = getattr(media_obj, "file_name", "Unknown_File")
    wrapper.file_size = getattr(media_obj, "file_size", 0)
    wrapper.mime_type = getattr(media_obj, "mime_type", "")
    wrapper.file_type = file_type
    wrapper.caption = caption
    return wrapper


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

    # Safely wrap before sending to database
    safe_media = wrap_media(media_obj, message.media.value, message.caption)

    try:
        await save_batch([safe_media])
        logger.info(
            f"Auto-indexed new file from {message.chat.title} ({message.chat.id})"
        )
    except Exception as e:
        logger.error(f"Auto-index failed for {message.chat.title}: {e}")


# ============================================================
# 🎛️ GLOBAL SKIP CONTROLS
# ============================================================
@Client.on_message(filters.command("setskip") & filters.user(ADMINS))
async def set_skip_number(bot: Client, message: Message):
    if len(message.command) > 1:
        skip = message.command[1]
        try:
            skip = int(skip)
        except ValueError:
            return await message.reply("Skip number should be an integer.")
        temp.CURRENT = skip
        await message.reply(f"✅ Successfully set default SKIP number to `{skip}`.")
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
    # Isolated Cancel Request (Only cancels the specific channel)
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

    # Process Index Acceptance/Rejection
    data_parts = query.data.split("#")

    # Safely extract callback payload including the localized skip value
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
                f"Your submission for indexing `{chat}` has been declined by our moderators.",
                reply_to_message_id=int(lst_msg_id),
            )
        except Exception as e:
            logger.error(f"Failed to send rejection to user {from_user}: {e}")
        return

    if lock.locked():
        return await query.answer(
            "Wait until the previous system-wide indexing process completes.",
            show_alert=True,
        )

    msg = query.message
    await query.answer("Processing...⏳", show_alert=True)

    if int(from_user) not in ADMINS:
        try:
            await bot.send_message(
                int(from_user),
                f"Your submission for indexing `{chat}` has been accepted by our moderators and is now processing.",
            )
        except Exception:
            pass

    try:
        chat = int(chat)
    except ValueError:
        pass

    try:
        await msg.edit(
            "Starting Indexing...",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("Cancel", callback_data=f"idx_cancel#{chat}")]]
            ),
        )
    except MessageNotModified:
        pass

    # Launch Database Injection Payload
    await index_files_to_db(int(lst_msg_id), chat, msg, bot, skip_val)


# ============================================================
# 🎯 PROCESS INDEX REQUESTS
# ============================================================
async def process_index_request(bot: Client, message: Message, chat_id, last_msg_id):
    try:
        chat_obj = await bot.get_chat(chat_id)
        chat_id = chat_obj.id
    except (ChannelInvalid, ChannelPrivate):
        return await message.reply(
            "This may be a private channel/group. Make me an admin there to index the files."
        )
    except (UsernameInvalid, UsernameNotModified):
        return await message.reply("Invalid Link/Username specified.")
    except Exception as e:
        logger.exception(e)
        return await message.reply(f"Error accessing chat: {e}")

    try:
        k = await bot.get_messages(chat_id, last_msg_id)
        if k.empty:
            return await message.reply(
                "This may be a group and I am not an admin, or the message does not exist."
            )
    except Exception:
        return await message.reply(
            "Make sure that I am an admin in the channel (if the channel is private)."
        )

    if message.from_user.id in ADMINS:
        current_skip = getattr(temp, "CURRENT", 0)
        skip_count = current_skip

        try:
            ask_msg = await message.reply(
                f"**Indexing Initiated!**\n\nCurrent Skip is `{current_skip}`.\n"
                f"Send a new number to change it, or send `0` to skip nothing.\n\n*(Timeout in 15s)*",
                quote=True,
            )
            response = await bot.listen(
                chat_id=message.chat.id,
                filters=filters.user(message.from_user.id),
                timeout=15,
            )
            if response and response.text:
                try:
                    skip_count = int(response.text)
                except ValueError:
                    pass
                try:
                    await response.delete()
                except Exception:
                    pass
            try:
                await ask_msg.delete()
            except Exception:
                pass
        except asyncio.TimeoutError:
            try:
                await ask_msg.delete()
            except Exception:
                pass

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
            f"Do you want to index this Channel/Group?\n\n"
            f"**Chat ID:** <code>{chat_id}</code>\n"
            f"**Last Message ID:** <code>{last_msg_id}</code>\n"
            f"**Skipping First:** <code>{skip_count}</code> messages",
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
        f"Chat ID: <code>{chat_id}</code>\nLast Message ID: <code>{last_msg_id}</code>\nInviteLink: {link}",
        reply_markup=InlineKeyboardMarkup(buttons),
    )
    await message.reply(
        "Thank you for the contribution! Wait for my moderators to verify the files."
    )


# ============================================================
# 💬 COMMAND LISTENERS
# ============================================================
@Client.on_message(filters.command("index") & filters.private & filters.incoming)
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
            "**Usage:** `/index <chat_id_or_username> <last_message_id>`\n\n*(Note: You can also just forward a message from the channel or send a message link to start indexing!)*"
        )

    chat_id = message.command[1]
    try:
        last_msg_id = int(message.command[2])
    except ValueError:
        return await message.reply("Last message ID must be an integer.")

    if chat_id.isnumeric() or (chat_id.startswith("-100") and chat_id[4:].isnumeric()):
        chat_id = int(chat_id)

    await process_index_request(bot, message, chat_id, last_msg_id)


# Captures Native Telegram Links OR Forwarded Media correctly
@Client.on_message(
    filters.private
    & filters.incoming
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
                # Check for isolated channel cancellation
                if temp.INDEX_CANCEL.get(chat):
                    try:
                        await msg.edit(
                            f"**Successfully Cancelled!!**\n\n"
                            f"Saved <code>{total_files}</code> files to database!\n"
                            f"Duplicate Files Skipped: <code>{duplicate}</code>\n"
                            f"Deleted Messages Skipped: <code>{deleted}</code>\n"
                            f"Non-Media messages skipped: <code>{no_media + unsupported}</code>\n"
                            f"Errors Occurred: <code>{errors}</code>"
                        )
                    except Exception:
                        pass
                    temp.INDEX_CANCEL[chat] = False
                    return

                chunk = message_ids[i : i + 200]
                messages = []
                max_retries = 3

                # Resilient Fetching Loop
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

                    if time.time() - last_update_time > 10:
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
                                f"Total messages fetched: <code>{fetched_count}</code>\n"
                                f"Total messages saved: <code>{total_files}</code>\n"
                                f"Duplicate Files Skipped: <code>{duplicate}</code>\n"
                                f"Deleted/Non-Media Skipped: <code>{deleted + no_media}</code>\n"
                                f"Errors Occurred: <code>{errors}</code>",
                                reply_markup=reply,
                            )
                        except FloodWait as e:
                            await asyncio.sleep(e.value + 1)
                        except MessageNotModified:
                            pass
                        last_update_time = time.time()

                    if message.empty:
                        deleted += 1
                        continue
                    elif not message.media:
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

                    # ⚡ Safely clone object using DummyMedia to completely bypass Python slot limits
                    safe_media = wrap_media(
                        media_obj, message.media.value, message.caption
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
                await msg.edit(f"Error: {e}")
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
