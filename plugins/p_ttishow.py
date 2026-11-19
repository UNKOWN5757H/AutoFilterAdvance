import asyncio
import hashlib
import html
import inspect
import re
from logging import ERROR, getLogger
from typing import Any, Dict, List, Optional, Set

from motor.motor_asyncio import AsyncIOMotorClient
from pyrogram import Client, StopPropagation, enums, filters
from pyrogram.errors import (
    ChatAdminRequired,
    ChatWriteForbidden,
    Forbidden,
    MessageIdInvalid,
    MessageNotModified,
    PeerIdInvalid,
    QueryIdInvalid,
    UserIsBlocked,
)
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

# Share hidden-link registry with pm_filter.py so ZERO links appear inside any button
try:
    from plugins.pm_filter import register_hidden_link, sanitize_markup_hide_links
except ImportError:
    try:
        from pm_filter import register_hidden_link, sanitize_markup_hide_links
    except ImportError:
        _LOCAL_HIDDEN_LINKS: Dict[str, str] = {}

        def register_hidden_link(url: str) -> str:
            clean_u = str(url or "").strip()
            if clean_u and not clean_u.startswith(("http://", "https://", "tg://")):
                clean_u = "https://" + clean_u.lstrip("/")
            token = hashlib.md5(clean_u.encode("utf-8")).hexdigest()[:12]
            if len(_LOCAL_HIDDEN_LINKS) >= 15000:
                _LOCAL_HIDDEN_LINKS.pop(next(iter(_LOCAL_HIDDEN_LINKS)), None)
            _LOCAL_HIDDEN_LINKS[token] = clean_u
            return token

        def sanitize_markup_hide_links(
            markup: Optional[InlineKeyboardMarkup],
        ) -> Optional[InlineKeyboardMarkup]:
            if not markup or not getattr(markup, "inline_keyboard", None):
                return markup
            rows = []
            for row in markup.inline_keyboard:
                new_row = []
                for b in row:
                    st = getattr(b, "style", None)
                    if getattr(b, "url", None):
                        new_row.append(create_btn(b.text, url=b.url, style=st))
                    else:
                        new_row.append(
                            create_btn(
                                b.text,
                                callback_data=getattr(b, "callback_data", "noop"),
                                style=st,
                            )
                        )
                if new_row:
                    rows.append(new_row)
            return InlineKeyboardMarkup(rows) if rows else None


logger = getLogger(__name__)
logger.setLevel(ERROR)

_BG_TASKS: Set[asyncio.Task] = set()

# ============================================================
# 🛡️ PYROGRAM v2.2.26 COMPATIBILITY & HIDDEN-LINK BUTTONS
# ============================================================
try:
    from pyrogram.types import LinkPreviewOptions
except ImportError:
    LinkPreviewOptions = None

try:
    from pyrogram.types import ReplyParameters
except ImportError:
    ReplyParameters = None

_REPLY_PARAMS = set(inspect.signature(Message.reply_text).parameters.keys())
_EDIT_PARAMS = set(inspect.signature(Message.edit_text).parameters.keys())

BTN_PRIMARY = None
BTN_SUCCESS = None
BTN_DANGER = None
_SUPPORTS_BTN_STYLE = False

try:
    from pyrogram.enums import ButtonStyle

    if "style" in inspect.signature(InlineKeyboardButton.__init__).parameters:
        BTN_PRIMARY = getattr(ButtonStyle, "PRIMARY", None)
        BTN_SUCCESS = getattr(ButtonStyle, "SUCCESS", None)
        BTN_DANGER = getattr(ButtonStyle, "DANGER", None)
        _SUPPORTS_BTN_STYLE = True
except (ImportError, ValueError, TypeError):
    pass


def _clean_button_label(raw_label: str) -> str:
    lbl = re.sub(r"<[^>]+>", "", str(raw_label or "")).strip()
    lbl = re.sub(r"(?i)https?://\S+|t\.me/\S+|www\.\S+", "", lbl).strip(" -|:")
    return lbl or "Open"


