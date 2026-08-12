import logging
import re

from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardButton, Message

import info
from database.plugin_dbs import plugin_db

logger = logging.getLogger(__name__)


# ============================================================
# 🛡️ CUSTOM ADMIN FILTER (Fixes silent command failures)
# ============================================================
async def admin_check(_, __, message: Message):
    if not message.from_user:
        return False
    return (
        message.from_user.id in info.ADMINS or str(message.from_user.id) in info.ADMINS
    )


admin_filter = filters.create(admin_check)


# ============================================================
# ➕ Add Promotional Link
# ============================================================
@Client.on_message(
    filters.command("addpromo") & admin_filter & (filters.private | filters.group)
)
async def add_promo_handler(bot: Client, message: Message):
    # Extract text after the command
    text = message.text.split(None, 1)[1] if len(message.command) > 1 else ""

    # Regex to capture "Button Text" and URL
    match = re.search(r'"([^"]+)"\s+(https?://\S+)', text)

    if not match:
        return await message.reply_text(
            '⚙️ **Usage:**\n`/addpromo "Button Text" https://example.com`\n\n'
            '⚠️ **Note:** Ensure the button text is inside double quotes `" "` followed by a valid HTTP/HTTPS URL.'
        )

    btn_text = match.group(1)
    btn_url = match.group(2)

    await plugin_db.add_promo(btn_text, btn_url)

    await message.reply_text(
        f"✅ **Promo Added Successfully!**\n\n"
        f"**Text:** `{btn_text}`\n"
        f"**URL:** {btn_url}",
        disable_web_page_preview=True,
    )


# ============================================================
# ➖ Delete Promotional Link
# ============================================================
@Client.on_message(
    filters.command("delpromo") & admin_filter & (filters.private | filters.group)
)
async def del_promo_handler(bot: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text(
            "⚙️ **Usage:**\n`/delpromo https://example.com`\n\n"
            "Provide the exact URL of the promotion you want to delete."
        )

    btn_url = message.command[1]
    deleted = await plugin_db.del_promo(btn_url)

    if deleted:
        await message.reply_text(
            f"🗑️ **Promo deleted successfully!**\n\n**URL:** {btn_url}",
            disable_web_page_preview=True,
        )
    else:
        await message.reply_text(
            f"❌ **Promo not found!**\n\nCould not find any promo matching URL: {btn_url}",
            disable_web_page_preview=True,
        )


# ============================================================
# 📄 List All Promotional Links
# ============================================================
@Client.on_message(
    filters.command("listpromos") & admin_filter & (filters.private | filters.group)
)
async def list_promo_handler(bot: Client, message: Message):
    promos = await plugin_db.get_all_promos()

    if not promos:
        return await message.reply_text(
            "⚠️ **No active promotional links found in the database.**"
        )

    text = "📢 **Current Promotional Links:**\n\n"
    for i, p in enumerate(promos, 1):
        text += f"**{i}. Text:** `{p['text']}`\n**🔗 URL:** {p['url']}\n\n"

    await message.reply_text(text, disable_web_page_preview=True)


# ============================================================
# 🛠️ Helper Function for Search/Filter modules
# ============================================================
async def get_promo_buttons() -> list:
    """
    Helper function to fetch all promos as Pyrogram InlineKeyboardButtons.
    You can import and use this in your search results module to inject promos!
    """
    promos = await plugin_db.get_all_promos()
    buttons = []

    for p in promos:
        buttons.append(InlineKeyboardButton(p["text"], url=p["url"]))

    return buttons
