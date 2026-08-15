import ast
import asyncio
import logging
import re

from pyrogram import Client, enums, filters
from pyrogram.enums import ButtonStyle
from pyrogram.errors import Forbidden
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

import info
from database.connections_mdb import active_connection
from database.filters_mdb import add_filter, delete_filter, find_filter, get_filters

logger = logging.getLogger(__name__)


async def delete_message_after_delay(message, delay: int):
    """Helper function to auto-delete messages."""
    if not message:
        return
    await asyncio.sleep(delay)
    try:
        await message.delete()
    except Exception:
        pass


async def is_admin(client: Client, message: Message, grp_id: int = None) -> bool:
    """Helper to verify if a user is a chat admin or a bot admin."""
    if not message.from_user:
        return False

    # Check global bot admins
    if message.from_user.id in info.ADMINS or str(message.from_user.id) in info.ADMINS:
        return True

    target_chat_id = grp_id or message.chat.id

    try:
        member = await client.get_chat_member(target_chat_id, message.from_user.id)
        return member.status in [
            enums.ChatMemberStatus.OWNER,
            enums.ChatMemberStatus.ADMINISTRATOR,
        ]
    except Exception:
        return False


async def get_target_group(client: Client, message: Message):
    """Resolves target group ID and verifies admin permissions."""
    if message.chat.type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
        grp_id = message.chat.id
    else:
        grp_id = await active_connection(str(message.from_user.id))
        if not grp_id:
            await message.reply_text(
                "⚠️ **You are not connected to any active group!**\n\n"
                "Use `/connect <group_id>` to connect to a group first."
            )
            return None, False

    admin_status = await is_admin(client, message, grp_id=grp_id)
    if not admin_status:
        await message.reply_text(
            "⚠️ **You must be an admin of the connected group to use this command.**"
        )
        return None, False

    return grp_id, True


def build_keyboard(btn_str: str):
    """Safely converts stored string buttons back to InlineKeyboardButtons."""
    if not btn_str or btn_str == "[]":
        return None
    try:
        button_data = ast.literal_eval(btn_str)
        if button_data and isinstance(button_data[0][0], dict):
            return [[InlineKeyboardButton(**b) for b in row] for row in button_data]
        else:
            return button_data
    except (ValueError, SyntaxError):
        try:
            return eval(btn_str)
        except Exception:
            return None


def parse_markdown_buttons(text: str):
    """Extracts [Text](url) or [Text|url] formats from text to create buttons."""
    if not text:
        return "", "[]"
    buttons = []

    for match in re.finditer(r"\[(.+?)\]\((.+?)\)", text):
        btn_text, btn_url = match.group(1), match.group(2)
        buttons.append([{"text": btn_text, "url": btn_url}])

    for match in re.finditer(r"\[([^\[\]]+)\|([^()]+)\]", text):
        btn_text, btn_url = match.group(1).strip(), match.group(2).strip()
        buttons.append([{"text": btn_text, "url": btn_url}])

    clean_text = re.sub(r"\[(.+?)\]\((.+?)\)", "", text)
    clean_text = re.sub(r"\[([^\[\]]+)\|([^()]+)\]", "", clean_text).strip()

    btn_str = str(buttons) if buttons else "[]"
    return clean_text, btn_str


# ============================================================
# ⚙️ 1. ADD FILTER
# ============================================================
@Client.on_message(filters.command("filter") & (filters.group | filters.private))
async def add_filter_cmd(client: Client, message: Message):
    grp_id, ok = await get_target_group(client, message)
    if not ok:
        return

    if not message.reply_to_message:
        return await message.reply_text(
            "⚠️ **Reply to a message to set it as a filter.**"
        )
    if len(message.command) < 2:
        return await message.reply_text(
            "⚙️ **Usage:** `/filter <keyword>`\n\n*(You can format buttons in your text using `[Button Name](http://link.com)`)*"
        )

    keyword = message.text.split(None, 1)[1].lower()
    replied = message.reply_to_message

    raw_text = replied.text or replied.caption or ""
    text, btn = parse_markdown_buttons(raw_text)

    fileid = "None"
    if replied.media:
        for media_type in (
            replied.photo,
            replied.video,
            replied.animation,
            replied.sticker,
            replied.document,
            replied.audio,
        ):
            if media_type:
                fileid = media_type.file_id
                break

    await add_filter(grp_id, keyword, text, btn, "[]", fileid)
    await message.reply_text(
        f"✅ **Filter successfully added!**\n\n**Keyword:** `{keyword}`"
    )


