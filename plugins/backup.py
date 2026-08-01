import asyncio
import logging
import os
import time
from datetime import datetime
from pyrogram import Client, filters
from pyrogram.types import Message
import info

logger = logging.getLogger(__name__)

try:
    from bson.json_util import dumps, loads
    from motor.motor_asyncio import AsyncIOMotorClient
    db_client = AsyncIOMotorClient(info.DATABASE_URI) if getattr(info, "DATABASE_URI", None) else None
    bot_db = db_client[info.DATABASE_NAME] if db_client else None
except ImportError:
    bot_db = None

BACKUP_INTERVAL = 86400
next_backup_time, scheduler_running = None, False

async def generate_backup_file() -> str:
    collections = await bot_db.list_collection_names()
    backup_data = {coll: await bot_db[coll].find({}).to_list(length=None) for coll in collections}
    file_name = f"DB_Backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(file_name, "w", encoding="utf-8") as f: f.write(dumps(backup_data, indent=4))
    return file_name

async def auto_backup_task(bot: Client):
    global next_backup_time, scheduler_running
    scheduler_running = True
    target_admin_id = info.ADMINS[0] if getattr(info, "ADMINS", None) else None
    
    while True:
        next_backup_time = time.time() + BACKUP_INTERVAL
        await asyncio.sleep(BACKUP_INTERVAL)
        if not bot_db or not target_admin_id: continue
        try:
            file_path = await generate_backup_file()
            await bot.send_document(chat_id=target_admin_id, document=file_path, caption=f"🔄 **Automated Daily Backup**\n📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            os.remove(file_path)
        except Exception as e: logger.error(f"Auto-backup failed: {e}")

@Client.on_message(filters.command("dbbackup") & filters.user(info.ADMINS))
async def db_backup_cmd(bot: Client, message: Message):
    if not bot_db: return await message.reply_text("❌ **MongoDB missing.**")
    status_msg = await message.reply_text("⏳ **Generating backup...**")
    try:
        file_path = await generate_backup_file()
        await message.reply_document(document=file_path, caption=f"✅ **Database Backup Complete!**\n📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        os.remove(file_path)
        await status_msg.delete()
    except Exception as e:
        await status_msg.edit_text(f"⚠️ **Backup Failed!**\n`{e}`")

@Client.on_message(filters.command("dbrestore") & filters.user(info.ADMINS))
async def db_restore_cmd(bot: Client, message: Message):
    if not bot_db: return await message.reply_text("❌ **MongoDB missing.**")
    if not message.reply_to_message or not message.reply_to_message.document or not message.reply_to_message.document.file_name.endswith(".json"):
        return await message.reply_text("⚙️ **Usage:** Reply to a `.json` backup file.")
    
    status_msg = await message.reply_text("⏳ **Restoring database...**")
    try:
        file_path = await message.reply_to_message.download()
        with open(file_path, "r", encoding="utf-8") as f: backup_data = loads(f.read())
        
        colls, docs = 0, 0
        for coll_name, doc_data in backup_data.items():
            if doc_data:
                await bot_db[coll_name].delete_many({})
                await bot_db[coll_name].insert_many(doc_data)
                colls += 1; docs += len(doc_data)
                
        os.remove(file_path)
        await status_msg.edit_text(f"✅ **Restored!**\n📁 Collections: `{colls}`\n📄 Docs: `{docs}`")
    except Exception as e:
        await status_msg.edit_text(f"⚠️ **Restore Failed!**\n`{e}`")

@Client.on_message(filters.command("dbstats") & filters.user(info.ADMINS))
async def db_stats_cmd(bot: Client, message: Message):
    if not bot_db: return await message.reply_text("❌ **MongoDB missing.**")
    try:
        stats = await bot_db.command("dbstats")
        text = f"📊 **DB Statistics**\n📦 Collections: `{stats.get('collections', 0)}`\n📄 Docs: `{stats.get('objects', 0)}`\n💾 Size: `{stats.get('dataSize', 0) / (1024 * 1024):.2f} MB`\n\n📁 Breakdown:\n"
        for coll in await bot_db.list_collection_names():
            text += f" - `{coll}`: {await bot_db[coll].count_documents({})} docs\n"
        await message.reply_text(text)
    except Exception as e:
        await message.reply_text(f"⚠️ **Error:**\n`{e}`")

@Client.on_message(filters.command("dbschedule") & filters.user(info.ADMINS))
async def db_schedule_cmd(bot: Client, message: Message):
    if not bot_db: return await message.reply_text("❌ **MongoDB missing.**")
    if not scheduler_running:
        asyncio.create_task(auto_backup_task(bot))
        return await message.reply_text("✅ **Scheduler started!** Backup in 24 hours.")
    
    if next_backup_time:
        h, rem = divmod(int(next_backup_time - time.time()), 3600)
        m, s = divmod(rem, 60)
        await message.reply_text(f"⏰ **Scheduled Backup**\n🟢 Active\n⏳ Next In: `{h}h {m}m {s}s`")
    else:
        await message.reply_text("⏰ Scheduler active, calculating time...")
