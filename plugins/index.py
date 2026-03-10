import logging
import asyncio
import time
import re
from pyrogram import Client, filters, enums
from pyrogram.errors import FloodWait, ChannelInvalid, ChatAdminRequired, UsernameInvalid, UsernameNotModified
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message

# Assuming these imports are defined elsewhere in your project
from info import ADMINS, INDEX_REQ_CHANNEL as LOG_CHANNEL
from database.ia_filterdb import save_file
from utils import temp

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
lock = asyncio.Lock()

# --- Utility Functions ---

def get_link_info(text: str):
    """Extracts chat_id and last_msg_id from a Telegram link."""
    match = re.match(r"(https://)?(t\.me/|telegram\.me/|telegram\.dog/)(c/)?(\d+|[\w_]+)/(\d+)$", text)
    if not match:
        return None, None
    chat_id = match.group(4)
    last_msg_id = int(match.group(5))
    
    # Convert public channel ID (e.g., 12345) to integer format (-10012345)
    if chat_id.isnumeric():
        chat_id = int("-100" + chat_id)
        
    return chat_id, last_msg_id

# =========================================================
# 📦 CALLBACK: INDEX ACCEPT/REJECT
# =========================================================
@Client.on_callback_query(filters.regex(r'^index'))
async def index_files_callback_handler(bot: Client, query):
    try:
        data = query.data
        if data.startswith('index_cancel'):
            # This check must be immediate for responsiveness
            if not lock.locked():
                 return await query.answer("Indexing is not currently running.")
                 
            temp.CANCEL = True
            return await query.answer("🛑 Cancelling Indexing...", show_alert=True)

        _, action, chat, lst_msg_id, from_user = data.split("#")

        if action == 'reject':
            await query.message.delete()
            await bot.send_message(
                int(from_user),
                f'❌ Your submission for indexing `{chat}` has been **declined** by moderators.',
                reply_to_message_id=int(lst_msg_id)
            )
            return await query.answer("Request rejected.")

        if lock.locked():
            return await query.answer('⚙️ Another indexing is in progress. Please wait.', show_alert=True)

        msg = query.message
        await query.answer('Starting indexing...', show_alert=False)

        # Notify the requester if they are not an admin
        if int(from_user) not in ADMINS:
            await bot.send_message(
                int(from_user),
                f'✅ Your submission for indexing `{chat}` has been **accepted** and is now processing.',
                reply_to_message_id=int(lst_msg_id)
            )

        await msg.edit(
            "📦 **Starting Indexing Process...**\n\nRetrieving messages...",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('🛑 Cancel', callback_data='index_cancel')]])
        )

        try:
            # Try to convert chat identifier to integer ID if possible
            chat_id = int(chat) if str(chat).lstrip('-').isdigit() else chat
        except ValueError:
            chat_id = chat

        await index_files_to_db(int(lst_msg_id), chat_id, msg, bot)

    except Exception as e:
        logger.exception("Error in index_files_callback_handler: %s", e)
        await query.answer(f"Error: {e}", show_alert=True)
        if 'msg' in locals():
             await msg.edit_text(f"❌ Indexing failed due to an internal error:\n`{e}`")


