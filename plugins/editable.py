import asyncio
import hashlib
import html
import inspect
import re
import time
from logging import ERROR, getLogger
from typing import Any, Dict, List, Optional, Tuple

import requests
from motor.motor_asyncio import AsyncIOMotorClient
from pyrogram import Client, enums, filters
from pyrogram.errors import (
    ChatWriteForbidden,
    Forbidden,
    MessageIdInvalid,
    MessageNotModified,
    PeerIdInvalid,
    UserIsBlocked,
)
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

import info
from Script import script

logger = getLogger(__name__)
logger.setLevel(ERROR)

_ORIG_START_TXT = getattr(script, "START_TXT", "")
_ORIG_HELP_TXT = getattr(script, "HELP_TXT", "")
_ORIG_ABOUT_TXT = getattr(script, "ABOUT_TXT", "")

_ORIG_START_IMG = getattr(info, "START_IMG", None)
_ORIG_HELP_IMG = getattr(info, "HELP_IMG", None)
_ORIG_ABOUT_IMG = getattr(info, "ABOUT_IMG", None)

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
    from pyrogram.types import ReplyParameters
except ImportError:
    ReplyParameters = None

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
                        new_row.append(
                            create_styled_btn(b.text, url=b.url, color=None)
                        )
                    else:
                        new_row.append(
                            create_styled_btn(
                                b.text,
                                callback_data=getattr(b, "callback_data", "noop"),
                            )
                        )
                if new_row:
                    rows.append(new_row)
            return InlineKeyboardMarkup(rows) if rows else None


# ============================================================
# 🛡️ PYROGRAM v2.2.26 COMPATIBILITY & HIDDEN-LINK BUTTONS
# ============================================================
_REPLY_PARAMS = set(inspect.signature(Message.reply_text).parameters.keys())
_EDIT_PARAMS = set(inspect.signature(Message.edit_text).parameters.keys())

BTN_PRIMARY = None
BTN_SECONDARY = None
BTN_SUCCESS = None
BTN_DANGER = None
_SUPPORTS_BTN_STYLE = False
_BTN_ICON_PARAM: Optional[str] = None
_BTN_ICON_WANTS_INT = False

try:
    from pyrogram.enums import ButtonStyle

    _btn_sig_params = inspect.signature(InlineKeyboardButton.__init__).parameters
    if "style" in _btn_sig_params:
        BTN_PRIMARY = getattr(ButtonStyle, "PRIMARY", None)
        BTN_SECONDARY = getattr(ButtonStyle, "SECONDARY", None)
        BTN_SUCCESS = getattr(ButtonStyle, "SUCCESS", None)
        BTN_DANGER = getattr(ButtonStyle, "DANGER", None)
        _SUPPORTS_BTN_STYLE = True
    for _cand_icon_param in ("icon_custom_emoji_id", "custom_emoji_id", "icon_id"):
        if _cand_icon_param in _btn_sig_params:
            _BTN_ICON_PARAM = _cand_icon_param
            _ann = str(_btn_sig_params[_cand_icon_param].annotation).lower()
            _BTN_ICON_WANTS_INT = "int" in _ann and "str" not in _ann
            break
except (ImportError, ValueError, TypeError):
    pass

_TG_EMOJI_RE = re.compile(
    r'<tg-emoji\s+emoji-id=["\']?(\d+)["\']?\s*>(.*?)</tg-emoji>',
    re.IGNORECASE | re.DOTALL,
)
        BTN_SECONDARY = getattr(ButtonStyle, "SECONDARY", None)
        BTN_SUCCESS = getattr(ButtonStyle, "SUCCESS", None)
        BTN_DANGER = getattr(ButtonStyle, "DANGER", None)
        _SUPPORTS_BTN_STYLE = True
except (ImportError, ValueError, TypeError):
    pass


