import asyncio
import hashlib
import html
import inspect
import re
import time
import urllib.parse
from logging import ERROR, getLogger
from typing import Any, Dict, List, Optional, Tuple

import requests
from motor.motor_asyncio import AsyncIOMotorClient
from pyrogram import Client, StopPropagation, enums, filters
from pyrogram.errors import (
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
from requests.adapters import HTTPAdapter

import info

logger = getLogger(__name__)
logger.setLevel(ERROR)

# ============================================================
# 🛡️ SAFE OPTIONAL IMPORTS (MULTI-DB & HIDDEN-LINK REGISTRY)
# ============================================================
try:
    from database.ia_filterdb import get_all_healthy_read_dbs, get_writable_System_db
except Exception:
    get_all_healthy_read_dbs = None
    get_writable_System_db = None

try:
    from pyrogram.types import LinkPreviewOptions
except ImportError:
    LinkPreviewOptions = None

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


# ============================================================
# 🎨 BUTTON BUILDER (ZERO VISIBLE LINKS INSIDE ANY BUTTON)
# ============================================================
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


# ============================================================
# 🛡️ PYROGRAM v2.2.26 SAFE MESSAGE & CALLBACK HELPERS
# ============================================================
_REPLY_PARAMS = set(inspect.signature(Message.reply_text).parameters.keys())
_EDIT_PARAMS = set(inspect.signature(Message.edit_text).parameters.keys())


def _preview_off_kw(supported_params: set) -> Dict[str, Any]:
    if "link_preview_options" in supported_params and LinkPreviewOptions is not None:
        try:
            return {"link_preview_options": LinkPreviewOptions(is_disabled=True)}
        except Exception:
            pass
    if "disable_web_page_preview" in supported_params:
        return {"disable_web_page_preview": True}
    return {}


async def safe_reply_text(
    message: Message,
    text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
) -> Optional[Message]:
    if not message:
        return None
    reply_markup = sanitize_markup_hide_links(reply_markup)
    try:
        return await message.reply_text(
            text=text,
            reply_markup=reply_markup,
            parse_mode=enums.ParseMode.HTML,
            **_preview_off_kw(_REPLY_PARAMS),
        )
    except (ChatWriteForbidden, Forbidden, UserIsBlocked, PeerIdInvalid):
        return None
    except Exception as e:
        logger.error(f"shortner safe_reply_text error: {e}")
        return None


async def safe_edit_text(
    message: Message,
    text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
) -> Optional[Message]:
    if not message:
        return None
    reply_markup = sanitize_markup_hide_links(reply_markup)
    try:
        if getattr(message, "photo", None) or getattr(message, "video", None):
            return await message.edit_caption(
                caption=text,
                reply_markup=reply_markup,
                parse_mode=enums.ParseMode.HTML,
            )
        return await message.edit_text(
            text=text,
            reply_markup=reply_markup,
            parse_mode=enums.ParseMode.HTML,
            **_preview_off_kw(_EDIT_PARAMS),
        )
    except (MessageNotModified, MessageIdInvalid, ChatWriteForbidden, Forbidden):
        return None
    except Exception as e:
        logger.error(f"shortner safe_edit_text error: {e}")
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
# 👑 ADMIN VERIFICATION
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


async def _require_global_admin(message: Message) -> bool:
    uid = (
        message.from_user.id
        if message.from_user
        else getattr(message.sender_chat, "id", 0)
    )
    if await is_global_admin(uid):
        return True
    await safe_reply_text(message, "❌ <b>Unauthorized:</b> Global Bot Admin only.")
    return False


# ============================================================
# 💾 MULTI-DB + RAM SHORTENER CONFIG ENGINE
# ============================================================
_shortner_col = None
try:
    _DB_CLIENT = AsyncIOMotorClient(
        info.DATABASE_URI,
        serverSelectionTimeoutMS=4000,
        connectTimeoutMS=4000,
        socketTimeoutMS=8000,
    )
    _BOT_DB = _DB_CLIENT[info.DATABASE_NAME]
    _shortner_col = _BOT_DB["shortener_settings"]
except Exception as e:
    logger.error(f"Failed to init shortner DB: {e}")


def _clean_site_domain(raw_site: str) -> str:
    if not raw_site:
        return ""
    s = str(raw_site).strip().lower()
    if s in ("none", "null", "off", "false", "reset"):
        return ""
    s = re.sub(r"^(?:https?://)?(?:www\.)?", "", s)
    return s.split("/")[0].strip()


_SHORTENER_RAM_CONFIG: Dict[str, Any] = {
    "enabled": bool(getattr(info, "SHORTLINK", False)),
    "site": _clean_site_domain(
        str(getattr(info, "SHORTLINK_URL", getattr(info, "SHORTENER_SITE", "")) or "")
    ),
    "api": str(
        getattr(info, "SHORTLINK_API", getattr(info, "SHORTENER_API", "")) or ""
    ).strip(),
    "updated_at": 0.0,
}
_SHORTENER_CACHE_TS: float = 0.0
_SHORT_URL_CACHE: Dict[Tuple[str, str, str], Tuple[float, str]] = {}

# Persistent connection-pooled HTTP session for fast concurrent link shortening
_HTTP_SESSION = requests.Session()
_HTTP_ADAPTER = HTTPAdapter(pool_connections=20, pool_maxsize=50, max_retries=1)
_HTTP_SESSION.mount("https://", _HTTP_ADAPTER)
_HTTP_SESSION.mount("http://", _HTTP_ADAPTER)
_HTTP_SESSION.headers.update(
    {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
    }
)


def _get_all_shortner_cols() -> List[Any]:
    cols = []
    if callable(get_writable_System_db):
        try:
            w_db = get_writable_System_db()
            if w_db is not None:
                cols.append(w_db["shortener_settings"])
        except Exception:
            pass
    if callable(get_all_healthy_read_dbs):
        try:
            for _, r_db in get_all_healthy_read_dbs():
                c = r_db["shortener_settings"]
                if c not in cols:
                    cols.append(c)
        except Exception:
            pass
    if _shortner_col is not None and _shortner_col not in cols:
        cols.append(_shortner_col)
    return cols


async def get_shortener_config(force_refresh: bool = False) -> Dict[str, Any]:
    global _SHORTENER_CACHE_TS
    now = time.time()
    if (
        not force_refresh
        and _SHORTENER_CACHE_TS > 0
        and (now - _SHORTENER_CACHE_TS) < 300
    ):
        return _SHORTENER_RAM_CONFIG

    best_doc = None
    best_ts = -1.0

    for col in _get_all_shortner_cols():
        try:
            doc = await asyncio.wait_for(
                col.find_one({"_id": "shortener_config"}), timeout=2.5
            )
            if doc:
                doc_ts = float(doc.get("updated_at", 0.0) or 0.0)
                if best_doc is None or doc_ts >= best_ts:
                    best_doc = doc
                    best_ts = doc_ts
        except Exception:
            continue

    if best_doc and best_ts >= float(
        _SHORTENER_RAM_CONFIG.get("updated_at", 0.0) or 0.0
    ):
        _SHORTENER_RAM_CONFIG["enabled"] = bool(best_doc.get("enabled", False))
        _SHORTENER_RAM_CONFIG["site"] = _clean_site_domain(best_doc.get("site", ""))
        _SHORTENER_RAM_CONFIG["api"] = str(best_doc.get("api", "") or "").strip()
        _SHORTENER_RAM_CONFIG["updated_at"] = best_ts

    _SHORTENER_CACHE_TS = now
    return _SHORTENER_RAM_CONFIG


async def save_shortener_config(
    enabled: Optional[bool] = None,
    site: Optional[str] = None,
    api: Optional[str] = None,
) -> Dict[str, Any]:
    global _SHORTENER_CACHE_TS
    await get_shortener_config()
    now = time.time()

    if site is not None:
        _SHORTENER_RAM_CONFIG["site"] = _clean_site_domain(site)
    if api is not None:
        clean_api = str(api).strip()
        if clean_api.lower() in ("none", "null", "off", "false", "reset"):
            clean_api = ""
        _SHORTENER_RAM_CONFIG["api"] = clean_api

    if enabled is not None:
        _SHORTENER_RAM_CONFIG["enabled"] = bool(enabled)
    elif _SHORTENER_RAM_CONFIG["site"] and _SHORTENER_RAM_CONFIG["api"]:
        _SHORTENER_RAM_CONFIG["enabled"] = True

    _SHORTENER_RAM_CONFIG["updated_at"] = now
    _SHORTENER_CACHE_TS = now
    _SHORT_URL_CACHE.clear()

    payload = {
        "enabled": _SHORTENER_RAM_CONFIG["enabled"],
        "site": _SHORTENER_RAM_CONFIG["site"],
        "api": _SHORTENER_RAM_CONFIG["api"],
        "updated_at": now,
    }
    for col in _get_all_shortner_cols():
        try:
            await asyncio.wait_for(
                col.update_one(
                    {"_id": "shortener_config"}, {"$set": payload}, upsert=True
                ),
                timeout=2.5,
            )
        except Exception:
            continue

    return _SHORTENER_RAM_CONFIG


# ============================================================
# 🔗 FAST LINK SHORTENER ENGINE (POOLED + SMART TTL CACHE)
# ============================================================
def _is_valid_short_url(url: str, domain: str) -> bool:
    if not url or not url.startswith(("http://", "https://")):
        return False
    if " " in url or "<html" in url.lower():
        return False
    # Reject bare domain root with no shortened path
    stripped = re.sub(r"^https?://(?:www\.)?", "", url).rstrip("/")
    return stripped.lower() != domain.lower()


def _shorten_sync(site: str, api: str, long_url: str) -> str:
    if not site or not api or not long_url:
        return long_url

    domain = _clean_site_domain(site)
    if not domain:
        return long_url

    encoded_url = urllib.parse.quote(long_url, safe="")
    endpoints = []

    if "shareus" in domain:
        endpoints.extend(
            [
                f"https://api.shareus.io/easy_api?key={api}&link={encoded_url}",
                f"https://{domain}/easy_api?key={api}&link={encoded_url}",
            ]
        )
    elif "ouo.io" in domain or "ouo.press" in domain:
        endpoints.append(f"https://ouo.io/api/{api}?s={encoded_url}")

    endpoints.extend(
        [
            f"https://{domain}/api?api={api}&url={encoded_url}",
            f"https://{domain}/api?api={api}&url={encoded_url}&format=text",
        ]
    )

    for api_url in endpoints:
        try:
            resp = _HTTP_SESSION.get(api_url, timeout=3.5)
            if resp.status_code != 200:
                continue

            raw_text = resp.text.strip()
            if _is_valid_short_url(raw_text, domain):
                return raw_text

            data = resp.json()
            if isinstance(data, dict):
                nested = data.get("data") if isinstance(data.get("data"), dict) else {}
                short = (
                    data.get("shortenedUrl")
                    or data.get("shorturl")
                    or data.get("short_url")
                    or data.get("result_url")
                    or data.get("link")
                    or data.get("url")
                    or nested.get("shortenedUrl")
                    or nested.get("short_url")
                    or nested.get("url")
                )
                if short and _is_valid_short_url(str(short).strip(), domain):
                    return str(short).strip()
        except Exception:
            continue

    return long_url


def _prune_short_cache(now: float):
    expired = [k for k, (exp, _) in list(_SHORT_URL_CACHE.items()) if now >= exp]
    for k in expired:
        _SHORT_URL_CACHE.pop(k, None)
    if len(_SHORT_URL_CACHE) >= 10000:
        for k in list(_SHORT_URL_CACHE.keys())[:2000]:
            _SHORT_URL_CACHE.pop(k, None)


async def shorten_single_url(
    long_url: str, cfg: Optional[Dict[str, Any]] = None
) -> str:
    if not long_url:
        return long_url
    if cfg is None:
        cfg = await get_shortener_config()

    if not cfg.get("enabled") or not cfg.get("site") or not cfg.get("api"):
        return long_url

    site, api = cfg["site"], cfg["api"]
    cache_key = (site, api, long_url)
    now = time.time()

    cached = _SHORT_URL_CACHE.get(cache_key)
    if cached and now < cached[0]:
        return cached[1]

    short_url = await asyncio.to_thread(_shorten_sync, site, api, long_url)
    if short_url and short_url != long_url:
        if len(_SHORT_URL_CACHE) >= 10000:
            _prune_short_cache(now)
        _SHORT_URL_CACHE[cache_key] = (now + 86400, short_url)
        return short_url

    return long_url


async def is_shortener_active() -> bool:
    cfg = await get_shortener_config()
    return bool(cfg.get("enabled") and cfg.get("site") and cfg.get("api"))


# ============================================================
# 🔄 INTERACTIVE INPUT LISTENER FOR BUTTON PROMPTS
# ============================================================
_SHORTENER_WAITING_INPUT: Dict[int, Dict[str, Any]] = {}


def _cancel_shortener_input(chat_id: int):
    sess = _SHORTENER_WAITING_INPUT.pop(int(chat_id), None)
    if sess:
        fut = sess.get("future")
        if fut and not fut.done():
            fut.cancel()


async def _shortener_waiting_filter_func(_, __, message: Message) -> bool:
    if not message.chat or message.chat.id not in _SHORTENER_WAITING_INPUT:
        return False
    if (
        message.text
        and message.text.startswith("/")
        and message.text.strip().lower() != "/cancel"
    ):
        _cancel_shortener_input(message.chat.id)
        return False
    return True


shortener_waiting_filter = filters.create(_shortener_waiting_filter_func)


@Client.on_message(
    (filters.private | filters.group) & shortener_waiting_filter, group=-18
)
async def _shortener_input_listener(client: Client, message: Message):
    sess = _SHORTENER_WAITING_INPUT.get(message.chat.id)
    if not sess:
        return

    uid = (
        message.from_user.id
        if message.from_user
        else getattr(message.sender_chat, "id", 0)
    )
    if uid == sess["user_id"] or uid == message.chat.id or await is_global_admin(uid):
        fut = sess["future"]
        if not fut.done():
            fut.set_result(message)
        raise StopPropagation


async def _wait_shortener_input(
    chat_id: int, user_id: int, prompt_msg: Optional[Message], timeout: int = 90
) -> Optional[Message]:
    _cancel_shortener_input(chat_id)
    loop = asyncio.get_running_loop()
    future = loop.create_future()
    _SHORTENER_WAITING_INPUT[int(chat_id)] = {
        "future": future,
        "user_id": user_id,
    }
    try:
        return await asyncio.wait_for(future, timeout=timeout)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        return None
    finally:
        if _SHORTENER_WAITING_INPUT.get(int(chat_id), {}).get("future") is future:
            _SHORTENER_WAITING_INPUT.pop(int(chat_id), None)
        if prompt_msg:
            try:
                await prompt_msg.delete()
            except Exception:
                pass


# ============================================================
# 🎛️ SHORTENER UI PANEL BUILDER
# ============================================================
def _mask_api_key(api_key: str) -> str:
    if not api_key:
        return "Not Set ❌"
    if len(api_key) <= 8:
        return api_key[:2] + "****"
    return f"{api_key[:4]}••••{api_key[-4:]}"


async def build_shortener_panel() -> Tuple[str, InlineKeyboardMarkup]:
    cfg = await get_shortener_config()
    enabled = bool(cfg.get("enabled", False))
    site = cfg.get("site") or ""
    api = cfg.get("api") or ""

    if enabled and site and api:
        status_str = "🟢 ON (Active)"
    elif enabled and (not site or not api):
        status_str = "🟡 ON (⚠️ Set API & Site to Activate)"
    else:
        status_str = "🔴 OFF (Direct Links)"

    site_display = f"<code>{html.escape(site)}</code>" if site else "<i>Not Set ❌</i>"
    api_display = (
        f"<code>{html.escape(_mask_api_key(api))}</code>"
        if api
        else "<i>Not Set ❌</i>"
    )

    text = (
        f"🔗 <b>Link Shortener Control Panel</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📡 <b>Status:</b> <b>{status_str}</b>\n"
        f"🌐 <b>Shortener Site:</b> {site_display}\n"
        f"🔑 <b>Shortener API:</b> {api_display}\n"
        f"⚡ <b>Cached Links:</b> <code>{len(_SHORT_URL_CACHE)}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>Direct Commands:</b>\n"
        f"• <code>/shortener</code> or <code>/shortner</code>\n"
        f"• <code>/shortener on</code> | <code>/shortener off</code>\n"
        f"• <code>/shortenerapi &lt;api_key&gt;</code>\n"
        f"• <code>/shortenersite &lt;domain.com&gt;</code>"
    )

    toggle_label = "On/Off: ON 🟢" if enabled else "On/Off: OFF 🔴"
    toggle_style = BTN_SUCCESS if enabled else BTN_DANGER

    buttons = [
        [create_btn(toggle_label, callback_data="shrt#toggle", style=toggle_style)],
        [
            create_btn("🔑 Set API", callback_data="shrt#set_api", style=BTN_PRIMARY),
            create_btn("🌐 Set Site", callback_data="shrt#set_site", style=BTN_PRIMARY),
        ],
        [
            create_btn("👁️ View API & Site", callback_data="shrt#view"),
            create_btn(
                "🗑️ Remove API & Site", callback_data="shrt#remove", style=BTN_DANGER
            ),
        ],
        [
            create_btn("🧹 Clear Cache", callback_data="shrt#clear_cache"),
            create_btn("🔐 Close", callback_data="shrt#close"),
        ],
    ]

    return text, InlineKeyboardMarkup(buttons)


# ============================================================
# 🎯 SHORTENER COMMAND HANDLERS
# ============================================================
@Client.on_message(filters.command(["shortener", "shortner"]), group=-15)
async def shortener_cmd_handler(client: Client, message: Message):
    _cancel_shortener_input(message.chat.id)
    if not await _require_global_admin(message):
        return

    if len(message.command) >= 2:
        arg = message.command[1].strip().lower()
        if arg in ("on", "enable", "true", "1", "yes"):
            await save_shortener_config(enabled=True)
            text, markup = await build_shortener_panel()
            return await safe_reply_text(
                message, f"✅ <b>Link Shortener turned ON!</b>\n\n{text}", markup
            )
        if arg in ("off", "disable", "false", "0", "no"):
            await save_shortener_config(enabled=False)
            text, markup = await build_shortener_panel()
            return await safe_reply_text(
                message, f"🔴 <b>Link Shortener turned OFF!</b>\n\n{text}", markup
            )

    text, markup = await build_shortener_panel()
    await safe_reply_text(message, text, markup)


@Client.on_message(
    filters.command(["shortenerapi", "shortnerapi", "setshortenerapi"]),
    group=-15,
)
async def shortener_api_cmd_handler(client: Client, message: Message):
    _cancel_shortener_input(message.chat.id)
    if not await _require_global_admin(message):
        return

    if len(message.command) < 2:
        text, markup = await build_shortener_panel()
        return await safe_reply_text(
            message,
            f"⚙️ <b>Usage:</b> <code>/shortenerapi &lt;your_api_key&gt;</code>\n\n{text}",
            markup,
        )

    api_val = message.text.split(None, 1)[1].strip()
    await save_shortener_config(api=api_val)
    text, markup = await build_shortener_panel()
    await safe_reply_text(
        message, f"✅ <b>Shortener API Key saved successfully!</b>\n\n{text}", markup
    )


@Client.on_message(
    filters.command(["shortenersite", "shortnersite", "setshortenersite"]),
    group=-15,
)
async def shortener_site_cmd_handler(client: Client, message: Message):
    _cancel_shortener_input(message.chat.id)
    if not await _require_global_admin(message):
        return

    if len(message.command) < 2:
        text, markup = await build_shortener_panel()
        return await safe_reply_text(
            message,
            f"⚙️ <b>Usage:</b> <code>/shortenersite &lt;domain.com&gt;</code>\n\n{text}",
            markup,
        )

    site_val = message.text.split(None, 1)[1].strip()
    await save_shortener_config(site=site_val)
    text, markup = await build_shortener_panel()
    await safe_reply_text(
        message,
        f"✅ <b>Shortener Site updated to <code>{html.escape(_clean_site_domain(site_val))}</code>!</b>\n\n{text}",
        markup,
    )


# ============================================================
# 🎛️ SHORTENER BUTTON CALLBACK HANDLER
# ============================================================
@Client.on_callback_query(filters.regex(r"^shrt#"), group=-16)
async def shortener_callback_handler(client: Client, query: CallbackQuery):
    uid = query.from_user.id if query.from_user else 0
    if not await is_global_admin(uid):
        return await safe_answer(query, "❌ Admin only!", show_alert=True)
    if not query.message:
        return await safe_answer(query)

    chat_id = query.message.chat.id
    action = query.data.split("#", 1)[1]

    if action == "cancel_input":
        _cancel_shortener_input(chat_id)
        await safe_answer(query, "❌ Cancelled.")
        try:
            await query.message.delete()
        except Exception:
            pass
        return

    _cancel_shortener_input(chat_id)

    if action == "close":
        await safe_answer(query, "Closed.")
        try:
            await query.message.delete()
        except Exception:
            pass
        return

    if action == "main":
        await safe_answer(query)
        text, markup = await build_shortener_panel()
        return await safe_edit_text(query.message, text, markup)

    if action == "clear_cache":
        cleared = len(_SHORT_URL_CACHE)
        _SHORT_URL_CACHE.clear()
        await safe_answer(
            query, f"🧹 Cleared {cleared} cached link(s)!", show_alert=True
        )
        text, markup = await build_shortener_panel()
        return await safe_edit_text(query.message, text, markup)

    if action == "toggle":
        cfg = await get_shortener_config()
        new_state = not bool(cfg.get("enabled", False))
        await save_shortener_config(enabled=new_state)
        await safe_answer(
            query, f"🔗 Link Shortener: {'ON 🟢' if new_state else 'OFF 🔴'}"
        )
        text, markup = await build_shortener_panel()
        return await safe_edit_text(query.message, text, markup)

    if action == "view":
        cfg = await get_shortener_config()
        enabled = bool(cfg.get("enabled", False))
        site = cfg.get("site") or "Not Set"
        api = cfg.get("api") or "Not Set"

        await safe_answer(query, "👁️ Viewing full API & Site details...")
        view_text = (
            f"👁️ <b>Current Shortener Details</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"📡 <b>Status:</b> <code>{'ON 🟢' if enabled else 'OFF 🔴'}</code>\n"
            f"🌐 <b>Site:</b> <code>{html.escape(site)}</code>\n"
            f"🔑 <b>Full API Key:</b> <code>{html.escape(api)}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━━"
        )
        back_kb = InlineKeyboardMarkup(
            [
                [
                    create_btn(
                        "🧪 Test Shortener Live",
                        callback_data="shrt#test",
                        style=BTN_PRIMARY,
                    )
                ],
                [
                    create_btn("🔙 Back", callback_data="shrt#main"),
                    create_btn("🔐 Close", callback_data="shrt#close"),
                ],
            ]
        )
        return await safe_edit_text(query.message, view_text, back_kb)

    if action == "test":
        cfg = await get_shortener_config()
        site = cfg.get("site") or ""
        api = cfg.get("api") or ""
        if not site or not api:
            return await safe_answer(
                query, "⚠️ Please set both API Key and Site first!", show_alert=True
            )
        await safe_answer(query, "⏳ Testing shortener API...")
        test_target = "https://t.me/telegram"
        short_res = await asyncio.to_thread(_shorten_sync, site, api, test_target)
        if short_res and short_res != test_target:
            res_text = (
                f"✅ <b>Shortener Test Successful!</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"🌐 <b>Site:</b> <code>{html.escape(site)}</code>\n"
                f"🔗 <b>Original:</b> <code>{test_target}</code>\n"
                f"⚡ <b>Shortened:</b> <code>{html.escape(short_res)}</code>"
            )
        else:
            res_text = (
                f"❌ <b>Shortener Test Failed!</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"🌐 <b>Site:</b> <code>{html.escape(site)}</code>\n"
                f"🔑 <b>API:</b> <code>{html.escape(api)}</code>\n\n"
                f"⚠️ <i>Please check that your Site domain and API key are valid.</i>"
            )
        back_kb = InlineKeyboardMarkup(
            [
                [
                    create_btn("🔙 Back", callback_data="shrt#main"),
                    create_btn("🔐 Close", callback_data="shrt#close"),
                ]
            ]
        )
        return await safe_edit_text(query.message, res_text, back_kb)

    if action == "remove":
        await save_shortener_config(enabled=False, site="", api="")
        await safe_answer(
            query,
            "🗑️ Removed Shortener API & Site and turned Shortener OFF!",
            show_alert=True,
        )
        text, markup = await build_shortener_panel()
        return await safe_edit_text(query.message, text, markup)

    if action in ("set_api", "set_site"):
        await safe_answer(query)
        is_api = action == "set_api"
        cancel_kb = InlineKeyboardMarkup(
            [[create_btn("❌ Cancel", callback_data="shrt#cancel_input")]]
        )
        prompt_text = (
            "🔑 <b>Send your Link Shortener API Key:</b>\n\nExample: <code>a1b2c3d4e5f6g7h8i9j0</code>"
            if is_api
            else "🌐 <b>Send your Link Shortener Website Domain:</b>\n\nExample: <code>shrinkme.io</code> or <code>gplinks.in</code>"
        )
        prompt = await safe_reply_text(query.message, prompt_text, cancel_kb)
        resp = await _wait_shortener_input(chat_id, uid, prompt_msg=prompt, timeout=90)
        if not resp or not resp.text or resp.text.strip().lower() == "/cancel":
            return

        user_input = resp.text.strip()
        try:
            await resp.delete()
        except Exception:
            pass

        if is_api:
            await save_shortener_config(api=user_input)
        else:
            await save_shortener_config(site=user_input)

        text, markup = await build_shortener_panel()
        return await safe_edit_text(query.message, text, markup)