# ============================================================
# ⚙️ 2. ADD PRE-MADE FILTER
# ============================================================
@Client.on_message(filters.command("addfilter") & (filters.group | filters.private))
async def add_premade_filter_cmd(client: Client, message: Message):
    grp_id, ok = await get_target_group(client, message)
    if not ok:
        return

    if not message.reply_to_message:
        return await message.reply_text(
            "⚠️ **Reply to a message containing inline buttons to set it as a filter.**"
        )
    if len(message.command) < 2:
        return await message.reply_text("⚙️ **Usage:** `/addfilter <keyword>`")

    keyword = message.text.split(None, 1)[1].lower()
    replied = message.reply_to_message
    text = replied.text or replied.caption or ""

    buttons = []
    if replied.reply_markup and replied.reply_markup.inline_keyboard:
        for row in replied.reply_markup.inline_keyboard:
            row_btns = []
            for btn in row:
                if btn.url:
                    row_btns.append({"text": btn.text, "url": btn.url})
                elif btn.callback_data:
                    row_btns.append(
                        {"text": btn.text, "callback_data": btn.callback_data}
                    )
            if row_btns:
                buttons.append(row_btns)

    btn_str = str(buttons) if buttons else "[]"

    fileid = "None"
    if replied.media:
        for media_type in (
            replied.photo,
            replied.video,
            replied.animation,
            replied.sticker,
            replied.document,
            replied.audio,
        ):
            if media_type:
                fileid = media_type.file_id
                break

    await add_filter(grp_id, keyword, text, btn_str, "[]", fileid)
    await message.reply_text(
        f"✅ **Filter with Pre-Made Buttons successfully added!**\n\n**Keyword:** `{keyword}`"
    )


# ============================================================
# 🎨 3. EDIT FILTER BUTTON COLOUR
# ============================================================
@Client.on_message(
    filters.command(["editfiltercolur", "editfiltercolour"])
    & (filters.group | filters.private)
)
async def edit_filter_colour_cmd(client: Client, message: Message):
    grp_id, ok = await get_target_group(client, message)
    if not ok:
        return

    if len(message.command) < 4:
        return await message.reply_text(
            "⚙️ **Usage:** `/editfiltercolur <keyword> <button_number> <colour>`\n\n"
            "**Example:** `/editfiltercolur Movie 1 green`\n"
            "**Colours:** `green`, `red`, `blue`"
        )

    keyword = message.command[1].lower()

    try:
        btn_num = int(message.command[2])
    except ValueError:
        return await message.reply_text(
            "❌ Button number must be an integer (e.g., 1, 2, 3)."
        )

    color_str = message.command[3].lower()

    # Safely map colours to Pyrogram's ButtonStyle Enum integer values
    color_map = {
        "green": getattr(ButtonStyle, "SUCCESS", 3),
        "red": getattr(ButtonStyle, "DANGER", 4),
        "blue": getattr(ButtonStyle, "PRIMARY", 1),
    }

    if color_str not in color_map:
        return await message.reply_text(
            "❌ Invalid colour. Choose from: `green`, `red`, `blue`."
        )

    reply_text, btn, alert, fileid = await find_filter(grp_id, keyword)

    if not reply_text:
        return await message.reply_text(
            f"❌ Filter `{keyword}` not found in this group's database."
        )

    if not btn or btn == "[]":
        return await message.reply_text(
            f"❌ Filter `{keyword}` does not have any buttons to colour."
        )

    try:
        button_data = ast.literal_eval(btn)
    except Exception:
        return await message.reply_text(
            "❌ Failed to parse filter buttons. Format corrupted."
        )

    count = 0
    found = False

    for r_idx, row in enumerate(button_data):
        for c_idx, b in enumerate(row):
            count += 1
            if count == btn_num:
                button_data[r_idx][c_idx]["style"] = int(color_map[color_str])
                found = True
                break
        if found:
            break

    if not found:
        return await message.reply_text(
            f"❌ Button number {btn_num} not found! The filter `{keyword}` only has {count} button(s)."
        )

    # Save back to database
    await add_filter(grp_id, keyword, reply_text, str(button_data), alert, fileid)

    await message.reply_text(
        f"✅ Filter `{keyword}` -> Button {btn_num} colour successfully changed to {color_str.title()}!"
    )


