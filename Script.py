class script(object):
    START_TXT = """<b>Hey {mention} bro 🥂,\nI'm {bname}, the Moviebot! \n \nJoin our gang — We've got Movies hotter than your ex's new filing 😊🎬</b>"""

    HELP_TXT = """<b>You can find the bot commands here.\n \n‣ /help - Show this help message\n \n<blockquote>Tap on corresponding modules to get the commands of that module.</blockquote></b>"""

    ABOUT_TXT = """<b>○ 𝗠𝘆 𝗡𝗮𝗺𝗲 : {bname}
○ 𝗖𝗿𝗲𝗮𝘁𝗼𝗿 : <a href="https://t.me/SandalwoodSupportBot"><b>Sandalwood Support</b></a>
○ 𝗟𝗶𝗯𝗿𝗮𝗿𝘆 : 𝙿𝚈𝚁𝙾𝙶𝚁𝙰𝙼
○ 𝗟𝗮𝗻𝗴𝘂𝗮𝗴𝗲 : 𝙿𝚈𝚃𝙷𝙾𝙽 𝟹.10
○ 𝗗𝗮𝘁𝗮𝗕𝗮𝘀𝗲 : 𝙼𝙾𝙽𝙶𝙾 𝙳𝙱
○ 𝗕𝘂𝗶𝗹𝗱 𝗩𝗲𝗿𝘀𝗶𝗼𝗻 : V2.0 [ 𝙱𝙴𝚃𝙰 ]</b>"""

    SOURCE_TXT = """<b>Source Code Of This Bot is Private 😊</b>"""

    BANS_TXT = """<b><blockquote>User Management\nBan or unban users to control access to the bot.</blockquote>\n \n‣ /ban - Ban a user from bot - /ban user_id\n‣ /unban - Unban a user from bot - /unban user_id</b>"""

    CUSTOMMESSAGES_TXT = """<b><blockquote>Custom Messages & Images\nConfigure custom messages and images for various actions, such as file info, file deletion, file not found, or force subscription prompts.</blockquote>\n
‣ /infomsg - Set info message before sending file - Reply /infomsg to a message to set or /infomsg off to remove
‣ /infoimg - Set info image before sending file - Reply /infoimg to an image to set or /infoimg off to remove
‣ /delmsg - Set delete message after sending file (File auto delete needs to be enabled to work) - Reply /delmsg to a message to set or /delmsg off to remove
‣ /delimg - Set delete image after sending file (File auto delete needs to be enabled to work) - Reply /delimg to an image to set or /delimg off to remove
‣ /notfoundmsg - Set message to send when file not found - Reply /notfoundmsg to a message to set or /notfoundmsg off to remove
‣ /notfoundimg - Set image to send when file not found - Reply /notfoundimg to an image to set or /notfoundimg off to remove
‣ /fsubmsg - Set force subscribe message - Reply /fsubmsg to a message to set or /fsubmsg off to remove
‣ /fsubimg - Set force subscribe image - Reply /fsubimg to an image to set or /fsubimg off to remove</b>"""

    CUSTOMCAPTION_TXT = """<b><blockquote>File Caption Management\nManage or customize captions for files, including additional captions, to enhance file presentation.</blockquote>\n
‣ /customcaption - Set custom caption for files - Reply /customcaption to a message to set or /customcaption off to disable.
‣ /captionplus - Set additional caption for files along with caption - Reply /captionplus to a message to set or /captionplus off to disable.</b>"""

    DELETE_TXT = """<b><blockquote>File/Auto Deletion Management\nDelete files from the database or configure auto-delete settings for files and button messages in groups.</blockquote>\n
‣ /delete - Reply to a file to delete it from database
‣ /delmulti - Delete multiple files from database with name - /delmulti name
‣ /autodelete - Set file auto delete time in seconds
‣ /buttondel - Set button message in groups auto delete time in seconds</b>"""

    FORCESUB_TXT = """<b><blockquote>Force Subscription Management\nSet, manage, or clear force subscribe channels.</blockquote>\n
‣ /setfsubcount - Set maximum Fsub chat count for queue (If not set, queued FSub will be activated instantly)
‣ /setfsub - Set force subscribe channel - /setfsub channel_id (Answer the questions after that) Bot must be admin of that channel (Bot will create a new invite link)
‣ /rmfsub - Remove force subscribe channel - /rmfsub channel_id
‣ /rmallfsub - Remove all force subscribe channels
‣ /getallfsub - Get all force subscribe channel details
‣ /getactivefsub - Get active force subscribe channels
‣ /getpendingfsub - Get pending force subscribe channels which is in queue
‣ /activatefsub - Activate pending force subscribe channel - /activatefsub channel_id
‣ /deactivatefsub - Deactivate force subscribe channel - /deactivatefsub channel_id
‣ /updatefsubtarget - Update force subscribe channel target - /updatefsubtarget channel_id target
‣ /checkfsubusers - Check force subscribe users count
‣ /clearfsubusers - Clear all force subscribe users from db</b>"""

    FILTERS_TXT = """<b><blockquote>Filter Management\nAdd, delete, or view filters to customize responses based on keywords.</blockquote>\n
‣ /filter - Add a text filter - Reply /filter keyword to a message to set (Supports custom button formats).
‣ /addfilter - (Only for messages with pre made buttons) Add a text filter - Reply /addfilter keyword to a message to set (If a filter is there, bot will send the filter rather than file)
‣ /delfilter - Delete a text filter - /delfilter filter
‣ /listfilters - List all filters currently added in the bot\n \nSupports text/photo/video/animation/sticker</b>"""

    INDEX_TXT = """<b><blockquote>Database Indexing\nIndex a database channel by forwarding messages or using links. Supports private channels if the bot is an admin.</blockquote>\n
‣ /index - Start indexing a database channel (bot must be admin of the channel if that is private channel)
You can just forward the message from database channel for starting indexing, no need to use the /index command.
‣ /indexlink - Start indexing a database channel using link (bot must be admin of the channel if that is private channel)
/indexlink last_message_link or /indexlink start_message_link last_message_link</b>"""

    PROMOTIONS_TXT = """<b><blockquote>Manage Promotional Links\nEasily add, delete, or view promotional links displayed between search results.</blockquote>\n
‣ /addpromo - Set promotional links between results - /addpromo "Button Text" URL
‣ /delpromo - Delete promotional links between results - /delpromo URL
‣ /listpromos - List all promotional links currently added in the DB</b>"""

    SETTINGS_TXT = """<b><blockquote>Bot Settings Management</blockquote>\n
‣ /repairmode - Enable or disable repair mode - If on, bot will not send any files
‣ /adminsettings - Get current admin settings</b>"""

    UTILITIES_TXT = """<b><blockquote>Utility Commands\nAccess bot logs, server stats, restart the bot, get user and file counts, send broadcasts, and more.</blockquote>\n
‣ /logs - Get logs as a file
‣ /server - Get server stats
‣ /restart - Restart the bot
‣ /stats - Get bot user stats (Will send only after checking active users)
‣ /broadcast - Reply to a message to send that to all bot users
‣ /total - Get count of total files in DB
‣ /clearfiles - Clear all files from DB
‣ /clearusers - Clear all users from DB
‣ /clearfsubusers - Clear all force subscribe users from db</b>"""

    CONNECTIONS_TXT = """<b><blockquote>𝗖𝗼𝗺𝗺𝗮𝗻𝗱𝘀 𝗮𝗻𝗱 𝗨𝘀𝗮𝗴𝗲\n - Used to connect bot to PM for managing filters\n- it helps to avoid spamming in groups.</blockquote>\n
‣ /connect  - Connect a particular chat to your PM
‣ /disconnect  - Disconnect from a chat
‣ /connections - List all your connections</b>"""

    FORCEADD_TXT = """<b><blockquote>ForceAdd Management</blockquote>\n

‣ /setforceadd - Set a Force Add channel for the group.
‣ /remforceadd - Remove the current Force Add channel.
‣ /getforceadd - View the configured Force Add channel.
‣ /topaddall - Show the all-time top inviters leaderboard.
‣ /topadd24 - Show the top inviters in the last 24 hours.
‣ /topadd7 - Show the top inviters from the last 7 days.
‣ /resetadddaily - Reset today's add statistics.
‣ /resetadd - Reset all Force Add statistics.
‣ /myadds - Check your personal add count and ranking.</b>"""

    BACKUP_TXT = """<b><blockquote>Database Backup Management\nManage database backups, including scheduled backups and manual backups.</blockquote>\n \nThese commands are only available for the ADMINS of the bot.\n
‣ /dbbackup - Backup the database
‣ /dbrestore - Restore the database
‣ /dbstats - Get database stats
‣ /dbschedule - Get scheduled backup status</b>"""

    MANUELFILTER_TXT = """𝗙𝗶𝗹𝘁𝗲𝗿𝘀

- Filter is the feature where users can set automated replies for a particular keyword and I will respond whenever a keyword is found in the message.

<blockquote>𝗡𝗼𝘁𝗲:
1. I should have Admin Privilege.
2. Only Admins can add Filters in a Chat.
3. Alert buttons have a limit of 64 characters.</blockquote>

<blockquote>𝗖𝗼𝗺𝗺𝗮𝗻𝗱𝘀 𝗮𝗻𝗱 𝗨𝘀𝗮𝗴𝗲:</blockquote>

• /filter - add a filter in chat
• /filters - list all the filters of a chat
• /del - delete a specific filter in chat
• /delall - delete the whole filters in a chat (chat ADMINS only)"""

    BUTTON_TXT = """𝗕𝘂𝘁𝘁𝗼𝗻𝘀

- I support both url and alert inline buttons.

<blockquote>𝗡𝗼𝘁𝗲:
1. Telegram will not allow you to send buttons without any content, so content is mandatory.
2. I support buttons with any telegram media type.
3. Buttons should be properly parsed as markdown format</blockquote>

URL buttons:
[Button Text](buttonurl:https://t.me/KR_PICTURE)

Alert buttons:
[Button Text](buttonalert:This is an alert message)"""

    AUTOFILTER_TXT = """𝗔𝘂𝘁𝗼 𝗙𝗶𝗹𝘁𝗲𝗿

<blockquote>𝗡𝗼𝘁𝗲:
    𝗧𝗵𝗶𝘀 𝗺𝗼𝗱𝘂𝗹𝗲 𝗼𝗻𝗹𝘆 𝘄𝗼𝗿𝗸𝘀 𝗳𝗼𝗿 𝗺𝘆 𝗔𝗱𝗺𝗶𝗻𝘀</blockquote>
    
1. Make me the admin of your channel if it's private.
2. Make sure that your channel does not contain camrips, porn, and fake files.
3. Forward the last message to me with quotes.
I'll add all the files in that channel to my db."""

    CONNECTION_TXT = """𝗖𝗼𝗻𝗻𝗲𝗰𝘁𝗶𝗼𝗻𝘀

- Used to connect bot to PM for managing filters. 
- It helps to avoid spamming in groups.

<blockquote>𝗡𝗼𝘁𝗲:
1. Only Group Admins can add a connection.
2. Send /connect for connecting me to your PM</blockquote>

𝗖𝗼𝗺𝗺𝗮𝗻𝗱𝘀 𝗮𝗻𝗱 𝗨𝘀𝗮𝗴𝗲:

• /connect - Connect a particular chat to your PM
• /disconnect - Disconnect from a chat
• /connections - List all your connections"""

    FRSUB_TXT = """Help:  𝗙𝗼𝗿𝗰𝗲𝗦𝘂𝗯 𝗠𝗼𝗱𝗲

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

• /logs - to get the recent errors
• /stats - to get status of files in db.
• /restart - Restart Bot
• /delete - to delete a specific file from db.
• /users - to get list of my users and ids.
• /ban - to ban a user.
• /unban - to unban a user.
• /chats - to get list of Groups
• /channel - to get list of total connected channels
• /broadcast - to broadcast a message to all users
• /group_broadcast - to broadcast a message to all saved Groups"""

    ADMIN_TXT = """Help: <b>Admin mods</b>

<b>NOTE:</b>
This module only works for my admins

<b>Commands and Usage:</b>
• /logs - <code>to get the recent errors</code>
• /stats - <code>to get status of files in db.</code>
• /delete - <code>to delete a specific file from db.</code>
• /users - <code>to get list of my users and ids.</code>
• /chats - <code>to get list of the my chats and ids</code>
• /leave - <code>to leave from a chat.</code>
• /disable - <code>to disable a chat.</code>
• /ban - <code>to ban a user.</code>
• /unban - <code>to unban a user.</code>
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

    DICS_TXT = """<b><code>ᴛʜɪꜱ ɪꜱ ᴀɴ ᴏᴘᴇɴ ꜱᴏᴜʀᴄᴇ ᴘʀᴏᴊᴇᴄᴛ.

