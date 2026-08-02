import asyncio
import logging
import os
import time
from datetime import datetime

from bson.json_util import dumps, loads
from motor.motor_asyncio import AsyncIOMotorClient
from pyrogram import Client, filters
from pyrogram.types import Message

import info

logger = logging.getLogger(__name__)

# ============================================================
# 🗄️ Database Connection
# ============================================================
DB_CLIENT = AsyncIOMotorClient(info.DATABASE_URI)
BOT_DB = DB_CLIENT[info.DATABASE_NAME]

# ============================================================
# ⏱️ Scheduler State
# ============================================================
BACKUP_INTERVAL = 86400  # 24 hours in seconds
last_backup_time = None
next_backup_time = None
scheduler_running = False


# ============================================================
# 🔐 Custom Admin Filter (Fixes the "No Response" Bug)
# ============================================================
async def admin_check(_, __, message: Message):
    if not message.from_user:
        return False
    # Safely checks against both integers and strings
    return (
        message.from_user.id in info.ADMINS or str(message.from_user.id) in info.ADMINS
    )


admin_filter = filters.create(admin_check)


async def auto_backup_task(bot: Client):
    """Background task to automatically backup DB every 24 hours to the primary Admin."""
    global last_backup_time, next_backup_time, scheduler_running
    scheduler_running = True

    # Send automated backups to the first admin in the list
    target_admin_id = info.ADMINS[0] if getattr(info, "ADMINS", None) else None

    while True:
        last_backup_time = time.time()
        next_backup_time = last_backup_time + BACKUP_INTERVAL

        await asyncio.sleep(BACKUP_INTERVAL)

        if not BOT_DB or not target_admin_id:
            continue

        try:
            file_path = await generate_backup_file()
            caption = f"🔄 **Automated Daily Database Backup**\n\n📅 Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            await bot.send_document(
                chat_id=target_admin_id, document=file_path, caption=caption
            )
            os.remove(file_path)
        except Exception as e:
            logger.error(f"Auto-backup failed: {e}")


# ============================================================
# 🛠️ Helper Functions
# ============================================================
async def generate_backup_file() -> str:
    """Fetches all collections and dumps them to a local JSON file."""
    collections = await BOT_DB.list_collection_names()
    backup_data = {}

    for coll_name in collections:
        docs = await BOT_DB[coll_name].find({}).to_list(length=None)
        backup_data[coll_name] = docs

    file_name = f"DB_Backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(file_name, "w", encoding="utf-8") as f:
        f.write(dumps(backup_data, indent=4))

    return file_name


# ============================================================
# 📤 Create Database Backup
# ============================================================
@Client.on_message(filters.command("dbbackup") & admin_filter)
async def db_backup_cmd(bot: Client, message: Message):
    status_msg = await message.reply_text(
        "⏳ **Generating database backup...**\nThis might take a few moments."
    )

    try:
        file_path = await generate_backup_file()
        caption = f"✅ **Database Backup Complete!**\n\n📅 Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n👤 **Requested By:** {message.from_user.mention}"

        await message.reply_document(document=file_path, caption=caption)
        os.remove(file_path)
        await status_msg.delete()

    except Exception as e:
        await status_msg.edit_text(f"⚠️ **Backup Failed!**\n\nError: `{e}`")


# ============================================================
# 📥 Restore Database
# ============================================================
@Client.on_message(filters.command("dbrestore") & admin_filter)
async def db_restore_cmd(bot: Client, message: Message):
    if not message.reply_to_message or not message.reply_to_message.document:
        return await message.reply_text(
            "⚙️ **Usage:**\nReply to a previously generated backup `.json` file with `/dbrestore`.\n\n"
            "⚠️ **WARNING:** This will overwrite existing data!"
        )

    doc = message.reply_to_message.document
    if not doc.file_name.endswith(".json"):
        return await message.reply_text(
            "❌ **Invalid File Format!** Please reply to a valid `.json` backup file."
        )

    status_msg = await message.reply_text("⏳ **Downloading backup file...**")

    try:
        file_path = await message.reply_to_message.download()

        await status_msg.edit_text("⏳ **Restoring database...**")

        with open(file_path, "r", encoding="utf-8") as f:
            backup_data = loads(f.read())

        restored_colls = 0
        restored_docs = 0

        for coll_name, docs in backup_data.items():
            if docs:
                # Clear existing collection and insert the backup data
                await BOT_DB[coll_name].delete_many({})
                await BOT_DB[coll_name].insert_many(docs)
                restored_colls += 1
                restored_docs += len(docs)

        os.remove(file_path)
        await status_msg.edit_text(
            f"✅ **Database Restored Successfully!**\n\n"
            f"📁 **Collections Restored:** `{restored_colls}`\n"
            f"📄 **Documents Restored:** `{restored_docs}`"
        )

    except Exception as e:
        await status_msg.edit_text(f"⚠️ **Restore Failed!**\n\nError: `{e}`")
        if "file_path" in locals() and os.path.exists(file_path):
            os.remove(file_path)


# ============================================================
# 📊 Database Statistics
# ============================================================
@Client.on_message(filters.command("dbstats") & admin_filter)
async def db_stats_cmd(bot: Client, message: Message):
    try:
        stats = await BOT_DB.command("dbstats")
        colls = await BOT_DB.list_collection_names()

        total_size_mb = stats.get("dataSize", 0) / (1024 * 1024)

        text = "📊 **Database Statistics**\n\n"
        text += f"🗄️ **Database:** `{info.DATABASE_NAME}`\n"
        text += f"📦 **Collections Count:** `{stats.get('collections', 0)}`\n"
        text += f"📄 **Total Documents:** `{stats.get('objects', 0)}`\n"
        text += f"💾 **Data Size:** `{total_size_mb:.2f} MB`\n\n"

        text += "📁 **Collection Breakdown:**\n"
        for coll in colls:
            count = await BOT_DB[coll].count_documents({})
            text += f"  - `{coll}`: {count} docs\n"

        await message.reply_text(text)

    except Exception as e:
        await message.reply_text(f"⚠️ **Failed to fetch stats:**\n`{e}`")


# ============================================================
# ⏰ Schedule Status
# ============================================================
@Client.on_message(filters.command("dbschedule") & admin_filter)
async def db_schedule_cmd(bot: Client, message: Message):
    if not scheduler_running:
        # Start the background task if it hasn't been started yet
        asyncio.create_task(auto_backup_task(bot))
        return await message.reply_text(
            "✅ **Auto-backup scheduler initiated!**\nThe first automated backup will run in 24 hours."
        )

    if next_backup_time:
        time_left = next_backup_time - time.time()
        hours, remainder = divmod(int(time_left), 3600)
        minutes, seconds = divmod(remainder, 60)

        time_str = f"{hours}h {minutes}m {seconds}s"
        await message.reply_text(
            f"⏰ **Scheduled Backup Status**\n\n"
            f"🟢 **Status:** `Active`\n"
            f"⏳ **Next Backup In:** `{time_str}`"
        )
    else:
        await message.reply_text("⏰ Scheduler is active but time is calculating...")
