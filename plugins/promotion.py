import logging
import re

from pyrogram import Client, filters
from pyrogram.types import Message

import info

logger = logging.getLogger(__name__)


# ============================================================
# 🗄️ Promotions Database Handler
# ============================================================
class PromoDB:
    def __init__(self):
        self.db_url = getattr(info, "DATABASE_URI", None)
        if self.db_url:
            try:
                from motor.motor_asyncio import AsyncIOMotorClient

                self.client = AsyncIOMotorClient(self.db_url)
                self.database = self.client["BotDatabase"]
                self.col = self.database["promotions"]
                self.use_mongo = True
            except ImportError:
                logger.warning("motor is not installed! Using memory for Promotions.")
                self.use_mongo = False
                self.mock_db = {}
        else:
            self.use_mongo = False
            self.mock_db = {}

    async def add_promo(self, text: str, url: str):
        if self.use_mongo:
            await self.col.update_one(
                {"url": url}, {"$set": {"text": text, "url": url}}, upsert=True
            )
        else:
            self.mock_db[url] = text

    async def del_promo(self, url: str) -> bool:
        if self.use_mongo:
            result = await self.col.delete_one({"url": url})
            return result.deleted_count > 0
        else:
            if url in self.mock_db:
                del self.mock_db[url]
                return True
            return False

    async def get_all_promos(self) -> list:
        if self.use_mongo:
            return await self.col.find({}).to_list(length=None)
        else:
            return [{"url": u, "text": t} for u, t in self.mock_db.items()]


promo_db = PromoDB()


# ============================================================
# ➕ Add Promotional Link
# ============================================================
@Client.on_message(filters.command("addpromo") & filters.user(info.ADMINS))
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

    await promo_db.add_promo(btn_text, btn_url)

    await message.reply_text(
        f"✅ **Promo Added Successfully!**\n\n"
        f"**Text:** `{btn_text}`\n"
        f"**URL:** {btn_url}",
        disable_web_page_preview=True,
    )


# ============================================================
# ➖ Delete Promotional Link
# ============================================================
@Client.on_message(filters.command("delpromo") & filters.user(info.ADMINS))
async def del_promo_handler(bot: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text(
            "⚙️ **Usage:**\n`/delpromo https://example.com`\n\n"
            "Provide the exact URL of the promotion you want to delete."
        )

    btn_url = message.command[1]
    deleted = await promo_db.del_promo(btn_url)

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
@Client.on_message(filters.command("listpromos") & filters.user(info.ADMINS))
async def list_promo_handler(bot: Client, message: Message):
    promos = await promo_db.get_all_promos()

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

    Example usage in other files:
    from plugins.promotion import get_promo_buttons
    promos = await get_promo_buttons()
    """
    from pyrogram.types import InlineKeyboardButton

    promos = await promo_db.get_all_promos()
    buttons = []

    for p in promos:
        buttons.append(InlineKeyboardButton(p["text"], url=p["url"]))

    return buttons
