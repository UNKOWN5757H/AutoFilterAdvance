class script(object):
    # ==========================================
    # 🏠 MAIN MENUS
    # ==========================================
    START_TXT = """<b>Hᴇʏ {mention} 👋🏻\n\nI ᴀᴍ {bname} 🤖\n\nA ᴘᴏᴡᴇʀꜰᴜʟ ᴀᴜᴛᴏ-ꜰɪʟᴛᴇʀ ʙᴏᴛ ᴛᴏ ꜱᴇᴀʀᴄʜ ᴍᴏᴠɪᴇꜱ ᴀɴᴅ ꜱᴇʀɪᴇꜱ ɪɴꜱᴛᴀɴᴛʟʏ!\n\nSᴇɴᴅ ᴍᴇ ᴀɴʏ ᴍᴏᴠɪᴇ ɴᴀᴍᴇ, ᴀɴᴅ I ᴡɪʟʟ ᴘʀᴏᴠɪᴅᴇ ᴛʜᴇ ꜰɪʟᴇꜱ.</b>"""

    HELP_TXT = """<b>Hᴇʏ {mention} 👋🏻\n\nCʜᴏᴏꜱᴇ ᴀ ᴄᴀᴛᴇɢᴏʀʏ ʙᴇʟᴏᴡ ᴛᴏ ᴍᴀɴᴀɢᴇ ʙᴏᴛ ᴄᴏᴍᴍᴀɴᴅꜱ ᴀɴᴅ ɪɴᴛᴇʀᴀᴄᴛɪᴠᴇ ᴄᴏɴᴛʀᴏʟꜱ!</b>"""

    ABOUT_TXT = """<b>🤖 Nᴀᴍᴇ:</b> {bname}\n<b>👨‍💻 Dᴇᴠᴇʟᴏᴘᴇʀ:</b> <a href='https://t.me/KR_Picture'>KR Pɪᴄᴛᴜʀᴇ</a>\n<b>📺 Cʜᴀɴɴᴇʟ:</b> <a href='https://t.me/sandalwood_kannada_moviesz'>Sᴀɴᴅᴀʟᴡᴏᴏᴅ</a>\n<b>💬 Sᴜᴘᴘᴏʀᴛ:</b> <a href='https://t.me/Kannada_Filmy_Group'>Kᴀɴɴᴀᴅᴀ Fɪʟᴍʏ Gʀᴏᴜᴘ</a>"""

    STATUS_TXT = """<b>📊 Bᴏᴛ Dᴀᴛᴀʙᴀsᴇ Sᴛᴀᴛᴜs</b>\n\n<b>📁 Tᴏᴛᴀʟ Fɪʟᴇs:</b> <code>{}</code>\n<b>👤 Tᴏᴛᴀʟ Usᴇʀs:</b> <code>{}</code>\n<b>🏘 Tᴏᴛᴀʟ Cʜᴀᴛs:</b> <code>{}</code>\n<b>💾 Usᴇᴅ Sᴛᴏʀᴀɢᴇ:</b> <code>{}</code>\n<b>💿 Fʀᴇᴇ Sᴛᴏʀᴀɢᴇ:</b> <code>{}</code>"""

    LOG_TEXT_G = """<b>#Nᴇᴡ_Gʀᴏᴜᴘ</b>\n\n<b>Group Name:</b> <code>{}</code>\n<b>Group ID:</b> <code>{}</code>\n<b>Members:</b> <code>{}</code>\n<b>Added By:</b> {}"""

    LOG_TEXT_P = (
        """<b>#Nᴇᴡ_Usᴇʀ</b>\n\n<b>User ID:</b> <code>{}</code>\n<b>Profile:</b> {}"""
    )

    # ==========================================
    # 🎨 UI CUSTOMIZATION MENUS
    # ==========================================
    UISTART_TXT = """<blockquote><b>🎨 Sᴛᴀʀᴛ Mᴇɴᴜ Cᴜsᴛᴏᴍɪᴢᴀᴛɪᴏɴ</b></blockquote>\n
<b>‣ /setstarttext</b> - Set custom text
<b>‣ /defaultstarttext</b> - Revert to default text
<b>‣ /setstartimage</b> - Set image (reply to photo)
<b>‣ /remstartimage</b> - Remove custom image
<b>‣ /addstartbutton</b> - Add a button (e.g. <code>/addstartbutton "Text" https://link.com</code>)
<b>‣ /editstartbuttons</b> - Edit layout & color (e.g. <code>/editstartbuttons 1 sidebyside green</code>)
<b>‣ /remstartbutton</b> - Clear all custom buttons"""

    UIHELP_TXT = """<blockquote><b>🎨 Hᴇʟᴘ Mᴇɴᴜ Cᴜsᴛᴏᴍɪᴢᴀᴛɪᴏɴ</b></blockquote>\n
<b>‣ /sethelptext</b> - Set custom text
<b>‣ /defaulthelptext</b> - Revert to default text
<b>‣ /sethelpimage</b> - Set image (reply to photo)
<b>‣ /remhelpimage</b> - Remove custom image
<b>‣ /addhelpbutton</b> - Add a button (e.g. <code>/addhelpbutton "Text" https://link.com</code>)
<b>‣ /edithelpbuttons</b> - Edit layout & color (e.g. <code>/edithelpbuttons 1 belowside red</code>)
<b>‣ /remhelpbutton</b> - Clear all custom buttons"""

    UIABOUT_TXT = """<blockquote><b>🎨 Aʙᴏᴜᴛ Mᴇɴᴜ Cᴜsᴛᴏᴍɪᴢᴀᴛɪᴏɴ</b></blockquote>\n
<b>‣ /setabouttext</b> - Set custom text
<b>‣ /defaultabouttext</b> - Revert to default text
<b>‣ /setaboutimage</b> - Set image (reply to photo)
<b>‣ /remaboutimage</b> - Remove custom image
<b>‣ /addaboutbutton</b> - Add a button (e.g. <code>/addaboutbutton "Text" https://link.com</code>)
<b>‣ /editaboutbuttons</b> - Edit layout & color
<b>‣ /remaboutbutton</b> - Clear all custom buttons"""

    # ==========================================
    # 📝 FORMATTING GUIDE
    # ==========================================
    FORMAT_GUIDE = """
<b>💡 Tᴇxᴛ Fᴏʀᴍᴀᴛᴛɪɴɢ Gᴜɪᴅᴇ:</b>
<i>Supports Markdown and HTML!</i>
• <code>**Bold**</code> ➔ <b>Bold</b>
• <code>__Italic__</code> ➔ <i>Italic</i>
• <code>~~Strike~~</code> ➔ <s>Strike</s>
• <code>--Underline--</code> ➔ <u>Underline</u>
• <code>||Spoiler||</code> ➔ <tg-spoiler>Spoiler</tg-spoiler>
• <code>`Mono`</code> ➔ <code>Mono</code>
• <code>&gt; Quote</code> ➔ Quote
• <code>[Link Text](http://url.com)</code> ➔ Link
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
    # 🔍 SPELL CHECK, SMART SEARCH & NOT FOUND
    # ==========================================
    SPELLCHECK_TXT = """<b>🔍 Sᴘᴇʟʟ Cʜᴇᴄᴋ & Sᴍᴀʀᴛ Sᴇᴀʀᴄʜ</b>

