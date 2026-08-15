class script(object):
    START_TXT = """<b>Hey {mention} bro 🥂,\nI'm {bname}, the Moviebot! \n\nJoin our gang — We've got Movies hotter than your ex's new filing 😊🎬</b>"""

    HELP_TXT = """<b>You can find the bot commands here.\n\n‣ /help - Show this help message</b>\n\n<blockquote><b>Tap on corresponding modules to get the commands of that module.</b></blockquote>"""

    ABOUT_TXT = """<b>○ 𝗠𝘆 𝗡𝗮𝗺𝗲 : {bname}
○ 𝗖𝗿𝗲𝗮𝘁𝗼𝗿 : <a href="https://t.me/SandalwoodSupportBot">Sandalwood Support</a>
○ 𝗟𝗶𝗯𝗿𝗮𝗿𝘆 : 𝙿𝚈𝚁𝙾𝙶𝚁𝙰𝙼
○ 𝗟𝗮𝗻𝗴𝘂𝗮𝗴𝗲 : 𝙿𝚈𝚃𝙷𝙾𝙽 𝟹.10
○ 𝗗𝗮𝘁𝗮𝗕𝗮𝘀𝗲 : 𝙼𝙾𝙽𝙶𝙾 𝙳𝙱
○ 𝗕𝘂𝗶𝗹𝗱 𝗩𝗲𝗿𝘀𝗶𝗼𝗻 : V2.0 [ 𝙱𝙴𝚃𝙰 ]</b>"""

    PRVCY_TXT = """<b>Hey {mention} ⚓

➡️ Your Request Has Been Deleted To Safeguard Your Privacy!

➡️ Thank You For Using @KR_PICTURE</b>"""

    SOURCE_TXT = """<b>Source Code Of This Bot is Private 😊</b>"""

    BANS_TXT = """<blockquote><b>User Management\nBan or unban users to control access to the bot.</b></blockquote>\n
<b>‣ /ban - Ban a user from bot - /ban user_id
‣ /unban - Unban a user from bot - /unban user_id
‣ /bannedusers - Check Banned Users List</b>"""

    CUSTOMMESSAGES_TXT = """<blockquote><b>Custom Messages & Images\nConfigure custom messages and images for various actions, such as file info, file deletion, file not found, or force subscription prompts.</b></blockquote>\n
<b>‣ /infomsg - Set info message before sending file
‣ /infoimg - Set info image before sending file
‣ /delmsg - Set delete message after sending file (File auto delete needs to be enabled)
‣ /delimg - Set delete image after sending file
‣ /notfoundmsg - Set message to send when file not found
‣ /notfoundimg - Set image to send when file not found
‣ /fsubmsg - Set force subscribe message
‣ /fsubimg - Set force subscribe image\n
*(Reply to a message/image with the command to set it, or use `<command> off` to remove)*</b>"""

    CUSTOMCAPTION_TXT = """<blockquote><b>File Caption Management\nManage or customize captions for files, including additional captions, to enhance file presentation.</b></blockquote>\n
<b>‣ /customcaption - Set custom caption for files (Reply to message to set, or `/customcaption off` to disable)
‣ /captionplus - Set additional caption for files along with main caption (Reply to message to set, or `/captionplus off` to disable)</b>"""

    DELETE_TXT = """<blockquote><b>File/Auto Deletion Management\nDelete files from the database or configure auto-delete settings for files and button messages in groups.</b></blockquote>\n
<b>‣ /delete - Reply to a file to delete it from database
‣ /delmulti - Delete multiple files from database with name - /delmulti name
‣ /autodelete - Set file auto delete time in seconds
‣ /buttondel - Set button message in groups auto delete time in seconds</b>"""

    FORCESUB_TXT = """<blockquote><b>Force Subscription Management\nSet, manage, or clear force subscribe channels.</b></blockquote>\n
<b>‣ /setfsubcount - Set maximum Fsub chat count for queue
‣ /setfsub - Set force subscribe channel - /setfsub channel_id
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

    FILTERS_TXT = """<blockquote><b>Filter Management\nAdd, delete, or view filters to customize responses based on keywords.</b></blockquote>\n
