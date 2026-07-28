import re
import ast
import asyncio
import logging
from pyrogram import Client, filters, enums
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import Forbidden

import info
from database.filters_mdb import add_filter, get_filters, find_filter, delete_filter

logger = logging.getLogger(__name__)

DELETE_TIME = 1800  # 30 Minutes

async def delete_message_after_delay(message, delay: int):
    """Helper function to auto-delete messages."""
    if not message: return
    await asyncio.sleep(delay)
    try: await message.delete()
    except Exception: pass

async def is_admin(message: Message) -> bool:
    """Helper to verify if a user is a chat admin or a bot admin."""
    if message.from_user and message.from_user.id in info.ADMINS:
        return True
    if message.chat.type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
        try:
            member = await message.chat.get_member(message.from_user.id)
            return member.status in [enums.ChatMemberStatus.OWNER, enums.ChatMemberStatus.ADMINISTRATOR]
        except Exception:
            return False
    return False

def build_keyboard(btn_str: str):
    """Safely converts stored string buttons back to InlineKeyboardButtons."""
    if not btn_str or btn_str == "[]":
        return None
    try:
        button_data = ast.literal_eval(btn_str)
        if button_data and isinstance(button_data[0][0], dict):
            # Parse new dictionary format
            return [[InlineKeyboardButton(**b) for b in row] for row in button_data]
        else:
            return button_data
    except (ValueError, SyntaxError):
        # Fallback for old eval-based strings if your database has legacy filters
        try:
            return eval(btn_str)
        except Exception:
            return None

def parse_markdown_buttons(text: str):
    """Extracts [Text](url) or [Text|url] formats from text to create buttons."""
    if not text: return "", "[]"
    buttons = []
    
    # Finds markdown links and extracts them
    for match in re.finditer(r"\[(.+?)\]\((.+?)\)", text):
        btn_text, btn_url = match.group(1), match.group(2)
        buttons.append([{"text": btn_text, "url": btn_url}])
    
    # Find alternative [Text | URL] syntax
    for match in re.finditer(r"\[([^\[\]]+)\|([^()]+)\]", text):
        btn_text, btn_url = match.group(1).strip(), match.group(2).strip()
        buttons.append([{"text": btn_text, "url": btn_url}])

    # Clean the text of the button strings
    clean_text = re.sub(r"\[(.+?)\]\((.+?)\)", "", text)
    clean_text = re.sub(r"\[([^\[\]]+)\|([^()]+)\]", "", clean_text).strip()
    
    btn_str = str(buttons) if buttons else "[]"
    return clean_text, btn_str


# ============================================================
# ⚙️ 1. ADD FILTER (Text formatting with custom buttons)
# ============================================================
@Client.on_message(filters.command("filter") & filters.group)
async def add_filter_cmd(client: Client, message: Message):
    if not await is_admin(message): return
    if not message.reply_to_message:
        return await message.reply_text("⚠️ **Reply to a message to set it as a filter.**")
    if len(message.command) < 2:
        return await message.reply_text("⚙️ **Usage:** `/filter <keyword>`\n\n*(You can format buttons in your text using `[Button Name](http://link.com)`)*")
    
    keyword = message.text.split(None, 1)[1].lower()
    replied = message.reply_to_message
    
    # Extract text and parse any markdown buttons
    raw_text = replied.text or replied.caption or ""
    text, btn = parse_markdown_buttons(raw_text)
    
    # Extract Media
    fileid = "None"
    if replied.media:
        for media_type in (replied.photo, replied.video, replied.animation, replied.sticker, replied.document, replied.audio):
            if media_type:
                fileid = media_type.file_id
                break
                
    await add_filter(message.chat.id, keyword, text, btn, "[]", fileid)
    await message.reply_text(f"✅ **Filter successfully added!**\n\n**Keyword:** `{keyword}`")


# ============================================================
# ⚙️ 2. ADD PRE-MADE FILTER (Copies existing inline buttons)
# ============================================================
@Client.on_message(filters.command("addfilter") & filters.group)
async def add_premade_filter_cmd(client: Client, message: Message):
    if not await is_admin(message): return
    if not message.reply_to_message:
        return await message.reply_text("⚠️ **Reply to a message containing inline buttons to set it as a filter.**")
    if len(message.command) < 2:
        return await message.reply_text("⚙️ **Usage:** `/addfilter <keyword>`")
    
    keyword = message.text.split(None, 1)[1].lower()
    replied = message.reply_to_message
    text = replied.text or replied.caption or ""
    
    # Extract existing InlineKeyboardMarkup layout from the replied message
    buttons = []
    if replied.reply_markup and replied.reply_markup.inline_keyboard:
        for row in replied.reply_markup.inline_keyboard:
            row_btns = []
            for btn in row:
                if btn.url:
                    row_btns.append({"text": btn.text, "url": btn.url})
                elif btn.callback_data:
                    row_btns.append({"text": btn.text, "callback_data": btn.callback_data})
            if row_btns:
                buttons.append(row_btns)
                
    btn_str = str(buttons) if buttons else "[]"
    
    # Extract Media
    fileid = "None"
    if replied.media:
        for media_type in (replied.photo, replied.video, replied.animation, replied.sticker, replied.document, replied.audio):
            if media_type:
                fileid = media_type.file_id
                break
                
    await add_filter(message.chat.id, keyword, text, btn_str, "[]", fileid)
    await message.reply_text(f"✅ **Filter with Pre-Made Buttons successfully added!**\n\n**Keyword:** `{keyword}`")


