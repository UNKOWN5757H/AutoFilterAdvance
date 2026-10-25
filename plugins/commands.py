import asyncio
import builtins
import html
import inspect
import random
import re
import time
from logging import ERROR, getLogger
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from pyrogram import Client, StopPropagation, enums, filters
from pyrogram.errors import (
    ChatWriteForbidden,
    FloodWait,
    Forbidden,
    MediaEmpty,
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

# Ensure typing aliases exist in builtins before importing other plugins
for _t_name, _t_obj in (
    ("Tuple", Tuple),
    ("List", List),
    ("Dict", Dict),
    ("Optional", Optional),
    ("Union", Union),
    ("Set", Set),
    ("Any", Any),
):
    if not hasattr(builtins, _t_name):
        setattr(builtins, _t_name, _t_obj)

import info
from database.ia_filterdb import get_file_details
from database.users_chats_db import db as _db
from info import AUTH_CHANNEL, CUSTOM_FILE_CAPTION, PICS, REQ_CHANNEL
from Script import script
from utils import get_size, is_subscribed, temp

try:
    from database.ia_filterdb import (
        encode_file_id,
        get_all_healthy_read_dbs,
        get_writable_System_db,
        mark_db_error,
        update_cached_file_id,
    )
except ImportError:
    encode_file_id = None
    update_cached_file_id = None
    get_all_healthy_read_dbs = None
    get_writable_System_db = None
    mark_db_error = None

try:
    from plugins.uibuttons import (
        DEFAULT_CLEAN_WORDS,
        _invalidate_pm_filter_clean_cache,
        _normalize_pm_button_url,
        build_cleanwords_panel_ui,
        build_interactive_help_section,
        cw_db,
        format_script_text,
        get_clean_words_state,
        get_default_file_keyboard,
        get_deleted_file_notify_keyboard,
        get_help_keyboard,
        get_pm_autoreply_keyboard,
        get_pm_settings,
        get_start_keyboard,
        is_global_admin,
        is_user_banned,
        is_waiting_for_cmd_input,
        safe_parse_text_and_markup,
        save_clean_words_state,
        save_pm_settings,
    )
    from plugins.uibuttons import start_and_help_cmd as _uibuttons_start_help_cmd
    from plugins.uibuttons import upload_image_safely
except ImportError:
    from uibuttons import (
        DEFAULT_CLEAN_WORDS,
        _invalidate_pm_filter_clean_cache,
        _normalize_pm_button_url,
        build_cleanwords_panel_ui,
        build_interactive_help_section,
        cw_db,
        format_script_text,
        get_clean_words_state,
        get_default_file_keyboard,
        get_deleted_file_notify_keyboard,
        get_help_keyboard,
        get_pm_autoreply_keyboard,
        get_pm_settings,
        get_start_keyboard,
        is_global_admin,
        is_user_banned,
        is_waiting_for_cmd_input,
        safe_parse_text_and_markup,
        save_clean_words_state,
        save_pm_settings,
    )
    from uibuttons import start_and_help_cmd as _uibuttons_start_help_cmd
    from uibuttons import upload_image_safely

logger = getLogger(__name__)
logger.setLevel(ERROR)

# Safe optional import for ForceSub
try:
    from plugins.fsub import ForceSub
except Exception as _fsub_err:
    logger.error(f"Could not import ForceSub from plugins.fsub: {_fsub_err}")
    ForceSub = None


# ============================================================
# 🛡️ PYROGRAM v2.2.26 (LAYER 230) COMPATIBILITY ENGINE
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
    BTN_PRIMARY = BTN_SUCCESS = BTN_DANGER = None
    _SUPPORTS_BTN_STYLE = False


def create_btn(
    text: str,
    url: Optional[str] = None,
    callback_data: Optional[str] = None,
    style: Any = None,
) -> InlineKeyboardButton:
    kwargs: Dict[str, Any] = {"text": str(text)}
    if url:
        clean_u = str(url).strip()
        if clean_u and not clean_u.startswith(("http://", "https://", "tg://")):
            clean_u = "https://" + clean_u.lstrip("/")
        kwargs["url"] = clean_u
    elif callback_data:
        kwargs["callback_data"] = str(callback_data)[:64]
    if _SUPPORTS_BTN_STYLE and style is not None:
        kwargs["style"] = style
    try:
        return InlineKeyboardButton(**kwargs)
    except Exception:
        kwargs.pop("style", None)
        return InlineKeyboardButton(**kwargs)


def _prepare_compat_kwargs(
    kwargs: dict, supported_params: set, disable_preview: Optional[bool] = None
) -> dict:
    clean_kw = dict(kwargs)
    explicit_disable = clean_kw.pop("disable_web_page_preview", disable_preview)

    if explicit_disable is not None:
        if "disable_web_page_preview" in supported_params:
            clean_kw["disable_web_page_preview"] = bool(explicit_disable)
        elif (
            "link_preview_options" in supported_params
            and LinkPreviewOptions is not None
        ):
            try:
                clean_kw["link_preview_options"] = LinkPreviewOptions(
                    is_disabled=bool(explicit_disable)
                )
            except Exception:
                pass

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
):
    safe_txt = str(text or "Hello!").strip() or "Hello!"
    compat_kw = _prepare_compat_kwargs(
        kwargs, _REPLY_PARAMS, disable_preview=disable_web_page_preview
    )
    try:
        return await message.reply_text(safe_txt, **compat_kw)
    except TypeError:
        compat_kw.pop("disable_web_page_preview", None)
        compat_kw.pop("link_preview_options", None)
        compat_kw.pop("reply_parameters", None)
        compat_kw.pop("reply_to_message_id", None)
        try:
            return await message.reply_text(safe_txt, **compat_kw)
        except Exception:
            pass
    except (ChatWriteForbidden, Forbidden, UserIsBlocked, PeerIdInvalid):
        return None
    except Exception:
        pass

    compat_kw.pop("parse_mode", None)
    plain_txt = re.sub(r"<[^>]+>", "", safe_txt).strip() or "Hello!"
    try:
        return await message.reply_text(plain_txt, **compat_kw)
    except Exception:
        return None