# =========================================================
# 📥 INDEX REQUEST HANDLER
# =========================================================
@Client.on_message(
    (filters.forwarded | filters.regex(r"(https://)?(t\.me/|telegram\.me/|telegram\.dog/)(c/)?(\d+|[a-zA-Z_0-9]+)/(\d+)$"))
    & filters.private & filters.incoming
)
async def send_for_index(bot: Client, message: Message):
    chat_id, last_msg_id = None, None

    # --- Extract link/info ---
    if message.text:
        chat_id, last_msg_id = get_link_info(message.text)
        if not chat_id or not last_msg_id:
            return await message.reply("❌ Invalid Telegram link format.")
    elif message.forward_from_chat:
        last_msg_id = message.forward_from_message_id
        chat_id = message.forward_from_chat.username or message.forward_from_chat.id
    else:
        return # Should not happen based on filters, but good practice

    # --- Validate Chat and Access ---
    try:
        chat_info = await bot.get_chat(chat_id)
    except (ChannelInvalid, UsernameInvalid, UsernameNotModified):
        return await message.reply("❌ Invalid or inaccessible channel/group.")
    except ChatAdminRequired:
        return await message.reply("⚠️ Make sure I'm an admin there before indexing.")
    except Exception as e:
        logger.exception(e)
        return await message.reply(f"Error checking chat: `{e}`")

    try:
        # Check if the last message ID is valid/accessible
        test_msg = await bot.get_messages(chat_id, last_msg_id)
        if test_msg.empty:
            return await message.reply("⚠️ Channel seems empty or I lack access to that message ID.")
    except Exception:
        return await message.reply("⚠️ Cannot access messages — ensure I’m an admin and the message ID is correct.")
    
    # Store the actual chat ID (integer or string username)
    final_chat_id = chat_info.username or chat_info.id

    # --- If admin, allow direct start ---
    if message.from_user.id in ADMINS:
        buttons = [[
            InlineKeyboardButton("✅ Start Indexing", callback_data=f"index#accept#{final_chat_id}#{last_msg_id}#{message.from_user.id}")
        ], [
            InlineKeyboardButton("❌ Cancel", callback_data="close_data")
        ]]
        return await message.reply(
            f"🗂 **Confirm Indexing**\n\n**Chat:** `{final_chat_id}`\n**Last Message ID:** `{last_msg_id}`",
            reply_markup=InlineKeyboardMarkup(buttons)
        )

    # --- Non-admin: forward request to LOG_CHANNEL ---
    try:
        # Get invite link only if it's a private chat ID (negative integer)
        if isinstance(final_chat_id, int) and final_chat_id < 0:
            try:
                link = (await bot.create_chat_invite_link(final_chat_id)).invite_link
            except ChatAdminRequired:
                return await message.reply("Make sure I’m an admin and can create invite links.")
        else:
            link = f"@{final_chat_id}"

        buttons = [[
            InlineKeyboardButton("✅ Accept Index", callback_data=f"index#accept#{final_chat_id}#{last_msg_id}#{message.from_user.id}")
        ], [
            InlineKeyboardButton("❌ Reject Index", callback_data=f"index#reject#{final_chat_id}#{message.id}#{message.from_user.id}")
        ]]

        await bot.send_message(
            LOG_CHANNEL,
            f"📥 **#IndexRequest**\n\n👤 From: {message.from_user.mention} (`{message.from_user.id}`)\n🗂 Chat: `{final_chat_id}`\n🆔 Last Msg ID: `{last_msg_id}`\n🔗 Invite: {link}",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        await message.reply("✅ Thank you! Your indexing request has been sent for moderation.")
    except Exception as e:
        logger.exception("Error sending request to LOG_CHANNEL: %s", e)
        await message.reply(f"Error while sending request: `{e}`")


# =========================================================
# ⚙️ SET SKIP COMMAND
# =========================================================
@Client.on_message(filters.command("setskip") & filters.user(ADMINS))
async def set_skip_number(bot: Client, message: Message):
    parts = message.text.split()
    if len(parts) < 2:
        return await message.reply("Usage: `/setskip <number>`")
    try:
        temp.CURRENT = int(parts[1])
        await message.reply(f"✅ Skip number set to **{temp.CURRENT}**. Indexing will start from this message ID.")
    except ValueError:
        await message.reply("⚠️ Skip number must be a valid integer.")


# =========================================================
# ⚡ INDEX CORE LOOP (ULTRA FAST)
# =========================================================
async def index_files_to_db(last_msg_id, chat, msg, bot: Client):
    total_files = duplicate = errors = deleted = no_media = unsupported = 0
    
    # 🚀 OPTIMIZATION: Increased concurrency and batch size for save_file
    db_batch = [] 
    db_batch_size = 50  # Process 50 media files concurrently 
    
    edit_interval = 5  # seconds
    last_edit = time.time()

    async with lock:
        temp.CANCEL = False
        current = temp.CURRENT
        start_time = time.time()
        
        try:
            # We iterate backwards from the last message ID down to the skip point
            async for message in bot.iter_messages(chat, last_msg_id, current):
                if temp.CANCEL:
                    break

                current += 1 # Message ID count increases as we iterate backwards (due to how iter_messages works with offset)
                
                # --- Quick skip checks ---
                if message.empty:
                    deleted += 1
                    continue
                if not message.media:
                    no_media += 1
                    continue

                # --- Media Type check ---
                media_type = message.media.value
                if media_type not in (
                    enums.MessageMediaType.VIDEO,
                    enums.MessageMediaType.AUDIO,
                    enums.MessageMediaType.DOCUMENT,
                ):
                    unsupported += 1
                    continue

                media = getattr(message, media_type, None)
                if not media:
                    unsupported += 1
                    continue

                # Prepare media object for saving
                media.file_type = media_type
                media.caption = message.caption
                
                # Add to batch for concurrent processing
                db_batch.append(media)

                # --- Process db_batch concurrently ---
                if len(db_batch) >= db_batch_size:
                    results = await asyncio.gather(*(save_file(m) for m in db_batch), return_exceptions=True)
                    for res in results:
                        if isinstance(res, Exception):
                            errors += 1
                        else:
                            success, code = res
                            if success:
                                total_files += 1
                            elif code == 0:
                                duplicate += 1
                            elif code == 2:
                                errors += 1
                    db_batch.clear()

                # --- Periodic edit (for progress update) ---
                if time.time() - last_edit >= edit_interval:
                    await msg.edit_text(
                        f"📊 **Indexing in progress...**\n\n"
                        f"✅ Saved: `{total_files}`\n"
                        f"♻️ Duplicates: `{duplicate}`\n"
                        f"📭 Deleted: `{deleted}`\n"
                        f"🚫 Skipped (media issues): `{no_media + unsupported}`\n"
                        f"⚠️ Errors: `{errors}`\n"
                        f"🧭 Messages Processed: `{current - temp.CURRENT}`",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('🛑 Cancel', callback_data='index_cancel')]])
                    )
                    last_edit = time.time()

            # --- Final flush for leftovers ---
            if db_batch:
                results = await asyncio.gather(*(save_file(m) for m in db_batch), return_exceptions=True)
                for res in results:
                    if isinstance(res, Exception):
                        errors += 1
                    else:
                        success, code = res
                        if success:
                            total_files += 1
                        elif code == 0:
                            duplicate += 1
                        elif code == 2:
                            errors += 1

            elapsed = time.time() - start_time
            
            # --- Final message update ---
            if temp.CANCEL:
                 final_status = "🛑 **Indexing Canceled!**"
            else:
                 final_status = "✅ **Indexing Completed!**"

            await msg.edit(
                f"{final_status}\n\n"
                f"📦 Total Saved: `{total_files}`\n"
                f"♻️ Duplicates: `{duplicate}`\n"
                f"🗑 Deleted: `{deleted}`\n"
                f"🚫 Skipped (non-media/unsupported): `{no_media + unsupported}`\n"
                f"⚠️ Errors: `{errors}`\n"
                f"⏱ Time Taken: `{elapsed:.1f}s`"
            )

        except FloodWait as e:
            logger.warning("FloodWait during indexing: %s", e)
            await asyncio.sleep(e.value)
            # Cannot safely continue iteration after a long FloodWait without tracking progress better
            await msg.edit(f"⚠️ **Indexing Paused (FloodWait)**\n\nResuming is unsafe. Please restart manually from ID `{current}` after `{e.value}s`.")
        except Exception as e:
            logger.exception("Indexing failed: %s", e)
            await msg.edit(f"❌ Error occurred during indexing:\n`{e}`")