ᴀʟʟ ᴛʜᴇ ꜰɪʟᴇꜱ ɪɴ ᴛʜɪꜱ ʙᴏᴛ ᴀʀᴇ ꜰʀᴇᴇʟʏ ᴀᴠᴀɪʟᴀʙʟᴇ ᴏɴ ᴛʜᴇ ɪɴᴛᴇʀɴᴇᴛ ᴏʀ ᴘᴏꜱᴛᴇᴅ ʙʏ ꜱᴏᴍᴇʙᴏᴅʏ ᴇʟꜱᴇ. 
ᴊᴜꜱᴛ ꜰᴏʀ ᴇᴀꜱʏ ꜱᴇᴀʀᴄʜɪɴɢ ᴛʜɪꜱ ʙᴏᴛ ɪꜱ ɪɴᴅᴇxɪɴɢ ꜰɪʟᴇꜱ ᴡʜɪᴄʜ ᴀʀᴇ ᴀʟʀᴇᴀᴅʏ ᴜᴘʟᴏᴀᴅᴇᴅ ᴏɴ ᴛᴇʟᴇɢʀᴀᴍ. 
ᴡᴇ ʀᴇꜱᴘᴇᴄᴛ ᴀʟʟ ᴛʜᴇ ᴄᴏᴘʏʀɪɢʜᴛ ʟᴀᴡꜱ ᴀɴᴅ ᴡᴏʀᴋꜱ ɪɴ ᴄᴏᴍᴘʟɪᴀɴᴄᴇ ᴡɪᴛʜ ᴅᴍᴄᴀ ᴀɴᴅ ᴇᴜᴄᴅ. 
ɪꜰ ᴀɴʏᴛʜɪɴɢ ɪꜱ ᴀɢᴀɪɴꜱᴛ ʟᴀᴡ ᴘʟᴇᴀꜱᴇ ᴄᴏɴᴛᴀᴄᴛ ᴍᴇ ꜱᴏ ᴛʜᴀᴛ ɪᴛ ᴄᴀɴ ʙᴇ ʀᴇᴍᴏᴠᴇᴅ ᴀꜱᴀᴘ. 
ɪᴛ ɪꜱ ꜰᴏʀʙɪᴅᴅᴇɴ ᴛᴏ ᴅᴏᴡɴʟᴏᴀᴅ, ꜱᴛʀᴇᴀᴍ, ʀᴇᴘʀᴏᴅᴜᴄᴇ, ᴏʀ ʙʏ ᴀɴʏ ᴍᴇᴀɴꜱ, ꜱʜᴀʀᴇ, ᴏʀ ᴄᴏɴꜱᴜᴍᴇ, ᴄᴏɴᴛᴇɴᴛ ᴡɪᴛʜᴏᴜᴛ ᴇxᴘʟɪᴄɪᴛ ᴘᴇʀᴍɪꜱꜱɪᴏɴ ꜰʀᴏᴍ ᴛʜᴇ ᴄᴏɴᴛᴇɴᴛ ᴄʀᴇᴀᴛᴏʀ ᴏʀ ʟᴇɢᴀʟ ᴄᴏᴘʏʀɪɢʜᴛ ʜᴏʟᴅᴇʀ. 
ɪꜰ ʏᴏᴜ ʙᴇʟɪᴇᴠᴇ ᴛʜɪꜱ ʙᴏᴛ ɪꜱ ᴠɪᴏʟᴀᴛɪɴɢ ʏᴏᴜʀ ɪɴᴛᴇʟʟᴇᴄᴛᴜᴀʟ ᴘʀᴏᴘᴇʀᴛʏ, ᴄᴏɴᴛᴀᴄᴛ ᴛʜᴇ ʀᴇꜱᴘᴇᴄᴛɪᴠᴇ ᴄʜᴀɴɴᴇʟꜱ ꜰᴏʀ ʀᴇᴍᴏᴠᴀʟ. 
ᴛʜᴇ ʙᴏᴛ ᴅᴏᴇꜱ ɴᴏᴛ ᴏᴡɴ ᴀɴʏ ᴏꜰ ᴛʜᴇꜱᴇ ᴄᴏɴᴛᴇɴᴛꜱ, ɪᴛ ᴏɴʟʏ ɪɴᴅᴇx ᴛʜᴇ ꜰɪʟᴇꜱ ꜰʀᴏᴍ ᴛᴇʟᴇɢʀᴀᴍ.</code></b>"""