async def safe_edit_text(
    message: Message, text: str, disable_web_page_preview: bool = True, **kwargs
):
    safe_txt = str(text or "Menu").strip() or "Menu"
    compat_kw = _prepare_compat_kwargs(
        kwargs, _EDIT_PARAMS, disable_preview=disable_web_page_preview
    )
    try:
        if getattr(message, "photo", None) or getattr(message, "video", None):
            edit_cap_kw = {
                k: v
                for k, v in compat_kw.items()
                if k in ("reply_markup", "parse_mode")
            }
            return await message.edit_caption(caption=safe_txt, **edit_cap_kw)
        return await message.edit_text(safe_txt, **compat_kw)
    except TypeError:
        compat_kw.pop("disable_web_page_preview", None)
        compat_kw.pop("link_preview_options", None)
        return await message.edit_text(safe_txt, **compat_kw)
    except (MessageNotModified, MessageIdInvalid, ChatWriteForbidden, Forbidden):
        return None
    except Exception:
        compat_kw.pop("parse_mode", None)
        plain_txt = re.sub(r"<[^>]+>", "", safe_txt).strip() or "Menu"
        try:
            return await message.edit_text(plain_txt, **compat_kw)
        except Exception:
            return None


async def safe_send_message(
    client: Client,
    chat_id: int,
    text: str,
    disable_web_page_preview: Optional[bool] = True,
    **kwargs,
):
    safe_txt = str(text or "Hello!").strip() or "Hello!"
    compat_kw = _prepare_compat_kwargs(
        kwargs, _SEND_MSG_PARAMS, disable_preview=disable_web_page_preview
    )
    try:
        return await client.send_message(chat_id=chat_id, text=safe_txt, **compat_kw)
    except TypeError:
        compat_kw.pop("disable_web_page_preview", None)
        compat_kw.pop("link_preview_options", None)
        compat_kw.pop("reply_parameters", None)
        compat_kw.pop("reply_to_message_id", None)
        return await client.send_message(chat_id=chat_id, text=safe_txt, **compat_kw)
    except (ChatWriteForbidden, Forbidden, UserIsBlocked, PeerIdInvalid):
        return None
    except Exception:
        compat_kw.pop("parse_mode", None)
        plain_txt = re.sub(r"<[^>]+>", "", safe_txt).strip() or "Hello!"
        try:
            return await client.send_message(
                chat_id=chat_id, text=plain_txt, **compat_kw
            )
        except Exception:
            return None


async def safe_answer(
    query: CallbackQuery,
    text: Optional[str] = None,
    show_alert: bool = False,
    url: Optional[str] = None,
):
    """Safely answers a CallbackQuery without ever raising QueryIdInvalid."""
    if not query:
        return
    try:
        kwargs: Dict[str, Any] = {"show_alert": show_alert}
        if text is not None:
            kwargs["text"] = str(text)[:200]
        if url is not None:
            kwargs["url"] = url
        await query.answer(**kwargs)
    except (QueryIdInvalid, Exception):
        pass


# ============================================================
# 🛡️ FAILSAFE /start & /help HANDLER (GROUP -14)
# ============================================================
_HANDLED_START_MSGS: Set[Tuple[int, int]] = set()


@Client.on_message(filters.command(["start", "help"]), group=-14)
async def failsafe_start_and_help_router(client: Client, message: Message):
    """
    Guarantees that `/start` and `/help` ALWAYS respond even if `uibuttons.py`
    was not registered in Pyrogram's plugin loader or encountered an error!
    Also prevents duplicate execution if `uibuttons.py` already handled the message.
    """
    if not message or not message.chat:
        return
    msg_key = (int(message.chat.id), int(message.id))
    if msg_key in _HANDLED_START_MSGS:
        return
    if len(_HANDLED_START_MSGS) > 5000:
        _HANDLED_START_MSGS.clear()
    _HANDLED_START_MSGS.add(msg_key)

    # Check if uibuttons.start_and_help_cmd is already registered in Pyrogram's dispatcher
    dispatcher = getattr(client, "dispatcher", None)
    if dispatcher and getattr(dispatcher, "groups", None):
        for grp_handlers in dispatcher.groups.values():
            for h in grp_handlers:
                cb = getattr(h, "callback", None)
                if cb and getattr(cb, "__name__", "") == "start_and_help_cmd":
                    return

    # If uibuttons handler wasn't registered by Pyrogram, execute it directly here!
    try:
        await _uibuttons_start_help_cmd(client, message)
    except Exception as e:
        logger.error(f"Failsafe /start error: {e}")
        uid = (
            message.from_user.id
            if message.from_user
            else getattr(message.sender_chat, "id", 0)
        )
        mention = message.from_user.mention if message.from_user else "User"
        kb = await get_start_keyboard(client, uid)
        await safe_reply_text(
            message,
            f"<b>Hello {mention}! 👋\n\nWelcome to {getattr(temp, 'B_NAME', 'MovieBot')}!</b>",
            reply_markup=kb,
            parse_mode=enums.ParseMode.HTML,
        )


# ============================================================
# 💾 QUOTA-SAFE MULTI-DB HELPERS FOR CLEAN WORDS & PM BUTTONS
# ============================================================
async def safe_update_clean_words(words_list: List[str], use_default: bool = False):
    """Delegates directly to uibuttons.save_clean_words_state so RAM + Multi-DB stay 100% synced."""
    await save_clean_words_state(words_list, use_default=use_default)


