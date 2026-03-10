import asyncio
from pyrogram import Client, filters, enums
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from info import ADMINS, AUTH_CHANNEL, REQ_CHANNEL
from database.join_reqs import JoinReqs

db = JoinReqs()


# ============================================================
# 🧠 Runtime ForceSub Checker (used by commands.py)
# ============================================================
async def ForceSub(bot: Client, message: Message, file_id: str = None, mode: str = None) -> bool:
    """
    Checks if user is subscribed to AUTH_CHANNEL or REQ_CHANNEL.
    Returns True if allowed, False if not (and sends a join prompt).
    """
    user = message.from_user

    # Admins always bypass
    if not user or user.id in ADMINS:
        return True

    try:
        # No ForceSub channel configured
        if not AUTH_CHANNEL and not REQ_CHANNEL:
            return True

        # Check AUTH_CHANNEL
        if AUTH_CHANNEL:
            try:
                member = await bot.get_chat_member(int(AUTH_CHANNEL), user.id)
                if member.status in [enums.ChatMemberStatus.MEMBER,
                                     enums.ChatMemberStatus.ADMINISTRATOR,
                                     enums.ChatMemberStatus.OWNER]:
                    return True
            except Exception:
                pass  # user not a member

        # Check REQ_CHANNEL (optional)
        if REQ_CHANNEL:
            try:
                member = await bot.get_chat_member(int(REQ_CHANNEL), user.id)
                if member.status in [enums.ChatMemberStatus.MEMBER,
                                     enums.ChatMemberStatus.ADMINISTRATOR,
                                     enums.ChatMemberStatus.OWNER]:
                    return True
            except Exception:
                pass

        # Not subscribed — prompt user
        buttons = []
        if AUTH_CHANNEL:
            buttons.append([InlineKeyboardButton("🔐 Join Main Channel", url=f"https://t.me/{str(AUTH_CHANNEL).lstrip('@')}")])
        if REQ_CHANNEL:
            buttons.append([InlineKeyboardButton("📨 Join Request Channel", url=f"https://t.me/{str(REQ_CHANNEL).lstrip('@')}")])

        buttons.append([InlineKeyboardButton("✅ I've Joined", callback_data=f"refresh_fsub_{file_id or 0}")])

        await message.reply_text(
            "🔒 **You must join the required channel(s) to use this bot.**\n\n"
            "Once you’ve joined, click **‘I’ve Joined’** to continue.",
            reply_markup=InlineKeyboardMarkup(buttons),
            disable_web_page_preview=True
        )
        return False

    except Exception as e:
        print(f"[ForceSub Error] {e}")
        return True  # fail-safe (don't block bot if API error)


# ============================================================
# 🔍 /fsub — Check ForceSub status
# ============================================================
@Client.on_message(filters.command("fsub") & filters.user(ADMINS))
async def fsub_status(bot: Client, message: Message):
    """Show current ForceSub channel info."""
    if not AUTH_CHANNEL and not REQ_CHANNEL:
        return await message.reply_text("⚠️ ForceSub is currently **disabled**.")

    text = "🔐 **Force Subscription Status**\n\n"
    if AUTH_CHANNEL:
        try:
            chat = await bot.get_chat(int(AUTH_CHANNEL))
            text += f"📢 ForceSub Channel: `{chat.title}` (`{chat.id}`)\n"
            text += f"🔗 Invite Link: {chat.invite_link or 'Not set'}\n"
        except Exception as e:
            text += f"❌ Could not fetch channel info.\nError: `{e}`\n"
    elif REQ_CHANNEL:
        try:
            chat = await bot.get_chat(int(REQ_CHANNEL))
            text += f"📨 Join Request Channel: `{chat.title}` (`{chat.id}`)\n"
        except Exception as e:
            text += f"❌ Could not fetch REQ channel info.\nError: `{e}`\n"

    await message.reply_text(text)


# ============================================================
# ➕ /add_fsub — Set or change ForceSub channel
# ============================================================
@Client.on_message(filters.command("add_fsub") & filters.user(ADMINS))
async def add_fsub(bot: Client, message: Message):
    """
    Add or update the ForceSub channel.
    Usage: /add_fsub <channel_id>
    """
    if len(message.command) < 2:
        return await message.reply_text("⚙️ Usage: `/add_fsub <channel_id>`")

    try:
        channel_id = int(message.command[1])
        chat = await bot.get_chat(channel_id)
        title = chat.title
        link = chat.invite_link or (await bot.create_chat_invite_link(channel_id)).invite_link

        await message.reply_text(
            f"✅ ForceSub channel set successfully!\n\n"
            f"📢 **{title}** (`{channel_id}`)\n"
            f"🔗 Invite: {link}"
        )

    except Exception as e:
        await message.reply_text(f"❌ Failed to add ForceSub channel.\n\nError: `{e}`")


# ============================================================
# 📄 /get_fsub — Show ForceSub channel details
# ============================================================
@Client.on_message(filters.command("get_fsub") & filters.user(ADMINS))
async def get_fsub(bot: Client, message: Message):
    """Show the active ForceSub channel invite link."""
    if not AUTH_CHANNEL and not REQ_CHANNEL:
        return await message.reply_text("❌ No ForceSub channel configured.")

    try:
        channel_id = int(AUTH_CHANNEL or REQ_CHANNEL)
        chat = await bot.get_chat(channel_id)
        link = chat.invite_link or (await bot.create_chat_invite_link(channel_id)).invite_link
        await message.reply_text(
            f"🔗 **ForceSub Channel:** `{chat.title}` (`{channel_id}`)\n"
            f"👉 Invite Link: {link}"
        )
    except Exception as e:
        await message.reply_text(f"⚠️ Unable to fetch channel info.\nError: `{e}`")


# ============================================================
# 📊 /ttreq — Show total pending join requests
# ============================================================
@Client.on_message(filters.command("ttreq") & filters.user(ADMINS))
async def total_requests(bot: Client, message: Message):
    """Show total join requests stored in DB."""
    try:
        total = await db.total_requests()
        await message.reply_text(f"📨 **Total Join Requests:** `{total}`")
    except Exception as e:
        await message.reply_text(f"⚠️ Failed to fetch join requests.\nError: `{e}`")


# ============================================================
# 🧹 /clreq — Clear all join requests
# ============================================================
@Client.on_message(filters.command("clreq") & filters.user(ADMINS))
async def clear_requests(bot: Client, message: Message):
    """Delete all stored join request records."""
    confirm = await message.reply_text("⚠️ Are you sure? This will delete all join requests. (y/n)")

    try:
        resp = await bot.listen(message.chat.id, timeout=30)
        if resp.text.lower() == "y":
            await db.clear_all()
            await message.reply_text("✅ All join requests cleared successfully.")
        else:
            await message.reply_text("❌ Cancelled.")
    except asyncio.TimeoutError:
        await message.reply_text("⌛ Timeout: Operation cancelled.")
    except Exception as e:
        await message.reply_text(f"⚠️ Error clearing requests.\nError: `{e}`")