def _clean_button_label(raw_label: str) -> str:
    lbl = re.sub(r"<[^>]+>", "", str(raw_label or "")).strip()
    lbl = re.sub(r"(?i)https?://\S+|t\.me/\S+|www\.\S+", "", lbl).strip(" -|:")
    return lbl or "Open"


def get_color_style(color_name: Optional[str]) -> Any:
    if not color_name or not _SUPPORTS_BTN_STYLE:
        return None
    return {
        "blue": BTN_PRIMARY,
        "green": BTN_SUCCESS,
        "red": BTN_DANGER,
        "gray": BTN_SECONDARY,
        "normal": None,
    }.get(str(color_name).strip().lower(), None)


def create_styled_btn(
    text: str,
    url: Optional[str] = None,
    callback_data: Optional[str] = None,
    color: Optional[str] = None,
    icon_custom_emoji_id: Optional[Any] = None,
) -> InlineKeyboardButton:
    """Creates an InlineKeyboardButton with ZERO visible links and Premium emoji icon support."""
    raw_text = str(text or "")
    resolved_icon = str(icon_custom_emoji_id).strip() if icon_custom_emoji_id else None
    if not resolved_icon:
        m = _TG_EMOJI_RE.search(raw_text)
        if m:
            resolved_icon = m.group(1).strip()
            raw_text = _TG_EMOJI_RE.sub(
                "" if _BTN_ICON_PARAM else m.group(2), raw_text, count=1
            )
    elif _TG_EMOJI_RE.search(raw_text):
        raw_text = _TG_EMOJI_RE.sub("", raw_text)

    kwargs: Dict[str, Any] = {"text": _clean_button_label(raw_text)}
    if callback_data:
        kwargs["callback_data"] = str(callback_data)[:64]
    elif url:
        kwargs["callback_data"] = f"olink#{register_hidden_link(url)}"
    else:
        kwargs["callback_data"] = "noop"

    style_obj = get_color_style(color)
    if style_obj is not None:
        kwargs["style"] = style_obj
    if _BTN_ICON_PARAM and resolved_icon and resolved_icon.isdigit():
        kwargs[_BTN_ICON_PARAM] = (
            int(resolved_icon) if _BTN_ICON_WANTS_INT else str(resolved_icon)
        )

    try:
        return InlineKeyboardButton(**kwargs)
    except Exception:
        if _BTN_ICON_PARAM and _BTN_ICON_PARAM in kwargs:
            alt_val = (
                str(resolved_icon)
                if isinstance(kwargs[_BTN_ICON_PARAM], int)
                else int(resolved_icon)
            )
            kwargs[_BTN_ICON_PARAM] = alt_val
            try:
                return InlineKeyboardButton(**kwargs)
            except Exception:
                kwargs.pop(_BTN_ICON_PARAM, None)
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
        if "link_preview_options" in supported_params and LinkPreviewOptions is not None:
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
):
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
):
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


# ============================================================
# ⚙️ QUOTA-SAFE MULTI-DB UI STORAGE & INSTANT CACHE SYNC
# ============================================================
_ui_settings = None
_UI_CACHE: Optional[Dict[str, Any]] = None
_UI_CACHE_TS: float = 0.0


def _get_fallback_col():
    global _ui_settings
    if _ui_settings is None:
        client = AsyncIOMotorClient(
            info.DATABASE_URI,
            serverSelectionTimeoutMS=4000,
            connectTimeoutMS=4000,
            socketTimeoutMS=8000,
        )
        _ui_settings = client[info.DATABASE_NAME]["ui_config"]
    return _ui_settings


def _get_ui_cols() -> List[Any]:
    cols = []
    if callable(get_writable_System_db):
        try:
            w_db = get_writable_System_db()
            if w_db is not None:
                cols.append(w_db["ui_config"])
        except Exception:
            pass
    if callable(get_all_healthy_read_dbs):
        try:
            for _, r_db in get_all_healthy_read_dbs():
                c = r_db["ui_config"]
                if c not in cols:
                    cols.append(c)
        except Exception:
            pass
    fb = _get_fallback_col()
    if fb is not None and fb not in cols:
        cols.append(fb)
    return cols


