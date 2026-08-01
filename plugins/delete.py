import re
from pyrogram import Client, filters
from pyrogram.types import Message
import info
from database.ia_filterdb import Media, unpack_new_file_id

if not hasattr(info, "FILE_AUTO_DELETE"): info.FILE_AUTO_DELETE = 1800
if not hasattr(info, "BUTTON_AUTO_DELETE"): info.BUTTON_AUTO_DELETE = 1800

@Client.on_message(filters.command("delete") & filters.user(info.ADMINS))
async def delete_single_file(bot: Client, message: Message):
    if len(message.command) == 2:
        res = await Media.collection.delete_one({"_id": message.command[1].strip()})
        return await message.reply_text("✅ **File deleted.**" if res.deleted_count else "⚠️ **File not found.**")

    reply = message.reply_to_message
    if not (reply and reply.media): return await message.reply_text("⚙️ **Usage:** `/delete <file_id>` or reply to a file.")
    
    media = getattr(reply, reply.media.value, None)
    if not media: return await message.reply_text("❌ **Unsupported format.**")

    file_id, _ = unpack_new_file_id(media.file_id)
    res = await Media.collection.delete_one({"_id": file_id})
    if res.deleted_count: return await message.reply_text("✅ **File deleted.**")

    # Fallback to name match
    file_name = re.sub(r"(_|\-|\.|\+)", " ", str(getattr(media, "file_name", "")))
    res = await Media.collection.delete_many({"file_name": file_name, "file_size": getattr(media, "file_size", 0)})
    await message.reply_text(f"✅ **Deleted {res.deleted_count} duplicate files.**" if res.deleted_count else "⚠️ **File not found.**")

@Client.on_message(filters.command("delmulti") & filters.user(info.ADMINS))
async def delete_multiple_files(bot: Client, message: Message):
    if len(message.command) < 2: return await message.reply_text("⚙️ **Usage:** `/delmulti <keyword>`")
    keyword = message.text.split(None, 1)[1]
    res = await Media.collection.delete_many({"file_name": {"$regex": keyword, "$options": "i"}})
    await message.reply_text(f"✅ **Deleted `{res.deleted_count}` files matching:** `{keyword}`" if res.deleted_count else f"⚠️ **No files found matching:** `{keyword}`")

@Client.on_message(filters.command("autodelete") & filters.user(info.ADMINS))
async def set_autodelete_timer(bot: Client, message: Message):
    if len(message.command) < 2: return await message.reply_text(f"⏱ **Current File Auto-Delete:** `{info.FILE_AUTO_DELETE}`s")
    try:
        info.FILE_AUTO_DELETE = int(message.command[1])
        await message.reply_text(f"✅ **File Auto-Delete set to:** `{info.FILE_AUTO_DELETE}`s")
    except ValueError:
        await message.reply_text("❌ **Invalid duration!**")

@Client.on_message(filters.command("buttondel") & filters.user(info.ADMINS))
async def set_buttondel_timer(bot: Client, message: Message):
    if len(message.command) < 2: return await message.reply_text(f"⏱ **Current Button Auto-Delete:** `{info.BUTTON_AUTO_DELETE}`s")
    try:
        info.BUTTON_AUTO_DELETE = int(message.command[1])
        await message.reply_text(f"✅ **Button Auto-Delete set to:** `{info.BUTTON_AUTO_DELETE}`s")
    except ValueError:
        await message.reply_text("❌ **Invalid duration!**")
