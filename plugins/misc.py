import os
from datetime import datetime
from logging import getLogger, ERROR

from pyrogram import Client, enums, filters
from pyrogram.errors import (
    MediaEmpty,
    PhotoInvalidDimensions,
    UserNotParticipant,
    WebpageMediaEmpty,
)
from pyrogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from info import IMDB_TEMPLATE
from utils import extract_user, get_file_id, get_poster

logger = getLogger(__name__)
logger.setLevel(ERROR)


class SafeDict(dict):
    """Safely formats strings. If a key is missing, it leaves the placeholder intact."""

    def __missing__(self, key):
        return "{" + key + "}"


@Client.on_message(filters.command("id"))
async def show_id(client: Client, message):
    chat_type = message.chat.type

    if chat_type == enums.ChatType.PRIVATE:
        user = message.from_user
        await message.reply_text(
            f"<b>👤 First Name:</b> {user.first_name}\n"
            f"<b>🧾 Last Name:</b> {user.last_name or 'None'}\n"
            f"<b>💬 Username:</b> @{user.username or 'None'}\n"
            f"<b>🆔 Telegram ID:</b> <code>{user.id}</code>\n"
            f"<b>🌐 Data Centre:</b> <code>{user.dc_id or 'N/A'}</code>",
            quote=True,
        )

    elif chat_type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
        reply = message.reply_to_message
        text = f"<b>🆔 Chat ID:</b> <code>{message.chat.id}</code>\n"

        if reply:
            text += f"<b>👤 User ID:</b> <code>{message.from_user.id if message.from_user else 'Anonymous'}</code>\n"
            text += f"<b>↪️ Replied User ID:</b> <code>{reply.from_user.id if reply.from_user else 'Anonymous'}</code>\n"
            file_id, _, media_type = get_file_id(reply)
        else:
            text += f"<b>👤 User ID:</b> <code>{message.from_user.id if message.from_user else 'Anonymous'}</code>\n"
            file_id, _, media_type = get_file_id(message)

        if file_id:
            text += f"<b>{media_type.capitalize()} ID:</b> <code>{file_id}</code>\n"

        await message.reply_text(text, quote=True)


@Client.on_message(filters.command("info"))
async def who_is(client: Client, message):
    status = await message.reply_text("🔍 Fetching user info...", quote=True)

    try:
        user = None
        if message.reply_to_message and message.reply_to_message.from_user:
            user = message.reply_to_message.from_user
        elif len(message.command) > 1:
            target = message.text.split(None, 1)[1]
            try:
                user = await client.get_users(target)
            except Exception:
                pass

        if not user:
            user = message.from_user

        if not user:
            return await status.edit("⚠️ No valid user found.")

        text = (
            f"<b>👤 First Name:</b> {user.first_name}\n"
            f"<b>🧾 Last Name:</b> {user.last_name or 'None'}\n"
            f"<b>🆔 Telegram ID:</b> <code>{user.id}</code>\n"
            f"<b>🌐 Data Centre:</b> <code>{user.dc_id or 'N/A'}</code>\n"
            f"<b>💬 Username:</b> @{user.username or 'None'}\n"
            f"<b>🔗 User Link:</b> <a href='tg://user?id={user.id}'>Click Here</a>\n"
        )

        if message.chat.type in (
            enums.ChatType.SUPERGROUP,
            enums.ChatType.CHANNEL,
            enums.ChatType.GROUP,
        ):
            try:
                member = await client.get_chat_member(message.chat.id, user.id)
                if member.joined_date:
                    joined_date = member.joined_date.strftime("%Y-%m-%d %H:%M:%S")
                    text += f"<b>📅 Joined Chat On:</b> <code>{joined_date}</code>\n"
            except Exception:
                pass

        buttons = [[InlineKeyboardButton("🔐 Close", callback_data="close_data")]]
        markup = InlineKeyboardMarkup(buttons)

        if user.photo:
            try:
                await message.reply_photo(
                    photo=user.photo.big_file_id,
                    caption=text,
                    reply_markup=markup,
                    parse_mode=enums.ParseMode.HTML,
                )
            except Exception as e:
                logger.error(f"Instant photo failed: {e}")
                await message.reply_text(
                    text, reply_markup=markup, parse_mode=enums.ParseMode.HTML
                )
        else:
            await message.reply_text(
                text, reply_markup=markup, parse_mode=enums.ParseMode.HTML
            )

        await status.delete()

    except Exception as e:
        logger.error(f"Info Command Error: {e}")
        await status.edit("❌ An error occurred while fetching user data.")