def _sync_ui_to_runtime(doc: Dict[str, Any]):
    if not isinstance(doc, dict):
        return
    script.START_TXT = doc.get("start_text") or _ORIG_START_TXT
    script.HELP_TXT = doc.get("help_text") or _ORIG_HELP_TXT
    script.ABOUT_TXT = doc.get("about_text") or _ORIG_ABOUT_TXT

    if "start_img" in doc:
        info.START_IMG = doc["start_img"] if doc["start_img"] else _ORIG_START_IMG
    if "help_img" in doc:
        info.HELP_IMG = doc["help_img"] if doc["help_img"] else _ORIG_HELP_IMG
    if "about_img" in doc:
        info.ABOUT_IMG = doc["about_img"] if doc["about_img"] else _ORIG_ABOUT_IMG

    # Immediately invalidate uibuttons caches so edits appear right away
    try:
        import plugins.uibuttons as _uib

        _uib._UI_SYNC_TS = 0.0
        _uib._CUSTOM_ROWS_CACHE.clear()
    except Exception:
        pass


async def get_ui(force_refresh: bool = False) -> Dict[str, Any]:
    global _UI_CACHE, _UI_CACHE_TS
    now = time.time()
    if not force_refresh and _UI_CACHE is not None and (now - _UI_CACHE_TS) < 60:
        return _UI_CACHE

    best_doc = None
    best_ts = -1.0
    for col in _get_ui_cols():
        try:
            doc = await asyncio.wait_for(col.find_one({"_id": "bot_ui"}), timeout=2.0)
            if doc:
                doc_ts = float(doc.get("updated_at", 0.0) or 0.0)
                if best_doc is None or doc_ts >= best_ts:
                    best_doc = doc
                    best_ts = doc_ts
        except Exception:
            continue

    _UI_CACHE = best_doc or _UI_CACHE or {}
    _UI_CACHE_TS = now
    _sync_ui_to_runtime(_UI_CACHE)
    return _UI_CACHE


async def update_ui(key: str, value: Any):
    global _UI_CACHE, _UI_CACHE_TS
    now = time.time()
    if _UI_CACHE is None:
        _UI_CACHE = {}
    _UI_CACHE[key] = value
    _UI_CACHE["updated_at"] = now
    _UI_CACHE_TS = now
    _sync_ui_to_runtime(_UI_CACHE)

    payload = {key: value, "updated_at": now}
    for col in _get_ui_cols():
        try:
            await asyncio.wait_for(
                col.update_one({"_id": "bot_ui"}, {"$set": payload}, upsert=True),
                timeout=2.5,
            )
        except Exception:
            continue


def build_custom_button_rows(
    btns_data: List[Dict[str, Any]],
) -> List[List[InlineKeyboardButton]]:
    rows: List[List[InlineKeyboardButton]] = []
    if not btns_data or not isinstance(btns_data, list):
        return rows

    for b in btns_data:
        if not isinstance(b, dict) or not b.get("text") or not b.get("url"):
            continue
        btn_obj = create_styled_btn(
            text=b["text"],
            url=b["url"],
            color=b.get("color", "blue"),
            icon_custom_emoji_id=b.get("icon_custom_emoji_id"),
        )
        if b.get("layout") == "sidebyside" and rows and len(rows[-1]) < 2:
            rows[-1].append(btn_obj)
        else:
            rows.append([btn_obj])
    return rows


async def get_custom_menu_rows(menu_name: str) -> List[List[InlineKeyboardButton]]:
    ui = await get_ui()
    return build_custom_button_rows(ui.get(f"{menu_name}_buttons", []))