<b>‣ /filter - Add a text filter (Reply `/filter keyword` to a message)
‣ /addfilter - Add a text filter from pre-made buttons
‣ /delfilter - Delete a text filter - /delfilter filter
‣ /listfilters - List all filters currently added in the bot\n\nSupports text/photo/video/animation/sticker</b>"""

    INDEX_TXT = """<blockquote><b>Database Indexing\nIndex a database channel by forwarding messages or using links. Supports private channels if the bot is an admin.</b></blockquote>\n
<b>‣ /index - Start indexing a database channel
You can just forward the message from database channel for starting indexing, no need to use the /index command.
‣ /indexlink - Start indexing a database channel using link</b>"""

    PROMOTIONS_TXT = """<blockquote><b>Manage Promotional Links\nEasily add, delete, or view promotional links displayed between search results.</b></blockquote>\n
<b>‣ /addpromo - Set promotional links between results - /addpromo "Button Text" URL
‣ /delpromo - Delete promotional links between results - /delpromo URL
‣ /listpromos - List all promotional links currently added in the DB</b>"""

    SETTINGS_TXT = """<blockquote><b>Bot Settings Management</b></blockquote>\n
<b>‣ /repairmode - Enable or disable repair mode - If on, bot will not send any files
‣ /adminsettings - Get current admin settings</b>"""

    UTILITIES_TXT = """<blockquote><b>Utility Commands\nAccess bot logs, server stats, restart the bot, get user and file counts, send broadcasts, and more.</b></blockquote>\n
<b>‣ /logs - Get logs as a file
‣ /server - Get server stats
‣ /restart - Restart the bot
‣ /stats - Get bot user stats
‣ /broadcast - Reply to a message to send that to all bot users
‣ /total - Get count of total files in DB
‣ /clearfiles - Clear all files from DB
‣ /clearusers - Clear all users from DB
‣ /clearfsubusers - Clear all force subscribe users from db</b>"""

    CONNECTIONS_TXT = """<blockquote><b>𝗖𝗼𝗺𝗺𝗮𝗻𝗱𝘀 𝗮𝗻𝗱 𝗨𝘀𝗮𝗴𝗲\nUsed to connect bot to PM for managing filters, avoiding spamming in groups.</b></blockquote>\n
<b>‣ /connect  - Connect a particular chat to your PM
‣ /disconnect  - Disconnect from a chat
‣ /connections - List all your connections</b>"""

    FORCEADD_TXT = """<blockquote><b>ForceAdd Management</b></blockquote>\n
<b>‣ /setforceadd - Set a Force Add channel for the group.
‣ /remforceadd - Remove the current Force Add channel.
‣ /getforceadd - View the configured Force Add channel.
‣ /topaddall - Show the all-time top inviters leaderboard.
‣ /topadd24 - Show the top inviters in the last 24 hours.
‣ /topadd7 - Show the top inviters from the last 7 days.
‣ /resetadddaily - Reset today's add statistics.
‣ /resetadd - Reset all Force Add statistics.
‣ /myadds - Check your personal add count and ranking.</b>"""

    BACKUP_TXT = """<blockquote><b>Database Backup Management\nManage database backups, including scheduled backups and manual backups.</b></blockquote>\n
<b>These commands are only available for the ADMINS of the bot.</b>\n
<b>‣ /dbbackup - Backup the database
‣ /dbrestore - Restore the database
‣ /dbstats - Get database stats
‣ /dbschedule - Get scheduled backup status</b>"""

    POSTHAND_TXT = """<b><blockquote>POST_HANDLER.PY - COMMAND REFERENCE GUIDE\n \n POST CREATION & EDITING </blockquote>

