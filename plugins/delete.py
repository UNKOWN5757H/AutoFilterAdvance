import logging
import re

from pyrogram import Client, filters
from pyrogram.types import Message

import info
from database.ia_filterdb import Media, unpack_new_file_id

logger = logging.getLogger(__name__)

# ============================================================
# ⚙️ Initialize Runtime States for Auto-Deletion
# ============================================================
# Defaults to 1800 seconds (30 minutes) if not set in info.py
if not hasattr(info, "FILE_AUTO_DELETE"):
    info.FILE_AUTO_DELETE = 1800

if not hasattr(info, "BUTTON_AUTO_DELETE"):
    info.BUTTON_AUTO_DELETE = 1800


# ============================================================
# 🗑 1. Single File Deletion (/delete)
# ============================================================
@Client.on_message(filters.command("delete") & filters.user(info.ADMINS))
async def delete_single_file(bot: Client, message: Message):
    """
    Deletes a single file from the database.
    Usage: Reply to a file with /delete OR send /delete [file_id]
    """
    try:
        # Check if a file ID is provided as text
        if len(message.command) == 2:
            file_id = message.command[1].strip()
            status_msg = await message.reply_text("🧹 **Deleting file from DB...**")

            result = await Media.collection.delete_one({"_id": file_id})
            if result.deleted_count:
                return await status_msg.edit_text(
                    f"✅ **File `{file_id}` deleted successfully.**"
                )
            else:
                return await status_msg.edit_text("⚠️ **File not found in database.**")

        # Check if replied to a media message
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

        # 1. Try deleting by exact file ID
        res = await Media.collection.delete_one({"_id": file_id})
        if res.deleted_count:
            return await status_msg.edit_text(
                "✅ **File successfully deleted from database.**"
            )

        # 2. Try deleting by matching file name, size, and mime type
        file_name = re.sub(r"(_|\-|\.|\+)", " ", str(getattr(media, "file_name", "")))
        res = await Media.collection.delete_many(
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


# ============================================================
# 🗑 2. Multiple File Deletion by Name (/delmulti)
# ============================================================
@Client.on_message(filters.command("delmulti") & filters.user(info.ADMINS))
async def delete_multiple_files(bot: Client, message: Message):
    """
    Deletes all files containing a specific keyword in their file_name.
    Usage: /delmulti keyword
    """
    if len(message.command) < 2:
        return await message.reply_text("⚙️ **Usage:** `/delmulti <keyword/name>`")

    keyword = message.text.split(None, 1)[1]
    status_msg = await message.reply_text(
        f"⏳ **Searching and deleting files matching:** `{keyword}`..."
    )

    try:
        # Regex search for files containing the keyword (case-insensitive)
        query = {"file_name": {"$regex": keyword, "$options": "i"}}
        result = await Media.collection.delete_many(query)

        if result.deleted_count > 0:
            await status_msg.edit_text(
                f"✅ **Successfully deleted `{result.deleted_count}` files matching:** `{keyword}`"
            )
        else:
            await status_msg.edit_text(f"⚠️ **No files found matching:** `{keyword}`")

    except Exception as e:
        logger.exception("delete_multiple_files failed")
        await status_msg.edit_text(f"❌ **Error while deleting files:**\n`{e}`")


# ============================================================
# ⏱ 3. Set File Auto-Delete Timer (/autodelete)
# ============================================================
@Client.on_message(filters.command("autodelete") & filters.user(info.ADMINS))
async def set_autodelete_timer(bot: Client, message: Message):
    """
    Sets the auto-delete time (in seconds) for files sent in PM.
    Usage: /autodelete 1800
    """
    if len(message.command) < 2:
        return await message.reply_text(
            f"⚙️ **Usage:** `/autodelete [seconds]`\n\n"
            f"⏱ **Current File Auto-Delete:** `{info.FILE_AUTO_DELETE}` seconds."
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


# ============================================================
# ⏱ 4. Set Button Auto-Delete Timer (/buttondel)
# ============================================================
@Client.on_message(filters.command("buttondel") & filters.user(info.ADMINS))
async def set_buttondel_timer(bot: Client, message: Message):
    """
    Sets the auto-delete time (in seconds) for button messages sent in groups.
    Usage: /buttondel 300
    """
    if len(message.command) < 2:
        return await message.reply_text(
            f"⚙️ **Usage:** `/buttondel [seconds]`\n\n"
            f"⏱ **Current Button Auto-Delete:** `{info.BUTTON_AUTO_DELETE}` seconds."
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
