class script(object):
    # ==========================================
    # 🏠 MAIN MENUS
    # ==========================================
    START_TXT = """<b>Hᴇʏ {mention} 👋🏻\n\nI ᴀᴍ {bname} 🤖\n\nA ᴘᴏᴡᴇʀꜰᴜʟ ᴀᴜᴛᴏ-ꜰɪʟᴛᴇʀ ʙᴏᴛ ᴛᴏ ꜱᴇᴀʀᴄʜ ᴍᴏᴠɪᴇꜱ ᴀɴᴅ ꜱᴇʀɪᴇꜱ ɪɴꜱᴛᴀɴᴛʟʏ!\n\nSᴇɴᴅ ᴍᴇ ᴀɴʏ ᴍᴏᴠɪᴇ ɴᴀᴍᴇ, ᴀɴᴅ I ᴡɪʟʟ ᴘʀᴏᴠɪᴅᴇ ᴛʜᴇ ꜰɪʟᴇꜱ.</b>"""

    HELP_TXT = """<b>Hᴇʏ {mention} 👋🏻\n\nCʜᴏᴏꜱᴇ ᴛʜᴇ ᴄᴀᴛᴇɢᴏʀʏ ʙᴇʟᴏᴡ ᴛᴏ ꜱᴇᴇ ᴀʟʟ ᴀᴠᴀɪʟᴀʙʟᴇ ᴄᴏᴍᴍᴀɴᴅꜱ ᴀɴᴅ ꜰᴇᴀᴛᴜʀᴇꜱ!</b>"""

    ABOUT_TXT = """<b>🤖 Nᴀᴍᴇ:</b> {bname}\n<b>👨‍💻 Dᴇᴠᴇʟᴏᴘᴇʀ:</b> <a href='https://t.me/KR_Picture'>KR Pɪᴄᴛᴜʀᴇ</a>\n<b>📺 Cʜᴀɴɴᴇʟ:</b> <a href='https://t.me/sandalwood_kannada_moviesz'>Sᴀɴᴅᴀʟᴡᴏᴏᴅ</a>\n<b>💬 Sᴜᴘᴘᴏʀᴛ:</b> <a href='https://t.me/Kannada_Filmy_Group'>Kᴀɴɴᴀᴅᴀ Fɪʟᴍʏ Gʀᴏᴜᴘ</a>"""

    STATUS_TXT = """<b>📊 Bᴏᴛ Dᴀᴛᴀʙᴀsᴇ Sᴛᴀᴛᴜs</b>\n\n<b>📁 Tᴏᴛᴀʟ Fɪʟᴇs:</b> <code>{}</code>\n<b>👤 Tᴏᴛᴀʟ Usᴇʀs:</b> <code>{}</code>\n<b>🏘 Tᴏᴛᴀʟ Cʜᴀᴛs:</b> <code>{}</code>\n<b>💾 Usᴇᴅ Sᴛᴏʀᴀɢᴇ:</b> <code>{}</code>\n<b>💿 Fʀᴇᴇ Sᴛᴏʀᴀɢᴇ:</b> <code>{}</code>"""

    LOG_TEXT_G = """<b>#Nᴇᴡ_Gʀᴏᴜᴘ</b>\n\n<b>Group Name:</b> <code>{}</code>\n<b>Group ID:</b> <code>{}</code>\n<b>Members:</b> <code>{}</code>\n<b>Added By:</b> {}"""

    LOG_TEXT_P = (
        """<b>#Nᴇᴡ_Usᴇʀ</b>\n\n<b>User ID:</b> <code>{}</code>\n<b>Profile:</b> {}"""
    )

    # ==========================================
    # 📝 FORMATTING GUIDE (Used in Help)
    # ==========================================
    FORMAT_GUIDE = """
<b>💡 Tᴇxᴛ Fᴏʀᴍᴀᴛᴛɪɴɢ Gᴜɪᴅᴇ:</b>
<i>Supports Markdown and HTML!</i>
• <code>**Bold**</code> ➔ **Bold**
• <code>__Italic__</code> ➔ __Italic__
• <code>~~Strike~~</code> ➔ ~~Strike~~
• <code>--Underline--</code> ➔ --Underline--
• <code>||Spoiler||</code> ➔ ||Spoiler||
• <code>`Mono`</code> ➔ `Mono`
• <code>> Quote</code> ➔ > Quote
• <code>[Link Text](http://url.com)</code> ➔ [Link Text](http://url.com)
"""

    # ==========================================
    # 👋 WELCOME SETTINGS
    # ==========================================
    WELCOME_TXT = f"""<b>👋 Wᴇʟᴄᴏᴍᴇ Mᴇssᴀɢᴇs (Gʀᴏᴜᴘ Aᴅᴍɪɴs)</b>

• <code>/enablewelcome</code> - Turn ON welcome messages.
• <code>/disablewelcome</code> - Turn OFF welcome messages.
• <code>/setwelcometxt &lt;text&gt;</code> - Set custom text.
<i>Variables: {{mention}}, {{title}}, {{count}}</i>
• <code>/setwelcomeimg</code> - Reply to an image to set it.
• <code>/setwelcome</code> - Reply to an image with a caption to set both!
• <code>/delwelcome</code> - Delete custom welcome settings.
{FORMAT_GUIDE}"""

    # ==========================================
    # 🖼️ IMAGE SETTINGS
    # ==========================================
    IMAGES_TXT = """<b>🖼️ Gʟᴏʙᴀʟ Iᴍᴀɢᴇs (Bᴏᴛ Aᴅᴍɪɴ)</b>

<b>Aᴜᴛᴏ-Fɪʟᴛᴇʀ Iᴍᴀɢᴇ</b>
• <code>/setautoimg</code> - Reply to an image to set a global default filter image.
• <code>/remautoimg</code> - Remove global default image.

<b>Fɪʟᴇ Nᴏᴛ Fᴏᴜɴᴅ Iᴍᴀɢᴇ</b>
• <code>/setfilenotfoundimg</code> - Reply to image to set FNF image.
• <code>/remfilenotfoundimg</code> - Remove FNF image.
• <code>/defaultfilenotfoundimg</code> - Reset to repo default.

<b>Fᴏʀᴄᴇ Sᴜʙsᴄʀɪʙᴇ Iᴍᴀɢᴇ</b>
• <code>/setfsubimg</code> - Reply to an image to set it as the Force Subscribe alert photo!"""

    # ==========================================
    # 🔍 SPELL CHECK & NOT FOUND
    # ==========================================
    SPELLCHECK_TXT = """<b>🔍 Sᴘᴇʟʟ Cʜᴇᴄᴋ & Nᴏᴛ Fᴏᴜɴᴅ</b>

<b>Sᴘᴇʟʟ Cʜᴇᴄᴋ & Sᴇᴀʀᴄʜ (Gʀᴏᴜᴘ Aᴅᴍɪɴs)</b>
‣ <code>/enablespellcheck</code> - Turn ON spelling suggestions.
‣ <code>/disablespellcheck</code> - Turn OFF spelling suggestions.

<b>Sᴛᴏᴘᴡᴏʀᴅs & Nᴏᴛ Fᴏᴜɴᴅ Tᴇxᴛ (Bᴏᴛ Aᴅᴍɪɴ)</b>
‣ <code>/addstopwords &lt;words&gt;</code> - Add words the bot should ignore (comma separated).
‣ /stopwords - Show Stop Words 
‣ /remstopwords - Remove Stop Word
‣ /remallstopwords - Remove All Stop Words
‣ /defaultstopwords - Make Default Words into available in repo
‣ <code>/setnotfoundtext &lt;text&gt;</code> - Set FNF text.
‣ <code>/remnotfoundtext</code> - Remove FNF text.
‣ <code>/defaultnotfoundtext</code> - Reset to repo default text."""

    # ==========================================
    # 📝 FILTERS (Auto & Manual)
    # ==========================================
    FILTERS_TXT = """<blockquote><b>Filter Management\nAdd, delete, or view filters to customize responses based on keywords.</b></blockquote>\n
<b>‣ /filter - Add a text filter (Reply `/filter keyword` to a message)
‣ /addfilter - Add a text filter from pre-made buttons
‣ /filterimage - Update only image for a filter (Reply to image with `/filterimage keyword`)
‣ /editfiltercolur - Change button colour - `/editfiltercolur keyword 1 green`
‣ /delfilter - Delete a text filter - /delfilter filter
‣ /listfilters - List all filters currently added in the bot\n\nSupports text/photo/video/animation/sticker</b>"""

    # ==========================================
    # 📱 FORCE SUBSCRIBE
    # ==========================================
    FORCESUB_TXT = """<blockquote><b>Force Subscription Management\nSet, manage, or clear force subscribe channels.</b></blockquote>\n
<b>‣ /enablefsub - enable force subscribe 
‣ /disablefsub - disable force subscribe 
‣ /setfsubcount - Set maximum Fsub chat count for queue
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

    # ==========================================
    # 👥 FORCE ADD
    # ==========================================
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

    # ==========================================
    # 🗑️ DELETE COMMANDS
    # ==========================================
    DELETE_TXT = """<blockquote><b>File/Auto Deletion Management\nDelete files from the database or configure auto-delete settings for files and button messages in groups.</b></blockquote>\n
