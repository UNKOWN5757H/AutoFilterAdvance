import asyncio
import hashlib
import html
import inspect
import re
import urllib.parse
from logging import ERROR, getLogger
from typing import Any, Dict, List, Optional, Set

from pyrogram import Client, StopPropagation, enums, filters
from pyrogram.errors import ChatWriteForbidden, Forbidden, PeerIdInvalid, UserIsBlocked
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

import info
from database.ia_filterdb import get_search_results
from database.users_chats_db import db as _db
from Script import script
from utils import get_size, temp

try:
    from database.plugin_dbs import plugin_db as _plugin_db
except ImportError:
    _plugin_db = None

try:
    from pyrogram.types import LinkPreviewOptions
except ImportError:
    LinkPreviewOptions = None

try:
    from pyrogram.types import ReplyParameters
except ImportError:
    ReplyParameters = None

# Share hidden-link button helpers with pm_filter.py
try:
    from plugins.pm_filter import (
        clean_filename,
        get_clean_words,
        register_hidden_link,
        sanitize_markup_hide_links,
    )
except ImportError:
    try:
        from pm_filter import (
            clean_filename,
            get_clean_words,
            register_hidden_link,
            sanitize_markup_hide_links,
        )
    except ImportError:
        clean_filename = None
        get_clean_words = None
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

_KNOWN_USERS_RAM: Set[int] = set()
_REPLY_PARAMS = set(inspect.signature(Message.reply_text).parameters.keys())

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


# ============================================================
# 🎨 HIDDEN-LINK BUTTON BUILDER & SAFE REPLY HELPERS
# ============================================================
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


def _prepare_reply_kwargs(
    kwargs: dict, disable_preview: Optional[bool] = True
) -> dict:
    clean_kw = dict(kwargs)
    if "reply_markup" in clean_kw and isinstance(
        clean_kw["reply_markup"], InlineKeyboardMarkup
    ):
        clean_kw["reply_markup"] = sanitize_markup_hide_links(clean_kw["reply_markup"])

    explicit_disable = clean_kw.pop("disable_web_page_preview", disable_preview)
    if explicit_disable is not None:
        if "link_preview_options" in _REPLY_PARAMS and LinkPreviewOptions is not None:
            try:
                clean_kw["link_preview_options"] = LinkPreviewOptions(
                    is_disabled=bool(explicit_disable)
                )
            except Exception:
                pass
        elif "disable_web_page_preview" in _REPLY_PARAMS:
            clean_kw["disable_web_page_preview"] = bool(explicit_disable)

    if "reply_to_message_id" in clean_kw:
        rep_id = clean_kw.pop("reply_to_message_id")
        if rep_id:
            if "reply_to_message_id" in _REPLY_PARAMS:
                clean_kw["reply_to_message_id"] = rep_id
            elif "reply_parameters" in _REPLY_PARAMS and ReplyParameters is not None:
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
    compat_kw = _prepare_reply_kwargs(kwargs, disable_preview=disable_web_page_preview)
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
    except Exception as e:
        logger.error(f"search_interceptor safe_reply_text error: {e}")
        return None


# ============================================================
# 👑 ADMIN, BAN & BACKGROUND USER REGISTRATION HELPERS
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


async def _is_user_banned(uid: int) -> bool:
    if not uid:
        return False
    if hasattr(temp, "BANNED_USERS") and uid in temp.BANNED_USERS:
        return True
    if _plugin_db is not None and hasattr(_plugin_db, "is_banned"):
        try:
            if await asyncio.wait_for(_plugin_db.is_banned(uid), timeout=1.5):
                return True
        except Exception:
            pass
    return False


async def _register_user_bg(client: Client, user):
    if not user or user.id in _KNOWN_USERS_RAM:
        return
    if len(_KNOWN_USERS_RAM) > 20000:
        _KNOWN_USERS_RAM.clear()
    _KNOWN_USERS_RAM.add(user.id)
    try:
        if not await asyncio.wait_for(_db.is_user_exist(user.id), timeout=2.0):
            await asyncio.wait_for(
                _db.add_user(user.id, user.first_name or "User"), timeout=2.0
            )
            log_channel = getattr(info, "LOG_CHANNEL", None)
            if log_channel and hasattr(script, "LOG_TEXT_P"):
                try:
                    await client.send_message(
                        int(log_channel),
                        script.LOG_TEXT_P.format(user.id, user.mention),
                    )
                except Exception:
                    pass
    except Exception:
        pass


