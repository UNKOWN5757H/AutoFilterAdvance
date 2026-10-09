from logging import ERROR, getLogger

from pyrogram import Client, filters
from pyrogram.types import Message

import info
from database.plugin_dbs import plugin_db as _plugin_db

logger = getLogger(__name__)
logger.setLevel(ERROR)


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


@Client.on_message(filters.command("ban") & admin_filter)
async def ban_user_cmd(bot: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text("⚙️ **Usage:** `/ban [user_id]`")
    try:
        user_id = int(message.command[1])
        if user_id in get_admin_list():
            return await message.reply_text(
                "❌ **You cannot ban a bot administrator!**"
            )
        if user_id == bot.me.id:
            return await message.reply_text("❌ **I cannot ban myself!**")

        await _plugin_db.ban_user(user_id)
        await message.reply_text(
            f"🚫 **User `{user_id}` has been successfully BANNED.**\nThey can no longer use this bot."
        )
    except ValueError:
        await message.reply_text(
            "❌ **Invalid User ID!** Please provide a valid numerical ID."
        )
    except Exception as e:
        await message.reply_text(f"❌ **Error:** `{e}`")


@Client.on_message(filters.command("unban") & admin_filter)
async def unban_user_cmd(bot: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text("⚙️ **Usage:** `/unban [user_id]`")
    try:
        user_id = int(message.command[1])
        is_banned = await _plugin_db.is_banned(user_id)
        if not is_banned:
            return await message.reply_text(
                f"⚠️ **User `{user_id}` is not currently banned.**"
            )

        await _plugin_db.unban_user(user_id)
        await message.reply_text(
            f"✅ **User `{user_id}` has been successfully UNBANNED.**\nThey can now use the bot again."
        )
    except ValueError:
        await message.reply_text(
            "❌ **Invalid User ID!** Please provide a valid numerical ID."
        )
    except Exception as e:
        await message.reply_text(f"❌ **Error:** `{e}`")


@Client.on_message(filters.command("bannedusers") & admin_filter)
async def check_banned_users(bot: Client, message: Message):
    try:
        count = await _plugin_db.get_ban_count()
        await message.reply_text(f"📊 **Total Banned Users:** `{count}`")
    except Exception as e:
        await message.reply_text(f"❌ **Error:** `{e}`")
