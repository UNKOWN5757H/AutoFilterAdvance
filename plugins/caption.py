import asyncio
import html
import re
from logging import ERROR, getLogger

import requests
from motor.motor_asyncio import AsyncIOMotorClient
from pyrogram import Client, enums, filters
from pyrogram.errors import MessageNotModified, QueryIdInvalid
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
# ⚙️ MONGODB PERMANENT STORAGE ENGINE
# ============================================================
_caption_db = None
_global_settings_db = None
_CAPTION_BOOT_LOADED = False

try:
    _DB_CLIENT = AsyncIOMotorClient(info.DATABASE_URI)
    _BOT_DB = _DB_CLIENT[info.DATABASE_NAME]
    _caption_db = _BOT_DB["custom_captions"]
    _global_settings_db = _BOT_DB["global_bot_settings"]
except Exception as e:
    logger.error(f"Failed to init Caption DB: {e}")

# Sync map between info attributes and global_bot_settings keys
_REVERSE_GLOBAL_MAP = {
    "FSUB_IMG": "fsub_img",
    "NOT_FOUND_IMG": "not_found_img",
    "NOT_FOUND_MSG": "not_found_text",
}


async def save_custom_data(key: str, value):
    setattr(info, key, value)
    if _caption_db is not None:
        try:
            await _caption_db.update_one(
                {"_id": "settings"}, {"$set": {key: value}}, upsert=True
            )
        except Exception as e:
            logger.error(f"Error saving {key} to custom_captions: {e}")

    global_key = _REVERSE_GLOBAL_MAP.get(key)
    if global_key and _global_settings_db is not None:
        try:
            await _global_settings_db.update_one(
                {"_id": "bot_config"}, {"$set": {global_key: value}}, upsert=True
            )
        except Exception:
            pass


@Client.on_message(filters.all, group=-997)
async def load_captions_on_boot(client: Client, message: Message):
    """Restores saved custom captions, messages, and images into `info` on bot startup."""
    global _CAPTION_BOOT_LOADED
    if _CAPTION_BOOT_LOADED:
        return
    _CAPTION_BOOT_LOADED = True
    if _caption_db is None:
        return
    try:
        doc = await _caption_db.find_one({"_id": "settings"})
        if doc:
            for k, v in doc.items():
                if k != "_id" and v is not None:
                    setattr(info, k, v)
    except Exception as e:
        logger.error(f"Failed to load custom captions on boot: {e}")


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

    # 1. Global Admin Check (Direct User)
    if message.from_user and message.from_user.id in admin_list:
        return True

    # 2. Global Admin Check (Anonymous/Channel sending as Chat)
    if message.sender_chat and message.sender_chat.id in admin_list:
        return True

    # 3. Group Admin Check (Normal & Anonymous Admins)
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


async def admin_check(_, client: Client, message: Message) -> bool:
    return await is_user_admin(client, message)


admin_filter = filters.create(admin_check)


# ============================================================
# ⚡ MULTI-LAYER CLOUD IMAGE UPLOAD ENGINE (ZERO-FAIL)
# ============================================================
def _upload_sync(file_bytes):
    headers = {"User-Agent": "Mozilla/5.0"}
    for url, files_dict, data_dict in [
        (
            "https://catbox.moe/user/api.php",
            {"fileToUpload": ("img.jpg", file_bytes, "image/jpeg")},
            {"reqtype": "fileupload"},
        ),
        (
            "https://graph.org/upload",
            {"file": ("img.jpg", file_bytes, "image/jpeg")},
            None,
        ),
        ("https://envs.sh", {"file": ("img.jpg", file_bytes, "image/jpeg")}, None),
        ("https://x0.at", {"file": ("img.jpg", file_bytes, "image/jpeg")}, None),
        ("https://ttm.sh", {"file": ("img.jpg", file_bytes, "image/jpeg")}, None),
        ("https://0x0.st", {"file": ("img.jpg", file_bytes, "image/jpeg")}, None),
        (
            "https://telegra.ph/upload",
            {"file": ("img.jpg", file_bytes, "image/jpeg")},
            None,
        ),
    ]:
        try:
            res = requests.post(
                url, data=data_dict, files=files_dict, headers=headers, timeout=8
            )
            if res.status_code in [200, 201]:
                if url in ["https://graph.org/upload", "https://telegra.ph/upload"]:
                    return url.rsplit("/", 1)[0] + res.json()[0]["src"]
                elif res.text.strip().startswith("http"):
                    return res.text.strip()
        except Exception:
            continue
    return None


async def upload_image_safely(client: Client, message: Message):
    try:
        file_io = await client.download_media(message, in_memory=True)
        if not file_io:
            return None
        return await asyncio.to_thread(_upload_sync, file_io.getvalue())
    except Exception:
        return None