@Client.on_message(filters.command(["imdb", "search"]))
async def imdb_search(client: Client, message):
    if len(message.command) < 2:
        return await message.reply(
            "🎬 **Usage:** `/imdb Movie or Series Name`", quote=True
        )

    query = message.text.split(None, 1)[1]
    wait_msg = await message.reply("🔎 Searching IMDb...", quote=True)

    try:
        movies = await get_poster(query, bulk=True)
        if not movies:
            return await wait_msg.edit("❌ No results found on IMDb.")

        buttons = []
        for movie in movies[:10]:
            m_id = (
                getattr(movie, "movieID", None)
                or (movie.get("movieID") if isinstance(movie, dict) else None)
                or movie.get("id", "")
            )
            title = getattr(movie, "title", None) or (
                movie.get("title") if isinstance(movie, dict) else "Unknown"
            )
            year = getattr(movie, "year", None) or (
                movie.get("year") if isinstance(movie, dict) else ""
            )

            if m_id:
                btn_text = f"{title} ({year})" if year else title
                buttons.append(
                    [InlineKeyboardButton(btn_text, callback_data=f"imdb#{m_id}")]
                )

        if not buttons:
            return await wait_msg.edit("❌ Could not parse IMDb results.")

        await wait_msg.edit(
            "🎥 **Here’s what I found:**", reply_markup=InlineKeyboardMarkup(buttons)
        )

    except Exception as e:
        logger.exception(e)
        return await wait_msg.edit(f"⚠️ IMDb search error: `{e}`")


@Client.on_callback_query(filters.regex("^imdb"))
async def imdb_callback(client: Client, query: CallbackQuery):
    try:
        _, movie_id = query.data.split("#")
        await query.answer("Fetching Details...", show_alert=False)

        imdb = await get_poster(query=movie_id, id=True)

        if not imdb:
            return await query.message.edit("❌ No IMDb results found.")

        url = imdb.get("url", f"https://www.imdb.com/title/tt{movie_id}/")
        buttons = [[InlineKeyboardButton(f"{imdb.get('title', 'IMDb Link')}", url=url)]]

        format_args = SafeDict(
            query=imdb.get("title", "N/A"),
            title=imdb.get("title", "N/A"),
            votes=imdb.get("votes", "N/A"),
            aka=imdb.get("aka", "N/A"),
            seasons=imdb.get("seasons", "N/A"),
            box_office=imdb.get("box_office", "N/A"),
            localized_title=imdb.get("localized_title", "N/A"),
            kind=imdb.get("kind", "N/A"),
            imdb_id=imdb.get("imdb_id", movie_id),
            cast=imdb.get("cast", "N/A"),
            runtime=imdb.get("runtime", "N/A"),
            countries=imdb.get("countries", "N/A"),
            certificates=imdb.get("certificates", "N/A"),
            languages=imdb.get("languages", "N/A"),
            director=imdb.get("director", "N/A"),
            writer=imdb.get("writer", "N/A"),
            producer=imdb.get("producer", "N/A"),
            composer=imdb.get("composer", "N/A"),
            cinematographer=imdb.get("cinematographer", "N/A"),
            music_team=imdb.get("music_team", "N/A"),
            distributors=imdb.get("distributors", "N/A"),
            release_date=imdb.get("release_date", "N/A"),
            year=imdb.get("year", "N/A"),
            genres=imdb.get("genres", "N/A"),
            poster=imdb.get("poster", "N/A"),
            plot=imdb.get("plot", "N/A"),
            rating=imdb.get("rating", "N/A"),
            url=url,
        )

        caption = IMDB_TEMPLATE.format_map(format_args)

        if imdb.get("poster"):
            try:
                await query.message.reply_photo(
                    photo=imdb["poster"],
                    caption=caption,
                    reply_markup=InlineKeyboardMarkup(buttons),
                )
            except (MediaEmpty, PhotoInvalidDimensions, WebpageMediaEmpty):
                poster = imdb["poster"].replace(".jpg", "._V1_UX360.jpg")
                await query.message.reply_photo(
                    photo=poster,
                    caption=caption,
                    reply_markup=InlineKeyboardMarkup(buttons),
                )
            await query.message.delete()
        else:
            await query.message.edit(
                caption,
                reply_markup=InlineKeyboardMarkup(buttons),
                disable_web_page_preview=False,
            )

    except Exception as e:
        logger.error(f"IMDb Callback Error: {e}")
        try:
            await query.message.edit(f"⚠️ Error loading details: `{e}`")
        except Exception:
            pass
