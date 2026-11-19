import asyncio
import html
import logging
import re
from typing import List, Optional, Tuple

from motor.motor_asyncio import AsyncIOMotorClient
from pyrogram import enums

from info import DATABASE_NAME, DATABASE_URI

logger = logging.getLogger(__name__)

_client = AsyncIOMotorClient(
    DATABASE_URI,
    serverSelectionTimeoutMS=5000,
    connectTimeoutMS=4000,
    socketTimeoutMS=10000,
)
mydb = _client[DATABASE_NAME]


async def add_filter(grp_id, text, reply_text, btn, file, alert="[]"):
    keyword = str(text).lower().strip()
    try:
        await asyncio.wait_for(
            mydb[str(grp_id)].update_one(
                {"text": keyword},
                {
                    "$set": {
                        "text": keyword,
                        "reply": str(reply_text or ""),
                        "btn": str(btn or "[]"),
                        "file": str(file or "None"),
                        "alert": str(alert or "[]"),
                    }
                },
                upsert=True,
            ),
            timeout=3.0,
        )
    except Exception as e:
        logger.error(f"add_filter error ({grp_id}/{keyword}): {e}")


async def find_filter(
    group_id, name
) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    keyword = str(name).lower().strip()
    try:
        doc = await asyncio.wait_for(
            mydb[str(group_id)].find_one({"text": keyword}), timeout=2.5
        )
        if not doc:
            doc = await asyncio.wait_for(
                mydb[str(group_id)].find_one(
                    {"text": {"$regex": f"^{re.escape(keyword)}$", "$options": "i"}}
                ),
                timeout=2.5,
            )
        if doc:
            return doc.get("reply"), doc.get("btn"), doc.get("alert"), doc.get("file")
    except Exception as e:
        logger.error(f"find_filter error ({group_id}/{keyword}): {e}")
    return None, None, None, None


async def get_filters(group_id) -> List[str]:
    try:
        docs = await asyncio.wait_for(
            mydb[str(group_id)].find({}, {"text": 1}).to_list(length=500), timeout=3.0
        )
        return [str(d["text"]) for d in docs if d.get("text")]
    except Exception as e:
        logger.error(f"get_filters error for {group_id}: {e}")
        return []


async def delete_filter(message, text, group_id) -> bool:
    keyword = str(text).lower().strip()
    try:
        res = await asyncio.wait_for(
            mydb[str(group_id)].delete_many(
                {
                    "$or": [
                        {"text": keyword},
                        {"text": {"$regex": f"^{re.escape(keyword)}$", "$options": "i"}},
                    ]
                }
            ),
            timeout=3.0,
        )
        return res.deleted_count > 0
    except Exception as e:
        logger.error(f"delete_filter error ({group_id}/{keyword}): {e}")
        return False


async def del_all(message, group_id, title):
    safe_title = html.escape(str(title or group_id))
    try:
        col_names = await asyncio.wait_for(mydb.list_collection_names(), timeout=4.0)
        if str(group_id) not in col_names:
            if message:
                await message.edit_text(
                    f"Nothing to remove in <b>{safe_title}</b>!",
                    parse_mode=enums.ParseMode.HTML,
                )
            return
        await asyncio.wait_for(mydb[str(group_id)].drop(), timeout=5.0)
        if message:
            await message.edit_text(
                f"All filters from <b>{safe_title}</b> have been removed.",
                parse_mode=enums.ParseMode.HTML,
            )
    except Exception:
        if message:
            try:
                await message.edit_text(
                    "Couldn't remove all filters from group!",
                    parse_mode=enums.ParseMode.HTML,
                )
            except Exception:
                pass
