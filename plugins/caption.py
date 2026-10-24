import asyncio
import html
import inspect
import re
from logging import ERROR, getLogger
from typing import Any, Optional, Tuple

from motor.motor_asyncio import AsyncIOMotorClient
from pyrogram import Client, enums, filters
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

try:
    from database.ia_filterdb import (
        get_all_configured_dbs,
        get_all_healthy_read_dbs,
        mark_db_error,
    )
except ImportError:
    get_all_configured_dbs = None
    get_all_healthy_read_dbs = None
    mark_db_error = None

logger = getLogger(__name__)
logger.setLevel(ERROR)

# Keep a permanent copy of the original default caption from info.py
_DEFAULT_CUSTOM_FILE_CAPTION = getattr(info, "CUSTOM_FILE_CAPTION", None)

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

_REPLY_PARAMS = set(inspect.signature(Message.reply_text).parameters.keys())
_EDIT_PARAMS = set(inspect.signature(Message.edit_text).parameters.keys())


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
    compat_kw = _prepare_compat_kwargs(
        kwargs, _REPLY_PARAMS, disable_preview=disable_web_page_preview
    )
    try:
        return await message.reply_text(text, **compat_kw)
    except TypeError:
        compat_kw.pop("disable_web_page_preview", None)
        compat_kw.pop("link_preview_options", None)
        compat_kw.pop("reply_parameters", None)
        compat_kw.pop("reply_to_message_id", None)
        return await message.reply_text(text, **compat_kw)
    except (ChatWriteForbidden, Forbidden, UserIsBlocked, PeerIdInvalid):
        return None


async def safe_edit_text(
    message: Message, text: str, disable_web_page_preview: bool = True, **kwargs
):
    compat_kw = _prepare_compat_kwargs(
        kwargs, _EDIT_PARAMS, disable_preview=disable_web_page_preview
    )
    try:
        return await message.edit_text(text, **compat_kw)
    except TypeError:
        compat_kw.pop("disable_web_page_preview", None)
        compat_kw.pop("link_preview_options", None)
        return await message.edit_text(text, **compat_kw)
    except (MessageNotModified, MessageIdInvalid, ChatWriteForbidden, Forbidden):
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
# ⚙️ QUOTA-SAFE MULTI-DB PERMANENT STORAGE ENGINE
# ============================================================
_caption_db = None
_global_settings_db = None
_CAPTION_BOOT_LOADED = False

try:
    _DB_CLIENT = AsyncIOMotorClient(
        info.DATABASE_URI,
        serverSelectionTimeoutMS=4000,
        connectTimeoutMS=4000,
        socketTimeoutMS=8000,
    )
    _BOT_DB = _DB_CLIENT[info.DATABASE_NAME]
    _caption_db = _BOT_DB["custom_captions"]
    _global_settings_db = _BOT_DB["global_bot_settings"]
except Exception as e:
    logger.error(f"Failed to init Caption DB: {e}")

# Sync map between info attributes and global_bot_settings keys
_REVERSE_GLOBAL_MAP = {
    "FSUB_IMG": "fsub_img",
    "FSUB_MSG": "fsub_msg",
    "NOT_FOUND_IMG": "not_found_img",
    "NOT_FOUND_MSG": "not_found_text",
    "INFO_MSG": "info_msg",
    "INFO_IMG": "info_img",
    "DEL_MSG": "del_msg",
    "DEL_IMG": "del_img",
}


def _get_all_dbs_list():
    if callable(get_all_configured_dbs):
        dbs = [
            (idx, handle)
            for idx, handle, _ in get_all_configured_dbs(include_when_disabled=True)
            if handle is not None
        ]
        if dbs:
            return dbs
    if callable(get_all_healthy_read_dbs):
        dbs = get_all_healthy_read_dbs()
        if dbs:
            return dbs
    return [(1, _BOT_DB)] if _BOT_DB is not None else []


