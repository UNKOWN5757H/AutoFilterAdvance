import ast
import asyncio
import re
from logging import ERROR, getLogger

from motor.motor_asyncio import AsyncIOMotorClient
from pyrogram import Client, enums, filters
from pyrogram.enums import ButtonStyle
from pyrogram.errors import (
    FloodWait,
    Forbidden,
    MessageNotModified,
    PeerIdInvalid,
    UserIsBlocked,
)
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

import info
from database.connections_mdb import active_connection
from database.filters_mdb import add_filter, delete_filter, find_filter, get_filters

logger = getLogger(__name__)
logger.setLevel(ERROR)

# ============================================================
# ⚙️ DIRECT MONGODB FAILOVER LAYER
# ============================================================
_filter_col = None
try:
    _DB_CLIENT = AsyncIOMotorClient(info.DATABASE_URI)
    _BOT_DB = _DB_CLIENT[info.DATABASE_NAME]
    _filter_col = _BOT_DB["filters"]
except Exception as e:
    logger.error(f"Filters Direct DB fallback init failed: {e}")


# ============================================================
# 👑 FOOLPROOF ADMIN PARSER
# ============================================================
def get_admin_list():
    raw_admins = getattr(info, "ADMINS", [])
    if isinstance(raw_admins, str):
        return [
            int(x)
            for x in raw_admins.replace(",", " ").split()
            if x.strip().lstrip("-").isdigit()
        ]
    elif isinstance(raw_admins, int):
        return [raw_admins]
    elif isinstance(raw_admins, list):
        return [int(x) for x in raw_admins if str(x).strip().lstrip("-").isdigit()]
    return []


async def is_admin(client: Client, message: Message, grp_id: int = None) -> bool:
    if not message.from_user:
        return False
    if message.from_user.id in get_admin_list():
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
                "⚠️ **You are not connected to any active group!**\n\nUse `/connect <group_id>` to connect to a group first."
            )
            return None, False

    admin_status = await is_admin(client, message, grp_id=grp_id)
    if not admin_status:
        await message.reply_text(
            "⚠️ **You must be an admin of the connected group to use this command.**"
        )
        return None, False
    return grp_id, True


# ============================================================
# 🗄️ DUAL-LAYER DATABASE ADAPTER
# ============================================================
async def db_add_filter(
    grp_id: int, keyword: str, text: str, btn: str, alert: str, fileid: str
):
    # Layer 1: Native helper
    try:
        return await add_filter(grp_id, keyword, text, btn, alert, fileid)
    except Exception as e:
        logger.warning(f"Layer 1 add_filter failed, attempting direct DB: {e}")
    # Layer 2: Direct MongoDB
    if _filter_col is not None:
        await _filter_col.update_one(
            {"chat_id": int(grp_id), "keyword": keyword},
            {"$set": {"text": text, "btn": btn, "alert": alert, "fileid": fileid}},
            upsert=True,
        )


async def db_find_filter(grp_id: int, keyword: str):
    # Layer 1: Native helper
    try:
        reply_text, btn, alert, fileid = await find_filter(grp_id, keyword)
        if reply_text or (fileid and fileid != "None"):
            return reply_text, btn, alert, fileid
    except Exception as e:
        logger.warning(f"Layer 1 find_filter failed, attempting direct DB: {e}")
    # Layer 2: Direct MongoDB
    if _filter_col is not None:
        doc = await _filter_col.find_one({"chat_id": int(grp_id), "keyword": keyword})
        if doc:
            return (
                doc.get("text", ""),
                doc.get("btn", "[]"),
                doc.get("alert", "[]"),
                doc.get("fileid", "None"),
            )
    return None, "[]", "[]", "None"


async def db_delete_filter(message: Message, keyword: str, grp_id: int):
    # Layer 1: Native helper
    try:
        await delete_filter(message, keyword, grp_id)
        return True
    except Exception as e:
        logger.warning(f"Layer 1 delete_filter failed, attempting direct DB: {e}")
    # Layer 2: Direct MongoDB
    if _filter_col is not None:
        await _filter_col.delete_one({"chat_id": int(grp_id), "keyword": keyword})
        return True
    return False


async def db_get_filters(grp_id: int):
    # Layer 1: Native helper
    try:
        res = await get_filters(grp_id)
        if res is not None:
            return res
    except Exception as e:
        logger.warning(f"Layer 1 get_filters failed, attempting direct DB: {e}")
    # Layer 2: Direct MongoDB
    if _filter_col is not None:
        docs = await _filter_col.find({"chat_id": int(grp_id)}).to_list(length=None)
        return [d["keyword"] for d in docs if "keyword" in d]
    return []