def _parse_pm_button_args(raw_input: str) -> Tuple[Optional[str], Optional[str], str]:
    """
    Parses PM button input in any of these formats:
    1. `Button Text | https://t.me/link | green`
    2. `Button Text - https://t.me/link`
    3. `[Button Text](https://t.me/link)`
    4. `Button Text | @ChannelUsername`
    """
    raw = str(raw_input or "").strip()
    if not raw:
        return None, None, "red"

    btn_text, btn_url, btn_color = None, None, "red"

    md_m = re.search(r"\[([^\[\]]+)\]\(\s*([^\(\)]+)\s*\)", raw)
    if md_m:
        btn_text = md_m.group(1).strip()
        btn_url = md_m.group(2).strip()
    elif "|" in raw:
        parts = [p.strip() for p in raw.split("|") if p.strip()]
        if len(parts) >= 2:
            btn_text, btn_url = parts[0], parts[1]
            if len(parts) > 2:
                btn_color = parts[2].lower()
    elif " - " in raw:
        parts = [p.strip() for p in raw.split(" - ", 1)]
        if len(parts) == 2:
            btn_text, btn_url = parts[0], parts[1]

    if btn_color not in ["green", "red", "blue", "normal"]:
        btn_color = "red"

    norm_url = _normalize_pm_button_url(btn_url)
    return btn_text, norm_url, btn_color