/post <Movie Name>
    - Creates a brand new movie post session by fetching data from TMDB.
/editpost <Channel Post Link>
    - Imports an existing post from your channel so you can edit its 
      caption, buttons, or image, and re-publish it over the original message.

<blockquote>TEXT & FORMATTING CONTROLS </blockquote>
* Pro Tip: Type 'blank' instead of a value to completely delete that line!

/edittitle <New Title>
    - Overrides the TMDB movie title. (Ex: /edittitle Kantara)
      To remove completely: /edittitle blank
/edityear <New Year>
    - Overrides the release year. (Ex: /edityear 2022)
      To remove completely: /edityear blank
/editlangs <Languages>
    - Updates the Languages line. (Ex: /editlangs Kannada, Hindi)
      To remove completely: /editlangs blank
/editresolutions <Resolutions>
    - Updates the Resolutions line. (Ex: /editresolutions 1080p, 720p)
      To remove completely: /editresolutions blank
/editgenres <Genres>
    - Updates the Genres line. (Ex: /editgenres Action, Drama)
      To remove completely: /editgenres blank
/editotts <OTT Platforms>
    - Updates the OTT line. (Ex: /editotts Netflix, Prime)
      To remove completely: /editotts blank

<blockquote> BUTTON & IMAGE CONTROLS </blockquote>

/editbuttoncolour <Button Number> <Colour>
    - Changes the color of a specific button. 
    - Available Colours: green, red, blue
    - Example: /editbuttoncolour 1 red
/editdirect <URL>
    - Updates the destination link of the "Direct Search 🔎" button.
      To remove the button entirely: /editdirect blank
/editimage
    - Changes the rich preview image. The bot will pause and ask you 
      to send a photo or a direct URL.
    - Send '/reset' to restore the original TMDB poster.
    - Send 'blank' to completely remove the image preview.
/editnormalimage 
    - Edit Image Sending Normal Image Without Preview & Telegraph Image
    - Send '/reset' to restore the original TMDB poster.
    - Send 'blank' to completely remove the image.</b>"""

    STATUS_TXT = """<b>★ 𝚃𝙾𝚃𝙰𝙻 𝙵𝙸𝙻𝙴𝚂:</b> <code>{}</code>
<b>★ 𝚃𝙾𝚃𝙰𝙻 𝚄𝚂𝙴𝚁𝚂:</b> <code>{}</code>
<b>★ 𝚃𝙾𝚃𝙰𝙻 𝙲𝙷𝙰𝚃𝚂:</b> <code>{}</code>
<b>★ 𝚄𝚂𝙴𝙳 𝚂𝚃𝙾𝚁𝙰𝙶𝙴:</b> <code>{}</code> <b>𝙼𝚒𝙱</b>
<b>★ 𝙵𝚁𝙴𝙴 𝚂𝚃𝙾𝚁𝙰𝙶𝙴:</b> <code>{}</code> <b>𝙼𝚒𝙱</b>"""

    LOG_TEXT_G = """#NewGroup
Group = {}(<code>{}</code>)
Total Members = <code>{}</code>
Added By - {}"""

    LOG_TEXT_P = """#NewUser
ID - <code>{}</code>
Name - {}"""

    DICS_TXT = """<b><code>ᴛʜɪꜱ ɪꜱ ᴀɴ ᴏᴘᴇɴ ꜱᴏᴜʀᴄᴇ ᴘʀᴏᴊᴇᴄᴛ.

