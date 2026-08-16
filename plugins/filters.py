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
    if not message:
        return
    await asyncio.sleep(delay)
    try:
        await message.delete()
    except Exception:
        pass


async def is_admin(client: Client, message: Message, grp_id: int = None) -> bool:
    if not message.from_user:
        return False
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
    if not btn_str or btn_str in ["[]", "None", "False", ""]:
        return None
    try:
        parsed_btn = ast.literal_eval(btn_str)
        button_layout = []
        for row in parsed_btn:
            btn_row = []
            for b in row:
                if isinstance(b, dict):
                    b_copy = b.copy()
                    style_val = b_copy.pop("style", None)
                    style_map = {
                        1: ButtonStyle.PRIMARY,
                        3: ButtonStyle.SUCCESS,
                        4: ButtonStyle.DANGER,
                    }
                    btn_obj = InlineKeyboardButton(**b_copy)
                    if style_val in style_map:
                        btn_obj.style = style_map[style_val]
                    elif isinstance(style_val, ButtonStyle):
                        btn_obj.style = style_val
                    btn_row.append(btn_obj)
                else:
                    btn_row.append(b)
            button_layout.append(btn_row)
        return button_layout
    except Exception as e:
        logger.error(f"Button parsing error: {e}")
        return None


def parse_markdown_buttons(text: str):
    if not text:
        return "", "[]"

    buttons = []
    clean_lines = []

    for line in text.split("\n"):
        row_btns = []
        matches = list(re.finditer(r"\[([^\[\]]+)\]\(([^()]+)\)", line))
        matches += list(re.finditer(r"\[([^\[\]]+)\|([^()]+)\]", line))
        matches.sort(key=lambda m: m.start())

        for match in matches:
            btn_text, btn_url = match.group(1).strip(), match.group(2).strip()
            row_btns.append({"text": btn_text, "url": btn_url})

        if row_btns:
            buttons.append(row_btns)

        clean_line = re.sub(r"\[([^\[\]]+)\]\(([^()]+)\)", "", line)
        clean_line = re.sub(r"\[([^\[\]]+)\|([^()]+)\]", "", clean_line).strip()

        if clean_line:
            clean_lines.append(clean_line)
        elif not matches:
            clean_lines.append("")

    clean_text = "\n".join(clean_lines).strip()
    btn_str = str(buttons) if buttons else "[]"
    return clean_text, btn_str


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
            "⚙️ **Usage:** `/filter <keyword>`\n\n*(You can format buttons in your text using `[Btn 1](http://link.com) [Btn 2](http://link.com)`)*"
        )

    keyword = message.text.split(None, 1)[1].lower()
    replied = message.reply_to_message
    raw_text = replied.text or replied.caption or ""
    text, btn = parse_markdown_buttons(raw_text)

    fileid = "None"
    if replied.photo:
        fileid = replied.photo.file_id
    elif replied.video:
        fileid = replied.video.file_id
    elif replied.document:
        fileid = replied.document.file_id
    elif replied.audio:
        fileid = replied.audio.file_id
    elif replied.animation:
        fileid = replied.animation.file_id
    elif replied.sticker:
        fileid = replied.sticker.file_id

    await add_filter(grp_id, keyword, text, btn, "[]", fileid)
    await message.reply_text(
        f"✅ **Filter successfully added!**\n\n**Keyword:** `{keyword}`"
    )


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
                btn_dict = {"text": btn.text}
                if btn.url:
                    btn_dict["url"] = btn.url
                elif btn.callback_data:
                    btn_dict["callback_data"] = btn.callback_data
                if hasattr(btn, "style") and btn.style:
                    btn_dict["style"] = int(btn.style)
                row_btns.append(btn_dict)
            if row_btns:
                buttons.append(row_btns)

    btn_str = str(buttons) if buttons else "[]"

    fileid = "None"
    if replied.photo:
        fileid = replied.photo.file_id
    elif replied.video:
        fileid = replied.video.file_id
    elif replied.document:
        fileid = replied.document.file_id
    elif replied.audio:
        fileid = replied.audio.file_id
    elif replied.animation:
        fileid = replied.animation.file_id
    elif replied.sticker:
        fileid = replied.sticker.file_id

    await add_filter(grp_id, keyword, text, btn_str, "[]", fileid)
    await message.reply_text(
        f"✅ **Filter with Pre-Made Buttons successfully added!**\n\n**Keyword:** `{keyword}`"
    )