# ============================================================
# 👑 ADMIN CHECKER & IMAGE UPLOADER
# ============================================================
def get_admin_list() -> List[int]:
    raw_admins = getattr(info, "ADMINS", [])
    if isinstance(raw_admins, (str, int)):
        return [
            int(x)
            for x in str(raw_admins).replace(",", " ").split()
            if x.strip().lstrip("-").isdigit()
        ]
    if isinstance(raw_admins, (list, tuple, set)):
        return [int(x) for x in raw_admins if str(x).strip().lstrip("-").isdigit()]
    return []


async def is_global_admin(message: Message) -> bool:
    admins = get_admin_list()
    if message.from_user and message.from_user.id in admins:
        return True
    if message.sender_chat and message.sender_chat.id in admins:
        return True
    return False


async def _require_global_admin(message: Message) -> bool:
    if await is_global_admin(message):
        return True
    await safe_reply_text(
        message,
        "❌ <b>Unauthorized:</b> Global Bot Admin only.",
        parse_mode=enums.ParseMode.HTML,
    )
    return False


def _upload_sync(file_bytes: bytes) -> Optional[str]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
    }
    endpoints = [
        (
            "https://catbox.moe/user/api.php",
            {"fileToUpload": ("img.jpg", file_bytes, "image/jpeg")},
            {"reqtype": "fileupload"},
        ),
        (
            "https://freeimage.host/api/1/upload",
            {"source": ("img.jpg", file_bytes, "image/jpeg")},
            {"key": "6d207e02198a847aa98d0a2a901485a5", "format": "json"},
        ),
        (
            "https://litterbox.catbox.moe/resources/internals/api.php",
            {"fileToUpload": ("img.jpg", file_bytes, "image/jpeg")},
            {"reqtype": "fileupload", "time": "72h"},
        ),
        ("https://envs.sh", {"file": ("img.jpg", file_bytes, "image/jpeg")}, None),
        ("https://0x0.st", {"file": ("img.jpg", file_bytes, "image/jpeg")}, None),
    ]
    for url, files_dict, data_dict in endpoints:
        try:
            res = requests.post(
                url, data=data_dict, files=files_dict, headers=headers, timeout=8
            )
            if res.status_code in (200, 201):
                if "freeimage.host" in url:
                    u = res.json().get("image", {}).get("url")
                    if u and u.startswith("http"):
                        return u
                elif res.text.strip().startswith("http"):
                    return res.text.strip()
        except Exception:
            continue
    return None


async def upload_image_safely(
    client: Client, message: Message
) -> Tuple[Optional[str], Optional[str]]:
    try:
        file_io = await client.download_media(message, in_memory=True)
        if not file_io:
            return None, "❌ Failed to download the image."
        url = await asyncio.to_thread(_upload_sync, file_io.getvalue())
        if not url:
            return None, "❌ All cloud uploaders failed."
        return url, None
    except Exception as e:
        return None, f"❌ Internal Error: {e}"


# ============================================================
# 🛠️ SHARED TEXT, IMAGE & BUTTON HANDLERS
# ============================================================
def extract_custom_html_text(message: Message) -> Optional[str]:
    if (
        message.reply_to_message
        and len(getattr(message, "command", [])) == 1
        and (message.reply_to_message.text or message.reply_to_message.caption)
    ):
        raw = message.reply_to_message.text or message.reply_to_message.caption
        return getattr(raw, "html", str(raw)).strip()

    if message.text and len(getattr(message, "command", [])) > 1:
        html_str = getattr(message.text, "html", str(message.text))
        cleaned = re.sub(r"^/\w+(?:@[a-zA-Z0-9_]+)?\s+", "", html_str, count=1).strip()
        return cleaned or None

    if message.text and not message.text.startswith("/"):
        return getattr(message.text, "html", str(message.text)).strip()

    return None


def _normalize_url(raw_url: str) -> str:
    u = raw_url.strip()
    if not u.startswith(("http://", "https://", "tg://")):
        u = "https://" + u
    return u


