import logging
from pyrogram import Client, filters
from pyrogram.types import Message
import info

logger = logging.getLogger(__name__)

if not hasattr(info, "REPAIR_MODE"):
    info.REPAIR_MODE = False

@Client.on_message(filters.command("repairmode") & filters.user(info.ADMINS))
async def toggle_repair_mode(bot: Client, message: Message):
    if len(message.command) > 1:
        arg = message.command[1].lower()
        if arg in ["on", "true", "enable"]: info.REPAIR_MODE = True
        elif arg in ["off", "false", "disable"]: info.REPAIR_MODE = False
        else: info.REPAIR_MODE = not info.REPAIR_MODE
    else:
        info.REPAIR_MODE = not info.REPAIR_MODE

    status = "🟢 **ENABLED**" if info.REPAIR_MODE else "🔴 **DISABLED**"
    text = f"🛠️ **Repair Mode is now {status}**\n\n"
    text += "⚠️ *Bot will NOT send files.*" if info.REPAIR_MODE else "✅ *Bot returned to normal.*"
    await message.reply_text(text)

@Client.on_message(filters.command("adminsettings") & filters.user(info.ADMINS))
async def show_admin_settings(bot: Client, message: Message):
    r_stat = "🟢 ENABLED" if getattr(info, "REPAIR_MODE", False) else "🔴 DISABLED"
    f_stat = "🟢 ENABLED" if getattr(info, "IS_FSUB_ENABLED", True) else "🔴 DISABLED"
    text = f"⚙️ **Admin Settings**\n━━━━━━━━━━━━━━\n🛠️ **Repair Mode:** {r_stat}\n🔐 **Force Subscribe:** {f_stat}\n\n"
    text += f"👥 **Total Admins Configured:** `{len(info.ADMINS) if getattr(info, 'ADMINS', None) else 0}`\n"
    await message.reply_text(text)
