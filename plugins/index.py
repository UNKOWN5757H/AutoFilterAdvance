import asyncio
import logging
import re
import time

from pyrogram import Client, enums, filters
from pyrogram.errors import (
    ChannelInvalid,
    ChannelPrivate,
    ChatAdminRequired,
    FloodWait,
    MessageNotModified,
)
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import info
from database.ia_filterdb import save_batch
from info import ADMINS
from info import INDEX_REQ_CHANNEL as LOG_CHANNEL
from utils import temp

logger = logging.getLogger(__name__)
lock = asyncio.Lock()

# Parse Auto-Index Channels
AUTO_INDEX_CHANNELS = []
for attr in ["CHANNELS", "INDEX_CHANNELS"]:
    val = getattr(info, attr, [])
    if isinstance(val, list):
        AUTO_INDEX_CHANNELS.extend(val)
    elif isinstance(val, (int, str)):
        AUTO_INDEX_CHANNELS.append(int(val))
AUTO_INDEX_CHANNELS = list(set(AUTO_INDEX_CHANNELS))


@Client.on_message(
    filters.channel
    & (filters.document | filters.video | filters.audio)
    & ~filters.forwarded,
    group=-4,
)
async def auto_index_new_files(bot: Client, message):
    if AUTO_INDEX_CHANNELS and message.chat.id not in AUTO_INDEX_CHANNELS:
        return
    media = getattr(message, message.media.value, None)
    if not media:
        return
    media.file_type = message.media.value
    media.caption = message.caption

    try:
        await save_batch([media])
        logger.info(f"Auto-indexed new file from {message.chat.title}")
    except Exception as e:
        logger.error(f"Auto-index failed for {message.chat.title}: {e}")


async def process_index_request(bot, message, chat_id, last_msg_id):
    try:
        chat_obj = await bot.get_chat(chat_id)
        chat_id = chat_obj.id
        k = await bot.get_messages(chat_id, last_msg_id)
        if k.empty:
            return await message.reply("Message does not exist or I lack permissions.")
    except Exception as e:
        return await message.reply(f"Error accessing chat: {e}")

    if message.from_user.id in ADMINS:
        ask_msg = await message.reply(
            "How many messages do you want to **skip**? (Send `0` for none)\n*(60s timeout)*",
            quote=True,
        )
        try:
            response = await bot.listen(
                chat_id=message.chat.id,
                filters=filters.user(message.from_user.id),
                timeout=60,
            )
            temp.CURRENT = int(response.text) if response.text.isdigit() else 0
            await response.delete()
            await ask_msg.delete()
        except asyncio.TimeoutError:
            temp.CURRENT = 0
            await ask_msg.edit("⏳ Timeout. Defaulting to skip `0`.")

        btn = [
            [
                InlineKeyboardButton(
                    "Yes, Start Indexing",
                    callback_data=f"index#accept#{chat_id}#{last_msg_id}#{message.from_user.id}",
                )
            ],
            [InlineKeyboardButton("Close", callback_data="close_data")],
        ]
        return await message.reply(
            f"Index Chat **{chat_id}** up to **{last_msg_id}**?\nSkipping: `{temp.CURRENT}`",
            reply_markup=InlineKeyboardMarkup(btn),
        )

    # User submission
    link = chat_obj.username or str(chat_id)
    btn = [
        [
            InlineKeyboardButton(
                "Accept",
                callback_data=f"index#accept#{chat_id}#{last_msg_id}#{message.from_user.id}",
            )
        ],
        [
            InlineKeyboardButton(
                "Reject",
                callback_data=f"index#reject#{chat_id}#{message.id}#{message.from_user.id}",
            )
        ],
    ]
    await bot.send_message(
        LOG_CHANNEL,
        f"#IndexRequest\nBy: {message.from_user.mention}\nChat: `{chat_id}`\nLast Msg: `{last_msg_id}`\nLink: {link}",
        reply_markup=InlineKeyboardMarkup(btn),
    )
    await message.reply("Thanks! Wait for our ADMINS to verify.")


@Client.on_message(filters.command("index") & filters.private)
async def index_command(bot, message):
    if message.reply_to_message and message.reply_to_message.forward_from_chat:
        chat_id = (
            message.reply_to_message.forward_from_chat.username
            or message.reply_to_message.forward_from_chat.id
        )
        return await process_index_request(
            bot, message, chat_id, message.reply_to_message.forward_from_message_id
        )

    if len(message.command) != 3:
        return await message.reply("**Usage:** `/index <chat_id> <last_message_id>`")
    await process_index_request(
        bot,
        message,
        (
            int(message.command[1])
            if message.command[1].lstrip("-").isdigit()
            else message.command[1]
        ),
        int(message.command[2]),
    )


@Client.on_callback_query(filters.regex(r"^index"))
async def index_callback(bot, query):
    if query.data.startswith("index_cancel"):
        temp.CANCEL = True
        return await query.answer("Cancelling...")

    _, action, chat, lst_msg, user = query.data.split("#")
    if action == "reject":
        await query.message.delete()
        return await bot.send_message(
            int(user), f"Your index request for `{chat}` was rejected by ADMINS."
        )

    if lock.locked():
        return await query.answer(
            "Another indexing process is running.", show_alert=True
        )
    await query.message.edit(
        "Starting Indexing...",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("Cancel", callback_data="index_cancel")]]
        ),
    )
    await index_files_to_db(
        int(lst_msg),
        int(chat) if chat.lstrip("-").isdigit() else chat,
        query.message,
        bot,
    )


async def index_files_to_db(lst_msg_id, chat, msg, bot):
    total, dups, errs, skipped = 0, 0, 0, 0
    async with lock:
        try:
            temp.CANCEL = False
            msg_ids = list(range(max(1, getattr(temp, "CURRENT", 0)), lst_msg_id + 1))
            last_update = time.time()

            for i in range(0, len(msg_ids), 200):
                if temp.CANCEL:
                    break
                chunk = msg_ids[i : i + 200]

                try:
                    messages = await bot.get_messages(chat, chunk)
                except FloodWait as e:
                    await asyncio.sleep(e.value)
                    messages = await bot.get_messages(chat, chunk)
                except Exception as e:
                    logger.error(e)
                    continue

                media_list = []
                for m in messages:
                    if (
                        m.empty
                        or not m.media
                        or m.media
                        not in [
                            enums.MessageMediaType.VIDEO,
                            enums.MessageMediaType.AUDIO,
                            enums.MessageMediaType.DOCUMENT,
                        ]
                    ):
                        skipped += 1
                        continue
                    media = getattr(m, m.media.value, None)
                    if media:
                        media.file_type = m.media.value
                        media.caption = m.caption
                        media_list.append(media)

                if media_list:
                    s, d, e = await save_batch(media_list)
                    total += s
                    dups += d
                    errs += e

                if time.time() - last_update > 8:
                    try:
                        await msg.edit_text(
                            f"⚡ **Indexing...**\nSaved: `{total}`\nDuplicates: `{dups}`\nSkipped: `{skipped}`",
                            reply_markup=InlineKeyboardMarkup(
                                [
                                    [
                                        InlineKeyboardButton(
                                            "Cancel", callback_data="index_cancel"
                                        )
                                    ]
                                ]
                            ),
                        )
                    except Exception:
                        pass
                    last_update = time.time()

        finally:
            temp.CURRENT = 0
            await msg.edit(
                f"🎉 **Indexing Complete!**\n\n✅ Saved: `{total}`\n🔁 Duplicates: `{dups}`\n⏭ Skipped: `{skipped}`\n⚠️ Errors: `{errs}`"
            )