async def save_custom_data(key: str, value: Any):
    """
    Saves custom caption / message settings to `info` in RAM immediately AND
    writes across all configured databases (Primary DB + /datadb URLs) so
    even if DB 1 is 512 MB full, your custom caption is permanently saved!
    """
    if key == "CUSTOM_FILE_CAPTION":
        effective_val = _DEFAULT_CUSTOM_FILE_CAPTION if value == "DEFAULT" else value
        setattr(info, "CUSTOM_FILE_CAPTION", effective_val)
        setattr(info, "BATCH_FILE_CAPTION", effective_val)
    else:
        setattr(info, key, value)

    # Also update commands.CUSTOM_FILE_CAPTION if imported directly
    if key == "CUSTOM_FILE_CAPTION":
        try:
            import plugins.commands as _cmds

            _cmds.CUSTOM_FILE_CAPTION = getattr(info, "CUSTOM_FILE_CAPTION", None)
        except Exception:
            pass

    for idx, target_db in _get_all_dbs_list():
        try:
            await target_db["custom_captions"].update_one(
                {"_id": "settings"}, {"$set": {key: value}}, upsert=True
            )
        except Exception as e:
            if callable(mark_db_error):
                mark_db_error(idx, e)

    global_key = _REVERSE_GLOBAL_MAP.get(key)
    if global_key:
        for idx, target_db in _get_all_dbs_list():
            try:
                await target_db["global_bot_settings"].update_one(
                    {"_id": "bot_config"}, {"$set": {global_key: value}}, upsert=True
                )
            except Exception:
                pass
        try:
            from plugins.custom_settings import update_bot_settings

            await update_bot_settings(global_key, value)
        except Exception:
            pass


@Client.on_message(filters.all, group=-997)
async def load_captions_on_boot(client: Client, message: Message):
    """Restores saved custom captions, messages, and images into `info` on bot startup across all DBs."""
    global _CAPTION_BOOT_LOADED
    if _CAPTION_BOOT_LOADED:
        return
    _CAPTION_BOOT_LOADED = True

    for idx, target_db in _get_all_dbs_list():
        try:
            doc = await target_db["custom_captions"].find_one({"_id": "settings"})
            if doc:
                for k, v in doc.items():
                    if k == "_id":
                        continue
                    if k == "CUSTOM_FILE_CAPTION":
                        if v == "DEFAULT":
                            setattr(
                                info,
                                "CUSTOM_FILE_CAPTION",
                                _DEFAULT_CUSTOM_FILE_CAPTION,
                            )
                        else:
                            setattr(info, "CUSTOM_FILE_CAPTION", v)
                    elif v is not None:
                        setattr(info, k, v)
                break
        except Exception as e:
            if callable(mark_db_error):
                mark_db_error(idx, e)


# ============================================================
# 👑 FULL POWER ADMIN CHECKER (GLOBAL + CHAT + ANONYMOUS)
# ============================================================
def get_admin_list():
    raw_admins = getattr(info, "ADMINS", [])
    if isinstance(raw_admins, (str, int)):
        raw_admins = str(raw_admins).replace(",", " ").split()
    elif isinstance(raw_admins, (list, tuple, set)):
        raw_admins = list(raw_admins)
    else:
        raw_admins = []
    return [int(x) for x in raw_admins if str(x).strip().lstrip("-").isdigit()]


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

    return False


async def is_callback_user_admin(client: Client, query: CallbackQuery) -> bool:
    if not query or not query.from_user:
        return False
    if query.from_user.id in get_admin_list():
        return True
    if (
        query.message
        and query.message.chat
        and query.message.chat.type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]
    ):
        try:
            member = await client.get_chat_member(
                query.message.chat.id, query.from_user.id
            )
            return member.status in [
                enums.ChatMemberStatus.ADMINISTRATOR,
                enums.ChatMemberStatus.OWNER,
            ]
        except Exception:
            pass
    return False


def extract_html_payload(message: Message) -> Optional[str]:
    """Extracts HTML text from either a replied message or inline command arguments."""
    if (
        message.reply_to_message
        and len(getattr(message, "command", [])) == 1
        and (message.reply_to_message.text or message.reply_to_message.caption)
    ):
        replied = message.reply_to_message
        content = replied.text or replied.caption
        if content:
            return getattr(content, "html", str(content))
    if message.text and len(message.command) > 1:
        html_text = getattr(message.text, "html", str(message.text))
        cleaned = re.sub(
            r"^/\w+(?:@[a-zA-Z0-9_]+)?\s+", "", html_text, count=1
        ).strip()
        return cleaned or None
    return None


