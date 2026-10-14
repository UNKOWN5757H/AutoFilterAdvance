import asyncio
import re
from logging import ERROR, getLogger

from motor.motor_asyncio import AsyncIOMotorClient
from pyrogram import Client, enums, filters
from pyrogram.errors import ChatAdminRequired, FloodWait, MessageNotModified
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

import info
from database.users_chats_db import db as _db
from Script import script
from utils import get_settings, parse_text_and_markup, temp

try:
    from plugins.custom_settings import get_group_welcome
except ImportError:
    get_group_welcome = None

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


# Fallback MongoDB connection for welcome settings if needed
_g_welcome_db = None
try:
    _DB_CLIENT = AsyncIOMotorClient(info.DATABASE_URI)
    _BOT_DB = _DB_CLIENT[info.DATABASE_NAME]
    _g_welcome_db = _BOT_DB["group_welcome_settings"]
except Exception as e:
    logger.error(f"p_ttishow DB init error: {e}")


async def safe_get_group_welcome(chat_id: int) -> dict:
    if get_group_welcome is not None:
        try:
            res = await get_group_welcome(chat_id)
            if isinstance(res, dict):
                return res
        except Exception:
            pass
    if _g_welcome_db is not None:
        try:
            doc = await _g_welcome_db.find_one({"_id": int(chat_id)})
            return doc or {}
        except Exception:
            pass
    return {}


class SafeFormatDict(dict):
    def __missing__(self, key):
        return "{" + key + "}"


# ============================================================
# 👑 SMART AUTHORIZATION ENGINE (GLOBAL + CHAT + ANONYMOUS)
# ============================================================
def get_admin_list():
    raw_admins = getattr(info, "ADMINS", [])
    if isinstance(raw_admins, (str, int)):
        raw_admins = str(raw_admins).replace(",", " ").split()
    return [int(x) for x in raw_admins if str(x).strip().lstrip("-").isdigit()]


async def is_global_admin(user_id: int) -> bool:
    return int(user_id) in get_admin_list()


async def is_message_global_admin(message: Message) -> bool:
    admin_list = get_admin_list()
    if message.from_user and message.from_user.id in admin_list:
        return True
    if message.sender_chat and message.sender_chat.id in admin_list:
        return True
    return False


async def is_user_admin(client: Client, message: Message) -> bool:
    if await is_message_global_admin(message):
        return True

    if message.chat and message.chat.type in [
        enums.ChatType.GROUP,
        enums.ChatType.SUPERGROUP,
    ]:
        # Group anonymous admin or linked discussion channel
        if message.sender_chat:
            if message.sender_chat.id == message.chat.id:
                return True
            if getattr(message, "is_automatic_forward", False):
                return True

        if message.from_user:
            try:
                member = await client.get_chat_member(
                    message.chat.id, message.from_user.id
                )
                return member.status in [
                    enums.ChatMemberStatus.ADMINISTRATOR,
                    enums.ChatMemberStatus.OWNER,
                ]
            except Exception:
                pass

    return False


# ============================================================
# 🛡️ ADMIN GROUP GATEKEEPER & LINK PROTECTOR
# ============================================================
TELEGRAM_LINK_PATTERN = re.compile(
    r"(https?://)?(www\.)?(t(elegram)?\.(me|dog)|telegram\.org)/(joinchat/|\+|[a-zA-Z0-9_]+)",
    re.IGNORECASE,
)


def is_external_channel_forward(message: Message) -> bool:
    """Detects channel forwards across both standard Pyrogram and Layer 230+."""
    if getattr(message, "is_automatic_forward", False):
        return False

    if (
        getattr(message, "forward_from_chat", None)
        and message.forward_from_chat.type == enums.ChatType.CHANNEL
    ):
        return True

    origin = getattr(message, "forward_origin", None)
    if origin and getattr(origin, "chat", None):
        if origin.chat.type == enums.ChatType.CHANNEL:
            return True

    return False


async def _delete_warning_later(msg: Message, delay: int = 8):
    await asyncio.sleep(delay)
    try:
        await msg.delete()
    except Exception:
        pass


