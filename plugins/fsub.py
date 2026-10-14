import asyncio
import time
from logging import ERROR, getLogger
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorClient
from pyrogram import Client, enums, filters
from pyrogram.errors import (
    ChatAdminRequired,
    FloodWait,
    MessageNotModified,
    PeerIdInvalid,
    QueryIdInvalid,
    UserIsBlocked,
    UserNotParticipant,
)
from pyrogram.types import (
    CallbackQuery,
    ChatJoinRequest,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

import info
from database.ia_filterdb import get_file_details
from database.join_reqs import join_reqs as _join_reqs_db
from database.plugin_dbs import plugin_db as _plugin_db
from plugins.custom_settings import get_bot_settings
from utils import get_size, parse_text_and_markup

logger = getLogger(__name__)
logger.setLevel(ERROR)

try:
    from pyrogram.enums import ButtonStyle

    BTN_PRIMARY = getattr(ButtonStyle, "PRIMARY", 1)
    BTN_SECONDARY = getattr(ButtonStyle, "SECONDARY", 2)
    BTN_SUCCESS = getattr(ButtonStyle, "SUCCESS", 3)
    BTN_DANGER = getattr(ButtonStyle, "DANGER", 4)
except ImportError:
    BTN_PRIMARY, BTN_SECONDARY, BTN_SUCCESS, BTN_DANGER = 1, 2, 3, 4


def create_btn(text, url=None, callback_data=None, style=None):
    kwargs = {"text": str(text)}
    if url:
        kwargs["url"] = str(url)
    elif callback_data:
        kwargs["callback_data"] = str(callback_data)
    if style is not None:
        kwargs["style"] = style
    try:
        return InlineKeyboardButton(**kwargs)
    except TypeError:
        kwargs.pop("style", None)
        return InlineKeyboardButton(**kwargs)


# ============================================================
# ⚙️ MONGODB PERMANENT FSUB & JOIN REQUEST ENGINE
# ============================================================
_fsub_db = None
_active_db = None
_fsub_reqs_db = None
_BOT_DB = None

try:
    _DB_CLIENT = AsyncIOMotorClient(info.DATABASE_URI)
    _BOT_DB = _DB_CLIENT[info.DATABASE_NAME]
    _fsub_db = _BOT_DB["fsub_config"]
    _active_db = _BOT_DB["active_connections"]
    _fsub_reqs_db = _BOT_DB["fsub_join_requests"]
except Exception as e:
    logger.error(f"Failed to init FSub DB: {e}")


async def get_fsub_config() -> dict:
    default_cfg = {
        "is_enabled": True,
        "max_count": 0,
        "rotation_enabled": False,
        "channels": {},
    }
    if _fsub_db is not None:
        try:
            doc = await _fsub_db.find_one({"_id": "config"})
            if doc:
                for k, v in default_cfg.items():
                    if k not in doc:
                        doc[k] = v
                return doc
        except Exception as e:
            logger.error(f"get_fsub_config error: {e}")
    return default_cfg


async def update_fsub_config(key: str, value):
    if _fsub_db is not None:
        await _fsub_db.update_one(
            {"_id": "config"}, {"$set": {key: value}}, upsert=True
        )


async def update_fsub_channels(channels_dict: dict):
    if _fsub_db is not None:
        await _fsub_db.update_one(
            {"_id": "config"}, {"$set": {"channels": channels_dict}}, upsert=True
        )


async def record_join_request(
    user_id: int, chat_id: int, first_name: str = "User", username: str = "None", date=None
):
    """Saves join requests in both native MongoDB and legacy join_reqs DB."""
    if _fsub_reqs_db is not None:
        try:
            await _fsub_reqs_db.update_one(
                {"user_id": int(user_id), "chat_id": int(chat_id)},
                {
                    "$set": {
                        "user_id": int(user_id),
                        "chat_id": int(chat_id),
                        "first_name": first_name,
                        "username": username,
                        "timestamp": time.time(),
                    }
                },
                upsert=True,
            )
        except Exception as e:
            logger.error(f"Native join request save error: {e}")

    try:
        if _join_reqs_db and _join_reqs_db.isActive():
            await _join_reqs_db.add_user(
                user_id=user_id,
                first_name=first_name,
                username=username,
                date=date,
            )
    except Exception:
        pass


async def has_join_request(user_id: int, chat_id: Optional[int] = None) -> bool:
    """Checks if a user has a recorded join request for the channel."""
    if _fsub_reqs_db is not None:
        try:
            if chat_id is not None:
                doc = await _fsub_reqs_db.find_one(
                    {"user_id": int(user_id), "chat_id": int(chat_id)}
                )
                if doc:
                    return True
            doc_any = await _fsub_reqs_db.find_one({"user_id": int(user_id)})
            if doc_any:
                return True
        except Exception:
            pass

    try:
        if _join_reqs_db and _join_reqs_db.isActive():
            if await _join_reqs_db.get_user(user_id):
                return True
    except Exception:
        pass
    return False


async def get_total_join_requests() -> int:
    total = 0
    if _fsub_reqs_db is not None:
        try:
            total = await _fsub_reqs_db.count_documents({})
        except Exception:
            pass
    try:
        if _join_reqs_db and _join_reqs_db.isActive():
            legacy_total = await _join_reqs_db.total_requests()
            total = max(total, int(legacy_total or 0))
    except Exception:
        pass
    return total


async def clear_all_join_requests() -> int:
    deleted = 0
    if _fsub_reqs_db is not None:
        try:
            res = await _fsub_reqs_db.delete_many({})
            deleted = getattr(res, "deleted_count", 0)
        except Exception:
            pass
    try:
        if _join_reqs_db and _join_reqs_db.isActive():
            await _join_reqs_db.clear_all()
    except Exception:
        pass
    return deleted


# ============================================================
# 👑 SMART AUTHORIZATION & CONNECTION ENGINE
# ============================================================
def get_admin_list():
    raw_admins = getattr(info, "ADMINS", [])
    if isinstance(raw_admins, (str, int)):
        raw_admins = str(raw_admins).replace(",", " ").split()
    return [int(x) for x in raw_admins if str(x).strip().lstrip("-").isdigit()]


async def is_global_admin(user_id: int) -> bool:
    return int(user_id) in get_admin_list()


async def get_active_connection(user_id: str) -> Optional[int]:
    uid_str = str(user_id)
    if _active_db is not None:
        try:
            doc = await _active_db.find_one({"user_id": uid_str})
            if doc and doc.get("group_id"):
                return int(doc["group_id"])
        except Exception:
            pass

    try:
        from database.connections_mdb import active_connection
        conn = await active_connection(uid_str)
        if conn:
            return int(conn)
    except Exception:
        pass

    try:
        from database.connections_mdb import all_connections, if_active
        groupids = await all_connections(uid_str)
        if groupids:
            for gid in groupids:
                if await if_active(uid_str, str(gid)):
                    return int(gid)
            return int(groupids[-1])
    except Exception:
        pass

    return None


async def get_target_chat(client: Client, message: Message) -> Optional[int]:
    if message.chat.type == enums.ChatType.PRIVATE:
        if not message.from_user:
            return None
        return await get_active_connection(str(message.from_user.id))
    return message.chat.id


async def verify_admin(
    client: Client, message: Message, target_chat_id: Optional[int] = None
) -> bool:
    uid = (
        message.from_user.id
        if message.from_user
        else getattr(message.sender_chat, "id", 0)
    )
    if await is_global_admin(uid):
        return True

    if message.chat.type == enums.ChatType.PRIVATE:
        if not target_chat_id:
            return False
        try:
            member = await client.get_chat_member(int(target_chat_id), uid)
            return member.status in [
                enums.ChatMemberStatus.ADMINISTRATOR,
                enums.ChatMemberStatus.OWNER,
            ]
        except Exception:
            return False

    if message.chat.type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
        if message.sender_chat and message.sender_chat.id == message.chat.id:
            return True
        if message.from_user:
            try:
                member = await client.get_chat_member(message.chat.id, uid)
                return member.status in [
                    enums.ChatMemberStatus.ADMINISTRATOR,
                    enums.ChatMemberStatus.OWNER,
                ]
            except Exception:
                return False
    return False


async def verify_cb_admin(client: Client, query: CallbackQuery) -> bool:
    uid = query.from_user.id if query.from_user else 0
    if await is_global_admin(uid):
        return True
    if query.message and query.message.chat:
        if query.message.chat.type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
            try:
                member = await client.get_chat_member(query.message.chat.id, uid)
                return member.status in [
                    enums.ChatMemberStatus.ADMINISTRATOR,
                    enums.ChatMemberStatus.OWNER,
                ]
            except Exception:
                return False
        elif query.message.chat.type == enums.ChatType.PRIVATE:
            conn_id = await get_active_connection(str(uid))
            if conn_id:
                try:
                    member = await client.get_chat_member(int(conn_id), uid)
                    return member.status in [
                        enums.ChatMemberStatus.ADMINISTRATOR,
                        enums.ChatMemberStatus.OWNER,
                    ]
                except Exception:
                    return False
    return False


# ============================================================
# 🔄 ASYNC NATIVE LISTENER ENGINE
# ============================================================
_WAITING_REQUESTS = {}


@Client.on_message(filters.group | filters.private, group=-12)
async def custom_listener(client: Client, message: Message):
    chat_id = message.chat.id
    if chat_id not in _WAITING_REQUESTS:
        return
    if (
        message.text
        and message.text.startswith("/")
        and message.text.strip().lower() not in ["/cancel"]
    ):
        return

    sender_id = (
        message.from_user.id
        if message.from_user
        else getattr(message.sender_chat, "id", 0)
    )
    expected_session_id = _WAITING_REQUESTS[chat_id]["session_id"]

    if sender_id == expected_session_id or sender_id == chat_id:
        future = _WAITING_REQUESTS[chat_id]["future"]
        if not future.done():
            future.set_result(message)
        message.stop_propagation()


async def native_listen(
    client: Client, chat_id: int, user_id: int, timeout: int = 120
) -> Message:
    if chat_id in _WAITING_REQUESTS:
        old_fut = _WAITING_REQUESTS[chat_id].get("future")
        if old_fut and not old_fut.done():
            old_fut.cancel()

    loop = asyncio.get_running_loop()
    future = loop.create_future()
    _WAITING_REQUESTS[chat_id] = {"future": future, "session_id": user_id}
    try:
        return await asyncio.wait_for(future, timeout=timeout)
    finally:
        if _WAITING_REQUESTS.get(chat_id, {}).get("future") is future:
            _WAITING_REQUESTS.pop(chat_id, None)


# ============================================================
# 🔗 INVITE LINK & USER CHECKING
# ============================================================
async def get_invite_link(bot: Client, chat_id_str: str, config: dict) -> str:
    channels = config.get("channels", {})
    channel_data = channels.get(chat_id_str, {})
    if channel_data.get("target"):
        return channel_data["target"]
    if channel_data.get("link"):
        return channel_data["link"]

    try:
        chat_id_int = int(str(chat_id_str).strip())
        chat = await bot.get_chat(chat_id_int)
        is_req = channel_data.get("type") == "req"
        try:
            invite = await bot.create_chat_invite_link(
                chat_id_int, creates_join_request=is_req
            )
            inv_link = invite.invite_link
        except Exception:
            inv_link = chat.invite_link or (
                f"https://t.me/{chat.username}" if chat.username else ""
            )

        if inv_link:
            if chat_id_str not in channels:
                channels[chat_id_str] = {
                    "title": chat.title or str(chat_id_int),
                    "link": inv_link,
                    "target": None,
                    "type": "req" if is_req else "regular",
                    "status": "active",
                }
            else:
                channels[chat_id_str]["link"] = inv_link
                channels[chat_id_str]["title"] = chat.title or str(chat_id_int)
            await update_fsub_channels(channels)
        return inv_link
    except (ChatAdminRequired, Exception) as e:
        logger.error(f"get_invite_link error for {chat_id_str}: {e}")
        return ""


async def check_user_in_channel(
    bot: Client, channel_id: int, user_id: int, is_req: bool = False
) -> bool:
    try:
        member = await bot.get_chat_member(int(channel_id), int(user_id))
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
        if await has_join_request(user_id, channel_id):
            return True
    return False


# ============================================================
# 🛑 MAIN FORCESUB INTERCEPTOR
# ============================================================
async def ForceSub(
    bot: Client, message: Message, file_id: str = None, mode: str = None
) -> bool:
    user = message.from_user
    if not user:
        return True
    if await is_global_admin(user.id):
        return True

    config = await get_fsub_config()
    if not config.get("is_enabled", True):
        return True

    channels_dict = config.get("channels", {})
    if not channels_dict:
        return True

    rotation_enabled = config.get("rotation_enabled", False)
    max_count = int(config.get("max_count", 0) or 0)

    if rotation_enabled:
        eligible_channels = list(channels_dict.keys())
        if eligible_channels:
            shift = int(time.time() / 3600) % len(eligible_channels)
            eligible_channels = eligible_channels[shift:] + eligible_channels[:shift]
    else:
        eligible_channels = [
            k for k, v in channels_dict.items() if v.get("status", "active") == "active"
        ]

    not_joined_buttons = []
    channels_to_force = 0

    try:
        for chat_id_str in eligible_channels:
            if max_count > 0 and channels_to_force >= max_count:
                break
            data = channels_dict.get(chat_id_str, {})
            is_req = data.get("type") == "req"

            if not await check_user_in_channel(bot, int(chat_id_str), user.id, is_req):
                if link := await get_invite_link(bot, chat_id_str, config):
                    btn_text = "⚓ Request to Join" if is_req else "📢 Join Channel"
                    not_joined_buttons.append(
                        [create_btn(btn_text, url=link, style=BTN_PRIMARY)]
                    )
                    channels_to_force += 1

        if not not_joined_buttons:
            await _plugin_db.add_fsub_user(user.id)
            return True

        safe_mode = mode or "checksub"
        safe_fid = file_id or "0"
        cb_data = f"refresh_fsub#{safe_mode}#{safe_fid}"
        not_joined_buttons.append(
            [create_btn(text="✅ I've Joined", callback_data=cb_data, style=BTN_SUCCESS)]
        )

        b_settings = await get_bot_settings()
        custom_fsub_img = b_settings.get("fsub_img", getattr(info, "FSUB_IMG", None))
        fsub_caption = "<b>⚠️ Please join the channels below to get your file!</b>"

        try:
            if custom_fsub_img:
                await message.reply_photo(
                    photo=custom_fsub_img,
                    caption=fsub_caption,
                    reply_markup=InlineKeyboardMarkup(not_joined_buttons),
                    parse_mode=enums.ParseMode.HTML,
                )
            else:
                await message.reply_text(
                    fsub_caption,
                    reply_markup=InlineKeyboardMarkup(not_joined_buttons),
                    disable_web_page_preview=True,
                    parse_mode=enums.ParseMode.HTML,
                )
        except (UserIsBlocked, PeerIdInvalid):
            return False
        except Exception:
            await message.reply_text(
                fsub_caption,
                reply_markup=InlineKeyboardMarkup(not_joined_buttons),
                disable_web_page_preview=True,
                parse_mode=enums.ParseMode.HTML,
            )
        return False
    except Exception as e:
        logger.error(f"ForceSub error: {e}")
        return True


async def _deliver_verified_file(
    bot: Client, user_id: int, chat_id: int, file_id: str, mode: str = "checksub"
):
    """Fetches full file details and sends the file with proper caption and auto-delete."""
    if not file_id or file_id == "0":
        return

    protect = mode in ["filep", "checksubp"]
    files_ = await get_file_details(file_id)

    if files_:
        files = files_[0]
        title = str(
            files.get("file_name", "Unknown")
            if isinstance(files, dict)
            else getattr(files, "file_name", "Unknown")
        )
        size = get_size(
            int(
                files.get("file_size", 0)
                if isinstance(files, dict)
                else getattr(files, "file_size", 0)
            )
        )
        f_caption = str(
            files.get("caption", "")
            if isinstance(files, dict)
            else getattr(files, "caption", "")
        )
        db_file_id = (
            files.get("full_file_id", files.get("file_id", file_id))
            if isinstance(files, dict)
            else getattr(files, "full_file_id", getattr(files, "file_id", file_id))
        )

        custom_cap = getattr(info, "CUSTOM_FILE_CAPTION", None)
        if custom_cap:
            try:
                f_caption = custom_cap.format(
                    file_name="" if title == "Unknown" else title,
                    file_size="" if size == "0B" else size,
                    file_caption="" if not f_caption else f_caption,
                )
            except Exception:
                pass

        if not f_caption:
            f_caption = f"<b>{title}</b>"
        elif not f_caption.strip().startswith("<b>"):
            f_caption = f"<b>{f_caption}</b>"

        if getattr(info, "CAPTION_PLUS", None):
            f_caption += f"\n\n{info.CAPTION_PLUS}"

        final_caption, final_keyboard = parse_text_and_markup(
            f_caption,
            InlineKeyboardMarkup(
                [
                    [
                        create_btn(
                            text="🎥 ಕನ್ನಡ ಹೊಸ ಮೂವೀಗಳು 🎥",
                            url="https://t.me/sandalwood_kannada_moviesz",
                            style=BTN_SUCCESS,
                        )
                    ]
                ]
            ),
        )
    else:
        db_file_id = file_id
        final_caption = "<b>🎉 Thank you for joining! Here is your file:</b>"
        final_keyboard = InlineKeyboardMarkup(
            [
                [
                    create_btn(
                        text="🎥 ಕನ್ನಡ ಹೊಸ ಮೂವೀಗಳು 🎥",
                        url="https://t.me/sandalwood_kannada_moviesz",
                        style=BTN_SUCCESS,
                    )
                ]
            ]
        )

    sent_msg = None
    try:
        sent_msg = await bot.send_cached_media(
            chat_id=user_id,
            file_id=db_file_id,
            caption=final_caption,
            reply_markup=final_keyboard,
            protect_content=protect,
            parse_mode=enums.ParseMode.HTML,
        )
    except FloodWait as e:
        await asyncio.sleep(e.value + 1)
        try:
            sent_msg = await bot.send_cached_media(
                chat_id=user_id,
                file_id=db_file_id,
                caption=final_caption,
                reply_markup=final_keyboard,
                protect_content=protect,
                parse_mode=enums.ParseMode.HTML,
            )
        except Exception:
            pass
    except Exception:
        try:
            sent_msg = await bot.send_document(
                chat_id=user_id,
                document=db_file_id,
                caption=final_caption,
                reply_markup=final_keyboard,
                protect_content=protect,
                parse_mode=enums.ParseMode.HTML,
            )
        except Exception:
            await bot.send_message(
                chat_id=user_id,
                text="✅ <b>Verification complete!</b>\n\n⚠️ <i>Please click the file link again to receive your movie.</i>",
                parse_mode=enums.ParseMode.HTML,
            )
            return

    if sent_msg:
        try:
            from plugins.pm_filter import format_duration, get_auto_delete_timer, schedule_auto_delete

            delete_timer = get_auto_delete_timer("FILE_AUTO_DELETE", 1800)
            if delete_timer > 0:
                time_str = format_duration(delete_timer)
                warn_text = (
                    f"<b>📢 Please Note\n\n"
                    f"✅ The above file will be autodeleted in {time_str} to avoid copyright issues.\n\n"
                    f"✅ Please forward this file to your saved messages and start downloading from there.\n\n"
                    f"Tᴇᴀᴍ: @KR_Picture</b>"
                )
                warn_msg = await bot.send_message(
                    chat_id=user_id,
                    text=warn_text,
                    reply_to_message_id=sent_msg.id,
                    parse_mode=enums.ParseMode.HTML,
                )
                schedule_auto_delete(
                    bot, chat_id, True, delete_timer, sent_msg, warn_msg
                )
        except Exception as e:
            logger.error(f"FSub auto-delete schedule error: {e}")


@Client.on_callback_query(filters.regex(r"^refresh_fsub"), group=-3)
async def refresh_fsub_callback(bot: Client, query: CallbackQuery):
    user_id = query.from_user.id if query.from_user else 0
    data = query.data

    mode = "checksub"
    file_id = "0"
    if data.startswith("refresh_fsub#"):
        parts = data.split("#", 2)
        if len(parts) == 3:
            _, mode, file_id = parts
    elif data.startswith("refresh_fsub_"):
        file_id = data.replace("refresh_fsub_", "", 1)

    config = await get_fsub_config()
    channels_dict = config.get("channels", {})
    rotation_enabled = config.get("rotation_enabled", False)
    max_count = int(config.get("max_count", 0) or 0)

    if not await is_global_admin(user_id) and channels_dict:
        if rotation_enabled:
            eligible_channels = list(channels_dict.keys())
            if eligible_channels:
                shift = int(time.time() / 3600) % len(eligible_channels)
                eligible_channels = eligible_channels[shift:] + eligible_channels[:shift]
        else:
            eligible_channels = [
                k
                for k, v in channels_dict.items()
                if v.get("status", "active") == "active"
            ]

        not_joined_buttons = []
        channels_to_force = 0

        for chat_id_str in eligible_channels:
            if max_count > 0 and channels_to_force >= max_count:
                break
            ch_data = channels_dict.get(chat_id_str, {})
            is_req = ch_data.get("type") == "req"
            if not await check_user_in_channel(
                bot, int(chat_id_str), user_id, is_req
            ):
                if link := await get_invite_link(bot, chat_id_str, config):
                    btn_text = "⚓ Request to Join" if is_req else "📢 Join Channel"
                    not_joined_buttons.append(
                        [create_btn(btn_text, url=link, style=BTN_PRIMARY)]
                    )
                    channels_to_force += 1

        if channels_to_force > 0:
            await query.answer(
                "❌ You haven't joined all required channels yet!", show_alert=True
            )
            cb_data = f"refresh_fsub#{mode}#{file_id}"
            not_joined_buttons.append(
                [
                    create_btn(
                        text="✅ I've Joined",
                        callback_data=cb_data,
                        style=BTN_SUCCESS,
                    )
                ]
            )
            try:
                await query.message.edit_reply_markup(
                    InlineKeyboardMarkup(not_joined_buttons)
                )
            except MessageNotModified:
                pass
            return

    await _plugin_db.add_fsub_user(user_id)
    try:
        await query.answer("✅ Subscriptions verified!", show_alert=False)
    except QueryIdInvalid:
        pass

    try:
        await query.message.delete()
    except Exception:
        pass

    await _deliver_verified_file(
        bot, user_id, query.message.chat.id, file_id, mode
    )


# ============================================================
# ⚙️ CONFIGURATION COMMANDS & INTERACTIVE BUTTONS
# ============================================================
@Client.on_message(filters.command("rotatefsub"), group=-3)
async def toggle_rotate(bot: Client, message: Message):
    target_chat_id = await get_target_chat(bot, message)
    if not await verify_admin(bot, message, target_chat_id):
        return await message.reply_text("❌ **Unauthorized:** Admin only.")

    config = await get_fsub_config()
    current = config.get("rotation_enabled", False)
    await update_fsub_config("rotation_enabled", not current)
    status = (
        "🟢 ENABLED (Smart 1-Hour User Rotation)"
        if not current
        else "🔴 DISABLED (Static Priority)"
    )
    await message.reply_text(
        f"🔄 **Auto-Rotation Engine:** {status}\n\n"
        f"*When enabled, the bot automatically cycles through all channels and forces users into the ones they haven't joined yet!*"
    )


@Client.on_message(filters.command("enablefsub"), group=-3)
async def enable_fsub(bot: Client, message: Message):
    target_chat_id = await get_target_chat(bot, message)
    if not await verify_admin(bot, message, target_chat_id):
        return await message.reply_text("❌ **Unauthorized:** Admin only.")

    await update_fsub_config("is_enabled", True)
    await message.reply_text("✅ **Force Subscribe has been ENABLED.**")


@Client.on_message(filters.command("disablefsub"), group=-3)
async def disable_fsub(bot: Client, message: Message):
    target_chat_id = await get_target_chat(bot, message)
    if not await verify_admin(bot, message, target_chat_id):
        return await message.reply_text("❌ **Unauthorized:** Admin only.")

    await update_fsub_config("is_enabled", False)
    await message.reply_text("❌ **Force Subscribe has been DISABLED.**")


async def _finalize_setfsub(
    bot: Client, chat_id: int, channel_id: str, is_req: bool
) -> Tuple[bool, str]:
    try:
        chat = await bot.get_chat(int(channel_id))
        fsub_type = "req" if is_req else "regular"

        config = await get_fsub_config()
        channels = config.get("channels", {})
        max_count = int(config.get("max_count", 0) or 0)
        active_count = len(
            [c for c in channels.values() if c.get("status") == "active"]
        )
        status = "pending" if max_count > 0 and active_count >= max_count else "active"

        invite = await bot.create_chat_invite_link(
            chat.id, creates_join_request=is_req
        )

        channels[str(chat.id)] = {
            "title": chat.title or str(chat.id),
            "link": invite.invite_link,
            "target": None,
            "type": fsub_type,
            "status": status,
        }
        await update_fsub_channels(channels)

        msg = (
            f"✅ **Successfully Configured FSub!**\n\n"
            f"📢 **Channel:** `{chat.title}`\n"
            f"🆔 **ID:** `{chat.id}`\n"
            f"🔗 **Link:** {invite.invite_link}\n"
            f"⚙️ **Type:** `{'Join Request' if is_req else 'Normal'}`\n"
            f"🟢 **Status:** `{status.upper()}`"
        )
        return True, msg
    except ChatAdminRequired:
        return (
            False,
            "❌ **The bot is not an admin in that channel or lacks 'Invite Users' rights.**",
        )
    except Exception as e:
        return False, f"❌ **Error:** `{e}`"


@Client.on_message(filters.command("setfsub"), group=-3)
async def add_dynamic_fsub(bot: Client, message: Message):
    target_chat_id = await get_target_chat(bot, message)
    if not await verify_admin(bot, message, target_chat_id):
        return await message.reply_text("❌ **Unauthorized:** Admin only.")

    if len(message.command) < 2:
        return await message.reply_text(
            "⚙️ **Usage:** `/setfsub <channel_id>`\nExample: `/setfsub -1001234567890`"
        )

    channel_id = message.command[1].strip()
    try:
        chat = await bot.get_chat(
            int(channel_id) if channel_id.lstrip("-").isdigit() else channel_id
        )
        channel_id = str(chat.id)
    except Exception as e:
        return await message.reply_text(
            f"❌ **Failed to fetch channel.** Make sure the bot is an admin in `{channel_id}`.\n`Error: {e}`"
        )

    # If user passed y/n or req/normal directly: /setfsub -10012345 y
    if len(message.command) >= 3:
        arg2 = message.command[2].strip().lower()
        is_req = arg2 in ["y", "yes", "req", "request", "true"]
        _, result_text = await _finalize_setfsub(
            bot, message.chat.id, channel_id, is_req
        )
        return await message.reply_text(result_text, disable_web_page_preview=True)

    buttons = [
        [
            create_btn(
                "⚓ Join Request (Yes)",
                callback_data=f"fsub_setup#req#{channel_id}",
                style=BTN_SUCCESS,
            ),
            create_btn(
                "📢 Normal Invite (No)",
                callback_data=f"fsub_setup#reg#{channel_id}",
                style=BTN_PRIMARY,
            ),
        ],
        [
            create_btn(
                "❌ Cancel",
                callback_data="fsub_setup#cancel#0",
                style=BTN_DANGER,
            )
        ],
    ]

    ask_msg = await message.reply_text(
        f"🎯 **Target:** `{chat.title}` (`{channel_id}`)\n\n"
        f"Do you want this to be a **Join Request** channel?\n\n"
        f"👉 **Click a button below** *(or reply with `y` for Yes / `n` for No)*:",
        reply_markup=InlineKeyboardMarkup(buttons),
    )

    try:
        user_id = (
            message.from_user.id
            if message.from_user
            else getattr(message.sender_chat, "id", 0)
        )
        resp = await native_listen(bot, message.chat.id, user_id, timeout=60)
        if not resp or not resp.text:
            return
        txt = resp.text.strip().lower()
        if txt == "/cancel":
            try:
                await ask_msg.edit_text("❌ **FSub setup cancelled.**")
            except Exception:
                pass
            return
        if txt in ["y", "yes", "n", "no"]:
            is_req = txt in ["y", "yes"]
            try:
                await resp.delete()
            except Exception:
                pass
            _, result_text = await _finalize_setfsub(
                bot, message.chat.id, channel_id, is_req
            )
            try:
                await ask_msg.edit_text(result_text, disable_web_page_preview=True)
            except Exception:
                await message.reply_text(result_text, disable_web_page_preview=True)
    except asyncio.TimeoutError:
        pass
    except asyncio.CancelledError:
        pass


@Client.on_callback_query(
    filters.regex(r"^(fsub_setup#|fsub_purge#|fsub_del#)"), group=-3
)
async def fsub_admin_callbacks(bot: Client, query: CallbackQuery):
    if not await verify_cb_admin(bot, query):
        return await query.answer("❌ Unauthorized: Admin only.", show_alert=True)

    data = query.data
    # Cancel any active text listener in this chat so it doesn't stay open
    if query.message.chat.id in _WAITING_REQUESTS:
        fut = _WAITING_REQUESTS[query.message.chat.id].get("future")
        if fut and not fut.done():
            fut.cancel()
        _WAITING_REQUESTS.pop(query.message.chat.id, None)

    if data.startswith("fsub_setup#"):
        _, mode, channel_id = data.split("#", 2)
        if mode == "cancel":
            await query.answer("Cancelled.")
            return await query.message.edit_text("❌ **FSub setup cancelled.**")

        await query.answer("⏳ Configuring FSub channel...")
        is_req = mode == "req"
        _, result_text = await _finalize_setfsub(
            bot, query.message.chat.id, channel_id, is_req
        )
        return await query.message.edit_text(
            result_text, disable_web_page_preview=True
        )

    if data.startswith("fsub_del#"):
        _, channel_id = data.split("#", 1)
        config = await get_fsub_config()
        channels = config.get("channels", {})
        if channel_id in channels:
            del channels[channel_id]
            await update_fsub_channels(channels)
            await query.answer("🗑️ Channel removed!", show_alert=True)
            text, markup = await build_fsub_list_ui("All")
            return await query.message.edit_text(
                text, reply_markup=markup, disable_web_page_preview=True
            )
        return await query.answer("Channel already removed.", show_alert=True)

    if data.startswith("fsub_purge#"):
        _, action = data.split("#", 1)
        if action == "cancel":
            await query.answer("Cancelled.")
            return await query.message.edit_text("❌ **Operation cancelled.**")
        if action == "confirm":
            count = await clear_all_join_requests()
            await query.answer("✅ Join requests purged!", show_alert=True)
            return await query.message.edit_text(
                f"✅ **All join requests purged successfully!** (`{count}` deleted)"
            )


@Client.on_message(filters.command("rmfsub"), group=-3)
async def rem_fsub(bot: Client, message: Message):
    target_chat_id = await get_target_chat(bot, message)
    if not await verify_admin(bot, message, target_chat_id):
        return await message.reply_text("❌ **Unauthorized:** Admin only.")

    if len(message.command) < 2:
        return await message.reply_text("⚙️ **Usage:** `/rmfsub <channel_id>`")
    channel_id = message.command[1].strip()

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


@Client.on_message(filters.command("rmallfsub"), group=-3)
async def rem_all_fsub(bot: Client, message: Message):
    target_chat_id = await get_target_chat(bot, message)
    if not await verify_admin(bot, message, target_chat_id):
        return await message.reply_text("❌ **Unauthorized:** Admin only.")

    await update_fsub_channels({})
    await message.reply_text(
        "🗑️ **ALL ForceSub channels have been removed and database is empty.**"
    )


async def build_fsub_list_ui(
    title_prefix: str = "All", filter_status: str = None
) -> Tuple[str, Optional[InlineKeyboardMarkup]]:
    config = await get_fsub_config()
    channels_dict = config.get("channels", {})
    max_count = config.get("max_count", 0)
    rot_status = "ON" if config.get("rotation_enabled", False) else "OFF"
    fsub_enabled = "🟢 ENABLED" if config.get("is_enabled", True) else "🔴 DISABLED"

    channels = list(channels_dict.items())
    if filter_status:
        channels = [
            (k, v) for k, v in channels if v.get("status") == filter_status
        ]

    header = (
        f"📡 **Force Subscribe Status:** {fsub_enabled}\n"
        f"⚙️ **Queue Limit:** `{max_count if max_count > 0 else 'Unlimited'}`\n"
        f"🔄 **Auto-Rotation:** `{rot_status}`\n\n"
    )

    if not channels:
        return (
            header + f"❌ No {title_prefix.lower()} ForceSub channels configured.",
            None,
        )

    text = header + f"📋 **{title_prefix} ForceSub Channels ({len(channels)}):**\n\n"
    buttons = []
    for idx, (cid, data) in enumerate(channels, 1):
        status_emoji = "🟢" if data.get("status", "active") == "active" else "🟡"
        req_type = "Join Request" if data.get("type") == "req" else "Normal"
        title_str = data.get("title", "Unknown")
        active_link = data.get("target") or data.get("link") or "No Link Generated"
        text += (
            f"{idx}. {status_emoji} **{title_str}**\n"
            f"├ ID: `{cid}`\n"
            f"├ Type: `{req_type}`\n"
            f"└ Link: {active_link}\n\n"
        )
        buttons.append(
            [
                create_btn(
                    f"🗑️ Remove {title_str[:20]}",
                    callback_data=f"fsub_del#{cid}",
                    style=BTN_DANGER,
                )
            ]
        )

    return text, (InlineKeyboardMarkup(buttons) if buttons else None)


@Client.on_message(filters.command(["getallfsub", "fsub"]), group=-3)
async def get_all_fsub(bot: Client, message: Message):
    target_chat_id = await get_target_chat(bot, message)
    if not await verify_admin(bot, message, target_chat_id):
        return await message.reply_text("❌ **Unauthorized:** Admin only.")

    text, markup = await build_fsub_list_ui("All")
    await message.reply_text(
        text, reply_markup=markup, disable_web_page_preview=True
    )


# ============================================================
# 🚪 JOIN REQUEST CATCHER (WORKS FOR ALL DYNAMIC FSUB CHANNELS)
# ============================================================
@Client.on_chat_join_request(group=-3)
async def join_reqs_handler(bot: Client, join_req: ChatJoinRequest):
    user = join_req.from_user
    if not user or not join_req.chat:
        return
    try:
        await record_join_request(
            user_id=user.id,
            chat_id=join_req.chat.id,
            first_name=user.first_name or "Unknown",
            username=user.username or "None",
            date=join_req.date,
        )
    except Exception as e:
        logger.error(f"Failed to log join request for {user.id}: {e}")


# ============================================================
# 📊 JOIN REQUEST COMMANDS
# ============================================================
@Client.on_message(filters.command("totalrequests"), group=-3)
async def total_requests(bot: Client, message: Message):
    target_chat_id = await get_target_chat(bot, message)
    if not await verify_admin(bot, message, target_chat_id):
        return await message.reply_text("❌ **Unauthorized:** Admin only.")

    try:
        total = await get_total_join_requests()
        await message.reply_text(
            f"📨 **Total Join Requests:** <code>{total}</code>",
            parse_mode=enums.ParseMode.HTML,
        )
    except Exception as e:
        await message.reply_text(
            f"⚠️ Error: <code>{e}</code>", parse_mode=enums.ParseMode.HTML
        )


@Client.on_message(filters.command("purgerequests"), group=-3)
async def purge_requests(bot: Client, message: Message):
    target_chat_id = await get_target_chat(bot, message)
    if not await verify_admin(bot, message, target_chat_id):
        return await message.reply_text("❌ **Unauthorized:** Admin only.")

    buttons = [
        [
            create_btn(
                "🔥 Yes, Purge All Requests",
                callback_data="fsub_purge#confirm",
                style=BTN_DANGER,
            )
        ],
        [
            create_btn(
                "❌ Cancel",
                callback_data="fsub_purge#cancel",
                style=BTN_PRIMARY,
            )
        ],
    ]

    ask_msg = await message.reply_text(
        "⚠️ **Are you sure you want to delete all join requests?**\n\n"
        "👉 *Click a button below or reply with `y` / `n`:*",
        reply_markup=InlineKeyboardMarkup(buttons),
    )

    try:
        user_id = (
            message.from_user.id
            if message.from_user
            else getattr(message.sender_chat, "id", 0)
        )
        resp = await native_listen(bot, message.chat.id, user_id, timeout=60)
        if not resp or not resp.text:
            return
        try:
            await resp.delete()
        except Exception:
            pass

        if resp.text.strip().lower() in ["y", "yes"]:
            count = await clear_all_join_requests()
            await ask_msg.edit_text(
                f"✅ **All join requests purged successfully!** (`{count}` deleted)"
            )
        else:
            await ask_msg.edit_text("❌ **Operation cancelled.**")
    except (asyncio.TimeoutError, asyncio.CancelledError):
        pass
    except Exception as e:
        await message.reply_text(f"⚠️ Error clearing requests: `{e}`")
