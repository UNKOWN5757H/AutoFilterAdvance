import asyncio
import base64
import hashlib
import html
import inspect
import json
import os
import re
import time
from logging import INFO, getLogger
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from motor.motor_asyncio import AsyncIOMotorClient
from pyrogram import Client, StopPropagation, enums, filters
from pyrogram.errors import (
    ChannelInvalid,
    ChannelPrivate,
    ChatWriteForbidden,
    FloodWait,
    Forbidden,
    MessageIdInvalid,
    MessageNotModified,
    PeerIdInvalid,
    QueryIdInvalid,
    UserIsBlocked,
    UsernameInvalid,
    UsernameNotModified,
)
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

import info
from database.ia_filterdb import get_file_details, unpack_new_file_id
from utils import get_size, parse_text_and_markup, temp

# ============================================================
# 🛡️ SAFE OPTIONAL IMPORTS (MULTI-DB, FSUB & HIDDEN LINKS)
# ============================================================
try:
    from database.ia_filterdb import get_writable_System_db, save_file
except ImportError:
    get_writable_System_db = None
    save_file = None

try:
    from plugins.fsub import ForceSub
except Exception:
    ForceSub = None

try:
    from plugins.uibuttons import (
        get_default_file_keyboard as _get_default_file_keyboard,
    )
    from plugins.uibuttons import (
        get_deleted_file_notify_keyboard as _get_deleted_file_notify_keyboard,
    )
except Exception:
    _get_default_file_keyboard = None
    _get_deleted_file_notify_keyboard = None

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
logger.setLevel(INFO)

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

_SEND_MSG_PARAMS = set(inspect.signature(Client.send_message).parameters.keys())
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


async def safe_send_message(
    client: Client,
    chat_id: int,
    text: str,
    disable_web_page_preview: Optional[bool] = True,
    **kwargs,
) -> Optional[Message]:
    compat_kw = _prepare_compat_kwargs(
        kwargs, _SEND_MSG_PARAMS, disable_preview=disable_web_page_preview
    )
    try:
        return await client.send_message(chat_id=chat_id, text=text, **compat_kw)
    except TypeError:
        for k in (
            "disable_web_page_preview",
            "link_preview_options",
            "reply_parameters",
            "reply_to_message_id",
        ):
            compat_kw.pop(k, None)
        return await client.send_message(chat_id=chat_id, text=text, **compat_kw)
    except (ChatWriteForbidden, Forbidden, UserIsBlocked, PeerIdInvalid):
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
# ⚙️ QUOTA-SAFE MONGODB STORAGE FOR LINKS & BATCHES
# ============================================================
_genlink_db = None
_batch_db = None
_active_db = None

try:
    _DB_CLIENT = AsyncIOMotorClient(
        info.DATABASE_URI,
        serverSelectionTimeoutMS=4000,
        connectTimeoutMS=4000,
        socketTimeoutMS=8000,
    )
    _BOT_DB = _DB_CLIENT[info.DATABASE_NAME]
    _genlink_db = _BOT_DB["genlink_files"]
    _batch_db = _BOT_DB["genlink_batches"]
    _active_db = _BOT_DB["active_connections"]
except Exception as e:
    logger.error(f"Failed to init genlink DB: {e}")

AUTO_DELETE_TASKS: Set[asyncio.Task] = set()
BATCH_CANCEL: Dict[int, bool] = {}
_WAITING_INPUT: Dict[int, Dict[str, Any]] = {}


def _get_writable_col(col_name: str, fallback_col: Any):
    if callable(get_writable_System_db):
        try:
            w_db = get_writable_System_db()
            if w_db is not None:
                return w_db[col_name]
        except Exception:
            pass
    return fallback_col


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


async def is_user_admin(client: Client, message: Message) -> bool:
    if not message:
        return False
    admin_list = get_admin_list()

    if message.from_user and message.from_user.id in admin_list:
        return True
    if message.sender_chat and message.sender_chat.id in admin_list:
        return True

    if message.chat and message.chat.type in [
        enums.ChatType.GROUP,
        enums.ChatType.SUPERGROUP,
    ]:
        if message.sender_chat and message.sender_chat.id == message.chat.id:
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

    if (
        message.chat
        and message.chat.type == enums.ChatType.PRIVATE
        and message.from_user
        and _active_db is not None
    ):
        try:
            doc = await asyncio.wait_for(
                _active_db.find_one({"user_id": str(message.from_user.id)}), timeout=2.0
            )
            if doc and doc.get("group_id"):
                member = await client.get_chat_member(
                    int(doc["group_id"]), message.from_user.id
                )
                return member.status in [
                    enums.ChatMemberStatus.ADMINISTRATOR,
                    enums.ChatMemberStatus.OWNER,
                ]
        except Exception:
            pass

    return False


async def is_cb_admin(client: Client, query: CallbackQuery) -> bool:
    uid = query.from_user.id if query.from_user else 0
    if await is_global_admin(uid):
        return True
    if (
        query.message
        and query.message.chat
        and query.message.chat.type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]
    ):
        try:
            member = await client.get_chat_member(query.message.chat.id, uid)
            return member.status in [
                enums.ChatMemberStatus.ADMINISTRATOR,
                enums.ChatMemberStatus.OWNER,
            ]
        except Exception:
            pass
    return False


