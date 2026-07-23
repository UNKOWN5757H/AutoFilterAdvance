class script(object):
    START_TXT = """<b>Hey {mention} bro 🥂,\nI'm {bname}, the Moviebot! \n \nJoin our gang — We've got Movies hotter than your ex's new filing 😊🎬</b>"""
    HELP_TXT = """<b>You can find the bot commands here.\n \n‣ /help - Show this help message\n \n<quote>Tap on corresponding modules to get the commands of that module.</quote></b>"""
    ABOUT_TXT = """<b>○ 𝗠𝘆 𝗡𝗮𝗺𝗲 : {bname}
○ 𝗖𝗿𝗲𝗮𝘁𝗼𝗿 : <a href=https://t.me/SandalwoodSupportBot><b>Sandalwood Support</b></a>
○ 𝗟𝗶𝗯𝗿𝗮𝗿𝘆 : 𝙿𝚈𝚁𝙾𝙶𝚁𝙰𝙼
○ 𝗟𝗮𝗻𝗴𝘂𝗮𝗴𝗲 : 𝙿𝚈𝚃𝙷𝙾𝙽 𝟹.10
○ 𝗗𝗮𝘁𝗮𝗕𝗮𝘀𝗲 : 𝙼𝙾𝙽𝙶𝙾 𝙳𝙱
○ 𝗕𝘂𝗶𝗹𝗱 𝗩𝗲𝗿𝘀𝗶𝗼𝗻 : V2.0 [ 𝙱𝙴𝚃𝙰 ]</b>"""
    SOURCE_TXT = """<b>Source Code Of This Bot is Private 😊"""
    MANUELFILTER_TXT = """𝗙𝗶𝗹𝘁𝗲𝗿𝘀

- Filter is the feature were users can set automated replies for a particular keyword and I will respond whenever a keyword is found the message

<blockquote>𝗡𝗼𝘁𝗲:
1. I should have Admin Privillage.
2. Only Admins can add Filters in a Chat.
3. Alert buttons have a limit of 64 characters.</blockquote>

<blockquote>𝗖𝗼𝗺𝗺𝗮𝗻𝗱𝘀 𝗮𝗻𝗱 𝗨𝘀𝗮𝗴𝗲:</blockquote>

• /filter - add a filter in chat
• /filters - list all the filters of a chat
• /del - delete a specific filter in chat
• /delall - delete the whole filters in a chat (chat owner only)"""
    BUTTON_TXT = """𝗕𝘂𝘁𝘁𝗼𝗻𝘀

- I will Supports both url and alert inline buttons.

<blockquote>𝗡𝗼𝘁𝗲:
1. Telegram will not allows you to send buttons without any content, so content is mandatory.
2. I supports buttons with any telegram media type.
3. Buttons should be properly parsed as markdown format</blockquote>

URL buttons:
[Button Text](buttonurl:https://t.me/KR_PICTURE)

Alert buttons:
[Button Text](buttonalert:This is an alert message)"""
    AUTOFILTER_TXT = """𝗔𝘂𝘁𝗼 𝗙𝗶𝗹𝘁𝗲𝗿

<blockquote>𝗡𝗼𝘁𝗲:
    𝗧𝗵𝗶𝘀 𝗺𝗼𝗱𝘂𝗹𝗲 𝗼𝗻𝗹𝘆 𝘄𝗼𝗿𝗸𝘀 𝗳𝗼𝗿 𝗺𝘆 𝗔𝗱𝗺𝗶𝗻𝘀</blockquote>
    
1. Make me the admin of your channel if it's private.
2. make sure that your channel does not contains camrips, porn and fake files.
3. Forward the last message to me with quotes.
 I'll add all the files in that channel to my db."""
    CONNECTION_TXT = """𝗖𝗼𝗻𝗻𝗲𝗰𝘁𝗶𝗼𝗻𝘀

- Used to connect bot to PM for managing filters 
- it helps to avoid spamming in groups.

<blockquote>𝗡𝗼𝘁𝗲:
1. Only Group Admins can add a connection.
2. Send /connect for connecting me to ur PM</blockquote>

𝗖𝗼𝗺𝗺𝗮𝗻𝗱𝘀 𝗮𝗻𝗱 𝗨𝘀𝗮𝗴𝗲:

• /connect  - Connect a particular chat to your PM
• /disconnect  - Disconnect from a chat
• /connections - List all your connections"""
    FRSUB_TXT = """Help:  𝗙𝗼𝗿𝗰𝗲𝗦𝘂𝗯 𝗠𝗼𝗱

<blockquote>𝗡𝗼𝘁𝗲:
    𝗧𝗵𝗶𝘀 𝗺𝗼𝗱𝘂𝗹𝗲 𝗼𝗻𝗹𝘆 𝘄𝗼𝗿𝗸𝘀 𝗳𝗼𝗿 𝗺𝘆 𝗔𝗱𝗺𝗶𝗻𝘀</blockquote>

𝗖𝗼𝗺𝗺𝗮𝗻𝗱𝘀 𝗮𝗻𝗱 𝗨𝘀𝗮𝗴𝗲:

• /fsub - Enable ForceSub / Request Sub Settings
• /add_fsub - Add ForceSub / Request Sub Channel
• /get_fsub - Get saved ForceSub Channel Detail
• /ttreq - Get total request counts on current FSub Channel
• /clreq - Clear Requests on current FSub Channel"""
    EXTRAMOD_TXT = """Help:  𝗔𝗱𝗺𝗶𝗻 𝗠𝗼𝗱𝘀

<blockquote>𝗡𝗼𝘁𝗲:
    𝗧𝗵𝗶𝘀 𝗺𝗼𝗱𝘂𝗹𝗲 𝗼𝗻𝗹𝘆 𝘄𝗼𝗿𝗸𝘀 𝗳𝗼𝗿 𝗺𝘆 𝗔𝗱𝗺𝗶𝗻𝘀</blockquote>

𝗖𝗼𝗺𝗺𝗮𝗻𝗱𝘀 𝗮𝗻𝗱 𝗨𝘀𝗮𝗴𝗲:

• /logs - to get the rescent errors
• /stats - to get status of files in db.
• /restart - Restart Bot
• /delete - to delete a specific file from db.
• /users - to get list of my users and ids.
• /ban  - to ban a user.
• /unban  - to unban a user.
• /chats  - to get list of Groups
• /channel - to get list of total connected channels
• /broadcast - to broadcast a message to all users
• /group_broadcast - to broadcast a message to all saved Groups"""
    ADMIN_TXT = """Help: <b>Admin mods</b>

<b>NOTE:</b>
This module only works for my admins

<b>Commands and Usage:</b>
• /logs - <code>to get the rescent errors</code>
• /stats - <code>to get status of files in db.</code>
• /delete - <code>to delete a specific file from db.</code>
• /users - <code>to get list of my users and ids.</code>
• /chats - <code>to get list of the my chats and ids </code>
• /leave  - <code>to leave from a chat.</code>
• /disable  -  <code>do disable a chat.</code>
• /ban  - <code>to ban a user.</code>
• /unban  - <code>to unban a user.</code>
• /channel - <code>to get list of total connected channels</code>
• /broadcast - <code>to broadcast a message to all users</code>"""
    STATUS_TXT = """★ 𝚃𝙾𝚃𝙰𝙻 𝙵𝙸𝙻𝙴𝚂: <code>{}</code>
★ 𝚃𝙾𝚃𝙰𝙻 𝚄𝚂𝙴𝚁𝚂: <code>{}</code>
★ 𝚃𝙾𝚃𝙰𝙻 𝙲𝙷𝙰𝚃𝚂: <code>{}</code>
★ 𝚄𝚂𝙴𝙳 𝚂𝚃𝙾𝚁𝙰𝙶𝙴: <code>{}</code> 𝙼𝚒𝙱
★ 𝙵𝚁𝙴𝙴 𝚂𝚃𝙾𝚁𝙰𝙶𝙴: <code>{}</code> 𝙼𝚒𝙱"""
    LOG_TEXT_G = """#NewGroup
Group = {}(<code>{}</code>)
Total Members = <code>{}</code>
Added By - {}
"""
    LOG_TEXT_P = """#NewUser
ID - <code>{}</code>
Name - {}
"""

    DICS_TXT = """ <b><code>ᴛʜɪꜱ ɪꜱ ᴀɴ ᴏᴘᴇɴ ꜱᴏᴜʀᴄᴇ ᴘʀᴏᴊᴇᴄᴛ.

ᴀʟʟ ᴛʜᴇ ꜰɪʟᴇꜱ ɪɴ ᴛʜɪꜱ ʙᴏᴛ ᴀʀᴇ ꜰʀᴇᴇʟʏ ᴀᴠᴀɪʟᴀʙʟᴇ ᴏɴ ᴛʜᴇ ɪɴᴛᴇʀɴᴇᴛ ᴏʀ ᴘᴏꜱᴛᴇᴅ ʙʏ ꜱᴏᴍᴇʙᴏᴅʏ ᴇʟꜱᴇ. 
ᴊᴜꜱᴛ ꜰᴏʀ ᴇᴀꜱʏ ꜱᴇᴀʀᴄʜɪɴɢ ᴛʜɪꜱ ʙᴏᴛ ɪꜱ ɪɴᴅᴇxɪɴɢꜰɪʟᴇꜱ ᴡʜɪᴄʜ ᴀʀᴇ ᴀʟʀᴇᴀᴅʏ ᴜᴘʟᴏᴀᴅᴇᴅ ᴏɴ ᴛᴇʟᴇɢʀᴀᴍ. 
ᴡᴇ ʀᴇꜱᴘᴇᴄᴛ ᴀʟʟ ᴛʜᴇ ᴄᴏᴘʏʀɪɢʜᴛ ʟᴀᴡꜱ ᴀɴᴅ ᴡᴏʀᴋꜱ ɪɴ ᴄᴏᴍᴘʟɪᴀɴᴄᴇ ᴡɪᴛʜ ᴅᴍᴄᴀ ᴀɴᴅ ᴇᴜᴄᴅ. 
ɪꜰ ᴀɴʏᴛʜɪɴɢ ɪꜱ ᴀɢᴀɪɴꜱᴛ ʟᴀᴡ ᴘʟᴇᴀꜱᴇ ᴄᴏɴᴛᴀᴄᴛ ᴍᴇ ꜱᴏ ᴛʜᴀᴛ ɪᴛ ᴄᴀɴ ʙᴇ ʀᴇᴍᴏᴠᴇᴅ ᴀꜱᴀᴘ. 
ɪᴛ ɪꜱ ꜰᴏʀʙɪʙʙᴇɴ ᴛᴏ ᴅᴏᴡɴʟᴏᴀᴅ, ꜱᴛʀᴇᴀᴍ, ʀᴇᴘʀᴏᴅᴜᴄᴇ, ᴏʀ ʙʏ ᴀɴʏ ᴍᴇᴀɴꜱ, ꜱʜᴀʀᴇ, ᴏʀ ᴄᴏɴꜱᴜᴍᴇ, ᴄᴏɴᴛᴇɴᴛ ᴡɪᴛʜᴏᴜᴛ ᴇxᴘʟɪᴄɪᴛ ᴘᴇʀᴍɪꜱꜱɪᴏɴ ꜰʀᴏᴍ ᴛʜᴇ ᴄᴏɴᴛᴇɴᴛ ᴄʀᴇᴀᴛᴏʀ ᴏʀ ʟᴇɢᴀʟ ᴄᴏᴘʏʀɪɢʜᴛ ʜᴏʟᴅᴇʀ. 
ɪꜰ ʏᴏᴜ ʙᴇʟɪᴇᴠᴇ ᴛʜɪꜱ ʙᴏᴛ ɪꜱ ᴠɪᴏʟᴀᴛɪɴɢ ʏᴏᴜʀ ɪɴᴛᴇʟʟᴇᴄᴛᴜᴀʟ ᴘʀᴏᴘᴇʀᴛʏ, ᴄᴏɴᴛᴀᴄᴛ ᴛʜᴇ ʀᴇꜱᴘᴇᴄᴛɪᴠᴇ ᴄʜᴀɴɴᴇʟꜱ ꜰᴏʀ ʀᴇᴍᴏᴠᴀʟ. 
ᴛʜᴇ ʙᴏᴛ ᴅᴏᴇꜱ ɴᴏᴛ ᴏᴡɴ ᴀɴʏ ᴏꜰ ᴛʜᴇꜱᴇ ᴄᴏɴᴛᴇɴᴛꜱ, ɪᴛ ᴏɴʟʏ ɪɴᴅᴇx ᴛʜᴇ ꜰɪʟᴇꜱ ꜰʀᴏᴍ ᴛᴇʟᴇɢʀᴀᴍ. </code> """