<b>‣ /delete - Reply to a file to delete it from database
‣ /delmulti - Delete multiple files from database with name - /delmulti name
‣ /autodelete - Set file auto delete time in seconds
‣ /buttondel - Set button message in groups auto delete time in seconds</b>"""

    # ==========================================
    # 🚫 BANS & RESTRICTIONS
    # ==========================================
    BANS_TXT = """<blockquote><b>User Management\nBan or unban users to control access to the bot.</b></blockquote>\n
<b>‣ /ban - Ban a user from bot - /ban user_id
‣ /unban - Unban a user from bot - /unban user_id
‣ /bannedusers - Check Banned Users List
‣ /leave - Force bot to leave a chat 
‣ /enable - whitelist a group 
‣ /disable - blacklist a group</b>"""

    # ==========================================
    # 📝 CUSTOM CAPTION
    # ==========================================
    CUSTOMCAPTION_TXT = """<blockquote><b>File Caption Management\nManage or customize captions for files, including additional captions, to enhance file presentation.</b></blockquote>\n
<b>‣ /customcaption - Set custom caption for files (Reply to message to set, or `/customcaption off` to disable)
‣ /captionplus - Set additional caption for files along with main caption (Reply to message to set, or `/captionplus off` to disable)</b>

You can customize file captions by editing your Environment Variables.

