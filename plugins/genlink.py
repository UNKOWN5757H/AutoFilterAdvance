import base64
import json
import os
import re

from pyrogram import Client, enums, filters
from pyrogram.errors import ChannelInvalid, UsernameInvalid, UsernameNotModified

from database.ia_filterdb import unpack_new_file_id
from info import ADMINS, FILE_STORE_CHANNEL, LOG_CHANNEL, PUBLIC_FILE_STORE
from utils import temp


async def allowed(_, __, message):
    return bool(
        PUBLIC_FILE_STORE or (message.from_user and message.from_user.id in ADMINS)
    )


@Client.on_message(filters.command(["link", "plink"]) & filters.create(allowed))
async def gen_link_s(bot, message):
    replied = message.reply_to_message
    if not replied or not replied.media:
        return await message.reply("Reply to supported media.")
    if message.has_protected_content and message.chat.id not in ADMINS:
        return

    file_id, _ = unpack_new_file_id(getattr(replied, replied.media.value).file_id)
    string = (
        f"filep_{file_id}"
        if message.text.lower().strip() == "/plink"
        else f"file_{file_id}"
    )
    outstr = base64.urlsafe_b64encode(string.encode("ascii")).decode().strip("=")
    await message.reply(
        f"🔗 **Here is your Link:**\nhttps://t.me/{temp.U_NAME}?start={outstr}"
    )


@Client.on_message(filters.command(["batch", "pbatch"]) & filters.create(allowed))
async def gen_link_batch(bot, message):
    links = message.text.strip().split()
    if len(links) != 3:
        return await message.reply("⚙️ **Usage:** `/batch <start_link> <end_link>`")

    cmd, first, last = links
    regex = re.compile(
        r"(https://)?(t\.me/|telegram\.me/|telegram\.dog/)(c/)?(\d+|[a-zA-Z_0-9]+)/(\d+)$"
    )
    m1, m2 = regex.match(first), regex.match(last)
    if not m1 or not m2:
        return await message.reply("❌ **Invalid link format.**")

    f_chat_id, f_msg_id = m1.group(4), int(m1.group(5))
    l_chat_id, l_msg_id = m2.group(4), int(m2.group(5))
    if f_chat_id.isnumeric():
        f_chat_id = int(f"-100{f_chat_id}")
    if l_chat_id.isnumeric():
        l_chat_id = int(f"-100{l_chat_id}")
    if f_chat_id != l_chat_id:
        return await message.reply("❌ **Chat IDs do not match.**")

    try:
        chat_id = (await bot.get_chat(f_chat_id)).id
    except (ChannelInvalid, UsernameInvalid, UsernameNotModified):
        return await message.reply(
            "❌ **Invalid link or I lack permissions in that chat.**"
        )

    sts = await message.reply("⏳ **Generating link...**")
    if chat_id in FILE_STORE_CHANNEL:
        b_64 = (
            base64.urlsafe_b64encode(
                f"{f_msg_id}_{l_msg_id}_{chat_id}_{cmd.lower().strip()}".encode("ascii")
            )
            .decode()
            .strip("=")
        )
        return await sts.edit(
            f"🔗 **Here is your link:**\nhttps://t.me/{temp.U_NAME}?start=DSTORE-{b_64}"
        )

    outlist, og_msg, tot = [], 0, 0
    async for msg in bot.iter_messages(chat_id, l_msg_id, f_msg_id):
        tot += 1
        if msg.empty or msg.service or not msg.media:
            continue
        try:
            file = getattr(msg, msg.media.value)
            outlist.append(
                {
                    "file_id": file.file_id,
                    "caption": msg.caption.html if msg.caption else "",
                    "title": getattr(file, "file_name", ""),
                    "size": file.file_size,
                    "protect": cmd.lower().strip() == "/pbatch",
                }
            )
            og_msg += 1
        except Exception:
            pass

        if tot % 20 == 0:
            try:
                await sts.edit(
                    f"⏳ **Saving Messages...**\nDone: `{tot}`\nRemaining: `{(l_msg_id - f_msg_id) - tot}`"
                )
            except Exception:
                pass

    file_path = f"batchmode_{message.from_user.id}.json"
    with open(file_path, "w+") as out:
        json.dump(outlist, out)

    post = await bot.send_document(
        LOG_CHANNEL, file_path, file_name="Batch.json", caption="⚠️ Batch file store."
    )
    os.remove(file_path)

    file_id, _ = unpack_new_file_id(post.document.file_id)
    await sts.edit(
        f"🔗 **Here is your link (Contains `{og_msg}` files):**\nhttps://t.me/{temp.U_NAME}?start=BATCH-{file_id}"
    )