def is_file_store_channel(chat_id: int) -> bool:
    fsc = getattr(info, "FILE_STORE_CHANNEL", [])
    if isinstance(fsc, int):
        return int(chat_id) == fsc
    if isinstance(fsc, str):
        return str(chat_id) in [
            x.strip() for x in fsc.replace(",", " ").split() if x.strip()
        ]
    if isinstance(fsc, list):
        return int(chat_id) in [
            int(x) for x in fsc if str(x).strip().lstrip("-").isdigit()
        ]
    return False


# ============================================================
# 🔄 INTERACTIVE LISTENER FOR STEP-BY-STEP /LINK & /BATCH
# ============================================================
@Client.on_message(filters.private | filters.group, group=-14)
async def genlink_listener(client: Client, message: Message):
    if not message or not message.chat:
        return
    chat_id = message.chat.id
    if chat_id not in _WAITING_INPUT:
        return
    if (
        message.text
        and message.text.startswith("/")
        and message.text.strip().lower() != "/cancel"
    ):
        return

    uid = (
        message.from_user.id
        if message.from_user
        else getattr(message.sender_chat, "id", 0)
    )
    session = _WAITING_INPUT.get(chat_id)
    if session and (uid == session["user_id"] or uid == chat_id):
        fut = session["future"]
        if not fut.done():
            fut.set_result(message)
        raise StopPropagation


async def wait_for_input(
    chat_id: int, user_id: int, timeout: int = 120
) -> Optional[Message]:
    if chat_id in _WAITING_INPUT:
        old_fut = _WAITING_INPUT[chat_id].get("future")
        if old_fut and not old_fut.done():
            old_fut.cancel()

    loop = asyncio.get_running_loop()
    future = loop.create_future()
    _WAITING_INPUT[chat_id] = {"future": future, "user_id": user_id}
    try:
        return await asyncio.wait_for(future, timeout=timeout)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        return None
    finally:
        if _WAITING_INPUT.get(chat_id, {}).get("future") is future:
            _WAITING_INPUT.pop(chat_id, None)


# ============================================================
# ⏳ AUTO-DELETE & FORMATTING HELPERS
# ============================================================
def get_auto_delete_timer(
    var_name: str = "FILE_AUTO_DELETE", default_time: int = 1800
) -> int:
    try:
        global_switch = getattr(info, "AUTO_DELETE", True)
        if str(global_switch).strip().lower() in ("false", "off", "0", "no"):
            return 0
        raw_val = getattr(
            info,
            var_name,
            getattr(
                info,
                "AUTO_DELETE_TIME",
                getattr(info, "FILE_AUTO_DELETE", default_time),
            ),
        )
        if isinstance(raw_val, bool):
            return default_time if raw_val else 0
        return max(0, int(str(raw_val).strip()))
    except Exception:
        return default_time


def format_duration(seconds: int) -> str:
    if seconds <= 0:
        return "0 Seconds"
    m, s = divmod(int(seconds), 60)
    if m > 0 and s > 0:
        return f"{m} Minute{'s' if m != 1 else ''} {s} Second{'s' if s != 1 else ''}"
    if m > 0:
        return f"{m} Minute{'s' if m != 1 else ''}"
    return f"{s} Second{'s' if s != 1 else ''}"


async def _auto_delete_worker(
    client: Client, chat_id: int, is_pm: bool, delay: int, *messages
):
    await asyncio.sleep(delay)
    msg_ids = [m.id for m in messages if m is not None and hasattr(m, "id") and m.id]
    if msg_ids:
        try:
            await client.delete_messages(chat_id, msg_ids)
        except Exception:
            for m in messages:
                if m is not None:
                    try:
                        await m.delete()
                    except Exception:
                        pass

    if is_pm:
        notify_text = (
            getattr(info, "DEL_MSG", None)
            or "<b>Successfully deleted your file, if you want request again in group.</b>"
        )
        markup = sanitize_markup_hide_links(
            _get_deleted_file_notify_keyboard()
            if callable(_get_deleted_file_notify_keyboard)
            else InlineKeyboardMarkup(
                [
                    [
                        create_btn(
                            "Movie Request 📝",
                            url="https://t.me/Sandalwood_Kannada_Group",
                            style=BTN_SUCCESS,
                        )
                    ]
                ]
            )
        )
        try:
            await safe_send_message(
                client,
                chat_id,
                text=notify_text,
                reply_markup=markup,
                parse_mode=enums.ParseMode.HTML,
            )
        except Exception:
            pass


def schedule_auto_delete(
    client: Client, chat_id: int, is_pm: bool, delay: int, *messages
):
    if delay <= 0:
        return
    task = asyncio.create_task(
        _auto_delete_worker(client, chat_id, is_pm, delay, *messages)
    )
    AUTO_DELETE_TASKS.add(task)
    task.add_done_callback(AUTO_DELETE_TASKS.discard)