ᴀʟʟ ᴛʜᴇ ꜰɪʟᴇꜱ ɪɴ ᴛʜɪꜱ ʙᴏᴛ ᴀʀᴇ ꜰʀᴇᴇʟʏ ᴀᴠᴀɪʟᴀʙʟᴇ ᴏɴ ᴛʜᴇ ɪɴᴛᴇʀɴᴇᴛ ᴏʀ ᴘᴏꜱᴛᴇᴅ ʙʏ ꜱᴏᴍᴇʙᴏᴅʏ ᴇʟꜱᴇ. 
ᴊᴜꜱᴛ ꜰᴏʀ ᴇᴀꜱʏ ꜱᴇᴀʀᴄʜɪɴɢ ᴛʜɪꜱ ʙᴏᴛ ɪꜱ ɪɴᴅᴇxɪɴɢ ꜰɪʟᴇꜱ ᴡʜɪᴄʜ ᴀʀᴇ ᴀʟʀᴇᴀᴅʏ ᴜᴘʟᴏᴀᴅᴇᴅ ᴏɴ ᴛᴇʟᴇɢʀᴀᴍ. 
ᴡᴇ ʀᴇꜱᴘᴇᴄᴛ ᴀʟʟ ᴛʜᴇ ᴄᴏᴘʏʀɪɢʜᴛ ʟᴀᴡꜱ ᴀɴᴅ ᴡᴏʀᴋꜱ ɪɴ ᴄᴏᴍᴘʟɪᴀɴᴄᴇ ᴡɪᴛʜ ᴅᴍᴄᴀ ᴀɴᴅ ᴇᴜᴄᴅ. 
ɪꜰ ᴀɴʏᴛʜɪɴɢ ɪꜱ ᴀɢᴀɪɴꜱᴛ ʟᴀᴡ ᴘʟᴇᴀꜱᴇ ᴄᴏɴᴛᴀᴄᴛ ᴍᴇ ꜱᴏ ᴛʜᴀᴛ ɪᴛ ᴄᴀɴ ʙᴇ ʀᴇᴍᴏᴠᴇᴅ ᴀꜱᴀᴘ. 
ɪᴛ ɪꜱ ꜰᴏʀʙɪᴅᴅᴇɴ ᴛᴏ ᴅᴏᴡɴʟᴏᴀᴅ, ꜱᴛʀᴇᴀᴍ, ʀᴇᴘʀᴏᴅᴜᴄᴇ, ᴏʀ ʙʏ ᴀɴʏ ᴍᴇᴀɴꜱ, ꜱʜᴀʀᴇ, ᴏʀ ᴄᴏɴꜱᴜᴍᴇ, ᴄᴏɴᴛᴇɴᴛ ᴡɪᴛʜᴏᴜᴛ ᴇxᴘʟɪᴄɪᴛ ᴘᴇʀᴍɪꜱꜱɪᴏɴ ꜰʀᴏᴍ ᴛʜᴇ ᴄᴏɴᴛᴇɴᴛ ᴄʀᴇᴀᴛᴏʀ ᴏʀ ʟᴇɢᴀʟ ᴄᴏᴘʏʀɪɢʜᴛ ʜᴏʟᴅᴇʀ. 
ɪꜰ ʏᴏᴜ ʙᴇʟɪᴇᴠᴇ ᴛʜɪꜱ ʙᴏᴛ ɪꜱ ᴠɪᴏʟᴀᴛɪɴɢ ʏᴏᴜʀ ɪɴᴛᴇʟʟᴇᴄᴛᴜᴀʟ ᴘʀᴏᴘᴇʀᴛʏ, ᴄᴏɴᴛᴀᴄᴛ ᴛʜᴇ ʀᴇꜱᴘᴇᴄᴛɪᴠᴇ ᴄʜᴀɴɴᴇʟꜱ ꜰᴏʀ ʀᴇᴍᴏᴠᴀʟ. 
ᴛʜᴇ ʙᴏᴛ ᴅᴏᴇꜱ ɴᴏᴛ ᴏᴡɴ ᴀɴʏ ᴏꜰ ᴛʜᴇꜱᴇ ᴄᴏɴᴛᴇɴᴛꜱ, ɪᴛ ᴏɴʟʏ ɪɴᴅᴇx ᴛʜᴇ ꜰɪʟᴇꜱ ꜰʀᴏᴍ ᴛᴇʟᴇɢʀᴀᴍ.</code></b>"""
