import asyncio
import io
import re
from datetime import datetime
from logging import ERROR, getLogger

from motor.motor_asyncio import AsyncIOMotorClient
from pyrogram import Client, filters
from pyrogram.types import Message

import info

logger = getLogger(__name__)
logger.setLevel(ERROR)

# ============================================================
# ⚙️ MONGODB SETUP FOR ANALYTICS & OPTIMIZATION
# ============================================================
db = None
search_stats_col = None
users_col = None
chats_col = None
media_col = None

try:
    _DB_CLIENT = AsyncIOMotorClient(info.DATABASE_URI)
    db = _DB_CLIENT[info.DATABASE_NAME]
    search_stats_col = db["search_analytics"]
    users_col = db["users"]
    chats_col = db["chats"]

    collection_name = getattr(info, "COLLECTION_NAME", "Anime_Files")
    media_col = db[collection_name]
except Exception as e:
    logger.error(f"Failed to init Analytics DB: {e}")


# ============================================================
# ⚡ FOOLPROOF ADMIN PARSER
# ============================================================
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


admin_filter = filters.create(
    lambda _, __, msg: bool(msg.from_user and msg.from_user.id in get_admin_list())
)


# ============================================================
# 📊 FEATURE 1: SILENT AUDIENCE TRACKER (Zero Interference)
# ============================================================
@Client.on_message(
    filters.text
    & filters.incoming
    & ~filters.bot
    & ~filters.command(list("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")),
    group=10,
)
async def silent_search_tracker(client: Client, message: Message):
    # ⚡ FIXED: Must compare explicitly to None for MongoDB objects
    if search_stats_col is None:
        return

    query = message.text.strip().lower()

    if len(query) < 2 or len(query) > 60:
        return
    if re.match(r"https?://\S+|t\.me/\S+|@\w+", query):
        return

    clean_query = re.sub(
        r"(?i)\b(1080p|720p|480p|2160p|4k|mkv|mp4|avi|hdrip|web-?dl|webrip|bluray|brrip|dvdrip|x264|x265|hevc|dual audio|hindi|kannada|telugu|tamil|malayalam|english|subtitles|subs|episodes|season\s*\d+|s\d+e\d+|complete)\b",
        "",
        query,
    )
    clean_query = re.sub(r"[\-\|:;_\[\]\(\)\{\}]", " ", clean_query)
    clean_query = re.sub(r"\s+", " ", clean_query).strip()

    if len(clean_query) < 2:
        return

    today = datetime.now().strftime("%Y-%m-%d")

    asyncio.create_task(
        search_stats_col.update_one(
            {"date": today, "query": clean_query}, {"$inc": {"count": 1}}, upsert=True
        )
    )


# ============================================================
# 📊 FEATURE 2: LIVE ANALYTICS DASHBOARD (/analize)
# ============================================================
@Client.on_message(filters.command("analize") & admin_filter)
async def live_dashboard_command(client: Client, message: Message):
    msg = await message.reply_text(
        "⏳ **Fetching Live Analytics & Processing Data...**"
    )

    try:
        today = datetime.now().strftime("%Y-%m-%d")

        # Fetch Top 15 Searches of the day
        top_searches_cursor = (
            search_stats_col.find({"date": today}).sort("count", -1).limit(15)
        )
        top_searches = await top_searches_cursor.to_list(length=15)

        # Calculate Total Searches Today
        pipeline = [
            {"$match": {"date": today}},
            {"$group": {"_id": None, "total": {"$sum": "$count"}}},
        ]
        total_searches_agg = await search_stats_col.aggregate(pipeline).to_list(
            length=1
        )
        total_searches_today = (
            total_searches_agg[0]["total"] if total_searches_agg else 0
        )

        # ⚡ FIXED: Collection objects evaluated against None correctly
        total_users = (
            await users_col.count_documents({}) if users_col is not None else 0
        )
        total_chats = (
            await chats_col.count_documents({}) if chats_col is not None else 0
        )
        total_files = (
            await media_col.count_documents({}) if media_col is not None else 0
        )

        dash_text = "📊 **ENTERPRISE ANALYTICS DASHBOARD** 📊\n"
        dash_text += "━━━━━━━━━━━━━━━━━━━━\n\n"

        dash_text += "📈 **NETWORK STATS:**\n"
        dash_text += f"👥 **Total Users:** `{total_users:,}`\n"
        dash_text += f"📢 **Total Groups:** `{total_chats:,}`\n"
        dash_text += f"📂 **Total Files Indexed:** `{total_files:,}`\n\n"

        dash_text += "🔥 **LIVE AUDIENCE DEMAND (Today):**\n"
        dash_text += f"🔍 **Total Queries Processed:** `{total_searches_today:,}`\n\n"

        dash_text += "🏆 **TOP 15 TRENDING SEARCHES:**\n"
        if top_searches:
            for idx, s in enumerate(top_searches, 1):
                dash_text += (
                    f"  **{idx}.** `{s['query'].title()}` ➔ _{s['count']} requests_\n"
                )
        else:
            dash_text += "  _No searches tracked yet today._\n"

        dash_text += (
            "\n💡 _Tip: Use /exportstats to download the complete search history._\n"
        )
        dash_text += "━━━━━━━━━━━━━━━━━━━━\n"

        await msg.edit_text(dash_text)

    except Exception as e:
        await msg.edit_text(f"❌ **Dashboard Generation Failed:**\n`{str(e)}`")


