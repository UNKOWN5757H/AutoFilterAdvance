import asyncio
import logging
import time
import traceback

from pyrogram import Client, StopPropagation, enums, filters
from pyrogram.errors import MessageNotModified
from pyrogram.types import (
    ChatPermissions,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

import info
from database.connections_mdb import active_connection
from database.plugin_dbs import plugin_db

logger = logging.getLogger(__name__)


async def is_admin(bot: Client, chat_id: int, user_id: int) -> bool:
    """Safely checks if a user is a bot admin or a chat admin using Pyrogram V2 Enums."""
    try:
        if str(user_id) in [str(a) for a in getattr(info, "ADMINS", [])]:
            return True
    except Exception:
        pass

    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in [
            enums.ChatMemberStatus.ADMINISTRATOR,
            enums.ChatMemberStatus.OWNER,
        ]
    except Exception:
        return False


async def get_target_group(bot: Client, message: Message, require_admin: bool = True):
    """Resolves target group ID and verifies admin permissions."""
    if not message.from_user:
        return None, False

    if message.chat.type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
        grp_id = message.chat.id
    else:
        grp_id = await active_connection(str(message.from_user.id))
        if not grp_id:
            await message.reply_text(
                "⚠️ **You are not connected to any active group!**\n\n"
                "Use `/connect <group_id>` to connect to a group first."
            )
            return None, False

    if require_admin:
        admin_status = await is_admin(bot, grp_id, message.from_user.id)
        if not admin_status:
            await message.reply_text(
                "❌ **Only admins of the connected group can use this command.**"
            )
            return None, False

    return grp_id, True


# ============================================================
# ⚙️ MAIN ADMIN COMMANDS (Set & Target)
# ============================================================
@Client.on_message(filters.command("setforceadd") & (filters.group | filters.private))
async def set_force_add(bot: Client, message: Message):
    try:
        grp_id, ok = await get_target_group(bot, message, require_admin=True)
        if not ok:
            return

        if len(message.command) < 2:
            return await message.reply_text(
                "⚙️ **Usage:** `/setforceadd <number>`\nExample: `/setforceadd 5`"
            )

        try:
            limit = int(message.command[1])
            if limit < 0:
                raise ValueError
        except ValueError:
            return await message.reply_text(
                "❌ Please provide a valid positive number."
            )

        admin_id = message.from_user.id
        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "👥 Force Add for ALL Members",
                        callback_data=f"fa_set_{limit}_all_{admin_id}_{grp_id}",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "🆕 Force Add for ONLY NEW Members",
                        callback_data=f"fa_set_{limit}_new_{admin_id}_{grp_id}",
                    )
                ],
            ]
        )
        await message.reply_text(
            "🎯 **Who should this requirement apply to?**\n\n*(Select an option below)*",
            reply_markup=kb,
        )
    except Exception as e:
        logger.error(f"Error in set_force_add: {e}")
        try:
            await message.reply_text(
                "❌ **An error occurred while setting Force Add.**"
            )
        except Exception:
            pass


@Client.on_callback_query(filters.regex(r"^fa_set_(\d+)_([a-z]+)_(\d+)_(-?\d+)$"))
async def set_forceadd_callback(bot: Client, query):
    try:
        limit = int(query.matches[0].group(1))
        mode = query.matches[0].group(2)
        admin_id = int(query.matches[0].group(3))
        grp_id = int(query.matches[0].group(4))

        if query.from_user.id != admin_id:
            return await query.answer(
                "❌ Only the admin who ran the command can choose this.",
                show_alert=True,
            )

        await plugin_db.set_fa_settings(grp_id, limit, mode)
        mode_text = (
            "ALL MEMBERS"
            if mode == "all"
            else "ONLY NEW MEMBERS (who join from now on)"
        )

        try:
            await query.message.edit_text(
                f"✅ **Force Add Configured Successfully!**\n\n"
                f"🔢 **Limit:** `{limit} members`\n"
                f"🎯 **Target:** `{mode_text}`\n"
                f"*(Saved permanently)*"
            )
        except MessageNotModified:
            pass
        await query.answer()
    except Exception as e:
        logger.error(f"Callback error in set_forceadd: {e}")
        await query.answer("An error occurred.", show_alert=True)


