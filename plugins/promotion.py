import logging
import re
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardButton
import info
from database.plugin_dbs import plugin_db

logger = logging.getLogger(__name__)

@Client.on_message(filters.command("addpromo") & filters.user(info.ADMINS))
async def add_promo_handler(bot: Client, message: Message):
    text = message.text.split(None, 1)[1] if len(message.command) > 1 else ""
    match = re.search(r'"([^"]+)"\s+(https?://\S+)', text)

    if not match:
        return await message.reply_text('⚙️ **Usage:**\n`/addpromo "Button Text" https://example.com`\n\n⚠️ Ensure text is in quotes `" "` followed by a URL.')

    btn_text, btn_url = match.group(1), match.group(2)
    await plugin_db.add_promo(btn_text, btn_url)
    await message.reply_text(f"✅ **Promo Added!**\n\n**Text:** `{btn_text}`\n**URL:** {btn_url}", disable_web_page_preview=True)

@Client.on_message(filters.command("delpromo") & filters.user(info.ADMINS))
async def del_promo_handler(bot: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text("⚙️ **Usage:**\n`/delpromo https://example.com`")

    btn_url = message.command[1]
    if await plugin_db.del_promo(btn_url):
        await message.reply_text(f"🗑️ **Promo deleted successfully!**\n\n**URL:** {btn_url}", disable_web_page_preview=True)
    else:
        await message.reply_text(f"❌ **Promo not found!**", disable_web_page_preview=True)

@Client.on_message(filters.command("listpromos") & filters.user(info.ADMINS))
async def list_promo_handler(bot: Client, message: Message):
    promos = await plugin_db.get_all_promos()
    if not promos:
        return await message.reply_text("⚠️ **No active promotional links found.**")

    text = "📢 **Current Promotional Links:**\n\n"
    for i, p in enumerate(promos, 1):
        text += f"**{i}. Text:** `{p['text']}`\n**🔗 URL:** {p['url']}\n\n"
    await message.reply_text(text, disable_web_page_preview=True)

async def get_promo_buttons() -> list:
    promos = await plugin_db.get_all_promos()
    return [InlineKeyboardButton(p["text"], url=p["url"]) for p in promos]
