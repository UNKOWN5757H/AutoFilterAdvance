import time
import logging
import asyncio
import re
from pyrogram import Client, filters, enums
from pyrogram.errors import (
    FloodWait, 
    ChannelInvalid, 
    ChatAdminRequired, 
    UsernameInvalid, 
    UsernameNotModified
)
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# Ensure these imports match your project structure
from info import ADMINS
from info import INDEX_REQ_CHANNEL as LOG_CHANNEL
# Notice we are now importing the ultra-fast save_batch function!
from database.ia_filterdb import save_batch
from utils import temp

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
lock = asyncio.Lock()


@Client.on_callback_query(filters.regex(r'^index'))
async def index_files(bot, query):
    if query.data.startswith('index_cancel'):
        temp.CANCEL = True
        return await query.answer("Cancelling Indexing...")
    
    # Safely unpack callback data
    data_parts = query.data.split("#")
    if len(data_parts) != 5:
        return await query.answer("Invalid callback data.", show_alert=True)
        
    _, action, chat, lst_msg_id, from_user = data_parts
    
    if action == 'reject':
        await query.message.delete()
        await bot.send_message(
            int(from_user),
            f'Your Submission for indexing {chat} has been declined by our moderators.',
            reply_to_message_id=int(lst_msg_id)
        )
        return

    if lock.locked():
        return await query.answer('Wait until the previous process completes.', show_alert=True)
        
    msg = query.message
    await query.answer('Processing...⏳', show_alert=True)
    
    if int(from_user) not in ADMINS:
        await bot.send_message(
            int(from_user),
            f'Your submission for indexing {chat} has been accepted by our moderators and will be added soon.',
            reply_to_message_id=int(lst_msg_id)
        )
        
    await msg.edit(
        "Starting Indexing...",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton('Cancel', callback_data='index_cancel')]]
        )
    )
    
    try:
        chat = int(chat)
    except ValueError:
        pass # Keep as string if it's a username
        
    await index_files_to_db(int(lst_msg_id), chat, msg, bot)


@Client.on_message((filters.forwarded | (filters.regex(r"(https://)?(t\.me/|telegram\.me/|telegram\.dog/)(c/)?(\d+|[a-zA-Z_0-9]+)/(\d+)$")) & filters.text) & filters.private & filters.incoming)
async def send_for_index(bot, message):
    if message.text:
        regex = re.compile(r"(https://)?(t\.me/|telegram\.me/|telegram\.dog/)(c/)?(\d+|[a-zA-Z_0-9]+)/(\d+)$")
        match = regex.match(message.text)
        if not match:
            return await message.reply('Invalid link')
        chat_id = match.group(4)
        last_msg_id = int(match.group(5))
        if chat_id.isnumeric():
            chat_id = int(f"-100{chat_id}")
    elif message.forward_from_chat.type == enums.ChatType.CHANNEL:
        last_msg_id = message.forward_from_message_id
        chat_id = message.forward_from_chat.username or message.forward_from_chat.id
    else:
        return
        
    try:
        await bot.get_chat(chat_id)
    except ChannelInvalid:
        return await message.reply('This may be a private channel/group. Make me an admin over there to index the files.')
    except (UsernameInvalid, UsernameNotModified):
        return await message.reply('Invalid Link specified.')
    except Exception as e:
        logger.exception(e)
        return await message.reply(f'Error - {e}')
        
    try:
        k = await bot.get_messages(chat_id, last_msg_id)
    except Exception:
        return await message.reply('Make sure that I am an admin in the channel (if the channel is private).')
        
    if k.empty:
        return await message.reply('This may be a group and I am not an admin of the group.')

    if message.from_user.id in ADMINS:
        buttons = [
            [InlineKeyboardButton('Yes', callback_data=f'index#accept#{chat_id}#{last_msg_id}#{message.from_user.id}')],
            [InlineKeyboardButton('Close', callback_data='close_data')]
        ]
        return await message.reply(
            f'Do you want to index this Channel/Group?\n\nChat ID/Username: <code>{chat_id}</code>\nLast Message ID: <code>{last_msg_id}</code>',
            reply_markup=InlineKeyboardMarkup(buttons)
        )

    if isinstance(chat_id, int):
        try:
            link = (await bot.create_chat_invite_link(chat_id)).invite_link
        except ChatAdminRequired:
            return await message.reply('Make sure I am an admin in the chat and have permission to invite users.')
    else:
        link = f"@{message.forward_from_chat.username}"
        
    buttons = [
        [InlineKeyboardButton('Accept Index', callback_data=f'index#accept#{chat_id}#{last_msg_id}#{message.from_user.id}')],
        [InlineKeyboardButton('Reject Index', callback_data=f'index#reject#{chat_id}#{message.id}#{message.from_user.id}')]
    ]
    
    await bot.send_message(
        LOG_CHANNEL,
        f'#IndexRequest\n\nBy: {message.from_user.mention} (<code>{message.from_user.id}</code>)\nChat ID/Username: <code>{chat_id}</code>\nLast Message ID: <code>{last_msg_id}</code>\nInviteLink: {link}',
        reply_markup=InlineKeyboardMarkup(buttons)
    )
    await message.reply('Thank you for the contribution! Wait for my moderators to verify the files.')


