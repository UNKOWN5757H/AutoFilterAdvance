import logging
from pyrogram import Client, emoji
from pyrogram.errors.exceptions.bad_request_400 import QueryIdInvalid
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, InlineQuery, InlineQueryResultCachedDocument
from database.ia_filterdb import get_search_results
from info import ADMINS, AUTH_CHANNEL, CACHE_TIME, CUSTOM_FILE_CAPTION, REQ_CHANNEL
from utils import get_size, is_subscribed, temp

logger = logging.getLogger(__name__)

async def inline_users(query: InlineQuery):
    return bool(query.from_user and query.from_user.id not in temp.BANNED_USERS)

@Client.on_inline_query()
async def answer(bot, query: InlineQuery):
    if not await inline_users(query):
        return await query.answer(results=[], cache_time=0, switch_pm_text="Banned User", switch_pm_parameter="hehe")
    if (AUTH_CHANNEL or REQ_CHANNEL) and not await is_subscribed(bot, query):
        return await query.answer(results=[], cache_time=0, switch_pm_text="Join channel to use", switch_pm_parameter="subscribe")

    results = []
    string, file_type = query.query.split("|", maxsplit=1) if "|" in query.query else (query.query.strip(), None)
    string = string.strip(); file_type = file_type.strip().lower() if file_type else None
    
    offset = int(query.offset or 0)
    files, next_offset, total = await get_search_results(string, file_type=file_type, max_results=10, offset=offset)

    for file in files:
        f_caption = CUSTOM_FILE_CAPTION.format(file_name=file.file_name or "", file_size=get_size(file.file_size) or "", file_caption=file.caption or "") if CUSTOM_FILE_CAPTION else file.file_name
        results.append(
            InlineQueryResultCachedDocument(
                title=file.file_name, document_file_id=file.file_id, caption=f_caption,
                description=f"Size: {get_size(file.file_size)}\nType: {file.file_type}",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("♻️ 𝗦𝗲𝗮𝗿𝗰𝗵 𝗔𝗴𝗮𝗶𝗻 ♻️", switch_inline_query_current_chat=query.query)]])
            )
        )

    try:
        if results:
            await query.answer(results=results, is_personal=True, cache_time=CACHE_TIME, switch_pm_text=f"{emoji.FILE_FOLDER} Results - {total}", switch_pm_parameter="start", next_offset=str(next_offset))
        else:
            await query.answer(results=[], is_personal=True, cache_time=CACHE_TIME, switch_pm_text=f"{emoji.CROSS_MARK} No results for \"{string}\"", switch_pm_parameter="okay")
    except QueryIdInvalid: pass
    except Exception as e: logger.error(f"Inline Error: {e}")
