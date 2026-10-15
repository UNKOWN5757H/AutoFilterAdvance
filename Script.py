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
    UISTART_TXT = """<blockquote><b>🎨 Sᴛᴀʀᴛ Mᴇɴᴜ Cᴜsᴛᴏᴍɪᴢᴀᴛɪᴏɴ (<code>/uistart</code>)</b></blockquote>\n
<b>‣ <code>/setstarttext</code></b> - Set custom start text
<b>‣ <code>/defaultstarttext</code></b> - Revert to default start text
<b>‣ <code>/setstartimage</code></b> - Set custom start image (reply to photo)
<b>‣ <code>/remstartimage</code></b> - Remove custom start image
<b>‣ <code>/addstartbutton</code></b> - Add a start button (e.g. <code>/addstartbutton "Text" https://link.com</code>)
<b>‣ <code>/editstartbuttons</code></b> - Edit layout & colour (e.g. <code>/editstartbuttons 1 sidebyside green</code>)
<b>‣ <code>/remstartbutton</code></b> - Clear all custom start buttons

👇 <i>Tap any button below to configure or execute directly:</i>"""

    UIHELP_TXT = """<blockquote><b>🎨 Hᴇʟᴘ Mᴇɴᴜ Cᴜsᴛᴏᴍɪᴢᴀᴛɪᴏɴ (<code>/uihelp</code>)</b></blockquote>\n
<b>‣ <code>/sethelptext</code></b> - Set custom help text
<b>‣ <code>/defaulthelptext</code></b> - Revert to default help text
<b>‣ <code>/sethelpimage</code></b> - Set custom help image (reply to photo)
<b>‣ <code>/remhelpimage</code></b> - Remove custom help image
<b>‣ <code>/addhelpbutton</code></b> - Add a help button (e.g. <code>/addhelpbutton "Text" https://link.com</code>)
<b>‣ <code>/edithelpbuttons</code></b> - Edit layout & colour (e.g. <code>/edithelpbuttons 1 belowside red</code>)
<b>‣ <code>/remhelpbutton</code></b> - Clear all custom help buttons

👇 <i>Tap any button below to configure or execute directly:</i>"""

    UIABOUT_TXT = """<blockquote><b>🎨 Aʙᴏᴜᴛ Mᴇɴᴜ Cᴜsᴛᴏᴍɪᴢᴀᴛɪᴏɴ (<code>/uiabout</code>)</b></blockquote>\n
<b>‣ <code>/setabouttext</code></b> - Set custom about text
<b>‣ <code>/defaultabouttext</code></b> - Revert to default about text
<b>‣ <code>/setaboutimage</code></b> - Set custom about image (reply to photo)
<b>‣ <code>/remaboutimage</code></b> - Remove custom about image
<b>‣ <code>/addaboutbutton</code></b> - Add an about button (e.g. <code>/addaboutbutton "Text" https://link.com</code>)
<b>‣ <code>/editaboutbuttons</code></b> - Edit layout & colour
<b>‣ <code>/remaboutbutton</code></b> - Clear all custom about buttons

👇 <i>Tap any button below to configure or execute directly:</i>"""

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
• <code>[Link Text](http://url.com)</code> ➔ Link"""

    # ==========================================
    # 👋 WELCOME SETTINGS
    # ==========================================
    WELCOME_TXT = f"""<blockquote><b>👋 Wᴇʟᴄᴏᴍᴇ Mᴇssᴀɢᴇs (<code>/welcome</code>)</b></blockquote>

• <code>/enablewelcome</code> - Turn ON welcome messages.
• <code>/disablewelcome</code> - Turn OFF welcome messages.
• <code>/setwelcometxt &lt;text&gt;</code> - Set custom welcome text.
<i>Variables: {{mention}}, {{title}}, {{count}}</i>
• <code>/setwelcomeimg</code> - Reply to an image to set welcome photo.
• <code>/setwelcome</code> - Reply to an image with caption to set both!
• <code>/delwelcome</code> - Delete custom welcome settings.
{FORMAT_GUIDE}"""

    # ==========================================
    # 🖼️ IMAGE SETTINGS
    # ==========================================
    IMAGES_TXT = """<blockquote><b>🖼️ Gʟᴏʙᴀʟ Iᴍᴀɢᴇs Mᴀɴᴀɢᴇʀ (<code>/images</code>)</b></blockquote>

<b>Aᴜᴛᴏ-Fɪʟᴛᴇʀ Iᴍᴀɢᴇ</b>
• <code>/setautoimg</code> - Set global default auto-filter image.
• <code>/remautoimg</code> - Remove global auto-filter image.

<b>Fɪʟᴇ Nᴏᴛ Fᴏᴜɴᴅ Iᴍᴀɢᴇ</b>
• <code>/setfilenotfoundimg</code> - Set File Not Found image.
• <code>/remfilenotfoundimg</code> - Remove File Not Found image.
• <code>/defaultfilenotfoundimg</code> - Reset to default File Not Found image.

<b>Fᴏʀᴄᴇ Sᴜʙsᴄʀɪʙᴇ Iᴍᴀɢᴇ</b>
• <code>/setfsubimg</code> - Set the Force Subscribe alert photo.

👇 <i>Tap any button below to upload or manage images directly:</i>"""

    # ==========================================
    # 🔍 SPELL CHECK, SMART SEARCH & NOT FOUND
    # ==========================================
    SPELLCHECK_TXT = """<blockquote><b>🔍 Sᴘᴇʟʟ Cʜᴇᴄᴋ & Sᴍᴀʀᴛ Sᴇᴀʀᴄʜ (<code>/spellcheck</code>)</b></blockquote>

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
    FILTERS_TXT = """<blockquote><b>📝 Fɪʟᴛᴇʀ Mᴀɴᴀɢᴇᴍᴇɴᴛ (<code>/Autofilter</code>)</b></blockquote>\n
<b>‣ <code>/filter</code> - Add a text/media filter (<code>/filter keyword</code>)
‣ <code>/addfilter</code> - Add a filter from pre-made inline buttons
‣ <code>/filterimage</code> - Update only the media/image for a filter
‣ <code>/editfiltercolur</code> - Change filter button colour (<code>/editfiltercolur keyword 1 green</code>)
‣ <code>/delfilter</code> - Delete a filter (<code>/delfilter keyword</code>)
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
    FORCESUB_TXT = """<blockquote><b>📱 Fᴏʀᴄᴇ Sᴜʙsᴄʀɪᴘᴛɪᴏɴ Mᴀɴᴀɢᴇᴍᴇɴᴛ (<code>/forcesub</code>)</b></blockquote>\n
<b>‣ <code>/enablefsub</code> - Enable force subscribe
‣ <code>/disablefsub</code> - Disable force subscribe
‣ <code>/rotatefsub</code> - Toggle 1-hour auto-rotation on/off
‣ <code>/setfsub</code> - Add force subscribe channel (<code>/setfsub channel_id</code>)
‣ <code>/rmfsub</code> - Remove force subscribe channel (<code>/rmfsub channel_id</code>)
‣ <code>/rmallfsub</code> - Remove all force subscribe channels
‣ <code>/getallfsub</code> - View all force subscribe channels

🚪 Jᴏɪɴ Rᴇǫᴜᴇsᴛs:
‣ <code>/totalrequests</code> - Get total pending join requests
‣ <code>/purgerequests</code> - Purge all join requests from database</b>"""

    # ==========================================
    # 👥 FORCE ADD
    # ==========================================
    FORCEADD_TXT = """<blockquote><b>👥 Fᴏʀᴄᴇ Aᴅᴅ Mᴀɴᴀɢᴇᴍᴇɴᴛ (<code>/forceadd</code>)</b></blockquote>\n
<b>‣ <code>/setforceadd</code> - Set required member add count or channel for the group.
‣ <code>/remforceadd</code> - Disable/remove Force Add for the group.
‣ <code>/getforceadd</code> - View current Force Add configuration.
‣ <code>/myadds</code> - Check your personal member add count & rank.
‣ <code>/topaddall</code> - Show all-time top inviters leaderboard.
‣ <code>/topadd24</code> - Show top inviters in the last 24 hours.
‣ <code>/topadd7</code> - Show top inviters from the last 7 days.
‣ <code>/resetadddaily</code> - Reset today's add statistics.
‣ <code>/resetadd</code> - Reset all Force Add statistics.</b>"""

    # ==========================================
    # 🚫 BANS & RESTRICTIONS
    # ==========================================
    BANS_TXT = """<blockquote><b>🚫 Usᴇʀ & Cʜᴀᴛ Rᴇsᴛʀɪᴄᴛɪᴏɴs (<code>/bans</code>)</b></blockquote>\n
<b>‣ <code>/ban</code> - Ban a user from using the bot (<code>/ban user_id</code>)
‣ <code>/unban</code> - Unban a user from the bot (<code>/unban user_id</code>)
‣ <code>/bannedusers</code> - View total banned users
‣ <code>/leave</code> - Force bot to leave a chat (<code>/leave chat_id</code>)
‣ <code>/enable</code> - Enable / whitelist a group chat (<code>/enable chat_id</code>)
‣ <code>/disable</code> - Disable / blacklist a group chat (<code>/disable chat_id</code>)</b>"""

    # ==========================================
    # 🗑️ DELETE COMMANDS
    # ==========================================
    DELETE_TXT = """<blockquote><b>🗑️ Fɪʟᴇ & Aᴜᴛᴏ-Dᴇʟᴇᴛɪᴏɴ Mᴀɴᴀɢᴇᴍᴇɴᴛ (<code>/deletes</code>)</b></blockquote>\n
<b>‣ <code>/delete</code> - Reply to a file or send file name to delete from DB
‣ <code>/delmulti</code> - Delete multiple files matching a keyword (<code>/delmulti keyword</code>)
‣ <code>/autodelete</code> - Set PM file auto-delete timer in seconds
‣ <code>/buttondel</code> - Set group search results auto-delete timer in seconds
‣ <code>/purgeduplicates</code> - Scan DB and remove duplicate files automatically</b>"""

    # ==========================================
    # 📢 PROMOTIONS & BROADCAST
    # ==========================================
    PROMOTIONS_TXT = """<blockquote><b>📢 Pʀᴏᴍᴏᴛɪᴏɴs & Bʀᴏᴀᴅᴄᴀsᴛ Mᴀɴᴀɢᴇᴍᴇɴᴛ (<code>/broadcasts</code>)</b></blockquote>\n
<b>‣ <code>/addpromo</code> - Add promotional button (<code>/addpromo "Button Text" URL</code>)
‣ <code>/delpromo</code> - Delete a promotional button (<code>/delpromo URL</code>)
‣ <code>/listpromos</code> - View all active promotional buttons

💬 Bʀᴏᴀᴅᴄᴀsᴛɪɴɢ:
‣ <code>/broadcast</code> - Broadcast a message to all bot users
‣ <code>/group_broadcast</code> - Broadcast a message to all connected groups
‣ <code>/listbroadcast</code> - View active/recent broadcast status & statistics</b>"""

    # ==========================================
    # 📚 INDEXING (File Save)
    # ==========================================
    INDEX_TXT = """<blockquote><b>📚 Cʜᴀɴɴᴇʟ Iɴᴅᴇxɪɴɢ Mᴀɴᴀɢᴇʀ (<code>/indexs</code>)</b></blockquote>\n
<b>📚 Iɴᴅᴇxɪɴɢ Mᴏᴅᴇs:
‣ <code>/index</code> - Index all media from a channel
‣ <code>/indexdoc</code> - Index only document files
‣ <code>/indexvideo</code> - Index only video files
‣ <code>/indexaudio</code> - Index only audio files
‣ <code>/resumeindex</code> - Resume interrupted indexing for a channel

⏩ Sᴋɪᴘ Cᴏɴᴛʀᴏʟs:
‣ <code>/setskip</code> - Set starting message skip number
‣ <code>/deleteskip</code> - Reset skip number back to 0
‣ <code>/currentskip</code> - View current skip number</b>"""

    # ==========================================
    # ⚙️ SETTINGS & CONNECTIONS
    # ==========================================
    SETTINGS_TXT = """<blockquote><b>⚙️ Bᴏᴛ Sᴇᴛᴛɪɴɢs Mᴀɴᴀɢᴇᴍᴇɴᴛ (<code>/settings</code>)</b></blockquote>\n
<b>‣ <code>/repairmode</code> - Enable or disable maintenance mode
‣ <code>/adminsettings</code> - View current admin configuration dashboard
‣ <code>/enablereaction</code> - Enable auto-reactions globally
‣ <code>/disablereaction</code> - Disable auto-reactions globally</b>"""

    CONNECTIONS_TXT = """<blockquote><b>🌐 Cᴏɴɴᴇᴄᴛɪᴏɴs & Eхᴘᴏʀᴛ Mᴀɴᴀɢᴇʀ (<code>/conection</code>)</b></blockquote>\n
<b>‣ <code>/connect</code> - Connect a group to your PM (<code>/connect group_id</code>)
‣ <code>/disconnect</code> - Disconnect an active group
‣ <code>/connections</code> - View & switch between connected groups
‣ <code>/channels</code> - Paginated list of all connected channels & groups
‣ <code>/leavechannel</code> - Leave and remove a channel/group from DB
‣ <code>/exportusers</code> - Export `.txt` file of all user IDs
‣ <code>/exportgroups</code> - Export `.txt` file of all group IDs
‣ <code>/exportchannels</code> - Export `.txt` file of all channel IDs</b>"""

    # ==========================================
    # 📊 UTILITIES & BACKUP
    # ==========================================
    UTILITIES_TXT = """<blockquote><b>📊 Uᴛɪʟɪᴛɪᴇs & Dᴀᴛᴀʙᴀsᴇ Tᴏᴏʟs (<code>/utilitys</code>)</b></blockquote>\n
<b>‣ <code>/logs</code> - Download the latest bot log file
‣ <code>/server</code> - View live CPU, RAM, and Disk usage
‣ <code>/stats</code> - View complete database statistics
‣ <code>/optimize_db</code> - Optimize MongoDB indexes for maximum speed
‣ <code>/total</code> - View total indexed files count
‣ <code>/clearfsubusers</code> - Clear all ForceSub user records
‣ <code>/clearfiles</code> - ⚠️ Delete all indexed media files from DB
‣ <code>/clearusers</code> - ⚠️ Delete all users from DB
‣ <code>/cleanusers</code> - Scan & remove blocked/deleted user accounts</b>"""

    CUSTOMMESSAGES_TXT = """<blockquote><b>💬 Cᴜsᴛᴏᴍ Mᴇssᴀɢᴇs & Iᴍᴀɢᴇs (<code>/custommessges</code>)</b></blockquote>\n
<b>‣ <code>/infomsg</code> - Set info message before sending file
‣ <code>/infoimg</code> - Set info image before sending file
‣ <code>/fsubmsg</code> - Set custom Force Subscribe message
‣ <code>/fsubimg</code> - Set custom Force Subscribe image
‣ <code>/delmsg</code> - Set custom auto-delete warning message
‣ <code>/delimg</code> - Set custom auto-delete warning image
‣ <code>/notfoundmsg</code> - Set custom File Not Found message
‣ <code>/notfoundimg</code> - Set custom File Not Found image</b>"""

    CUSTOMCAPTION_TXT = """<blockquote><b>📝 Fɪʟᴇ Cᴀᴘᴛɪᴏɴ Mᴀɴᴀɢᴇᴍᴇɴᴛ (<code>/customcaptions</code>)</b></blockquote>\n
<b>‣ <code>/customcaption</code> - Set custom file caption template (or <code>off</code> to disable)
‣ <code>/captionplus</code> - Set extra footer caption appended to all files (or <code>off</code> to disable)</b>

<b>Vᴀʀɪᴀʙʟᴇs:</b>
• <code>{file_name}</code> - Name of the file
• <code>{file_size}</code> - Size of the file
• <code>{file_caption}</code> - Original file caption"""

    BACKUP_TXT = """<blockquote><b>💾 Dᴀᴛᴀʙᴀsᴇ Bᴀᴄᴋᴜᴘ Mᴀɴᴀɢᴇᴍᴇɴᴛ (<code>/backups</code>)</b></blockquote>\n
<b>‣ <code>/dbbackup</code> - Generate full JSON backup of your database
‣ <code>/dbrestore</code> - Reply to a `.json` backup file to restore DB
‣ <code>/dbstats</code> - View detailed MongoDB storage & collection specs
‣ <code>/dbschedule</code> - Toggle 24-hour automated backup schedule</b>"""

    # ==========================================
    # 💬 PM AUTO-REPLY & POST HANDLER
    # ==========================================
    PMAUTOREPLY_TXT = """<blockquote><b>💬 PM Aᴜᴛᴏ-Rᴇᴘʟʏ Eɴɢɪɴᴇ (<code>/pmautoreply</code>)</b></blockquote>

<b>Commands:</b>
• <code>/pmautoreply</code> - Toggle PM Auto-Reply ON or OFF.
• <code>/setpmtext [text]</code> - Set PM reply text (HTML supported).
• <code>/rempmtext</code> - Reset PM text to default.
• <code>/setpmimage</code> - Reply to a photo to set PM image.
• <code>/rempmimage</code> - Remove PM image.
• <code>/setpmbutton [Text | URL | Color]</code> - Set PM button.
• <code>/rempmbutton</code> - Remove PM button."""

    POSTHAND_TXT = """<blockquote><b>📝 Pᴏsᴛ Hᴀɴᴅʟᴇʀ Gᴜɪᴅᴇ (<code>/post</code>)</b></blockquote>

<b>‣ <code>/post &lt;movie_name&gt;</code> - Start interactive movie post creator
‣ <code>/editpost &lt;post_link&gt;</code> - Import and edit an existing channel post
‣ <code>/edittitle</code> / <code>/edityear</code> - Edit title or year in active draft
‣ <code>/editlangs</code> / <code>/editresolutions</code> - Edit languages or resolutions
‣ <code>/editgenres</code> / <code>/editotts</code> - Edit genres or OTT platforms
‣ <code>/editbutton</code> / <code>/editbuttoncolour</code> - Edit custom buttons & colours
‣ <code>/editdirect</code> - Edit Direct Search button text/link
‣ <code>/setpoststicker</code> / <code>/rempoststicker</code> - Manage auto-post sticker</b>"""