def extract_html_payload(message: Message) -> str | None:
    """Extracts HTML text from either a replied message or inline command arguments."""
    if message.reply_to_message:
        replied = message.reply_to_message
        content = replied.text or replied.caption
        if content:
            return getattr(content, "html", str(content))
    if message.text and len(message.command) > 1:
        html_text = getattr(message.text, "html", str(message.text))
        cleaned = re.sub(r"^/\w+(?:@[a-zA-Z0-9_]+)?\s+", "", html_text, count=1).strip()
        return cleaned or None
    return None


# ============================================================
# 📝 PROCESSING ENGINES
# ============================================================
async def process_text_setting(message: Message, var_name: str, setting_name: str):
    if len(message.command) > 1 and message.command[1].strip().lower() in (
        "off",
        "reset",
        "clear",
        "default",
        "none",
    ):
        await save_custom_data(var_name, None)
        return await message.reply_text(
            f"✅ <b>{setting_name} has been REMOVED.</b>\nSystem will now use the default message.",
            parse_mode=enums.ParseMode.HTML,
        )

    raw_text = extract_html_payload(message)
    if not raw_text:
        return await message.reply_text(
            f"⚙️ <b>Usage:</b>\n"
            f"• Reply to a text message with <code>/{message.command[0]}</code>\n"
            f"• Or send <code>/{message.command[0]} Your Text Here</code>\n"
            f"• Or use <code>/{message.command[0]} off</code> to reset to default.",
            parse_mode=enums.ParseMode.HTML,
        )

    await save_custom_data(var_name, raw_text)
    await message.reply_text(
        f"✅ <b>{setting_name} successfully updated permanently!</b>\n\n"
        f"<b>New Value:</b>\n{raw_text}",
        disable_web_page_preview=True,
        parse_mode=enums.ParseMode.HTML,
    )


async def process_image_setting(
    client: Client, message: Message, var_name: str, setting_name: str
):
    if len(message.command) > 1 and message.command[1].strip().lower() in (
        "off",
        "reset",
        "clear",
        "default",
        "none",
    ):
        await save_custom_data(var_name, None)
        return await message.reply_text(
            f"✅ <b>{setting_name} has been REMOVED.</b>\nSystem will now use the default image.",
            parse_mode=enums.ParseMode.HTML,
        )

    if not message.reply_to_message or not message.reply_to_message.photo:
        return await message.reply_text(
            f"⚙️ <b>Usage:</b>\n"
            f"• Reply to a photo with <code>/{message.command[0]}</code> to set it.\n"
            f"• Or use <code>/{message.command[0]} off</code> to disable.",
            parse_mode=enums.ParseMode.HTML,
        )

    status = await message.reply_text(
        "⏳ <b>Uploading to Cloud...</b>", parse_mode=enums.ParseMode.HTML
    )
    url = await upload_image_safely(client, message.reply_to_message)

    if url:
        await save_custom_data(var_name, url)
        await status.edit_text(
            f"✅ <b>{setting_name} successfully updated to Cloud Image!</b>",
            parse_mode=enums.ParseMode.HTML,
        )
    else:
        file_id = message.reply_to_message.photo.file_id
        await save_custom_data(var_name, file_id)
        await status.edit_text(
            f"⚠️ Cloud blocked. <b>{setting_name} updated using Telegram File ID!</b>",
            parse_mode=enums.ParseMode.HTML,
        )


# ============================================================
# 🎛️ CUSTOM FILE CAPTION COMMANDS & INTERACTIVE DASHBOARD
# ============================================================
def _build_caption_dashboard() -> tuple[str, InlineKeyboardMarkup]:
    cap = getattr(info, "CUSTOM_FILE_CAPTION", None)
    cap_plus = getattr(info, "CAPTION_PLUS", None)
    fsub_msg = getattr(info, "FSUB_MSG", None)
    nf_msg = getattr(info, "NOT_FOUND_MSG", None)

    cap_status = "🟢 Custom Set" if cap else "⚪️ Default"
    plus_status = "🟢 Active" if cap_plus else "🔴 None"
    fsub_status = "🟢 Custom Set" if fsub_msg else "⚪️ Default"
    nf_status = "🟢 Custom Set" if nf_msg else "⚪️ Default"

    preview_cap = (
        html.escape(str(cap)[:180] + ("..." if cap and len(str(cap)) > 180 else ""))
        if cap
        else "<i>Default</i>"
    )
    preview_plus = (
        html.escape(
            str(cap_plus)[:120]
            + ("..." if cap_plus and len(str(cap_plus)) > 120 else "")
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
        "💡 <b>Variables for</b> <code>/setcaption</code>:\n"
        "<code>{file_name}</code> | <code>{file_size}</code> | <code>{file_caption}</code>"
    )

    buttons = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🗑️ Reset File Caption", callback_data="cap_ctl:reset_cap"
                ),
                InlineKeyboardButton(
                    "🗑️ Clear Caption Plus", callback_data="cap_ctl:reset_plus"
                ),
            ],
            [
                InlineKeyboardButton("🔄 Refresh", callback_data="cap_ctl:refresh"),
                InlineKeyboardButton("🔐 Close", callback_data="cap_ctl:close"),
            ],
        ]
    )
    return text, buttons


