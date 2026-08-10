import asyncio
import logging

from pyrogram import Client, enums, filters
from pyrogram.enums import ButtonStyle
from pyrogram.errors import (
    ChatAdminRequired,
    MessageNotModified,
    UserIsBlocked,
    UserNotParticipant,
)
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

import info
from database.plugin_dbs import plugin_db

logger = logging.getLogger(__name__)

# ============================================================
# 🗄️ FSub Database & Dynamic State Variables
# ============================================================
if not hasattr(info, "IS_FSUB_ENABLED"):
    info.IS_FSUB_ENABLED = True

if not hasattr(info, "FSUB_MAX_COUNT"):
    info.FSUB_MAX_COUNT = 0

if not hasattr(info, "FSUB_CHANNELS"):
    info.FSUB_CHANNELS = {}


def migrate_legacy_fsub():
    if (
        getattr(info, "AUTH_CHANNEL", None)
        and str(info.AUTH_CHANNEL) not in info.FSUB_CHANNELS
    ):
        info.FSUB_CHANNELS[str(info.AUTH_CHANNEL)] = {
            "title": "Main Channel",
            "link": None,
            "target": None,
            "type": "regular",
            "status": "active",
        }
    if (
        getattr(info, "REQ_CHANNEL", None)
        and str(info.REQ_CHANNEL) not in info.FSUB_CHANNELS
    ):
        info.FSUB_CHANNELS[str(info.REQ_CHANNEL)] = {
            "title": "Request Channel",
            "link": None,
            "target": None,
            "type": "req",
            "status": "active",
        }


migrate_legacy_fsub()


# ============================================================
# 🔗 Link Generation & Caching
# ============================================================
async def get_invite_link(bot: Client, chat_id: str) -> str:
    channel_data = info.FSUB_CHANNELS.get(chat_id, {})

    if channel_data.get("target"):
        return channel_data["target"]

    if channel_data.get("link"):
        return channel_data["link"]

    try:
        chat = await bot.get_chat(int(chat_id))
        is_req = channel_data.get("type") == "req"
        invite = await bot.create_chat_invite_link(
            int(chat_id), creates_join_request=is_req
        )

        info.FSUB_CHANNELS[chat_id]["link"] = invite.invite_link
        info.FSUB_CHANNELS[chat_id]["title"] = chat.title
        return invite.invite_link
    except Exception as e:
        logger.error(f"Failed to fetch invite link for {chat_id}: {e}")
        return ""