@Client.on_message(filters.command('setskip') & filters.user(ADMINS))
async def set_skip_number(bot, message):
    if len(message.command) > 1:
        skip = message.command[1]
        try:
            skip = int(skip)
        except ValueError:
            return await message.reply("Skip number should be an integer.")
        await message.reply(f"Successfully set SKIP number to {skip}")
        temp.CURRENT = skip
    else:
        await message.reply("Give me a skip number. Usage: `/setskip 100`")


async def index_files_to_db(lst_msg_id, chat, msg, bot):
    total_files = 0
    duplicate = 0
    errors = 0
    deleted = 0
    no_media = 0
    unsupported = 0
    
    async with lock:
        try:
            current = temp.CURRENT
            temp.CANCEL = False
            last_update_time = time.time()
            
            message_ids = list(range(current, lst_msg_id + 1))
            
            # Fetch from Telegram in massive chunks of 200
            for i in range(0, len(message_ids), 200):
                if temp.CANCEL:
                    await msg.edit(
                        f"**Successfully Cancelled!!**\n\n"
                        f"Saved <code>{total_files}</code> files to database!\n"
                        f"Duplicate Files Skipped: <code>{duplicate}</code>\n"
                        f"Deleted Messages Skipped: <code>{deleted}</code>\n"
                        f"Non-Media messages skipped: <code>{no_media + unsupported}</code> "
                        f"(Unsupported Media - `{unsupported}`)\n"
                        f"Errors Occurred: <code>{errors}</code>"
                    )
                    break
                
                chunk = message_ids[i:i + 200]
                messages = []
                
                # Robust FloodWait handling loop
                max_retries = 3
                while max_retries > 0:
                    try:
                        messages = await bot.get_messages(chat, chunk)
                        break
                    except FloodWait as e:
                        await asyncio.sleep(e.value + 1)
                        max_retries -= 1
                        
                if not messages:
                    continue # Skip this chunk if we exhausted retries
                
                # List to hold media objects for our bulk database insert
                media_to_save = []
                
                for message in messages:
                    current += 1
                    
                    # Update the UI message every 10 seconds safely
                    if time.time() - last_update_time > 10:
                        reply = InlineKeyboardMarkup([[InlineKeyboardButton('Cancel', callback_data='index_cancel')]])
                        try:
                            await msg.edit_text(
                                text=f"⚡ **Ultra-Speed Indexing...** ⚡\n\n"
                                     f"Total messages fetched: <code>{current}</code>\n"
                                     f"Total messages saved: <code>{total_files}</code>\n"
                                     f"Duplicate Files Skipped: <code>{duplicate}</code>\n"
                                     f"Deleted/Non-Media Skipped: <code>{deleted + no_media}</code>\n"
                                     f"Errors Occurred: <code>{errors}</code>",
                                reply_markup=reply
                            )
                        except FloodWait as e:
                            await asyncio.sleep(e.value + 1)
                        last_update_time = time.time()

                    if message.empty:
                        deleted += 1
                        continue
                    elif not message.media:
                        no_media += 1
                        continue
                    elif message.media not in [enums.MessageMediaType.VIDEO, enums.MessageMediaType.AUDIO, enums.MessageMediaType.DOCUMENT]:
                        unsupported += 1
                        continue
                        
                    media = getattr(message, message.media.value, None)
                    if not media:
                        unsupported += 1
                        continue
                        
                    media.file_type = message.media.value
                    media.caption = message.caption
                    
                    # Append valid media to our batch list!
                    media_to_save.append(media)
                
                # Push the entire chunk of files to MongoDB at the exact same time
                if media_to_save:
                    saved, dups, errs = await save_batch(media_to_save)
                    total_files += saved
                    duplicate += dups
                    errors += errs
                        
        except Exception as e:
            logger.exception(e)
            await msg.edit(f'Error: {e}')
        else:
            if not temp.CANCEL:
                await msg.edit(
                    f"🎉 **Indexing Complete!**\n\n"
                    f"Successfully saved <code>{total_files}</code> files to database!\n"
                    f"Duplicate Files Skipped: <code>{duplicate}</code>\n"
                    f"Deleted Messages Skipped: <code>{deleted}</code>\n"
                    f"Non-Media messages skipped: <code>{no_media + unsupported}</code> "
                    f"(Unsupported Media - `{unsupported}`)\n"
                    f"Errors Occurred: <code>{errors}</code>"
                )
