import logging

from pyrogram import Client, filters
from pyrogram.types import Message

import info
from database.plugin_dbs import plugin_db

logger = logging.getLogger(__name__)


@Client.on_message(filters.command("ban") & filters.user(info.ADMINS))
async def ban_user_cmd(bot: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text("⚙️ **Usage:** `/ban [user_id]`")
    try:
        user_id = int(message.command[1])
        if user_id in info.ADMINS:
            return await message.reply_text(
                "❌ **You cannot ban a bot administrator!**"
            )
        if user_id == bot.me.id:
            return await message.reply_text("❌ **I cannot ban myself!**")

        await plugin_db.ban_user(user_id)
        await message.reply_text(
            f"🚫 **User `{user_id}` has been successfully BANNED.**"
        )
    except ValueError:
        await message.reply_text("❌ **Invalid User ID!**")


@Client.on_message(filters.command("unban") & filters.user(info.ADMINS))
async def unban_user_cmd(bot: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text("⚙️ **Usage:** `/unban [user_id]`")
    try:
        user_id = int(message.command[1])
        if not await plugin_db.is_banned(user_id):
            return await message.reply_text(
                f"⚠️ **User `{user_id}` is not currently banned.**"
            )

        await plugin_db.unban_user(user_id)
        await message.reply_text(
            f"✅ **User `{user_id}` has been successfully UNBANNED.**"
        )
    except ValueError:
        await message.reply_text("❌ **Invalid User ID!**")


@Client.on_message(filters.command("bannedusers") & filters.user(info.ADMINS))
async def check_banned_users(bot: Client, message: Message):
    count = await plugin_db.get_ban_count()
    await message.reply_text(f"📊 **Total Banned Users:** `{count}`")