@Client.on_message(
    filters.command(["editfiltercolur", "editfiltercolour"])
    & (filters.group | filters.private)
)
async def edit_filter_colour_cmd(client: Client, message: Message):
    grp_id, ok = await get_target_group(client, message)
    if not ok:
        return

    args = message.command
    if len(args) < 4:
        return await message.reply_text(
            "❌ **Usage:** `/editfiltercolur <keyword> <button_number> <colour>`\n\n"
            "**Example:** `/editfiltercolur Kantara 1 green`\n"
            "**Colours:** `green`, `red`, `blue`"
        )

    try:
        btn_num = int(args[-2])
        color_str = args[-1].lower()
        keyword = " ".join(args[1:-2]).lower()
    except ValueError:
        return await message.reply_text(
            "❌ Button number must be an integer. Example: `/editfiltercolur Kantara 1 green`"
        )

    color_map = {
        "green": 3,
        "red": 4,
        "blue": 1,
    }

    if color_str not in color_map:
        return await message.reply_text(
            "❌ Invalid colour. Choose from: `green`, `red`, `blue`."
        )

    reply_text, btn, alert, fileid = await find_filter(grp_id, keyword)

    if not reply_text and (not fileid or fileid == "None"):
        return await message.reply_text(
            f"❌ Filter `{keyword}` not found in this group's database."
        )
    if not btn or btn in ["[]", "None", "False", ""]:
        return await message.reply_text(
            f"❌ Filter `{keyword}` does not have any buttons to colour."
        )

    try:
        button_data = ast.literal_eval(btn)
    except Exception:
        return await message.reply_text(
            "❌ Failed to parse filter buttons. Format corrupted."
        )

    count, found = 0, False

    for r_idx, row in enumerate(button_data):
        for c_idx, b in enumerate(row):
            count += 1
            if count == btn_num:
                button_data[r_idx][c_idx]["style"] = color_map[color_str]
                found = True
                break
        if found:
            break

    if not found:
        return await message.reply_text(
            f"❌ Button number {btn_num} not found! The filter `{keyword}` only has {count} button(s)."
        )

    await add_filter(grp_id, keyword, reply_text, str(button_data), alert, fileid)
    await message.reply_text(
        f"✅ Filter `{keyword}` -> Button {btn_num} colour successfully changed to {color_str.title()}!"
    )


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

    name = text or message.text or message.caption or ""
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

            sent_msg = None
            fileid_str = str(fileid).strip()

            if not fileid or fileid_str in ["None", "[]", "", "False"]:
                try:
                    sent_msg = await client.send_message(
                        message.chat.id,
                        reply_text or "",
                        disable_web_page_preview=True,
                        reply_markup=reply_markup,
                        reply_to_message_id=reply_id,
                    )
                except Exception:
                    try:
                        sent_msg = await client.send_message(
                            message.chat.id,
                            reply_text or "",
                            disable_web_page_preview=True,
                            reply_markup=reply_markup,
                        )
                    except Exception as e:
                        logger.error(f"Error sending text filter: {e}")
            else:
                try:
                    sent_msg = await client.send_cached_media(
                        message.chat.id,
                        fileid,
                        caption=reply_text or "",
                        reply_markup=reply_markup,
                        reply_to_message_id=reply_id,
                    )
                except Exception:
                    try:
                        sent_msg = await client.send_cached_media(
                            message.chat.id,
                            fileid,
                            caption=reply_text or "",
                            reply_markup=reply_markup,
                        )
                    except Exception:
                        try:
                            sent_msg = await client.send_photo(
                                message.chat.id,
                                photo=fileid,
                                caption=reply_text or "",
                                reply_markup=reply_markup,
                            )
                        except Exception:
                            try:
                                sent_msg = await client.send_document(
                                    message.chat.id,
                                    document=fileid,
                                    caption=reply_text or "",
                                    reply_markup=reply_markup,
                                )
                            except Exception as e:
                                logger.error(f"Media filter failed entirely: {e}")

            if sent_msg:
                delete_timer = getattr(info, "BUTTON_AUTO_DELETE", 1800)
                if delete_timer > 0:
                    asyncio.create_task(
                        delete_message_after_delay(sent_msg, delete_timer)
                    )
            return True
    return False