@Client.on_message(filters.command("remforceadd") & (filters.group | filters.private))
async def remove_force_add(bot: Client, message: Message):
    try:
        grp_id, ok = await get_target_group(bot, message, require_admin=True)
        if not ok:
            return

        await plugin_db.set_fa_settings(grp_id, 0, "all")
        await message.reply_text(
            "🗑️ **Force Add requirement has been completely removed.**"
        )
    except Exception as e:
        logger.error(f"Error in remforceadd: {e}")


@Client.on_message(filters.command("getforceadd") & (filters.group | filters.private))
async def get_force_add(bot: Client, message: Message):
    try:
        grp_id, ok = await get_target_group(bot, message, require_admin=False)
        if not ok:
            return

        settings = await plugin_db.get_fa_settings(grp_id)
        if settings["limit"] == 0:
            await message.reply_text("ℹ️ **Force Add is currently DISABLED.**")
        else:
            target = "Everyone" if settings["mode"] == "all" else "Only New Members"
            await message.reply_text(
                f"ℹ️ **Current Requirement:** Users must add {settings['limit']} members.\n🎯 **Applies to:** {target}"
            )
    except Exception as e:
        logger.error(f"Error in getforceadd: {e}")


# ============================================================
# 🏆 LEADERBOARDS & RESETS
# ============================================================
async def generate_leaderboard(bot, message, grp_id, title, time_limit_seconds):
    try:
        top_10 = await plugin_db.get_fa_top_adds(grp_id, time_limit_seconds)

        if not top_10:
            return await message.reply_text(
                f"📊 **{title}**\n\nNo members have added anyone yet!"
            )

        text = f"📊 **{title} (Top 10)**\n\n"
        for i, (uid, score) in enumerate(top_10, 1):
            try:
                user = await bot.get_users(uid)
                user_name = user.mention if user else f"User {uid}"
            except Exception:
                user_name = f"User {uid}"

            text += f"**{i}.** {user_name} ➔ `{score}` added\n"

        await message.reply_text(text, disable_web_page_preview=True)
    except Exception as e:
        logger.error(f"Error generating leaderboard: {e}")


@Client.on_message(filters.command("topaddall") & (filters.group | filters.private))
async def top_add_all(bot: Client, message: Message):
    grp_id, ok = await get_target_group(bot, message, require_admin=False)
    if ok:
        await generate_leaderboard(bot, message, grp_id, "All-Time Top Adders", None)


@Client.on_message(filters.command("topadd24") & (filters.group | filters.private))
async def top_add_24(bot: Client, message: Message):
    grp_id, ok = await get_target_group(bot, message, require_admin=False)
    if ok:
        await generate_leaderboard(bot, message, grp_id, "Top Adders (Past 24 Hours)", 86400)


@Client.on_message(filters.command("topadd7") & (filters.group | filters.private))
async def top_add_7(bot: Client, message: Message):
    grp_id, ok = await get_target_group(bot, message, require_admin=False)
    if ok:
        await generate_leaderboard(bot, message, grp_id, "Top Adders (Past 7 Days)", 604800)


@Client.on_message(filters.command("resetadddaily") & (filters.group | filters.private))
async def reset_add_daily(bot: Client, message: Message):
    try:
        grp_id, ok = await get_target_group(bot, message, require_admin=True)
        if not ok:
            return

        await plugin_db.reset_fa_daily_adds(grp_id)
        await message.reply_text(
            "♻️ **Daily/Weekly limits reset!** Leaderboards for 24h and 7d have been wiped."
        )
    except Exception as e:
        logger.error(f"Error in resetadddaily: {e}")