<b>Sᴘᴇʟʟ Cʜᴇᴄᴋ & Sᴍᴀʀᴛ Tᴏɢɢʟᴇs</b>
‣ <code>/enablespellcheck</code> - Turn ON spelling suggestions.
‣ <code>/disablespellcheck</code> - Turn OFF spelling suggestions.
‣ <code>/autotranslate</code> - Toggle Indic Script ➔ English translation.
‣ <code>/enautotranslate</code> / <code>/diautotranslate</code> - Enable or disable Auto-Translate.
‣ <code>/multichoice</code> - Toggle 'Did You Mean?' multi-choice buttons.
‣ <code>/enmultichoice</code> / <code>/dimultichoice</code> - Enable or disable Multi-Choice.

<b>Sᴛᴏᴘᴡᴏʀᴅs & Nᴏᴛ Fᴏᴜɴᴅ Tᴇxᴛ</b>
‣ <code>/addstopwords &lt;words&gt;</code> - Add ignored words (comma separated).
‣ <code>/stopwords</code> - View active stopwords.
‣ <code>/remstopwords &lt;word&gt;</code> - Remove a stopword.
‣ <code>/remallstopwords</code> - Clear all stopwords.
‣ <code>/defaultstopwords</code> - Restore default stopwords.
‣ <code>/setnotfoundtext &lt;text&gt;</code> - Set custom File Not Found text.
‣ <code>/remnotfoundtext</code> / <code>/defaultnotfoundtext</code> - Reset FNF text."""

    # ==========================================
    # 📝 FILTERS (Manual & Auto-Filter)
    # ==========================================
    FILTERS_TXT = """<blockquote><b>📝 Filter Management\nAdd, delete, or view filters to customize responses based on keywords.</b></blockquote>\n
