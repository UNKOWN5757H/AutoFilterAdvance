from logging import ERROR, getLogger
from pyrogram import Client, enums, filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from database.connections_mdb import add_connection, all_connections, delete_connection, if_active
import info

logger = getLogger(__name__)
logger.setLevel(ERROR)

def get_admin_list():
    raw_admins = getattr(info, "ADMINS", [])
    if isinstance(raw_admins, str): return [int(x) for x in raw_admins.replace(",", " ").split() if x.strip().lstrip("-").isdigit()]
    elif isinstance(raw_admins, int): return [raw_admins]
    elif isinstance(raw_admins, list): return [int(x) for x in raw_admins if str(x).strip().lstrip("-").isdigit()]
    return []

@Client.on_message((filters.private | filters.group) & filters.command("connect"))
async def addconnection(client, message):
    userid = message.from_user.id if message.from_user else None
    if not userid: return await message.reply("You are anonymous admin. Use /connect in PM.")
    
    if message.chat.type == enums.ChatType.PRIVATE:
        try: cmd, group_id = message.text.split(" ", 1)
        except Exception: return await message.reply_text("<b>Enter correct format!</b>\n\n<code>/connect groupid</code>", quote=True)
    else: group_id = message.chat.id

    try:
        st = await client.get_chat_member(group_id, userid)
        if st.status not in [enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER] and userid not in get_admin_list():
            return await message.reply_text("You should be an admin in the Given group!", quote=True)
    except Exception: return await message.reply_text("Invalid Group ID!\n\nMake sure I'm present in your group!", quote=True)

    try:
        st = await client.get_chat_member(group_id, "me")
        if st.status == enums.ChatMemberStatus.ADMINISTRATOR:
            ttl = await client.get_chat(group_id)
            if await add_connection(str(group_id), str(userid)):
                await message.reply_text(f"Successfully connected to **{ttl.title}**\nNow manage your group from my PM!", quote=True)
            else: await message.reply_text("You're already connected to this chat!", quote=True)
        else: await message.reply_text("Add me as an admin in group", quote=True)
    except Exception: await message.reply_text("Some error occurred! Try again later.", quote=True)

@Client.on_message((filters.private | filters.group) & filters.command("disconnect"))
async def deleteconnection(client, message):
    userid = message.from_user.id if message.from_user else None
    if not userid: return
    
    if message.chat.type == enums.ChatType.PRIVATE: return await message.reply_text("Run /connections to view or disconnect from groups!", quote=True)
    group_id = message.chat.id

    st = await client.get_chat_member(group_id, userid)
    if st.status not in [enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER] and userid not in get_admin_list(): return

    if await delete_connection(str(userid), str(group_id)): await message.reply_text("Successfully disconnected from this chat", quote=True)
    else: await message.reply_text("This chat isn't connected to me!", quote=True)

@Client.on_message(filters.private & filters.command(["connections"]))
async def connections(client, message):
    userid = message.from_user.id
    groupids = await all_connections(str(userid))
    
    if not groupids: return await message.reply_text("There are no active connections!! Connect to some groups first.", quote=True)
    
    buttons = []
    for groupid in groupids:
        try:
            ttl = await client.get_chat(int(groupid))
            act = " - ACTIVE" if await if_active(str(userid), str(groupid)) else ""
            buttons.append([InlineKeyboardButton(text=f"{ttl.title}{act}", callback_data=f"groupcb:{groupid}:{act}")])
        except Exception: pass
        
    if buttons: await message.reply_text("Your connected group details:\n\n", reply_markup=InlineKeyboardMarkup(buttons), quote=True)
    else: await message.reply_text("There are no active connections!", quote=True)
