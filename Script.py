class script(object):
    # ==========================================
    # 🏠 MAIN MENUS
    # ==========================================
    START_TXT = """<b>Hᴇʏ {mention} 👋🏻\n\nI ᴀᴍ {bname} 🤖\n\nA ᴘᴏᴡᴇʀꜰᴜʟ ᴀᴜᴛᴏ-ꜰɪʟᴛᴇʀ ʙᴏᴛ ᴛᴏ ꜱᴇᴀʀᴄʜ ᴍᴏᴠɪᴇꜱ ᴀɴᴅ ꜱᴇʀɪᴇꜱ ɪɴꜱᴛᴀɴᴛʟʏ!\n\nSᴇɴᴅ ᴍᴇ ᴀɴʏ ᴍᴏᴠɪᴇ ɴᴀᴍᴇ, ᴀɴᴅ I ᴡɪʟʟ ᴘʀᴏᴠɪᴅᴇ ᴛʜᴇ ꜰɪʟᴇꜱ.</b>"""

    HELP_TXT = """<b>Hᴇʏ {mention} 👋🏻\n\nCʜᴏᴏꜱᴇ ᴛʜᴇ ᴄᴀᴛᴇɢᴏʀʏ ʙᴇʟᴏᴡ ᴛᴏ ꜱᴇᴇ ᴀʟʟ ᴀᴠᴀɪʟᴀʙʟᴇ ᴄᴏᴍᴍᴀɴᴅꜱ ᴀɴᴅ ꜰᴇᴀᴛᴜʀᴇꜱ!</b>"""

    ABOUT_TXT = """<b>🤖 Nᴀᴍᴇ:</b> {bname}\n<b>👨‍💻 Dᴇᴠᴇʟᴏᴘᴇʀ:</b> <a href='https://t.me/KR_Picture'>KR Pɪᴄᴛᴜʀᴇ</a>\n<b>📺 Cʜᴀɴɴᴇʟ:</b> <a href='https://t.me/sandalwood_kannada_moviesz'>Sᴀɴᴅᴀʟᴡᴏᴏᴅ</a>\n<b>💬 Sᴜᴘᴘᴏʀᴛ:</b> <a href='https://t.me/Kannada_Filmy_Group'>Kᴀɴɴᴀᴅᴀ Fɪʟᴍʏ Gʀᴏᴜᴘ</a>"""

    STATUS_TXT = """<b>📊 Bᴏᴛ Dᴀᴛᴀʙᴀsᴇ Sᴛᴀᴛᴜs</b>\n\n<b>📁 Tᴏᴛᴀʟ Fɪʟᴇs:</b> <code>{}</code>\n<b>👤 Tᴏᴛᴀʟ Usᴇʀs:</b> <code>{}</code>\n<b>🏘 Tᴏᴛᴀʟ Cʜᴀᴛs:</b> <code>{}</code>\n<b>💾 Usᴇᴅ Sᴛᴏʀᴀɢᴇ:</b> <code>{}</code>\n<b>💿 Fʀᴇᴇ Sᴛᴏʀᴀɢᴇ:</b> <code>{}</code>"""

    LOG_TEXT_G = """<b>#Nᴇᴡ_Gʀᴏᴜᴘ</b>\n\n<b>Group Name:</b> <code>{}</code>\n<b>Group ID:</b> <code>{}</code>\n<b>Members:</b> <code>{}</code>\n<b>Added By:</b> {}"""
    
    LOG_TEXT_P = """<b>#Nᴇᴡ_Usᴇʀ</b>\n\n<b>User ID:</b> <code>{}</code>\n<b>Profile:</b> {}"""

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
    FORCEADD_TXT = """<b>👥 Fᴏʀᴄᴇ Aᴅᴅ Mᴇᴍʙᴇʀs</b>

Force users to add members to your group before they can send messages!

<b>⚙️ Sᴇᴛᴜᴘ</b>
• <code>/setforceadd &lt;num&gt;</code> - Set how many members a user must add.
• <code>/remforceadd</code> - Disable the requirement.
• <code>/getforceadd</code> - View current requirements.

<b>📊 Lᴇᴀᴅᴇʀʙᴏᴀʀᴅs</b>
• <code>/myadds</code> - Check your current added count.
• <code>/topaddall</code> - All-time top adders.
• <code>/topadd24</code> - Top adders in last 24h.
• <code>/topadd7</code> - Top adders in last 7 days.
• <code>/resetadddaily</code> - Reset 24h/7d leaderboards.
• <code>/resetadd</code> - Nuke all scores back to 0."""

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
    SETTINGS_TXT = """<b>⚙️ Gʀᴏᴜᴘ Sᴇᴛᴛɪɴɢs</b>

• <code>/settings</code> - Open interactive settings menu for the current group.
• Configure Buttons, Bot PM, Spell Check, and Welcome modes.

<b>🌐 Cᴏɴɴᴇᴄᴛɪᴏɴs</b>
• <code>/connect &lt;group_id&gt;</code> - Link PM to group.
• <code>/disconnect &lt;group_id&gt;</code> - Unlink PM.
• <code>/connections</code> - View active connections."""
    
    CONNECTIONS_TXT = SETTINGS_TXT

    # ==========================================
    # 📊 UTILITIES & BACKUP
    # ==========================================
    UTILITIES_TXT = """<b>📊 Uᴛɪʟɪᴛɪᴇs & Sᴇʀᴠᴇʀ (Bᴏᴛ Aᴅᴍɪɴ)</b>

• <code>/stats</code> - Database statistics.
• <code>/server</code> - CPU, RAM, and Disk usage.
• <code>/restart</code> - Restart bot process safely.
• <code>/logs</code> - Download full system log file.
• <code>/cleanusers</code> - Ping all users to purge deleted accounts.
• <code>/clearusers</code> - ⚠️ Nuke user database!"""

    BACKUP_TXT = """<b>💾 MᴏɴɢᴏDB Bᴀᴄᴋᴜᴘ (Bᴏᴛ Aᴅᴍɪɴ)</b>

• <code>/dbbackup</code> - Generate full JSON backup of your database.
• <code>/dbrestore</code> (reply to .json file) - Restore database from file.
• <code>/dbstats</code> - Detailed MongoDB specs.
• <code>/dbschedule</code> - Start 24h automated backup cron job."""

    POSTHAND_TXT = """<b>📝 Pᴏsᴛ Hᴀɴᴅʟᴇ (Bᴏᴛ Aᴅᴍɪɴ)</b>

• <code>/channels</code> - Interactive menu of all connected channels/groups.
• <code>/leavechannel &lt;id&gt;</code> - Force leave and scrub a channel from DB.
• <code>/exportusers</code> - Download .txt list of all users.
• <code>/exportgroups</code> - Download .txt list of all groups.
• <code>/exportchannels</code> - Download .txt list of all channels."""