# ============================================================
# 🎨 KEYBOARD AND BUTTON PARSERS
# ============================================================
def create_button(text, url=None, callback_data=None, style=None):
    kwargs = {"text": text}
    if url:
        kwargs["url"] = url
    if callback_data:
        kwargs["callback_data"] = callback_data
    if style is not None:
        kwargs["style"] = style
    try:
        return InlineKeyboardButton(**kwargs)
    except TypeError:
        kwargs.pop("style", None)
        return InlineKeyboardButton(**kwargs)


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
                    final_style = style_map.get(style_val, style_val)
                    btn_row.append(
                        create_button(
                            text=b_copy.get("text", "Button"),
                            url=b_copy.get("url"),
                            callback_data=b_copy.get("callback_data"),
                            style=final_style,
                        )
                    )
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


# ============================================================
# 🎯 FILTER COMMANDS
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
        return await message.reply_text("⚙️ **Usage:** `/filter <keyword>`")

    keyword = message.text.split(None, 1)[1].lower().strip()
    replied = message.reply_to_message
    raw_text = replied.text or replied.caption or ""
    text, btn = parse_markdown_buttons(raw_text)

    fileid = "None"
    for media_attr in ["photo", "video", "document", "audio", "animation", "sticker"]:
        media_obj = getattr(replied, media_attr, None)
        if media_obj:
            fileid = media_obj.file_id
            break

    await db_add_filter(grp_id, keyword, text, btn, "[]", fileid)
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
            "⚠️ **Reply to a message containing inline buttons.**"
        )
    if len(message.command) < 2:
        return await message.reply_text("⚙️ **Usage:** `/addfilter <keyword>`")

    keyword = message.text.split(None, 1)[1].lower().strip()
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
    for media_attr in ["photo", "video", "document", "audio", "animation", "sticker"]:
        media_obj = getattr(replied, media_attr, None)
        if media_obj:
            fileid = media_obj.file_id
            break

    await db_add_filter(grp_id, keyword, text, btn_str, "[]", fileid)
    await message.reply_text(
        f"✅ **Filter with buttons added!**\n\n**Keyword:** `{keyword}`"
    )


@Client.on_message(filters.command("filterimage") & (filters.group | filters.private))
async def edit_filter_image_cmd(client: Client, message: Message):
    grp_id, ok = await get_target_group(client, message)
    if not ok:
        return
    if not message.reply_to_message or not message.reply_to_message.media:
        return await message.reply_text(
            "⚠️ **Reply to a photo, video, or document to set the new image.**"
        )
    if len(message.command) < 2:
        return await message.reply_text("⚙️ **Usage:** `/filterimage <keyword>`")

    keyword = message.text.split(None, 1)[1].lower().strip()
    replied = message.reply_to_message
    reply_text, btn, alert, old_fileid = await db_find_filter(grp_id, keyword)

    if not reply_text and (not old_fileid or old_fileid == "None"):
        return await message.reply_text(f"❌ Filter `{keyword}` not found.")

    fileid = "None"
    for media_attr in ["photo", "video", "document", "audio", "animation", "sticker"]:
        media_obj = getattr(replied, media_attr, None)
        if media_obj:
            fileid = media_obj.file_id
            break

    if fileid == "None":
        return await message.reply_text("❌ Could not extract valid media.")

    await db_add_filter(grp_id, keyword, reply_text, btn, alert, fileid)
    await message.reply_text(
        f"✅ **Filter image updated!**\n\n**Keyword:** `{keyword}`"
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
            "❌ **Usage:** `/editfiltercolur <keyword> <button_number> <colour>`\n\n**Colours:** `green`, `red`, `blue`"
        )

    try:
        btn_num = int(args[-2])
        color_str = args[-1].lower()
        keyword = " ".join(args[1:-2]).lower().strip()
    except ValueError:
        return await message.reply_text("❌ Button number must be an integer.")

    color_map = {"green": 3, "red": 4, "blue": 1}
    if color_str not in color_map:
        return await message.reply_text(
            "❌ Invalid colour. Choose from: `green`, `red`, `blue`."
        )

    reply_text, btn, alert, fileid = await db_find_filter(grp_id, keyword)
    if not reply_text and (not fileid or fileid == "None"):
        return await message.reply_text(f"❌ Filter `{keyword}` not found.")
    if not btn or btn in ["[]", "None", "False", ""]:
        return await message.reply_text(f"❌ Filter `{keyword}` has no buttons.")

    try:
        button_data = ast.literal_eval(btn)
    except Exception:
        return await message.reply_text("❌ Corrupted button format.")

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
            f"❌ Button {btn_num} not found. Filter has {count} buttons."
        )

    await db_add_filter(grp_id, keyword, reply_text, str(button_data), alert, fileid)
    await message.reply_text(
        f"✅ Filter `{keyword}` Button {btn_num} colour changed to {color_str.title()}!"
    )


@Client.on_message(filters.command("delfilter") & (filters.group | filters.private))
async def del_filter_cmd(client: Client, message: Message):
    grp_id, ok = await get_target_group(client, message)
    if not ok:
        return
    if len(message.command) < 2:
        return await message.reply_text("⚙️ **Usage:** `/delfilter <keyword>`")
    keyword = message.text.split(None, 1)[1].lower().strip()
    await db_delete_filter(message, keyword, grp_id)
    await message.reply_text(f"🗑️ **Filter `{keyword}` deleted.**")