def parse_button_cmd(
    message: Message,
) -> Tuple[Optional[str], Optional[str], str, str, Optional[str]]:
    raw_obj = message.text or message.caption or ""
    raw = getattr(raw_obj, "html", str(raw_obj))
    body = re.sub(r"^/\w+(?:@[a-zA-Z0-9_]+)?\s*", "", raw, count=1).strip()
    if not body and message.reply_to_message:
        rep_obj = message.reply_to_message.text or message.reply_to_message.caption or ""
        body = getattr(rep_obj, "html", str(rep_obj)).strip()

    if not body:
        return None, None, "belowside", "blue", None

    # Extract any Telegram Premium custom emoji from the button label before cleaning HTML
    icon_id: Optional[str] = None
    m_emoji = _TG_EMOJI_RE.search(body)
    if m_emoji:
        icon_id = m_emoji.group(1).strip()
        body = _TG_EMOJI_RE.sub("" if _BTN_ICON_PARAM else m_emoji.group(2), body, count=1)
    body = re.sub(r"<[^>]+>", "", body).strip()

    layout, color = "belowside", "blue"

    if "|" in body:
        parts = [p.strip() for p in body.split("|") if p.strip()]
        if len(parts) >= 2:
            btn_text = _clean_button_label(parts[0].strip("\"'“”"))
            url = _normalize_url(parts[1])
            for extra in parts[2:]:
                el = extra.lower()
                if el in ("sidebyside", "belowside"):
                    layout = el
                elif el in ("green", "red", "blue", "gray", "normal"):
                    color = el
            return btn_text, url, layout, color, icon_id

    match = re.search(
        r'["“\']([^"”\']+)["”\']\s+(\S+)(?:\s+(\S+))?(?:\s+(\S+))?', body
    )
    if match:
        btn_text = _clean_button_label(match.group(1).strip())
        url = _normalize_url(match.group(2).strip())
        for extra in (match.group(3), match.group(4)):
            if extra:
                el = extra.lower()
                if el in ("sidebyside", "belowside"):
                    layout = el
                elif el in ("green", "red", "blue", "gray", "normal"):
                    color = el
        return btn_text, url, layout, color, icon_id

    if " - " in body:
        parts = body.split(" - ", 1)
        return (
            _clean_button_label(parts[0].strip("\"'“” ")),
            _normalize_url(parts[1]),
            layout,
            color,
            icon_id,
        )

    tokens = body.split()
    if len(tokens) >= 2 and (
        tokens[-1].startswith(("http://", "https://", "t.me/", "tg://"))
        or "." in tokens[-1]
    ):
        btn_text = _clean_button_label(" ".join(tokens[:-1]).strip("\"'“” "))
        if btn_text:
            return btn_text, _normalize_url(tokens[-1]), layout, color, icon_id

    return None, None, layout, color, icon_id

    idx = int(parts[0]) - 1
    layout = color = None
    for token in parts[1:]:
        if token in ("sidebyside", "belowside"):
            layout = token
        elif token in ("green", "red", "blue", "gray", "normal"):
            color = token
    return idx, layout, color


def format_btn_list(btns: List[Dict[str, Any]]) -> str:
    if not btns:
        return "<i>No custom buttons configured.</i>"
    return "\n".join(
        f"<b>{i}.</b> <code>{html.escape(str(b.get('text')))}</code> — Layout: <code>{b.get('layout', 'belowside')}</code> | Color: <code>{b.get('color', 'blue')}</code>"
        for i, b in enumerate(btns, 1)
    )