# ============================================================
# 🔍 DIRECT DB FALLBACK SEARCH (TEXT-ONLY BUTTONS, ZERO LINKS)
# ============================================================
async def _fallback_pm_search(client: Client, message: Message, query: str):
    try:
        files, _, total_results = await get_search_results(
            query.lower(), offset=0, filter=True
        )
    except TypeError:
        files, _, total_results = await get_search_results(query.lower(), offset=0)

    safe_query = html.escape(query)
    if not files:
        return await safe_reply_text(
            message,
            f"❌ <b>No files found for:</b> <code>{safe_query}</code>\n\n"
            f"Please check the spelling or request it in our group!",
            parse_mode=enums.ParseMode.HTML,
        )

    c_words = await get_clean_words() if callable(get_clean_words) else []
    btn_rows: List[List[InlineKeyboardButton]] = []

    for file in files[:10]:
        f_id = (
            file.get("file_id")
            if isinstance(file, dict)
            else getattr(file, "file_id", "")
        )
        raw_name = str(
            file.get("file_name", "File")
            if isinstance(file, dict)
            else getattr(file, "file_name", "File")
        )
        f_size = get_size(
            int(
                file.get("file_size", 0)
                if isinstance(file, dict)
                else getattr(file, "file_size", 0)
            )
        )
        disp_name = (
            clean_filename(raw_name, c_words)
            if callable(clean_filename)
            else _clean_button_label(raw_name)[:45]
        )
        if f_id:
            btn_rows.append(
                [
                    create_btn(
                        text=f"[{f_size}] {disp_name}",
                        callback_data=f"file#{f_id}",
                    )
                ]
            )

    btn_rows.append([create_btn("🔐 Close", callback_data="close_data")])

    await safe_reply_text(
        message,
        f"🔍 <b>Search Results for:</b> <code>{safe_query}</code>\n"
        f"📁 <b>Total Found:</b> <code>{total_results}</code>\n\n"
        f"👇 <i>Click on a file button below to download:</i>",
        reply_markup=InlineKeyboardMarkup(btn_rows),
        parse_mode=enums.ParseMode.HTML,
    )


# ============================================================
# 🚨 CLEAN DEEP-LINK SEARCH INTERCEPTOR
# ============================================================
@Client.on_message(
    filters.command("start") & filters.private & filters.incoming, group=-99
)
async def intercept_direct_search(client: Client, message: Message):
    if len(message.command) < 2 or not message.command[1].startswith("search_"):
        return

    user = message.from_user
    uid = user.id if user else 0

    if getattr(info, "REPAIR_MODE", False) and uid not in get_admin_list():
        await safe_reply_text(
            message,
            "🛠️ <b>Bot is currently under maintenance!</b>",
            parse_mode=enums.ParseMode.HTML,
        )
        raise StopPropagation

    if uid and await _is_user_banned(uid):
        raise StopPropagation

    # Non-blocking background user registration so search results open instantly
    if user and uid not in _KNOWN_USERS_RAM:
        asyncio.create_task(_register_user_bg(client, user))

    raw_query = urllib.parse.unquote(message.command[1][len("search_") :])
    query = re.sub(r"[_+\-]+", " ", raw_query).strip()
    if not query:
        return

    try:
        try:
            from plugins.pm_filter import auto_filter
        except ImportError:
            from pm_filter import auto_filter

        message.text = query
        message.command = None
        await auto_filter(client, message)
    except Exception as e:
        logger.error(f"auto_filter failed in search_interceptor, using fallback: {e}")
        try:
            await _fallback_pm_search(client, message, query)
        except Exception as fallback_err:
            logger.error(f"Fallback search also failed: {fallback_err}")
            await safe_reply_text(
                message,
                f"🔍 <b>Search Query:</b> <code>{html.escape(query)}</code>\n\n"
                f"Tap the text above to copy it, then send it to me to search!",
                parse_mode=enums.ParseMode.HTML,
            )

    raise StopPropagation