def create_btn(
    text: str,
    url: Optional[str] = None,
    callback_data: Optional[str] = None,
    style: Any = None,
) -> InlineKeyboardButton:
    """Creates an InlineKeyboardButton with ZERO visible links inside the button."""
    kwargs: Dict[str, Any] = {"text": _clean_button_label(text)}
    if callback_data:
        kwargs["callback_data"] = str(callback_data)[:64]
    elif url:
        kwargs["callback_data"] = f"olink#{register_hidden_link(url)}"
    else:
        kwargs["callback_data"] = "noop"

    if _SUPPORTS_BTN_STYLE and style is not None:
        kwargs["style"] = style
    try:
        return InlineKeyboardButton(**kwargs)
    except Exception:
        kwargs.pop("style", None)
        return InlineKeyboardButton(**kwargs)


def _prepare_compat_kwargs(
    kwargs: dict, supported_params: set, disable_preview: Optional[bool] = True
) -> dict:
    clean_kw = dict(kwargs)
    if "reply_markup" in clean_kw and isinstance(
        clean_kw["reply_markup"], InlineKeyboardMarkup
    ):
        clean_kw["reply_markup"] = sanitize_markup_hide_links(clean_kw["reply_markup"])

    explicit_disable = clean_kw.pop("disable_web_page_preview", disable_preview)
    if explicit_disable is not None:
        if (
            "link_preview_options" in supported_params
            and LinkPreviewOptions is not None
        ):
            try:
                clean_kw["link_preview_options"] = LinkPreviewOptions(
                    is_disabled=bool(explicit_disable)
                )
            except Exception:
                pass
        elif "disable_web_page_preview" in supported_params:
            clean_kw["disable_web_page_preview"] = bool(explicit_disable)

    if "reply_to_message_id" in clean_kw:
        rep_id = clean_kw.pop("reply_to_message_id")
        if rep_id:
            if "reply_to_message_id" in supported_params:
                clean_kw["reply_to_message_id"] = rep_id
            elif "reply_parameters" in supported_params and ReplyParameters is not None:
                try:
                    clean_kw["reply_parameters"] = ReplyParameters(message_id=rep_id)
                except Exception:
                    pass

    return clean_kw


async def safe_reply_text(
    message: Message, text: str, disable_web_page_preview: bool = True, **kwargs
) -> Optional[Message]:
    if not message:
        return None
    compat_kw = _prepare_compat_kwargs(
        kwargs, _REPLY_PARAMS, disable_preview=disable_web_page_preview
    )
    try:
        return await message.reply_text(text, **compat_kw)
    except TypeError:
        for k in (
            "disable_web_page_preview",
            "link_preview_options",
            "reply_parameters",
            "reply_to_message_id",
        ):
            compat_kw.pop(k, None)
        return await message.reply_text(text, **compat_kw)
    except (ChatWriteForbidden, Forbidden, UserIsBlocked, PeerIdInvalid):
        return None


async def safe_edit_text(
    message: Message, text: str, disable_web_page_preview: bool = True, **kwargs
) -> Optional[Message]:
    if not message:
        return None
    compat_kw = _prepare_compat_kwargs(
        kwargs, _EDIT_PARAMS, disable_preview=disable_web_page_preview
    )
    try:
        return await message.edit_text(text, **compat_kw)
    except (MessageNotModified, MessageIdInvalid, ChatWriteForbidden, Forbidden):
        return None
    except TypeError:
        compat_kw.pop("disable_web_page_preview", None)
        compat_kw.pop("link_preview_options", None)
        try:
            return await message.edit_text(text, **compat_kw)
        except Exception:
            return None


async def safe_answer(
    query: CallbackQuery, text: Optional[str] = None, show_alert: bool = False
):
    if not query:
        return
    try:
        if text is not None:
            await query.answer(str(text)[:200], show_alert=show_alert)
        else:
            await query.answer(show_alert=show_alert)
    except (QueryIdInvalid, Exception):
        pass


# ============================================================
# ⚙️ TIMEOUT-SAFE WELCOME DB FALLBACK
# ============================================================
_g_welcome_db = None
try:
    _DB_CLIENT = AsyncIOMotorClient(
        info.DATABASE_URI,
        serverSelectionTimeoutMS=4000,
        connectTimeoutMS=4000,
        socketTimeoutMS=8000,
    )
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
            doc = await asyncio.wait_for(
                _g_welcome_db.find_one({"_id": int(chat_id)}), timeout=2.0
            )
            return doc or {}
        except Exception:
            pass
    return {}