async def process_image_upload(
    client: Client, message: Message, db_key: str, menu_name: str
):
    target_msg = None
    if message.reply_to_message and (
        message.reply_to_message.photo or message.reply_to_message.document
    ):
        target_msg = message.reply_to_message
    elif message.photo or message.document:
        target_msg = message

    if target_msg is None and message.text and len(getattr(message, "command", [])) > 1:
        arg = message.text.split(None, 1)[1].strip()
        if arg.startswith(("http://", "https://")) or len(arg) > 20:
            await update_ui(db_key, arg)
            return await safe_reply_text(
                message,
                f"✅ <b>{menu_name} Image updated successfully!</b>",
                parse_mode=enums.ParseMode.HTML,
            )

    if target_msg is None:
        return await safe_reply_text(
            message,
            f"⚠️ <b>Usage:</b> Reply to a photo with <code>/{message.command[0]}</code> (or provide an image URL).",
            parse_mode=enums.ParseMode.HTML,
        )

    status = await safe_reply_text(
        message, "⏳ <b>Uploading to Cloud...</b>", parse_mode=enums.ParseMode.HTML
    )
    url, _ = await upload_image_safely(client, target_msg)

    if url:
        await update_ui(db_key, url)
        if status:
            await safe_edit_text(
                status,
                f"✅ <b>{menu_name} Image updated!</b>\n<i>(Saved permanently to cloud)</i>",
                parse_mode=enums.ParseMode.HTML,
            )
    else:
        file_id = (
            target_msg.photo.file_id
            if target_msg.photo
            else getattr(target_msg.document, "file_id", None)
        )
        if not file_id:
            if status:
                await safe_edit_text(
                    status,
                    "❌ <b>Could not extract valid photo!</b>",
                    parse_mode=enums.ParseMode.HTML,
                )
            return
        await update_ui(db_key, file_id)
        if status:
            await safe_edit_text(
                status,
                f"⚠️ Cloud blocked. <b>{menu_name} Image updated!</b>\n<i>(Saved as Telegram File_ID)</i>",
                parse_mode=enums.ParseMode.HTML,
            )


async def _handle_set_text(message: Message, menu: str, label: str):
    if not await _require_global_admin(message):
        return
    text = extract_custom_html_text(message)
    if not text:
        return await safe_reply_text(
            message,
            f"⚠️ <b>Usage:</b> <code>/set{menu}text &lt;text&gt;</code> (or reply to a message).",
            parse_mode=enums.ParseMode.HTML,
        )
    await update_ui(f"{menu}_text", text)
    await safe_reply_text(
        message, f"✅ <b>{label} Text updated!</b>", parse_mode=enums.ParseMode.HTML
    )


async def _handle_default_text(message: Message, menu: str, label: str):
    if not await _require_global_admin(message):
        return
    await update_ui(f"{menu}_text", None)
    await safe_reply_text(
        message,
        f"✅ <b>{label} Text reset to default.</b>",
        parse_mode=enums.ParseMode.HTML,
    )


async def _handle_rem_img(message: Message, menu: str, label: str):
    if not await _require_global_admin(message):
        return
    await update_ui(f"{menu}_img", None)
    await safe_reply_text(
        message, f"🗑️ <b>{label} Image removed.</b>", parse_mode=enums.ParseMode.HTML
    )


async def _handle_add_btn(message: Message, menu: str, label: str):
    if not await _require_global_admin(message):
        return
    btn_text, url, layout, color, icon_id = parse_button_cmd(message)
    if not btn_text or not url:
        return await safe_reply_text(
            message,
            f'⚠️ <b>Usage:</b> <code>/add{menu}button "Button Text" https://link.com</code>\n'
            f"Or: <code>/add{menu}button Button Text | https://link.com</code>",
            parse_mode=enums.ParseMode.HTML,
        )
    ui = await get_ui()
    btns = list(ui.get(f"{menu}_buttons", []))
    entry = {"text": btn_text, "url": url, "layout": layout, "color": color}
    if icon_id:
        entry["icon_custom_emoji_id"] = icon_id
    btns.append(entry)
    await update_ui(f"{menu}_buttons", btns)
    await safe_reply_text(
        message,
        f"✅ <b>{label} Button Added!</b>\n\n<b>Current Buttons:</b>\n{format_btn_list(btns)}",
        parse_mode=enums.ParseMode.HTML,
    )