# ============================================================
# 📝 PROCESSING ENGINE FOR FILE CAPTIONS
# ============================================================
async def process_text_setting(
    client: Client, message: Message, var_name: str, setting_name: str
):
    if not await is_user_admin(client, message):
        return await safe_reply_text(
            message,
            "❌ <b>Unauthorized:</b> Admin access required.",
            parse_mode=enums.ParseMode.HTML,
        )

    if len(message.command) > 1:
        arg1 = message.command[1].strip().lower()
        if arg1 in ("off", "clear", "none", "disable"):
            await save_custom_data(var_name, None)
            return await safe_reply_text(
                message,
                f"🗑️ <b>{setting_name} has been DISABLED (Only filename will be shown).</b>",
                parse_mode=enums.ParseMode.HTML,
            )
        if arg1 in ("reset", "default"):
            await save_custom_data(
                var_name,
                "DEFAULT" if var_name == "CUSTOM_FILE_CAPTION" else None,
            )
            return await safe_reply_text(
                message,
                f"✅ <b>{setting_name} has been restored to the default template!</b>",
                parse_mode=enums.ParseMode.HTML,
            )

    raw_text = extract_html_payload(message)
    if not raw_text:
        cur_val = getattr(info, var_name, None)
        cur_preview = (
            f"\n\n<b>Current {setting_name}:</b>\n<code>{html.escape(str(cur_val))}</code>"
            if cur_val
            else "\n\n<b>Current Status:</b> <code>Disabled / None</code>"
        )
        return await safe_reply_text(
            message,
            f"⚙️ <b>Usage:</b>\n"
            f"• Reply to a text message with <code>/{message.command[0]}</code>\n"
            f"• Or send <code>/{message.command[0]} Your Text Here</code>\n"
            f"• Send <code>/{message.command[0]} default</code> to restore default\n"
            f"• Send <code>/{message.command[0]} off</code> to disable\n\n"
            f"💡 <b>Supported Variables:</b> <code>{{file_name}}</code>, <code>{{file_size}}</code>, <code>{{file_caption}}</code>"
            f"{cur_preview}",
            parse_mode=enums.ParseMode.HTML,
        )

    await save_custom_data(var_name, raw_text)
    await safe_reply_text(
        message,
        f"✅ <b>{setting_name} successfully updated permanently!</b>\n\n"
        f"<b>New Value:</b>\n{raw_text}",
        disable_web_page_preview=True,
        parse_mode=enums.ParseMode.HTML,
    )


# ============================================================
# 🎛️ CUSTOM FILE CAPTION COMMANDS & INTERACTIVE DASHBOARD
# ============================================================
def _build_caption_dashboard() -> Tuple[str, InlineKeyboardMarkup]:
    cap = getattr(info, "CUSTOM_FILE_CAPTION", None)
    cap_plus = getattr(info, "CAPTION_PLUS", None)
    fsub_msg = getattr(info, "FSUB_MSG", None)
    nf_msg = getattr(info, "NOT_FOUND_MSG", None)

    cap_status = "🟢 Active" if cap else "🔴 Disabled (Filename Only)"
    plus_status = "🟢 Active" if cap_plus else "🔴 None"
    fsub_status = "🟢 Custom Set" if fsub_msg else "⚪️ Default"
    nf_status = "🟢 Custom Set" if nf_msg else "⚪️ Default"

    preview_cap = (
        html.escape(str(cap)[:300] + ("..." if cap and len(str(cap)) > 300 else ""))
        if cap
        else "<i>None (Only {file_name} is sent)</i>"
    )
    preview_plus = (
        html.escape(
            str(cap_plus)[:150]
            + ("..." if cap_plus and len(str(cap_plus)) > 150 else "")
        )
        if cap_plus
        else "<i>None</i>"
    )

    text = (
        "📝 <b>Custom Caption & Message Manager</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"📄 <b>File Caption:</b> <code>{cap_status}</code>\n"
        f"➕ <b>Caption Plus:</b> <code>{plus_status}</code>\n"
        f"🔐 <b>FSub Message:</b> <code>{fsub_status}</code>\n"
        f"🚫 <b>Not Found Text:</b> <code>{nf_status}</code>\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>Current File Caption Template:</b>\n<code>{preview_cap}</code>\n\n"
        f"<b>Current Caption Plus Footer:</b>\n<code>{preview_plus}</code>\n\n"
        "💡 <b>Variables for</b> <code>/customcaption</code>:\n"
        "<code>{file_name}</code> | <code>{file_size}</code> | <code>{file_caption}</code>"
    )

    buttons = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "♻️ Restore Default Caption", callback_data="cap_ctl:default_cap"
                ),
                InlineKeyboardButton(
                    "🗑️ Turn Off Caption", callback_data="cap_ctl:reset_cap"
                ),
            ],
            [
                InlineKeyboardButton(
                    "🗑️ Clear Caption Plus", callback_data="cap_ctl:reset_plus"
                ),
                InlineKeyboardButton("🔄 Refresh", callback_data="cap_ctl:refresh"),
            ],
            [
                InlineKeyboardButton("🔐 Close", callback_data="cap_ctl:close"),
            ],
        ]
    )
    return text, buttons


