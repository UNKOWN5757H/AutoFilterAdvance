
import asyncio
import html
import inspect
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

import info

logger = getLogger(__name__)
logger.setLevel(ERROR)

# ============================================================
# 🛡️ SAFE OPTIONAL IMPORTS FOR MULTI-DB SUPPORT
# ============================================================
try:
    from database.ia_filterdb import (
        get_all_healthy_read_dbs,
        get_writable_System_db,
    )
except Exception:
    get_all_healthy_read_dbs = None
    get_writable_System_db = None

# ============================================================
# 🎨 SAFE TELEGRAM BUTTON STYLE DETECTION
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
        kwargs["url"] = str(url).strip()
    elif callback_data:
        kwargs["callback_data"] = str(callback_data)[:64]

    if _SUPPORTS_BTN_STYLE and style is not None:
        kwargs["style"] = style
    try:
        return InlineKeyboardButton(**kwargs)
    except Exception:
        kwargs.pop("style", None)
        return InlineKeyboardButton(**kwargs)


# ============================================================
# 🛡️ PYROGRAM v2.2.26 (LAYER 230) SAFE HELPERS
# ============================================================
async def safe_reply_text(
    message: Message,
    text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
) -> Optional[Message]:
    if not message:
        return None
    try:
        return await message.reply_text(
            text=text,
            reply_markup=reply_markup,
            parse_mode=enums.ParseMode.HTML,
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
    if not user_id:
        return False
    return int(user_id) in get_admin_list()


# ============================================================
# 💾 QUOTA-SAFE MULTI-DB + RAM SHORTENER CONFIG ENGINE
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

# In-memory state so settings work instantaneously even if DB1 hits 512MB quota
_SHORTENER_RAM_CONFIG: Dict[str, Any] = {
    "enabled": bool(getattr(info, "SHORTLINK", False)),
    "site": str(
        getattr(info, "SHORTLINK_URL", getattr(info, "SHORTENER_SITE", "")) or ""
    ).strip(),
    "api": str(
        getattr(info, "SHORTLINK_API", getattr(info, "SHORTENER_API", "")) or ""
    ).strip(),
    "updated_at": 0.0,
}
_SHORTENER_CACHE_TS: float = 0.0

# 24-hour cache of shortened URLs: {(site, api, long_url): (expire_ts, short_url)}
_SHORT_URL_CACHE: Dict[Tuple[str, str, str], Tuple[float, str]] = {}


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


def _clean_site_domain(raw_site: str) -> str:
    if not raw_site:
        return ""
    s = str(raw_site).strip().lower()
    if s in ("none", "null", "off", "false", "reset"):
        return ""
    s = s.replace("https://", "").replace("http://", "")
    s = s.split("/")[0].strip()
    return s


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
            doc = await col.find_one({"_id": "shortener_config"})
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

    if enabled is not None:
        _SHORTENER_RAM_CONFIG["enabled"] = bool(enabled)
    if site is not None:
        _SHORTENER_RAM_CONFIG["site"] = _clean_site_domain(site)
    if api is not None:
        clean_api = str(api).strip()
        if clean_api.lower() in ("none", "null", "off", "false", "reset"):
            clean_api = ""
        _SHORTENER_RAM_CONFIG["api"] = clean_api

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
            await col.update_one(
                {"_id": "shortener_config"}, {"$set": payload}, upsert=True
            )
        except Exception:
            continue

    return _SHORTENER_RAM_CONFIG


# ============================================================
# 🔗 ON-DEMAND SINGLE LINK SHORTENER ENGINE (ONLY ON USER CLICK)
# ============================================================
def _shorten_sync(site: str, api: str, long_url: str) -> str:
    """
    Converts a single file URL on demand when a user clicks a file button.
    Supports all popular link shorteners:
    - Standard AdLinkFly API (`/api?api=KEY&url=URL`)
    - Shareus.io / Shareus.in (`/easy_api?key=KEY&link=URL`)
    - OuO.io (`/api/KEY?s=URL`)
    """
    if not site or not api or not long_url:
        return long_url

    domain = _clean_site_domain(site)
    if not domain:
        return long_url

    encoded_url = urllib.parse.quote(long_url, safe="")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
    }

    endpoints = []
    if "shareus" in domain:
        endpoints.append(
            f"https://api.shareus.io/easy_api?key={api}&link={encoded_url}"
        )
        endpoints.append(f"https://{domain}/easy_api?key={api}&link={encoded_url}")
    elif "ouo.io" in domain or "ouo.press" in domain:
        endpoints.append(f"https://ouo.io/api/{api}?s={encoded_url}")

    endpoints.append(f"https://{domain}/api?api={api}&url={encoded_url}")
    endpoints.append(f"https://{domain}/api?api={api}&url={encoded_url}&format=text")

    for api_url in endpoints:
        try:
            resp = requests.get(api_url, headers=headers, timeout=5)
            if resp.status_code != 200:
                continue

            raw_text = resp.text.strip()
            if (
                raw_text.startswith(("http://", "https://"))
                and " " not in raw_text
                and "<html" not in raw_text.lower()
            ):
                return raw_text

            data = resp.json()
            if isinstance(data, dict):
                short = (
                    data.get("shortenedUrl")
                    or data.get("shorturl")
                    or data.get("short_url")
                    or data.get("result_url")
                    or data.get("link")
                )
                if short and str(short).startswith(("http://", "https://")):
                    return str(short).strip()
        except Exception:
            continue

    return long_url