<b>Vᴀʀɪᴀʙʟᴇs:</b>
• <code>{file_name}</code> - Name of the file
• <code>{file_size}</code> - Size of the file
• <code>{file_caption}</code> - Original caption"""

    CUSTOMMESSAGES_TXT = """<blockquote><b>Custom Messages & Images\nConfigure custom messages and images for various actions, such as file info, file deletion, file not found, or force subscription prompts.</b></blockquote>\n
<b>‣ /infomsg - Set info message before sending file
‣ /infoimg - Set info image before sending file
‣ /delmsg - Set delete message after sending file (File auto delete needs to be enabled)
‣ /delimg - Set delete image after sending file
‣ /notfoundmsg - Set message to send when file not found
‣ /notfoundimg - Set image to send when file not found
‣ /fsubmsg - Set force subscribe message
‣ /fsubimg - Set force subscribe image\n
*(Reply to a message/image with the command to set it, or use `off` to remove)*</b>"""

    # ==========================================
    # 📚 INDEXING (File Save)
    # ==========================================
    INDEX_TXT = """<b>📚 Iɴᴅᴇxɪɴɢ (Bᴏᴛ Aᴅᴍɪɴ)</b>

• <code>/index</code> (reply to file/msg) - Save single file to DB.
• <code>/batch</code> - Index entire channel in bulk.
• <code>/link</code> - Get shareable link for a file.
• <code>/total</code> - Count total indexed files.
• <code>/clearfiles</code> - ⚠️ Nuke entire file database!"""

    # ==========================================
    # 📢 PROMOTIONS & BROADCAST
    # ==========================================

    PROMOTIONS_TXT = """<blockquote><b>Manage Promotional Links\nEasily add, delete, or view promotional links displayed between search results.</b></blockquote>\n