@Client.on_message(filters.command("resetadd") & (filters.group | filters.private))
async def reset_all_adds(bot: Client, message: Message):
    try:
        grp_id, ok = await get_target_group(bot, message, require_admin=True)
        if not ok:
            return

        await plugin_db.reset_fa_all_adds(grp_id)
        await message.reply_text(
            "💥 **TOTAL RESET!** All members' scores are now 0. Everyone must add members again."
        )
    except Exception as e:
        logger.error(f"Error in resetadd: {e}")


# ============================================================
# 🧑‍💻 USER COMMAND: Check their own progress
# ============================================================
@Client.on_message(filters.command("myadds") & (filters.group | filters.private))
async def my_adds(bot: Client, message: Message):
    try:
        grp_id, ok = await get_target_group(bot, message, require_admin=False)
        if not ok:
            return

        settings = await plugin_db.get_fa_settings(grp_id)
        if settings["limit"] == 0:
            return await message.reply_text("ℹ️ Force Add is not active in this group.")

        current_adds = await plugin_db.get_fa_user_adds(
            grp_id, message.from_user.id
        )
        if current_adds >= settings["limit"]:
            await message.reply_text(
                f"✅ You have added **{current_adds}** members. You are cleared to chat freely!"
            )
        else:
            await message.reply_text(
                f"⚠️ You have added **{current_adds}/{settings['limit']}** members."
            )
    except Exception as e:
        logger.error(f"Error in myadds command: {e}")


# ============================================================
# 📥 TRACKER & ENFORCER (Combined Core Logic)
# ============================================================
@Client.on_message(filters.new_chat_members & filters.group)
async def track_added_members(bot: Client, message: Message):
    try:
        if not message.from_user:
            return

        for u in message.new_chat_members:
            await plugin_db.track_fa_new_user(message.chat.id, u.id)

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
            except Exception as e:
                logger.error(f"Failed to unrestrict user {adder_id}: {e}")

            try:
                msg = await message.reply_text(
                    f"🎉 Thank you {message.from_user.mention}! You've met the requirement. You can now chat freely!"
                )
                await asyncio.sleep(8)
                await msg.delete()
            except Exception:
                pass
    except Exception as e:
        logger.error(f"Error in track_added_members: {e}")


@Client.on_message(filters.group & ~filters.service, group=-1)
async def enforce_force_add(bot: Client, message: Message):
    if not message.from_user:
        return

    chat_id = message.chat.id
    user_id = message.from_user.id
    warn_msg = None

    try:
        settings = await plugin_db.get_fa_settings(chat_id)
        limit = settings["limit"]

        if limit == 0:
            return

        if settings["mode"] == "new":
            if not await plugin_db.is_fa_new_user(chat_id, user_id):
                return

        text = message.text or message.caption
        if text and text.startswith("/"):
            return
        if await is_admin(bot, chat_id, user_id):
            return

        current_adds = await plugin_db.get_fa_user_adds(chat_id, user_id)

        if current_adds < limit:
            try:
                await message.delete()
            except Exception:
                pass

            try:
                until_time = int(time.time()) + 120
                await bot.restrict_chat_member(
                    chat_id=chat_id,
                    user_id=user_id,
                    permissions=ChatPermissions(
                        can_send_messages=False, can_invite_users=True
                    ),
                    until_date=until_time,
                )
            except Exception:
                pass

            try:
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
            except Exception:
                pass

            raise StopPropagation
    except StopPropagation:
        raise
    except Exception as e:
        logger.error(f"Error in enforce_force_add: {e}\n{traceback.format_exc()}")
    finally:
        if warn_msg:

            async def delete_warning(msg_to_delete):
                await asyncio.sleep(120)
                try:
                    await msg_to_delete.delete()
                except Exception:
                    pass

            asyncio.create_task(delete_warning(warn_msg))


# ============================================================
# 🖱️ BUTTON CLICK HANDLER (Pop-up Stats Alert)
# ============================================================
@Client.on_callback_query(filters.regex("^forceadd_check$"))
async def check_adds_button(bot: Client, query):
    try:
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
    except Exception as e:
        logger.error(f"Error in check_adds_button: {e}")
        try:
            await query.answer(
                "An error occurred checking your status.", show_alert=True
            )
        except Exception:
            pass