async def shorten_single_url(
    long_url: str, cfg: Optional[Dict[str, Any]] = None
) -> str:
    """
    Shortens ONLY the single URL that the user clicked!
    Caches the shortened link for 24 hours so repeat clicks are instant.
    """
    if not long_url:
        return long_url
    if cfg is None:
        cfg = await get_shortener_config()

    if not cfg.get("enabled") or not cfg.get("site") or not cfg.get("api"):
        return long_url

    site = cfg["site"]
    api = cfg["api"]
    cache_key = (site, api, long_url)
    now = time.time()

    cached = _SHORT_URL_CACHE.get(cache_key)
    if cached and now < cached[0]:
        return cached[1]

    short_url = await asyncio.to_thread(_shorten_sync, site, api, long_url)
    if short_url and short_url != long_url:
        if len(_SHORT_URL_CACHE) > 10000:
            _SHORT_URL_CACHE.clear()
        _SHORT_URL_CACHE[cache_key] = (now + 86400, short_url)
        return short_url

    return long_url


async def is_shortener_active() -> bool:
    """Returns True if Link Shortener is ON and both Site and API Key are configured."""
    cfg = await get_shortener_config()
    return bool(cfg.get("enabled") and cfg.get("site") and cfg.get("api"))


# ============================================================
# 🔄 INTERACTIVE INPUT LISTENER FOR BUTTON PROMPTS
# ============================================================
_SHORTENER_WAITING_INPUT: Dict[int, Dict[str, Any]] = {}


def is_waiting_for_shortener_input(chat_id: int) -> bool:
    return int(chat_id) in _SHORTENER_WAITING_INPUT


def _cancel_shortener_input(chat_id: int):
    sess = _SHORTENER_WAITING_INPUT.pop(int(chat_id), None)
    if sess:
        fut = sess.get("future")
        if fut and not fut.done():
            fut.cancel()
        p_msg = sess.get("prompt_msg")
        if p_msg:
            try:
                asyncio.create_task(p_msg.delete())
            except Exception:
                pass


async def _shortener_waiting_filter_func(_, __, message: Message) -> bool:
    if not message.chat or message.chat.id not in _SHORTENER_WAITING_INPUT:
        return False
    if (
        message.text
        and message.text.startswith("/")
        and message.text.strip().lower() not in ["/cancel"]
    ):
        _cancel_shortener_input(message.chat.id)
        return False
    return True


shortener_waiting_filter = filters.create(_shortener_waiting_filter_func)