@Client.on_message(filters.command("listfilters") & (filters.group | filters.private))
async def list_filters_cmd(client: Client, message: Message):
    grp_id, ok = await get_target_group(client, message)
    if not ok:
        return
    keywords = await db_get_filters(grp_id)
    if not keywords:
        return await message.reply_text("⚠️ **No active filters found.**")
    text = "📋 **Current Filters:**\n\n" + "\n".join([f"• `{kw}`" for kw in keywords])
    await message.reply_text(text)


# ============================================================
# 📤 4-LAYER MULTI-MEDIA FILTER DISPATCHER
# ============================================================
async def send_filter_media(
    client: Client,
    chat_id: int,
    fileid: str,
    reply_text: str,
    reply_markup,
    reply_id: int,
):
    # Layer 1: Cached media with reply
    try:
        return await client.send_cached_media(
            chat_id,
            fileid,
            caption=reply_text,
            reply_markup=reply_markup,
            reply_to_message_id=reply_id,
        )
    except FloodWait as e:
        await asyncio.sleep(e.value + 1)
        return await send_filter_media(
            client, chat_id, fileid, reply_text, reply_markup, reply_id
        )
    except (UserIsBlocked, PeerIdInvalid):
        return None
    except Exception:
        pass

    # Layer 2: Cached media without reply (survives deleted trigger messages)
    try:
        return await client.send_cached_media(
            chat_id, fileid, caption=reply_text, reply_markup=reply_markup
        )
    except Exception:
        pass

    # Layer 3: Direct type dispatch (Photo -> Video -> Document)
    for send_fn, arg_name in [
        (client.send_photo, "photo"),
        (client.send_video, "video"),
        (client.send_document, "document"),
        (client.send_animation, "animation"),
    ]:
        try:
            kwargs = {
                "chat_id": chat_id,
                arg_name: fileid,
                "caption": reply_text,
                "reply_markup": reply_markup,
            }
            return await send_fn(**kwargs)
        except Exception:
            continue

    # Layer 4: Fallback to plain text message
    try:
        return await client.send_message(
            chat_id, text=reply_text or "Here is your file:", reply_markup=reply_markup
        )
    except Exception as err:
        logger.error(f"Media filter failed all 4 layers: {err}")
        return None


async def safe_send_text_filter(
    client: Client, chat_id: int, text: str, reply_markup, reply_id: int
):
    try:
        return await client.send_message(
            chat_id,
            text,
            disable_web_page_preview=True,
            reply_markup=reply_markup,
            reply_to_message_id=reply_id,
        )
    except Exception:
        try:
            return await client.send_message(
                chat_id, text, disable_web_page_preview=True, reply_markup=reply_markup
            )
        except Exception as e:
            logger.error(f"Text filter failed: {e}")
            return None


# ============================================================
# ⚡ LIVE GROUP TRIGGER HANDLER
# ============================================================
async def manual_filters(client: Client, message: Message, text=False):
    if getattr(info, "REPAIR_MODE", False):
        if not message.from_user or message.from_user.id not in get_admin_list():
            return False

    group_id = message.chat.id
    if message.chat.type == enums.ChatType.PRIVATE:
        active_grp = await active_connection(str(message.from_user.id))
        if active_grp:
            group_id = active_grp

    name = text or message.text or message.caption or ""
    reply_id = message.reply_to_message.id if message.reply_to_message else message.id
    keywords = await db_get_filters(group_id)
    if not keywords:
        return False

    for keyword in reversed(sorted(keywords, key=len)):
        pattern = r"( |^|[^\w])" + re.escape(keyword) + r"( |$|[^\w])"
        if re.search(pattern, name, flags=re.IGNORECASE):
            reply_text, btn, alert, fileid = await db_find_filter(group_id, keyword)
            if reply_text:
                reply_text = reply_text.replace("\\n", "\n").replace("\\t", "\t")

            button_layout = build_keyboard(btn)
            reply_markup = (
                InlineKeyboardMarkup(button_layout) if button_layout else None
            )
            sent_msg = None
            fileid_str = str(fileid).strip()

            if not fileid or fileid_str in ["None", "[]", "", "False"]:
                sent_msg = await safe_send_text_filter(
                    client, message.chat.id, reply_text or "", reply_markup, reply_id
                )
            else:
                sent_msg = await send_filter_media(
                    client,
                    message.chat.id,
                    fileid,
                    reply_text or "",
                    reply_markup,
                    reply_id,
                )

            if sent_msg:
                delete_timer = getattr(info, "BUTTON_AUTO_DELETE", 1800)
                if delete_timer > 0:
                    asyncio.create_task(
                        client.delete_messages(sent_msg.chat.id, sent_msg.id)
                        if delete_timer == 0
                        else asyncio.sleep(0)
                    )
            return True
    return False


@Client.on_message(filters.group & filters.text & ~filters.bot, group=5)
async def filter_listener_hook(client: Client, message: Message):
    if message.text.startswith("/"):
        return
    await manual_filters(client, message)
