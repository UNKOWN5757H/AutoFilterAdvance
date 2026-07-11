import asyncio
import base64
import json
import logging
import os
import random
import re
import sys

from pyrogram import Client, enums, filters
from pyrogram.errors import ChatAdminRequired, FloodWait
from pyrogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from database.connections_mdb import active_connection
from database.ia_filterdb import Media, get_file_details, unpack_new_file_id
from database.users_chats_db import db
from info import (
    ADMINS,
    AUTH_CHANNEL,
    BATCH_FILE_CAPTION,
    CHANNELS,
    CUSTOM_FILE_CAPTION,
    LOG_CHANNEL,
    PICS,
    PROTECT_CONTENT,
)
from plugins.fsub import ForceSub
from Script import script
from utils import get_settings, get_size, save_group_settings, temp

logger = logging.getLogger(__name__)

BATCH_FILES = {}
DELETE_TIME = 14400  # 4 Hours in seconds
LOG_FILE = "TelegramBot.log"


def get_start_buttons(user_id):
    """Helper to generate start buttons dynamically based on admin status."""
    buttons = [
        [
            InlineKeyboardButton("💫 Group", url="http://t.me/Kannada_Filmy_Group"),
            InlineKeyboardButton("🤖 Updates", url="https://t.me/Sandalwood_kannada_moviesz"),
        ]
    ]
    if user_id in ADMINS or str(user_id) in ADMINS:
        buttons.append([
            InlineKeyboardButton("ℹ️ 𝙷𝚎𝚕𝚙", callback_data="help"),
            InlineKeyboardButton("😊 𝙰𝚋𝚘𝚞𝚝", callback_data="about"),
        ])
    buttons.append([InlineKeyboardButton("© Dɪsᴄʟᴀɪᴍᴇʀ ©", callback_data="dics_btn")])
    return InlineKeyboardMarkup(buttons)


