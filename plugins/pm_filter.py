import ast
import asyncio
import difflib
import math
import re
import time
from logging import ERROR, getLogger
from typing import Dict, Optional, Tuple

from motor.motor_asyncio import AsyncIOMotorClient
from pyrogram import Client, enums, filters
from pyrogram.errors import (
    ButtonUrlInvalid,
    ChatWriteForbidden,
    FloodWait,
    Forbidden,
    MessageIdInvalid,
    MessageNotModified,
    PeerIdInvalid,
    QueryIdInvalid,
    UserIsBlocked,
)
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

import info
from database.connections_mdb import active_connection
from database.filters_mdb import find_filter, get_filters
from database.ia_filterdb import Media as _Media
from database.ia_filterdb import get_search_results
from database.plugin_dbs import plugin_db as _plugin_db
from database.users_chats_db import db as _db
from plugins.custom_settings import get_bot_settings, get_stopwords
from utils import get_settings, get_size, parse_text_and_markup, temp

logger = getLogger(__name__)
logger.setLevel(ERROR)

# ============================================================
# ⚡ GLOBAL CONFIG & MONGODB SETUP
# ============================================================
cw_db = None
try:
    _DB_CLIENT = AsyncIOMotorClient(info.DATABASE_URI)
    _BOT_DB = _DB_CLIENT[info.DATABASE_NAME]
    cw_db = _BOT_DB["clean_words"]
except Exception as e:
    logger.error(f"Failed to init cw_db: {e}")

DEFAULT_CLEAN_WORDS = ["sandalwood", "mkv", "mp4", "avi", "webm", "zip", "rar"]


async def get_clean_words():
    if cw_db is None:
        return DEFAULT_CLEAN_WORDS
    try:
        doc = await cw_db.find_one({"id": "words"})
        if doc is None or doc.get("use_default", True):
            return DEFAULT_CLEAN_WORDS
        return doc.get("list", [])
    except Exception:
        return DEFAULT_CLEAN_WORDS


def clean_filename(name: str, clean_words: list) -> str:
    if not name:
        return "File"
    if any(w.lower() in ["mkv", "sandalwood"] for w in clean_words):
        name = re.sub(r"(?i)\[?@?sandalwood[^\]\s]*\]?", "", name)
        name = re.sub(r"(?i)\b(sandalwood|mkv|mp4|avi|webm|zip|rar)\b", "", name)
    name = re.sub(r"[_.-]", " ", name)
    for word in clean_words:
        if word.lower() in ["mkv", "sandalwood", "mp4", "avi", "webm", "zip", "rar"]:
            continue
        name = re.sub(rf"(?i){re.escape(word)}", "", name)
    name = re.sub(r"\s+", " ", name).strip()
    return (name[:42] + "..") if len(name) > 45 else (name or "File")


class TTLCache:
    def __init__(self, maxsize: int = 2000, ttl: int = 1800):
        self._data: Dict[str, Tuple[float, any]] = {}
        self._maxsize = maxsize
        self._ttl = ttl

    def set(self, key: str, value: any):
        self._cleanup()
        if len(self._data) >= self._maxsize:
            oldest_key = min(self._data, key=lambda k: self._data[k][0])
            self._data.pop(oldest_key, None)
        self._data[key] = (time.time() + self._ttl, value)

    def get(self, key: str) -> Optional[any]:
        item = self._data.get(key)
        if not item:
            return None
        expire_at, value = item
        if time.time() > expire_at:
            self._data.pop(key, None)
            return None
        return value

    def _cleanup(self):
        now = time.time()
        expired = [k for k, (exp, _) in self._data.items() if now > exp]
        for k in expired:
            self._data.pop(k, None)


# ⚡ CACHE SYSTEM
GLOBAL_SEARCH_CACHE = TTLCache(maxsize=3000, ttl=600)
BUTTONS_CACHE = TTLCache(maxsize=3000, ttl=1800)
USER_LAST_REQ = TTLCache(maxsize=5000, ttl=60)

try:
    from pyrogram.enums import ButtonStyle

    BTN_PRIMARY = getattr(ButtonStyle, "PRIMARY", 1)
    BTN_SUCCESS = getattr(ButtonStyle, "SUCCESS", 3)
    BTN_DANGER = getattr(ButtonStyle, "DANGER", 4)
except ImportError:
    BTN_PRIMARY, BTN_SUCCESS, BTN_DANGER = 1, 3, 4