<b>‣ <code>/filter</code> - Add a text filter (Reply <code>/filter keyword</code> to a message)
‣ <code>/addfilter</code> - Add a text filter from pre-made buttons
‣ <code>/filterimage</code> - Update only image for a filter (Reply to image with <code>/filterimage keyword</code>)
‣ <code>/editfiltercolur</code> - Change button colour (<code>/editfiltercolur keyword 1 green</code>)
‣ <code>/delfilter</code> - Delete a text filter (<code>/delfilter keyword</code>)
‣ <code>/listfilters</code> - List all filters currently added in the group

Supports text, photo, video, animation, and sticker filters.</b>"""

    # ==========================================
    # 🧹 CLEAN FILENAME
    # ==========================================
    CLEANFILE_TXT = """<b>🧹 Clean Filename Words Manager</b>
━━━━━━━━━━━━━━━━━━━━━
⚙️ <b>Current Mode:</b> {mode_str}
🔢 <b>Total Active Words:</b> <code>{count}</code>

📋 <b>Active Words Removed From Buttons:</b>
{words_display}
━━━━━━━━━━━━━━━━━━━━━
<b>Commands:</b>
• <code>/listcleanfilename</code> — View & manage active clean words.
• <code>/setcleanfilename w1, w2</code> — Set custom words to strip from file buttons.
• <code>/defaultcleanfilename</code> — Restore default extensions & tags.
• <code>/remcleanfilename</code> — Remove all clean words."""

    # ==========================================
    # 📱 FORCE SUBSCRIBE
    # ==========================================
    FORCESUB_TXT = """<blockquote><b>Force Subscription Management\nSet, manage, or clear force subscribe channels.</b></blockquote>\n