@Client.on_message(
    filters.command(["caption", "captions", "captionsettings"]) & filters.incoming,
    group=-2,
)
async def caption_dashboard_cmd(bot: Client, message: Message):
    if not await is_user_admin(bot, message):
        return await safe_reply_text(
            message,
            "❌ <b>Unauthorized:</b> Admin access required.",
            parse_mode=enums.ParseMode.HTML,
        )
    text, markup = _build_caption_dashboard()
    await safe_reply_text(
        message, text, reply_markup=markup, parse_mode=enums.ParseMode.HTML
    )


@Client.on_callback_query(
    filters.regex(r"^cap_ctl:(default_cap|reset_cap|reset_plus|refresh|close)$"),
    group=-2,
)
async def caption_dashboard_cb(client: Client, query: CallbackQuery):
    if not await is_callback_user_admin(client, query):
        return await safe_answer(
            query, "❌ Unauthorized: Admins only!", show_alert=True
        )

    action = query.matches[0].group(1)
    try:
        if action == "close":
            await safe_answer(query, "Closed!")
            return await query.message.delete()
        elif action == "default_cap":
            await save_custom_data("CUSTOM_FILE_CAPTION", "DEFAULT")
            await safe_answer(
                query, "✅ Default File Caption Restored!", show_alert=True
            )
        elif action == "reset_cap":
            await save_custom_data("CUSTOM_FILE_CAPTION", None)
            await safe_answer(
                query, "🗑️ Custom File Caption Disabled!", show_alert=True
            )
        elif action == "reset_plus":
            await save_custom_data("CAPTION_PLUS", None)
            await safe_answer(query, "✅ Caption Plus footer removed!", show_alert=True)
        else:
            await safe_answer(query, "Refreshed!")

        text, markup = _build_caption_dashboard()
        await safe_edit_text(
            query.message, text, reply_markup=markup, parse_mode=enums.ParseMode.HTML
        )
    except Exception as e:
        logger.error(f"Caption dashboard callback error: {e}")


@Client.on_message(
    filters.command(["customcaption", "setcaption", "set_caption"]) & filters.incoming,
    group=-2,
)
async def set_file_caption_cmd(bot: Client, message: Message):
    await process_text_setting(
        bot, message, "CUSTOM_FILE_CAPTION", "Custom File Caption"
    )


@Client.on_message(
    filters.command(["defaultcaption", "resetcaption"]) & filters.incoming,
    group=-2,
)
async def default_file_caption_cmd(bot: Client, message: Message):
    if not await is_user_admin(bot, message):
        return await safe_reply_text(
            message,
            "❌ <b>Unauthorized:</b> Admin access required.",
            parse_mode=enums.ParseMode.HTML,
        )
    await save_custom_data("CUSTOM_FILE_CAPTION", "DEFAULT")
    await safe_reply_text(
        message,
        "✅ <b>Custom File Caption has been restored to default!</b>",
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(
    filters.command(["delcaption", "remcaption"]) & filters.incoming,
    group=-2,
)
async def del_file_caption_cmd(bot: Client, message: Message):
    if not await is_user_admin(bot, message):
        return await safe_reply_text(
            message,
            "❌ <b>Unauthorized:</b> Admin access required.",
            parse_mode=enums.ParseMode.HTML,
        )
    await save_custom_data("CUSTOM_FILE_CAPTION", None)
    await safe_reply_text(
        message,
        "🗑️ <b>Custom File Caption has been disabled (only filename will be sent).</b>",
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(
    filters.command(["setcaptionplus", "captionplus"]) & filters.incoming,
    group=-2,
)
async def set_caption_plus_cmd(bot: Client, message: Message):
    await process_text_setting(bot, message, "CAPTION_PLUS", "Caption Plus Footer")


@Client.on_message(
    filters.command(["remcaptionplus", "delcaptionplus"]) & filters.incoming,
    group=-2,
)
async def rem_caption_plus_cmd(bot: Client, message: Message):
    if not await is_user_admin(bot, message):
        return await safe_reply_text(
            message,
            "❌ <b>Unauthorized:</b> Admin access required.",
            parse_mode=enums.ParseMode.HTML,
        )
    await save_custom_data("CAPTION_PLUS", None)
    await safe_reply_text(
        message,
        "🗑️ <b>Caption Plus footer has been removed.</b>",
        parse_mode=enums.ParseMode.HTML,
    )