# ============================================================
# 📝 SAFE CUSTOM FILE CAPTION RENDERER (EXACT TEMPLATE, NO FORCED FILENAME)
# ============================================================
class _SafeCaptionMap(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def build_formatted_file_caption(
    title: str, size_str: str, raw_caption: str = ""
) -> str:
    """
    Renders `info.CUSTOM_FILE_CAPTION` exactly as configured:
    - Does NOT force-prepend the filename if `{file_name}` is not in your custom caption!
    - Supports `{file_name}`, `{filename}`, `{title}`, `{file_size}`, `{size}`, `{file_caption}`, `{caption}` if you choose to include them.
    """
    clean_title = html.escape(str(title or "File").strip())
    clean_size = html.escape(str(size_str or "").strip())
    orig_cap = str(raw_caption or "").strip()

    custom_cap = getattr(info, "CUSTOM_FILE_CAPTION", None)
    f_caption = ""

    if custom_cap and str(custom_cap).strip().lower() not in [
        "none",
        "off",
        "false",
        "",
    ]:
        tpl = str(custom_cap)
        mapping = _SafeCaptionMap(
            file_name="" if clean_title == "Unknown" else clean_title,
            filename="" if clean_title == "Unknown" else clean_title,
            title="" if clean_title == "Unknown" else clean_title,
            file_size="" if clean_size in ("0B", "0 Bytes") else clean_size,
            filesize="" if clean_size in ("0B", "0 Bytes") else clean_size,
            size="" if clean_size in ("0B", "0 Bytes") else clean_size,
            file_caption=orig_cap,
            caption=orig_cap,
        )
        try:
            f_caption = tpl.format_map(mapping).strip()
        except Exception:
            f_caption = (
                tpl.replace("{file_name}", clean_title)
                .replace("{filename}", clean_title)
                .replace("{title}", clean_title)
                .replace("{file_size}", clean_size)
                .replace("{filesize}", clean_size)
                .replace("{size}", clean_size)
                .replace("{file_caption}", orig_cap)
                .replace("{caption}", orig_cap)
                .strip()
            )
    else:
        if orig_cap:
            f_caption = orig_cap
        else:
            f_caption = (
                f"<b>📁 {clean_title} [{clean_size}]</b>"
                if clean_size and clean_size not in ("0B", "0 Bytes")
                else f"<b>📁 {clean_title}</b>"
            )

    if f_caption and not f_caption.startswith("<") and "<b>" not in f_caption:
        f_caption = f"<b>{f_caption}</b>"

    cap_plus = getattr(info, "CAPTION_PLUS", None)
    if cap_plus and str(cap_plus).strip().lower() not in ["none", "off", "false", ""]:
        f_caption = f"{f_caption}\n\n{cap_plus}" if f_caption else str(cap_plus)

    if len(f_caption) > 1024:
        f_caption = f_caption[:1020] + "</b>"

    return f_caption


# ============================================================
# 🛠️ HELPER FUNCTIONS
# ============================================================
def get_html_text(message: Message) -> Optional[str]:
    if message.reply_to_message:
        reply_msg = message.reply_to_message
        raw = reply_msg.text or reply_msg.caption
        if raw:
            return getattr(raw, "html", str(raw))
    if message.text and len(message.command) > 1:
        html_text = getattr(message.text, "html", str(message.text))
        return re.sub(r"^/\w+(?:@[a-zA-Z0-9_]+)?\s+", "", html_text, count=1)
    return None


def parse_timer(var_name: str, default_time: int = 1800) -> int:
    try:
        global_switch = getattr(info, "AUTO_DELETE", True)
        if str(global_switch).strip().lower() in ["false", "off", "0", "no"]:
            return 0
        val = getattr(info, var_name, getattr(info, "FILE_AUTO_DELETE", default_time))
        if isinstance(val, bool):
            return 1800 if val else 0
        parsed_time = int(str(val).strip())
        return 1800 if 0 < parsed_time < 10 else max(0, parsed_time)
    except Exception:
        return 1800


async def run_force_sub(client: Client, message: Message, file_id=False, mode=False):
    if not callable(ForceSub):
        return True
    try:
        return await ForceSub(client, message, file_id=file_id, mode=mode)
    except TypeError:
        try:
            return await ForceSub(client, message, file_id=file_id)
        except TypeError:
            return await ForceSub(client, message)
    except Exception as e:
        logger.error(f"ForceSub error: {e}")
        return True


# ============================================================
# ⏳ SILENT AUTO-DELETE ENGINE
# ============================================================
AUTO_DELETE_TASKS = set()


async def auto_delete_all_messages(
    client: Client, chat_id: int, is_pm: bool, delay: int, *messages
):
    await asyncio.sleep(delay)

    msg_ids = [m.id for m in messages if m is not None and hasattr(m, "id") and m.id]
    if msg_ids:
        try:
            await client.delete_messages(chat_id, msg_ids)
        except Exception:
            for msg in messages:
                if msg:
                    try:
                        await msg.delete()
                    except Exception:
                        pass

    if is_pm:
        notify_text = (
            getattr(info, "DEL_MSG", None)
            or "<b>Successfully deleted your file, if you want request again in group.</b>"
        )
        markup = get_deleted_file_notify_keyboard()
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


def schedule_pm_auto_delete(
    client: Client, chat_id: int, is_pm: bool, delay: int, *messages
):
    if delay <= 0:
        return
    task = asyncio.create_task(
        auto_delete_all_messages(client, chat_id, is_pm, delay, *messages)
    )
    AUTO_DELETE_TASKS.add(task)
    task.add_done_callback(AUTO_DELETE_TASKS.discard)


# ============================================================
# 🔧 SELF-HEALING MEDIA SENDER (FIXES [400 MEDIA_EMPTY] & PRESERVES CUSTOM CAPTION)
# ============================================================
async def _try_send_with_client(
    bot_client: Client,
    chat_id: int,
    fid: str,
    file_type: Optional[str],
    caption: str,
    reply_markup: Any,
    protect: bool,
) -> Optional[Message]:
    """
    Tries sending a file_id using send_cached_media and type-specific fallbacks.
    Also guarantees that `CUSTOM_FILE_CAPTION` and `reply_markup` are applied
    even if Telegram's `send_cached_media` ignores caption on certain document types!
    """
    if not fid:
        return None

    sent_msg: Optional[Message] = None
    try:
        sent_msg = await bot_client.send_cached_media(
            chat_id=chat_id,
            file_id=fid,
            caption=caption,
            reply_markup=reply_markup,
            protect_content=protect,
            parse_mode=enums.ParseMode.HTML,
        )
    except FloodWait as e:
        await asyncio.sleep(e.value + 1)
        try:
            sent_msg = await bot_client.send_cached_media(
                chat_id=chat_id,
                file_id=fid,
                caption=caption,
                reply_markup=reply_markup,
                protect_content=protect,
                parse_mode=enums.ParseMode.HTML,
            )
        except Exception:
            sent_msg = None
    except (UserIsBlocked, PeerIdInvalid):
        raise
    except Exception:
        sent_msg = None

    if not sent_msg:
        ft = str(file_type or "").lower()
        if "video" in ft:
            methods = [
                (bot_client.send_video, "video"),
                (bot_client.send_document, "document"),
            ]
        elif "audio" in ft:
            methods = [
                (bot_client.send_audio, "audio"),
                (bot_client.send_document, "document"),
            ]
        else:
            methods = [
                (bot_client.send_document, "document"),
                (bot_client.send_video, "video"),
                (bot_client.send_audio, "audio"),
            ]

        for fn, param_name in methods:
            try:
                sent_msg = await fn(
                    **{
                        "chat_id": chat_id,
                        param_name: fid,
                        "caption": caption,
                        "reply_markup": reply_markup,
                        "protect_content": protect,
                        "parse_mode": enums.ParseMode.HTML,
                    }
                )
                if sent_msg:
                    break
            except (UserIsBlocked, PeerIdInvalid):
                raise
            except Exception:
                continue

    if sent_msg and caption and not getattr(sent_msg, "caption", None):
        try:
            await sent_msg.edit_caption(
                caption=caption,
                reply_markup=reply_markup,
                parse_mode=enums.ParseMode.HTML,
            )
        except Exception:
            pass

    return sent_msg


async def _recover_and_send_media(
    main_bot: Client,
    user_id: int,
    short_id: str,
    file_obj: Any,
    final_caption: str,
    final_keyboard: Any,
    protect: bool,
) -> Optional[Message]:
    db_file_id = (
        file_obj.get("full_file_id", file_obj.get("file_id", short_id))
        if isinstance(file_obj, dict)
        else getattr(file_obj, "full_file_id", getattr(file_obj, "file_id", short_id))
    )
    file_type = (
        file_obj.get("file_type")
        if isinstance(file_obj, dict)
        else getattr(file_obj, "file_type", None)
    )
    src_chat_id = (
        file_obj.get("chat_id")
        if isinstance(file_obj, dict)
        else getattr(file_obj, "chat_id", None)
    )
    src_msg_id = (
        file_obj.get("msg_id")
        if isinstance(file_obj, dict)
        else getattr(file_obj, "msg_id", None)
    )

    candidate_fids = [db_file_id]
    if callable(encode_file_id):
        no_ref_fid = encode_file_id(str(short_id), "")
        if no_ref_fid and no_ref_fid not in candidate_fids:
            candidate_fids.append(no_ref_fid)

    # LAYER 1: Direct send via Main Bot
    for cand_fid in candidate_fids:
        sent = await _try_send_with_client(
            main_bot,
            user_id,
            cand_fid,
            file_type,
            final_caption,
            final_keyboard,
            protect,
        )
        if sent:
            return sent

    # LAYER 2: Fetch fresh message from source channel if chat_id & msg_id are saved
    if src_chat_id and src_msg_id:
        try:
            ch_msg = await main_bot.get_messages(int(src_chat_id), int(src_msg_id))
            if ch_msg and ch_msg.media:
                media_sub = getattr(ch_msg, ch_msg.media.value, None)
                fresh_fid = getattr(media_sub, "file_id", None)
                if fresh_fid:
                    if callable(update_cached_file_id):
                        asyncio.create_task(
                            update_cached_file_id(
                                short_id, fresh_fid, int(src_chat_id), int(src_msg_id)
                            )
                        )
                    sent = await _try_send_with_client(
                        main_bot,
                        user_id,
                        fresh_fid,
                        ch_msg.media.value,
                        final_caption,
                        final_keyboard,
                        protect,
                    )
                    if sent:
                        return sent
        except Exception:
            pass

    # LAYER 3: Worker Bot Relay (When a Worker Bot indexed the file and owns the file_id)
    try:
        from plugins.multibot import ensure_all_workers_started

        workers = await ensure_all_workers_started()
    except Exception:
        workers = []

    if workers:
        relay_channels = []
        for ch_candidate in (
            getattr(info, "LOG_CHANNEL", None),
            getattr(info, "INDEX_REQ_CHANNEL", None),
            *(getattr(info, "FILE_STORE_CHANNEL", []) or []),
            *(getattr(info, "CHANNELS", []) or []),
        ):
            if ch_candidate and int(ch_candidate) not in relay_channels:
                relay_channels.append(int(ch_candidate))

        for w_client in workers:
            for relay_chat in relay_channels:
                for cand_fid in candidate_fids:
                    relayed_msg = None
                    try:
                        relayed_msg = await _try_send_with_client(
                            w_client,
                            relay_chat,
                            cand_fid,
                            file_type,
                            caption="🔄",
                            reply_markup=None,
                            protect=False,
                        )
                    except Exception:
                        relayed_msg = None

                    if relayed_msg and relayed_msg.id:
                        try:
                            main_view = await main_bot.get_messages(
                                relay_chat, relayed_msg.id
                            )
                            try:
                                await w_client.delete_messages(
                                    relay_chat, relayed_msg.id
                                )
                            except Exception:
                                pass

                            if main_view and main_view.media:
                                m_obj = getattr(main_view, main_view.media.value, None)
                                new_main_fid = getattr(m_obj, "file_id", None)
                                if new_main_fid:
                                    if callable(update_cached_file_id):
                                        asyncio.create_task(
                                            update_cached_file_id(
                                                short_id, new_main_fid
                                            )
                                        )
                                    sent = await _try_send_with_client(
                                        main_bot,
                                        user_id,
                                        new_main_fid,
                                        main_view.media.value,
                                        final_caption,
                                        final_keyboard,
                                        protect,
                                    )
                                    if sent:
                                        return sent
                        except Exception:
                            try:
                                await w_client.delete_messages(
                                    relay_chat, relayed_msg.id
                                )
                            except Exception:
                                pass

    return None


# ============================================================
# 📦 SHARED FILE SENDER LOGIC & FILE CALLBACK HANDLER
# ============================================================
async def send_requested_file(
    client: Client,
    user_id: int,
    file_id: str,
    ident: str = "file",
    reply_target: Message = None,
    query: CallbackQuery = None,
):
    files_ = await get_file_details(file_id)
    if not files_:
        if query:
            await safe_answer(query, "⚠️ No such file exists.", show_alert=True)
        elif reply_target:
            await safe_reply_text(
                reply_target,
                "⚠️ No such file exists.",
                parse_mode=enums.ParseMode.HTML,
            )
        return

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
    raw_caption = str(
        files.get("caption", "")
        if isinstance(files, dict)
        else getattr(files, "caption", "")
    )

    f_caption = build_formatted_file_caption(title, size, raw_caption)

    default_btn = get_default_file_keyboard()
    final_caption, final_keyboard = safe_parse_text_and_markup(f_caption, default_btn)
    protect = True if ident in ["filep", "checksubp"] else False

    info_msg_txt = getattr(info, "INFO_MSG", None)
    info_img_val = getattr(info, "INFO_IMG", None)
    pre_info_msg = None
    if info_msg_txt or info_img_val:
        try:
            if info_img_val and str(info_img_val).lower() != "none":
                pre_info_msg = await client.send_photo(
                    chat_id=user_id,
                    photo=info_img_val,
                    caption=info_msg_txt or "",
                    parse_mode=enums.ParseMode.HTML,
                )
            elif info_msg_txt:
                pre_info_msg = await safe_send_message(
                    client,
                    chat_id=user_id,
                    text=info_msg_txt,
                    parse_mode=enums.ParseMode.HTML,
                )
        except Exception:
            pre_info_msg = None

    msg = None
    try:
        msg = await _recover_and_send_media(
            main_bot=client,
            user_id=user_id,
            short_id=file_id,
            file_obj=files,
            final_caption=final_caption,
            final_keyboard=final_keyboard,
            protect=protect,
        )
    except (UserIsBlocked, PeerIdInvalid):
        if query and getattr(temp, "U_NAME", None):
            return await safe_answer(
                query, url=f"https://t.me/{temp.U_NAME}?start={ident}_{file_id}"
            )
        return
    except Exception as err:
        logger.error(f"send_requested_file error: {err}")

    if not msg:
        err_note = (
            "⚠️ <b>Could not deliver this file (Invalid/Expired Media ID).</b>\n\n"
            "💡 <i>If you indexed this channel using Worker Bots, make sure your Worker Bots are also Admins in your LOG_CHANNEL or re-index with the updated indexer!</i>"
        )
        if query:
            return await safe_answer(
                query,
                "⚠️ Could not deliver file (Invalid/Expired Media ID).",
                show_alert=True,
            )
        if reply_target:
            return await safe_reply_text(
                reply_target,
                err_note,
                parse_mode=enums.ParseMode.HTML,
            )
        return

    if query:
        await safe_answer(query, "📥 File sent to your PM!")

    if msg:
        try:
            delete_timer = parse_timer("FILE_AUTO_DELETE", 1800)
            m, s = divmod(delete_timer, 60)
            time_str = f"{m} Minutes {s} Seconds" if s > 0 else f"{m} Minutes"

            warn_text = (
                f"<b>📢 Please Note\n\n"
                f"✅ The above file will be autodeleted in {time_str} to avoid copyright issues.\n\n"
                f"✅ Please forward this file to your saved messages and start downloading from there.\n\n"
                f"Tᴇᴀᴍ: @KR_Picture</b>"
            )
            k = await safe_send_message(
                client,
                chat_id=user_id,
                text=warn_text,
                reply_to_message_id=msg.id,
                parse_mode=enums.ParseMode.HTML,
            )

            if delete_timer > 0:
                schedule_pm_auto_delete(
                    client, user_id, True, delete_timer, pre_info_msg, msg, k
                )
        except Exception as e:
            logger.error(f"Auto-delete warning failed to send: {e}")


@Client.on_callback_query(filters.regex(r"^(file|checksub)"))
async def file_cb_handler(client: Client, query: CallbackQuery):
    uid = (
        query.from_user.id
        if query.from_user
        else getattr(query.message.sender_chat, "id", 0)
    )
    if getattr(info, "REPAIR_MODE", False) and not await is_global_admin(uid):
        return await safe_answer(query, "🛠️ Bot is under maintenance!", show_alert=True)

    if (
        query.data.startswith("checksub")
        and (AUTH_CHANNEL or REQ_CHANNEL)
        and not await is_subscribed(client, query)
    ):
        return await safe_answer(
            query,
            "⚠️ Please join our channel first, then click Try Again! Team: @KR_PICTURE",
            show_alert=True,
        )

    try:
        ident, file_id = query.data.split("#", 1)
    except ValueError:
        return await safe_answer(query, "⚠️ Invalid button data!", show_alert=True)

    await send_requested_file(
        client=client,
        user_id=query.from_user.id,
        file_id=file_id,
        ident=ident,
        query=query,
    )


# ============================================================
# ⚙️ CLEAN FILENAME COMMANDS (ADMIN ONLY - QUOTA SAFE)
# ============================================================
@Client.on_message(
    filters.command(["listcleanfilename", "cleanfilenames", "cleanwords", "cleanfile"]),
    group=-15,
)
async def list_clean_words_cmd(client: Client, message: Message):
    uid = (
        message.from_user.id
        if message.from_user
        else getattr(message.sender_chat, "id", 0)
    )
    if not await is_global_admin(uid):
        return await safe_reply_text(
            message,
            "❌ <b>Unauthorized:</b> Global Bot Admin only.",
            parse_mode=enums.ParseMode.HTML,
        )

    text, markup = await build_cleanwords_panel_ui()
    await safe_reply_text(
        message,
        text,
        reply_markup=markup,
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(filters.command("addcleanfilename"), group=-15)
async def add_clean_words_cmd(client: Client, message: Message):
    uid = (
        message.from_user.id
        if message.from_user
        else getattr(message.sender_chat, "id", 0)
    )
    if not await is_global_admin(uid):
        return await safe_reply_text(
            message,
            "❌ <b>Unauthorized:</b> Global Bot Admin only.",
            parse_mode=enums.ParseMode.HTML,
        )

    if len(message.command) < 2:
        text, markup = await build_cleanwords_panel_ui()
        return await safe_reply_text(
            message,
            "⚠️ <b>Usage:</b> <code>/addcleanfilename word1, word2, @ChannelName</code>\n\n"
            + text,
            reply_markup=markup,
            parse_mode=enums.ParseMode.HTML,
        )

    new_words = [
        w.strip() for w in message.text.split(None, 1)[1].split(",") if w.strip()
    ]
    if new_words:
        _, cur_words = await get_clean_words_state()
        merged = list(dict.fromkeys((cur_words or []) + new_words))
        await safe_update_clean_words(merged, use_default=False)
        text, markup = await build_cleanwords_panel_ui()
        await safe_reply_text(
            message,
            f"✅ <b>Added {len(new_words)} word(s) to Clean Filename Manager!</b>\n\n{text}",
            reply_markup=markup,
            parse_mode=enums.ParseMode.HTML,
        )


@Client.on_message(filters.command("setcleanfilename"), group=-15)
async def set_clean_words(client: Client, message: Message):
    uid = (
        message.from_user.id
        if message.from_user
        else getattr(message.sender_chat, "id", 0)
    )
    if not await is_global_admin(uid):
        return await safe_reply_text(
            message,
            "❌ <b>Unauthorized:</b> Global Bot Admin only.",
            parse_mode=enums.ParseMode.HTML,
        )

    if len(message.command) < 2:
        text, markup = await build_cleanwords_panel_ui()
        return await safe_reply_text(
            message,
            "⚠️ <b>Usage:</b> <code>/setcleanfilename word1, word2, @ChannelName</code>\n\n"
            + text,
            reply_markup=markup,
            parse_mode=enums.ParseMode.HTML,
        )
    words_list = [
        w.strip() for w in message.text.split(None, 1)[1].split(",") if w.strip()
    ]
    await safe_update_clean_words(words_list, use_default=False)
    text, markup = await build_cleanwords_panel_ui()
    await safe_reply_text(
        message,
        f"✅ <b>Clean Words Updated Successfully!</b>\n\n{text}",
        reply_markup=markup,
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(filters.command("defaultcleanfilename"), group=-15)
async def default_clean_words(client: Client, message: Message):
    uid = (
        message.from_user.id
        if message.from_user
        else getattr(message.sender_chat, "id", 0)
    )
    if not await is_global_admin(uid):
        return await safe_reply_text(
            message,
            "❌ <b>Unauthorized:</b> Global Bot Admin only.",
            parse_mode=enums.ParseMode.HTML,
        )

    await safe_update_clean_words(list(DEFAULT_CLEAN_WORDS), use_default=True)
    text, markup = await build_cleanwords_panel_ui()
    await safe_reply_text(
        message,
        f"✅ <b>Reverted to Default Clean Words!</b>\n\n{text}",
        reply_markup=markup,
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(filters.command("remcleanfilename"), group=-15)
async def rem_clean_words(client: Client, message: Message):
    uid = (
        message.from_user.id
        if message.from_user
        else getattr(message.sender_chat, "id", 0)
    )
    if not await is_global_admin(uid):
        return await safe_reply_text(
            message,
            "❌ <b>Unauthorized:</b> Global Bot Admin only.",
            parse_mode=enums.ParseMode.HTML,
        )

    await safe_update_clean_words([], use_default=False)
    text, markup = await build_cleanwords_panel_ui()
    await safe_reply_text(
        message,
        f"🗑️ <b>All Custom Clean Words Removed!</b>\n<i>(Note: Stylish fonts, @words and symbols are still always stripped automatically)</i>\n\n{text}",
        reply_markup=markup,
        parse_mode=enums.ParseMode.HTML,
    )


# ============================================================
# ⚙️ PM REPLY SETTINGS SETUP COMMANDS (ADMIN ONLY)
# ============================================================
@Client.on_message(filters.command("setpmtext"), group=-15)
async def set_pm_text(client: Client, message: Message):
    uid = (
        message.from_user.id
        if message.from_user
        else getattr(message.sender_chat, "id", 0)
    )
    if not await is_global_admin(uid):
        return await safe_reply_text(
            message,
            "❌ <b>Unauthorized:</b> Global Bot Admin only.",
            parse_mode=enums.ParseMode.HTML,
        )
    try:
        text = get_html_text(message)
        if not text:
            return await safe_reply_text(
                message,
                "⚙️ <b>Usage:</b> <code>/setpmtext Your Text Here</code> or reply to a message.",
                parse_mode=enums.ParseMode.HTML,
            )
        await save_pm_settings("text", text)
        await safe_reply_text(
            message,
            f"✅ <b>PM Text updated successfully to:</b>\n\n{text}",
            parse_mode=enums.ParseMode.HTML,
        )
    except Exception as e:
        await safe_reply_text(message, f"⚠️ Error: {e}")


@Client.on_message(filters.command("rempmtext"), group=-15)
async def rem_pm_text(client: Client, message: Message):
    uid = (
        message.from_user.id
        if message.from_user
        else getattr(message.sender_chat, "id", 0)
    )
    if not await is_global_admin(uid):
        return await safe_reply_text(
            message,
            "❌ <b>Unauthorized:</b> Global Bot Admin only.",
            parse_mode=enums.ParseMode.HTML,
        )
    await save_pm_settings(
        "text",
        "<b>🚫 Don't Message Here, Message Here Only!</b>\n\nI do not respond to direct messages in PM. Please join our official group to request and download movies.",
    )
    await safe_reply_text(
        message,
        "✅ <b>PM Text reset to default.</b>",
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(filters.command("setpmimage"), group=-15)
async def set_pm_image(client: Client, message: Message):
    uid = (
        message.from_user.id
        if message.from_user
        else getattr(message.sender_chat, "id", 0)
    )
    if not await is_global_admin(uid):
        return await safe_reply_text(
            message,
            "❌ <b>Unauthorized:</b> Global Bot Admin only.",
            parse_mode=enums.ParseMode.HTML,
        )
    target_photo_msg = (
        message.reply_to_message
        if (message.reply_to_message and message.reply_to_message.photo)
        else (message if message.photo else None)
    )
    if not target_photo_msg:
        return await safe_reply_text(
            message,
            "⚙️ <b>Usage:</b> Reply to a photo with <code>/setpmimage</code>",
            parse_mode=enums.ParseMode.HTML,
        )

    status = await safe_reply_text(
        message, "⏳ <b>Uploading to Cloud...</b>", parse_mode=enums.ParseMode.HTML
    )
    url = await upload_image_safely(client, target_photo_msg)
    if url:
        await save_pm_settings("image", url)
        if status:
            await safe_edit_text(
                status,
                "✅ <b>PM Image updated successfully!</b>",
                parse_mode=enums.ParseMode.HTML,
            )
    else:
        file_id = target_photo_msg.photo.file_id
        await save_pm_settings("image", file_id)
        if status:
            await safe_edit_text(
                status,
                "⚠️ Cloud upload failed. <b>PM Image saved using Telegram File_ID!</b>",
                parse_mode=enums.ParseMode.HTML,
            )


@Client.on_message(filters.command("rempmimage"), group=-15)
async def rem_pm_image(client: Client, message: Message):
    uid = (
        message.from_user.id
        if message.from_user
        else getattr(message.sender_chat, "id", 0)
    )
    if not await is_global_admin(uid):
        return await safe_reply_text(
            message,
            "❌ <b>Unauthorized:</b> Global Bot Admin only.",
            parse_mode=enums.ParseMode.HTML,
        )
    await save_pm_settings("image", None)
    await safe_reply_text(
        message, "✅ <b>PM Image removed.</b>", parse_mode=enums.ParseMode.HTML
    )


@Client.on_message(filters.command("setpmbutton"), group=-15)
async def set_pm_button(client: Client, message: Message):
    uid = (
        message.from_user.id
        if message.from_user
        else getattr(message.sender_chat, "id", 0)
    )
    if not await is_global_admin(uid):
        return await safe_reply_text(
            message,
            "❌ <b>Unauthorized:</b> Global Bot Admin only.",
            parse_mode=enums.ParseMode.HTML,
        )
    try:
        raw_arg = (
            message.text.split(None, 1)[1].strip()
            if (message.text and len(message.command) >= 2)
            else ""
        )
        if not raw_arg and message.reply_to_message:
            raw_arg = (
                message.reply_to_message.text or message.reply_to_message.caption or ""
            ).strip()

        if not raw_arg:
            return await safe_reply_text(
                message,
                "⚙️ <b>Usage:</b>\n"
                "• <code>/setpmbutton Text | https://t.me/link | green</code>\n"
                "• <code>/setpmbutton Text - https://t.me/link</code>\n"
                "• <code>/setpmbutton [Text](https://t.me/link)</code>",
                parse_mode=enums.ParseMode.HTML,
            )

        btn_text, btn_url, btn_color = _parse_pm_button_args(raw_arg)
        if not btn_text or not btn_url:
            return await safe_reply_text(
                message,
                "❌ <b>Invalid button format.</b>\n"
                "Use: <code>/setpmbutton Text | https://t.me/your_group | green</code>",
                parse_mode=enums.ParseMode.HTML,
            )

        await save_pm_settings("button_text", btn_text)
        await save_pm_settings("button_url", btn_url)
        await save_pm_settings("button_color", btn_color)

        preview_kb = get_pm_autoreply_keyboard(btn_text, btn_url, btn_color)
        await safe_reply_text(
            message,
            f"✅ <b>PM Auto-Reply Button Updated!</b>\n\n"
            f"🔘 <b>Text:</b> <code>{html.escape(btn_text)}</code>\n"
            f"🔗 <b>URL:</b> <code>{html.escape(btn_url)}</code>\n"
            f"🎨 <b>Color:</b> <code>{btn_color.upper()}</code>",
            reply_markup=preview_kb,
            parse_mode=enums.ParseMode.HTML,
        )
    except Exception as e:
        await safe_reply_text(message, f"⚠️ Error: {e}")


@Client.on_message(filters.command("rempmbutton"), group=-15)
async def rem_pm_button(client: Client, message: Message):
    uid = (
        message.from_user.id
        if message.from_user
        else getattr(message.sender_chat, "id", 0)
    )
    if not await is_global_admin(uid):
        return await safe_reply_text(
            message,
            "❌ <b>Unauthorized:</b> Global Bot Admin only.",
            parse_mode=enums.ParseMode.HTML,
        )
    await save_pm_settings("button_text", None)
    await save_pm_settings("button_url", None)
    await safe_reply_text(
        message,
        "✅ <b>PM Button removed completely.</b>",
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(filters.command(["pmautoreply", "pmreply"]), group=-15)
async def toggle_pm_autoreply_cmd(client: Client, message: Message):
    uid = (
        message.from_user.id
        if message.from_user
        else getattr(message.sender_chat, "id", 0)
    )
    if not await is_global_admin(uid):
        return await safe_reply_text(
            message,
            "❌ <b>Unauthorized:</b> Global Bot Admin only.",
            parse_mode=enums.ParseMode.HTML,
        )

    settings = await get_pm_settings()
    cur = bool(settings.get("enabled", True))
    if len(message.command) > 1:
        arg = message.command[1].strip().lower()
        new_val = (
            True
            if arg in ["on", "enable", "true", "1", "yes"]
            else False if arg in ["off", "disable", "false", "0", "no"] else (not cur)
        )
    else:
        new_val = not cur

    await save_pm_settings("enabled", new_val)
    text, markup = await build_interactive_help_section(
        client,
        "helps_pmautoreply",
        uid,
        message.from_user.mention if message.from_user else "Admin",
        message,
    )
    await safe_reply_text(
        message,
        text,
        reply_markup=markup,
        parse_mode=enums.ParseMode.HTML,
    )


# ============================================================
# 📩 PM AUTO-REPLY ENGINE (ANTI-DUPLICATE & DEBOUNCED)
# ============================================================
_PM_REPLIED_MSG_KEYS: Set[Tuple[int, int]] = set()
_PM_USER_LAST_REPLY_TS: Dict[int, float] = {}


@Client.on_message(
    filters.private & filters.incoming & ~filters.bot & ~filters.service,
    group=1,
)
async def pm_auto_reply(client: Client, message: Message):
    if not message or not message.chat:
        return

    raw_txt = (message.text or message.caption or "").strip()
    if raw_txt.startswith("/"):
        return

    if is_waiting_for_cmd_input(message.chat.id):
        return

    try:
        from plugins.multibot import _MB_WAITING_INPUT

        if message.chat.id in _MB_WAITING_INPUT:
            return
    except Exception:
        pass

    try:
        from plugins.datadb import _DATADB_WAITING_INPUT

        if message.chat.id in _DATADB_WAITING_INPUT:
            return
    except Exception:
        pass

    try:
        from plugins.post_handler import _WAITING_REQUESTS as _POST_WAIT

        if message.chat.id in _POST_WAIT:
            return
    except Exception:
        pass

    try:
        from plugins.fsub import _WAITING_REQUESTS as _FSUB_WAIT

        if message.chat.id in _FSUB_WAIT:
            return
    except Exception:
        pass

    uid = (
        message.from_user.id
        if message.from_user
        else getattr(message.sender_chat, "id", 0)
    )

    if getattr(info, "REPAIR_MODE", False) and not await is_global_admin(uid):
        return
    if message.from_user and await is_user_banned(uid):
        return

    msg_key = (int(message.chat.id), int(message.id))
    if msg_key in _PM_REPLIED_MSG_KEYS:
        raise StopPropagation
    if len(_PM_REPLIED_MSG_KEYS) > 5000:
        _PM_REPLIED_MSG_KEYS.clear()
    _PM_REPLIED_MSG_KEYS.add(msg_key)

    now = time.time()
    last_ts = _PM_USER_LAST_REPLY_TS.get(int(message.chat.id), 0.0)
    if (now - last_ts) < 2.0:
        raise StopPropagation
    if len(_PM_USER_LAST_REPLY_TS) > 5000:
        _PM_USER_LAST_REPLY_TS.clear()
    _PM_USER_LAST_REPLY_TS[int(message.chat.id)] = now

    settings = await get_pm_settings()
    if not settings.get("enabled", True):
        return

    if await is_global_admin(uid):
        if message.forward_from_chat or getattr(message, "forward_origin", None):
            return
        if message.document or message.video or message.audio:
            return
        if not settings.get("reply_admins", True):
            return

    text = settings.get("text", "<b>🚫 Don't Message Here, Message Here Only!</b>")
    pm_img = settings.get("image", getattr(info, "NOT_FOUND_IMG", None))
    btn_text = settings.get("button_text", "💬 Message Here Only")
    btn_url = settings.get("button_url", "https://t.me/Sandalwood_Kannada_Group")
    btn_color_str = str(settings.get("button_color", "red")).lower()

    default_markup = get_pm_autoreply_keyboard(btn_text, btn_url, btn_color_str)

    final_text, final_markup = safe_parse_text_and_markup(text, default_markup)
    final_text = final_text or text

    sent = None
    try:
        if pm_img and str(pm_img).lower() != "none" and len(final_text) <= 1024:
            try:
                sent = await message.reply_photo(
                    photo=pm_img,
                    caption=final_text,
                    reply_markup=final_markup,
                    parse_mode=enums.ParseMode.HTML,
                )
            except Exception:
                sent = None

        if not sent:
            await safe_reply_text(
                message,
                text=final_text,
                reply_markup=final_markup,
                parse_mode=enums.ParseMode.HTML,
                disable_web_page_preview=True,
            )
    except Exception as e:
        logger.error(f"PM Reply Error: {e}")

    raise StopPropagation