async def _handle_edit_btn(message: Message, menu: str, label: str):
    if not await _require_global_admin(message):
        return
    idx, layout, color = parse_edit_button_args(message.text or "")
    ui = await get_ui()
    btns = list(ui.get(f"{menu}_buttons", []))

    if idx is None or idx < 0 or idx >= len(btns) or (not layout and not color):
        return await safe_reply_text(
            message,
            f"⚠️ <b>Usage:</b> <code>/edit{menu}buttons &lt;number&gt; &lt;sidebyside/belowside&gt; &lt;color&gt;</code>\n\n"
            f"<b>Current Buttons:</b>\n{format_btn_list(btns)}",
            parse_mode=enums.ParseMode.HTML,
        )

    if layout:
        btns[idx]["layout"] = layout
    if color:
        btns[idx]["color"] = color
    await update_ui(f"{menu}_buttons", btns)
    await safe_reply_text(
        message,
        f"✅ <b>{label} Button #{idx + 1} Updated!</b>\n\n{format_btn_list(btns)}",
        parse_mode=enums.ParseMode.HTML,
    )


async def _handle_rem_btn(message: Message, menu: str, label: str):
    if not await _require_global_admin(message):
        return
    await update_ui(f"{menu}_buttons", [])
    await safe_reply_text(
        message,
        f"🗑️ <b>All custom {label} buttons cleared.</b>",
        parse_mode=enums.ParseMode.HTML,
    )


# ============================================================
# 🏠 START, ℹ️ HELP & 📖 ABOUT MENU COMMANDS
# ============================================================
@Client.on_message(filters.command("setstarttext") & filters.incoming, group=-2)
async def set_start_text(client: Client, message: Message):
    await _handle_set_text(message, "start", "Start Menu")


@Client.on_message(filters.command("defaultstarttext") & filters.incoming, group=-2)
async def def_start_text(client: Client, message: Message):
    await _handle_default_text(message, "start", "Start Menu")


@Client.on_message(filters.command("setstartimage") & filters.incoming, group=-2)
async def set_start_img(client: Client, message: Message):
    if await _require_global_admin(message):
        await process_image_upload(client, message, "start_img", "Start Menu")


@Client.on_message(filters.command("remstartimage") & filters.incoming, group=-2)
async def rem_start_img(client: Client, message: Message):
    await _handle_rem_img(message, "start", "Start Menu")


@Client.on_message(filters.command("addstartbutton") & filters.incoming, group=-2)
async def add_start_btn(client: Client, message: Message):
    await _handle_add_btn(message, "start", "Start Menu")


@Client.on_message(filters.command("editstartbuttons") & filters.incoming, group=-2)
async def edit_start_btn(client: Client, message: Message):
    await _handle_edit_btn(message, "start", "Start Menu")


@Client.on_message(filters.command("remstartbutton") & filters.incoming, group=-2)
async def rem_start_btn(client: Client, message: Message):
    await _handle_rem_btn(message, "start", "Start Menu")


@Client.on_message(filters.command("sethelptext") & filters.incoming, group=-2)
async def set_help_text(client: Client, message: Message):
    await _handle_set_text(message, "help", "Help Menu")


@Client.on_message(filters.command("defaulthelptext") & filters.incoming, group=-2)
async def def_help_text(client: Client, message: Message):
    await _handle_default_text(message, "help", "Help Menu")


@Client.on_message(filters.command("sethelpimage") & filters.incoming, group=-2)
async def set_help_img(client: Client, message: Message):
    if await _require_global_admin(message):
        await process_image_upload(client, message, "help_img", "Help Menu")


@Client.on_message(filters.command("remhelpimage") & filters.incoming, group=-2)
async def rem_help_img(client: Client, message: Message):
    await _handle_rem_img(message, "help", "Help Menu")


@Client.on_message(filters.command("addhelpbutton") & filters.incoming, group=-2)
async def add_help_btn(client: Client, message: Message):
    await _handle_add_btn(message, "help", "Help Menu")


