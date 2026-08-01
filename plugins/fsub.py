import asyncio
import logging
from pyrogram import Client, enums, filters
from pyrogram.errors import ChatAdminRequired, UserNotParticipant
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message
import info
from database.join_reqs import join_reqs as db_req
from database.plugin_dbs import plugin_db

logger = logging.getLogger(__name__)

if not hasattr(info, "IS_FSUB_ENABLED"): info.IS_FSUB_ENABLED = True
if not hasattr(info, "FSUB_MAX_COUNT"): info.FSUB_MAX_COUNT = 0 
if not hasattr(info, "FSUB_CHANNELS"): info.FSUB_CHANNELS = {}

def migrate_legacy_fsub():
    for attr, f_type, title in [("AUTH_CHANNEL", "regular", "Main Channel"), ("REQ_CHANNEL", "req", "Request Channel")]:
        ch = getattr(info, attr, None)
        if ch and str(ch) not in info.FSUB_CHANNELS:
            info.FSUB_CHANNELS[str(ch)] = {"title": title, "link": None, "target": None, "type": f_type, "status": "active"}

migrate_legacy_fsub()

async def get_invite_link(bot: Client, chat_id: str) -> str:
    data = info.FSUB_CHANNELS.get(chat_id, {})
    if data.get("target"): return data["target"]
    if data.get("link"): return data["link"]
    try:
        chat = await bot.get_chat(int(chat_id))
        invite = await bot.create_chat_invite_link(int(chat_id), creates_join_request=(data.get("type") == "req"))
        info.FSUB_CHANNELS[chat_id].update({"link": invite.invite_link, "title": chat.title})
        return invite.invite_link
    except Exception as e:
        logger.error(f"FSub link error for {chat_id}: {e}")
        return ""

async def check_user_in_channel(bot: Client, channel_id: int, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(channel_id, user_id)
        return member.status in [enums.ChatMemberStatus.MEMBER, enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER]
    except UserNotParticipant:
        return False
    except Exception:
        return False

async def ForceSub(bot: Client, message: Message, file_id: str = None, mode: str = None) -> bool:
    user = message.from_user
    if not user or user.id in info.ADMINS or not getattr(info, "IS_FSUB_ENABLED", True): return True

    active_fsubs = {k: v for k, v in info.FSUB_CHANNELS.items() if v.get("status") == "active"}
    if not active_fsubs: return True

    not_joined = []
    for chat_id_str, data in active_fsubs.items():
        if not await check_user_in_channel(bot, int(chat_id_str), user.id):
            link = await get_invite_link(bot, chat_id_str)
            if link:
                btn_text = f"📨 Join {data.get('title', 'Channel')}" if data.get("type") == "req" else f"🔐 Join {data.get('title', 'Channel')}"
                not_joined.append([InlineKeyboardButton(btn_text, url=link)])

    if not not_joined:
        await plugin_db.add_fsub_user(user.id)
        return True

    not_joined.append([InlineKeyboardButton("✅ I've Joined", callback_data=f"refresh_fsub_{file_id or 0}")])
    await message.reply_text("🔒 **You must join our update channel(s) to use this bot.**", reply_markup=InlineKeyboardMarkup(not_joined), disable_web_page_preview=True)
    return False

@Client.on_message(filters.command("setfsub") & filters.user(info.ADMINS))
async def add_dynamic_fsub(bot: Client, message: Message):
    if len(message.command) < 2: return await message.reply_text("⚙️ **Usage:** `/setfsub [channel_id]`")
    channel_id = message.command[1]
    
    try:
        chat = await bot.get_chat(int(channel_id))
        await message.reply_text(f"🎯 **Target:** `{chat.title}`\n\nIs this a **Join Request** channel? (Reply `y` or `n`)")
        resp = await bot.listen(message.chat.id, timeout=30)
        is_req = resp.text.lower() == "y"
        
        active_count = sum(1 for c in info.FSUB_CHANNELS.values() if c.get("status") == "active")
        status = "pending" if (info.FSUB_MAX_COUNT > 0 and active_count >= info.FSUB_MAX_COUNT) else "active"
        invite = await bot.create_chat_invite_link(chat.id, creates_join_request=is_req)
        
        info.FSUB_CHANNELS[channel_id] = {"title": chat.title, "link": invite.invite_link, "target": None, "type": "req" if is_req else "regular", "status": status}
        await message.reply_text(f"✅ **FSub Configured!**\n📢 **Channel:** `{chat.title}`\n🟢 **Status:** `{status.upper()}`")
    except ChatAdminRequired:
        await message.reply_text("❌ **I lack admin/invite rights in that channel.**")
    except Exception as e:
        await message.reply_text(f"❌ **Error:** {e}")

@Client.on_message(filters.command(["enablefsub", "disablefsub"]) & filters.user(info.ADMINS))
async def toggle_fsub(bot: Client, message: Message):
    enable = message.command[0] == "enablefsub"
    info.IS_FSUB_ENABLED = enable
    await message.reply_text(f"{'✅ ENABLED' if enable else '❌ DISABLED'} **Force Subscribe.**")

@Client.on_message(filters.command("checkfsubusers") & filters.user(info.ADMINS))
async def check_fsub_users(bot: Client, message: Message):
    count = await plugin_db.get_fsub_count()
    await message.reply_text(f"👥 **Total Force Subscribed Users (DB):** <code>{count}</code>")