<b>‣ /addpromo - Set promotional links between results - /addpromo "Button Text" URL
‣ /delpromo - Delete promotional links between results - /delpromo URL
‣ /listpromos - List all promotional links currently added in the DB

💬 Bʀᴏᴀᴅᴄᴀsᴛɪɴɢ (Aᴜᴛᴏ-ᴅᴇʟᴇᴛᴇs ɪɴ 24ʜ)
‣ /broadcast - send to all users 
‣ /group_broadcasr - send to all grous</b>"""

    # ==========================================
    # ⚙️ SETTINGS & CONNECTIONS
    # ==========================================
    SETTINGS_TXT = """<blockquote><b>Bot Settings Management</b></blockquote>\n
<b>‣ /repairmode - Enable or disable repair mode - If on, bot will not send any files
‣ /adminsettings - Get current admin settings</b>"""

    CONNECTIONS_TXT = """<blockquote><b>𝗖𝗼𝗺𝗺𝗮𝗻𝗱𝘀 𝗮𝗻𝗱 𝗨𝘀𝗮𝗴𝗲\nUsed to connect bot to PM for managing filters, avoiding spamming in groups.</b></blockquote>\n
<b>‣ /connect  - Connect a particular chat to your PM
‣ /disconnect  - Disconnect from a chat
‣ /connections - List all your connections</b>"""

    # ==========================================
    # 📊 UTILITIES & BACKUP
    # ==========================================

    UTILITIES_TXT = """<blockquote><b>Utility Commands\nAccess bot logs, server stats, restart the bot, get user and file counts, send broadcasts, and more.</b></blockquote>\n
<b>‣ /channels - List all connected groups and channels (15 per page)
‣ /leavechannel - Leave a channel or group by ID
‣ /logs - Get logs as a file
‣ /server - Get server stats
‣ /restart - Restart the bot
‣ /stats - Database statistics
‣ /broadcast - Reply to a message to send that to all bot users
‣ /total - Get count of total files in DB
‣ /clearfiles - Clear all files from DB
‣ /clearusers - Clear all users from DB
‣ /cleanusers - Ping all users to purge deleted accounts
‣ /clearfsubusers - Clear all force subscribe users from db</b>"""

    BACKUP_TXT = """<blockquote><b>Database Backup Management\nManage database backups, including scheduled backups and manual backups.</b></blockquote>\n
<b>These commands are only available for the ADMINS of the bot.</b>\n
<b>‣ /dbbackup - Generate full JSON backup of your database.
‣ /dbrestore - (reply to .json file) - Restore database from file.
‣ /dbstats - Detailed MongoDB specs.
‣ /dbschedule - Start 24h automated backup cron job.</b>"""

    POSTHAND_TXT = """<b>📝 POST HANDLER GUIDE

[ CREATE / EDIT ]
‣ /post [Movie] - TMDB post
‣ /editpost [Link] - Edit channel post

[ FORMATTING ] 
*(Send 'blank' to remove field)*
‣ /edittitle [Title]
‣ /edityear [Year]
‣ /editlangs [Langs]
‣ /editresolutions [Qualities]
‣ /editgenres [Genres]
‣ /editotts [OTTs]

[ BUTTONS / IMAGES ]
‣ /editbuttoncolour [No] [Color] - green/red/blue
‣ /editdirect [URL] - Direct link
‣ /editimage - Preview image
‣ /editnormalimage - Native photo</b>"""

    POSTHAND_TXT = """<b>📝 Pᴏsᴛ Hᴀɴᴅʟᴇ (Bᴏᴛ Aᴅᴍɪɴ)</b>

• <code>/channels</code> - Interactive menu of all connected channels/groups.
• <code>/leavechannel &lt;id&gt;</code> - Force leave and scrub a channel from DB.
• <code>/exportusers</code> - Download .txt list of all users.
• <code>/exportgroups</code> - Download .txt list of all groups.
• <code>/exportchannels</code> - Download .txt list of all channels."""