<b>‣ /enablefsub - Enable force subscribe
‣ /disablefsub - Disable force subscribe
‣ /setfsubcount - Set maximum Fsub chat count for queue
‣ /setfsub - Set force subscribe channel (<code>/setfsub channel_id</code>)
‣ /rmfsub - Remove force subscribe channel (<code>/rmfsub channel_id</code>)
‣ /rmallfsub - Remove all force subscribe channels
‣ /getallfsub - Get all force subscribe channel details
‣ /getactivefsub - Get active force subscribe channels
‣ /getpendingfsub - Get pending force subscribe channels in queue
‣ /activatefsub - Activate pending force subscribe channel
‣ /deactivatefsub - Deactivate force subscribe channel
‣ /updatefsubtarget - Update force subscribe channel target
‣ /checkfsubusers - Check force subscribe users count
‣ /clearfsubusers - Clear all force subscribe users from DB\n
🚪 JOIN REQUESTS:
‣ /totalrequests - Get total pending join requests
‣ /purgerequests - Purge all join requests from database</b>"""

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
‣ /delmulti - Delete multiple files from database with name (<code>/delmulti name</code>)
‣ /autodelete - Set file auto delete time in seconds
‣ /buttondel - Set button message in groups auto delete time in seconds
‣ /purgeduplicates - Scan DB, keep highest resolution, and delete redundant clones</b>"""

    # ==========================================
    # 🚫 BANS & RESTRICTIONS
    # ==========================================
    BANS_TXT = """<blockquote><b>User Management\nBan or unban users to control access to the bot.</b></blockquote>\n
<b>‣ /ban - Ban a user from bot (<code>/ban user_id</code>)
‣ /unban - Unban a user from bot (<code>/unban user_id</code>)
‣ /bannedusers - Check Banned Users List
‣ /leave - Force bot to leave a chat
‣ /enable - Whitelist a group
‣ /disable - Blacklist a group</b>"""

    # ==========================================
    # 📝 CUSTOM CAPTION & MESSAGES
    # ==========================================
    CUSTOMCAPTION_TXT = """<blockquote><b>File Caption Management\nManage or customize captions for files, including additional captions, to enhance file presentation.</b></blockquote>\n
<b>‣ /customcaption - Set custom caption for files (Reply to message to set, or <code>/customcaption off</code> to disable)
‣ /captionplus - Set additional caption for files along with main caption (Reply to message to set, or <code>/captionplus off</code> to disable)</b>

<b>Vᴀʀɪᴀʙʟᴇs:</b>
• <code>{file_name}</code> - Name of the file
• <code>{file_size}</code> - Size of the file
• <code>{file_caption}</code> - Original caption"""

    CUSTOMMESSAGES_TXT = """<blockquote><b>Custom Messages & Images\nConfigure custom messages and images for various actions.</b></blockquote>\n
<b>‣ /infomsg - Set info message before sending file
‣ /infoimg - Set info image before sending file
‣ /delmsg - Set delete message after sending file
‣ /delimg - Set delete image after sending file
‣ /notfoundmsg - Set message to send when file not found
‣ /notfoundimg - Set image to send when file not found
‣ /fsubmsg - Set force subscribe message
‣ /fsubimg - Set force subscribe image\n
<i>(Reply to a message/image with the command to set it, or use <code>off</code> to remove)</i></b>"""

    # ==========================================
    # 📚 INDEXING (File Save)
    # ==========================================
    INDEX_TXT = """<b>📚 Indexing
‣ <code>/index</code> - Save all media to DB
‣ <code>/indexvideo</code> - Save only videos
‣ <code>/indexdoc</code> - Save only documents
‣ <code>/indexaudio</code> - Save only audio
‣ <code>/resumeindex</code> - Resume stopped indexing

⏩ Speed & Skip
‣ <code>/setskip</code> - Skip first X messages
‣ <code>/currentskip</code> - View current skip count
‣ <code>/deleteskip</code> - Reset skip to 0
‣ <code>/setindexspeed</code> - Set delay between fetches

⚖️ Filters
‣ <code>/setminsize</code> - Set minimum file size (MB)
‣ <code>/setblacklist</code> - Add words to ignore
‣ <code>/remblacklist</code> - Remove ignored word
‣ <code>/allblacklist</code> - View ignored words
‣ <code>/setwhitelist</code> - Index ONLY these words
‣ <code>/remwhitelist</code> - Remove whitelist word
‣ <code>/allwhitelist</code> - View whitelist words

🛡️ Auto-Backup & Links
‣ <code>/setbackupchannel</code> - Set private backup chat ID
‣ <code>/autobackup</code> - Toggle Anti-Copyright shield
‣ <code>/link</code> - Get shareable link for a file
‣ <code>/plink</code> - Get protected shareable link
‣ <code>/batch</code> - Index entire channel in bulk
‣ <code>/pbatch</code> - Index entire channel in bulk (Protected Content)

🧹 Database Cleanup
‣ <code>/purgeduplicates</code> - Scan & Delete duplicate DB entries
‣ <code>/cleandeadlinks</code> - Remove broken Telegram links
‣ <code>/total</code> - Count total indexed files
‣ <code>/clearfiles</code> - ⚠️ Nuke entire file database!</b>"""

    # ==========================================
    # 📢 PROMOTIONS & BROADCAST
    # ==========================================
    PROMOTIONS_TXT = """<blockquote><b>Manage Promotional Links\nEasily add, delete, or view promotional links displayed between search results.</b></blockquote>\n
<b>‣ /addpromo - Set promotional links between results (<code>/addpromo "Button Text" URL</code>)
‣ /delpromo - Delete promotional links between results (<code>/delpromo URL</code>)
‣ /listpromos - List all promotional links currently added in the DB

💬 Bʀᴏᴀᴅᴄᴀsᴛɪɴɢ (Aᴜᴛᴏ-ᴅᴇʟᴇᴛᴇs ɪɴ 24ʜ)
‣ /broadcast - Send to all users
‣ /group_broadcast - Send to all groups</b>"""

    # ==========================================
    # ⚙️ SETTINGS & CONNECTIONS
    # ==========================================
    SETTINGS_TXT = """<blockquote><b>Bot Settings Management</b></blockquote>\n
<b>‣ /repairmode - Enable or disable repair mode (If on, bot will not send any files)
‣ /adminsettings - Get current admin settings
‣ /enablereaction - Enable Auto-Heart reactions globally
‣ /disablereaction - Disable Auto-Heart reactions globally</b>"""

    CONNECTIONS_TXT = """<blockquote><b>𝗖𝗼𝗺𝗺𝗮𝗻𝗱𝘀 𝗮𝗻𝗱 𝗨𝘀𝗮𝗴𝗲\nUsed to connect bot to PM for managing filters, avoiding spamming in groups.</b></blockquote>\n
<b>‣ /connect - Connect a particular chat to your PM
‣ /disconnect - Disconnect from a chat
‣ /connections - List all your connections

• <code>/channels</code> - Interactive menu of all connected channels/groups.
• <code>/leavechannel &lt;id&gt;</code> - Force leave and scrub a channel from DB.
• <code>/exportusers</code> - Download .txt list of all users.
• <code>/exportgroups</code> - Download .txt list of all groups.
• <code>/exportchannels</code> - Download .txt list of all channels.</b>"""

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
‣ /analize - View Live Trending Search Dashboard
‣ /exportstats - Export full search history data to .txt
‣ /optimize_db - Optimize Database indexes for speed
‣ /broadcast - Reply to a message to send that to all bot users
‣ /total - Get count of total files in DB
‣ /clearfiles - Clear all files from DB
‣ /users_list - Get list of users in DB
‣ /clearusers - Clear all users from DB
‣ /cleanusers - Ping all users to purge deleted accounts
‣ /clearfsubusers - Clear all force subscribe users from DB</b>"""

    BACKUP_TXT = """<blockquote><b>Database Backup Management\nManage database backups, including scheduled backups and manual backups.</b></blockquote>\n
