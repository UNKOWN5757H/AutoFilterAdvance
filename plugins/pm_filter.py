import ast
import asyncio
import math
import re
import time
from logging import ERROR, getLogger
from typing import Dict, List, Optional, Tuple

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
from database.connections_mdb import (
    active_connection,
    all_connections,
    delete_connection,
    if_active,
    make_active,
    make_inactive,
)
from database.filters_mdb import del_all, find_filter, get_filters
from database.ia_filterdb import Media as _Media
from database.ia_filterdb import get_file_details, get_search_results
from database.plugin_dbs import plugin_db as _plugin_db
from database.users_chats_db import db as _db
from info import ADMINS, AUTH_CHANNEL, CUSTOM_FILE_CAPTION, REQ_CHANNEL
from plugins.custom_settings import get_bot_settings, get_stopwords
from Script import script
from utils import (
    get_settings,
    get_size,
    is_subscribed,
    parse_text_and_markup,
    search_gagala,
    temp,
)

logger = getLogger(__name__)
logger.setLevel(ERROR)

# ⚡ DATABASE SETUP FOR CLEAN WORDS
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

    def pop(self, key: str, default=None):
        item = self._data.pop(key, None)
        if not item:
            return default
        expire_at, value = item
        return value if time.time() <= expire_at else default

    def _cleanup(self):
        now = time.time()
        expired = [k for k, (exp, _) in self._data.items() if now > exp]
        for k in expired:
            self._data.pop(k, None)


BUTTONS_CACHE = TTLCache(maxsize=3000, ttl=1800)
SPELL_CHECK_CACHE = TTLCache(maxsize=1000, ttl=900)

try:
    from pyrogram.enums import ButtonStyle

    BTN_PRIMARY = getattr(ButtonStyle, "PRIMARY", 1)
    BTN_SUCCESS = getattr(ButtonStyle, "SUCCESS", 3)
    BTN_DANGER = getattr(ButtonStyle, "DANGER", 4)
    BTN_SECONDARY = getattr(ButtonStyle, "SECONDARY", 2)
