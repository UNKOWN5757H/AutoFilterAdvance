import asyncio
import logging
import time

from pyrogram import Client, StopPropagation, enums, filters
from pyrogram.types import (
    ChatPermissions,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

import info
from database.plugin_dbs import plugin_db

logger = logging.getLogger(__name__)


async def is_admin(bot: Client, chat_id: int, user_id: int) -> bool:
    """Safely checks if a user is a bot admin or a chat admin using Pyrogram V2 Enums."""
    # 1. Check if user is a global bot admin
    if user_id in info.ADMINS or str(user_id) in info.ADMINS:
        return True
    
    # 2. Check if user is an admin in the specific group
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in [
            enums.ChatMemberStatus.ADMINISTRATOR,
            enums.ChatMemberStatus.OWNER,
        ]
    except Exception:
        return False


# ============================================================
# ⚙️ MAIN ADMIN COMMANDS (Set & Target)
# ============================================================
@Client.on_message(filters.command("setforceadd") & filters.group)
async def set_force_add(bot: Client, message: Message):
    if not message.from_user:
        return await message.reply_text("❌ **Anonymous Admins cannot use this command. Please reveal your account to configure this.**")
        
    if not await is_admin(bot, message.chat.id, message.from_user.id):
        return await message.reply_text("❌ **Only admins can use this command.**")

    if len(message.command) < 2:
        return await message.reply_text(
            "⚙️ **Usage:** `/setforceadd <number>`\nExample: `/setforceadd 5`"
        )

    try:
        limit = int(message.command[1])
        if limit < 0:
            raise ValueError
    except ValueError:
        return await message.reply_text("❌ Please provide a valid positive number.")

    # Show buttons to choose target audience
    admin_id = message.from_user.id
    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "👥 Force Add for ALL Members",
                    callback_data=f"fa_set_{limit}_all_{admin_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    "🆕 Force Add for ONLY NEW Members",
                    callback_data=f"fa_set_{limit}_new_{admin_id}",
                )
            ],
        ]
    )
    await message.reply_text(
        "🎯 **Who should this requirement apply to?**\n\n*(Select an option below)*",
        reply_markup=kb,
    )


@Client.on_callback_query(filters.regex(r"^fa_set_(\d+)_([a-z]+)_(\d+)$"))
async def set_forceadd_callback(bot: Client, query):
    limit = int(query.matches[0].group(1))
    mode = query.matches[0].group(2)
    admin_id = int(query.matches[0].group(3))

    if query.from_user.id != admin_id:
        return await query.answer(
            "❌ Only the admin who ran the command can choose this.", show_alert=True
        )

    await plugin_db.set_fa_settings(query.message.chat.id, limit, mode)
    mode_text = (
        "ALL MEMBERS" if mode == "all" else "ONLY NEW MEMBERS (who join from now on)"
    )

    await query.message.edit_text(
        f"✅ **Force Add Configured Successfully!**\n\n"
        f"🔢 **Limit:** `{limit} members`\n"
        f"🎯 **Target:** `{mode_text}`\n"
        f"*(Saved permanently)*"
    )


@Client.on_message(filters.command("remforceadd") & filters.group)
async def remove_force_add(bot: Client, message: Message):
    if not message.from_user:
        return
    if not await is_admin(bot, message.chat.id, message.from_user.id):
        return
    await plugin_db.set_fa_settings(message.chat.id, 0, "all")
    await message.reply_text(
        "🗑️ **Force Add requirement has been completely removed.**"
    )


@Client.on_message(filters.command("getforceadd") & filters.group)
async def get_force_add(bot: Client, message: Message):
    settings = await plugin_db.get_fa_settings(message.chat.id)
    if settings["limit"] == 0:
        await message.reply_text("ℹ️ **Force Add is currently DISABLED.**")
    else:
        target = "Everyone" if settings["mode"] == "all" else "Only New Members"
        await message.reply_text(
            f"ℹ️ **Current Requirement:** Users must add {settings['limit']} members.\n🎯 **Applies to:** {target}"
        )


# ============================================================
# 🏆 LEADERBOARDS & RESETS
# ============================================================
async def generate_leaderboard(message, title, time_limit_seconds):
    top_10 = await plugin_db.get_fa_top_adds(message.chat.id, time_limit_seconds)

    if not top_10:
        return await message.reply_text(
            f"📊 **{title}**\n\nNo members have added anyone yet!"
        )

    text = f"📊 **{title} (Top 10)**\n\n"
    for i, (uid, score) in enumerate(top_10, 1):
        text += (
            f"**{i}.** <a href='tg://user?id={uid}'>User {uid}</a> ➔ `{score}` added\n"
        )

    await message.reply_text(text, disable_web_page_preview=True)


@Client.on_message(filters.command("topaddall") & filters.group)
async def top_add_all(bot: Client, message: Message):
    await generate_leaderboard(message, "All-Time Top Adders", None)


@Client.on_message(filters.command("topadd24") & filters.group)
async def top_add_24(bot: Client, message: Message):
    await generate_leaderboard(message, "Top Adders (Past 24 Hours)", 86400)


@Client.on_message(filters.command("topadd7") & filters.group)
async def top_add_7(bot: Client, message: Message):
    await generate_leaderboard(message, "Top Adders (Past 7 Days)", 604800)


@Client.on_message(filters.command("resetadddaily") & filters.group)
async def reset_add_daily(bot: Client, message: Message):
    if not message.from_user:
        return
    if not await is_admin(bot, message.chat.id, message.from_user.id):
        return
    await plugin_db.reset_fa_daily_adds(message.chat.id)
    await message.reply_text(
        "♻️ **Daily/Weekly limits reset!** Leaderboards for 24h and 7d have been wiped."
    )


