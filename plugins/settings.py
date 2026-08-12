import logging

from pyrogram import Client, filters
from pyrogram.types import Message

import info

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
# ⚙️ Initialize Runtime State
# ============================================================
# Defaults to False so the bot works normally upon startup
if not hasattr(info, "REPAIR_MODE"):
    info.REPAIR_MODE = False


# ============================================================
# 🛠️ Toggle Repair Mode
# ============================================================
@Client.on_message(
    filters.command("repairmode") & admin_filter & (filters.private | filters.group)
)
async def toggle_repair_mode(bot: Client, message: Message):
    """
    Toggles the repair mode on or off.
    Usage: /repairmode, /repairmode on, or /repairmode off
    """
    if len(message.command) > 1:
        arg = message.command[1].lower()
        if arg in ["on", "true", "enable"]:
            info.REPAIR_MODE = True
        elif arg in ["off", "false", "disable"]:
            info.REPAIR_MODE = False
        else:
            # Toggle if unknown argument
            info.REPAIR_MODE = not getattr(info, "REPAIR_MODE", False)
    else:
        # Toggle if no argument provided
        info.REPAIR_MODE = not getattr(info, "REPAIR_MODE", False)

    status = "🟢 **ENABLED**" if info.REPAIR_MODE else "🔴 **DISABLED**"

    text = f"🛠️ **Repair Mode is now {status}**\n\n"
    if info.REPAIR_MODE:
        text += "⚠️ *The bot is now in maintenance mode. It will NOT send any files to users until this is disabled.*"
    else:
        text += "✅ *The bot has returned to normal operation and will process file requests.*"

    await message.reply_text(text)


# ============================================================
# 📊 View Admin Settings
# ============================================================
@Client.on_message(
    filters.command("adminsettings") & admin_filter & (filters.private | filters.group)
)
async def show_admin_settings(bot: Client, message: Message):
    """
    Displays the current state of all major bot configurations.
    """
    # Fetch states (falling back to defaults if not set yet)
    repair_status = (
        "🟢 ENABLED" if getattr(info, "REPAIR_MODE", False) else "🔴 DISABLED"
    )
    fsub_status = (
        "🟢 ENABLED" if getattr(info, "IS_FSUB_ENABLED", True) else "🔴 DISABLED"
    )

    text = "⚙️ **Current Admin Settings Dashboard**\n"
    text += "━━━━━━━━━━━━━━━━━━━━━\n\n"

    text += f"🛠️ **Repair Mode:** {repair_status}\n"
    text += f"🔐 **Force Subscribe:** {fsub_status}\n\n"

    # Show FSub Channels if configured
    if getattr(info, "AUTH_CHANNEL", None):
        text += f"📢 **Main FSub Channel:** <code>{info.AUTH_CHANNEL}</code>\n"
    else:
        text += "📢 **Main FSub Channel:** ❌ Not Set\n"

    if getattr(info, "REQ_CHANNEL", None):
        text += f"📨 **Request FSub Channel:** <code>{info.REQ_CHANNEL}</code>\n"
    else:
        text += "📨 **Request FSub Channel:** ❌ Not Set\n"

    # Show Admin Count
    admin_count = len(info.ADMINS) if getattr(info, "ADMINS", None) else 0
    text += f"\n👥 **Total Admins Configured:** `{admin_count}`\n"

    text += "\n━━━━━━━━━━━━━━━━━━━━━\n"
    text += (
        "💡 *Use commands like `/repairmode` or `/disablefsub` to toggle these values.*"
    )

    await message.reply_text(text)
