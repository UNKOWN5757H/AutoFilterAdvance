import ast
import asyncio
import difflib
import html
import inspect
import math
import re
import time
from logging import ERROR, getLogger
from typing import Dict, Optional, Tuple

from motor.motor_asyncio import AsyncIOMotorClient
from pyrogram import Client, enums, filters
from pyrogram.errors import (
    ButtonUrlInvalid,
    FloodWait,
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
from database.filters_mdb import add_filter, delete_filter, find_filter, get_filters
from database.ia_filterdb import Media as _Media
from database.ia_filterdb import get_search_results
from utils import get_settings, get_size, parse_text_and_markup, temp

# Safe optional imports
try:
    from database.plugin_dbs import plugin_db as _plugin_db
except ImportError:
    _plugin_db = None

try:
    from plugins.custom_settings import get_bot_settings, get_stopwords
except ImportError:
    try:
        from custom_settings import get_bot_settings, get_stopwords
    except ImportError:

        async def get_bot_settings():
            return {}

        def get_stopwords():
            return []


logger = getLogger(__name__)
logger.setLevel(ERROR)

# Strong reference set so Python's garbage collector never cancels sleeping auto-delete tasks
AUTO_DELETE_TASKS = set()

# ============================================================
# 🎨 SAFE TELEGRAM BUTTON STYLE DETECTION
# ============================================================
BTN_PRIMARY = None
BTN_SUCCESS = None
BTN_DANGER = None
_SUPPORTS_BTN_STYLE = False

try:
    from pyrogram.enums import ButtonStyle

    if "style" in inspect.signature(InlineKeyboardButton.__init__).parameters:
        BTN_PRIMARY = getattr(ButtonStyle, "PRIMARY", None)
        BTN_SUCCESS = getattr(ButtonStyle, "SUCCESS", None)
        BTN_DANGER = getattr(ButtonStyle, "DANGER", None)
        _SUPPORTS_BTN_STYLE = True
except (ImportError, ValueError, TypeError):
    BTN_PRIMARY = BTN_SUCCESS = BTN_DANGER = None
    _SUPPORTS_BTN_STYLE = False


def _normalize_style(style):
    if not _SUPPORTS_BTN_STYLE or style is None:
        return None
    if hasattr(style, "value"):
        return style
    if isinstance(style, int):
        return {
            1: BTN_PRIMARY,
            3: BTN_SUCCESS,
            4: BTN_DANGER,
        }.get(style, None)
    return None


def create_btn(text, url=None, callback_data=None, style=None):
    kwargs = {"text": str(text)}
    if url:
        kwargs["url"] = str(url).strip()
    elif callback_data:
        kwargs["callback_data"] = str(callback_data)[:64]

    norm_style = _normalize_style(style)
    if _SUPPORTS_BTN_STYLE and norm_style is not None:
        kwargs["style"] = norm_style
    try:
        return InlineKeyboardButton(**kwargs)
    except Exception:
        kwargs.pop("style", None)
        return InlineKeyboardButton(**kwargs)


# ============================================================
# ⚡ GLOBAL CONFIG & MONGODB SETUP
# ============================================================
cw_db = None
_BOT_DB = None
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


def get_auto_delete_timer(
    var_name: str = "AUTO_DELETE_TIME", default_time: int = 1800
) -> int:
    """Safely parses the auto-delete timer from info.py without throwing TypeErrors."""
    try:
        global_switch = getattr(info, "AUTO_DELETE", True)
        if str(global_switch).strip().lower() in ["false", "off", "0", "no"]:
            return 0
        raw_val = getattr(
            info,
            var_name,
            getattr(
                info,
                "AUTO_DELETE_TIME",
                getattr(info, "FILE_AUTO_DELETE", default_time),
            ),
        )
        if isinstance(raw_val, bool):
            return default_time if raw_val else 0
        val = int(str(raw_val).strip())
        return max(0, val)
    except Exception:
        return default_time


def format_duration(seconds: int) -> str:
    if seconds <= 0:
        return "0 Seconds"
    m, s = divmod(int(seconds), 60)
    if m > 0 and s > 0:
        return f"{m} Minute{'s' if m != 1 else ''} {s} Second{'s' if s != 1 else ''}"
    if m > 0:
        return f"{m} Minute{'s' if m != 1 else ''}"
    return f"{s} Second{'s' if s != 1 else ''}"


# ============================================================
# 👑 SMART AUTHORIZATION & UNBREAKABLE CONNECTION ENGINE
# ============================================================
def get_admin_list():
    raw_admins = getattr(info, "ADMINS", [])
    if isinstance(raw_admins, (str, int)):
        raw_admins = str(raw_admins).replace(",", " ").split()
    elif isinstance(raw_admins, (list, tuple, set)):
        raw_admins = list(raw_admins)
    else:
        raw_admins = []
    return [int(x) for x in raw_admins if str(x).strip().lstrip("-").isdigit()]


async def is_global_admin(user_id: int) -> bool:
    if not user_id:
        return False
    return int(user_id) in get_admin_list()


async def is_user_banned(user_id: int) -> bool:
    if not user_id:
        return False
    if hasattr(temp, "BANNED_USERS") and int(user_id) in temp.BANNED_USERS:
        return True
    if _plugin_db is not None and hasattr(_plugin_db, "is_banned"):
        try:
            return bool(await _plugin_db.is_banned(int(user_id)))
        except Exception:
            pass
    return False


async def get_active_connection(user_id: str) -> Optional[int]:
    """Checks all possible connection tables so PM connected commands never fail."""
    uid_str = str(user_id)

    # 1. Check native active_connections collection first
    if _BOT_DB is not None:
        try:
            doc = await _BOT_DB["active_connections"].find_one({"user_id": uid_str})
            if doc and doc.get("group_id"):
                return int(doc["group_id"])
        except Exception:
            pass

    # 2. Check database.connections_mdb.active_connection if available
    try:
        from database.connections_mdb import active_connection

        conn = await active_connection(uid_str)
        if conn:
            return int(conn)
    except Exception:
        pass

    # 3. Check database.connections_mdb (all_connections + if_active)
    try:
        from database.connections_mdb import all_connections, if_active

        groupids = await all_connections(uid_str)
        if groupids:
            for gid in groupids:
                if await if_active(uid_str, str(gid)):
                    return int(gid)
            return int(groupids[-1])
    except Exception:
        pass

    # 4. Check CONNECTION collection directly
    if _BOT_DB is not None:
        try:
            doc = await _BOT_DB["CONNECTION"].find_one({"_id": uid_str})
            if doc and doc.get("active_group"):
                return int(doc["active_group"])
        except Exception:
            pass

    return None


async def get_target_chat(client: Client, message: Message) -> Optional[int]:
    if message.chat.type == enums.ChatType.PRIVATE:
        if not message.from_user:
            return None
        return await get_active_connection(str(message.from_user.id))
    return message.chat.id


async def verify_admin(
    client: Client, message: Message, target_chat_id: Optional[int] = None
) -> bool:
    uid = (
        message.from_user.id
        if message.from_user
        else getattr(message.sender_chat, "id", 0)
    )
    if await is_global_admin(uid):
        return True

    if message.chat.type == enums.ChatType.PRIVATE:
        if not target_chat_id:
            return False
        try:
            member = await client.get_chat_member(int(target_chat_id), uid)
            return member.status in [
                enums.ChatMemberStatus.ADMINISTRATOR,
                enums.ChatMemberStatus.OWNER,
            ]
        except Exception:
            return False

    if message.chat.type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
        if message.sender_chat and message.sender_chat.id == message.chat.id:
            return True
        if message.from_user:
            try:
                member = await client.get_chat_member(message.chat.id, uid)
                return member.status in [
                    enums.ChatMemberStatus.ADMINISTRATOR,
                    enums.ChatMemberStatus.OWNER,
                ]
            except Exception:
                return False
    return False


async def safe_save_filter(group_id, keyword, reply_text, btn, fileid, alert="[]"):
    """Handles any parameter order of add_filter in database/filters_mdb.py."""
    try:
        params = list(inspect.signature(add_filter).parameters.keys())
        if len(params) >= 6 and params[4] == "alert":
            await add_filter(group_id, keyword, reply_text, btn, alert, fileid)
        else:
            await add_filter(group_id, keyword, reply_text, btn, fileid, alert)
    except Exception:
        await add_filter(group_id, keyword, reply_text, btn, fileid, alert)


# ============================================================
# ⚡ CACHE SYSTEM
# ============================================================
class TTLCache:
    def __init__(self, maxsize: int = 2000, ttl: int = 1800):
        self._data: Dict[str, Tuple[float, any]] = {}
        self._maxsize, self._ttl = maxsize, ttl

    def set(self, key: str, value: any):
        self._cleanup()
        if len(self._data) >= self._maxsize:
            oldest_key = min(self._data, key=lambda k: self._data[k][0])
            self._data.pop(oldest_key, None)
        self._data[key] = (time.time() + self._ttl, value)

    def get(self, key: str) -> Optional[any]:
        if not (item := self._data.get(key)):
            return None
        if time.time() > item[0]:
            self._data.pop(key, None)
            return None
        return item[1]

    def _cleanup(self):
        now = time.time()
        for k in [k for k, (exp, _) in self._data.items() if now > exp]:
            self._data.pop(k, None)


GLOBAL_SEARCH_CACHE = TTLCache(maxsize=3000, ttl=600)
BUTTONS_CACHE = TTLCache(maxsize=3000, ttl=1800)
USER_LAST_REQ = TTLCache(maxsize=5000, ttl=60)


# ============================================================
# 🔮 GOD-TIER "ZERO-CLICK" FUZZY SEARCH ENGINE
# ============================================================
def sanitize_search_query(text: str) -> str:
    if not text:
        return ""
    q = re.sub(r"https?://\S+|t\.me/\S+|@\w+", "", text.strip().lower())
    q = re.sub(
        r"(?i)\b(1080p|720p|480p|2160p|4k|mkv|mp4|avi|hdrip|web-?dl|webrip|bluray|brrip|dvdrip|x264|x265|hevc|dual audio|hindi|kannada|telugu|tamil|malayalam|english|subtitles|subs|episodes|season\s*\d+|s\d+e\d+|complete)\b",
        "",
        q,
    )
    q = re.sub(r"[^a-zA-Z0-9]", " ", q)
    if active_stops := get_stopwords():
        q = re.sub(
            r"\b(" + "|".join(re.escape(w) for w in active_stops if w.strip()) + r")\b",
            " ",
            q,
            flags=re.IGNORECASE,
        )
    return re.sub(r"\s+", " ", q).strip()


async def god_tier_search(query: str) -> Tuple[list, int, int, str, bool]:
    clean_query = sanitize_search_query(query)
    if not clean_query:
        return [], 0, 0, query, False

    is_short_query = len(clean_query) <= 2

    files, offset, total = await get_search_results(
        clean_query, max_results=10, offset=0, filter=True
    )
    if files:
        return files, offset, total, clean_query, False

    if is_short_query:
        return [], 0, 0, query, False

    try:
        media_col = getattr(_Media, "collection", _Media)
        sample_docs = (
            await media_col.find({}, {"file_name": 1})
            .limit(2000)
            .to_list(length=2000)
        )
        db_titles = list(
            set(
                [
                    sanitize_search_query(d.get("file_name", ""))
                    for d in sample_docs
                    if d.get("file_name")
                ]
            )
        )

        if matches := difflib.get_close_matches(
            clean_query, db_titles, n=1, cutoff=0.55
        ):
            corrected_query = matches[0]
            c_files, c_offset, c_total = await get_search_results(
                corrected_query, max_results=10, offset=0, filter=True
            )
            if c_files:
                return c_files, c_offset, c_total, corrected_query, True
    except Exception as e:
        logger.error(f"Fuzzy search fallback error: {e}")

    return [], 0, 0, query, False


# ============================================================
# ⏳ RELIABLE AUTO-DELETE ENGINE (GROUP + PM)
# ============================================================
async def _auto_delete_worker(
    client: Client, chat_id: int, is_pm: bool, delay: int, *messages
):
    await asyncio.sleep(delay)

    msg_ids = [m.id for m in messages if m is not None and hasattr(m, "id") and m.id]
    if msg_ids:
        try:
            await client.delete_messages(chat_id, msg_ids)
        except Exception:
            for m in messages:
                if m is not None:
                    try:
                        await m.delete()
                    except Exception:
                        pass

    if is_pm:
        notify_text = (
            "<b>Successfully deleted your file, if you want request again in group.</b>"
        )
        markup = InlineKeyboardMarkup(
            [
                [
                    create_btn(
                        "Movie Request 📝",
                        url="https://t.me/Sandalwood_Kannada_Group",
                        style=BTN_SUCCESS,
                    )
                ]
            ]
        )
        try:
            await client.send_message(
                chat_id,
                text=notify_text,
                reply_markup=markup,
                parse_mode=enums.ParseMode.HTML,
            )
        except Exception:
            pass


def schedule_auto_delete(
    client: Client, chat_id: int, is_pm: bool, delay: int, *messages
):
    if delay <= 0:
        return
    task = asyncio.create_task(
        _auto_delete_worker(client, chat_id, is_pm, delay, *messages)
    )
    AUTO_DELETE_TASKS.add(task)
    task.add_done_callback(AUTO_DELETE_TASKS.discard)


async def _send_not_found(client: Client, msg: Message, img: Optional[str], text: str):
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

    delete_timer = get_auto_delete_timer("AUTO_DELETE_TIME", 1800)
    if delete_timer > 0 and k_msg:
        schedule_auto_delete(client, msg.chat.id, False, delete_timer, k_msg, msg)


# ============================================================
# 📁 CORE AUTO FILTER ENGINE (USER-FRIENDLY & FAST)
# ============================================================
async def auto_filter(client: Client, msg: Message):
    try:
        b_set = await get_bot_settings()
        if (
            not msg
            or not msg.text
            or msg.text.startswith(("/", "!", "#", ".", ",", "?", "@"))
        ):
            return

        search = re.sub(r"https?://\S+|t\.me/\S+|@\w+", "", msg.text).strip()
        if not search:
            return

        # Ignore common conversational greetings in groups
        if search.lower() in [
            "hello",
            "hey",
            "hlo",
            "hlw",
            "ok",
            "okay",
            "k",
            "thanks",
            "tq",
            "yes",
            "no",
            "yo",
            "hmm",
            "hm",
            "gm",
            "gn",
            "good morning",
        ]:
            return

        settings = await get_settings(msg.chat.id)
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
            return await _send_not_found(client, msg, fnf_img, fnf_txt)

        files.sort(
            key=lambda x: (
                x.get("file_size", 0)
                if isinstance(x, dict)
                else getattr(x, "file_size", 0)
            ),
            reverse=True,
        )

        try:
            total_results = int(total_results)
        except Exception:
            total_results = len(files)

        total_pages = math.ceil(total_results / 10) if total_results > 0 else 1
        pre = "filep" if settings.get("file_secure", False) else "file"
        btn = []
        bot_username = temp.U_NAME or (await client.get_me()).username or "bot"
        mention = msg.from_user.mention if msg.from_user else "User"

        safe_orig_title = html.escape(search.title())
        safe_corr_title = html.escape(search_query.title())

        cap = (
            f"<b>Hᴇʏ {mention} 👋🏻\n\n"
            f"🪄 Aᴜᴛᴏ-Cᴏʀʀᴇᴄᴛᴇᴅ : <del>{safe_orig_title}</del> ➔ <code>{safe_corr_title}</code>\n"
            f"📂 Tᴏᴛᴀʟ Fɪʟᴇꜱ : <code>{total_results}</code>\n"
            f"➤ Yᴏᴜʀ Fɪʟᴇꜱ Rᴇᴀᴅʏ Nᴏᴡ 👇</b>"
            if was_corrected
            else f"<b>Hᴇʏ {mention} 👋🏻\n\n"
            f"➤ Tɪᴛʟᴇ : <code>{safe_corr_title}</code>\n"
            f"📂 Tᴏᴛᴀʟ Fɪʟᴇꜱ : <code>{total_results}</code>\n"
            f"➤ Yᴏᴜʀ Fɪʟᴇꜱ Rᴇᴀᴅʏ Nᴏᴡ 👇</b>"
        )

        key = f"{msg.chat.id}-{msg.id}"
        BUTTONS_CACHE.set(key, search_query)
        req = msg.from_user.id if msg.from_user else 0
        clean_words = await get_clean_words()

        btn.append(
            [
                create_btn(
                    text="• Bᴀᴄᴋ Uᴘ Cʜᴀɴɴᴇʟ •",
                    url="https://t.me/KR_Picture",
                    style=BTN_SUCCESS,
                )
            ]
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

        if offset:
            btn.append(
                [
                    create_btn(
                        text=f"📄 1/{total_pages}",
                        callback_data=f"pages#1#{total_pages}#{total_results}",
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
                [
                    create_btn(
                        text="📄 1/1",
                        callback_data=f"pages#1#1#{total_results}",
                        style=BTN_SUCCESS,
                    )
                ]
            )

        final_caption, final_markup = parse_text_and_markup(
            cap, InlineKeyboardMarkup(btn)
        )
        m = None
        auto_img = b_set.get("auto_img", getattr(info, "AUTO_IMG", None))

        try:
            if auto_img and str(auto_img).lower() != "none":
                try:
                    m = await msg.reply_photo(
                        photo=auto_img,
                        caption=final_caption,
                        reply_markup=final_markup,
                        parse_mode=enums.ParseMode.HTML,
                    )
                except Exception:
                    m = await msg.reply_text(
                        final_caption,
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
        except Exception as e:
            logger.error(f"Failed sending auto_filter message: {e}")
            return

        delete_timer = get_auto_delete_timer("AUTO_DELETE_TIME", 1800)
        if delete_timer > 0 and m:
            time_str = format_duration(delete_timer)
            warn_text = (
                f"<b>📢 Please Note\n\n"
                f"✅ The above file will be autodeleted in {time_str} to avoid copyright issues.\n\n"
                f"✅ Please forward this file to your saved messages and start downloading from there.\n\n"
                f"Tᴇᴀᴍ: @KR_Picture</b>"
            )
            warn_msg = None
            try:
                warn_msg = await client.send_message(
                    chat_id=msg.chat.id,
                    text=warn_text,
                    reply_to_message_id=m.id,
                    parse_mode=enums.ParseMode.HTML,
                )
            except Exception:
                pass

            is_pm = msg.chat.type == enums.ChatType.PRIVATE
            schedule_auto_delete(
                client, msg.chat.id, is_pm, delete_timer, msg, m, warn_msg
            )

    except Exception as e:
        logger.error(f"Fatal error in auto_filter: {e}")


# ============================================================
# ⚡ UNIFIED GROUP MESSAGE HANDLER (CUSTOM FILTERS + AUTO FILTER)
# ============================================================
@Client.on_message(
    filters.group
    & filters.text
    & filters.incoming
    & ~filters.bot
    & ~filters.regex(r"^[/!#.,?@]"),
    group=-1,
)
async def give_filter(client: Client, message: Message):
    if not message.text:
        return

    if getattr(info, "REPAIR_MODE", False) and not await verify_admin(
        client, message, message.chat.id
    ):
        return

    user_id = message.from_user.id if message.from_user else 0
    if user_id and await is_user_banned(user_id):
        return

    if user_id != 0:
        if (last_req := USER_LAST_REQ.get(str(user_id))) and (
            time.time() - last_req
        ) < 2.0:
            return
        USER_LAST_REQ.set(str(user_id), time.time())

    try:
        # 1. Check if a custom manual filter matches first
        matched_manual = await manual_filters(client, message)
        if matched_manual:
            return
        # 2. Otherwise run the Movie Auto-Filter search
        await auto_filter(client, message)
    except Exception as e:
        logger.error(f"give_filter top-level error: {e}")


# ============================================================
# 🎛️ INLINE CALLBACK HANDLERS (PAGINATION & PAGES)
# ============================================================
@Client.on_callback_query(
    filters.regex(r"^(next_|pages|delallconfirm|delallcancel)"),
    group=-2,
)
async def pagination_handler(bot: Client, query: CallbackQuery):
    data = query.data

    if data.startswith("pages"):
        parts = data.split("#")
        if len(parts) == 4:
            _, cur_p, tot_p, tot_f = parts
            return await query.answer(
                f"📄 Page {cur_p} of {tot_p} • Total Files: {tot_f}",
                show_alert=False,
            )
        return await query.answer("📄 Current Page Indicator", show_alert=False)

    if data == "delallcancel":
        await query.answer("Cancelled.")
        try:
            await query.message.delete()
        except Exception:
            pass
        return

    if data.startswith("delallconfirm#"):
        target_chat_id = int(data.split("#")[1])
        uid = query.from_user.id if query.from_user else 0
        if not await is_global_admin(uid):
            try:
                member = await bot.get_chat_member(target_chat_id, uid)
                if member.status not in [
                    enums.ChatMemberStatus.ADMINISTRATOR,
                    enums.ChatMemberStatus.OWNER,
                ]:
                    return await query.answer("❌ Unauthorized!", show_alert=True)
            except Exception:
                return await query.answer("❌ Unauthorized!", show_alert=True)

        keywords = await get_filters(target_chat_id)
        for kw in keywords:
            await delete_filter(query.message, kw, target_chat_id)
        await query.answer("✅ All filters deleted!", show_alert=True)
        return await query.message.edit_text(
            f"🗑️ <b>Deleted all filters for chat:</b> <code>{target_chat_id}</code>",
            parse_mode=enums.ParseMode.HTML,
        )

    try:
        _, req, key, offset_str = data.split("_", 3)
    except ValueError:
        return await query.answer("Invalid button data!", show_alert=True)

    if int(req) not in [query.from_user.id, 0] and not await is_global_admin(
        query.from_user.id
    ):
        return await query.answer(
            "⚠️ That's not for you! Request your own movie in the group.",
            show_alert=True,
        )

    offset = int(offset_str) if offset_str.isdigit() else 0
    if not (search := BUTTONS_CACHE.get(key)):
        return await query.answer(
            "⌛ This search expired. Please type the movie name again!",
            show_alert=True,
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
    btn, bot_username = [], temp.U_NAME or (await bot.get_me()).username or "bot"
    pre = "filep" if settings.get("file_secure", False) else "file"
    clean_words = await get_clean_words()

    btn.append(
        [
            create_btn(
                text="• Bᴀᴄᴋ Uᴘ Cʜᴀɴɴᴇʟ •",
                url="https://t.me/KR_Picture",
                style=BTN_SUCCESS,
            )
        ]
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

    off_set = 0 if 0 < offset <= 10 else None if offset == 0 else offset - 10
    try:
        total = int(total)
    except Exception:
        total = 0
    total_pages = math.ceil(total / 10) if total > 0 else 1
    current_page = math.ceil(offset / 10) + 1 if offset > 0 else 1
    page_cb = f"pages#{current_page}#{total_pages}#{total}"

    if not n_offset:
        nav_row = [
            create_btn(
                "⬅️ BACK",
                callback_data=f"next_{req}_{key}_{off_set}",
                style=BTN_PRIMARY,
            ),
            create_btn(
                f"📄 {current_page}/{total_pages}",
                callback_data=page_cb,
                style=BTN_SUCCESS,
            ),
        ]
    elif off_set is None:
        nav_row = [
            create_btn(
                f"📄 {current_page}/{total_pages}",
                callback_data=page_cb,
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
                f"📄 {current_page}/{total_pages}",
                callback_data=page_cb,
                style=BTN_SUCCESS,
            ),
            create_btn(
                "NEXT ➡️",
                callback_data=f"next_{req}_{key}_{n_offset}",
                style=BTN_PRIMARY,
            ),
        ]

    btn.append(nav_row)

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


# ============================================================
# 🎨 KEYBOARD AND BUTTON PARSERS
# ============================================================
def build_keyboard(btn_str: str):
    if not btn_str or btn_str in ["[]", "None", "False", ""]:
        return None
    try:
        button_layout = []
        for row in ast.literal_eval(btn_str):
            btn_row = []
            for b in row:
                if isinstance(b, dict):
                    b_copy = b.copy()
                    style_val = b_copy.pop("style", None)
                    btn_row.append(
                        create_btn(
                            text=b_copy.get("text", "Button"),
                            url=b_copy.get("url"),
                            callback_data=b_copy.get("callback_data"),
                            style=style_val,
                        )
                    )
                else:
                    btn_row.append(b)
            button_layout.append(btn_row)
        return button_layout
    except Exception as e:
        logger.error(f"Button parsing error: {e}")
        return None


def parse_markdown_buttons(text: str):
    if not text:
        return "", "[]"
    buttons, clean_lines = [], []
    for line in text.split("\n"):
        row_btns = []
        matches = sorted(
            list(re.finditer(r"\[([^\[\]]+)\]\(([^()]+)\)", line))
            + list(re.finditer(r"\[([^\[\]]+)\|([^()]+)\]", line)),
            key=lambda m: m.start(),
        )
        for match in matches:
            url_val = match.group(2).strip()
            if not url_val.startswith(("http://", "https://", "tg://")):
                url_val = "https://" + url_val
            row_btns.append({"text": match.group(1).strip(), "url": url_val})
        if row_btns:
            buttons.append(row_btns)
        if clean_line := re.sub(
            r"\[([^\[\]]+)\|([^()]+)\]",
            "",
            re.sub(r"\[([^\[\]]+)\]\(([^()]+)\)", "", line),
        ).strip():
            clean_lines.append(clean_line)
        elif not matches:
            clean_lines.append("")
    return "\n".join(clean_lines).strip(), (str(buttons) if buttons else "[]")


# ============================================================
# 🎯 FILTER COMMANDS (HIGH PRIORITY GROUP=-2 SO THEY NEVER FAIL)
# ============================================================
@Client.on_message(filters.command("filter") & filters.incoming, group=-2)
async def add_filter_cmd(client: Client, message: Message):
    target_chat_id = await get_target_chat(client, message)
    if not target_chat_id:
        return await message.reply_text(
            "⚠️ <b>No active connection!</b>\nPlease run <code>/connect &lt;group_id&gt;</code> first.",
            parse_mode=enums.ParseMode.HTML,
        )
    if not await verify_admin(client, message, target_chat_id):
        return await message.reply_text(
            f"❌ <b>You are not authorized for chat:</b> <code>{target_chat_id}</code>",
            parse_mode=enums.ParseMode.HTML,
        )

    if not message.reply_to_message:
        return await message.reply_text(
            "⚠️ <b>Reply to a message (text or media) to set it as a filter.</b>\n"
            "⚙️ <b>Usage:</b> <code>/filter &lt;keyword&gt;</code>",
            parse_mode=enums.ParseMode.HTML,
        )
    if len(message.command) < 2:
        return await message.reply_text(
            "⚙️ <b>Usage:</b> <code>/filter &lt;keyword&gt;</code>",
            parse_mode=enums.ParseMode.HTML,
        )

    keyword = message.text.split(None, 1)[1].lower().strip()
    replied = message.reply_to_message
    raw_content = (
        replied.text.html
        if replied.text and hasattr(replied.text, "html")
        else (
            replied.caption.html
            if replied.caption and hasattr(replied.caption, "html")
            else (replied.text or replied.caption or "")
        )
    )
    text, btn = parse_markdown_buttons(raw_content)

    # If the replied message already has inline buttons and no markdown buttons were parsed
    if btn == "[]" and replied.reply_markup and replied.reply_markup.inline_keyboard:
        existing_btns = []
        for row in replied.reply_markup.inline_keyboard:
            row_btns = []
            for b in row:
                b_dict = {"text": b.text}
                if b.url:
                    b_dict["url"] = b.url
                elif b.callback_data:
                    b_dict["callback_data"] = b.callback_data
                st = getattr(b, "style", None)
                if st:
                    b_dict["style"] = st.value if hasattr(st, "value") else int(st)
                row_btns.append(b_dict)
            if row_btns:
                existing_btns.append(row_btns)
        if existing_btns:
            btn = str(existing_btns)

    fileid = "None"
    for media_attr in ["photo", "video", "document", "audio", "animation", "sticker"]:
        if media_obj := getattr(replied, media_attr, None):
            fileid = media_obj.file_id
            break

    await safe_save_filter(target_chat_id, keyword, text, btn, fileid, "[]")
    out_msg = await message.reply_text(
        f"✅ <b>Filter successfully added!</b>\n\n"
        f"🔑 <b>Keyword:</b> <code>{html.escape(keyword)}</code>\n"
        f"🆔 <b>Chat ID:</b> <code>{target_chat_id}</code>",
        parse_mode=enums.ParseMode.HTML,
    )
    delete_timer = get_auto_delete_timer("AUTO_DELETE_TIME", 1800)
    schedule_auto_delete(client, message.chat.id, False, delete_timer, message, out_msg)


@Client.on_message(filters.command("addfilter") & filters.incoming, group=-2)
async def add_premade_filter_cmd(client: Client, message: Message):
    target_chat_id = await get_target_chat(client, message)
    if not target_chat_id:
        return await message.reply_text(
            "⚠️ <b>No active connection!</b>\nPlease run <code>/connect &lt;group_id&gt;</code> first.",
            parse_mode=enums.ParseMode.HTML,
        )
    if not await verify_admin(client, message, target_chat_id):
        return await message.reply_text(
            f"❌ <b>You are not authorized for chat:</b> <code>{target_chat_id}</code>",
            parse_mode=enums.ParseMode.HTML,
        )

    if not message.reply_to_message:
        return await message.reply_text(
            "⚠️ <b>Reply to a message containing inline buttons.</b>",
            parse_mode=enums.ParseMode.HTML,
        )
    if len(message.command) < 2:
        return await message.reply_text(
            "⚙️ <b>Usage:</b> <code>/addfilter &lt;keyword&gt;</code>",
            parse_mode=enums.ParseMode.HTML,
        )

    keyword = message.text.split(None, 1)[1].lower().strip()
    replied = message.reply_to_message

    buttons = []
    if replied.reply_markup and replied.reply_markup.inline_keyboard:
        for row in replied.reply_markup.inline_keyboard:
            row_btns = []
            for btn in row:
                btn_dict = {"text": btn.text}
                if btn.url:
                    btn_dict["url"] = btn.url
                elif btn.callback_data:
                    btn_dict["callback_data"] = btn.callback_data
                st = getattr(btn, "style", None)
                if st:
                    btn_dict["style"] = st.value if hasattr(st, "value") else int(st)
                row_btns.append(btn_dict)
            if row_btns:
                buttons.append(row_btns)

    fileid = "None"
    for media_attr in ["photo", "video", "document", "audio", "animation", "sticker"]:
        if media_obj := getattr(replied, media_attr, None):
            fileid = media_obj.file_id
            break

    raw_content = (
        replied.text.html
        if replied.text and hasattr(replied.text, "html")
        else (
            replied.caption.html
            if replied.caption and hasattr(replied.caption, "html")
            else (replied.text or replied.caption or "")
        )
    )

    await safe_save_filter(
        target_chat_id,
        keyword,
        raw_content,
        str(buttons) if buttons else "[]",
        fileid,
        "[]",
    )
    out_msg = await message.reply_text(
        f"✅ <b>Filter with buttons added!</b>\n\n<b>Keyword:</b> <code>{html.escape(keyword)}</code>",
        parse_mode=enums.ParseMode.HTML,
    )
    delete_timer = get_auto_delete_timer("AUTO_DELETE_TIME", 1800)
    schedule_auto_delete(client, message.chat.id, False, delete_timer, message, out_msg)


@Client.on_message(filters.command("filterimage") & filters.incoming, group=-2)
async def edit_filter_image_cmd(client: Client, message: Message):
    target_chat_id = await get_target_chat(client, message)
    if not target_chat_id:
        return await message.reply_text(
            "⚠️ <b>No active connection!</b>\nPlease run <code>/connect &lt;group_id&gt;</code> first.",
            parse_mode=enums.ParseMode.HTML,
        )
    if not await verify_admin(client, message, target_chat_id):
        return await message.reply_text(
            f"❌ <b>You are not authorized for chat:</b> <code>{target_chat_id}</code>",
            parse_mode=enums.ParseMode.HTML,
        )

    if not message.reply_to_message or not message.reply_to_message.media:
        return await message.reply_text(
            "⚠️ <b>Reply to a photo, video, or document to set the new image.</b>",
            parse_mode=enums.ParseMode.HTML,
        )
    if len(message.command) < 2:
        return await message.reply_text(
            "⚙️ <b>Usage:</b> <code>/filterimage &lt;keyword&gt;</code>",
            parse_mode=enums.ParseMode.HTML,
        )

    keyword = message.text.split(None, 1)[1].lower().strip()
    reply_text, btn, alert, old_fileid = await find_filter(target_chat_id, keyword)

    if not reply_text and (not old_fileid or old_fileid == "None"):
        return await message.reply_text(
            f"❌ <b>Filter <code>{html.escape(keyword)}</code> not found.</b>",
            parse_mode=enums.ParseMode.HTML,
        )

    fileid = "None"
    for media_attr in ["photo", "video", "document", "audio", "animation", "sticker"]:
        if media_obj := getattr(message.reply_to_message, media_attr, None):
            fileid = media_obj.file_id
            break

    if fileid == "None":
        return await message.reply_text(
            "❌ <b>Could not extract valid media.</b>", parse_mode=enums.ParseMode.HTML
        )

    await safe_save_filter(target_chat_id, keyword, reply_text, btn, fileid, alert)
    out_msg = await message.reply_text(
        f"✅ <b>Filter image updated!</b>\n\n<b>Keyword:</b> <code>{html.escape(keyword)}</code>",
        parse_mode=enums.ParseMode.HTML,
    )
    delete_timer = get_auto_delete_timer("AUTO_DELETE_TIME", 1800)
    schedule_auto_delete(client, message.chat.id, False, delete_timer, message, out_msg)


@Client.on_message(
    filters.command(["editfiltercolur", "editfiltercolour"]) & filters.incoming,
    group=-2,
)
async def edit_filter_colour_cmd(client: Client, message: Message):
    target_chat_id = await get_target_chat(client, message)
    if not target_chat_id:
        return await message.reply_text(
            "⚠️ <b>No active connection!</b>\nPlease run <code>/connect &lt;group_id&gt;</code> first.",
            parse_mode=enums.ParseMode.HTML,
        )
    if not await verify_admin(client, message, target_chat_id):
        return await message.reply_text(
            f"❌ <b>You are not authorized for chat:</b> <code>{target_chat_id}</code>",
            parse_mode=enums.ParseMode.HTML,
        )

    args = message.command
    if len(args) < 4:
        return await message.reply_text(
            "❌ <b>Usage:</b> <code>/editfiltercolour &lt;keyword&gt; &lt;button_number&gt; &lt;colour&gt;</code>\n\n<b>Colours:</b> <code>green</code>, <code>red</code>, <code>blue</code>",
            parse_mode=enums.ParseMode.HTML,
        )

    try:
        btn_num, color_str, keyword = (
            int(args[-2]),
            args[-1].lower(),
            " ".join(args[1:-2]).lower().strip(),
        )
    except ValueError:
        return await message.reply_text(
            "❌ <b>Button number must be an integer.</b>",
            parse_mode=enums.ParseMode.HTML,
        )

    color_map = {"green": 3, "red": 4, "blue": 1}
    if color_str not in color_map:
        return await message.reply_text(
            "❌ <b>Invalid colour.</b> Choose from: <code>green</code>, <code>red</code>, <code>blue</code>.",
            parse_mode=enums.ParseMode.HTML,
        )

    reply_text, btn, alert, fileid = await find_filter(target_chat_id, keyword)
    if not reply_text and (not fileid or fileid == "None"):
        return await message.reply_text(
            f"❌ <b>Filter <code>{html.escape(keyword)}</code> not found.</b>",
            parse_mode=enums.ParseMode.HTML,
        )
    if not btn or btn in ["[]", "None", "False", ""]:
        return await message.reply_text(
            f"❌ <b>Filter <code>{html.escape(keyword)}</code> has no buttons.</b>",
            parse_mode=enums.ParseMode.HTML,
        )

    try:
        button_data = ast.literal_eval(btn)
    except Exception:
        return await message.reply_text(
            "❌ <b>Corrupted button format.</b>", parse_mode=enums.ParseMode.HTML
        )

    count, found = 0, False
    for r_idx, row in enumerate(button_data):
        for c_idx, b in enumerate(row):
            count += 1
            if count == btn_num:
                button_data[r_idx][c_idx]["style"] = color_map[color_str]
                found = True
                break
        if found:
            break

    if not found:
        return await message.reply_text(
            f"❌ <b>Button {btn_num} not found.</b> Filter has {count} buttons.",
            parse_mode=enums.ParseMode.HTML,
        )

    await safe_save_filter(
        target_chat_id, keyword, reply_text, str(button_data), fileid, alert
    )
    out_msg = await message.reply_text(
        f"✅ <b>Filter <code>{html.escape(keyword)}</code> Button {btn_num} colour changed to {color_str.title()}!</b>",
        parse_mode=enums.ParseMode.HTML,
    )
    delete_timer = get_auto_delete_timer("AUTO_DELETE_TIME", 1800)
    schedule_auto_delete(client, message.chat.id, False, delete_timer, message, out_msg)


@Client.on_message(filters.command(["delfilter", "stop"]) & filters.incoming, group=-2)
async def del_filter_cmd(client: Client, message: Message):
    target_chat_id = await get_target_chat(client, message)
    if not target_chat_id:
        return await message.reply_text(
            "⚠️ <b>No active connection!</b>\nPlease run <code>/connect &lt;group_id&gt;</code> first.",
            parse_mode=enums.ParseMode.HTML,
        )
    if not await verify_admin(client, message, target_chat_id):
        return await message.reply_text(
            f"❌ <b>You are not authorized for chat:</b> <code>{target_chat_id}</code>",
            parse_mode=enums.ParseMode.HTML,
        )

    if len(message.command) < 2:
        return await message.reply_text(
            "⚙️ <b>Usage:</b> <code>/delfilter &lt;keyword&gt;</code>",
            parse_mode=enums.ParseMode.HTML,
        )
    keyword = message.text.split(None, 1)[1].lower().strip()
    await delete_filter(message, keyword, target_chat_id)
    out_msg = await message.reply_text(
        f"🗑️ <b>Filter <code>{html.escape(keyword)}</code> deleted.</b>",
        parse_mode=enums.ParseMode.HTML,
    )
    delete_timer = get_auto_delete_timer("AUTO_DELETE_TIME", 1800)
    schedule_auto_delete(client, message.chat.id, False, delete_timer, message, out_msg)


@Client.on_message(filters.command(["delall", "deleteall"]) & filters.incoming, group=-2)
async def del_all_filters_cmd(client: Client, message: Message):
    target_chat_id = await get_target_chat(client, message)
    if not target_chat_id:
        return await message.reply_text(
            "⚠️ <b>No active connection!</b>\nPlease run <code>/connect &lt;group_id&gt;</code> first.",
            parse_mode=enums.ParseMode.HTML,
        )
    if not await verify_admin(client, message, target_chat_id):
        return await message.reply_text(
            f"❌ <b>You are not authorized for chat:</b> <code>{target_chat_id}</code>",
            parse_mode=enums.ParseMode.HTML,
        )

    buttons = [
        [
            create_btn(
                "🔥 Yes, Delete All",
                callback_data=f"delallconfirm#{target_chat_id}",
                style=BTN_DANGER,
            )
        ],
        [create_btn("❌ Cancel", callback_data="delallcancel", style=BTN_PRIMARY)],
    ]
    await message.reply_text(
        f"⚠️ <b>Are you sure you want to delete ALL filters in <code>{target_chat_id}</code>?</b>",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode=enums.ParseMode.HTML,
    )


@Client.on_message(
    filters.command(["listfilters", "filters", "viewfilters"]) & filters.incoming,
    group=-2,
)
async def list_filters_cmd(client: Client, message: Message):
    target_chat_id = await get_target_chat(client, message)
    if not target_chat_id:
        return await message.reply_text(
            "⚠️ <b>No active connection!</b>\nPlease run <code>/connect &lt;group_id&gt;</code> first.",
            parse_mode=enums.ParseMode.HTML,
        )
    if not await verify_admin(client, message, target_chat_id):
        return await message.reply_text(
            f"❌ <b>You are not authorized for chat:</b> <code>{target_chat_id}</code>",
            parse_mode=enums.ParseMode.HTML,
        )

    keywords = await get_filters(target_chat_id)
    if not keywords:
        return await message.reply_text(
            f"⚠️ <b>No active filters found in <code>{target_chat_id}</code>.</b>",
            parse_mode=enums.ParseMode.HTML,
        )

    out_msg = await message.reply_text(
        f"📋 <b>Current Filters ({len(keywords)}):</b>\n\n"
        + "\n".join([f"• <code>{html.escape(str(kw))}</code>" for kw in keywords]),
        parse_mode=enums.ParseMode.HTML,
    )
    delete_timer = get_auto_delete_timer("AUTO_DELETE_TIME", 1800)
    schedule_auto_delete(client, message.chat.id, False, delete_timer, message, out_msg)


# ============================================================
# 📤 4-LAYER MULTI-MEDIA FILTER DISPATCHER
# ============================================================
async def send_filter_media(
    client: Client,
    chat_id: int,
    fileid: str,
    reply_text: str,
    reply_markup,
    reply_id: int,
):
    try:
        return await client.send_cached_media(
            chat_id,
            fileid,
            caption=reply_text,
            reply_markup=reply_markup,
            reply_to_message_id=reply_id,
            parse_mode=enums.ParseMode.HTML,
        )
    except FloodWait as e:
        await asyncio.sleep(e.value + 1)
        return await send_filter_media(
            client, chat_id, fileid, reply_text, reply_markup, reply_id
        )
    except (UserIsBlocked, PeerIdInvalid):
        return None
    except Exception:
        pass

    try:
        return await client.send_cached_media(
            chat_id,
            fileid,
            caption=reply_text,
            reply_markup=reply_markup,
            parse_mode=enums.ParseMode.HTML,
        )
    except Exception:
        pass

    for send_fn, arg_name in [
        (client.send_photo, "photo"),
        (client.send_video, "video"),
        (client.send_document, "document"),
        (client.send_animation, "animation"),
    ]:
        try:
            return await send_fn(
                **{
                    "chat_id": chat_id,
                    arg_name: fileid,
                    "caption": reply_text,
                    "reply_markup": reply_markup,
                    "parse_mode": enums.ParseMode.HTML,
                }
            )
        except Exception:
            continue

    try:
        return await client.send_message(
            chat_id,
            text=reply_text or "<b>Here is your file:</b>",
            reply_markup=reply_markup,
            parse_mode=enums.ParseMode.HTML,
        )
    except Exception as err:
        logger.error(f"Media filter failed all 4 layers: {err}")
        return None


async def safe_send_text_filter(
    client: Client, chat_id: int, text: str, reply_markup, reply_id: int
):
    try:
        return await client.send_message(
            chat_id,
            text,
            disable_web_page_preview=True,
            reply_markup=reply_markup,
            reply_to_message_id=reply_id,
            parse_mode=enums.ParseMode.HTML,
        )
    except Exception:
        try:
            return await client.send_message(
                chat_id,
                text,
                disable_web_page_preview=True,
                reply_markup=reply_markup,
                parse_mode=enums.ParseMode.HTML,
            )
        except Exception as e:
            logger.error(f"Text filter failed: {e}")
            return None


# ============================================================
# ⚡ LIVE GROUP TRIGGER HANDLER
# ============================================================
async def manual_filters(client: Client, message: Message, text=False) -> bool:
    if getattr(info, "REPAIR_MODE", False) and not await verify_admin(
        client, message, message.chat.id
    ):
        return False

    group_id = message.chat.id
    if message.chat.type == enums.ChatType.PRIVATE:
        if active_grp := await get_active_connection(
            str(message.from_user.id if message.from_user else 0)
        ):
            group_id = active_grp

    name = text or message.text or message.caption or ""
    reply_id = message.reply_to_message.id if message.reply_to_message else message.id
    if not (keywords := await get_filters(group_id)):
        return False

    for keyword in reversed(sorted(keywords, key=len)):
        if re.search(
            r"( |^|[^\w])" + re.escape(keyword) + r"( |$|[^\w])",
            name,
            flags=re.IGNORECASE,
        ):
            reply_text, btn, alert, fileid = await find_filter(group_id, keyword)
            # Handle swapped fileid/alert from older filter entries gracefully
            if str(fileid).strip() in ["[]", "None", ""] and str(alert).strip() not in [
                "[]",
                "None",
                "",
            ]:
                fileid, alert = alert, fileid

            if reply_text:
                reply_text = reply_text.replace("\\n", "\n").replace("\\t", "\t")
                if not reply_text.startswith("<b>") and not reply_text.startswith("**"):
                    reply_text = f"<b>{reply_text}</b>"

            button_layout = build_keyboard(btn) or []
            reply_markup = (
                InlineKeyboardMarkup(button_layout) if button_layout else None
            )
            fileid_str = str(fileid).strip()

            if not fileid or fileid_str in ["None", "[]", "", "False"]:
                sent_msg = await safe_send_text_filter(
                    client, message.chat.id, reply_text or "", reply_markup, reply_id
                )
            else:
                sent_msg = await send_filter_media(
                    client,
                    message.chat.id,
                    fileid,
                    reply_text or "",
                    reply_markup,
                    reply_id,
                )

            delete_timer = get_auto_delete_timer("AUTO_DELETE_TIME", 1800)
            if sent_msg and delete_timer > 0:
                is_pm = message.chat.type == enums.ChatType.PRIVATE
                schedule_auto_delete(
                    client, message.chat.id, is_pm, delete_timer, sent_msg, message
                )
            return True
    return False