@Client.on_message(filters.group & ~filters.service & ~filters.bot, group=-4)
async def group_gatekeeper_and_link_protector(bot: Client, message: Message):
    # Bypass protector for Global Admins, Group Admins, and Anonymous Admins
    if await is_user_admin(bot, message):
        return

    text = message.text or message.caption or ""
    mention = message.from_user.mention if message.from_user else "User"

    # 1. Check for unauthorized Telegram channel / invite links
    if text and TELEGRAM_LINK_PATTERN.search(text):
        try:
            await message.delete()
            warning = await bot.send_message(
                message.chat.id,
                f"⚠️ **Link Deleted!** {mention}, unauthorized links are not permitted in this group.",
            )
            asyncio.create_task(_delete_warning_later(warning, 8))
            message.stop_propagation()
        except Exception:
            pass
        return

    # 2. Check for spammed forward headers from external channels
    if is_external_channel_forward(message):
        try:
            await message.delete()
            warning = await bot.send_message(
                message.chat.id,
                f"⚠️ **Channel Forward Blocked!** {mention}, forwarding messages from external channels is prohibited.",
            )
            asyncio.create_task(_delete_warning_later(warning, 8))
            message.stop_propagation()
        except Exception:
            pass
        return


# ============================================================
# 👥 WELCOME SYSTEM & CHAT LIFECYCLE
# ============================================================
@Client.on_message(filters.command("start") & filters.private, group=-3)
async def start_about_interceptor(bot: Client, message: Message):
    """Handles ?start=about deep-link from the group welcome message so it never shows 'No such file exists'."""
    if len(message.command) == 2 and message.command[1].strip().lower() == "about":
        mention = message.from_user.mention if message.from_user else "User"
        bname = temp.B_NAME or (await bot.get_me()).first_name or "MovieBot"
        raw_text = getattr(script, "ABOUT_TXT", "<b>About Bot</b>").format(
            mention=mention, bname=bname
        )
        kb = InlineKeyboardMarkup(
            [
                [
                    create_btn("🏘 Hᴏᴍᴇ", callback_data="start", style=BTN_SUCCESS),
                    create_btn("ℹ️ Hᴇʟᴘ", callback_data="help", style=BTN_PRIMARY),
                    create_btn("🔐 Cʟᴏsᴇ", callback_data="close_data", style=BTN_DANGER),
                ]
            ]
        )
        final_text, final_kb = parse_text_and_markup(raw_text, kb)
        img = getattr(info, "ABOUT_IMG", None)
        if img:
            try:
                await message.reply_photo(
                    photo=img,
                    caption=final_text,
                    reply_markup=final_kb,
                    parse_mode=enums.ParseMode.HTML,
                )
                message.stop_propagation()
                return
            except Exception:
                pass
        await message.reply_text(
            text=final_text,
            reply_markup=final_kb,
            parse_mode=enums.ParseMode.HTML,
        )
        message.stop_propagation()


