import re
from logging import ERROR, getLogger

from pyrogram import Client, StopPropagation, enums, filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

import info
from database.ia_filterdb import get_search_results
from database.users_chats_db import db as _db
from Script import script
from utils import get_size, temp

# Optional ban database check
try:
    from database.plugin_dbs import plugin_db as _plugin_db
except ImportError:
    _plugin_db = None

logger = getLogger(__name__)
logger.setLevel(ERROR)


def get_admin_list():
    raw_admins = getattr(info, "ADMINS", [])
    if isinstance(raw_admins, (str, int)):
        raw_admins = str(raw_admins).replace(",", " ").split()
    elif isinstance(raw_admins, (list, tuple, set)):
        raw_admins = list(raw_admins)
    else:
        raw_admins = []
    return [int(x) for x in raw_admins if str(x).strip().lstrip("-").isdigit()]


async def _fallback_pm_search(client: Client, message: Message, query: str):
    """Fallback direct database search if pm_filter.auto_filter is unavailable or fails."""
    files, _, total_results = await get_search_results(
        query.lower(), offset=0, filter=True
    )
    if not files:
        return await message.reply_text(
            f"❌ <b>No files found for:</b> <code>{query}</code>\n\n"
            f"Please check the spelling or request it in our group!",
            parse_mode=enums.ParseMode.HTML,
        )

    btn_rows = []
    for file in files[:10]:
        f_id = (
            file.get("file_id")
            if isinstance(file, dict)
            else getattr(file, "file_id", "")
        )
        f_name = (
            file.get("file_name", "File")
            if isinstance(file, dict)
            else getattr(file, "file_name", "File")
        )
        f_size = get_size(
            int(
                file.get("file_size", 0)
                if isinstance(file, dict)
                else getattr(file, "file_size", 0)
            )
        )
        if f_id:
            btn_rows.append(
                [
                    InlineKeyboardButton(
                        text=f"[{f_size}] {f_name}",
                        callback_data=f"file#{f_id}",
                    )
                ]
            )

    btn_rows.append([InlineKeyboardButton("🔐 Close", callback_data="close_data")])

    await message.reply_text(
        f"🔍 <b>Search Results for:</b> <code>{query}</code>\n"
        f"📁 <b>Total Found:</b> <code>{total_results}</code>\n\n"
        f"👇 <i>Click on a file button below to download:</i>",
        reply_markup=InlineKeyboardMarkup(btn_rows),
        parse_mode=enums.ParseMode.HTML,
    )


# ============================================================
# 🚨 CLEAN DEEP-LINK SEARCH INTERCEPTOR
# ============================================================
@Client.on_message(
    filters.command("start") & filters.private & filters.incoming, group=-99
)
async def intercept_direct_search(client: Client, message: Message):
    if len(message.command) < 2 or not message.command[1].startswith("search_"):
        return

    user = message.from_user
    uid = user.id if user else 0

    # 1. Maintenance Mode Check
    if getattr(info, "REPAIR_MODE", False) and uid not in get_admin_list():
        await message.reply_text(
            "🛠️ <b>Bot is currently under maintenance!</b>",
            parse_mode=enums.ParseMode.HTML,
        )
        raise StopPropagation

    # 2. Ban Check
    if uid and _plugin_db is not None and hasattr(_plugin_db, "is_banned"):
        try:
            if await _plugin_db.is_banned(uid):
                raise StopPropagation
        except StopPropagation:
            raise
        except Exception:
            pass

    # 3. Ensure New Users Clicking Channel Search Buttons Are Registered in DB
    if user:
        try:
            if not await _db.is_user_exist(uid):
                await _db.add_user(uid, user.first_name)
                log_channel = getattr(info, "LOG_CHANNEL", None)
                if log_channel and hasattr(script, "LOG_TEXT_P"):
                    try:
                        await client.send_message(
                            log_channel,
                            script.LOG_TEXT_P.format(uid, user.mention),
                        )
                    except Exception:
                        pass
        except Exception as e:
            logger.error(f"User registration in search interceptor failed: {e}")

    # 4. Extract & Clean the Search Query
    # Example: "search_Khalifa__The_Ruler_2026" -> "Khalifa The Ruler 2026"
    raw_query = message.command[1][len("search_") :]
    query = re.sub(r"[_+\-]+", " ", raw_query).strip()

    if not query:
        return

    # 5. Execute Search via pm_filter.auto_filter with Direct DB Fallback
    try:
        try:
            from plugins.pm_filter import auto_filter
        except ImportError:
            from pm_filter import auto_filter

        # Mutate message so auto_filter treats it as a plain text search query
        message.text = query
        message.command = None
        await auto_filter(client, message)
    except Exception as e:
        logger.error(f"auto_filter failed in search_interceptor, using fallback: {e}")
        try:
            await _fallback_pm_search(client, message, query)
        except Exception as fallback_err:
            logger.error(f"Fallback search also failed: {fallback_err}")
            await message.reply_text(
                f"🔍 <b>Search Query:</b> <code>{query}</code>\n\n"
                f"Tap the text above to copy it, then send it to me to search!",
                parse_mode=enums.ParseMode.HTML,
            )

    # 6. Stop default /start handler from firing after search results are sent
    raise StopPropagation