# ============================================================
# 🗑 4. DELETE FILTER
# ============================================================
@Client.on_message(filters.command("delfilter") & (filters.group | filters.private))
async def del_filter_cmd(client: Client, message: Message):
    grp_id, ok = await get_target_group(client, message)
    if not ok:
        return

    if len(message.command) < 2:
        return await message.reply_text("⚙️ **Usage:** `/delfilter <keyword>`")

    keyword = message.text.split(None, 1)[1].lower()

    await delete_filter(message, keyword, grp_id)
    await message.reply_text(
        f"🗑️ **Filter `{keyword}` has been deleted (if it existed).**"
    )


# ============================================================
# 📄 5. LIST FILTERS
# ============================================================
@Client.on_message(filters.command("listfilters") & (filters.group | filters.private))
async def list_filters_cmd(client: Client, message: Message):
    grp_id, ok = await get_target_group(client, message)
    if not ok:
        return

    keywords = await get_filters(grp_id)
    if not keywords:
        return await message.reply_text(
            "⚠️ **No active filters found for this group.**"
        )

    text = "📋 **Current Filters:**\n\n"
    for kw in keywords:
        text += f"• `{kw}`\n"

    await message.reply_text(text)


# ============================================================
# 🧠 6. TRIGGER MANUAL FILTERS
# ============================================================
async def manual_filters(client: Client, message: Message, text=False):
    if getattr(info, "REPAIR_MODE", False):
        if not message.from_user or (
            message.from_user.id not in info.ADMINS
            and str(message.from_user.id) not in info.ADMINS
        ):
            return False

    group_id = message.chat.id
    if message.chat.type == enums.ChatType.PRIVATE:
        active_grp = await active_connection(str(message.from_user.id))
        if active_grp:
            group_id = active_grp

    name = text or message.text
    reply_id = message.reply_to_message.id if message.reply_to_message else message.id
    keywords = await get_filters(group_id)

    if not keywords:
        return False

    for keyword in reversed(sorted(keywords, key=len)):
        pattern = r"( |^|[^\w])" + re.escape(keyword) + r"( |$|[^\w])"
        if re.search(pattern, name, flags=re.IGNORECASE):
            reply_text, btn, alert, fileid = await find_filter(group_id, keyword)

            if reply_text:
                reply_text = reply_text.replace("\\n", "\n").replace("\\t", "\t")

            button_layout = build_keyboard(btn)
            reply_markup = (
                InlineKeyboardMarkup(button_layout) if button_layout else None
            )

            try:
                sent_msg = None

                if fileid == "None":
                    sent_msg = await client.send_message(
                        message.chat.id,
                        reply_text,
                        disable_web_page_preview=True,
                        reply_markup=reply_markup,
                        reply_to_message_id=reply_id,
                    )
                else:
                    sent_msg = await client.send_cached_media(
                        message.chat.id,
                        fileid,
                        caption=reply_text or "",
                        reply_markup=reply_markup,
                        reply_to_message_id=reply_id,
                    )

                if sent_msg:
                    delete_timer = getattr(info, "BUTTON_AUTO_DELETE", 1800)
                    if delete_timer > 0:
                        asyncio.create_task(
                            delete_message_after_delay(sent_msg, delete_timer)
                        )

            except Forbidden as e:
                if "CHAT_SEND_PHOTOS_FORBIDDEN" in str(
                    e
                ) or "CHAT_SEND_MEDIA_FORBIDDEN" in str(e):
                    try:
                        fallback_text = (
                            f"{reply_text}\n\n*(Media blocked by chat permissions)*"
                            if reply_text
                            else "*(Media blocked by chat permissions)*"
                        )
                        sent_msg = await client.send_message(
                            message.chat.id,
                            text=fallback_text,
                            reply_to_message_id=reply_id,
                            reply_markup=reply_markup,
                        )
                        if sent_msg:
                            delete_timer = getattr(info, "BUTTON_AUTO_DELETE", 1800)
                            if delete_timer > 0:
                                asyncio.create_task(
                                    delete_message_after_delay(sent_msg, delete_timer)
                                )
                    except Exception:
                        pass
            except Exception as e:
                logger.exception(e)

            return True

    return False