# ============================================================
# 🧠 Runtime Dynamic ForceSub Checker
# ============================================================
async def check_user_in_channel(bot: Client, channel_id: int, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(channel_id, user_id)
        return member.status in [
            enums.ChatMemberStatus.MEMBER,
            enums.ChatMemberStatus.ADMINISTRATOR,
            enums.ChatMemberStatus.OWNER,
        ]
    except UserNotParticipant:
        return False
    except Exception as e:
        logger.error(f"FSub check error for channel {channel_id}: {e}")
        return False


async def ForceSub(
    bot: Client, message: Message, file_id: str = None, mode: str = None
) -> bool:
    user = message.from_user

    if (
        not user
        or str(user.id) in [str(a) for a in getattr(info, "ADMINS", [])]
        or not getattr(info, "IS_FSUB_ENABLED", True)
    ):
        return True

    active_fsubs = {
        k: v for k, v in info.FSUB_CHANNELS.items() if v.get("status") == "active"
    }

    if not active_fsubs:
        return True

    not_joined_buttons = []

    try:
        for chat_id_str, data in active_fsubs.items():
            chat_id = int(chat_id_str)
            is_participant = await check_user_in_channel(bot, chat_id, user.id)

            if not is_participant:
                link = await get_invite_link(bot, chat_id_str)
                if link:
                    btn_text = (
                        "⚓ Request to Join"
                        if data.get("type") == "req"
                        else "📢 Join Channel"
                    )
                    not_joined_buttons.append(
                        [
                            InlineKeyboardButton(
                                btn_text,
                                url=link,
                                icon_custom_emoji_id=5258096772776991776,
                                style=ButtonStyle.PRIMARY,
                            )
                        ]
                    )

        if not not_joined_buttons:
            await plugin_db.add_fsub_user(user.id)
            return True

        cb_data = f"refresh_fsub_{file_id}" if file_id else "refresh_fsub_0"
        not_joined_buttons.append(
            [
                InlineKeyboardButton(
                    text="✅ I've Joined",
                    callback_data=cb_data,
                    icon_custom_emoji_id=5258503720928288433,
                    style=ButtonStyle.SUCCESS,
                )
            ]
        )

        try:
            await message.reply_text(
                "Please join below channel to get file!",
                reply_markup=InlineKeyboardMarkup(not_joined_buttons),
                disable_web_page_preview=True,
            )
        except UserIsBlocked:
            return False

        return False

    except Exception as e:
        logger.exception(f"[ForceSub Error] {e}")
        return True


# ============================================================
# 🔄 Callback Query Handler: Verify & Send File Automatically
# ============================================================
@Client.on_callback_query(filters.regex(r"^refresh_fsub_(.*)"))
async def refresh_fsub_callback(bot: Client, query: CallbackQuery):
    user_id = query.from_user.id
    file_id = query.matches[0].group(1)

    active_fsubs = {
        k: v for k, v in info.FSUB_CHANNELS.items() if v.get("status") == "active"
    }

    if not active_fsubs:
        return await query.answer(
            "Force subscribe is no longer required.", show_alert=True
        )

    not_joined_channels = False

    for chat_id_str in active_fsubs.keys():
        is_participant = await check_user_in_channel(bot, int(chat_id_str), user_id)
        if not is_participant:
            not_joined_channels = True
            break

    if not_joined_channels:
        await query.answer(
            "❌ You haven't joined all required channels yet!", show_alert=True
        )
    else:
        await plugin_db.add_fsub_user(user_id)

        try:
            await query.message.delete()
        except Exception:
            pass

        await query.answer("✅ Subscriptions verified!", show_alert=False)

        # Automatically send media directly if file_id is present
        if file_id and file_id != "0":
            try:
                await bot.send_cached_media(
                    chat_id=user_id,
                    file_id=file_id,
                    caption="🎉 **Thank you for joining! Here is your file:**",
                )
            except Exception as e:
                logger.error(f"Failed to send cached file {file_id} to {user_id}: {e}")
                await bot.send_message(
                    chat_id=user_id,
                    text="✅ **Verification complete!** Please send your file request link again.",
                )


# ============================================================
# ⚙️ Basic Controls & Queue Configuration
# ============================================================
@Client.on_message(filters.command("enablefsub") & filters.user(info.ADMINS))
async def enable_fsub(bot: Client, message: Message):
    info.IS_FSUB_ENABLED = True
    await message.reply_text("✅ **Force Subscribe has been ENABLED.**")


@Client.on_message(filters.command("disablefsub") & filters.user(info.ADMINS))
async def disable_fsub(bot: Client, message: Message):
    info.IS_FSUB_ENABLED = False
    await message.reply_text("❌ **Force Subscribe has been DISABLED.**")


@Client.on_message(filters.command("setfsubcount") & filters.user(info.ADMINS))
async def set_fsub_count(bot: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text(
            "⚙️ **Usage:** `/setfsubcount [number]`\n*Set to 0 for unlimited active channels.*"
        )

    try:
        count = int(message.command[1])
        if count < 0:
            raise ValueError
        info.FSUB_MAX_COUNT = count

        limit_text = (
            f"maximum `{count}` active channels"
            if count > 0
            else "unlimited active channels"
        )
        await message.reply_text(
            f"✅ **FSub Queue Limit Updated!**\nThe system will now allow a {limit_text}."
        )
    except ValueError:
        await message.reply_text(
            "❌ **Invalid number.** Please provide a valid positive integer."
        )


# ============================================================
# ➕ Interactive Add / Set FSub
# ============================================================
@Client.on_message(filters.command("setfsub") & filters.user(info.ADMINS))
async def add_dynamic_fsub(bot: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text("⚙️ **Usage:** `/setfsub [channel_id]`")

    channel_id = message.command[1]

    try:
        chat = await bot.get_chat(int(channel_id))
    except Exception as e:
        return await message.reply_text(
            f"❌ **Failed to fetch channel.** Make sure the bot is an admin in `{channel_id}`.\n`Error: {e}`"
        )

    try:
        await message.reply_text(
            f"🎯 **Target:** `{chat.title}`\n\nDo you want this to be a **Join Request** channel?\n\nReply with `y` for Yes, or `n` for No (Normal invite)."
        )
        resp = await bot.listen(message.chat.id, timeout=30)

        if not resp or not resp.text:
            return await message.reply_text(
                "❌ **Invalid response.** Please send text (y/n)."
            )

        is_req = resp.text.lower() == "y"
        fsub_type = "req" if is_req else "regular"

        active_count = len(
            [c for c in info.FSUB_CHANNELS.values() if c.get("status") == "active"]
        )
        if info.FSUB_MAX_COUNT > 0 and active_count >= info.FSUB_MAX_COUNT:
            status = "pending"
        else:
            status = "active"

        invite = await bot.create_chat_invite_link(chat.id, creates_join_request=is_req)

        info.FSUB_CHANNELS[channel_id] = {
            "title": chat.title,
            "link": invite.invite_link,
            "target": None,
            "type": fsub_type,
            "status": status,
        }

        await message.reply_text(
            f"✅ **Successfully Configured FSub!**\n\n📢 **Channel:** `{chat.title}`\n🔗 **Link:** {invite.invite_link}\n⚙️ **Type:** `{'Join Request' if is_req else 'Normal'}`\n🟢 **Status:** `{status.upper()}`\n\n*(If status is PENDING, it was queued due to your `/setfsubcount` limit)*",
            disable_web_page_preview=True,
        )

    except ChatAdminRequired:
        await message.reply_text(
            "❌ **The bot is not an admin in that channel or lacks 'Invite Users' rights.**"
        )
    except asyncio.TimeoutError:
        await message.reply_text("⌛ **Timeout.** Setup cancelled.")
    except Exception as e:
        await message.reply_text(f"❌ **Error:** {e}")


# ============================================================
# 🔄 Manage Status & Targets (Queue System)
# ============================================================
@Client.on_message(filters.command("activatefsub") & filters.user(info.ADMINS))
async def activate_fsub(bot: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text("⚙️ **Usage:** `/activatefsub [channel_id]`")
    channel_id = message.command[1]

    if channel_id not in info.FSUB_CHANNELS:
        return await message.reply_text("❌ Channel not found in FSub database.")

    active_count = len(
        [c for c in info.FSUB_CHANNELS.values() if c.get("status") == "active"]
    )
    if info.FSUB_MAX_COUNT > 0 and active_count >= info.FSUB_MAX_COUNT:
        return await message.reply_text(
            f"⚠️ **Queue Full!** You already have `{active_count}` active channels (Limit: {info.FSUB_MAX_COUNT}).\nUse `/deactivatefsub` on another channel first."
        )

    info.FSUB_CHANNELS[channel_id]["status"] = "active"
    await message.reply_text(f"✅ FSub for `{channel_id}` is now **ACTIVE**.")


@Client.on_message(filters.command("deactivatefsub") & filters.user(info.ADMINS))
async def deactivate_fsub(bot: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text("⚙️ **Usage:** `/deactivatefsub [channel_id]`")
    channel_id = message.command[1]

    if channel_id in info.FSUB_CHANNELS:
        info.FSUB_CHANNELS[channel_id]["status"] = "pending"
        await message.reply_text(
            f"⏸ FSub for `{channel_id}` is now **PENDING (Deactivated)**."
        )
    else:
        await message.reply_text("❌ Channel not found in FSub database.")


@Client.on_message(filters.command("updatefsubtarget") & filters.user(info.ADMINS))
async def update_fsub_target(bot: Client, message: Message):
    if len(message.command) < 3:
        return await message.reply_text(
            "⚙️ **Usage:** `/updatefsubtarget [channel_id] [target_link]`\n*Use 'none' to remove custom target.*"
        )

    channel_id = str(message.command[1])
    target = message.command[2]

    if channel_id not in info.FSUB_CHANNELS:
        return await message.reply_text(
            f"❌ Channel `{channel_id}` is not configured in FSub."
        )

    if target.lower() == "none":
        info.FSUB_CHANNELS[channel_id]["target"] = None
        await message.reply_text(
            "✅ Custom target removed. Bot will use standard invite link."
        )
    else:
        info.FSUB_CHANNELS[channel_id]["target"] = target
        await message.reply_text(f"✅ Target for `{channel_id}` updated to:\n{target}")


# ============================================================
# 🗑 Remove Channels
# ============================================================
@Client.on_message(filters.command("rmfsub") & filters.user(info.ADMINS))
async def rem_fsub(bot: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text("⚙️ **Usage:** `/rmfsub [channel_id]`")
    channel_id = message.command[1]

    if channel_id in info.FSUB_CHANNELS:
        del info.FSUB_CHANNELS[channel_id]
        await message.reply_text(f"🗑️ **ForceSub channel `{channel_id}` removed.**")
    else:
        await message.reply_text("❌ Channel not found in FSub database.")


@Client.on_message(filters.command("rmallfsub") & filters.user(info.ADMINS))
async def rem_all_fsub(bot: Client, message: Message):
    info.FSUB_CHANNELS.clear()
    await message.reply_text(
        "🗑️ **ALL ForceSub channels have been removed and queue is empty.**"
    )


# ============================================================
# 📊 Get Lists (All / Active / Pending)
# ============================================================
def build_fsub_list_text(title_prefix: str, filter_status: str = None) -> str:
    channels = info.FSUB_CHANNELS.items()
    if filter_status:
        channels = [(k, v) for k, v in channels if v.get("status") == filter_status]

    if not channels:
        return f"❌ No {title_prefix.lower()} ForceSub channels found."

    text = f"📋 **{title_prefix} ForceSub Channels:**\n\n"
    for idx, (cid, data) in enumerate(channels, 1):
        status_emoji = "🟢" if data.get("status") == "active" else "🟡"
        req_type = "Req" if data.get("type") == "req" else "Normal"
        active_link = data.get("target") or data.get("link") or "No Link Generated"

        text += f"{idx}. {status_emoji} **{data.get('title', 'Unknown')}**\n├ ID: `{cid}`\n├ Type: `{req_type}`\n└ Link: {active_link}\n\n"

    return text


@Client.on_message(filters.command("getallfsub") & filters.user(info.ADMINS))
async def get_all_fsub(bot: Client, message: Message):
    text = f"⚙️ **Queue Limit:** `{info.FSUB_MAX_COUNT if info.FSUB_MAX_COUNT > 0 else 'Unlimited'}`\n\n"
    text += build_fsub_list_text("All")
    await message.reply_text(text, disable_web_page_preview=True)


@Client.on_message(filters.command("getactivefsub") & filters.user(info.ADMINS))
async def get_active_fsub(bot: Client, message: Message):
    await message.reply_text(
        build_fsub_list_text("Active", "active"), disable_web_page_preview=True
    )


@Client.on_message(filters.command("getpendingfsub") & filters.user(info.ADMINS))
async def get_pending_fsub(bot: Client, message: Message):
    await message.reply_text(
        build_fsub_list_text("Pending", "pending"), disable_web_page_preview=True
    )


# ============================================================
# 👥 Users & Requests Management
# ============================================================
@Client.on_message(filters.command("checkfsubusers") & filters.user(info.ADMINS))
async def check_fsub_users(bot: Client, message: Message):
    count = await plugin_db.get_fsub_count()
    await message.reply_text(
        f"👥 **Total Force Subscribed Users (DB):** <code>{count}</code>"
    )


@Client.on_message(filters.command("clearfsubusers") & filters.user(info.ADMINS))
async def clear_fsub_users(bot: Client, message: Message):
    try:
        await message.reply_text(
            "⚠️ Are you sure you want to clear all FSub users from the database? Reply with 'y' to confirm."
        )
        resp = await bot.listen(message.chat.id, timeout=30)

        if resp and resp.text and resp.text.lower() == "y":
            await plugin_db.clear_fsub_users()
            await message.reply_text(
                "✅ All force subscribed users have been cleared from the database."
            )
        else:
            await message.reply_text("❌ Cancelled.")
    except asyncio.TimeoutError:
        await message.reply_text("⌛ Timeout: Operation cancelled.")