@Client.on_message(filters.command("start") & filters.incoming)
async def start(client: Client, message: Message):
    # ================= Handle Group Start =================
    if message.chat.type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
        reply_markup = get_start_buttons(message.from_user.id if message.from_user else 0)
        await message.reply(
            script.START_TXT.format(
                mention=(message.from_user.mention if message.from_user else message.chat.title),
                uname=temp.U_NAME,
                bname=temp.B_NAME,
            ),
            reply_markup=reply_markup,
        )
        await asyncio.sleep(2)
        
        # Log new group
        if not await db.get_chat(message.chat.id):
            total = await client.get_chat_members_count(message.chat.id)
            try:
                await client.send_message(
                    LOG_CHANNEL,
                    script.LOG_TEXT_G.format(message.chat.title, message.chat.id, total, "Unknown"),
                )
            except Exception as e:
                logger.error(f"Failed to log new group: {e}")
            await db.add_chat(message.chat.id, message.chat.title)
        return

    # ================= Handle Private Start =================
    if not await db.is_user_exist(message.from_user.id):
        await db.add_user(message.from_user.id, message.from_user.first_name)
        try:
            await client.send_message(
                LOG_CHANNEL,
                script.LOG_TEXT_P.format(message.from_user.id, message.from_user.mention),
            )
        except Exception as e:
            logger.error(f"Failed to log new user: {e}")

    # No deep link arguments
    if len(message.command) != 2:
        reply_markup = get_start_buttons(message.from_user.id)
        await message.reply_photo(
            photo=random.choice(PICS),
            caption=script.START_TXT.format(
                mention=message.from_user.mention, uname=temp.U_NAME, bname=temp.B_NAME
            ),
            reply_markup=reply_markup,
            parse_mode=enums.ParseMode.HTML,
        )
        return

    # Deep links with string commands
    if message.command[1] in ["subscribe", "error", "okay", "help", "start", "hehe"]:
        if message.command[1] == "subscribe":
            await ForceSub(client, message)
            return

        reply_markup = get_start_buttons(message.from_user.id)
        await message.reply_photo(
            photo=random.choice(PICS),
            caption=script.START_TXT.format(
                mention=message.from_user.mention, uname=temp.U_NAME, bname=temp.B_NAME
            ),
            reply_markup=reply_markup,
            parse_mode=enums.ParseMode.HTML,
        )
        return

    # ================= Handle File Deep Links =================
    cmd_data = message.command[1]
    kk, file_id = cmd_data.split("_", 1) if "_" in cmd_data else (False, False)
    pre = ("checksubp" if kk == "filep" else "checksub") if kk else False

    status = await ForceSub(client, message, file_id=file_id or cmd_data, mode=pre)
    if not status:
        return

    data = cmd_data
    if not file_id:
        file_id = data

    # Batch file handling
    if data.split("-", 1)[0] == "BATCH":
        sts = await message.reply("Please wait...")
        file_id = data.split("-", 1)[1]
        msgs = BATCH_FILES.get(file_id)
        
        if not msgs:
            file = await client.download_media(file_id)
            try:
                with open(file) as file_data:
                    msgs = json.loads(file_data.read())
            except Exception:
                await sts.edit("FAILED")
                try:
                    await client.send_message(LOG_CHANNEL, "UNABLE TO OPEN BATCH FILE.")
                except Exception:
                    pass
                return
            finally:
                if os.path.exists(file):
                    os.remove(file)
            BATCH_FILES[file_id] = msgs

        for msg in msgs:
            title = msg.get("title")
            size = get_size(int(msg.get("size", 0)))
            f_caption = msg.get("caption", "")

            if BATCH_FILE_CAPTION:
                try:
                    f_caption = BATCH_FILE_CAPTION.format(
                        file_name="" if title is None else title,
                        file_size="" if size is None else size,
                        file_caption="" if f_caption is None else f_caption,
                    )
                except Exception as e:
                    logger.exception(e)

            if not f_caption:
                f_caption = f"{title}"

            try:
                await client.send_cached_media(
                    chat_id=message.from_user.id,
                    file_id=msg.get("file_id"),
                    caption=f_caption,
                    protect_content=msg.get("protect", False),
                )
            except FloodWait as e:
                await asyncio.sleep(e.value)
                logger.warning(f"Floodwait of {e.value} sec.")
                await client.send_cached_media(
                    chat_id=message.from_user.id,
                    file_id=msg.get("file_id"),
                    caption=f_caption,
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🎥 ಕನ್ನಡ ಹೊಸ ಮೂವೀಗಳು 🎥", url="https://t.me/Sandalwood_kannada_moviesz")]]),
                    protect_content=msg.get("protect", False),
                )
            except Exception as e:
                logger.warning(e, exc_info=True)
                continue
            await asyncio.sleep(1)
            
        await sts.delete()
        return

    # DSTORE handling
    elif data.split("-", 1)[0] == "DSTORE":
        sts = await message.reply("Please wait...")
        b_string = data.split("-", 1)[1]
        decoded = base64.urlsafe_b64decode(b_string + "=" * (-len(b_string) % 4)).decode("ascii")
        try:
            f_msg_id, l_msg_id, f_chat_id, protect = decoded.split("_", 3)
        except ValueError:
            f_msg_id, l_msg_id, f_chat_id = decoded.split("_", 2)
            protect = "/pbatch" if PROTECT_CONTENT else "batch"

        async for msg in client.iter_messages(int(f_chat_id), int(l_msg_id), int(f_msg_id)):
            if msg.media:
                media = getattr(msg, msg.media)
                if BATCH_FILE_CAPTION:
                    try:
                        f_caption = BATCH_FILE_CAPTION.format(
                            file_name=getattr(media, "file_name", ""),
                            file_size=getattr(media, "file_size", ""),
                            file_caption=getattr(msg, "caption", ""),
                        )
                    except Exception as e:
                        logger.exception(e)
                        f_caption = getattr(msg, "caption", "")
                else:
                    f_caption = getattr(msg, "caption", getattr(media, "file_name", ""))

                try:
                    await msg.copy(
                        message.chat.id,
                        caption=f_caption,
                        protect_content=True if protect == "/pbatch" else False,
                    )
                except FloodWait as e:
                    await asyncio.sleep(e.value)
                    await msg.copy(
                        message.chat.id,
                        caption=f_caption,
                        protect_content=True if protect == "/pbatch" else False,
                    )
                except Exception as e:
                    logger.exception(e)
                    continue
            elif msg.empty:
                continue
            else:
                try:
                    await msg.copy(
                        message.chat.id,
                        protect_content=True if protect == "/pbatch" else False,
                    )
                except FloodWait as e:
                    await asyncio.sleep(e.value)
                    await msg.copy(message.chat.id, protect_content=True if protect == "/pbatch" else False)
                except Exception as e:
                    logger.exception(e)
                    continue
            await asyncio.sleep(1)
        return await sts.delete()

    # Regular single file handling
    files_ = await get_file_details(file_id)
    if not files_:
        try:
            pre, file_id = (base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))).decode("ascii").split("_", 1)
            msg = await client.send_cached_media(
                chat_id=message.from_user.id,
                file_id=file_id,
                protect_content=True if pre == "filep" else False,
            )
            filetype = msg.media
            file = getattr(msg, filetype)
            title = file.file_name
            size = get_size(file.file_size)
            f_caption = f"<code>{title}</code>"
            if CUSTOM_FILE_CAPTION:
                try:
                    f_caption = CUSTOM_FILE_CAPTION.format(
                        file_name="" if title is None else title,
                        file_size="" if size is None else size,
                        file_caption="",
                    )
                except Exception:
                    pass
            await msg.edit_caption(f_caption)
            return
        except Exception:
            return await message.reply("No such file exist.")

    files = files_[0]
    title = files.file_name
    size = get_size(files.file_size)
    f_caption = files.caption

    if CUSTOM_FILE_CAPTION:
        try:
            f_caption = CUSTOM_FILE_CAPTION.format(
                file_name="" if title is None else title,
                file_size="" if size is None else size,
                file_caption="" if f_caption is None else f_caption,
            )
        except Exception as e:
            logger.exception(e)

    if not f_caption:
        f_caption = f"{files.file_name}"

    msg = await client.send_cached_media(
        chat_id=message.from_user.id,
        file_id=file_id,
        caption=f_caption,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🎥 ಕನ್ನಡ ಹೊಸ ಮೂವೀಗಳು 🎥", url="https://t.me/Sandalwood_kannada_moviesz")]]),
        protect_content=True if pre == "filep" else False,
    )

    k = await msg.reply(
        f"<b><u>❗️❗️❗️IMPORTANT❗️️❗️❗️</u></b>\n\nᴛʜɪꜱ ᴍᴏᴠɪᴇ ꜰɪʟᴇ/ᴠɪᴅᴇᴏ ᴡɪʟʟ ʙᴇ ᴅᴇʟᴇᴛᴇᴅ ɪɴ <b><u><code>4 Hours</code></u> 🫥 <i></b>(ᴅᴜᴇ ᴛᴏ ᴄᴏᴘʏʀɪɢʜᴛ ɪꜱꜱᴜᴇꜱ)</i>.\n\n<b><i>ᴘʟᴇᴀꜱᴇ ꜰᴏʀᴡᴀʀᴅ ᴛʜɪꜱ ꜰɪʟᴇ ᴛᴏ ꜱᴏᴍᴇᴡʜᴇʀᴇ ᴇʟꜱᴇ ᴀɴᴅ ꜱᴛᴀʀᴛ ᴅᴏᴡɴʟᴏᴀᴅɪɴɢ ᴛʜᴇʀᴇ Team: @KR_Picture</i></b>",
        quote=True,
    )

    asyncio.create_task(delete_after_delay(msg, k, DELETE_TIME))


