import asyncio
import logging
import time
from typing import Optional, Union

from motor.motor_asyncio import AsyncIOMotorClient

from info import DATABASE_NAME, DATABASE_URI

logger = logging.getLogger(__name__)


class PluginDatabase:
    def __init__(self):
        self.client = AsyncIOMotorClient(
            DATABASE_URI,
            serverSelectionTimeoutMS=5000,
            connectTimeoutMS=5000,
            socketTimeoutMS=15000,
        )
        self.db = self.client[DATABASE_NAME]
        self.promo_col = self.db["promotions"]
        self.ban_col = self.db["banned_users"]
        self.fsub_col = self.db["fsub_users"]
        self.react_col = self.db["reaction_settings"]
        self.del_col = self.db["deletion_settings"]

    # ============================================================
    # 📢 PROMOTIONS HELPERS
    # ============================================================
    async def add_promo(self, text: str, url: str):
        clean_url = str(url).strip()
        try:
            await asyncio.wait_for(
                self.promo_col.update_one(
                    {"url": clean_url},
                    {"$set": {"text": str(text).strip(), "url": clean_url}},
                    upsert=True,
                ),
                timeout=3.0,
            )
        except Exception as e:
            logger.error(f"add_promo error: {e}")

    async def del_promo(self, url: str) -> bool:
        target = str(url).strip()
        try:
            res = await asyncio.wait_for(
                self.promo_col.delete_many(
                    {"$or": [{"url": target}, {"text": target}]}
                ),
                timeout=3.0,
            )
            return res.deleted_count > 0
        except Exception:
            return False

    async def get_all_promos(self) -> list:
        try:
            return await asyncio.wait_for(
                self.promo_col.find({}).to_list(length=100), timeout=3.0
            )
        except Exception:
            return []

    async def get_promos(self) -> list:
        return await self.get_all_promos()

    # ============================================================
    # 🚫 BAN MANAGEMENT HELPERS
    # ============================================================
    async def ban_user(self, user_id: Union[int, str]):
        uid = int(user_id)
        try:
            await asyncio.wait_for(
                self.ban_col.update_one(
                    {"_id": uid},
                    {"$set": {"_id": uid, "banned_at": int(time.time())}},
                    upsert=True,
                ),
                timeout=3.0,
            )
        except Exception as e:
            logger.error(f"ban_user error ({uid}): {e}")

    async def unban_user(self, user_id: Union[int, str]):
        try:
            await asyncio.wait_for(
                self.ban_col.delete_one({"_id": int(user_id)}), timeout=3.0
            )
        except Exception:
            pass

    async def is_banned(self, user_id: Union[int, str]) -> bool:
        try:
            return bool(
                await asyncio.wait_for(
                    self.ban_col.find_one({"_id": int(user_id)}, {"_id": 1}),
                    timeout=2.5,
                )
            )
        except Exception:
            return False

    async def get_ban_count(self) -> int:
        try:
            return int(
                await asyncio.wait_for(self.ban_col.count_documents({}), timeout=3.0)
            )
        except Exception:
            return 0

    # ============================================================
    # 📱 FORCE SUBSCRIBE LEGACY USER HELPERS
    # ============================================================
    async def clear_fsub_users(self):
        try:
            await asyncio.wait_for(self.fsub_col.delete_many({}), timeout=4.0)
        except Exception:
            pass

    # ============================================================
    # ❤️ AUTO-REACTION STATUS HELPERS
    # ============================================================
    async def get_reaction_status(self) -> bool:
        try:
            cfg = await asyncio.wait_for(
                self.react_col.find_one({"_id": "config"}), timeout=2.5
            )
            if cfg and "enabled" in cfg:
                return bool(cfg["enabled"])
            doc = await asyncio.wait_for(
                self.react_col.find_one({"_id": "global_status"}), timeout=2.5
            )
            if doc and "is_enabled" in doc:
                return bool(doc["is_enabled"])
        except Exception:
            pass
        return True

    async def set_reaction_status(self, status: bool):
        val = bool(status)
        try:
            await asyncio.wait_for(
                self.react_col.update_one(
                    {"_id": "config"},
                    {"$set": {"enabled": val, "updated_at": time.time()}},
                    upsert=True,
                ),
                timeout=3.0,
            )
        except Exception:
            pass

    # ============================================================
    # ⏳ AUTO-DELETE TIMER HELPERS
    # ============================================================
    async def set_buttondel(self, seconds: int):
        try:
            await asyncio.wait_for(
                self.del_col.update_one(
                    {"_id": "timers"},
                    {"$set": {"BUTTON_AUTO_DELETE": int(seconds)}},
                    upsert=True,
                ),
                timeout=3.0,
            )
        except Exception:
            pass

    async def get_buttondel(self) -> Optional[int]:
        try:
            doc = await asyncio.wait_for(
                self.del_col.find_one({"_id": "timers"}), timeout=2.5
            )
            if doc and doc.get("BUTTON_AUTO_DELETE") is not None:
                return int(doc["BUTTON_AUTO_DELETE"])
        except Exception:
            pass
        return None

    async def set_autodelete(self, seconds: int):
        try:
            await asyncio.wait_for(
                self.del_col.update_one(
                    {"_id": "timers"},
                    {"$set": {"FILE_AUTO_DELETE": int(seconds)}},
                    upsert=True,
                ),
                timeout=3.0,
            )
        except Exception:
            pass

    async def get_autodelete(self) -> Optional[int]:
        try:
            doc = await asyncio.wait_for(
                self.del_col.find_one({"_id": "timers"}), timeout=2.5
            )
            if doc and doc.get("FILE_AUTO_DELETE") is not None:
                return int(doc["FILE_AUTO_DELETE"])
        except Exception:
            pass
        return None


plugin_db = PluginDatabase()
