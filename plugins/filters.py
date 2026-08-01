import ast
import asyncio
import re
from pyrogram import Client, enums, filters
from pyrogram.errors import Forbidden
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

import info
from database.filters_mdb import add_filter, delete_filter, find_filter, get_filters

async def is_admin(message: Message) -> bool:
    if message.from_user and message.from_user.id in info.ADMINS: return True
    if message.chat.type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
        try:
            member = await message.chat.get_member(message.from_user.id)
            return member.status in [enums.ChatMemberStatus.OWNER, enums.ChatMemberStatus.ADMINISTRATOR]
        except Exception: return False
    return False

def parse_markdown_buttons(text: str):
    if not text: return "", "[]"
    buttons = []
    for match in re.finditer(r"\[(.+?)\]\((.+?)\)", text):
        buttons.append([{"text": match.group(1), "url": match.group(2)}])
    for match in re.finditer(r"\[([^\[\]]+)\|([^()]+)\]", text):
        buttons.append([{"text": match.group(1).strip(), "url": match.group(2).strip()}])
    clean_text = re.sub(r"\[(.+?)\]\((.+?)\)", "", text)
    clean_text = re.sub(r"\[([^\[\]]+)\|([^()]+)\]", "", clean_text).strip()
    return clean_text, str(buttons) if buttons else "[]"

@Client.on_message(filters.command("filter") & filters.group)
async def add_filter_cmd(client: Client, message: Message):
    if not await is_admin(message) or not message.reply_to_message: return
    if len(message.command) < 2: return await message.reply_text("⚙️ **Usage:** `/filter <keyword>`")
    
    keyword = message.text.split(None, 1)[1].lower()
    text, btn = parse_markdown_buttons(message.reply_to_message.text or message.reply_to_message.caption or "")
    
    fileid = "None"
    if message.reply_to_message.media:
        for m_type in (message.reply_to_message.photo, message.reply_to_message.video, message.reply_to_message.document):
            if m_type: fileid = m_type.file_id; break

    await add_filter(message.chat.id, keyword, text, btn, "[]", fileid)
    await message.reply_text(f"✅ **Filter added!**\n**Keyword:** `{keyword}`")

@Client.on_message(filters.command("delfilter") & filters.group)
async def del_filter_cmd(client: Client, message: Message):
    if not await is_admin(message): return
    if len(message.command) < 2: return await message.reply_text("⚙️ **Usage:** `/delfilter <keyword>`")
    await delete_filter(message, message.text.split(None, 1)[1].lower(), message.chat.id)

@Client.on_message(filters.command("listfilters") & filters.group)
async def list_filters_cmd(client: Client, message: Message):
    if not await is_admin(message): return
    keywords = await get_filters(message.chat.id)
    if not keywords: return await message.reply_text("⚠️ **No filters found.**")
    await message.reply_text(f"📋 **Filters:**\n" + "\n".join([f"• `{k}`" for k in keywords]))