@Client.on_message(filters.new_chat_members & filters.group, group=-3)
async def save_group(bot: Client, message: Message):
    if not message.new_chat_members:
        return

    bot_id = temp.ME
    if not bot_id:
        me = await bot.get_me()
        bot_id = me.id
        temp.ME = me.id
        temp.U_NAME = me.username
        temp.B_NAME = me.first_name

    new_member_ids = [u.id for u in message.new_chat_members]

    # 1. If the Bot itself was added to the group
    if bot_id in new_member_ids:
        chat_doc = await _db.get_chat(message.chat.id)
        if not chat_doc:
            try:
                total = await bot.get_chat_members_count(message.chat.id)
            except Exception:
                total = "Unknown"
            added_by = message.from_user.mention if message.from_user else "Anonymous"
            log_chan = getattr(info, "LOG_CHANNEL", None)
            if log_chan:
                try:
                    await bot.send_message(
                        int(log_chan),
                        script.LOG_TEXT_G.format(
                            message.chat.title, message.chat.id, total, added_by
                        ),
                    )
                except Exception:
                    pass
            await _db.add_chat(message.chat.id, message.chat.title)

        is_disabled_db = bool(chat_doc and chat_doc.get("is_disabled"))
        if message.chat.id in getattr(temp, "BANNED_CHATS", []) or is_disabled_db:
            support = getattr(info, "SUPPORT_CHAT", "")
            btn = (
                [
                    [
                        create_btn(
                            "🤖 Contact Support",
                            url=f"https://t.me/{support.lstrip('@')}",
                            style=BTN_DANGER,
                        )
                    ]
                ]
                if support
                else []
            )
            try:
                await message.reply_text(
                    "<b>🚫 This chat is restricted!\nMy admins have disabled me here.</b>",
                    reply_markup=InlineKeyboardMarkup(btn) if btn else None,
                    parse_mode=enums.ParseMode.HTML,
                )
            except Exception:
                pass
            try:
                await bot.leave_chat(message.chat.id)
            except Exception:
                pass
            return

        bot_user = temp.U_NAME or (await bot.get_me()).username
        btn = [
            [
                create_btn(
                    "ℹ️ Help",
                    url=f"https://t.me/{bot_user}?start=help",
                    style=BTN_PRIMARY,
                ),
                create_btn(
                    "📖 About",
                    url=f"https://t.me/{bot_user}?start=about",
                    style=BTN_SUCCESS,
                ),
            ]
        ]
        try:
            await message.reply_text(
                f"<b>Thanks for adding me to {message.chat.title} ❣️</b>",
                reply_markup=InlineKeyboardMarkup(btn),
                parse_mode=enums.ParseMode.HTML,
            )
        except Exception:
            pass
        return

    # 2. Regular Users Joined -> Check Welcome Settings
    w_settings = await safe_get_group_welcome(message.chat.id)
    settings = await get_settings(message.chat.id)

    # Welcome is active if enabled in custom_settings OR in standard settings
    if "welcome" in w_settings:
        is_welcome_on = bool(w_settings.get("welcome"))
    else:
        is_welcome_on = bool(settings.get("welcome", True))

    if not is_welcome_on:
        return

    w_txt = w_settings.get("text") or "<b>👋 Hey {mention}, welcome to {title}!</b>"
    w_img = w_settings.get("img")

    try:
        total_members = await bot.get_chat_members_count(message.chat.id)
    except Exception:
        total_members = ""

    if not hasattr(temp, "MELCOW"):
        temp.MELCOW = {}

    for user in message.new_chat_members:
        if user.is_bot:
            continue

        formatted_raw = w_txt.format_map(
            SafeFormatDict(
                mention=user.mention,
                title=message.chat.title or "this group",
                count=total_members,
                first=user.first_name or "User",
                last=user.last_name or "",
                username=f"@{user.username}" if user.username else user.mention,
                id=user.id,
            )
        )
        final_text, final_markup = parse_text_and_markup(formatted_raw)

        old_msg = temp.MELCOW.get(message.chat.id)
        if old_msg:
            try:
                await old_msg.delete()
            except Exception:
                pass

        sent_welcome = None
        if w_img:
            try:
                sent_welcome = await message.reply_photo(
                    photo=w_img,
                    caption=final_text,
                    reply_markup=final_markup,
                    parse_mode=enums.ParseMode.HTML,
                )
            except Exception:
                sent_welcome = None

        if not sent_welcome:
            try:
                sent_welcome = await message.reply_text(
                    text=final_text,
                    reply_markup=final_markup,
                    parse_mode=enums.ParseMode.HTML,
                )
            except Exception:
                pass

        if sent_welcome:
            temp.MELCOW[message.chat.id] = sent_welcome


