import asyncio
import logging
from typing import Any, Dict, List, Union

import motor.motor_asyncio

import info
from info import (
    DATABASE_NAME,
    DATABASE_URI,
    IMDB,
    IMDB_TEMPLATE,
    MELCOW_NEW_USERS,
    P_TTI_SHOW_OFF,
    PROTECT_CONTENT,
    SINGLE_BUTTON,
    SPELL_CHECK_REPLY,
)

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, uri: str, database_name: str):
        self._client = motor.motor_asyncio.AsyncIOMotorClient(
            uri,
            serverSelectionTimeoutMS=5000,
            connectTimeoutMS=5000,
            socketTimeoutMS=15000,
        )
        self.db = self._client[database_name]
        self.col = self.db.users
        self.grp = self.db.groups
        self.bot_settings = self.db.bot_settings

    # ============================================================
    # 👤 USERS MANAGEMENT
    # ============================================================
    async def add_user(self, id: Union[int, str], name: str = "User"):
        uid = int(id)
        try:
            await asyncio.wait_for(
                self.col.update_one(
                    {"id": uid},
                    {
                        "$set": {"name": str(name or "User")},
                        "$setOnInsert": {
                            "id": uid,
                            "ban_status": {"is_banned": False, "ban_reason": ""},
                        },
                    },
                    upsert=True,
                ),
                timeout=4.0,
            )
        except Exception as e:
            logger.error(f"add_user error ({uid}): {e}")

    async def is_user_exist(self, id: Union[int, str]) -> bool:
        try:
            return bool(
                await asyncio.wait_for(
                    self.col.find_one({"id": int(id)}, {"_id": 1}), timeout=3.0
                )
            )
        except Exception:
            return False

    async def total_users_count(self) -> int:
        try:
            return int(
                await asyncio.wait_for(self.col.count_documents({}), timeout=5.0)
            )
        except Exception:
            return 0

    async def get_all_users(self) -> List[Dict[str, Any]]:
        try:
            return await self.col.find({}).to_list(length=None)
        except Exception as e:
            logger.error(f"get_all_users error: {e}")
            return []

    async def delete_user(self, user_id: Union[int, str]):
        uid = int(user_id)
        try:
            await asyncio.wait_for(
                self.col.delete_many({"$or": [{"id": uid}, {"user_id": uid}]}),
                timeout=4.0,
            )
        except Exception as e:
            logger.error(f"delete_user error ({uid}): {e}")

    async def ban_user(self, user_id: Union[int, str], ban_reason: str = "No Reason"):
        uid = int(user_id)
        try:
            await asyncio.wait_for(
                self.col.update_one(
                    {"id": uid},
                    {
                        "$set": {
                            "ban_status": {
                                "is_banned": True,
                                "ban_reason": str(ban_reason),
                            }
                        }
                    },
                    upsert=True,
                ),
                timeout=4.0,
            )
        except Exception as e:
            logger.error(f"ban_user error ({uid}): {e}")

    async def remove_ban(self, id: Union[int, str]):
        uid = int(id)
        try:
            await asyncio.wait_for(
                self.col.update_one(
                    {"id": uid},
                    {"$set": {"ban_status": {"is_banned": False, "ban_reason": ""}}},
                ),
                timeout=4.0,
            )
        except Exception as e:
            logger.error(f"remove_ban error ({uid}): {e}")

    async def get_ban_status(self, id: Union[int, str]) -> Dict[str, Any]:
        default = {"is_banned": False, "ban_reason": ""}
        try:
            user = await asyncio.wait_for(
                self.col.find_one({"id": int(id)}, {"ban_status": 1}), timeout=3.0
            )
            return user.get("ban_status", default) if user else default
        except Exception:
            return default

    async def get_all_banned_users(self) -> List[Dict[str, Any]]:
        try:
            return await self.col.find({"ban_status.is_banned": True}).to_list(
                length=None
            )
        except Exception:
            return []

    # ============================================================
    # 🏘️ CHATS & GROUP SETTINGS MANAGEMENT
    # ============================================================
    async def add_chat(self, chat: Union[int, str], title: str = "Group"):
        cid = int(chat)
        try:
            await asyncio.wait_for(
                self.grp.update_one(
                    {"id": cid},
                    {
                        "$set": {"title": str(title or "Group")},
                        "$setOnInsert": {
                            "id": cid,
                            "chat_status": {"is_disabled": False, "reason": ""},
                        },
                    },
                    upsert=True,
                ),
                timeout=4.0,
            )
        except Exception as e:
            logger.error(f"add_chat error ({cid}): {e}")

    async def get_chat(self, chat: Union[int, str]) -> Union[Dict[str, Any], bool]:
        try:
            chat_doc = await asyncio.wait_for(
                self.grp.find_one({"id": int(chat)}), timeout=3.0
            )
        except Exception:
            return False
        if not chat_doc:
            return False
        status = dict(chat_doc.get("chat_status") or {})
        status.setdefault("title", chat_doc.get("title", ""))
        status.setdefault("id", chat_doc.get("id", int(chat)))
        return status

    async def re_enable_chat(self, id: Union[int, str]):
        cid = int(id)
        try:
            await asyncio.wait_for(
                self.grp.update_one(
                    {"id": cid},
                    {"$set": {"chat_status": {"is_disabled": False, "reason": ""}}},
                    upsert=True,
                ),
                timeout=4.0,
            )
        except Exception as e:
            logger.error(f"re_enable_chat error ({cid}): {e}")

    async def disable_chat(self, chat: Union[int, str], reason: str = "No Reason"):
        cid = int(chat)
        try:
            await asyncio.wait_for(
                self.grp.update_one(
                    {"id": cid},
                    {
                        "$set": {
                            "chat_status": {
                                "is_disabled": True,
                                "reason": str(reason),
                            }
                        }
                    },
                    upsert=True,
                ),
                timeout=4.0,
            )
        except Exception as e:
            logger.error(f"disable_chat error ({cid}): {e}")

    async def delete_chat(self, chat_id: Union[int, str]) -> bool:
        cid = int(chat_id)
        try:
            res = await asyncio.wait_for(
                self.grp.delete_many(
                    {"$or": [{"id": cid}, {"chat_id": cid}, {"_id": cid}]}
                ),
                timeout=4.0,
            )
            return res.deleted_count > 0
        except Exception:
            return False

    async def total_chat_count(self) -> int:
        try:
            return int(
                await asyncio.wait_for(self.grp.count_documents({}), timeout=5.0)
            )
        except Exception:
            return 0

    async def get_all_chats(self) -> List[Dict[str, Any]]:
        try:
            chats = await self.grp.find({}).to_list(length=None)
            for c in chats:
                chat_status = c.get("chat_status") or {}
                if "is_disabled" not in c and "is_disabled" in chat_status:
                    c["is_disabled"] = chat_status["is_disabled"]
                if "reason" not in c and "reason" in chat_status:
                    c["reason"] = chat_status["reason"]
            return chats
        except Exception as e:
            logger.error(f"get_all_chats error: {e}")
            return []

    async def update_settings(self, id: Union[int, str], settings: Dict[str, Any]):
        cid = int(id)
        try:
            await asyncio.wait_for(
                self.grp.update_one(
                    {"id": cid}, {"$set": {"settings": settings}}, upsert=True
                ),
                timeout=4.0,
            )
        except Exception as e:
            logger.error(f"update_settings error ({cid}): {e}")

    async def get_settings(self, id: Union[int, str]) -> Dict[str, Any]:
        default = {
            "button": SINGLE_BUTTON,
            "botpm": P_TTI_SHOW_OFF,
            "file_secure": PROTECT_CONTENT,
            "imdb": IMDB,
            "spell_check": SPELL_CHECK_REPLY,
            "welcome": MELCOW_NEW_USERS,
            "template": IMDB_TEMPLATE,
            "auto_delete": getattr(info, "AUTO_DELETE", True),
            "button_del": int(getattr(info, "BUTTON_AUTO_DELETE", 300)),
        }
        try:
            chat = await asyncio.wait_for(
                self.grp.find_one({"id": int(id)}, {"settings": 1}), timeout=3.0
            )
            if chat and isinstance(chat.get("settings"), dict):
                return {**default, **chat["settings"]}
        except Exception:
            pass
        return default

    async def get_db_size(self) -> int:
        try:
            stats = await asyncio.wait_for(self.db.command("dbstats"), timeout=4.0)
            return int(stats.get("dataSize", 0) or 0)
        except Exception:
            return 0

    async def get_bot_setting(
        self, bot_id: Union[int, str], setting_name: str, default: Any = None
    ) -> Any:
        try:
            bot_doc = await asyncio.wait_for(
                self.bot_settings.find_one({"id": int(bot_id)}), timeout=3.0
            )
            return bot_doc.get(setting_name, default) if bot_doc else default
        except Exception:
            return default

    async def update_bot_setting(
        self, bot_id: Union[int, str], setting_name: str, value: Any
    ):
        try:
            await asyncio.wait_for(
                self.bot_settings.update_one(
                    {"id": int(bot_id)}, {"$set": {setting_name: value}}, upsert=True
                ),
                timeout=4.0,
            )
        except Exception as e:
            logger.error(f"update_bot_setting error: {e}")


db = Database(DATABASE_URI, DATABASE_NAME)