except ImportError:
    BTN_PRIMARY = 1
    BTN_SUCCESS = 3
    BTN_DANGER = 4
    BTN_SECONDARY = 2


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
    q = re.sub(r"\b(19\d{2}|20\d{2})\b", "", q)
    q = re.sub(r"[\[\]\(\)\{\}\-_.:|/#+*~`$@^&!?;,<=>\\]", " ", q)
    active_stops = get_stopwords()
    if active_stops:
        pattern = (
            r"\b(" + "|".join(re.escape(w) for w in active_stops if w.strip()) + r")\b"
        )
        q = re.sub(pattern, " ", q, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", q).strip()


AUTO_DELETE_TASKS = set()


def get_auto_delete_timer() -> int:
    try:
        global_switch = getattr(info, "AUTO_DELETE", True)
        if str(global_switch).strip().lower() in ["false", "off", "0"]:
            return 0
        val = getattr(
            info, "AUTO_DELETE_TIME", getattr(info, "BUTTON_AUTO_DELETE", global_switch)
        )
        if isinstance(val, bool):
            return 1800 if val else 0
        parsed = int(val)
        if 0 < parsed < 10:
            return 1800
        return parsed
    except Exception:
        return 1800


async def silent_auto_delete(
    bot_message: Optional[Message], delay: int, user_message: Optional[Message] = None
):
    if not bot_message or delay <= 0:
        return
    await asyncio.sleep(delay)
    try:
        await bot_message.delete()
    except Exception:
        pass
    if user_message:
        try:
            await user_message.delete()
        except Exception:
            pass


def schedule_auto_delete(bot_msg, delay, user_msg=None):
    if delay <= 0:
        return
    task = asyncio.create_task(silent_auto_delete(bot_msg, delay, user_msg))
    AUTO_DELETE_TASKS.add(task)
    task.add_done_callback(AUTO_DELETE_TASKS.discard)


async def advantage_spell_chok(client: Client, msg: Message, search_query: str):
    b_set = await get_bot_settings()
    fnf_img = b_set.get("not_found_img", getattr(info, "NOT_FOUND_IMG", None))
    fnf_txt = b_set.get(
        "not_found_text", getattr(info, "NOT_FOUND_MSG", "<b>🚫 File not found.</b>")
    )

    clean_text = search_query or sanitize_search_query(msg.text or "")
    if not clean_text:
        return

    g_s = await search_gagala(clean_text + " movie") or []
    g_s += await search_gagala(clean_text) or []

    if not g_s:
        return await _send_not_found(msg, fnf_img, fnf_txt)

    gs_parsed = []
    for mv in g_s:
        clean_mv = re.sub(
            r"(?i)(\s*\-\s*IMDb|\s*\-\s*Wikipedia|\s*\-\s*TMDB|\|.*|\(.*\)|Watch.*|Full.*|Movie.*|Download.*|Free.*)",
            "",
            mv,
        ).strip()
        clean_mv = re.sub(r"[\-\|:;_]*$", "", clean_mv).strip()
        if clean_mv and clean_mv.lower() not in [m.lower() for m in gs_parsed]:
            gs_parsed.append(clean_mv)

    movielist = gs_parsed[:80]
    if not movielist:
        return await _send_not_found(msg, fnf_img, fnf_txt)

    user_id = msg.from_user.id if msg.from_user else 0
    SPELL_CHECK_CACHE.set(str(msg.id), movielist)

    btn = []
    for idx in range(0, len(movielist), 2):
        row = []
        row.append(
            create_btn(
                text=movielist[idx][:35],
                callback_data=f"spolling#{user_id}#{idx}",
                style=BTN_PRIMARY,
            )
        )
        if idx + 1 < len(movielist):
            row.append(
                create_btn(
                    text=movielist[idx + 1][:35],
                    callback_data=f"spolling#{user_id}#{idx+1}",
                    style=BTN_PRIMARY,
                )
            )
        btn.append(row)

    btn.append(
        [
            create_btn(
                text="🔐 Close",
                callback_data=f"spolling#{user_id}#close_spellcheck",
                style=BTN_DANGER,
            )
        ]
    )
    final_text, final_markup = parse_text_and_markup(fnf_txt)
    if not final_text:
        final_text = "<b>🚫 File not found.</b>"
    final_text += "\n\n<b>Did you mean one of these? 👇</b>"

    combined_buttons = []
    if final_markup and hasattr(final_markup, "inline_keyboard"):
        combined_buttons.extend(final_markup.inline_keyboard)
    combined_buttons.extend(btn)
    reply_markup = InlineKeyboardMarkup(combined_buttons)

    try:
        k_msg = None
        if fnf_img:
            try:
                k_msg = await msg.reply_photo(
                    photo=fnf_img,
                    caption=final_text,
                    reply_markup=reply_markup,
                    parse_mode=enums.ParseMode.HTML,
                )
            except Exception as e:
                logger.error(f"SpellCheck Image Error: {e}")
                k_msg = await msg.reply_text(
                    text=final_text,
                    reply_markup=reply_markup,
                    parse_mode=enums.ParseMode.HTML,
                )
        else:
            k_msg = await msg.reply_text(
                text=final_text,
                reply_markup=reply_markup,
                parse_mode=enums.ParseMode.HTML,
            )

        if k_msg:
            delete_timer = get_auto_delete_timer()
            if delete_timer > 0:
                schedule_auto_delete(k_msg, delete_timer, msg)
    except (Forbidden, UserIsBlocked, PeerIdInvalid, ChatWriteForbidden):
        pass


async def _send_not_found(msg: Message, img: Optional[str], text: str):
    k_msg = None
    try:
        final_text, final_markup = parse_text_and_markup(text)
        if not final_text:
            final_text = "<b>🚫 File not found.</b>"

        if img:
            try:
                k_msg = await msg.reply_photo(
                    photo=img,
                    caption=final_text,
                    reply_markup=final_markup,
                    parse_mode=enums.ParseMode.HTML,
                )
            except Exception as e:
                logger.error(f"FNF Image Error: {e}")
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
    except Exception as e:
        logger.error(f"FNF Critical Error: {e}")
        try:
            k_msg = await msg.reply_text(
                text="<b>🚫 File not found.</b>", parse_mode=enums.ParseMode.HTML
            )
        except Exception:
            pass

    if k_msg:
        delete_timer = get_auto_delete_timer()
        if delete_timer > 0:
            schedule_auto_delete(k_msg, delete_timer, msg)


def build_keyboard(btn_str: str) -> Optional[List[List[InlineKeyboardButton]]]:
    if not btn_str or btn_str in ["[]", "None", "False", ""]:
        return None
    try:
        parsed_btn = ast.literal_eval(btn_str)
        button_layout = []
        for row in parsed_btn:
            btn_row = []
            for b in row:
                if isinstance(b, dict):
                    b_copy = b.copy()
                    style_val = b_copy.pop("style", None)
                    if style_val in [1, "blue"]:
                        b_copy["style"] = BTN_PRIMARY
                    elif style_val in [3, "green"]:
                        b_copy["style"] = BTN_SUCCESS
                    elif style_val in [4, "red"]:
                        b_copy["style"] = BTN_DANGER
                    elif style_val in [2, "normal", "gray", "default"]:
                        b_copy.pop("style", None)
                    elif isinstance(style_val, int):
                        b_copy["style"] = style_val

                    try:
                        btn_row.append(InlineKeyboardButton(**b_copy))
                    except TypeError:
                        b_copy.pop("style", None)
                        btn_row.append(InlineKeyboardButton(**b_copy))
                else:
                    btn_row.append(b)
            button_layout.append(btn_row)
        return button_layout
    except Exception:
        return None


async def manual_filters(client: Client, message: Message, text: bool = False) -> bool:
    if getattr(info, "REPAIR_MODE", False):
        if not message.from_user or str(message.from_user.id) not in [
            str(a) for a in info.ADMINS
        ]:
            return False

    group_id = message.chat.id
    if message.chat.type == enums.ChatType.PRIVATE and message.from_user:
        active_grp = await active_connection(str(message.from_user.id))
        if active_grp:
            group_id = active_grp

    name = text or message.text or message.caption or ""
    if not name:
        return False

    reply_id = message.reply_to_message.id if message.reply_to_message else message.id
    keywords = await get_filters(group_id)
    if not keywords:
        return False

    for keyword in reversed(sorted(keywords, key=len)):
        pattern = r"( |^|[^\w])" + re.escape(keyword) + r"( |$|[^\w])"
        if re.search(pattern, name, flags=re.IGNORECASE):
            reply_text, btn, alert, fileid = await find_filter(group_id, keyword)
            if reply_text:
                reply_text = reply_text.replace("\\n", "\n").replace("\\t", "\t")

            button_layout = build_keyboard(btn)
            static_keyboard = (
                InlineKeyboardMarkup(button_layout) if button_layout else None
            )
            final_text, final_markup = parse_text_and_markup(
                reply_text or "", static_keyboard
            )

            sent_msg = None
            fileid_str = str(fileid).strip()

            try:
                if not fileid or fileid_str in ["None", "[]", "", "False"]:
                    sent_msg = await client.send_message(
                        chat_id=message.chat.id,
                        text=final_text,
                        disable_web_page_preview=True,
                        reply_markup=final_markup,
                        reply_to_message_id=reply_id,
                        parse_mode=enums.ParseMode.HTML,
                    )
                else:
                    sent_msg = await client.send_cached_media(
                        chat_id=message.chat.id,
                        file_id=fileid,
                        caption=final_text,
                        reply_markup=final_markup,
                        reply_to_message_id=reply_id,
                        parse_mode=enums.ParseMode.HTML,
                    )
            except FloodWait as e:
                await asyncio.sleep(e.value + 1)
                return await manual_filters(client, message, text)
            except Exception:
                pass

            if sent_msg:
                delete_timer = get_auto_delete_timer()
                if delete_timer > 0:
                    schedule_auto_delete(sent_msg, delete_timer, message)
            return True
    return False


async def auto_filter(client: Client, msg: any, spoll: any = False):
    try:
        b_set = await get_bot_settings()
        auto_img = b_set.get("auto_img")

        if not spoll:
            message: Message = msg
            if (
                not message
                or not message.text
                or message.text.startswith(("/", "!", "#", ".", ",", "?", "@"))
            ):
                return

            settings = await get_settings(message.chat.id)
            search = message.text
            search = re.sub(r"https?://\S+|t\.me/\S+|@\w+", "", search).strip()
            if not search:
                return

            if len(search) <= 3:
                files, offset, total_results = await get_search_results(
                    search, max_results=50, offset=0, filter=True
                )
                if files:
                    strict_pattern = re.compile(
                        rf"(^|[\s\.\_\-\[\]\(\)])({re.escape(search)})([\s\.\_\-\[\]\(\)]|$)",
                        re.IGNORECASE,
                    )
                    strict_files = [
                        f
                        for f in files
                        if strict_pattern.search(
                            f.get("file_name", "")
                            if isinstance(f, dict)
                            else getattr(f, "file_name", "")
                        )
                    ]
                    if strict_files:
                        files, total_results = strict_files[:10], len(strict_files)
                    else:
                        files, total_results = files[:10], len(files)
            else:
                files, offset, total_results = await get_search_results(
                    search, max_results=10, offset=0, filter=True
                )

            if not files:
                stripped = sanitize_search_query(search)
                if stripped and stripped != search:
                    if len(stripped) <= 3:
                        files, offset, total_results = await get_search_results(
                            stripped, max_results=50, offset=0, filter=True
                        )
                        if files:
                            strict_pattern = re.compile(
                                rf"(^|[\s\.\_\-\[\]\(\)])({re.escape(stripped)})([\s\.\_\-\[\]\(\)]|$)",
                                re.IGNORECASE,
                            )
                            strict_files = [
                                f
                                for f in files
                                if strict_pattern.search(
                                    f.get("file_name", "")
                                    if isinstance(f, dict)
                                    else getattr(f, "file_name", "")
                                )
                            ]
                            if strict_files:
                                files, total_results = strict_files[:10], len(
                                    strict_files
                                )
                            else:
                                files, total_results = files[:10], len(files)
                    else:
                        files, offset, total_results = await get_search_results(
                            stripped, max_results=10, offset=0, filter=True
                        )
                    if files:
                        search = stripped

            if not files:
                if settings.get("spell_check", False):
                    return await advantage_spell_chok(client, msg, search)
                fnf_img = b_set.get(
                    "not_found_img", getattr(info, "NOT_FOUND_IMG", None)
                )
                fnf_txt = b_set.get(
                    "not_found_text",
                    getattr(info, "NOT_FOUND_MSG", "<b>🚫 File not found.</b>"),
                )
                return await _send_not_found(msg, fnf_img, fnf_txt)
        else:
            settings = await get_settings(msg.message.chat.id)
            message = msg.message.reply_to_message or msg.message
            search, files, offset, total_results = spoll

        if not files:
            return
        files.sort(
            key=lambda x: (
                x.get("file_size", 0)
                if isinstance(x, dict)
                else getattr(x, "file_size", 0)
            )
        )
        pre = "filep" if settings.get("file_secure", False) else "file"
        btn = []
        bot_username = temp.U_NAME or (await client.get_me()).username or "bot"
        mention = message.from_user.mention if (message.from_user) else "User"
        cap = f"<b>Hᴇʏ {mention} 👋🏻\n\n➤ Tɪᴛʟᴇ : <code>{search.title()}</code>\n➤ Yᴏᴜʀ Fɪʟᴇꜱ Rᴇᴀᴅʏ Nᴏᴡ 👇</b>"

        key = f"{message.chat.id}-{message.id}"
        BUTTONS_CACHE.set(key, search)
        req = message.from_user.id if message.from_user else 0

        clean_words = await get_clean_words()

        is_specific_season = bool(
            re.search(
                r"(?i)(?:^|[^a-zA-Z0-9])(?:s|season)\s*\d{1,2}(?:[^a-zA-Z0-9]|$|e|ep|episode)",
                search,
            )
        )
        seasons_dict = {}
        standalone_files = []

        if not is_specific_season:
            for file in files:
                name = str(
                    file.get("file_name", "Unknown")
                    if isinstance(file, dict)
                    else getattr(file, "file_name", "Unknown")
                )
                match = re.search(
                    r"(?i)(?:^|[^a-zA-Z0-9])(?:s|season)\s*(\d{1,2})(?:[^a-zA-Z0-9]|$|e|ep|episode)",
                    name,
                )
                if match:
                    s_num = int(match.group(1))
                    if s_num not in seasons_dict:
                        seasons_dict[s_num] = []
                    seasons_dict[s_num].append(file)
                else:
                    standalone_files.append(file)
        else:
            standalone_files = files

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

        for s_num in sorted(seasons_dict.keys()):
            season_btn_text = f"📺 Season {s_num}"
            btn.append(
                [
                    create_btn(
                        text=season_btn_text,
                        callback_data=f"eval_sea#{req}#{s_num}#{key}",
                        style=BTN_PRIMARY,
                    )
                ]
            )

        for file in standalone_files:
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

        # ⚡ CRITICAL FIX: Safe integer parsing for total_results
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
                m = await message.reply_photo(
                    photo=auto_img,
                    caption=final_caption,
                    reply_markup=final_markup,
                    parse_mode=enums.ParseMode.HTML,
                )
            else:
                m = await message.reply_text(
                    final_caption,
                    reply_markup=final_markup,
                    parse_mode=enums.ParseMode.HTML,
                )
        except FloodWait as e:
            await asyncio.sleep(e.value + 1)
            try:
                m = await message.reply_text(
                    final_caption,
                    reply_markup=final_markup,
                    parse_mode=enums.ParseMode.HTML,
                )
            except Exception:
                return
        except Exception:
            return

        if spoll and msg and hasattr(msg, "message"):
            try:
                await msg.message.delete()
            except Exception:
                pass
        delete_timer = get_auto_delete_timer()
        if delete_timer > 0 and m:
            schedule_auto_delete(m, delete_timer, message)
    except Exception as e:
        logger.error(f"Fatal error in auto_filter: {e}")


@Client.on_message(filters.group & filters.text & filters.incoming)
async def give_filter(client: Client, message: Message):
    if getattr(info, "REPAIR_MODE", False):
        if not message.from_user or str(message.from_user.id) not in [
            str(a) for a in info.ADMINS
        ]:
            return
    if message.from_user and await _plugin_db.is_banned(message.from_user.id):
        return
    try:
        matched = await manual_filters(client, message)
        if not matched:
            await auto_filter(client, message)
    except Exception as e:
        logger.error(f"give_filter top-level error: {e}")


@Client.on_callback_query(filters.regex(r"^(next_|spolling#|eval_sea#)"))
async def pagination_and_spell_handler(bot: Client, query: CallbackQuery):
    if getattr(info, "REPAIR_MODE", False):
        if str(query.from_user.id) not in [str(a) for a in info.ADMINS]:
            return await query.answer("🛠️ Bot is under maintenance!", show_alert=True)

    if query.data.startswith("eval_sea#"):
        try:
            _, req, s_num, key = query.data.split("#")
        except ValueError:
            return await query.answer("Invalid data!", show_alert=True)

        if int(req) != 0 and query.from_user.id != int(req):
            return await query.answer(
                "⚠️ That's not for you! Request your own file in the group.",
                show_alert=True,
            )

        search = BUTTONS_CACHE.get(key)
        if not search:
            return await query.answer(
                "⌛ This search expired. Please search again!", show_alert=True
            )

        new_search = f"{search} S{int(s_num):02d}"
        files, offset, total_results = await get_search_results(
            new_search, max_results=10, offset=0, filter=True
        )
        if not files:
            return await query.answer(
                "No episodes found for this season.", show_alert=True
            )

        await auto_filter(bot, query, spoll=(new_search, files, offset, total_results))
        return

    if query.data.startswith("spolling#"):
        try:
            _, req_user, idx_val = query.data.split("#")
        except ValueError:
            return await query.answer("Invalid data!", show_alert=True)
        if int(req_user) != 0 and query.from_user.id != int(req_user):
            return await query.answer(
                "⚠️ This suggestion is not for you!", show_alert=True
            )
        if idx_val == "close_spellcheck":
            try:
                await query.answer()
            except QueryIdInvalid:
                pass
            return await query.message.delete()
        msg_id = (
            query.message.reply_to_message.id
            if query.message.reply_to_message
            else query.message.id
        )
        candidates = SPELL_CHECK_CACHE.get(str(msg_id)) or []
        try:
            selected_movie = candidates[int(idx_val)]
            files, offset, total_results = await get_search_results(
                selected_movie, max_results=10, offset=0, filter=True
            )
            if files:
                await auto_filter(
                    bot, query, spoll=(selected_movie, files, offset, total_results)
                )
            else:
                await query.answer(
                    "No files found for this suggestion.", show_alert=True
                )
        except (IndexError, ValueError):
            await query.answer("Suggestion expired.", show_alert=True)
        return

    try:
        _, req, key, offset_str = query.data.split("_", 3)
    except ValueError:
        return await query.answer("Invalid button data!", show_alert=True)
    try:
        if int(req) not in [query.from_user.id, 0]:
            return await query.answer(
                "⚠️ That's not for you! Request your own file in the group.",
                show_alert=True,
            )
    except Exception:
        pass

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
        )
    )
    settings = await get_settings(query.message.chat.id)
    btn = []
    bot_username = temp.U_NAME or (await bot.get_me()).username or "bot"
    pre = "filep" if settings.get("file_secure", False) else "file"

    clean_words = await get_clean_words()

    is_specific_season = bool(
        re.search(
            r"(?i)(?:^|[^a-zA-Z0-9])(?:s|season)\s*\d{1,2}(?:[^a-zA-Z0-9]|$|e|ep|episode)",
            search,
        )
    )
    seasons_dict = {}
    standalone_files = []

    if not is_specific_season:
        for file in files:
            name = str(
                file.get("file_name", "Unknown")
                if isinstance(file, dict)
                else getattr(file, "file_name", "Unknown")
            )
            match = re.search(
                r"(?i)(?:^|[^a-zA-Z0-9])(?:s|season)\s*(\d{1,2})(?:[^a-zA-Z0-9]|$|e|ep|episode)",
                name,
            )
            if match:
                s_num = int(match.group(1))
                if s_num not in seasons_dict:
                    seasons_dict[s_num] = []
                seasons_dict[s_num].append(file)
            else:
                standalone_files.append(file)
    else:
        standalone_files = files

    for s_num in sorted(seasons_dict.keys()):
        season_btn_text = f"📺 Season {s_num}"
        btn.append(
            [
                create_btn(
                    text=season_btn_text,
                    callback_data=f"eval_sea#{req}#{s_num}#{key}",
                    style=BTN_PRIMARY,
                )
            ]
        )

    for file in standalone_files:
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

    # ⚡ CRITICAL FIX: Safe integer parsing for total rows
    try:
        total = int(total)
    except Exception:
        total = 0
    total_pages = math.ceil(total / 10) if total > 0 else 1
    current_page = math.ceil(offset / 10) + 1 if offset > 0 else 1

    # ⚡ EXACT BUTTON COLORS: Next/Back = Blue(PRIMARY), Pages = Green(SUCCESS)
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
