#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import motor.motor_asyncio
from pymongo.errors import DuplicateKeyError

from info import REQ_CHANNEL, JOIN_REQS_DB

logger = logging.getLogger(__name__)


class JoinReqs:

    def __init__(self):

        self.client = None
        self.db = None
        self.col = None

        if JOIN_REQS_DB:
            try:
                self.client = motor.motor_asyncio.AsyncIOMotorClient(
                    JOIN_REQS_DB,
                    serverSelectionTimeoutMS=5000
                )

                self.db = self.client["JoinReqs"]
                self.col = self.db[str(REQ_CHANNEL)]

            except Exception as e:
                logger.exception(f"MongoDB Connection Error: {e}")

    def isActive(self):
        return self.col is not None

    async def add_user(self, user_id, first_name=None, username=None, date=None):

        if not self.isActive():
            return False

        data = {
            "_id": int(user_id),
            "user_id": int(user_id),
            "first_name": first_name or "",
            "username": username or "",
            "date": date
        }

        try:
            await self.col.insert_one(data)
            return True

        except DuplicateKeyError:
            return False

        except Exception as e:
            logger.exception(f"add_user(): {e}")
            return False

    async def get_user(self, user_id):

        if not self.isActive():
            return None

        try:
            return await self.col.find_one(
                {"user_id": int(user_id)}
            )

        except Exception as e:
            logger.exception(f"get_user(): {e}")
            return None

    async def get_all_users(self):

        if not self.isActive():
            return []

        try:
            cursor = self.col.find({})
            return await cursor.to_list(length=None)

        except Exception as e:
            logger.exception(f"get_all_users(): {e}")
            return []

    async def delete_user(self, user_id):

        if not self.isActive():
            return False

        try:
            result = await self.col.delete_one(
                {"user_id": int(user_id)}
            )
            return result.deleted_count > 0

        except Exception as e:
            logger.exception(f"delete_user(): {e}")
            return False

    async def delete_all_users(self):

        if not self.isActive():
            return 0

        try:
            result = await self.col.delete_many({})
            return result.deleted_count

        except Exception as e:
            logger.exception(f"delete_all_users(): {e}")
            return 0

    async def get_all_users_count(self):

        if not self.isActive():
            return 0

        try:
            return await self.col.count_documents({})

        except Exception as e:
            logger.exception(f"get_all_users_count(): {e}")
            return 0


join_reqs = JoinReqs()