@Client.on_message(filters.command("resetadd") & filters.group)
async def reset_all_adds(bot: Client, message: Message):
    if not message.from_user:
        return
    if not await is_admin(bot, message.chat.id, message.from_user.id):
        return
    await plugin_db.reset_fa_all_adds(message.chat.id)
    await message.reply_text(
        "💥 **TOTAL RESET!** All members' scores are now 0. Everyone must add members again."
    )


# ============================================================
# 🧑‍💻 USER COMMAND: Check their own progress
# ============================================================
@Client.on_message(filters.command("myadds") & filters.group)
async def my_adds(bot: Client, message: Message):
    if not message.from_user:
        return
    settings = await plugin_db.get_fa_settings(message.chat.id)
    if settings["limit"] == 0:
        return await message.reply_text("ℹ️ Force Add is not active in this group.")

    current_adds = await plugin_db.get_fa_user_adds(message.chat.id, message.from_user.id)
    if current_adds >= settings["limit"]:
        await message.reply_text(
            f"✅ You have added **{current_adds}** members. You are cleared to chat freely!"
        )
    else:
        await message.reply_text(
            f"⚠️ You have added **{current_adds}/{settings['limit']}** members."
        )


# ============================================================
# 📥 TRACKER & ENFORCER (Combined Core Logic)
# ============================================================
@Client.on_message(filters.new_chat_members & filters.group)
async def track_added_members(bot: Client, message: Message):
    if not message.from_user:
        return

    # 1. Register ALL new joining members so the enforcer knows they are new!
    for u in message.new_chat_members:
        await plugin_db.track_fa_new_user(message.chat.id, u.id)

    # 2. Track who added who
    settings = await plugin_db.get_fa_settings(message.chat.id)
    if settings["limit"] == 0:
        return

    adder_id = message.from_user.id
    added_others = [
        u for u in message.new_chat_members if u.id != adder_id and not u.is_bot
    ]
    if not added_others:
        return

    await plugin_db.increment_fa_adds(message.chat.id, adder_id, len(added_others))
    current_adds = await plugin_db.get_fa_user_adds(message.chat.id, adder_id)

    if current_adds >= settings["limit"]:
        try:
            await bot.restrict_chat_member(
                message.chat.id,
                adder_id,
                permissions=ChatPermissions(
                    can_send_messages=True,
                    can_send_media_messages=True,
                    can_send_other_messages=True,
                    can_add_web_page_previews=True,
                    can_invite_users=True,
                ),
            )
        except Exception:
            pass

        msg = await message.reply_text(
            f"🎉 Thank you {message.from_user.mention}! You've met the requirement. You can now chat freely!"
        )
        await asyncio.sleep(8)
        try:
            await msg.delete()
        except Exception:
            pass


@Client.on_message(filters.group & ~filters.service, group=-1)
async def enforce_force_add(bot: Client, message: Message):
    if not message.from_user:
        return

    chat_id = message.chat.id
    user_id = message.from_user.id
    settings = await plugin_db.get_fa_settings(chat_id)
    limit = settings["limit"]

    if limit == 0:
        return

    # Check Target Mode
    if settings["mode"] == "new":
        if not await plugin_db.is_fa_new_user(chat_id, user_id):
            return  # Skip them, they are a legacy member!

    # Bypass bot commands
    text = message.text or message.caption
    if text and text.startswith("/"):
        return
    if await is_admin(bot, chat_id, user_id):
        return

    current_adds = await plugin_db.get_fa_user_adds(chat_id, user_id)
    if current_adds < limit:
        try:
            await message.delete()

            # Restrict for 2 minutes
            until_time = int(time.time()) + 120
            await bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=user_id,
                permissions=ChatPermissions(
                    can_send_messages=False, can_invite_users=True
                ),
                until_date=until_time,
            )

            warn_msg = await message.reply_text(
                f"🛑 **Hold on, {message.from_user.mention}!**\n\n"
                f"You must add **{limit - current_adds} more member(s)** to this group before you can send messages.\n\n"
                f"🔇 **You have been restricted from messaging.**",
                reply_markup=InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                "📊 How many users have I added?",
                                callback_data="forceadd_check",
                            )
                        ]
                    ]
                ),
            )
            raise StopPropagation
        except StopPropagation:
            raise
        except Exception:
            pass
        finally:
            if "warn_msg" in locals():

                async def delete_warning():
                    await asyncio.sleep(120)
                    try:
                        await warn_msg.delete()
                    except Exception:
                        pass

                asyncio.create_task(delete_warning())


# ============================================================
# 🖱️ BUTTON CLICK HANDLER (Pop-up Stats Alert)
# ============================================================
@Client.on_callback_query(filters.regex("^forceadd_check$"))
async def check_adds_button(bot: Client, query):
    chat_id = query.message.chat.id
    user_id = query.from_user.id
    settings = await plugin_db.get_fa_settings(chat_id)

    if settings["limit"] == 0:
        return await query.answer(
            "Force Add is not active in this group.", show_alert=True
        )

    current_adds = await plugin_db.get_fa_user_adds(chat_id, user_id)
    if current_adds >= settings["limit"]:
        await query.answer(
            f"✅ You have added {current_adds} members.\nYou are cleared to chat freely!",
            show_alert=True,
        )
    else:
        await query.answer(
            f"⚠️ You have added {current_adds}/{settings['limit']} members.\n\nYou need {settings['limit'] - current_adds} more to chat.",
            show_alert=True,
        )