@Client.on_message(
    (filters.private | filters.group) & shortener_waiting_filter, group=-18
)
async def _shortener_input_listener(client: Client, message: Message):
    chat_id = message.chat.id
    sess = _SHORTENER_WAITING_INPUT.get(chat_id)
    if not sess:
        return

    uid = (
        message.from_user.id
        if message.from_user
        else getattr(message.sender_chat, "id", 0)
    )
    if uid == sess["user_id"] or uid == chat_id or await is_global_admin(uid):
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
        "prompt_msg": prompt_msg,
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
# 🎛️ SHORTENER UI PANEL BUILDER (EXACT REQUESTED BUTTON LAYOUT)
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

    is_ready = bool(enabled and site and api)
    if is_ready:
        status_str = "🟢 ON (Converts Only Clicked File Link)"
    elif enabled and (not site or not api):
        status_str = "🟡 ON (⚠️ Set API & Site to Activate)"
    else:
        status_str = "🔴 OFF (Direct Telegram Links)"

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
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"💡 <i>When enabled, search results load instantly and only the specific file link a user clicks is converted!</i>\n\n"
        f"<b>Direct Commands:</b>\n"
        f"• <code>/shortener</code> or <code>/shortner</code>\n"
        f"• <code>/shortener on</code> | <code>/shortener off</code>\n"
        f"• <code>/shortenerapi &lt;api_key&gt;</code>\n"
        f"• <code>/shortenersite &lt;domain.com&gt;</code>"
    )

    toggle_label = "On/Off: ON 🟢" if enabled else "On/Off: OFF 🔴"
    toggle_style = BTN_SUCCESS if enabled else BTN_DANGER

    # Exact 3-row layout requested:
    # Row 1: On/off
    # Row 2: Set api | Set site
    # Row 3: View api & site | Remove api & site
    buttons = [
        [
            create_btn(
                toggle_label,
                callback_data="shrt#toggle",
                style=toggle_style,
            )
        ],
        [
            create_btn("🔑 Set API", callback_data="shrt#set_api", style=BTN_PRIMARY),
            create_btn("🌐 Set Site", callback_data="shrt#set_site", style=BTN_PRIMARY),
        ],
        [
            create_btn("👁️ View API & Site", callback_data="shrt#view"),
            create_btn(
                "🗑️ Remove API & Site",
                callback_data="shrt#remove",
                style=BTN_DANGER,
            ),
        ],
        [
            create_btn("🔐 Close", callback_data="shrt#close"),
        ],
    ]

    return text, InlineKeyboardMarkup(buttons)


# ============================================================
# 🎯 SHORTENER COMMAND HANDLERS
# ============================================================
@Client.on_message(
    filters.command(["shortener", "shortner"]),
    group=-15,
)
async def shortener_cmd_handler(client: Client, message: Message):
    uid = (
        message.from_user.id
        if message.from_user
        else getattr(message.sender_chat, "id", 0)
    )
    _cancel_shortener_input(message.chat.id)

    if not await is_global_admin(uid):
        return await safe_reply_text(
            message, "❌ <b>Unauthorized:</b> Global Bot Admin only."
        )

    if len(message.command) >= 2:
        arg = message.command[1].strip().lower()
        if arg in ("on", "enable", "true", "1", "yes"):
            await save_shortener_config(enabled=True)
            text, markup = await build_shortener_panel()
            return await safe_reply_text(
                message,
                f"✅ <b>Link Shortener turned ON!</b>\n\n{text}",
                reply_markup=markup,
            )
        elif arg in ("off", "disable", "false", "0", "no"):
            await save_shortener_config(enabled=False)
            text, markup = await build_shortener_panel()
            return await safe_reply_text(
                message,
                f"🔴 <b>Link Shortener turned OFF!</b>\n\n{text}",
                reply_markup=markup,
            )

    text, markup = await build_shortener_panel()
    await safe_reply_text(message, text, reply_markup=markup)


@Client.on_message(
    filters.command(["shortenerapi", "shortnerapi", "setshortenerapi"]),
    group=-15,
)
async def shortener_api_cmd_handler(client: Client, message: Message):
    uid = (
        message.from_user.id
        if message.from_user
        else getattr(message.sender_chat, "id", 0)
    )
    _cancel_shortener_input(message.chat.id)

    if not await is_global_admin(uid):
        return await safe_reply_text(
            message, "❌ <b>Unauthorized:</b> Global Bot Admin only."
        )

    if len(message.command) < 2:
        text, markup = await build_shortener_panel()
        return await safe_reply_text(
            message,
            "⚙️ <b>Usage:</b> <code>/shortenerapi &lt;your_api_key&gt;</code>\n\n"
            + text,
            reply_markup=markup,
        )

    api_val = message.text.split(None, 1)[1].strip()
    await save_shortener_config(api=api_val, enabled=True)
    text, markup = await build_shortener_panel()
    await safe_reply_text(
        message,
        f"✅ <b>Shortener API Key saved successfully!</b>\n\n{text}",
        reply_markup=markup,
    )


