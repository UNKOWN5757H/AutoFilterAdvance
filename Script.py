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
• <code>/enablespellcheck</code> - Turn ON spelling suggestions.
• <code>/disablespellcheck</code> - Turn OFF spelling suggestions.

<b>Sᴛᴏᴘᴡᴏʀᴅs & Nᴏᴛ Fᴏᴜɴᴅ Tᴇxᴛ (Bᴏᴛ Aᴅᴍɪɴ)</b>
• <code>/addstopwords &lt;words&gt;</code> - Add words the bot should ignore (comma separated).
• <code>/setnotfoundtext &lt;text&gt;</code> - Set FNF text.
• <code>/remnotfoundtext</code> - Remove FNF text.
• <code>/defaultnotfoundtext</code> - Reset to repo default text."""

    # ==========================================
    # 📝 FILTERS (Auto & Manual)
    # ==========================================
    FILTERS_TXT = f"""<b>📝 Mᴀɴᴜᴀʟ Fɪʟᴛᴇʀs</b>

• <code>/add &lt;keyword&gt;</code> - Reply to a file/text to create a filter.
• <code>/del &lt;keyword&gt;</code> - Delete a filter.
• <code>/delall</code> - Delete all filters in a chat.
• <code>/viewfilters</code> - See all active filters.
{FORMAT_GUIDE}"""

    # ==========================================
    # 📱 FORCE SUBSCRIBE
    # ==========================================
    FORCESUB_TXT = """<b>📱 Fᴏʀᴄᴇ Sᴜʙsᴄʀɪʙᴇ Sᴇᴛᴛɪɴɢs</b>

<b>🔗 Cʜᴀɴɴᴇʟ Mᴀɴᴀɢᴇᴍᴇɴᴛ</b>
• <code>/setfsub &lt;channel_id&gt;</code> - Add a dynamic FSub channel.
• <code>/rmfsub &lt;channel_id&gt;</code> - Remove an FSub channel.
• <code>/rmallfsub</code> - Clear all FSub channels.
• <code>/setfsubcount &lt;num&gt;</code> - Limit active required channels.

<b>⚙️ Cᴏɴᴛʀᴏʟs</b>
• <code>/enablefsub</code> / <code>/disablefsub</code> - Toggle global FSub.
• <code>/getallfsub</code> - View FSub channel queue.
• <code>/clearfsubusers</code> - Reset all verified FSub users."""

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
    DELETE_TXT = """<b>🗑️ Dᴇʟᴇᴛᴇ Sᴇᴛᴛɪɴɢs</b>

<b>⏱ Aᴜᴛᴏ Dᴇʟᴇᴛɪᴏɴ (Bᴏᴛ Aᴅᴍɪɴ)</b>
• <code>/autodelete &lt;seconds&gt;</code> - Time before PM files are deleted (Default: 1800s). Set 0 to disable.
• <code>/buttondel &lt;seconds&gt;</code> - Time before inline search buttons in groups are deleted. Set 0 to disable.

<b>🧹 Mᴀɴᴜᴀʟ Dᴇʟᴇᴛɪᴏɴ (Bᴏᴛ Aᴅᴍɪɴ)</b>
• <code>/delete &lt;file_id&gt;</code> - Delete specific file from DB.
• <code>/delete</code> (reply to file) - Delete replied file.
• <code>/delmulti &lt;keyword&gt;</code> - Mass delete files matching keyword."""

    # ==========================================
    # 🚫 BANS & RESTRICTIONS
    # ==========================================
    BANS_TXT = """<b>🚫 Bᴀɴs & Rᴇsᴛʀɪᴄᴛɪᴏɴs (Bᴏᴛ Aᴅᴍɪɴ)</b>

• <code>/ban &lt;user_id&gt;</code> - Ban a user globally.
• <code>/unban &lt;user_id&gt;</code> - Unban a user.
• <code>/bannedusers</code> - View count of banned users.
• <code>/leave &lt;group_id&gt;</code> - Force bot to leave a chat.
• <code>/disable &lt;group_id&gt;</code> - Blacklist a group.
• <code>/enable &lt;group_id&gt;</code> - Whitelist a group."""

    # ==========================================
    # 📝 CUSTOM CAPTION
    # ==========================================
    CUSTOMCAPTION_TXT = """<b>📝 Cᴜsᴛᴏᴍ Cᴀᴘᴛɪᴏɴs</b>

You can customize file captions by editing your Environment Variables.

<b>Vᴀʀɪᴀʙʟᴇs:</b>
• <code>{file_name}</code> - Name of the file
• <code>{file_size}</code> - Size of the file
• <code>{file_caption}</code> - Original caption"""

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
‣ /broadcast</b>"""

    PROMOTIONS_TXT = """<b>📢 Pʀᴏᴍᴏᴛɪᴏɴs & Bʀᴏᴀᴅᴄᴀsᴛ (Bᴏᴛ Aᴅᴍɪɴ)</b>

<b>💬 Bʀᴏᴀᴅᴄᴀsᴛɪɴɢ (Aᴜᴛᴏ-ᴅᴇʟᴇᴛᴇs ɪɴ 24ʜ)</b>
• <code>/broadcast</code> (reply to msg) - Send to all users.
• <code>/group_broadcast</code> (reply to msg) - Send to all groups.

<b>🔗 Iɴʟɪɴᴇ Pʀᴏᴍᴏs</b>
• <code>/addpromo "Text" &lt;Link&gt;</code> - Add inline promo button to search results.
• <code>/delpromo &lt;Link&gt;</code> - Remove promo button.
• <code>/listpromos</code> - View all active promos."""

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