async def _send_autodelete_warning_and_schedule(
    bot: Client, user_id: int, chat_id: int, sent_messages: List[Message]
):
    if not sent_messages:
        return
    delete_timer = get_auto_delete_timer("FILE_AUTO_DELETE", 1800)
    if delete_timer <= 0:
        return

    time_str = format_duration(delete_timer)
    count = len(sent_messages)
    noun = f"{count} files" if count > 1 else "file"
    pronoun = "these files" if count > 1 else "this file"
    warn_text = (
        f"<b>📢 Please Note\n\n"
        f"✅ The above {noun} will be autodeleted in {time_str} to avoid copyright issues.\n\n"
        f"✅ Please forward {pronoun} to your saved messages and start downloading from there.\n\n"
        f"Tᴇᴀᴍ: @KR_Picture</b>"
    )
    warn_msg = await safe_send_message(
        bot,
        chat_id=user_id,
        text=warn_text,
        reply_to_message_id=sent_messages[-1].id,
        parse_mode=enums.ParseMode.HTML,
    )
    schedule_auto_delete(bot, chat_id, True, delete_timer, *sent_messages, warn_msg)


def format_media_caption(
    title: str, size_bytes: int, raw_caption: str = ""
) -> Tuple[str, Optional[InlineKeyboardMarkup]]:
    size_str = get_size(int(size_bytes or 0))
    f_caption = str(raw_caption or "")
    custom_cap = getattr(info, "CUSTOM_FILE_CAPTION", None)

    if custom_cap:
        try:
            f_caption = custom_cap.format(
                file_name="" if not title or title == "Unknown" else title,
                file_size="" if size_str == "0B" else size_str,
                file_caption="" if not f_caption else f_caption,
            )
        except Exception:
            pass

    if not f_caption:
        f_caption = f"<b>{html.escape(title or 'File')}</b>"
    elif not f_caption.strip().startswith("<"):
        f_caption = f"<b>{f_caption}</b>"

    if getattr(info, "CAPTION_PLUS", None):
        f_caption += f"\n\n{info.CAPTION_PLUS}"

    default_kb = (
        _get_default_file_keyboard()
        if callable(_get_default_file_keyboard)
        else InlineKeyboardMarkup(
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
    )
    final_cap, final_kb = parse_text_and_markup(f_caption, default_kb)
    return final_cap, sanitize_markup_hide_links(final_kb)


async def send_any_media(
    bot: Client,
    chat_id: int,
    file_id: str,
    caption: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    protect: bool = False,
):
    reply_markup = sanitize_markup_hide_links(reply_markup)
    try:
        return await bot.send_cached_media(
            chat_id=chat_id,
            file_id=file_id,
            caption=caption,
            reply_markup=reply_markup,
            protect_content=protect,
            parse_mode=enums.ParseMode.HTML,
        )
    except FloodWait as e:
        await asyncio.sleep(e.value + 1)
        return await send_any_media(
            bot, chat_id, file_id, caption, reply_markup, protect
        )
    except (UserIsBlocked, PeerIdInvalid, Forbidden):
        return None
    except Exception:
        for send_fn, kw in (
            (bot.send_document, "document"),
            (bot.send_video, "video"),
            (bot.send_photo, "photo"),
            (bot.send_audio, "audio"),
            (bot.send_animation, "animation"),
        ):
            try:
                return await send_fn(
                    **{
                        "chat_id": chat_id,
                        kw: file_id,
                        "caption": caption,
                        "reply_markup": reply_markup,
                        "protect_content": protect,
                        "parse_mode": enums.ParseMode.HTML,
                    }
                )
            except (UserIsBlocked, PeerIdInvalid, Forbidden):
                return None
            except Exception:
                continue
    return None


# ============================================================
# 🔗 SINGLE FILE LINK GENERATOR (/link, /plink)
# ============================================================
async def _create_single_link_from_msg(
    bot: Client, command_msg: Message, target_msg: Message, is_protect: bool
):
    file_type = target_msg.media
    if not file_type or file_type not in (
        enums.MessageMediaType.VIDEO,
        enums.MessageMediaType.AUDIO,
        enums.MessageMediaType.DOCUMENT,
        enums.MessageMediaType.PHOTO,
        enums.MessageMediaType.ANIMATION,
    ):
        return await safe_reply_text(
            command_msg,
            "⚠️ <b>Invalid Media:</b> Please reply to or send a Video, Document, Audio, Photo, or GIF.",
            parse_mode=enums.ParseMode.HTML,
        )

    media_obj = getattr(target_msg, file_type.value, None)
    if not media_obj:
        return await safe_reply_text(
            command_msg,
            "❌ <b>Could not extract media information.</b>",
            parse_mode=enums.ParseMode.HTML,
        )

    raw_file_id = getattr(media_obj, "file_id", "")
    try:
        unpacked_id, _ = unpack_new_file_id(raw_file_id)
    except Exception:
        unpacked_id = raw_file_id

    file_name = (
        getattr(media_obj, "file_name", None)
        or f"{file_type.value.title()}_{target_msg.id}"
    )
    file_size = getattr(media_obj, "file_size", 0) or 0
    caption_html = (
        target_msg.caption.html
        if target_msg.caption and hasattr(target_msg.caption, "html")
        else (target_msg.caption or "")
    )

    gl_col = _get_writable_col("genlink_files", _genlink_db)
    if gl_col is not None:
        try:
            await asyncio.wait_for(
                gl_col.update_one(
                    {"_id": str(unpacked_id)},
                    {
                        "$set": {
                            "file_id": str(unpacked_id),
                            "full_file_id": str(raw_file_id),
                            "file_name": str(file_name),
                            "file_size": int(file_size),
                            "caption": str(caption_html),
                            "file_type": str(file_type.value),
                            "timestamp": time.time(),
                        }
                    },
                    upsert=True,
                ),
                timeout=3.0,
            )
        except Exception as e:
            logger.error(f"genlink DB save error: {e}")

    if save_file is not None and file_type in (
        enums.MessageMediaType.VIDEO,
        enums.MessageMediaType.AUDIO,
        enums.MessageMediaType.DOCUMENT,
    ):
        try:
            media_obj.file_type = file_type.value
            media_obj.caption = caption_html
            await save_file(media_obj)
        except Exception:
            pass

    prefix = "filep" if is_protect else "file"
    bot_username = temp.U_NAME or (await bot.get_me()).username
    share_link = f"https://t.me/{bot_username}?start={prefix}_{unpacked_id}"

    # Pure hidden-link buttons (shows only button text, zero visible URL inside buttons)
    buttons = [
        [
            create_btn("🔗 Open Link", url=share_link, style=BTN_SUCCESS),
            create_btn(
                "📤 Share Link",
                url=f"https://t.me/share/url?url={share_link}",
                style=BTN_PRIMARY,
            ),
        ]
    ]

    await safe_reply_text(
        command_msg,
        f"✅ <b>Shareable Link Generated!</b>\n\n"
        f"📄 <b>File:</b> <code>{html.escape(str(file_name))}</code>\n"
        f"📦 <b>Size:</b> <code>{get_size(file_size)}</code>\n"
        f"🔒 <b>Protected:</b> <code>{'Yes' if is_protect else 'No'}</code>\n\n"
        f"🔗 <b>Link:</b>\n<code>{share_link}</code>",
        reply_markup=InlineKeyboardMarkup(buttons),
        disable_web_page_preview=True,
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(filters.command(["link", "plink"]) & filters.incoming, group=-3)
async def gen_link_s(bot: Client, message: Message):
    if not await is_user_admin(bot, message):
        return await safe_reply_text(
            message,
            "❌ <b>Unauthorized:</b> Admin only.",
            parse_mode=enums.ParseMode.HTML,
        )

    is_protect = message.command[0].lower() == "plink"
    if message.reply_to_message and message.reply_to_message.media:
        return await _create_single_link_from_msg(
            bot, message, message.reply_to_message, is_protect
        )

    uid = (
        message.from_user.id
        if message.from_user
        else getattr(message.sender_chat, "id", 0)
    )
    btn = [
        [
            create_btn(
                "❌ Cancel",
                callback_data=f"genlink_abort#{message.chat.id}",
                style=BTN_DANGER,
            )
        ]
    ]
    ask_msg = await safe_reply_text(
        message,
        "📂 <b>Please send or forward the media file</b> you want to generate a link for:\n\n<i>(Or reply to any file with <code>/link</code>)</i>",
        reply_markup=InlineKeyboardMarkup(btn),
        parse_mode=enums.ParseMode.HTML,
    )

    resp = await wait_for_input(message.chat.id, uid, timeout=120)
    if ask_msg:
        try:
            await ask_msg.delete()
        except Exception:
            pass

    if not resp or (resp.text and resp.text.strip().lower() == "/cancel"):
        return

    await _create_single_link_from_msg(bot, message, resp, is_protect)


# ============================================================
# 📦 BATCH LINK GENERATOR (/batch, /pbatch)
# ============================================================
LINK_REGEX = re.compile(
    r"(https?://)?(t(elegram)?\.(me|dog)|telegram\.org)/(c/)?(\d+|[a-zA-Z0-9_]+)/(\d+)$"
)


def extract_chat_and_msg_id(
    msg_or_text,
) -> Tuple[Optional[Union[int, str]], Optional[int]]:
    if isinstance(msg_or_text, Message):
        if (
            getattr(msg_or_text, "forward_from_chat", None)
            and msg_or_text.forward_from_chat.type == enums.ChatType.CHANNEL
        ):
            return (
                msg_or_text.forward_from_chat.id,
                msg_or_text.forward_from_message_id,
            )
        origin = getattr(msg_or_text, "forward_origin", None)
        if origin and getattr(origin, "chat", None):
            if origin.chat.type == enums.ChatType.CHANNEL:
                return origin.chat.id, getattr(origin, "message_id", None)
        text = msg_or_text.text or ""
    else:
        text = str(msg_or_text or "")

    match = LINK_REGEX.match(text.strip())
    if not match:
        return None, None
    chat_raw = match.group(6)
    msg_id = int(match.group(7))
    chat_id = int(f"-100{chat_raw}") if chat_raw.isdigit() else chat_raw
    return chat_id, msg_id


@Client.on_message(filters.command(["batch", "pbatch"]) & filters.incoming, group=-3)
async def gen_link_batch(bot: Client, message: Message):
    if not await is_user_admin(bot, message):
        return await safe_reply_text(
            message,
            "❌ <b>Unauthorized:</b> Admin only.",
            parse_mode=enums.ParseMode.HTML,
        )

    cmd = message.command[0].lower().strip()
    is_protect = cmd == "pbatch"
    parts = message.text.strip().split()

    if len(parts) == 3:
        f_chat_id, f_msg_id = extract_chat_and_msg_id(parts[1])
        l_chat_id, l_msg_id = extract_chat_and_msg_id(parts[2])
    else:
        uid = (
            message.from_user.id
            if message.from_user
            else getattr(message.sender_chat, "id", 0)
        )
        cancel_kb = InlineKeyboardMarkup(
            [
                [
                    create_btn(
                        "❌ Cancel",
                        callback_data=f"genlink_abort#{message.chat.id}",
                        style=BTN_DANGER,
                    )
                ]
            ]
        )
        ask1 = await safe_reply_text(
            message,
            "📦 <b>Step 1/2:</b> Send the <b>First Message Link</b> from the channel <i>(or forward the first message)</i>:\n\n"
            "💡 <i>Tip: You can also use <code>/batch &lt;first_link&gt; &lt;last_link&gt;</code> directly.</i>",
            reply_markup=cancel_kb,
            parse_mode=enums.ParseMode.HTML,
        )
        resp1 = await wait_for_input(message.chat.id, uid, timeout=120)
        if ask1:
            try:
                await ask1.delete()
            except Exception:
                pass
        if not resp1 or (resp1.text and resp1.text.strip().lower() == "/cancel"):
            return
        f_chat_id, f_msg_id = extract_chat_and_msg_id(resp1)
        if not f_chat_id or not f_msg_id:
            return await safe_reply_text(
                message,
                "❌ <b>Invalid First Message!</b> Please provide a valid channel post link or forwarded channel message.",
                parse_mode=enums.ParseMode.HTML,
            )

        ask2 = await safe_reply_text(
            message,
            "📦 <b>Step 2/2:</b> Now send the <b>Last Message Link</b> from the same channel <i>(or forward the last message)</i>:",
            reply_markup=cancel_kb,
            parse_mode=enums.ParseMode.HTML,
        )
        resp2 = await wait_for_input(message.chat.id, uid, timeout=120)
        if ask2:
            try:
                await ask2.delete()
            except Exception:
                pass
        if not resp2 or (resp2.text and resp2.text.strip().lower() == "/cancel"):
            return
        l_chat_id, l_msg_id = extract_chat_and_msg_id(resp2)

    if not (f_chat_id and f_msg_id and l_chat_id and l_msg_id):
        return await safe_reply_text(
            message,
            f"⚙️ <b>Usage Format:</b>\n"
            f"<code>/{cmd} &lt;first_link&gt; &lt;last_link&gt;</code>\n\n"
            f"<b>Example:</b>\n"
            f"<code>/{cmd} https://t.me/c/1234567/10 https://t.me/c/1234567/20</code>",
            parse_mode=enums.ParseMode.HTML,
        )

    if str(f_chat_id) != str(l_chat_id):
        return await safe_reply_text(
            message,
            "❌ <b>Mismatch:</b> Both links must belong to the exact same channel.",
            parse_mode=enums.ParseMode.HTML,
        )

    try:
        chat = await bot.get_chat(f_chat_id)
        chat_id = chat.id
    except (ChannelInvalid, ChannelPrivate, UsernameInvalid, UsernameNotModified):
        return await safe_reply_text(
            message,
            "❌ <b>Access Denied:</b> Please make sure the bot is an <b>Admin</b> in that channel.",
            parse_mode=enums.ParseMode.HTML,
        )
    except Exception as e:
        return await safe_reply_text(
            message,
            f"❌ <b>Error accessing channel:</b> <code>{html.escape(str(e))}</code>",
            parse_mode=enums.ParseMode.HTML,
        )

    bot_username = temp.U_NAME or (await bot.get_me()).username
    start_id, end_id = min(f_msg_id, l_msg_id), max(f_msg_id, l_msg_id)

    if is_file_store_channel(chat_id):
        string = f"{start_id}_{end_id}_{chat_id}_{cmd}"
        b_64 = base64.urlsafe_b64encode(string.encode("ascii")).decode().rstrip("=")
        dstore_link = f"https://t.me/{bot_username}?start=DSTORE-{b_64}"
        buttons = [
            [
                create_btn("📦 Open Batch", url=dstore_link, style=BTN_SUCCESS),
                create_btn(
                    "📤 Share Link",
                    url=f"https://t.me/share/url?url={dstore_link}",
                    style=BTN_PRIMARY,
                ),
            ]
        ]
        return await safe_reply_text(
            message,
            f"✅ <b>Batch File Store Link Generated!</b>\n\n"
            f"📢 <b>Channel:</b> <code>{html.escape(chat.title or str(chat_id))}</code>\n"
            f"🔢 <b>Range:</b> <code>{start_id}</code> to <code>{end_id}</code>\n\n"
            f"🔗 <b>Link:</b>\n<code>{dstore_link}</code>",
            reply_markup=InlineKeyboardMarkup(buttons),
            disable_web_page_preview=True,
            parse_mode=enums.ParseMode.HTML,
        )

    BATCH_CANCEL[message.chat.id] = False
    cancel_btn = InlineKeyboardMarkup(
        [
            [
                create_btn(
                    "❌ Cancel Batch",
                    callback_data=f"genlink_cancel#{message.chat.id}",
                    style=BTN_DANGER,
                )
            ]
        ]
    )
    sts = await safe_reply_text(
        message,
        "⏳ <b>Initiating Batch Generation...</b>",
        reply_markup=cancel_btn,
        parse_mode=enums.ParseMode.HTML,
    )

    outlist = []
    og_msg = 0
    total_range = list(range(start_id, end_id + 1))
    total_count = len(total_range)

    for i in range(0, total_count, 200):
        if BATCH_CANCEL.get(message.chat.id):
            BATCH_CANCEL.pop(message.chat.id, None)
            if sts:
                await safe_edit_text(
                    sts,
                    "⛔ <b>Batch generation cancelled.</b>",
                    parse_mode=enums.ParseMode.HTML,
                )
            return

        chunk_ids = total_range[i : i + 200]
        try:
            messages = await bot.get_messages(chat_id, message_ids=chunk_ids)
        except FloodWait as e:
            await asyncio.sleep(e.value + 1)
            messages = await bot.get_messages(chat_id, message_ids=chunk_ids)
        except Exception as e:
            logger.error(f"Error fetching batch chunk: {e}")
            continue

        if not isinstance(messages, list):
            messages = [messages]

        for msg in messages:
            if not msg or msg.empty or msg.service or not msg.media:
                continue
            try:
                media_obj = getattr(msg, msg.media.value, None)
                if not media_obj:
                    continue
                caption = (
                    msg.caption.html
                    if msg.caption and hasattr(msg.caption, "html")
                    else (msg.caption or "")
                )
                outlist.append(
                    {
                        "file_id": media_obj.file_id,
                        "caption": caption,
                        "title": getattr(media_obj, "file_name", "")
                        or f"File_{msg.id}",
                        "size": getattr(media_obj, "file_size", 0) or 0,
                        "protect": is_protect,
                    }
                )
                og_msg += 1
            except Exception:
                pass

        if sts:
            await safe_edit_text(
                sts,
                f"⏳ <b>Batch Link Progress:</b>\n"
                f"├ Processed: <code>{min(i + 200, total_count)}/{total_count}</code> messages\n"
                f"└ Files Found: <code>{og_msg}</code>",
                reply_markup=cancel_btn,
                parse_mode=enums.ParseMode.HTML,
            )

    BATCH_CANCEL.pop(message.chat.id, None)
    if not outlist:
        if sts:
            await safe_edit_text(
                sts,
                "❌ <b>No downloadable media found</b> within the provided message range.",
                parse_mode=enums.ParseMode.HTML,
            )
        return

    req_id = (
        message.from_user.id
        if message.from_user
        else (message.sender_chat.id if message.sender_chat else chat_id)
    )
    batch_file_path = f"batchmode_{req_id}_{int(time.time())}.json"
    with open(batch_file_path, "w+", encoding="utf-8") as out:
        json.dump(outlist, out)

    log_chan = getattr(info, "LOG_CHANNEL", None)
    post = None
    uploader_name = (
        message.from_user.mention
        if message.from_user
        else (message.sender_chat.title if message.sender_chat else "Admin")
    )

    if log_chan:
        try:
            post = await bot.send_document(
                int(log_chan),
                batch_file_path,
                file_name="Batch.json",
                caption=f"⚠️ Batch generated for {uploader_name} ({og_msg} files).",
                parse_mode=enums.ParseMode.HTML,
            )
        except Exception:
            post = None

    if not post:
        try:
            post = await bot.send_document(
                message.chat.id,
                batch_file_path,
                file_name="Batch.json",
                caption="⚠️ Batch generated locally.",
            )
        except Exception:
            post = None

    if os.path.exists(batch_file_path):
        try:
            os.remove(batch_file_path)
        except Exception:
            pass

    if post and post.document:
        try:
            batch_id, _ = unpack_new_file_id(post.document.file_id)
        except Exception:
            batch_id = post.document.file_id
        raw_doc_id = post.document.file_id
    else:
        batch_id = f"{abs(int(chat_id))}_{start_id}_{end_id}"
        raw_doc_id = None

    b_col = _get_writable_col("genlink_batches", _batch_db)
    if b_col is not None:
        try:
            await asyncio.wait_for(
                b_col.update_one(
                    {"_id": str(batch_id)},
                    {
                        "$set": {
                            "files": outlist,
                            "raw_doc_id": raw_doc_id,
                            "chat_id": int(chat_id),
                            "start_id": start_id,
                            "end_id": end_id,
                            "protect": is_protect,
                            "timestamp": time.time(),
                        }
                    },
                    upsert=True,
                ),
                timeout=4.0,
            )
        except Exception as e:
            logger.error(f"Batch DB save error: {e}")

    batch_link = f"https://t.me/{bot_username}?start=BATCH-{batch_id}"
    buttons = [
        [
            create_btn("📦 Open Batch Link", url=batch_link, style=BTN_SUCCESS),
            create_btn(
                "📤 Share Link",
                url=f"https://t.me/share/url?url={batch_link}",
                style=BTN_PRIMARY,
            ),
        ]
    ]

    if sts:
        await safe_edit_text(
            sts,
            f"✅ <b>Batch Link Complete!</b>\n\n"
            f"📢 <b>Channel:</b> <code>{html.escape(chat.title or str(chat_id))}</code>\n"
            f"📂 <b>Files Included:</b> <code>{og_msg}</code>\n"
            f"🔒 <b>Protected:</b> <code>{'Yes' if is_protect else 'No'}</code>\n\n"
            f"🔗 <b>Link:</b>\n<code>{batch_link}</code>",
            reply_markup=InlineKeyboardMarkup(buttons),
            disable_web_page_preview=True,
            parse_mode=enums.ParseMode.HTML,
        )


# ============================================================
# 🎛️ CANCEL & ABORT CALLBACKS
# ============================================================
@Client.on_callback_query(filters.regex(r"^(genlink_cancel#|genlink_abort#)"), group=-3)
async def genlink_callbacks(bot: Client, query: CallbackQuery):
    if not await is_cb_admin(bot, query):
        return await safe_answer(query, "❌ Unauthorized: Admin only.", show_alert=True)

    action, chat_id_str = query.data.split("#", 1)
    chat_id = int(chat_id_str)

    if action == "genlink_abort":
        if chat_id in _WAITING_INPUT:
            fut = _WAITING_INPUT[chat_id].get("future")
            if fut and not fut.done():
                fut.cancel()
            _WAITING_INPUT.pop(chat_id, None)
        await safe_answer(query, "Cancelled.")
        if query.message:
            await safe_edit_text(
                query.message,
                "❌ <b>Operation cancelled.</b>",
                parse_mode=enums.ParseMode.HTML,
            )
        return

    if action == "genlink_cancel":
        BATCH_CANCEL[chat_id] = True
        await safe_answer(query, "Stopping batch process...", show_alert=True)


# ============================================================
# 🚀 DEEP-LINK INTERCEPTOR FOR BATCH-, DSTORE-, BASE64 & GENLINK FILES
# ============================================================
def _try_decode_base64_payload(payload: str) -> Optional[str]:
    if (
        not payload
        or payload.startswith(
            ("file_", "filep_", "search_", "olink_", "BATCH-", "DSTORE-")
        )
        or payload in ("help", "about", "subscribe", "error", "okay", "hehe")
    ):
        return None
    try:
        padded = payload + "=" * (-len(payload) % 4)
        decoded = base64.urlsafe_b64decode(padded.encode("ascii")).decode("ascii")
        if decoded.startswith(("file_", "filep_")) or "_" in decoded:
            return decoded
    except Exception:
        pass
    return None


async def deliver_genlink_payload(
    bot: Client, user_id: int, chat_id: int, payload: str
) -> bool:
    decoded = _try_decode_base64_payload(payload)
    if decoded:
        payload = decoded

    # 1. Handle BATCH-<batch_id>
    if payload.startswith("BATCH-"):
        batch_id = payload.split("BATCH-", 1)[1]
        files_list = None

        b_col = _get_writable_col("genlink_batches", _batch_db)
        if b_col is not None:
            try:
                doc = await asyncio.wait_for(
                    b_col.find_one({"_id": str(batch_id)}), timeout=3.0
                )
                if doc and doc.get("files"):
                    files_list = doc["files"]
            except Exception:
                pass

        if not files_list:
            try:
                file_path = await bot.download_media(batch_id)
                if file_path and os.path.exists(file_path):
                    with open(file_path, "r", encoding="utf-8") as f:
                        files_list = json.load(f)
                    os.remove(file_path)
            except Exception as e:
                logger.error(f"Batch download fallback error: {e}")

        if not files_list:
            await safe_send_message(
                bot,
                chat_id,
                "⚠️ <b>Batch link expired or no longer exists!</b>",
                parse_mode=enums.ParseMode.HTML,
            )
            return True

        sts = await safe_send_message(
            bot,
            chat_id,
            f"⏳ <b>Sending {len(files_list)} files from batch... Please wait.</b>",
            parse_mode=enums.ParseMode.HTML,
        )
        sent_messages = []

        for item in files_list:
            fid = item.get("file_id")
            if not fid:
                continue
            final_cap, final_kb = format_media_caption(
                item.get("title") or "File",
                item.get("size") or 0,
                item.get("caption") or "",
            )
            sent = await send_any_media(
                bot, user_id, fid, final_cap, final_kb, bool(item.get("protect", False))
            )
            if sent:
                sent_messages.append(sent)
            await asyncio.sleep(0.8)

        if sts:
            try:
                await sts.delete()
            except Exception:
                pass

        await _send_autodelete_warning_and_schedule(
            bot, user_id, chat_id, sent_messages
        )
        return True

    # 2. Handle DSTORE-<b64>
    if payload.startswith("DSTORE-"):
        b64_str = payload.split("DSTORE-", 1)[1]
        try:
            padded = b64_str + "=" * (-len(b64_str) % 4)
            decoded_str = base64.urlsafe_b64decode(padded.encode("ascii")).decode(
                "ascii"
            )
            f_msg_id, l_msg_id, f_chat_id, cmd_type = decoded_str.split("_", 3)
            start_id, end_id = min(int(f_msg_id), int(l_msg_id)), max(
                int(f_msg_id), int(l_msg_id)
            )
            src_chat_id = int(f_chat_id)
            protect = "pbatch" in cmd_type.lower()
        except Exception:
            await safe_send_message(
                bot,
                chat_id,
                "⚠️ <b>Invalid Batch Store Link!</b>",
                parse_mode=enums.ParseMode.HTML,
            )
            return True

        sts = await safe_send_message(
            bot,
            chat_id,
            "⏳ <b>Fetching files from File Store... Please wait.</b>",
            parse_mode=enums.ParseMode.HTML,
        )
        sent_messages = []
        total_ids = list(range(start_id, end_id + 1))

        for i in range(0, len(total_ids), 200):
            chunk = total_ids[i : i + 200]
            try:
                msgs = await bot.get_messages(src_chat_id, chunk)
            except FloodWait as e:
                await asyncio.sleep(e.value + 1)
                msgs = await bot.get_messages(src_chat_id, chunk)
            except Exception:
                continue

            if not isinstance(msgs, list):
                msgs = [msgs]

            for m in msgs:
                if not m or m.empty or m.service or not m.media:
                    continue
                media_obj = getattr(m, m.media.value, None)
                if not media_obj:
                    continue
                raw_cap = (
                    m.caption.html
                    if m.caption and hasattr(m.caption, "html")
                    else (m.caption or "")
                )
                final_cap, final_kb = format_media_caption(
                    getattr(media_obj, "file_name", "") or f"File_{m.id}",
                    getattr(media_obj, "file_size", 0) or 0,
                    raw_cap,
                )
                sent = await send_any_media(
                    bot, user_id, media_obj.file_id, final_cap, final_kb, protect
                )
                if sent:
                    sent_messages.append(sent)
                await asyncio.sleep(0.8)

        if sts:
            try:
                await sts.delete()
            except Exception:
                pass

        await _send_autodelete_warning_and_schedule(
            bot, user_id, chat_id, sent_messages
        )
        return True

    # 3. Handle single file link stored in _genlink_db (or decoded base64 file_ link)
    if payload.startswith(("file_", "filep_")):
        prefix, fid = payload.split("_", 1)
        protect = prefix == "filep"

        db_files = await get_file_details(fid)
        gen_doc = None
        gl_col = _get_writable_col("genlink_files", _genlink_db)
        if not db_files and gl_col is not None:
            try:
                gen_doc = await asyncio.wait_for(
                    gl_col.find_one({"_id": str(fid)}), timeout=2.5
                )
            except Exception:
                gen_doc = None

        if gen_doc or decoded:
            if gen_doc:
                full_fid = gen_doc.get("full_file_id") or gen_doc.get("file_id", fid)
                title = gen_doc.get("file_name", "File")
                size = gen_doc.get("file_size", 0)
                raw_cap = gen_doc.get("caption", "")
            elif db_files:
                f_obj = db_files[0]
                full_fid = (
                    f_obj.get("full_file_id", f_obj.get("file_id", fid))
                    if isinstance(f_obj, dict)
                    else getattr(f_obj, "full_file_id", getattr(f_obj, "file_id", fid))
                )
                title = (
                    f_obj.get("file_name", "File")
                    if isinstance(f_obj, dict)
                    else getattr(f_obj, "file_name", "File")
                )
                size = (
                    f_obj.get("file_size", 0)
                    if isinstance(f_obj, dict)
                    else getattr(f_obj, "file_size", 0)
                )
                raw_cap = (
                    f_obj.get("caption", "")
                    if isinstance(f_obj, dict)
                    else getattr(f_obj, "caption", "")
                )
            else:
                full_fid, title, size, raw_cap = fid, "File", 0, ""

            final_cap, final_kb = format_media_caption(title, size, raw_cap)
            sent = await send_any_media(
                bot, user_id, full_fid, final_cap, final_kb, protect
            )
            if sent:
                await _send_autodelete_warning_and_schedule(
                    bot, user_id, chat_id, [sent]
                )
                return True

    return False


@Client.on_message(
    filters.command("start") & filters.private & filters.incoming, group=-3
)
async def genlink_start_interceptor(bot: Client, message: Message):
    if len(message.command) < 2 or not message.from_user:
        return

    cmd_data = message.command[1].strip()
    if cmd_data.startswith("olink_"):
        return

    decoded = _try_decode_base64_payload(cmd_data)
    is_batch_or_dstore = cmd_data.startswith(("BATCH-", "DSTORE-")) or (
        decoded and decoded.startswith(("BATCH-", "DSTORE-"))
    )

    is_genlink_single = False
    if not is_batch_or_dstore:
        if decoded and decoded.startswith(("file_", "filep_")):
            is_genlink_single = True
        elif cmd_data.startswith(("file_", "filep_")):
            gl_col = _get_writable_col("genlink_files", _genlink_db)
            if gl_col is not None:
                _, fid = cmd_data.split("_", 1)
                if not await get_file_details(fid):
                    try:
                        if await asyncio.wait_for(
                            gl_col.find_one({"_id": str(fid)}), timeout=2.0
                        ):
                            is_genlink_single = True
                    except Exception:
                        pass

    if not (is_batch_or_dstore or is_genlink_single):
        return

    if callable(ForceSub):
        status = await ForceSub(bot, message, file_id=cmd_data, mode="checksub")
        if not status:
            raise StopPropagation

    if await deliver_genlink_payload(
        bot, message.from_user.id, message.chat.id, cmd_data
    ):
        raise StopPropagation