@Client.on_message(
    filters.command(["shortenersite", "shortnersite", "setshortenersite"]),
    group=-15,
)
async def shortener_site_cmd_handler(client: Client, message: Message):
    uid = (
        message.from_user.id
        if message.from_user
        else getattr(message.sender_chat, "id", 0)
    )
    _cancel_shortener_input(message.chat.id)

    if not await is_global_admin(uid):
        return await safe_reply_text(
            message, "❌ <b>Unauthorized:</b> Global Bot Admin only."
        )

    if len(message.command) < 2:
        text, markup = await build_shortener_panel()
        return await safe_reply_text(
            message,
            "⚙️ <b>Usage:</b> <code>/shortenersite &lt;domain.com&gt;</code>\n"
            "Example: <code>/shortenersite shrinkme.io</code>\n\n" + text,
            reply_markup=markup,
        )

    site_val = message.text.split(None, 1)[1].strip()
    await save_shortener_config(site=site_val, enabled=True)
    text, markup = await build_shortener_panel()
    await safe_reply_text(
        message,
        f"✅ <b>Shortener Site updated to <code>{html.escape(_clean_site_domain(site_val))}</code>!</b>\n\n{text}",
        reply_markup=markup,
    )


# ============================================================
# 🎛️ SHORTENER BUTTON CALLBACK HANDLER (shrt#...)
# ============================================================
@Client.on_callback_query(filters.regex(r"^shrt#"), group=-16)
async def shortener_callback_handler(client: Client, query: CallbackQuery):
    uid = query.from_user.id if query.from_user else 0
    if not await is_global_admin(uid):
        return await safe_answer(query, "❌ Admin only!", show_alert=True)

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
        return await safe_edit_text(query.message, text, reply_markup=markup)

    if action == "toggle":
        cfg = await get_shortener_config()
        new_state = not bool(cfg.get("enabled", False))
        await save_shortener_config(enabled=new_state)
        await safe_answer(
            query,
            f"🔗 Link Shortener: {'ON 🟢' if new_state else 'OFF 🔴'}",
        )
        text, markup = await build_shortener_panel()
        return await safe_edit_text(query.message, text, reply_markup=markup)

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
        return await safe_edit_text(query.message, view_text, reply_markup=back_kb)

    if action == "test":
        cfg = await get_shortener_config()
        site = cfg.get("site") or ""
        api = cfg.get("api") or ""
        if not site or not api:
            return await safe_answer(
                query,
                "⚠️ Please set both API Key and Site first!",
                show_alert=True,
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
                f"⚡ <b>Shortened:</b> {html.escape(short_res)}"
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
        return await safe_edit_text(query.message, res_text, reply_markup=back_kb)

    if action == "remove":
        await save_shortener_config(enabled=False, site="", api="")
        await safe_answer(
            query,
            "🗑️ Removed Shortener API & Site and turned Shortener OFF!",
            show_alert=True,
        )
        text, markup = await build_shortener_panel()
        return await safe_edit_text(query.message, text, reply_markup=markup)

    if action == "set_api":
        await safe_answer(query)
        cancel_kb = InlineKeyboardMarkup(
            [[create_btn("❌ Cancel", callback_data="shrt#cancel_input")]]
        )
        prompt = await safe_reply_text(
            query.message,
            "🔑 <b>Send your Link Shortener API Key:</b>\n\n"
            "Example: <code>a1b2c3d4e5f6g7h8i9j0</code>",
            reply_markup=cancel_kb,
        )
        resp = await _wait_shortener_input(chat_id, uid, prompt_msg=prompt, timeout=90)
        if not resp or not resp.text or resp.text.strip().lower() == "/cancel":
            return
        api_input = resp.text.strip()
        try:
            await resp.delete()
        except Exception:
            pass

        await save_shortener_config(api=api_input)
        text, markup = await build_shortener_panel()
        return await safe_edit_text(query.message, text, reply_markup=markup)

    if action == "set_site":
        await safe_answer(query)
        cancel_kb = InlineKeyboardMarkup(
            [[create_btn("❌ Cancel", callback_data="shrt#cancel_input")]]
        )
        prompt = await safe_reply_text(
            query.message,
            "🌐 <b>Send your Link Shortener Website Domain:</b>\n\n"
            "Example: <code>shrinkme.io</code> or <code>fxnlinks.com</code> or <code>gplinks.in</code>",
            reply_markup=cancel_kb,
        )
        resp = await _wait_shortener_input(chat_id, uid, prompt_msg=prompt, timeout=90)
        if not resp or not resp.text or resp.text.strip().lower() == "/cancel":
            return
        site_input = resp.text.strip()
        try:
            await resp.delete()
        except Exception:
            pass

        await save_shortener_config(site=site_input)
        text, markup = await build_shortener_panel()
        return await safe_edit_text(query.message, text, reply_markup=markup)
