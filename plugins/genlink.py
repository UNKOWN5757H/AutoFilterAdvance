import base64
import json
import os
import re
from logging import INFO, getLogger

from pyrogram import Client, enums, filters
from pyrogram.errors import FloodWait
from pyrogram.errors.exceptions.bad_request_400 import (
    ChannelInvalid,
    UsernameInvalid,
    UsernameNotModified,
)

import info
from database.ia_filterdb import unpack_new_file_id
from utils import temp

logger = getLogger(__name__)
logger.setLevel(INFO)


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


def is_file_store_channel(chat_id: int) -> bool:
    fsc = getattr(info, "FILE_STORE_CHANNEL", [])
    if isinstance(fsc, int):
        return chat_id == fsc
    if isinstance(fsc, str):
        return str(chat_id) in [
            x.strip() for x in fsc.replace(",", " ").split() if x.strip()
        ]
    if isinstance(fsc, list):
        return chat_id in [int(x) for x in fsc if str(x).strip().lstrip("-").isdigit()]
    return False


async def allowed(_, __, message):
    if getattr(info, "PUBLIC_FILE_STORE", False):
        return True
    if message.from_user and message.from_user.id in get_admin_list():
        return True
    return False


# ============================================================
# 🔗 SINGLE FILE LINK GENERATOR (/link, /plink)
# ============================================================
@Client.on_message(filters.command(["link", "plink"]) & filters.create(allowed))
async def gen_link_s(bot: Client, message):
    replied = message.reply_to_message
    if not replied:
        return await message.reply("⚠️ Reply to a message to get a shareable link.")

    file_type = replied.media
    if not file_type or file_type not in [
        enums.MessageMediaType.VIDEO,
        enums.MessageMediaType.AUDIO,
        enums.MessageMediaType.DOCUMENT,
        enums.MessageMediaType.PHOTO,
        enums.MessageMediaType.ANIMATION,
    ]:
        return await message.reply("⚠️ Reply to a valid media file.")

    if (
        getattr(message, "has_protected_content", False)
        and message.from_user.id not in get_admin_list()
    ):
        return await message.reply("❌ Protected media cannot be shared.")

    media_obj = getattr(replied, file_type.value)
    file_id, _ = unpack_new_file_id(media_obj.file_id)

    is_protect = message.command[0].lower() == "plink"
    string = f"filep_{file_id}" if is_protect else f"file_{file_id}"
    outstr = base64.urlsafe_b64encode(string.encode("ascii")).decode().rstrip("=")

    bot_username = temp.U_NAME or (await bot.get_me()).username
    await message.reply(
        f"🔗 **Shareable Link Generated:**\nhttps://t.me/{bot_username}?start={outstr}"
    )