async def delete_after_delay(msg, warning_msg, delay):
    """Helper function to auto-delete PM files after X seconds."""
    await asyncio.sleep(delay)
    try:
        await msg.delete()
        await warning_msg.edit_text("<b>ʏᴏᴜʀ ᴠɪᴅᴇᴏ / ꜰɪʟᴇ ɪꜱ ꜱᴜᴄᴄᴇꜱꜱꜰᴜʟʟʏ ᴅᴇʟᴇᴛᴇᴅ !!. ᴛᴇᴀᴍ: @KR_Picture</b>")
    except Exception:
        pass


@Client.on_message(filters.command("channel") & filters.user(ADMINS))
async def channel_info(bot, message):
    if isinstance(CHANNELS, (int, str)):
        channels = [CHANNELS]
    elif isinstance(CHANNELS, list):
        channels = CHANNELS
    else:
        raise ValueError("Unexpected type of CHANNELS")

    text = "📑 **Indexed channels/groups**\n"
    for channel in channels:
        chat = await bot.get_chat(channel)
        if chat.username:
            text += "\n@" + chat.username
        else:
            text += "\n" + (chat.title or chat.first_name)

    text += f"\n\n**Total:** {len(CHANNELS)}"

    if len(text) < 4096:
        await message.reply(text)
    else:
        file = "Indexed channels.txt"
        with open(file, "w") as f:
            f.write(text)
        await message.reply_document(file)
        os.remove(file)