# ============================================================
# 🗑 3. DELETE FILTER
# ============================================================
@Client.on_message(filters.command("delfilter") & filters.group)
async def del_filter_cmd(client: Client, message: Message):
    if not await is_admin(message): return
    if len(message.command) < 2:
        return await message.reply_text("⚙️ **Usage:** `/delfilter <keyword>`")
        
    keyword = message.text.split(None, 1)[1].lower()
    
    # Typically, standard DBs return False if not found, True if deleted.
    # Adjust logic below if your delete_filter handles messages automatically.
    await delete_filter(message, keyword, message.chat.id)
    await message.reply_text(f"🗑️ **Filter `{keyword}` has been deleted (if it existed).**")


# ============================================================
# 📄 4. LIST FILTERS
# ============================================================
@Client.on_message(filters.command("listfilters") & filters.group)
async def list_filters_cmd(client: Client, message: Message):
    if not await is_admin(message): return
    
    keywords = await get_filters(message.chat.id)
    if not keywords:
        return await message.reply_text("⚠️ **No active filters found in this chat.**")
    
    text = f"📋 **Current Filters for {message.chat.title}:**\n\n"
    for kw in keywords:
        text += f"• `{kw}`\n"
        
    await message.reply_text(text)


# ============================================================
# 🧠 5. TRIGGER MANUAL FILTERS (Re-written for cleanliness)
# ============================================================
async def manual_filters(client: Client, message: Message, text=False):
    # Optional Repair Mode integration
    if getattr(info, "REPAIR_MODE", False):
        if not message.from_user or message.from_user.id not in info.ADMINS:
            return False

    group_id = message.chat.id
    name = text or message.text
    reply_id = message.reply_to_message.id if message.reply_to_message else message.id
    keywords = await get_filters(group_id)

    for keyword in reversed(sorted(keywords, key=len)):
        pattern = r"( |^|[^\w])" + re.escape(keyword) + r"( |$|[^\w])"
        if re.search(pattern, name, flags=re.IGNORECASE):
            reply_text, btn, alert, fileid = await find_filter(group_id, keyword)

            if reply_text:
                reply_text = reply_text.replace("\\n", "\n").replace("\\t", "\t")

            # Parse Button layout securely using the helper function
            button_layout = build_keyboard(btn)
            reply_markup = InlineKeyboardMarkup(button_layout) if button_layout else None

            try:
                sent_msg = None
                
                # Check if it's text-only or includes media
                if fileid == "None":
                    if not reply_markup:
                        sent_msg = await client.send_message(group_id, reply_text, disable_web_page_preview=True, reply_to_message_id=reply_id)
                    else:
                        sent_msg = await client.send_message(group_id, reply_text, disable_web_page_preview=True, reply_markup=reply_markup, reply_to_message_id=reply_id)
                else:
                    if not reply_markup:
                        sent_msg = await client.send_cached_media(group_id, fileid, caption=reply_text or "", reply_to_message_id=reply_id)
                    else:
                        sent_msg = await message.reply_cached_media(fileid, caption=reply_text or "", reply_markup=reply_markup, reply_to_message_id=reply_id)

                if sent_msg:
                    asyncio.create_task(delete_message_after_delay(sent_msg, DELETE_TIME))

            except Forbidden as e:
                # Chat Permission Fallback (Sends as text if sending media is blocked)
                if "CHAT_SEND_PHOTOS_FORBIDDEN" in str(e) or "CHAT_SEND_MEDIA_FORBIDDEN" in str(e):
                    try:
                        fallback_text = f"{reply_text}\n\n*(Media blocked by chat permissions)*" if reply_text else "*(Media blocked by chat permissions)*"
                        sent_msg = await client.send_message(group_id, text=fallback_text, reply_to_message_id=reply_id, reply_markup=reply_markup)
                        if sent_msg:
                            asyncio.create_task(delete_message_after_delay(sent_msg, DELETE_TIME))
                    except Exception:
                        pass
            except Exception as e:
                logger.exception(e)
                
            return True
            
    return False
    
