from logging import ERROR, getLogger

from pyrogram import Client, filters
from pyrogram.types import Message

import info

logger = getLogger(__name__)
logger.setLevel(ERROR)


async def admin_check(_, __, message: Message):
    if not message.from_user:
        return False
    return (
        message.from_user.id in info.ADMINS or str(message.from_user.id) in info.ADMINS
    )


admin_filter = filters.create(admin_check)

if not hasattr(info, "REPAIR_MODE"):
    info.REPAIR_MODE = False


@Client.on_message(
    filters.command("repairmode") & admin_filter & (filters.private | filters.group)
)
async def toggle_repair_mode(bot: Client, message: Message):
    if len(message.command) > 1:
        arg = message.command[1].lower()
        if arg in ["on", "true", "enable"]:
            info.REPAIR_MODE = True
        elif arg in ["off", "false", "disable"]:
            info.REPAIR_MODE = False
        else:
            info.REPAIR_MODE = not getattr(info, "REPAIR_MODE", False)
    else:
        info.REPAIR_MODE = not getattr(info, "REPAIR_MODE", False)

    status = "🟢 **ENABLED**" if info.REPAIR_MODE else "🔴 **DISABLED**"
    text = f"🛠️ **Repair Mode is now {status}**\n\n"
    if info.REPAIR_MODE:
        text += "⚠️ *The bot is now in maintenance mode. It will NOT send any files to users until this is disabled.*"
    else:
        text += "✅ *The bot has returned to normal operation and will process file requests.*"

    await message.reply_text(text)


@Client.on_message(
    filters.command("adminsettings") & admin_filter & (filters.private | filters.group)
)
async def show_admin_settings(bot: Client, message: Message):
    repair_status = (
        "🟢 ENABLED" if getattr(info, "REPAIR_MODE", False) else "🔴 DISABLED"
    )
    fsub_status = (
        "🟢 ENABLED" if getattr(info, "IS_FSUB_ENABLED", True) else "🔴 DISABLED"
    )

    text = "⚙️ **Current Admin Settings Dashboard**\n━━━━━━━━━━━━━━━━━━━━━\n\n"
    text += f"🛠️ **Repair Mode:** {repair_status}\n🔐 **Force Subscribe:** {fsub_status}\n\n"

    if getattr(info, "AUTH_CHANNEL", None):
        text += f"📢 **Main FSub Channel:** <code>{info.AUTH_CHANNEL}</code>\n"
    else:
        text += "📢 **Main FSub Channel:** ❌ Not Set\n"

    if getattr(info, "REQ_CHANNEL", None):
        text += f"📨 **Request FSub Channel:** <code>{info.REQ_CHANNEL}</code>\n"
    else:
        text += "📨 **Request FSub Channel:** ❌ Not Set\n"

    admin_count = len(info.ADMINS) if getattr(info, "ADMINS", None) else 0
    text += f"\n👥 **Total Admins Configured:** `{admin_count}`\n\n━━━━━━━━━━━━━━━━━━━━━\n💡 *Use commands like `/repairmode` or `/disablefsub` to toggle these values.*"

    await message.reply_text(text)
