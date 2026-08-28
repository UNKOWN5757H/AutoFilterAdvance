import re
from logging import getLogger, ERROR

from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardButton, Message

import info
from database.plugin_dbs import plugin_db as _plugin_db

logger = getLogger(__name__)
logger.setLevel(ERROR)

async def admin_check(_, __, message: Message):
    if not message.from_user: return False
    return (message.from_user.id in info.ADMINS or str(message.from_user.id) in info.ADMINS)

admin_filter = filters.create(admin_check)

@Client.on_message(filters.command("addpromo") & admin_filter & (filters.private | filters.group))
async def add_promo_handler(bot: Client, message: Message):
    text = message.text.split(None, 1)[1] if len(message.command) > 1 else ""
    match = re.search(r'"([^"]+)"\s+(https?://\S+)', text)
    if not match:
        return await message.reply_text('⚙️ **Usage:**\n`/addpromo "Button Text" https://example.com`\n\n⚠️ **Note:** Ensure the button text is inside double quotes `" "` followed by a valid HTTP/HTTPS URL.')

    btn_text, btn_url = match.group(1), match.group(2)
    await _plugin_db.add_promo(btn_text, btn_url)
    await message.reply_text(f"✅ **Promo Added Successfully!**\n\n**Text:** `{btn_text}`\n**URL:** {btn_url}", disable_web_page_preview=True)

@Client.on_message(filters.command("delpromo") & admin_filter & (filters.private | filters.group))
async def del_promo_handler(bot: Client, message: Message):
    if len(message.command) < 2: return await message.reply_text("⚙️ **Usage:**\n`/delpromo https://example.com`\n\nProvide the exact URL of the promotion you want to delete.")
    btn_url = message.command[1]
    deleted = await _plugin_db.del_promo(btn_url)

    if deleted: await message.reply_text(f"🗑️ **Promo deleted successfully!**\n\n**URL:** {btn_url}", disable_web_page_preview=True)
    else: await message.reply_text(f"❌ **Promo not found!**\n\nCould not find any promo matching URL: {btn_url}", disable_web_page_preview=True)

@Client.on_message(filters.command("listpromos") & admin_filter & (filters.private | filters.group))
async def list_promo_handler(bot: Client, message: Message):
    promos = await _plugin_db.get_all_promos()
    if not promos: return await message.reply_text("⚠️ **No active promotional links found in the database.**")

    text = "📢 **Current Promotional Links:**\n\n"
    for i, p in enumerate(promos, 1): text += f"**{i}. Text:** `{p['text']}`\n**🔗 URL:** {p['url']}\n\n"
    await message.reply_text(text, disable_web_page_preview=True)

async def get_promo_buttons() -> list:
    promos = await _plugin_db.get_all_promos()
    buttons = []
    for p in promos: buttons.append(InlineKeyboardButton(p["text"], url=p["url"]))
    return buttons
