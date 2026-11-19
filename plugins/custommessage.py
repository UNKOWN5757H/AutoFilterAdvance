import asyncio
import inspect
import re
from logging import ERROR, getLogger
from typing import Any, List, Optional

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
from pyrogram.types import InlineKeyboardMarkup, Message

import info

try:
    from database.ia_filterdb import get_all_healthy_read_dbs, get_writable_System_db
except ImportError:
    get_all_healthy_read_dbs = None
    get_writable_System_db = None

try:
    from plugins.pm_filter import sanitize_markup_hide_links
except ImportError:
    try:
        from pm_filter import sanitize_markup_hide_links
    except ImportError:

        def sanitize_markup_hide_links(
            markup: Optional[InlineKeyboardMarkup],
        ) -> Optional[InlineKeyboardMarkup]:
            return markup


logger = getLogger(__name__)
logger.setLevel(ERROR)

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


# ============================================================
# ⚙️ QUOTA-SAFE MULTI-DB PERMANENT SETTINGS
# ============================================================
_custom_db = None
_global_settings_db = None
_CUSTOM_BOOT_LOADED = False

try:
    _DB_CLIENT = AsyncIOMotorClient(
        info.DATABASE_URI,
        serverSelectionTimeoutMS=4000,
        connectTimeoutMS=4000,
        socketTimeoutMS=8000,
    )
    _BOT_DB = _DB_CLIENT[info.DATABASE_NAME]
    _custom_db = _BOT_DB["custom_captions"]
    _global_settings_db = _BOT_DB["global_bot_settings"]
except Exception as e:
    logger.error(f"Failed to init custommessage DB: {e}")

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


def _get_candidate_cols(col_name: str, fallback_col: Any) -> List[Any]:
    cols = []
    if callable(get_writable_System_db):
        try:
            w_db = get_writable_System_db()
            if w_db is not None:
                cols.append(w_db[col_name])
        except Exception:
            pass
    if callable(get_all_healthy_read_dbs):
        try:
            for _, r_db in get_all_healthy_read_dbs():
                c = r_db[col_name]
                if c not in cols:
                    cols.append(c)
        except Exception:
            pass
    if fallback_col is not None and fallback_col not in cols:
        cols.append(fallback_col)
    return cols


async def save_msg_data(key: str, value: Any):
    setattr(info, key, value)
    for col in _get_candidate_cols("custom_captions", _custom_db):
        try:
            await asyncio.wait_for(
                col.update_one(
                    {"_id": "settings"}, {"$set": {key: value}}, upsert=True
                ),
                timeout=2.5,
            )
        except Exception:
            continue

    global_key = _REVERSE_GLOBAL_MAP.get(key)
    if global_key:
        for col in _get_candidate_cols("global_bot_settings", _global_settings_db):
            try:
                await asyncio.wait_for(
                    col.update_one(
                        {"_id": "bot_config"},
                        {"$set": {global_key: value}},
                        upsert=True,
                    ),
                    timeout=2.5,
                )
            except Exception:
                continue
        try:
            from plugins.custom_settings import update_bot_settings

            await update_bot_settings(global_key, value)
        except Exception:
            pass


@Client.on_message(filters.all, group=-998)
async def load_custom_messages_on_boot(client: Client, message: Message):
    global _CUSTOM_BOOT_LOADED
    if _CUSTOM_BOOT_LOADED:
        return
    _CUSTOM_BOOT_LOADED = True

    for col in _get_candidate_cols("custom_captions", _custom_db):
        try:
            doc = await asyncio.wait_for(col.find_one({"_id": "settings"}), timeout=2.5)
            if doc:
                for k, v in doc.items():
                    if k != "_id" and v is not None:
                        setattr(info, k, v)
                break
        except Exception:
            continue


# ============================================================
# 👑 FULL POWER ADMIN CHECKER
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


async def _require_admin(client: Client, message: Message) -> bool:
    if await is_user_admin(client, message):
        return True
    await safe_reply_text(
        message,
        "❌ <b>Unauthorized:</b> Admin access required.",
        parse_mode=enums.ParseMode.HTML,
    )
    return False


# ============================================================
# ☁️ RELIABLE CLOUD IMAGE UPLOADER
# ============================================================
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


async def upload_image_safely(client: Client, message: Message) -> Optional[str]:
    try:
        file_io = await client.download_media(message, in_memory=True)
        if not file_io:
            return None
        return await asyncio.to_thread(_upload_sync, file_io.getvalue())
    except Exception:
        return None