@Client.on_message(
    filters.command(["caption", "captions", "captionsettings"]) & admin_filter
)
async def caption_dashboard_cmd(bot: Client, message: Message):
    text, markup = _build_caption_dashboard()
    await message.reply_text(text, reply_markup=markup, parse_mode=enums.ParseMode.HTML)


@Client.on_callback_query(
    filters.regex(r"^cap_ctl:(reset_cap|reset_plus|refresh|close)$")
)
async def caption_dashboard_cb(client: Client, query: CallbackQuery):
    if not await is_callback_user_admin(client, query):
        return await query.answer("❌ Unauthorized: Admins only!", show_alert=True)

    action = query.matches[0].group(1)
    try:
        if action == "close":
            await query.answer("Closed!")
            return await query.message.delete()
        elif action == "reset_cap":
            await save_custom_data("CUSTOM_FILE_CAPTION", None)
            await query.answer("✅ File Caption reset to default!", show_alert=True)
        elif action == "reset_plus":
            await save_custom_data("CAPTION_PLUS", None)
            await query.answer("✅ Caption Plus footer removed!", show_alert=True)
        else:
            await query.answer("Refreshed!")

        text, markup = _build_caption_dashboard()
        await query.message.edit_text(
            text, reply_markup=markup, parse_mode=enums.ParseMode.HTML
        )
    except MessageNotModified:
        pass
    except QueryIdInvalid:
        pass
    except Exception as e:
        logger.error(f"Caption dashboard callback error: {e}")


@Client.on_message(filters.command(["setcaption", "set_caption"]) & admin_filter)
async def set_file_caption_cmd(bot: Client, message: Message):
    await process_text_setting(message, "CUSTOM_FILE_CAPTION", "Custom File Caption")


@Client.on_message(
    filters.command(["delcaption", "remcaption", "resetcaption", "defaultcaption"])
    & admin_filter
)
async def del_file_caption_cmd(bot: Client, message: Message):
    await save_custom_data("CUSTOM_FILE_CAPTION", None)
    await message.reply_text(
        "🗑️ <b>Custom File Caption has been reset to default.</b>",
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(filters.command(["setcaptionplus", "captionplus"]) & admin_filter)
async def set_caption_plus_cmd(bot: Client, message: Message):
    await process_text_setting(message, "CAPTION_PLUS", "Caption Plus Footer")


@Client.on_message(filters.command(["remcaptionplus", "delcaptionplus"]) & admin_filter)
async def rem_caption_plus_cmd(bot: Client, message: Message):
    await save_custom_data("CAPTION_PLUS", None)
    await message.reply_text(
        "🗑️ <b>Caption Plus footer has been removed.</b>",
        parse_mode=enums.ParseMode.HTML,
    )


# ============================================================
# 🎯 CUSTOM MESSAGE & IMAGE COMMANDS
# ============================================================
@Client.on_message(filters.command("infomsg") & admin_filter)
async def set_info_msg(bot: Client, message: Message):
    await process_text_setting(message, "INFO_MSG", "Info Message")


@Client.on_message(filters.command("infoimg") & admin_filter)
async def set_info_img(bot: Client, message: Message):
    await process_image_setting(bot, message, "INFO_IMG", "Info Image")


@Client.on_message(filters.command("delmsg") & admin_filter)
async def set_del_msg(bot: Client, message: Message):
    await process_text_setting(message, "DEL_MSG", "Delete Message")


@Client.on_message(filters.command("delimg") & admin_filter)
async def set_del_img(bot: Client, message: Message):
    await process_image_setting(bot, message, "DEL_IMG", "Delete Image")


@Client.on_message(filters.command("notfoundmsg") & admin_filter)
async def set_notfound_msg(bot: Client, message: Message):
    await process_text_setting(message, "NOT_FOUND_MSG", "File Not Found Message")


@Client.on_message(filters.command("notfoundimg") & admin_filter)
async def set_notfound_img(bot: Client, message: Message):
    await process_image_setting(bot, message, "NOT_FOUND_IMG", "File Not Found Image")


@Client.on_message(filters.command("fsubmsg") & admin_filter)
async def set_fsub_msg(bot: Client, message: Message):
    await process_text_setting(message, "FSUB_MSG", "Force Subscribe Message")


@Client.on_message(filters.command("fsubimg") & admin_filter)
async def set_fsub_img(bot: Client, message: Message):
    await process_image_setting(bot, message, "FSUB_IMG", "Force Subscribe Image")