# ============================================================
# 🛠️ GLOBAL ADMIN CHAT MANAGEMENT COMMANDS & BUTTONS
# ============================================================
@Client.on_message(filters.command("disable"), group=-3)
async def disable_chat(bot: Client, message: Message):
    if not await is_message_global_admin(message):
        return await message.reply_text("❌ **Unauthorized:** Global Bot Admin only.")

    if len(message.command) == 1:
        return await message.reply_text("⚙️ **Usage:** `/disable <chat_id> [reason]`")

    parts = message.text.split(None, 2)
    try:
        chat_id = int(parts[1].strip())
    except ValueError:
        return await message.reply_text("❌ **Invalid chat ID!** Must be an integer.")
    reason = parts[2] if len(parts) > 2 else "No reason provided."

    chat_info = await _db.get_chat(chat_id)
    if not chat_info:
        try:
            chat_obj = await bot.get_chat(chat_id)
            chat_title = chat_obj.title or str(chat_id)
        except Exception:
            chat_title = str(chat_id)
        await _db.add_chat(chat_id, chat_title)
        chat_info = await _db.get_chat(chat_id)

    if chat_info and chat_info.get("is_disabled"):
        btn = [
            [
                create_btn(
                    "✅ Re-Enable Chat",
                    callback_data=f"ptti#enable#{chat_id}",
                    style=BTN_SUCCESS,
                )
            ]
        ]
        return await message.reply_text(
            f"🚷 **This chat is already disabled.**\n"
            f"🆔 **Chat ID:** `{chat_id}`\n"
            f"📝 **Reason:** `{chat_info.get('reason', 'Unknown')}`",
            reply_markup=InlineKeyboardMarkup(btn),
        )

    await _db.disable_chat(chat_id, reason)
    if not hasattr(temp, "BANNED_CHATS"):
        temp.BANNED_CHATS = []
    if chat_id not in temp.BANNED_CHATS:
        temp.BANNED_CHATS.append(chat_id)

    btn = [
        [
            create_btn(
                "✅ Re-Enable Chat",
                callback_data=f"ptti#enable#{chat_id}",
                style=BTN_SUCCESS,
            )
        ]
    ]
    await message.reply_text(
        f"✅ **Chat `{chat_id}` has been disabled!**\n📝 **Reason:** `{reason}`",
        reply_markup=InlineKeyboardMarkup(btn),
    )
    try:
        await bot.leave_chat(chat_id)
    except Exception:
        pass


@Client.on_message(filters.command("enable"), group=-3)
async def enable_chat(bot: Client, message: Message):
    if not await is_message_global_admin(message):
        return await message.reply_text("❌ **Unauthorized:** Global Bot Admin only.")

    if len(message.command) == 1:
        return await message.reply_text("⚙️ **Usage:** `/enable <chat_id>`")

    try:
        chat_id = int(message.command[1].strip())
    except ValueError:
        return await message.reply_text("❌ **Invalid chat ID!** Must be an integer.")

    chat_info = await _db.get_chat(chat_id)
    if not chat_info:
        return await message.reply_text("⚠️ **Chat not found in database.**")

    if not chat_info.get("is_disabled"):
        return await message.reply_text(f"✅ **Chat `{chat_id}` is already enabled.**")

    await _db.re_enable_chat(chat_id)
    if hasattr(temp, "BANNED_CHATS") and chat_id in temp.BANNED_CHATS:
        temp.BANNED_CHATS.remove(chat_id)

    btn = [
        [
            create_btn(
                "🚫 Disable Again",
                callback_data=f"ptti#disable#{chat_id}",
                style=BTN_DANGER,
            )
        ]
    ]
    await message.reply_text(
        f"✅ **Chat `{chat_id}` has been successfully re-enabled!**",
        reply_markup=InlineKeyboardMarkup(btn),
    )


