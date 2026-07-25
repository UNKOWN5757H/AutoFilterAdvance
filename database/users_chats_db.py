import motor.motor_asyncio

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


class Database:
    def __init__(self, uri, database_name):
        self._client = motor.motor_asyncio.AsyncIOMotorClient(uri)
        self.db = self._client[database_name]
        self.col = self.db.users
        self.grp = self.db.groups

    def new_user(self, id, name):
        return dict(
            id=id,
            name=name,
            ban_status=dict(
                is_banned=False,
                ban_reason="",
            ),
        )

    def new_group(self, id, title):
        return dict(
            id=id,
            title=title,
            chat_status=dict(
                is_disabled=False,
                reason="",
            ),
        )

    async def add_user(self, id, name):
        user = self.new_user(id, name)
        await self.col.insert_one(user)

    async def is_user_exist(self, id):
        user = await self.col.find_one({"id": int(id)})
        return bool(user)

    async def total_users_count(self):
        return await self.col.count_documents({})

    async def remove_ban(self, id):
        ban_status = dict(is_banned=False, ban_reason="")
        await self.col.update_one({"id": int(id)}, {"$set": {"ban_status": ban_status}})

    async def ban_user(self, user_id, ban_reason="No Reason"):
        ban_status = dict(is_banned=True, ban_reason=ban_reason)
        await self.col.update_one(
            {"id": int(user_id)}, {"$set": {"ban_status": ban_status}}
        )

    async def get_ban_status(self, id):
        default = dict(is_banned=False, ban_reason="")
        user = await self.col.find_one({"id": int(id)})
        if not user:
            return default
        return user.get("ban_status", default)

    async def get_all_users(self):
        # FIXED: Return a list so len() works on the output
        return await self.col.find({}).to_list(length=None)

    async def delete_user(self, user_id):
        await self.col.delete_many({"id": int(user_id)})

    async def get_banned(self):
        users_cursor = self.col.find({"ban_status.is_banned": True})
        chats_cursor = self.grp.find({"chat_status.is_disabled": True})

        b_chats = [chat["id"] async for chat in chats_cursor]
        b_users = [user["id"] async for user in users_cursor]
        return b_users, b_chats

    async def add_chat(self, chat, title):
        chat_doc = self.new_group(chat, title)
        await self.grp.insert_one(chat_doc)

    async def get_chat(self, chat):
        chat_doc = await self.grp.find_one({"id": int(chat)})
        return False if not chat_doc else chat_doc.get("chat_status")

    async def re_enable_chat(self, id):
        chat_status = dict(
            is_disabled=False,
            reason="",
        )
        await self.grp.update_one(
            {"id": int(id)}, {"$set": {"chat_status": chat_status}}
        )

    async def update_settings(self, id, settings):
        await self.grp.update_one({"id": int(id)}, {"$set": {"settings": settings}})

    async def get_settings(self, id):
        default = {
            "button": SINGLE_BUTTON,
            "botpm": P_TTI_SHOW_OFF,
            "file_secure": PROTECT_CONTENT,
            "imdb": IMDB,
            "spell_check": SPELL_CHECK_REPLY,
            "welcome": MELCOW_NEW_USERS,
            "template": IMDB_TEMPLATE,
        }
        chat = await self.grp.find_one({"id": int(id)})
        if chat:
            return chat.get("settings", default)
        return default

    async def disable_chat(self, chat, reason="No Reason"):
        chat_status = dict(
            is_disabled=True,
            reason=reason,
        )
        await self.grp.update_one(
            {"id": int(chat)}, {"$set": {"chat_status": chat_status}}
        )

    async def total_chat_count(self):
        return await self.grp.count_documents({})

    async def get_all_chats(self):
        # FIXED: Return a list so len() works on the output
        return await self.grp.find({}).to_list(length=None)

    async def get_db_size(self):
        stats = await self.db.command("dbstats")
        return stats.get("dataSize", 0)

    async def movie_update_status(self, bot_id):
        return await self.get_bot_setting(
            bot_id, "MOVIE_UPDATE_NOTIFICATION", MOVIE_UPDATE_NOTIFICATION
        )

    async def update_movie_update_status(self, bot_id, enable):
        await self.update_bot_setting(bot_id, "MOVIE_UPDATE_NOTIFICATION", enable)


db = Database(DATABASE_URI, DATABASE_NAME)