<b>These commands are only available for the ADMINS of the bot.</b>\n
<b>‣ /dbbackup - Generate full JSON backup of your database.
‣ /dbrestore - (reply to .json file) - Restore database from file.
‣ /dbstats - Detailed MongoDB specs.
‣ /dbschedule - Start 24h automated backup cron job.</b>"""

    # ==========================================
    # 💬 PM AUTO-REPLY & POST HANDLER
    # ==========================================
    PMAUTOREPLY_TXT = """<b>💬 PM Auto-Reply Engine</b>

Configure what the bot says when someone messages it directly in PM.

<b>Commands:</b>
• <code>/pmautoreply</code> - Toggle PM Auto-Reply ON or OFF.
• <code>/setpmtext [text]</code> - Set PM reply text (HTML bold, italics, links supported).
• <code>/rempmtext</code> - Reset text to default.
• <code>/setpmimage [URL/Reply]</code> - Set PM image.
• <code>/rempmimage</code> - Remove PM image.
• <code>/setpmbutton [Text | URL | Color]</code> - Set colored PM button (green, red, blue).
• <code>/rempmbutton</code> - Remove PM button."""

    POSTHAND_TXT = """<b>📝 POST HANDLER GUIDE

‣ <code>/post</code> - Start manual post session with interactive search
‣ <code>/editpost</code> - Import and edit an existing channel post via link
‣ <code>/resumepost</code> - Restore lost/interrupted draft from MongoDB
‣ <code>/hydra</code> - Toggle Hydra Anti-Ban engine (on/off)
‣ <code>/updatealllinks</code> - Mass update old inline URLs across channel posts
‣ <code>/editposttitle</code> / <code>/edittitle</code> - Edit movie title in active draft
‣ <code>/editpostyear</code> / <code>/edityear</code> - Edit release year in active draft
‣ <code>/editpostbutton</code> - Edit custom inline button (Number Text | URL)
‣ <code>/editpostbuttoncolour</code> / <code>/editbuttoncolour</code> - Change button colour (green/red/blue)
‣ <code>/editpostdirect</code> / <code>/editdirect</code> - Change Direct Search button URL
‣ <code>/editpostlangs</code> / <code>/editlangs</code> - Edit languages list in active draft
‣ <code>/editpostresolutions</code> / <code>/editresolutions</code> - Edit resolutions list in active draft
‣ <code>/editpostgenres</code> / <code>/editgenres</code> - Edit genres list in active draft
‣ <code>/editpostotts</code> / <code>/editotts</code> - Edit OTT platforms list in active draft
‣ <code>/editpostimage</code> / <code>/editimage</code> - Set preview URL/poster for draft
‣ <code>/editpostnormalimage</code> / <code>/editnormalimage</code> - Set normal photo file_id for draft</b>"""
