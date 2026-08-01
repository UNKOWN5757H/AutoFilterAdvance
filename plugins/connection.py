from pyrogram import Client, enums, filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from database.connections_mdb import add_connection, all_connections, delete_connection, if_active
from info import ADMINS

@Client.on_message((filters.private | filters.group) & filters.command("connect"))
async def addconnection(client, message):
    userid = message.from_user.id if message.from_user else None
    if not userid: return
    
    if message.chat.type == enums.ChatType.PRIVATE:
        if len(message.command) < 2: return await message.reply_text("⚙️ **Usage:** `/connect <group_id>`")
        group_id = message.command[1]
    else:
        group_id = message.chat.id

    try:
        st = await client.get_chat_member(group_id, userid)
        if st.status not in [enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER] and userid not in ADMINS:
            return await message.reply_text("❌ You must be an admin in that group!")
            
        bot_st = await client.get_chat_member(group_id, "me")
        if bot_st.status != enums.ChatMemberStatus.ADMINISTRATOR:
            return await message.reply_text("❌ Make me an admin in the group first!")

        chat = await client.get_chat(group_id)
        if await add_connection(str(group_id), str(userid)):
            await message.reply_text(f"✅ Successfully connected to **{chat.title}**!")
        else:
            await message.reply_text("⚠️ You're already connected to this chat!")
    except Exception:
        await message.reply_text("❌ Invalid Group ID or I am not present in the group.")

@Client.on_message((filters.private | filters.group) & filters.command("disconnect"))
async def deleteconnection(client, message):
    userid = message.from_user.id if message.from_user else None
    if not userid: return
    
    if message.chat.type == enums.ChatType.PRIVATE:
        return await message.reply_text("Use `/connections` to disconnect from groups.")
        
    group_id = message.chat.id
    if await delete_connection(str(userid), str(group_id)):
        await message.reply_text("✅ Successfully disconnected from this chat.")
    else:
        await message.reply_text("⚠️ This chat isn't connected to me!")

@Client.on_message(filters.private & filters.command("connections"))
async def connections(client, message):
    groupids = await all_connections(str(message.from_user.id))
    if not groupids: return await message.reply_text("⚠️ No active connections!")
    
    buttons = []
    for gid in groupids:
        try:
            chat = await client.get_chat(int(gid))
            active = " - ACTIVE" if await if_active(str(message.from_user.id), str(gid)) else ""
            buttons.append([InlineKeyboardButton(text=f"{chat.title}{active}", callback_data=f"groupcb:{gid}:{active}")])
        except Exception: pass
        
    if buttons: await message.reply_text("🔗 **Your Connected Groups:**", reply_markup=InlineKeyboardMarkup(buttons))
    else: await message.reply_text("⚠️ No active connections!")