@Client.on_message(filters.command("logs") & filters.user(ADMINS))
async def send_logs(bot: Client, message):
    try:
        if not os.path.exists(LOG_FILE) and not os.path.exists("TelegramBot.log"):
            return await message.reply_text("⚠️ Log file not found.")
        log_file_name = "TelegramBot.log" if os.path.exists("TelegramBot.log") else LOG_FILE
        await message.reply_document(log_file_name, caption="📜 **Latest Bot Logs**")
    except Exception as e:
        logger.exception("send_logs failed")
        await message.reply_text(f"❌ Failed to send logs:\n`{e}`")


@Client.on_message(filters.command("restart") & filters.user(ADMINS))
async def restart_bot(bot: Client, message):
    buttons = [[InlineKeyboardButton("✅ Confirm Restart", callback_data="confirm_restart")]]
    await message.reply_text(
        "⚠️ Are you sure you want to restart the bot?",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


@Client.on_callback_query(filters.regex("^confirm_restart$"))
async def confirm_restart_callback(bot: Client, query: CallbackQuery):
    try:
        await query.answer("♻️ Restarting...", show_alert=True)
        await query.edit_message_text("♻️ Bot is restarting...")
        await asyncio.sleep(1)
        os.execv(sys.executable, [sys.executable, *sys.argv])
    except Exception:
        logger.exception("confirm_restart_callback failed")


@Client.on_message(filters.command("delete") & filters.user(ADMINS))
async def delete_file(bot: Client, message):
    try:
        if len(message.command) == 2:
            file_id = message.command[1].strip()
            await message.reply_text("🧹 Deleting file from DB...")
            try:
                result = await Media.collection.delete_one({"_id": file_id})
                if result.deleted_count:
                    await message.reply_text(f"✅ File `{file_id}` deleted successfully.")
                else:
                    await message.reply_text("⚠️ File not found in database.")
            except Exception as e:
                logger.exception("Error deleting file by id")
                await message.reply_text(f"❌ Error while deleting:\n`{e}`")
            return

        reply = message.reply_to_message
        if not (reply and reply.media):
            await message.reply_text("Usage:\n`/delete <file_id>`\nOr reply to file with /delete", quote=True)
            return

        msg = await message.reply_text("Processing...⏳", quote=True)
        media = getattr(reply, reply.media.value, None) if reply.media else None

        if not media:
            await msg.edit_text("This is not a supported file format.")
            return

        file_id, file_ref = unpack_new_file_id(media.file_id)
        res = await Media.collection.delete_one({"_id": file_id})
        if res.deleted_count:
            await msg.edit_text("File is successfully deleted from database.")
            return

        file_name = re.sub(r"(_|\-|\.|\+)", " ", str(getattr(media, "file_name", "")))
        res = await Media.collection.delete_many(
            {
                "file_name": file_name,
                "file_size": getattr(media, "file_size", 0),
                "mime_type": getattr(media, "mime_type", ""),
            }
        )
        if res.deleted_count:
            await msg.edit_text("File is successfully deleted from database.")
        else:
            await msg.edit_text("File not found in database.")
    except Exception:
        logger.exception("delete_file failed")


@Client.on_message(filters.command("deleteallfiles") & filters.user(ADMINS))
async def delete_all_files(bot: Client, message):
    buttons = [[InlineKeyboardButton("🔥 Confirm Delete All Files", callback_data="confirm_delete_all_files")]]
    await message.reply_text(
        "⚠️ This will permanently delete **all indexed files**.\nDo you really want to continue?",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


@Client.on_callback_query(filters.regex("^confirm_delete_all_files$"))
async def confirm_delete_all_files_callback(bot: Client, query: CallbackQuery):
    try:
        await query.answer("Deleting all files...", show_alert=True)
        deleted = await Media.collection.delete_many({})
        count = getattr(deleted, "deleted_count", 0)
        await query.edit_message_text(f"🗑️ Successfully deleted `{count}` files from DB.")
        logger.warning(f"Deleted {count} files from database.")
    except Exception:
        logger.exception("confirm_delete_all_files failed")
        try:
            await query.edit_message_text("❌ Error deleting files.")
        except Exception:
            pass


# ============================================================
# ⚙️ FIXED & COMPLETED SETTINGS COMMAND
# ============================================================
@Client.on_message(filters.command("settings"))
async def settings(client: Client, message: Message):
    userid = message.from_user.id if message.from_user else None
    if not userid:
        return await message.reply("You are an anonymous admin! Please verify your identity.")

    chat_type = message.chat.type

    # Handle if used in Private Message
    if chat_type == enums.ChatType.PRIVATE:
        grpid = await active_connection(str(userid))
        if grpid is not None:
            grp_id = grpid
            try:
                chat = await client.get_chat(grpid)
                title = chat.title
            except Exception:
                await message.reply_text("Make sure I'm present in your group!", quote=True)
                return
        else:
            await message.reply_text("I'm not connected to any groups!\nCheck /connections or connect to any groups.", quote=True)
            return

    # Handle if used inside a Group/Supergroup
    elif chat_type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
        grp_id = message.chat.id
        title = message.chat.title
    else:
        return

    # Permissions Check
    st = await client.get_chat_member(grp_id, userid)
    if (
        st.status != enums.ChatMemberStatus.ADMINISTRATOR
        and st.status != enums.ChatMemberStatus.OWNER
        and str(userid) not in ADMINS
    ):
        return await message.reply("Only group admins can use this command.")

    # Fetch and Build Settings Menu
    settings = await get_settings(grp_id)
    if settings is not None:
        buttons = [
            [
                InlineKeyboardButton('Filter Button', callback_data=f'setgs#button#{settings["button"]}#{grp_id}'),
                InlineKeyboardButton('Single' if settings["button"] else 'Double', callback_data=f'setgs#button#{settings["button"]}#{grp_id}')
            ],
            [
                InlineKeyboardButton('Bot PM', callback_data=f'setgs#botpm#{settings["botpm"]}#{grp_id}'),
                InlineKeyboardButton('✅ Yes' if settings["botpm"] else '❌ No', callback_data=f'setgs#botpm#{settings["botpm"]}#{grp_id}')
            ],
            [
                InlineKeyboardButton('File Secure', callback_data=f'setgs#file_secure#{settings["file_secure"]}#{grp_id}'),
                InlineKeyboardButton('✅ Yes' if settings["file_secure"] else '❌ No', callback_data=f'setgs#file_secure#{settings["file_secure"]}#{grp_id}')
            ],
            [
                InlineKeyboardButton('Spell Check', callback_data=f'setgs#spell_check#{settings["spell_check"]}#{grp_id}'),
                InlineKeyboardButton('✅ Yes' if settings["spell_check"] else '❌ No', callback_data=f'setgs#spell_check#{settings["spell_check"]}#{grp_id}')
            ],
            [
                InlineKeyboardButton('Welcome', callback_data=f'setgs#welcome#{settings["welcome"]}#{grp_id}'),
                InlineKeyboardButton('✅ Yes' if settings["welcome"] else '❌ No', callback_data=f'setgs#welcome#{settings["welcome"]}#{grp_id}')
            ]
        ]
        
        reply_markup = InlineKeyboardMarkup(buttons)
        await message.reply_text(
            text=f"⚙️ **Change Your Settings for {title}**",
            reply_markup=reply_markup,
            disable_web_page_preview=True,
            parse_mode=enums.ParseMode.MARKDOWN,
            quote=True
        )