@Client.on_message(filters.command("edithelpbuttons") & filters.incoming, group=-2)
async def edit_help_btn(client: Client, message: Message):
    await _handle_edit_btn(message, "help", "Help Menu")


@Client.on_message(filters.command("remhelpbutton") & filters.incoming, group=-2)
async def rem_help_btn(client: Client, message: Message):
    await _handle_rem_btn(message, "help", "Help Menu")


@Client.on_message(filters.command("setabouttext") & filters.incoming, group=-2)
async def set_about_text(client: Client, message: Message):
    await _handle_set_text(message, "about", "About Menu")


@Client.on_message(filters.command("defaultabouttext") & filters.incoming, group=-2)
async def def_about_text(client: Client, message: Message):
    await _handle_default_text(message, "about", "About Menu")


@Client.on_message(filters.command("setaboutimage") & filters.incoming, group=-2)
async def set_about_img(client: Client, message: Message):
    if await _require_global_admin(message):
        await process_image_upload(client, message, "about_img", "About Menu")


@Client.on_message(filters.command("remaboutimage") & filters.incoming, group=-2)
async def rem_about_img(client: Client, message: Message):
    await _handle_rem_img(message, "about", "About Menu")


@Client.on_message(filters.command("addaboutbutton") & filters.incoming, group=-2)
async def add_about_btn(client: Client, message: Message):
    await _handle_add_btn(message, "about", "About Menu")


@Client.on_message(filters.command("editaboutbuttons") & filters.incoming, group=-2)
async def edit_about_btn(client: Client, message: Message):
    await _handle_edit_btn(message, "about", "About Menu")


@Client.on_message(filters.command("remaboutbutton") & filters.incoming, group=-2)
async def rem_about_btn(client: Client, message: Message):
    await _handle_rem_btn(message, "about", "About Menu")


# ============================================================
# 🎯 LIVE UI PREVIEW ENGINE
# ============================================================
@Client.on_message(
    filters.command(["preview_ui", "preview"]) & filters.incoming, group=-2
)
async def preview_ui_cmd(client: Client, message: Message):
    if not await _require_global_admin(message):
        return

    if len(message.command) < 2 or message.command[1].lower() not in (
        "start",
        "help",
        "about",
    ):
        return await safe_reply_text(
            message,
            "⚠️ <b>Usage:</b>\n<code>/preview_ui start</code>\n<code>/preview_ui help</code>\n<code>/preview_ui about</code>",
            parse_mode=enums.ParseMode.HTML,
        )

    menu = message.command[1].lower()
    ui = await get_ui(force_refresh=True)

    fallback_map = {
        "start": getattr(script, "START_TXT", "Hello {mention}!"),
        "help": getattr(script, "HELP_TXT", "<b>Help Menu</b>"),
        "about": getattr(script, "ABOUT_TXT", "<b>About Bot</b>"),
    }
    text = ui.get(f"{menu}_text") or fallback_map[menu]
    img = ui.get(f"{menu}_img") or getattr(info, f"{menu.upper()}_IMG", None)
    btns_data = ui.get(f"{menu}_buttons", [])

    mention = message.from_user.mention if message.from_user else "Admin"
    text = text.replace("{mention}", mention)

    keyboard = build_custom_button_rows(btns_data)
    reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None

    try:
        if img and len(text) <= 1024:
            await message.reply_photo(
                photo=img,
                caption=text,
                reply_markup=reply_markup,
                parse_mode=enums.ParseMode.HTML,
            )
        else:
            await safe_reply_text(
                message,
                text=text,
                reply_markup=reply_markup,
                disable_web_page_preview=True,
                parse_mode=enums.ParseMode.HTML,
            )
    except Exception as e:
        await safe_reply_text(
            message,
            f"❌ <b>Preview Render Error:</b>\n<code>{html.escape(str(e))}</code>\n\n<i>(Check if your image URL or File ID is valid)</i>",
            parse_mode=enums.ParseMode.HTML,
        )