class SafeFormatDict(dict):
    def __missing__(self, key):
        return "{" + key + "}"


# ============================================================
# 👑 SMART AUTHORIZATION ENGINE
# ============================================================
def get_admin_list() -> List[int]:
    raw_admins = getattr(info, "ADMINS", [])
    if isinstance(raw_admins, (str, int)):
        raw_admins = str(raw_admins).replace(",", " ").split()
    elif isinstance(raw_admins, (list, tuple, set)):
        raw_admins = list(raw_admins)
    else:
        raw_admins = []
    return [int(x) for x in raw_admins if str(x).strip().lstrip("-").isdigit()]


async def is_global_admin(user_id: int) -> bool:
    return bool(user_id and int(user_id) in get_admin_list())


async def is_message_global_admin(message: Message) -> bool:
    admin_list = get_admin_list()
    if message.from_user and message.from_user.id in admin_list:
        return True
    if message.sender_chat and message.sender_chat.id in admin_list:
        return True
    return False


async def _require_global_admin(message: Message) -> bool:
    if await is_message_global_admin(message):
        return True
    await safe_reply_text(
        message,
        "❌ <b>Unauthorized:</b> Global Bot Admin only.",
        parse_mode=enums.ParseMode.HTML,
    )
    return False


async def is_user_admin(client: Client, message: Message) -> bool:
    if await is_message_global_admin(message):
        return True

    if message.chat and message.chat.type in [
        enums.ChatType.GROUP,
        enums.ChatType.SUPERGROUP,
    ]:
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
# 🛡️ FAST GROUP GATEKEEPER & LINK PROTECTOR (ZERO WASTED API CALLS)
# ============================================================
TELEGRAM_LINK_PATTERN = re.compile(
    r"(https?://)?(www\.)?(t(elegram)?\.(me|dog)|telegram\.org)/(joinchat/|\+|[a-zA-Z0-9_]+)",
    re.IGNORECASE,
)


def is_external_channel_forward(message: Message) -> bool:
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


def _schedule_delete(msg: Optional[Message], delay: int = 8):
    if not msg:
        return
    t = asyncio.create_task(_delete_warning_later(msg, delay))
    _BG_TASKS.add(t)
    t.add_done_callback(_BG_TASKS.discard)


@Client.on_message(filters.group & ~filters.service & ~filters.bot, group=-4)
async def group_gatekeeper_and_link_protector(bot: Client, message: Message):
    text = message.text or message.caption or ""
    has_tg_link = bool(text and TELEGRAM_LINK_PATTERN.search(text))
    is_ch_fwd = not has_tg_link and is_external_channel_forward(message)

    # Fast-path: return immediately if no violation (avoids calling get_chat_member on every message!)
    if not has_tg_link and not is_ch_fwd:
        return

    if await is_user_admin(bot, message):
        return

    mention = message.from_user.mention if message.from_user else "User"
    warn_text = (
        f"⚠️ <b>Link Deleted!</b> {mention}, unauthorized links are not permitted in this group."
        if has_tg_link
        else f"⚠️ <b>Channel Forward Blocked!</b> {mention}, forwarding messages from external channels is prohibited."
    )

    try:
        await message.delete()
        warning = await bot.send_message(
            message.chat.id, warn_text, parse_mode=enums.ParseMode.HTML
        )
        _schedule_delete(warning, 8)
    except Exception:
        pass
    raise StopPropagation


