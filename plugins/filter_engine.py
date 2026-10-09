import asyncio
import base64
import urllib.parse
from logging import ERROR, getLogger

import requests
from motor.motor_asyncio import AsyncIOMotorClient
from pyrogram import Client, filters
from pyrogram.types import Message

import info
from database.ia_filterdb import Media as _Media
from plugins.delete import get_del_setting, schedule_file_with_countdown

logger = getLogger(__name__)
logger.setLevel(ERROR)

# MongoDB VIP Connection
_vip_db = None
try:
    _DB_CLIENT = AsyncIOMotorClient(info.DATABASE_URI)
    _BOT_DB = _DB_CLIENT[info.DATABASE_NAME]
    _vip_db = _BOT_DB["fsub_vips"]
except Exception as e:
    logger.error(f"Failed to init VIP DB in filter_engine: {e}")


async def is_vip(user_id: int) -> bool:
    if _vip_db is not None:
        doc = await _vip_db.find_one({"user_id": user_id})
        return bool(doc)
    return False


# ============================================================
# 🔐 DMCA ANTI-BAN TOKEN ENCRYPTION / DECRYPTION
# ============================================================
def encode_file_token(file_id: str) -> str:
    raw_bytes = file_id.encode("utf-8")
    return base64.urlsafe_b64encode(raw_bytes).decode("utf-8").rstrip("=")


def decode_file_token(token: str) -> str:
    padding = 4 - (len(token) % 4)
    if padding != 4:
        token += "=" * padding
    return base64.urlsafe_b64decode(token.encode("utf-8")).decode("utf-8")


# ============================================================
# 💰 AUTO-MONETIZATION SHORTLINK ENGINE
# ============================================================
async def get_monetized_link(user_id: int, original_url: str) -> str:
    # VIPs bypass shortlinks entirely
    if await is_vip(user_id):
        return original_url

    shortener_api = getattr(info, "SHORTENER_API", "")
    shortener_url = getattr(info, "SHORTENER_URL", "")

    if not (shortener_api and shortener_url):
        return original_url

    try:
        api_endpoint = f"https://{shortener_url}/api?api={shortener_api}&url={urllib.parse.quote(original_url)}"
        res = await asyncio.to_thread(requests.get, api_endpoint, timeout=5)
        data = res.json()
        if data.get("status") == "success" or "shortenedUrl" in data:
            return data.get("shortenedUrl") or data.get("url")
    except Exception:
        pass
    return original_url


# ============================================================
# 🚀 DMCA SECURE DISPATCHER (?start=file_<token>)
# ============================================================
@Client.on_message(filters.command("start") & filters.private)
async def secure_dmca_dispatch(client: Client, message: Message):
    if len(message.command) > 1 and message.command[1].startswith("file_"):
        token = message.command[1].replace("file_", "")
        try:
            target_id = decode_file_token(token)
            doc = await _Media.collection.find_one({"_id": target_id})
            if not doc:
                return await message.reply_text(
                    "❌ **File not found or link has expired.**"
                )

            raw_file_id = doc.get("file_id")
            caption = (
                f"🎬 **File:** `{doc.get('file_name')}`\n\n⚡ *Delivered securely.*"
            )

            # Fresh cached dispatch avoids copyright/origin forward headers
            msg = await client.send_cached_media(
                chat_id=message.chat.id, file_id=raw_file_id, caption=caption
            )

            # Apply countdown auto-delete timer
            delay = await get_del_setting("FILE_AUTO_DELETE", 1800)
            await schedule_file_with_countdown(client, msg, delay)

        except Exception as e:
            logger.error(f"Secure Dispatch Error: {e}")
            await message.reply_text(
                "⚠️ **Error delivering file.** The link may be corrupted."
            )