# ============================================================
# 📦 BATCH LINK GENERATOR (/batch, /pbatch)
# ============================================================
@Client.on_message(filters.command(["batch", "pbatch"]) & filters.create(allowed))
async def gen_link_batch(bot: Client, message):
    links = message.text.strip().split()
    if len(links) != 3:
        return await message.reply(
            "⚙️ **Usage Format:**\n`/batch <first_link> <last_link>`\n\n**Example:**\n`/batch https://t.me/c/1234567/10 https://t.me/c/1234567/20`"
        )

    cmd, first, last = links
    regex = re.compile(
        r"(https?://)?(t(elegram)?\.(me|dog)|telegram\.org)/(c/)?(\d+|[a-zA-Z_0-9]+)/(\d+)$"
    )

    match_first = regex.match(first)
    match_last = regex.match(last)
    if not (match_first and match_last):
        return await message.reply("❌ Invalid Telegram message links.")

    f_chat_raw, f_msg_id = match_first.group(6), int(match_first.group(7))
    l_chat_raw, l_msg_id = match_last.group(6), int(match_last.group(7))

    f_chat_id = int(f"-100{f_chat_raw}") if f_chat_raw.isdigit() else f_chat_raw
    l_chat_id = int(f"-100{l_chat_raw}") if l_chat_raw.isdigit() else l_chat_raw

    if f_chat_id != l_chat_id:
        return await message.reply(
            "❌ Both links must originate from the same channel."
        )

    try:
        chat = await bot.get_chat(f_chat_id)
        chat_id = chat.id
    except ChannelInvalid:
        return await message.reply(
            "❌ Bot lacks access. Add this bot as an admin in the target channel."
        )
    except Exception as e:
        return await message.reply(f"❌ Error accessing channel: `{e}`")

    sts = await message.reply("⏳ **Initiating Batch Generation...**")
    bot_username = temp.U_NAME or (await bot.get_me()).username

    # Layer 1: Native File Store Direct Link
    if is_file_store_channel(chat_id):
        string = f"{f_msg_id}_{l_msg_id}_{chat_id}_{cmd.lower().strip()}"
        b_64 = base64.urlsafe_b64encode(string.encode("ascii")).decode().rstrip("=")
        return await sts.edit(
            f"🔗 **Batch File Store Link:**\nhttps://t.me/{bot_username}?start=DSTORE-{b_64}"
        )

    # Layer 2: Safe Native Chunk Retrieval Engine
    outlist = []
    og_msg = 0
    total_range = list(range(min(f_msg_id, l_msg_id), max(f_msg_id, l_msg_id) + 1))
    total_count = len(total_range)

    # Process in batches of 200 messages
    for i in range(0, total_count, 200):
        chunk_ids = total_range[i : i + 200]
        try:
            messages = await bot.get_messages(chat_id, message_ids=chunk_ids)
        except FloodWait as e:
            await asyncio.sleep(e.value + 1)
            messages = await bot.get_messages(chat_id, message_ids=chunk_ids)
        except Exception as e:
            logger.error(f"Error fetching chunk: {e}")
            continue

        for msg in messages:
            if not msg or msg.empty or msg.service or not msg.media:
                continue
            try:
                media_obj = getattr(msg, msg.media.value)
                caption = msg.caption.html if msg.caption else ""
                outlist.append(
                    {
                        "file_id": media_obj.file_id,
                        "caption": caption,
                        "title": getattr(media_obj, "file_name", ""),
                        "size": getattr(media_obj, "file_size", 0),
                        "protect": cmd.lower().strip() == "/pbatch",
                    }
                )
                og_msg += 1
            except Exception:
                pass

        try:
            await sts.edit(
                f"⏳ **Batch Link Progress:**\nProcessed: `{min(i + 200, total_count)}/{total_count}` messages\nFiles Found: `{og_msg}`"
            )
        except Exception:
            pass

    if not outlist:
        return await sts.edit(
            "❌ No downloadable media found within the provided message range."
        )

    batch_file_path = f"batchmode_{message.from_user.id}.json"
    with open(batch_file_path, "w+", encoding="utf-8") as out:
        json.dump(outlist, out)

    # Multi-Layer Delivery for the Batch Index File
    log_chan = getattr(info, "LOG_CHANNEL", None)
    post = None

    if log_chan:
        try:
            post = await bot.send_document(
                log_chan,
                batch_file_path,
                file_name="Batch.json",
                caption=f"⚠️ Batch generated for {message.from_user.mention} ({og_msg} files).",
            )
        except Exception:
            pass

    if not post:
        # Fallback: Deliver directly to user's chat
        try:
            post = await bot.send_document(
                message.chat.id,
                batch_file_path,
                file_name="Batch.json",
                caption="⚠️ Batch generated locally.",
            )
        except Exception as err:
            if os.path.exists(batch_file_path):
                os.remove(batch_file_path)
            return await sts.edit(f"❌ Failed to archive batch: `{err}`")

    if os.path.exists(batch_file_path):
        os.remove(batch_file_path)

    file_id, _ = unpack_new_file_id(post.document.file_id)
    await sts.edit(
        f"✅ **Batch Link Complete!**\nFiles Included: `{og_msg}`\n\n🔗 https://t.me/{bot_username}?start=BATCH-{file_id}"
    )
