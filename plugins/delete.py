import re
from logging import ERROR, getLogger

from pyrogram import Client, filters
from pyrogram.types import Message

import info

# ⚡ FIXED: Aliased Media to _Media
from database.ia_filterdb import Media as _Media
from database.ia_filterdb import unpack_new_file_id

logger = getLogger(__name__)
logger.setLevel(ERROR)

if not hasattr(info, "FILE_AUTO_DELETE"):
    info.FILE_AUTO_DELETE = 1800

if not hasattr(info, "BUTTON_AUTO_DELETE"):
    info.BUTTON_AUTO_DELETE = 1800


async def admin_check(_, __, message: Message):
    if not message.from_user:
        return False
    return (
        message.from_user.id in info.ADMINS or str(message.from_user.id) in info.ADMINS
    )


admin_filter = filters.create(admin_check)


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
            else:
                return await status_msg.edit_text("⚠️ **File not found in database.**")

        reply = message.reply_to_message
        if not (reply and reply.media):
            return await message.reply_text(
                "⚙️ **Usage:**\n`/delete <file_id>`\nOr reply to a file with `/delete`",
                quote=True,
            )

        status_msg = await message.reply_text("⏳ **Processing...**", quote=True)
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
    if len(message.command) < 2:
        return await message.reply_text(
            f"⚙️ **Usage:** `/autodelete [seconds]`\n\n⏱ **Current File Auto-Delete:** `{info.FILE_AUTO_DELETE}` seconds."
        )
    try:
        seconds = int(message.command[1])
        if seconds < 0:
            raise ValueError
        info.FILE_AUTO_DELETE = seconds

        if seconds == 0:
            await message.reply_text(
                "✅ **File Auto-Delete has been DISABLED (0 seconds).**"
            )
        else:
            await message.reply_text(
                f"✅ **File Auto-Delete successfully set to:** `{seconds}` seconds."
            )
    except ValueError:
        await message.reply_text(
            "❌ **Invalid duration!** Please provide a valid positive integer (seconds)."
        )


@Client.on_message(filters.command("buttondel") & admin_filter)
async def set_buttondel_timer(bot: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text(
            f"⚙️ **Usage:** `/buttondel [seconds]`\n\n⏱ **Current Button Auto-Delete:** `{info.BUTTON_AUTO_DELETE}` seconds."
        )
    try:
        seconds = int(message.command[1])
        if seconds < 0:
            raise ValueError
        info.BUTTON_AUTO_DELETE = seconds

        if seconds == 0:
            await message.reply_text(
                "✅ **Group Button Auto-Delete has been DISABLED (0 seconds).**"
            )
        else:
            await message.reply_text(
                f"✅ **Group Button Auto-Delete successfully set to:** `{seconds}` seconds."
            )
    except ValueError:
        await message.reply_text(
            "❌ **Invalid duration!** Please provide a valid positive integer (seconds)."
        )