# ============================================================
# 👥 WELCOME SYSTEM & CHAT LIFECYCLE
# ============================================================
@Client.on_message(filters.command("start") & filters.private, group=-3)
async def start_about_interceptor(bot: Client, message: Message):
    if len(message.command) == 2 and message.command[1].strip().lower() == "about":
        mention = message.from_user.mention if message.from_user else "User"
        bname = temp.B_NAME or (await bot.get_me()).first_name or "MovieBot"
        raw_text = getattr(script, "ABOUT_TXT", "<b>About Bot</b>").format_map(
            SafeFormatDict(mention=mention, bname=bname)
        )
        kb = InlineKeyboardMarkup(
            [
                [
                    create_btn("🏘 Hᴏᴍᴇ", callback_data="start", style=BTN_SUCCESS),
                    create_btn("ℹ️ Hᴇʟᴘ", callback_data="help", style=BTN_PRIMARY),
                    create_btn(
                        "🔐 Cʟᴏsᴇ", callback_data="close_data", style=BTN_DANGER
                    ),
                ]
            ]
        )
        final_text, final_kb = parse_text_and_markup(raw_text, kb)
        final_kb = sanitize_markup_hide_links(final_kb)
        img = getattr(info, "ABOUT_IMG", None)
        if img:
            try:
                await message.reply_photo(
                    photo=img,
                    caption=final_text,
                    reply_markup=final_kb,
                    parse_mode=enums.ParseMode.HTML,
                )
                raise StopPropagation
            except StopPropagation:
                raise
            except Exception:
                pass
        await safe_reply_text(
            message,
            text=final_text,
            reply_markup=final_kb,
            parse_mode=enums.ParseMode.HTML,
        )
        raise StopPropagation


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
                await safe_reply_text(
                    message,
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
            await safe_reply_text(
                message,
                f"<b>Thanks for adding me to {html.escape(message.chat.title or 'this group')} ❣️</b>",
                reply_markup=InlineKeyboardMarkup(btn),
                parse_mode=enums.ParseMode.HTML,
            )
        except Exception:
            pass
        return

    w_settings = await safe_get_group_welcome(message.chat.id)
    settings = await get_settings(message.chat.id) or {}
    is_welcome_on = (
        bool(w_settings.get("welcome"))
        if "welcome" in w_settings
        else bool(settings.get("welcome", True))
    )
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
    elif len(temp.MELCOW) > 2000:
        temp.MELCOW.clear()

    for user in message.new_chat_members:
        if user.is_bot:
            continue

        formatted_raw = w_txt.format_map(
            SafeFormatDict(
                mention=user.mention,
                title=html.escape(message.chat.title or "this group"),
                count=total_members,
                first=html.escape(user.first_name or "User"),
                last=html.escape(user.last_name or ""),
                username=f"@{user.username}" if user.username else user.mention,
                id=user.id,
            )
        )
        final_text, final_markup = parse_text_and_markup(formatted_raw)
        final_markup = sanitize_markup_hide_links(final_markup)

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
            sent_welcome = await safe_reply_text(
                message,
                text=final_text,
                reply_markup=final_markup,
                parse_mode=enums.ParseMode.HTML,
            )

        if sent_welcome:
            temp.MELCOW[message.chat.id] = sent_welcome


# ============================================================
# 🛠️ GLOBAL ADMIN CHAT MANAGEMENT COMMANDS & BUTTONS
# ============================================================
@Client.on_message(filters.command("disable") & filters.incoming, group=-2)
async def disable_chat(bot: Client, message: Message):
    if not await _require_global_admin(message):
        return

    if len(message.command) == 1:
        return await safe_reply_text(
            message,
            "⚙️ <b>Usage:</b> <code>/disable &lt;chat_id&gt; [reason]</code>",
            parse_mode=enums.ParseMode.HTML,
        )

    parts = message.text.split(None, 2)
    try:
        chat_id = int(parts[1].strip())
    except ValueError:
        return await safe_reply_text(
            message,
            "❌ <b>Invalid chat ID!</b> Must be an integer.",
            parse_mode=enums.ParseMode.HTML,
        )
    reason = parts[2] if len(parts) > 2 else "No reason provided."

    chat_info = await _db.get_chat(chat_id)
    if not chat_info:
        try:
            chat_title = (await bot.get_chat(chat_id)).title or str(chat_id)
        except Exception:
            chat_title = str(chat_id)
        await _db.add_chat(chat_id, chat_title)
        chat_info = await _db.get_chat(chat_id)

    btn = InlineKeyboardMarkup(
        [
            [
                create_btn(
                    "✅ Re-Enable Chat",
                    callback_data=f"ptti#enable#{chat_id}",
                    style=BTN_SUCCESS,
                )
            ]
        ]
    )

    if chat_info and chat_info.get("is_disabled"):
        return await safe_reply_text(
            message,
            f"🚷 <b>This chat is already disabled.</b>\n"
            f"🆔 <b>Chat ID:</b> <code>{chat_id}</code>\n"
            f"📝 <b>Reason:</b> <code>{html.escape(str(chat_info.get('reason', 'Unknown')))}</code>",
            reply_markup=btn,
            parse_mode=enums.ParseMode.HTML,
        )

    await _db.disable_chat(chat_id, reason)
    if not hasattr(temp, "BANNED_CHATS"):
        temp.BANNED_CHATS = []
    if chat_id not in temp.BANNED_CHATS:
        temp.BANNED_CHATS.append(chat_id)

    await safe_reply_text(
        message,
        f"✅ <b>Chat <code>{chat_id}</code> has been disabled!</b>\n📝 <b>Reason:</b> <code>{html.escape(reason)}</code>",
        reply_markup=btn,
        parse_mode=enums.ParseMode.HTML,
    )
    try:
        await bot.leave_chat(chat_id)
    except Exception:
        pass


@Client.on_message(filters.command("enable") & filters.incoming, group=-2)
async def enable_chat(bot: Client, message: Message):
    if not await _require_global_admin(message):
        return

    if len(message.command) == 1:
        return await safe_reply_text(
            message,
            "⚙️ <b>Usage:</b> <code>/enable &lt;chat_id&gt;</code>",
            parse_mode=enums.ParseMode.HTML,
        )

    try:
        chat_id = int(message.command[1].strip())
    except ValueError:
        return await safe_reply_text(
            message,
            "❌ <b>Invalid chat ID!</b> Must be an integer.",
            parse_mode=enums.ParseMode.HTML,
        )

    chat_info = await _db.get_chat(chat_id)
    if not chat_info:
        return await safe_reply_text(
            message,
            "⚠️ <b>Chat not found in database.</b>",
            parse_mode=enums.ParseMode.HTML,
        )

    if not chat_info.get("is_disabled"):
        return await safe_reply_text(
            message,
            f"✅ <b>Chat <code>{chat_id}</code> is already enabled.</b>",
            parse_mode=enums.ParseMode.HTML,
        )

    await _db.re_enable_chat(chat_id)
    if hasattr(temp, "BANNED_CHATS") and chat_id in temp.BANNED_CHATS:
        temp.BANNED_CHATS.remove(chat_id)

    btn = InlineKeyboardMarkup(
        [
            [
                create_btn(
                    "🚫 Disable Again",
                    callback_data=f"ptti#disable#{chat_id}",
                    style=BTN_DANGER,
                )
            ]
        ]
    )
    await safe_reply_text(
        message,
        f"✅ <b>Chat <code>{chat_id}</code> has been successfully re-enabled!</b>",
        reply_markup=btn,
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(
    filters.command(["disabled", "bannedchats"]) & filters.incoming, group=-2
)
async def list_disabled_chats(bot: Client, message: Message):
    if not await _require_global_admin(message):
        return

    raw_chats = await _db.get_all_chats()
    all_chats = (
        await raw_chats.to_list(length=None)
        if hasattr(raw_chats, "to_list")
        else (
            [c async for c in raw_chats]
            if hasattr(raw_chats, "__aiter__")
            else list(raw_chats)
        )
    )

    disabled_list = [c for c in all_chats if c.get("is_disabled")]
    if not disabled_list:
        return await safe_reply_text(
            message,
            "✅ <b>There are currently no disabled chats.</b>",
            parse_mode=enums.ParseMode.HTML,
        )

    text = f"🚷 <b>Disabled Chats ({len(disabled_list)}):</b>\n\n"
    buttons = []
    for idx, c in enumerate(disabled_list[:20], 1):
        cid = c.get("id") or c.get("chat_id")
        title = html.escape(str(c.get("title") or cid))
        reason = html.escape(str(c.get("reason") or "No reason provided"))
        text += (
            f"<b>{idx}. {title}</b>\n"
            f"├ ID: <code>{cid}</code>\n"
            f"└ Reason: <code>{reason}</code>\n\n"
        )
        buttons.append(
            [
                create_btn(
                    f"✅ Enable {str(c.get('title') or cid)[:20]}",
                    callback_data=f"ptti#enable#{cid}",
                    style=BTN_SUCCESS,
                )
            ]
        )

    buttons.append(
        [create_btn("🔐 Close", callback_data="ptti#close", style=BTN_DANGER)]
    )
    await safe_reply_text(
        message,
        text,
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(filters.command("invite") & filters.incoming, group=-2)
async def gen_invite_link_cmd(bot: Client, message: Message):
    if not await _require_global_admin(message):
        return

    if len(message.command) < 2:
        return await safe_reply_text(
            message,
            "⚙️ <b>Usage:</b> <code>/invite &lt;chat_id&gt;</code>",
            parse_mode=enums.ParseMode.HTML,
        )

    try:
        chat_id = int(message.command[1].strip())
    except ValueError:
        return await safe_reply_text(
            message,
            "❌ <b>Invalid chat ID!</b> Must be an integer.",
            parse_mode=enums.ParseMode.HTML,
        )

    try:
        link = await bot.create_chat_invite_link(chat_id)
        await safe_reply_text(
            message,
            f"🔗 <b>Generated Invite Link for <code>{chat_id}</code>:</b>\n{link.invite_link}",
            disable_web_page_preview=True,
            parse_mode=enums.ParseMode.HTML,
        )
    except ChatAdminRequired:
        await safe_reply_text(
            message,
            "❌ <b>Failed:</b> I do not have permission to generate invite links in that chat.",
            parse_mode=enums.ParseMode.HTML,
        )
    except Exception as e:
        await safe_reply_text(
            message,
            f"❌ <b>Error:</b> <code>{html.escape(str(e))}</code>",
            parse_mode=enums.ParseMode.HTML,
        )


@Client.on_callback_query(filters.regex(r"^ptti#"), group=-2)
async def ptti_callbacks(bot: Client, query: CallbackQuery):
    uid = query.from_user.id if query.from_user else 0
    if not await is_global_admin(uid):
        return await safe_answer(query, "❌ Unauthorized: Admin only.", show_alert=True)
    if not query.message:
        return await safe_answer(query)

    parts = query.data.split("#")
    action = parts[1] if len(parts) > 1 else "close"

    if action == "close":
        await safe_answer(query)
        try:
            await query.message.delete()
        except Exception:
            pass
        return

    try:
        chat_id = int(parts[2])
    except (IndexError, ValueError):
        return await safe_answer(query, "⚠️ Invalid chat ID!", show_alert=True)

    if action == "enable":
        await _db.re_enable_chat(chat_id)
        if hasattr(temp, "BANNED_CHATS") and chat_id in temp.BANNED_CHATS:
            temp.BANNED_CHATS.remove(chat_id)
        await safe_answer(query, "✅ Chat Re-Enabled!", show_alert=True)
        btn = InlineKeyboardMarkup(
            [
                [
                    create_btn(
                        "🚫 Disable Chat",
                        callback_data=f"ptti#disable#{chat_id}",
                        style=BTN_DANGER,
                    )
                ]
            ]
        )
        await safe_edit_text(
            query.message,
            f"✅ <b>Chat <code>{chat_id}</code> has been re-enabled!</b>",
            reply_markup=btn,
            parse_mode=enums.ParseMode.HTML,
        )

    elif action == "disable":
        await _db.disable_chat(chat_id, "Disabled via button")
        if not hasattr(temp, "BANNED_CHATS"):
            temp.BANNED_CHATS = []
        if chat_id not in temp.BANNED_CHATS:
            temp.BANNED_CHATS.append(chat_id)
        await safe_answer(query, "🚫 Chat Disabled!", show_alert=True)
        btn = InlineKeyboardMarkup(
            [
                [
                    create_btn(
                        "✅ Re-Enable Chat",
                        callback_data=f"ptti#enable#{chat_id}",
                        style=BTN_SUCCESS,
                    )
                ]
            ]
        )
        await safe_edit_text(
            query.message,
            f"🚷 <b>Chat <code>{chat_id}</code> has been disabled!</b>",
            reply_markup=btn,
            parse_mode=enums.ParseMode.HTML,
        )
        try:
            await bot.leave_chat(chat_id)
        except Exception:
            pass
