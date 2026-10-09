import asyncio
import time
from logging import ERROR, getLogger

from motor.motor_asyncio import AsyncIOMotorClient
from pyrogram import Client, enums, filters
from pyrogram.enums import ButtonStyle
from pyrogram.errors import (
    ChatAdminRequired,
    FloodWait,
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
from database.join_reqs import join_reqs as _join_reqs_db
from database.plugin_dbs import plugin_db as _plugin_db
from plugins.custom_settings import get_bot_settings

logger = getLogger(__name__)
logger.setLevel(ERROR)

# ============================================================
# ⚙️ MONGODB PERMANENT FSUB & VIP ENGINE
# ============================================================
_fsub_db = None
_vip_db = None

try:
    _DB_CLIENT = AsyncIOMotorClient(info.DATABASE_URI)
    _BOT_DB = _DB_CLIENT[info.DATABASE_NAME]
    _fsub_db = _BOT_DB["fsub_config"]
    _vip_db = _BOT_DB["fsub_vips"]
except Exception as e:
    logger.error(f"Failed to init FSub DB: {e}")


async def get_fsub_config():
    if _fsub_db is not None:
        doc = await _fsub_db.find_one({"_id": "config"})
        if doc:
            return doc
    return {
        "is_enabled": True,
        "max_count": 0,
        "rotation_enabled": False,
        "channels": {},
    }


async def update_fsub_config(key, value):
    if _fsub_db is not None:
        await _fsub_db.update_one(
            {"_id": "config"}, {"$set": {key: value}}, upsert=True
        )


async def update_fsub_channels(channels_dict):
    if _fsub_db is not None:
        await _fsub_db.update_one(
            {"_id": "config"}, {"$set": {"channels": channels_dict}}, upsert=True
        )


async def add_vip(user_id: int):
    if _vip_db is not None:
        await _vip_db.update_one(
            {"user_id": user_id}, {"$set": {"is_vip": True}}, upsert=True
        )


async def rem_vip(user_id: int):
    if _vip_db is not None:
        await _vip_db.delete_one({"user_id": user_id})


async def is_vip(user_id: int):
    if _vip_db is not None:
        doc = await _vip_db.find_one({"user_id": user_id})
        return bool(doc)
    return False


async def get_all_vips():
    if _vip_db is not None:
        return await _vip_db.find().to_list(length=None)
    return []


# ============================================================
# 👑 FOOLPROOF ADMIN & LISTENER ENGINE
# ============================================================
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

_WAITING_REQUESTS = {}


@Client.on_message(admin_filter, group=-12)
async def custom_listener(client: Client, message: Message):
    key = (message.chat.id, message.from_user.id)
    if key in _WAITING_REQUESTS:
        future = _WAITING_REQUESTS.pop(key)
        if not future.done():
            future.set_result(message)
        message.stop_propagation()


async def native_listen(
    client: Client, chat_id: int, user_id: int, timeout: int = 120
) -> Message:
    loop = asyncio.get_running_loop()
    future = loop.create_future()
    _WAITING_REQUESTS[(chat_id, user_id)] = future
    try:
        return await asyncio.wait_for(future, timeout=timeout)
    except asyncio.TimeoutError:
        _WAITING_REQUESTS.pop((chat_id, user_id), None)
        raise asyncio.TimeoutError


# ============================================================
# 🔗 INVITE LINK & USER CHECKING (2-LAYER FALLBACK)
# ============================================================
async def get_invite_link(bot: Client, chat_id_str: str, config: dict) -> str:
    channels = config.get("channels", {})
    channel_data = channels.get(chat_id_str, {})

    if channel_data.get("target"):
        return channel_data["target"]
    if channel_data.get("link"):
        return channel_data["link"]

    try:
        chat_id_int = int(chat_id_str.strip())
        chat = await bot.get_chat(chat_id_int)
        is_req = channel_data.get("type") == "req"
        invite = await bot.create_chat_invite_link(
            chat_id_int, creates_join_request=is_req
        )

        channels[chat_id_str]["link"] = invite.invite_link
        channels[chat_id_str]["title"] = chat.title
        await update_fsub_channels(channels)
        return invite.invite_link
    except ChatAdminRequired:
        return ""
    except Exception as e:
        return ""


async def check_user_in_channel(
    bot: Client, channel_id: int, user_id: int, is_req: bool = False
) -> bool:
    try:
        member = await bot.get_chat_member(channel_id, user_id)
        if member.status in [
            enums.ChatMemberStatus.MEMBER,
            enums.ChatMemberStatus.ADMINISTRATOR,
            enums.ChatMemberStatus.OWNER,
        ]:
            return True
    except UserNotParticipant:
        pass
    except FloodWait as e:
        await asyncio.sleep(e.value + 1)
        return await check_user_in_channel(bot, channel_id, user_id, is_req)
    except Exception:
        pass

    if is_req:
        try:
            if _join_reqs_db.isActive() and await _join_reqs_db.get_user(user_id):
                return True
        except Exception:
            pass

    return False


# ============================================================
# 🛑 MAIN FORCESUB INTERCEPTOR (WITH SMART ROTATION)
# ============================================================
async def ForceSub(
    bot: Client, message: Message, file_id: str = None, mode: str = None
) -> bool:
    user = message.from_user
    if not user or user.id in get_admin_list():
        return True

    if await is_vip(user.id):
        return True  # 👑 VIP BYPASS ACTIVATED

    config = await get_fsub_config()
    if not config.get("is_enabled", True):
        return True

    channels_dict = config.get("channels", {})
    if not channels_dict:
        return True

    rotation_enabled = config.get("rotation_enabled", False)
    max_count = config.get("max_count", 0)

    # ⏱️ 1-HOUR SMART TIME ROTATION ENGINE
    if rotation_enabled:
        eligible_channels = list(channels_dict.keys())
        if eligible_channels:
            shift = int(time.time() / 3600) % len(eligible_channels)
            eligible_channels = eligible_channels[shift:] + eligible_channels[:shift]
    else:
        eligible_channels = [
            k for k, v in channels_dict.items() if v.get("status") == "active"
        ]

    not_joined_buttons = []
    channels_to_force = 0

    try:
        for chat_id_str in eligible_channels:
            # 🎯 USER-SPECIFIC FALLBACK: Stop adding channels if max_count is reached
            if max_count > 0 and channels_to_force >= max_count:
                break

            data = channels_dict[chat_id_str]
            chat_id = int(chat_id_str)
            is_req = data.get("type") == "req"

            is_participant = await check_user_in_channel(bot, chat_id, user.id, is_req)

            # If user is NOT in this channel, demand it. If they are, skip and check the next one!
            if not is_participant:
                link = await get_invite_link(bot, chat_id_str, config)
                if link:
                    btn_text = "⚓ Request to Join" if is_req else "📢 Join Channel"
                    not_joined_buttons.append(
                        [
                            InlineKeyboardButton(
                                btn_text, url=link, style=ButtonStyle.PRIMARY
                            )
                        ]
                    )
                    channels_to_force += 1

        if not not_joined_buttons:
            await _plugin_db.add_fsub_user(user.id)
            return True

        cb_data = f"refresh_fsub_{file_id}" if file_id else "refresh_fsub_0"
        not_joined_buttons.append(
            [
                InlineKeyboardButton(
                    text="✅ I've Joined",
                    callback_data=cb_data,
                    style=ButtonStyle.SUCCESS,
                )
            ]
        )

        b_settings = await get_bot_settings()
        custom_fsub_img = b_settings.get("fsub_img", getattr(info, "FSUB_IMG", None))

        try:
            if custom_fsub_img:
                await message.reply_photo(
                    photo=custom_fsub_img,
                    caption="**⚠️ Please join the channels below to get your file!**",
                    reply_markup=InlineKeyboardMarkup(not_joined_buttons),
                )
            else:
                await message.reply_text(
                    "**⚠️ Please join the channels below to get your file!**",
                    reply_markup=InlineKeyboardMarkup(not_joined_buttons),
                    disable_web_page_preview=True,
                )
        except UserIsBlocked:
            return False
        return False
    except Exception:
        return True


@Client.on_callback_query(filters.regex(r"^refresh_fsub_(.*)"))
async def refresh_fsub_callback(bot: Client, query: CallbackQuery):
    user_id, file_id = query.from_user.id, query.matches[0].group(1)

    if await is_vip(user_id):
        return await query.answer("👑 VIP Verified!", show_alert=False)

    config = await get_fsub_config()
    channels_dict = config.get("channels", {})
    rotation_enabled = config.get("rotation_enabled", False)
    max_count = config.get("max_count", 0)

    if not channels_dict:
        return await query.answer(
            "Force subscribe is no longer required.", show_alert=True
        )

    if rotation_enabled:
        eligible_channels = list(channels_dict.keys())
        if eligible_channels:
            shift = int(time.time() / 3600) % len(eligible_channels)
            eligible_channels = eligible_channels[shift:] + eligible_channels[:shift]
    else:
        eligible_channels = [
            k for k, v in channels_dict.items() if v.get("status") == "active"
        ]

    not_joined_buttons = []
    channels_to_force = 0

    for chat_id_str in eligible_channels:
        if max_count > 0 and channels_to_force >= max_count:
            break

        data = channels_dict[chat_id_str]
        is_req = data.get("type") == "req"
        is_participant = await check_user_in_channel(
            bot, int(chat_id_str), user_id, is_req
        )

        if not is_participant:
            link = await get_invite_link(bot, chat_id_str, config)
            if link:
                btn_text = "⚓ Request to Join" if is_req else "📢 Join Channel"
                not_joined_buttons.append(
                    [
                        InlineKeyboardButton(
                            btn_text, url=link, style=ButtonStyle.PRIMARY
                        )
                    ]
                )
                channels_to_force += 1

    if channels_to_force > 0:
        await query.answer(
            "❌ You haven't joined all required channels yet!", show_alert=True
        )
        # Visually update the buttons in case the 1-hour rotation shifted while they were looking at the menu
        cb_data = f"refresh_fsub_{file_id}" if file_id else "refresh_fsub_0"
        not_joined_buttons.append(
            [
                InlineKeyboardButton(
                    text="✅ I've Joined",
                    callback_data=cb_data,
                    style=ButtonStyle.SUCCESS,
                )
            ]
        )
        try:
            await query.message.edit_reply_markup(
                InlineKeyboardMarkup(not_joined_buttons)
            )
        except MessageNotModified:
            pass
    else:
        await _plugin_db.add_fsub_user(user_id)
        try:
            await query.message.delete()
        except Exception:
            pass

        await query.answer("✅ Subscriptions verified!", show_alert=False)

        if file_id and file_id != "0":
            try:
                await bot.send_cached_media(
                    chat_id=user_id,
                    file_id=file_id,
                    caption="🎉 **Thank you for joining! Here is your file:**",
                )
            except Exception:
                try:
                    await bot.send_message(
                        chat_id=user_id,
                        text="✅ **Verification complete!**\n\n⚠️ *The original file link expired. Please go back to the main group and click the file link again to get your movie!*",
                    )
                except Exception:
                    pass


# ============================================================
# 👑 VIP SYSTEM COMMANDS
# ============================================================
@Client.on_message(filters.command("addvip") & admin_filter)
async def cmd_addvip(bot: Client, message: Message):
    if message.reply_to_message:
        user_id = message.reply_to_message.from_user.id
    elif len(message.command) > 1:
        try:
            user_id = int(message.command[1])
        except ValueError:
            return await message.reply_text("❌ Invalid User ID.")
    else:
        return await message.reply_text(
            "⚠️ **Usage:** `/addvip <user_id>` or reply to a user."
        )

    await add_vip(user_id)
    await message.reply_text(
        f"👑 **User `{user_id}` added to VIP List!**\nThey will now bypass all Force Subscribe restrictions."
    )


@Client.on_message(filters.command("remvip") & admin_filter)
async def cmd_remvip(bot: Client, message: Message):
    if message.reply_to_message:
        user_id = message.reply_to_message.from_user.id
    elif len(message.command) > 1:
        try:
            user_id = int(message.command[1])
        except ValueError:
            return await message.reply_text("❌ Invalid User ID.")
    else:
        return await message.reply_text(
            "⚠️ **Usage:** `/remvip <user_id>` or reply to a user."
        )

    await rem_vip(user_id)
    await message.reply_text(f"🗑️ **User `{user_id}` removed from VIP List!**")


@Client.on_message(filters.command("viplist") & admin_filter)
async def cmd_viplist(bot: Client, message: Message):
    vips = await get_all_vips()
    if not vips:
        return await message.reply_text("ℹ️ **VIP List is empty.**")

    text = "👑 **ForceSub VIP List:**\n\n"
    for i, vip in enumerate(vips, 1):
        text += f"{i}. `{vip['user_id']}`\n"
    await message.reply_text(text)


# ============================================================
# ⚙️ CONFIGURATION COMMANDS
# ============================================================
@Client.on_message(filters.command("rotatefsub") & admin_filter)
async def toggle_rotate(bot: Client, message: Message):
    config = await get_fsub_config()
    current = config.get("rotation_enabled", False)
    await update_fsub_config("rotation_enabled", not current)
    status = (
        "🟢 ENABLED (Smart 1-Hour User Rotation)"
        if not current
        else "🔴 DISABLED (Static Priority)"
    )
    await message.reply_text(
        f"🔄 **Auto-Rotation Engine:** {status}\n\n*When enabled, the bot automatically cycles through all channels and forces users into the ones they haven't joined yet!*"
    )


@Client.on_message(filters.command("enablefsub") & admin_filter)
async def enable_fsub(bot: Client, message: Message):
    await update_fsub_config("is_enabled", True)
    await message.reply_text("✅ **Force Subscribe has been ENABLED.**")


@Client.on_message(filters.command("disablefsub") & admin_filter)
async def disable_fsub(bot: Client, message: Message):
    await update_fsub_config("is_enabled", False)
    await message.reply_text("❌ **Force Subscribe has been DISABLED.**")


@Client.on_message(filters.command("setfsubcount") & admin_filter)
async def set_fsub_count(bot: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text(
            "⚙️ **Usage:** `/setfsubcount [number]`\n*Set to 0 for unlimited active channels.*"
        )
    try:
        count = int(message.command[1])
        if count < 0:
            raise ValueError
        await update_fsub_config("max_count", count)
        limit_text = (
            f"maximum `{count}` active channels at once"
            if count > 0
            else "unlimited channels simultaneously"
        )
        await message.reply_text(
            f"✅ **FSub Queue Limit Updated!**\nThe system will now force a {limit_text}."
        )
    except ValueError:
        await message.reply_text(
            "❌ **Invalid number.** Please provide a valid positive integer."
        )


@Client.on_message(filters.command("setfsub") & admin_filter)
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
        ask_msg = await message.reply_text(
            f"🎯 **Target:** `{chat.title}`\n\nDo you want this to be a **Join Request** channel?\n\nReply with `y` for Yes, or `n` for No (Normal invite)."
        )
        resp = await native_listen(
            bot, message.chat.id, message.from_user.id, timeout=120
        )

        try:
            await ask_msg.delete()
        except Exception:
            pass
        if resp:
            try:
                await resp.delete()
            except Exception:
                pass

        if not resp or not resp.text:
            return await message.reply_text(
                "❌ **Invalid response.** Please send text (y/n)."
            )

        is_req = resp.text.lower() == "y"
        fsub_type = "req" if is_req else "regular"

        config = await get_fsub_config()
        channels = config.get("channels", {})
        max_count = config.get("max_count", 0)

        active_count = len(
            [c for c in channels.values() if c.get("status") == "active"]
        )
        status = "pending" if max_count > 0 and active_count >= max_count else "active"

        invite = await bot.create_chat_invite_link(chat.id, creates_join_request=is_req)

        channels[channel_id] = {
            "title": chat.title,
            "link": invite.invite_link,
            "target": None,
            "type": fsub_type,
            "status": status,
        }
        await update_fsub_channels(channels)

        await message.reply_text(
            f"✅ **Successfully Configured FSub!**\n\n📢 **Channel:** `{chat.title}`\n🔗 **Link:** {invite.invite_link}\n⚙️ **Type:** `{'Join Request' if is_req else 'Normal'}`\n🟢 **Status:** `{status.upper()}`",
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


@Client.on_message(filters.command("activatefsub") & admin_filter)
async def activate_fsub(bot: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text("⚙️ **Usage:** `/activatefsub [channel_id]`")
    channel_id = message.command[1]

    config = await get_fsub_config()
    channels = config.get("channels", {})
    max_count = config.get("max_count", 0)

    if channel_id not in channels:
        return await message.reply_text("❌ Channel not found in FSub database.")

    active_count = len([c for c in channels.values() if c.get("status") == "active"])
    if max_count > 0 and active_count >= max_count:
        return await message.reply_text(
            f"⚠️ **Queue Full!** You already have `{active_count}` active channels (Limit: {max_count}).\nUse `/deactivatefsub` on another channel first."
        )

    channels[channel_id]["status"] = "active"
    await update_fsub_channels(channels)
    await message.reply_text(f"✅ FSub for `{channel_id}` is now **ACTIVE**.")


@Client.on_message(filters.command("deactivatefsub") & admin_filter)
async def deactivate_fsub(bot: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text("⚙️ **Usage:** `/deactivatefsub [channel_id]`")
    channel_id = message.command[1]

    config = await get_fsub_config()
    channels = config.get("channels", {})

    if channel_id in channels:
        channels[channel_id]["status"] = "pending"
        await update_fsub_channels(channels)
        await message.reply_text(
            f"⏸ FSub for `{channel_id}` is now **PENDING (Deactivated)**."
        )
    else:
        await message.reply_text("❌ Channel not found in FSub database.")


@Client.on_message(filters.command("updatefsubtarget") & admin_filter)
async def update_fsub_target(bot: Client, message: Message):
    if len(message.command) < 3:
        return await message.reply_text(
            "⚙️ **Usage:** `/updatefsubtarget [channel_id] [target_link]`\n*Use 'none' to remove custom target.*"
        )
    channel_id, target = str(message.command[1]), message.command[2]

    config = await get_fsub_config()
    channels = config.get("channels", {})

    if channel_id not in channels:
        return await message.reply_text(
            f"❌ Channel `{channel_id}` is not configured in FSub."
        )

    if target.lower() == "none":
        channels[channel_id]["target"] = None
        await message.reply_text(
            "✅ Custom target removed. Bot will use standard invite link."
        )
    else:
        channels[channel_id]["target"] = target
        await message.reply_text(f"✅ Target for `{channel_id}` updated to:\n{target}")

    await update_fsub_channels(channels)


@Client.on_message(filters.command("rmfsub") & admin_filter)
async def rem_fsub(bot: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text("⚙️ **Usage:** `/rmfsub [channel_id]`")
    channel_id = message.command[1]

    config = await get_fsub_config()
    channels = config.get("channels", {})

    if channel_id in channels:
        del channels[channel_id]
        await update_fsub_channels(channels)
        await message.reply_text(
            f"🗑️ **ForceSub channel `{channel_id}` removed permanently.**"
        )
    else:
        await message.reply_text("❌ Channel not found in FSub database.")


@Client.on_message(filters.command("rmallfsub") & admin_filter)
async def rem_all_fsub(bot: Client, message: Message):
    await update_fsub_channels({})
    await message.reply_text(
        "🗑️ **ALL ForceSub channels have been removed and database is empty.**"
    )


async def build_fsub_list_text(title_prefix: str, filter_status: str = None) -> str:
    config = await get_fsub_config()
    channels_dict = config.get("channels", {})

    channels = channels_dict.items()
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


@Client.on_message(filters.command("getallfsub") & admin_filter)
async def get_all_fsub(bot: Client, message: Message):
    config = await get_fsub_config()
    max_count = config.get("max_count", 0)
    rot_status = "ON" if config.get("rotation_enabled", False) else "OFF"
    text = (
        f"⚙️ **Queue Limit:** `{max_count if max_count > 0 else 'Unlimited'}`\n🔄 **Auto-Rotation:** `{rot_status}`\n\n"
        + await build_fsub_list_text("All")
    )
    await message.reply_text(text, disable_web_page_preview=True)


@Client.on_message(filters.command("getactivefsub") & admin_filter)
async def get_active_fsub(bot: Client, message: Message):
    await message.reply_text(
        await build_fsub_list_text("Active", "active"), disable_web_page_preview=True
    )


@Client.on_message(filters.command("getpendingfsub") & admin_filter)
async def get_pending_fsub(bot: Client, message: Message):
    await message.reply_text(
        await build_fsub_list_text("Pending", "pending"), disable_web_page_preview=True
    )
