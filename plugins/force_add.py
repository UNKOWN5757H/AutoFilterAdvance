import asyncio
import time
from pyrogram import Client, StopPropagation, filters
from pyrogram.types import ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup, Message
from info import ADMINS
from database.plugin_dbs import plugin_db

async def is_admin(bot: Client, chat_id: int, user_id: int) -> bool:
    if user_id in [int(a) for a in ADMINS if str(a).isdigit()]:
        return True
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return any(role in str(getattr(member, "status", "")).lower() for role in ["administrator", "creator", "owner"])
    except Exception:
        return False

@Client.on_message(filters.command("setforceadd") & filters.group)
async def set_force_add(bot: Client, message: Message):
    if not message.from_user or not await is_admin(bot, message.chat.id, message.from_user.id):
        return await message.reply_text("❌ **Only ADMINS can use this command.**")
    if len(message.command) < 2:
        return await message.reply_text("⚙️ **Usage:** `/setforceadd <number>`")
        
    limit = int(message.command[1])
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 Force Add for ALL Members", callback_data=f"fa_set_{limit}_all_{message.from_user.id}")],
        [InlineKeyboardButton("🆕 Force Add for ONLY NEW Members", callback_data=f"fa_set_{limit}_new_{message.from_user.id}")]
    ])
    await message.reply_text("🎯 **Who should this requirement apply to?**", reply_markup=kb)

@Client.on_callback_query(filters.regex(r"^fa_set_(\d+)_([a-z]+)_(\d+)$"))
async def set_forceadd_callback(bot: Client, query):
    limit, mode, admin_id = int(query.matches[0].group(1)), query.matches[0].group(2), int(query.matches[0].group(3))
    if query.from_user.id != admin_id:
        return await query.answer("❌ Only the ADMIN who ran the command can choose this.", show_alert=True)
        
    await plugin_db.set_fa_settings(query.message.chat.id, limit, mode)
    mode_text = "ALL MEMBERS" if mode == "all" else "ONLY NEW MEMBERS"
    await query.message.edit_text(f"✅ **Force Add Configured Successfully!**\n\n🔢 **Limit:** `{limit} members`\n🎯 **Target:** `{mode_text}`")

@Client.on_message(filters.command("remforceadd") & filters.group)
async def remove_force_add(bot: Client, message: Message):
    if message.from_user and await is_admin(bot, message.chat.id, message.from_user.id):
        await plugin_db.set_fa_settings(message.chat.id, 0, "all")
        await message.reply_text("🗑️ **Force Add requirement has been completely removed.**")

@Client.on_message(filters.command(["topaddall", "topadd24", "topadd7"]) & filters.group)
async def top_adds(bot: Client, message: Message):
    limits = {"topaddall": None, "topadd24": 86400, "topadd7": 604800}
    time_limit = limits[message.command[0]]
    title = message.command[0].replace("topadd", "Top Adders ").upper()
    
    top_users = await plugin_db.get_fa_top_adds(message.chat.id, time_limit)
    if not top_users:
        return await message.reply_text(f"📊 **{title}**\n\nNo members have added anyone yet!")
        
    text = f"📊 **{title} (Top 10)**\n\n"
    for i, (uid, score) in enumerate(top_users, 1):
        text += f"**{i}.** <a href='tg://user?id={uid}'>User {uid}</a> ➔ `{score}` added\n"
    await message.reply_text(text, disable_web_page_preview=True)

@Client.on_message(filters.new_chat_members & filters.group)
async def track_added_members(bot: Client, message: Message):
    if not message.from_user:
        return
    for u in message.new_chat_members:
        await plugin_db.track_fa_new_user(message.chat.id, u.id)
        
    settings = await plugin_db.get_fa_settings(message.chat.id)
    if settings.get("limit", 0) == 0:
        return

    adder_id = message.from_user.id
    added_others = [u for u in message.new_chat_members if u.id != adder_id and not u.is_bot]
    if not added_others:
        return

    await plugin_db.increment_fa_adds(message.chat.id, adder_id, len(added_others))
    current_adds = await plugin_db.get_fa_user_adds(message.chat.id, adder_id)

    if current_adds >= settings["limit"]:
        try:
            await bot.restrict_chat_member(
                message.chat.id, adder_id,
                permissions=ChatPermissions(can_send_messages=True, can_send_media_messages=True, can_send_other_messages=True, can_invite_users=True)
            )
        except Exception:
            pass
        msg = await message.reply_text(f"🎉 Thank you {message.from_user.mention}! You've met the requirement. You can now chat freely!")
        await asyncio.sleep(8)
        try:
            await msg.delete()
        except Exception:
            pass

@Client.on_message(filters.group & ~filters.service, group=-1)
async def enforce_force_add(bot: Client, message: Message):
    if not message.from_user:
        return
    settings = await plugin_db.get_fa_settings(message.chat.id)
    limit = settings.get("limit", 0)
    
    if limit == 0 or await is_admin(bot, message.chat.id, message.from_user.id):
        return
        
    if settings.get("mode") == "new" and not await plugin_db.is_fa_new_user(message.chat.id, message.from_user.id):
        return

    text = message.text or message.caption
    if text and text.startswith("/"):
        return

    current_adds = await plugin_db.get_fa_user_adds(message.chat.id, message.from_user.id)
    if current_adds < limit:
        try:
            await message.delete()
            await bot.restrict_chat_member(message.chat.id, message.from_user.id, permissions=ChatPermissions(can_send_messages=False, can_invite_users=True), until_date=int(time.time()) + 120)
            warn_msg = await message.reply_text(
                f"🛑 **Hold on, {message.from_user.mention}!**\n\nYou must add **{limit - current_adds} more member(s)** to chat.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📊 Check My Progress", callback_data="forceadd_check")]])
            )
            asyncio.create_task(delete_after_delay(warn_msg, 120))
            raise StopPropagation
        except StopPropagation:
            raise
        except Exception:
            pass

async def delete_after_delay(msg, delay):
    await asyncio.sleep(delay)
    try:
        await msg.delete()
    except Exception:
        pass

@Client.on_callback_query(filters.regex("^forceadd_check$"))
async def check_adds_button(bot: Client, query):
    settings = await plugin_db.get_fa_settings(query.message.chat.id)
    if settings.get("limit", 0) == 0:
        return await query.answer("Force Add is not active.", show_alert=True)
    current = await plugin_db.get_fa_user_adds(query.message.chat.id, query.from_user.id)
    limit = settings["limit"]
    
    if current >= limit:
        await query.answer(f"✅ You have added {current} members. Chat freely!", show_alert=True)
    else:
        await query.answer(f"⚠️ Added {current}/{limit} members.\nYou need {limit - current} more to chat.", show_alert=True)