# ============================================================
# 🛠️ TEXT & IMAGE SETTING PROCESSORS
# ============================================================
async def process_text_setting(
    client: Client, message: Message, var_name: str, setting_name: str
):
    if not await _require_admin(client, message):
        return

    if len(message.command) > 1 and message.command[1].strip().lower() in (
        "off",
        "reset",
        "clear",
        "default",
        "none",
    ):
        await save_msg_data(var_name, None)
        return await safe_reply_text(
            message,
            f"✅ <b>{setting_name} has been REMOVED.</b>\nSystem will now use the default message.",
            parse_mode=enums.ParseMode.HTML,
        )

    raw_text = None
    if (
        message.reply_to_message
        and len(getattr(message, "command", [])) == 1
        and (message.reply_to_message.text or message.reply_to_message.caption)
    ):
        content = message.reply_to_message.text or message.reply_to_message.caption
        raw_text = getattr(content, "html", str(content)).strip()
    elif message.text and len(message.command) > 1:
        html_text = getattr(message.text, "html", str(message.text))
        raw_text = re.sub(
            r"^/\w+(?:@[a-zA-Z0-9_]+)?\s+", "", html_text, count=1
        ).strip()

    if not raw_text:
        return await safe_reply_text(
            message,
            f"⚙️ <b>Usage:</b>\n"
            f"• Reply to a text message with <code>/{message.command[0]}</code>\n"
            f"• Or send <code>/{message.command[0]} Your Text Here</code>\n"
            f"• Or use <code>/{message.command[0]} off</code> to reset to default.",
            parse_mode=enums.ParseMode.HTML,
        )

    await save_msg_data(var_name, raw_text)
    await safe_reply_text(
        message,
        f"✅ <b>{setting_name} successfully updated!</b>\n\n"
        f"<b>New Message:</b>\n{raw_text}",
        disable_web_page_preview=True,
        parse_mode=enums.ParseMode.HTML,
    )


async def process_image_setting(
    client: Client, message: Message, var_name: str, setting_name: str
):
    if not await _require_admin(client, message):
        return

    if len(message.command) > 1 and message.command[1].strip().lower() in (
        "off",
        "reset",
        "clear",
        "default",
        "none",
    ):
        await save_msg_data(var_name, None)
        return await safe_reply_text(
            message,
            f"✅ <b>{setting_name} has been REMOVED.</b>\nSystem will now use the default image.",
            parse_mode=enums.ParseMode.HTML,
        )

    target_msg = (
        message.reply_to_message
        if (message.reply_to_message and message.reply_to_message.photo)
        else (message if message.photo else None)
    )

    if target_msg is None and len(message.command) > 1:
        arg = message.text.split(None, 1)[1].strip()
        if arg.startswith(("http://", "https://")) or len(arg) > 20:
            await save_msg_data(var_name, arg)
            return await safe_reply_text(
                message,
                f"✅ <b>{setting_name} updated!</b>",
                parse_mode=enums.ParseMode.HTML,
            )

    if not target_msg or not target_msg.photo:
        return await safe_reply_text(
            message,
            f"⚙️ <b>Usage:</b>\n"
            f"• Reply to a photo with <code>/{message.command[0]}</code> to set it.\n"
            f"• Or use <code>/{message.command[0]} off</code> to disable.",
            parse_mode=enums.ParseMode.HTML,
        )

    status = await safe_reply_text(
        message, "⏳ <b>Uploading to Cloud...</b>", parse_mode=enums.ParseMode.HTML
    )
    url = await upload_image_safely(client, target_msg)
    if url:
        await save_msg_data(var_name, url)
        if status:
            await safe_edit_text(
                status,
                f"✅ <b>{setting_name} updated to Cloud Image!</b>",
                parse_mode=enums.ParseMode.HTML,
            )
    else:
        await save_msg_data(var_name, target_msg.photo.file_id)
        if status:
            await safe_edit_text(
                status,
                f"⚠️ Cloud upload failed. <b>{setting_name} saved as Telegram File ID!</b>",
                parse_mode=enums.ParseMode.HTML,
            )


# ============================================================
# 🎯 COMMAND HANDLERS
# ============================================================
@Client.on_message(filters.command("infomsg") & filters.incoming, group=-2)
async def set_info_msg(bot: Client, message: Message):
    await process_text_setting(bot, message, "INFO_MSG", "Info Message")


@Client.on_message(filters.command("infoimg") & filters.incoming, group=-2)
async def set_info_img(bot: Client, message: Message):
    await process_image_setting(bot, message, "INFO_IMG", "Info Image")


@Client.on_message(filters.command("delmsg") & filters.incoming, group=-2)
async def set_del_msg(bot: Client, message: Message):
    await process_text_setting(bot, message, "DEL_MSG", "Delete Message")


@Client.on_message(filters.command("delimg") & filters.incoming, group=-2)
async def set_del_img(bot: Client, message: Message):
    await process_image_setting(bot, message, "DEL_IMG", "Delete Image")


@Client.on_message(filters.command("notfoundmsg") & filters.incoming, group=-2)
async def set_notfound_msg(bot: Client, message: Message):
    await process_text_setting(bot, message, "NOT_FOUND_MSG", "File Not Found Message")


@Client.on_message(filters.command("notfoundimg") & filters.incoming, group=-2)
async def set_notfound_img(bot: Client, message: Message):
    await process_image_setting(bot, message, "NOT_FOUND_IMG", "File Not Found Image")


@Client.on_message(filters.command("fsubmsg") & filters.incoming, group=-2)
async def set_fsub_msg(bot: Client, message: Message):
    await process_text_setting(bot, message, "FSUB_MSG", "Force Subscribe Message")


@Client.on_message(filters.command("fsubimg") & filters.incoming, group=-2)
async def set_fsub_img(bot: Client, message: Message):
    await process_image_setting(bot, message, "FSUB_IMG", "Force Subscribe Image")