def create_btn(text, url=None, callback_data=None, style=None):
    kwargs = {"text": text}
    if url:
        kwargs["url"] = url
    if callback_data:
        kwargs["callback_data"] = callback_data
    if style is not None:
        kwargs["style"] = style
    try:
        return InlineKeyboardButton(**kwargs)
    except TypeError:
        kwargs.pop("style", None)
        return InlineKeyboardButton(**kwargs)


# ============================================================
# 🔮 GOD-TIER "ZERO-CLICK" FUZZY SEARCH ENGINE
# ============================================================
def sanitize_search_query(text: str) -> str:
    if not text:
        return ""
    q = text.strip().lower()
    q = re.sub(r"https?://\S+|t\.me/\S+|@\w+", "", q)
    q = re.sub(
        r"(?i)\b(1080p|720p|480p|2160p|4k|mkv|mp4|avi|hdrip|web-?dl|webrip|bluray|brrip|dvdrip|x264|x265|hevc|dual audio|hindi|kannada|telugu|tamil|malayalam|english|subtitles|subs|episodes|season\s*\d+|s\d+e\d+|complete)\b",
        "",
        q,
    )
    # Symbol Immunity: Convert all symbols to spaces for perfect wildcard matching
    q = re.sub(r"[^a-zA-Z0-9]", " ", q)
    active_stops = get_stopwords()
    if active_stops:
        pattern = (
            r"\b(" + "|".join(re.escape(w) for w in active_stops if w.strip()) + r")\b"
        )
        q = re.sub(pattern, " ", q, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", q).strip()


async def god_tier_search(query: str) -> Tuple[list, int, int, str, bool]:
    """
    Returns: (files, offset, total_results, final_search_query, was_auto_corrected)
    """
    clean_query = sanitize_search_query(query)
    if not clean_query:
        return [], 0, 0, query, False

    # LAYER 1: Standard / Any-Order Match
    files, offset, total = await get_search_results(
        clean_query, max_results=10, offset=0, filter=True
    )
    if files:
        return files, offset, total, clean_query, False

    # LAYER 2: Advanced "Zero-Click" Auto-Correct (Fuzzy Matching)
    # If no files found, grab a random sample of 2000 titles from DB to find the closest typo match
    sample_docs = (
        await _Media.collection.find({}, {"file_name": 1})
        .limit(2000)
        .to_list(length=2000)
    )

    # Extract clean text from filenames to compare against the user's typo
    db_titles = list(
        set(
            [
                sanitize_search_query(d.get("file_name", ""))
                for d in sample_docs
                if d.get("file_name")
            ]
        )
    )

    # Mathematical String Comparison (Calculates closest match with >45% accuracy)
    matches = difflib.get_close_matches(clean_query, db_titles, n=1, cutoff=0.45)

    if matches:
        corrected_query = matches[0]
        # Silently execute the search using the mathematically corrected word
        c_files, c_offset, c_total = await get_search_results(
            corrected_query, max_results=10, offset=0, filter=True
        )
        if c_files:
            return c_files, c_offset, c_total, corrected_query, True

    return [], 0, 0, query, False


# ============================================================
# ⏳ LIVE COUNTDOWN AUTO-DELETE ENGINE
# ============================================================
def get_auto_delete_timer() -> int:
    try:
        return int(getattr(info, "AUTO_DELETE_TIME", 0))
    except Exception:
        return 0


async def live_countdown_task(
    client: Client, msg: Message, delay: int, user_msg: Message = None
):
    expire_at = time.time() + delay

    while time.time() < expire_at:
        remaining = int(expire_at - time.time())
        if remaining <= 0:
            break

        m, s = divmod(remaining, 60)
        btn_text = f"⏳ Auto-Delete in {m}m" if m > 0 else f"⏳ Auto-Delete in {s}s"

        try:
            new_kbd = []
            if msg.reply_markup and msg.reply_markup.inline_keyboard:
                for row in msg.reply_markup.inline_keyboard:
                    clean_row = [b for b in row if "⏳ Auto-Delete" not in b.text]
                    if clean_row:
                        new_kbd.append(clean_row)

            new_kbd.append([InlineKeyboardButton(btn_text, callback_data="noop_timer")])
            new_markup = InlineKeyboardMarkup(new_kbd)

            await client.edit_message_reply_markup(
                chat_id=msg.chat.id, message_id=msg.id, reply_markup=new_markup
            )
            msg.reply_markup = new_markup
        except FloodWait as e:
            await asyncio.sleep(e.value + 1)
            continue
        except Exception:
            pass

        # Update UI every 60s, then every 15s when close to deletion
        sleep_time = 60 if remaining > 60 else 15
        await asyncio.sleep(min(sleep_time, remaining))

    try:
        await msg.delete()
    except Exception:
        pass
    if user_msg:
        try:
            await user_msg.delete()
        except Exception:
            pass


def schedule_auto_delete(
    client: Client, bot_msg: Message, delay: int, user_msg: Message = None
):
    if delay <= 0:
        return
    asyncio.create_task(live_countdown_task(client, bot_msg, delay, user_msg))


async def _send_not_found(msg: Message, img: Optional[str], text: str):
    k_msg = None
    try:
        final_text, final_markup = parse_text_and_markup(text)
        final_text = final_text or "<b>🚫 File not found.</b>"
        if img:
            try:
                k_msg = await msg.reply_photo(
                    photo=img,
                    caption=final_text,
                    reply_markup=final_markup,
                    parse_mode=enums.ParseMode.HTML,
                )
            except Exception:
                k_msg = await msg.reply_text(
                    text=final_text,
                    reply_markup=final_markup,
                    parse_mode=enums.ParseMode.HTML,
                )
        else:
            k_msg = await msg.reply_text(
                text=final_text,
                reply_markup=final_markup,
                parse_mode=enums.ParseMode.HTML,
            )
    except Exception:
        pass

    if k_msg:
        delete_timer = get_auto_delete_timer()
        if delete_timer > 0:
            schedule_auto_delete(msg._client, k_msg, delete_timer, msg)


# ============================================================
# 📁 CORE AUTO FILTER ENGINE
# ============================================================
async def auto_filter(client: Client, msg: Message):
    try:
        b_set = await get_bot_settings()
        auto_img = b_set.get("auto_img")

        if (
            not msg
            or not msg.text
            or msg.text.startswith(("/", "!", "#", ".", ",", "?", "@"))
        ):
            return

        search = msg.text
        search = re.sub(r"https?://\S+|t\.me/\S+|@\w+", "", search).strip()
        if not search:
            return

        settings = await get_settings(msg.chat.id)

        # 🔮 INITIATE GOD-TIER SEARCH ENGINE
        cache_key = search.lower()
        cached_data = GLOBAL_SEARCH_CACHE.get(cache_key)

        if cached_data:
            files, offset, total_results, search_query, was_corrected = cached_data
        else:
            files, offset, total_results, search_query, was_corrected = (
                await god_tier_search(search)
            )
            if files:
                GLOBAL_SEARCH_CACHE.set(
                    cache_key,
                    (files, offset, total_results, search_query, was_corrected),
                )

        if not files:
            fnf_img = b_set.get("not_found_img", getattr(info, "NOT_FOUND_IMG", None))
            fnf_txt = b_set.get(
                "not_found_text",
                getattr(info, "NOT_FOUND_MSG", "<b>🚫 File not found.</b>"),
            )
            return await _send_not_found(msg, fnf_img, fnf_txt)

        # Exact Size Sorting (Largest First)
        files.sort(
            key=lambda x: (
                x.get("file_size", 0)
                if isinstance(x, dict)
                else getattr(x, "file_size", 0)
            ),
            reverse=True,
        )

        pre = "filep" if settings.get("file_secure", False) else "file"
        btn = []
        bot_username = temp.U_NAME or (await client.get_me()).username or "bot"
        mention = msg.from_user.mention if msg.from_user else "User"

        # Dynamic Header based on Auto-Correction
        if was_corrected:
            cap = f"<b>Hᴇʏ {mention} 👋🏻\n\n🪄 Aᴜᴛᴏ-Cᴏʀʀᴇᴄᴛᴇᴅ: <del>{search.title()}</del> ➔ <code>{search_query.title()}</code>\n➤ Yᴏᴜʀ Fɪʟᴇꜱ Rᴇᴀᴅʏ Nᴏᴡ 👇</b>"
        else:
            cap = f"<b>Hᴇʏ {mention} 👋🏻\n\n➤ Tɪᴛʟᴇ : <code>{search_query.title()}</code>\n➤ Yᴏᴜʀ Fɪʟᴇꜱ Rᴇᴀᴅʏ Nᴏᴡ 👇</b>"

        key = f"{msg.chat.id}-{msg.id}"
        BUTTONS_CACHE.set(
            key, search_query
        )  # Save the successfully matched query for Pagination
        req = msg.from_user.id if msg.from_user else 0

        clean_words = await get_clean_words()

        btn.insert(
            0,
            [
                create_btn(
                    text="• Bᴀᴄᴋ Uᴘ Cʜᴀɴɴᴇʟ •",
                    url="https://t.me/KR_Picture",
                    style=BTN_SUCCESS,
                )
            ],
        )

        for file in files:
            file_id = str(
                file.get("file_id", "")
                if isinstance(file, dict)
                else getattr(file, "file_id", "")
            )
            raw_name = str(
                file.get("file_name", "Unknown")
                if isinstance(file, dict)
                else getattr(file, "file_name", "Unknown")
            )
            file_size = int(
                file.get("file_size", 0)
                if isinstance(file, dict)
                else getattr(file, "file_size", 0)
            )

            display_name = clean_filename(raw_name, clean_words)
            size_str = get_size(file_size)
            url_payload = f"https://t.me/{bot_username}?start={pre}_{file_id}"

            if settings.get("button", False):
                btn.append(
                    [create_btn(text=f"{size_str} | {display_name}", url=url_payload)]
                )
            else:
                btn.append(
                    [
                        create_btn(text=f"{display_name}", url=url_payload),
                        create_btn(text=f"{size_str}", url=url_payload),
                    ]
                )

        try:
            total_results = int(total_results)
        except Exception:
            total_results = 0
        total_pages = math.ceil(total_results / 10) if total_results > 0 else 1

        if offset:
            btn.append(
                [
                    create_btn(
                        text=f"1/{total_pages}",
                        callback_data="pages",
                        style=BTN_SUCCESS,
                    ),
                    create_btn(
                        text="NEXT ➡️",
                        callback_data=f"next_{req}_{key}_{offset}",
                        style=BTN_PRIMARY,
                    ),
                ]
            )
        else:
            btn.append(
                [create_btn(text="1/1", callback_data="pages", style=BTN_SUCCESS)]
            )

        final_caption, final_markup = parse_text_and_markup(
            cap, InlineKeyboardMarkup(btn)
        )

        m = None
        try:
            if auto_img and str(auto_img).startswith("http"):
                m = await msg.reply_photo(
                    photo=auto_img,
                    caption=final_caption,
                    reply_markup=final_markup,
                    parse_mode=enums.ParseMode.HTML,
                )
            else:
                m = await msg.reply_text(
                    final_caption,
                    reply_markup=final_markup,
                    parse_mode=enums.ParseMode.HTML,
                )
        except FloodWait as e:
            await asyncio.sleep(e.value + 1)
            try:
                m = await msg.reply_text(
                    final_caption,
                    reply_markup=final_markup,
                    parse_mode=enums.ParseMode.HTML,
                )
            except Exception:
                return
        except Exception:
            return

        # ⚡ INJECT LIVE COUNTDOWN
        delete_timer = get_auto_delete_timer()
        if delete_timer > 0 and m:
            schedule_auto_delete(client, m, delete_timer, msg)

    except Exception as e:
        logger.error(f"Fatal error in auto_filter: {e}")


@Client.on_message(filters.group & filters.text & filters.incoming)
async def give_filter(client: Client, message: Message):
    if getattr(info, "REPAIR_MODE", False):
        if not message.from_user or str(message.from_user.id) not in [
            str(a) for a in getattr(info, "ADMINS", [])
        ]:
            return

    user_id = message.from_user.id if message.from_user else 0
    if user_id and await _plugin_db.is_banned(user_id):
        return

    if user_id != 0:
        last_req = USER_LAST_REQ.get(str(user_id))
        if last_req and (time.time() - last_req) < 2.0:
            return
        USER_LAST_REQ.set(str(user_id), time.time())

    try:
        await auto_filter(client, message)
    except Exception as e:
        logger.error(f"give_filter top-level error: {e}")


# ============================================================
# 🎛️ INLINE CALLBACK HANDLERS (PAGINATION & TIMER)
# ============================================================
@Client.on_callback_query(filters.regex(r"^(next_|noop_timer)"))
async def pagination_and_timer_handler(bot: Client, query: CallbackQuery):
    if query.data == "noop_timer":
        return await query.answer(
            "⏳ This file will be automatically deleted when the timer hits zero to protect from copyrights!",
            show_alert=True,
        )

    # Pagination Handler
    try:
        _, req, key, offset_str = query.data.split("_", 3)
    except ValueError:
        return await query.answer("Invalid button data!", show_alert=True)

    if int(req) not in [query.from_user.id, 0]:
        return await query.answer(
            "⚠️ That's not for you! Request your own file in the group.",
            show_alert=True,
        )

    offset = int(offset_str) if offset_str.isdigit() else 0
    search = BUTTONS_CACHE.get(key)
    if not search:
        return await query.answer(
            "⌛ This search expired. Please type the movie name again!", show_alert=True
        )

    files, n_offset, total = await get_search_results(
        search, max_results=10, offset=offset, filter=True
    )
    if not files:
        return await query.answer("No more files found.", show_alert=True)

    files.sort(
        key=lambda x: (
            x.get("file_size", 0) if isinstance(x, dict) else getattr(x, "file_size", 0)
        ),
        reverse=True,
    )
    settings = await get_settings(query.message.chat.id)
    btn = []
    bot_username = temp.U_NAME or (await bot.get_me()).username or "bot"
    pre = "filep" if settings.get("file_secure", False) else "file"
    clean_words = await get_clean_words()

    btn.insert(
        0,
        [
            create_btn(
                text="• Bᴀᴄᴋ Uᴘ Cʜᴀɴɴᴇʟ •",
                url="https://t.me/KR_Picture",
                style=BTN_SUCCESS,
            )
        ],
    )

    for file in files:
        file_id = str(
            file.get("file_id", "")
            if isinstance(file, dict)
            else getattr(file, "file_id", "")
        )
        raw_name = str(
            file.get("file_name", "Unknown")
            if isinstance(file, dict)
            else getattr(file, "file_name", "Unknown")
        )
        file_size = int(
            file.get("file_size", 0)
            if isinstance(file, dict)
            else getattr(file, "file_size", 0)
        )

        display_name = clean_filename(raw_name, clean_words)
        size_str = get_size(file_size)
        url_payload = f"https://t.me/{bot_username}?start={pre}_{file_id}"

        if settings.get("button", False):
            btn.append(
                [create_btn(text=f"{size_str} | {display_name}", url=url_payload)]
            )
        else:
            btn.append(
                [
                    create_btn(text=f"{display_name}", url=url_payload),
                    create_btn(text=f"{size_str}", url=url_payload),
                ]
            )

    if 0 < offset <= 10:
        off_set = 0
    elif offset == 0:
        off_set = None
    else:
        off_set = offset - 10

    try:
        total = int(total)
    except Exception:
        total = 0

    total_pages = math.ceil(total / 10) if total > 0 else 1
    current_page = math.ceil(offset / 10) + 1 if offset > 0 else 1

    nav_row = []
    if not n_offset:
        nav_row = [
            create_btn(
                "⬅️ BACK",
                callback_data=f"next_{req}_{key}_{off_set}",
                style=BTN_PRIMARY,
            ),
            create_btn(
                f"Pages {current_page} / {total_pages}",
                callback_data="pages",
                style=BTN_SUCCESS,
            ),
        ]
    elif off_set is None:
        nav_row = [
            create_btn(
                f"{current_page} / {total_pages}",
                callback_data="pages",
                style=BTN_SUCCESS,
            ),
            create_btn(
                "NEXT ➡️",
                callback_data=f"next_{req}_{key}_{n_offset}",
                style=BTN_PRIMARY,
            ),
        ]
    else:
        nav_row = [
            create_btn(
                "⬅️ BACK",
                callback_data=f"next_{req}_{key}_{off_set}",
                style=BTN_PRIMARY,
            ),
            create_btn(
                f"{current_page} / {total_pages}",
                callback_data="pages",
                style=BTN_SUCCESS,
            ),
            create_btn(
                "NEXT ➡️",
                callback_data=f"next_{req}_{key}_{n_offset}",
                style=BTN_PRIMARY,
            ),
        ]

    btn.append(nav_row)

    # Re-apply the live countdown button if it existed on the previous page
    if query.message.reply_markup and query.message.reply_markup.inline_keyboard:
        for row in query.message.reply_markup.inline_keyboard:
            for b in row:
                if "⏳ Auto-Delete" in b.text:
                    btn.append(
                        [InlineKeyboardButton(b.text, callback_data="noop_timer")]
                    )
                    break

    try:
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(btn))
    except (MessageNotModified, MessageIdInvalid, ButtonUrlInvalid):
        pass
    except FloodWait as e:
        await asyncio.sleep(e.value + 1)
        try:
            await query.edit_message_reply_markup(
                reply_markup=InlineKeyboardMarkup(btn)
            )
        except Exception:
            pass
    try:
        await query.answer()
    except QueryIdInvalid:
        pass