@Client.on_message(filters.command(["disabled", "bannedchats"]), group=-3)
async def list_disabled_chats(bot: Client, message: Message):
    if not await is_message_global_admin(message):
        return await message.reply_text("❌ **Unauthorized:** Global Bot Admin only.")

    raw_chats = await _db.get_all_chats()
    all_chats = (
        await raw_chats.to_list(length=None)
        if hasattr(raw_chats, "to_list")
        else [c async for c in raw_chats]
        if hasattr(raw_chats, "__aiter__")
        else list(raw_chats)
    )

    disabled_list = [c for c in all_chats if c.get("is_disabled")]
    if not disabled_list:
        return await message.reply_text("✅ **There are currently no disabled chats.**")

    text = f"🚷 **Disabled Chats ({len(disabled_list)}):**\n\n"
    buttons = []
    for idx, c in enumerate(disabled_list[:20], 1):
        cid = c.get("id") or c.get("chat_id")
        title = c.get("title") or str(cid)
        reason = c.get("reason") or "No reason provided"
        text += f"**{idx}. {title}**\n├ ID: `{cid}`\n└ Reason: `{reason}`\n\n"
        buttons.append(
            [
                create_btn(
                    f"✅ Enable {title[:20]}",
                    callback_data=f"ptti#enable#{cid}",
                    style=BTN_SUCCESS,
                )
            ]
        )

    buttons.append([create_btn("🔐 Close", callback_data="ptti#close", style=BTN_DANGER)])
    await message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons))


@Client.on_message(filters.command("invite"), group=-3)
async def gen_invite_link_cmd(bot: Client, message: Message):
    if not await is_message_global_admin(message):
        return await message.reply_text("❌ **Unauthorized:** Global Bot Admin only.")

    if len(message.command) < 2:
        return await message.reply_text("⚙️ **Usage:** `/invite <chat_id>`")

    try:
        chat_id = int(message.command[1].strip())
    except ValueError:
        return await message.reply_text("❌ **Invalid chat ID!** Must be an integer.")

    try:
        link = await bot.create_chat_invite_link(chat_id)
        await message.reply_text(
            f"🔗 **Generated Invite Link for `{chat_id}`:**\n{link.invite_link}",
            disable_web_page_preview=True,
        )
    except ChatAdminRequired:
        await message.reply_text(
            "❌ **Failed:** I do not have permission to generate invite links in that chat."
        )
    except Exception as e:
        await message.reply_text(f"❌ **Error:** `{e}`")


@Client.on_callback_query(filters.regex(r"^ptti#"), group=-3)
async def ptti_callbacks(bot: Client, query: CallbackQuery):
    uid = query.from_user.id if query.from_user else 0
    if not await is_global_admin(uid):
        return await query.answer("❌ Unauthorized: Admin only.", show_alert=True)

    parts = query.data.split("#")
    action = parts[1]

    if action == "close":
        await query.answer()
        try:
            await query.message.delete()
        except Exception:
            pass
        return

    chat_id = int(parts[2])
    if action == "enable":
        await _db.re_enable_chat(chat_id)
        if hasattr(temp, "BANNED_CHATS") and chat_id in temp.BANNED_CHATS:
            temp.BANNED_CHATS.remove(chat_id)
        await query.answer("✅ Chat Re-Enabled!", show_alert=True)
        btn = [
            [
                create_btn(
                    "🚫 Disable Chat",
                    callback_data=f"ptti#disable#{chat_id}",
                    style=BTN_DANGER,
                )
            ]
        ]
        try:
            await query.message.edit_text(
                f"✅ **Chat `{chat_id}` has been re-enabled!**",
                reply_markup=InlineKeyboardMarkup(btn),
            )
        except MessageNotModified:
            pass

    elif action == "disable":
        await _db.disable_chat(chat_id, "Disabled via button")
        if not hasattr(temp, "BANNED_CHATS"):
            temp.BANNED_CHATS = []
        if chat_id not in temp.BANNED_CHATS:
            temp.BANNED_CHATS.append(chat_id)
        await query.answer("🚫 Chat Disabled!", show_alert=True)
        btn = [
            [
                create_btn(
                    "✅ Re-Enable Chat",
                    callback_data=f"ptti#enable#{chat_id}",
                    style=BTN_SUCCESS,
                )
            ]
        ]
        try:
            await query.message.edit_text(
                f"🚷 **Chat `{chat_id}` has been disabled!**",
                reply_markup=InlineKeyboardMarkup(btn),
            )
        except MessageNotModified:
            pass
        try:
            await bot.leave_chat(chat_id)
        except Exception:
            pass