# ============================================================
# 📄 FEATURE 3: COMPLETE RESULTS EXPORT (/exportstats)
# ============================================================
@Client.on_message(filters.command("exportstats") & admin_filter)
async def export_stats_command(client: Client, message: Message):
    msg = await message.reply_text(
        "⏳ **Generating Complete Search History Report...**"
    )
    try:
        if search_stats_col is None:
            return await msg.edit_text("❌ Database not connected.")

        cursor = search_stats_col.find({}).sort([("date", -1), ("count", -1)])
        all_searches = await cursor.to_list(length=None)

        if not all_searches:
            return await msg.edit_text("⚠️ No search data available to export.")

        report_lines = ["📊 COMPLETE SEARCH ANALYTICS EXPORT 📊", "=" * 40, ""]

        for s in all_searches:
            report_lines.append(
                f"Date: {s.get('date')} | Count: {s.get('count')} | Query: {s.get('query')}"
            )

        file_data = "\n".join(report_lines)
        file_io = io.BytesIO(file_data.encode("utf-8"))
        file_io.name = f"Search_Analytics_{datetime.now().strftime('%Y%m%d')}.txt"

        await message.reply_document(
            document=file_io,
            caption="✅ **Complete Search Statistics Exported Successfully!**",
        )
        await msg.delete()
    except Exception as e:
        await msg.edit_text(f"❌ **Export Failed:**\n`{str(e)}`")


# ============================================================
# 🚀 FEATURE 4: MONGODB CORE OPTIMIZER (/optimize_db)
# ============================================================
@Client.on_message(filters.command("optimize_db") & admin_filter)
async def optimize_mongodb(client: Client, message: Message):
    msg = await message.reply_text(
        "🚀 **Initiating Database Core Optimization...**\n_Please wait, this might take a few seconds._"
    )

    try:
        if media_col is None:
            return await msg.edit_text(
                "❌ **Error:** Media collection not found. Check `info.COLLECTION_NAME`."
            )

        await media_col.create_index([("file_name", "text")])
        await media_col.create_index([("file_id", 1)])
        await media_col.create_index(
            [("file_size", -1)]
        )  # ⚡ UPGRADE: Speeds up file sorting

        if search_stats_col is not None:
            await search_stats_col.create_index(
                [("date", 1), ("query", 1)], unique=True
            )

        success_text = (
            "✅ **MongoDB Core Optimization Complete!**\n\n"
            "**Upgrades Applied:**\n"
            "➤ `$text` search index injected into the database.\n"
            "➤ Fast-Sort index added for `file_size`.\n"
            "➤ Analytics background indexes synced.\n\n"
            "🔥 _Your bot is now operating at Peak Enterprise Level!_"
        )
        await msg.edit_text(success_text)

    except Exception as e:
        logger.error(f"Optimization Failed: {e}")
        await msg.edit_text(f"❌ **Optimization Failed:**\n`{str(e)}`")
