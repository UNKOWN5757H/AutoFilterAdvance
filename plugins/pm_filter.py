import ast
import asyncio
import math
import re
import time
from logging import ERROR, getLogger
from typing import Dict, List, Optional, Tuple

from pyrogram import Client, enums, filters
from pyrogram.enums import ButtonStyle
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

# ⚡ One-way dynamic import to fetch live settings safely
from plugins.custom_settings import get_bot_settings, get_stopwords
from Script import script
from utils import get_settings, get_size, is_subscribed, search_gagala, temp

logger = getLogger(__name__)
logger.setLevel(ERROR)


# ============================================================
# 🔒 MEMORY-SAFE BOUNDED CACHE
# ============================================================
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

MESSAGE_EMOJI_PLANE = '<tg-emoji emoji-id="5875465628285931233">✈️</tg-emoji> Telegram'
MESSAGE_EMOJI_LINK = '<tg-emoji emoji-id="5877465816030515018">🔗</tg-emoji> Link'


# ============================================================
# ⚙️ QUERY & STRING NORMALIZERS
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
    q = re.sub(r"\b(19\d{2}|20\d{2})\b", "", q)
    q = re.sub(r"[\[\]\(\)\{\}\-_.:|/#+*~`$@^&!?;,<=>\\]", " ", q)

    # ⚡ Fetch dynamic stopwords
    active_stops = get_stopwords()
    if active_stops:
        pattern = (
            r"\b(" + "|".join(re.escape(w) for w in active_stops if w.strip()) + r")\b"
        )
        q = re.sub(pattern, " ", q, flags=re.IGNORECASE)

    return re.sub(r"\s+", " ", q).strip()


def clean_filename(name: str) -> str:
    if not name:
        return "File"
    name = re.sub(r"(?i)\[?@?sandalwood[^\]\s]*\]?", "", name)
    name = re.sub(r"(?i)\bsandalwood\b", "", name)
    name = re.sub(r"[_.-]", " ", name)
    name = re.sub(r"(?i)\b(mkv|mp4|avi|webm|zip|rar)\b", "", name)
    name = re.sub(r"\s+", " ", name).strip()
    return (name[:42] + "..") if len(name) > 45 else (name or "File")


# ============================================================
# 🗑️ ASYNC FAIL-SAFE AUTO DELETERS
# ============================================================
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


# ============================================================
# 🔍 SPELL CHECK ENGINE
# ============================================================
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

    regex = re.compile(r".*(imdb|wikipedia).*", re.IGNORECASE)
    gs = list(filter(regex.match, g_s))
    gs_parsed = [
        re.sub(
            r"\b(\-([a-zA-Z-\s])\-\simdb|(\-\s)?imdb|(\-\s)?wikipedia|\(|\)|\-|reviews|full|all|episode(s)?|film|movie|series)",
            "",
            i,
            flags=re.IGNORECASE,
        )
        for i in gs
    ]

    if not gs_parsed:
        reg = re.compile(r"watch(\s[a-zA-Z0-9_\s\-\(\)]*)*\|.*", re.IGNORECASE)
        for mv in g_s:
            match = reg.match(mv)
            if match:
                gs_parsed.append(match.group(1))

    user_id = msg.from_user.id if msg.from_user else 0
    movielist = [
        re.sub(r"(\-|\(|\)|_)", "", i, flags=re.IGNORECASE).strip() for i in gs_parsed
    ]
    movielist = list(dict.fromkeys([m for m in movielist if m]))[:5]

    if not movielist:
        return await _send_not_found(msg, fnf_img, fnf_txt)

    SPELL_CHECK_CACHE.set(str(msg.id), movielist)
    btn = [
        [
            InlineKeyboardButton(
                text=movie[:35], callback_data=f"spolling#{user_id}#{idx}"
            )
        ]
        for idx, movie in enumerate(movielist)
    ]
    btn.append(
        [
            InlineKeyboardButton(
                text="🔐 Close", callback_data=f"spolling#{user_id}#close_spellcheck"
            )
        ]
    )

    try:
        k_msg = await msg.reply_text(
            "<b>I couldn't find exact files. Did you mean one of these?</b>",
            reply_markup=InlineKeyboardMarkup(btn),
            parse_mode=enums.ParseMode.DEFAULT,
        )
        delete_timer = getattr(info, "BUTTON_AUTO_DELETE", 1800)
        if delete_timer > 0:
            asyncio.create_task(silent_auto_delete(k_msg, delete_timer, msg))
    except (Forbidden, UserIsBlocked, PeerIdInvalid, ChatWriteForbidden):
        pass


async def _send_not_found(msg: Message, img: Optional[str], text: str):
    k_msg = None
    try:
        if img and str(img).startswith("http"):
            k_msg = await msg.reply_photo(
                photo=img, caption=text, parse_mode=enums.ParseMode.DEFAULT
            )
        else:
            k_msg = await msg.reply_text(text=text, parse_mode=enums.ParseMode.DEFAULT)
    except Exception:
        try:
            k_msg = await msg.reply_text(
                text="<b>🚫 File not found.</b>", parse_mode=enums.ParseMode.DEFAULT
            )
        except Exception:
            pass

    if k_msg:
        delete_timer = getattr(info, "BUTTON_AUTO_DELETE", 1800)
        if delete_timer > 0:
            asyncio.create_task(silent_auto_delete(k_msg, delete_timer, msg))


# ============================================================
# ⌨️ KEYBOARD & BUTTON PARSERS
# ============================================================
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
                    style_map = {
                        1: ButtonStyle.PRIMARY,
                        3: ButtonStyle.SUCCESS,
                        4: ButtonStyle.DANGER,
                    }
                    if style_val in style_map:
                        b_copy["style"] = style_map[style_val]
                    elif isinstance(style_val, ButtonStyle):
                        b_copy["style"] = style_val
                    btn_row.append(InlineKeyboardButton(**b_copy))
                else:
                    btn_row.append(b)
            button_layout.append(btn_row)
        return button_layout
    except Exception:
        return None


# ============================================================
# 🛡️ RESILIENT MANUAL FILTER PIPELINE
# ============================================================
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
            reply_markup = (
                InlineKeyboardMarkup(button_layout) if button_layout else None
            )
            sent_msg = None
            fileid_str = str(fileid).strip()

            try:
                if not fileid or fileid_str in ["None", "[]", "", "False"]:
                    sent_msg = await client.send_message(
                        chat_id=message.chat.id,
                        text=reply_text or "",
                        disable_web_page_preview=True,
                        reply_markup=reply_markup,
                        reply_to_message_id=reply_id,
                        parse_mode=enums.ParseMode.DEFAULT,
                    )
                else:
                    sent_msg = await client.send_cached_media(
                        chat_id=message.chat.id,
                        file_id=fileid,
                        caption=reply_text or "",
                        reply_markup=reply_markup,
                        reply_to_message_id=reply_id,
                        parse_mode=enums.ParseMode.DEFAULT,
                    )
            except FloodWait as e:
                await asyncio.sleep(e.value + 1)
                return await manual_filters(client, message, text)
            except Exception:
                pass

            if sent_msg:
                delete_timer = getattr(info, "BUTTON_AUTO_DELETE", 1800)
                if delete_timer > 0:
                    asyncio.create_task(
                        silent_auto_delete(sent_msg, delete_timer, message)
                    )
            return True
    return False


# ============================================================
# ⚡ HIGH-PERFORMANCE AUTO FILTER ENGINE
# ============================================================
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
            search = sanitize_search_query(message.text)
            if not search or len(search) < 2:
                return

            files, offset, total_results = await get_search_results(
                search, max_results=10, offset=0, filter=True
            )

            if not files:
                stripped = re.sub(
                    r"(?i)\b(kannada|telugu|tamil|malayalam|hindi|english|dual|multi)\b",
                    "",
                    search,
                ).strip()
                if stripped and stripped != search:
                    files, offset, total_results = await get_search_results(
                        stripped, max_results=10, offset=0, filter=True
                    )
                    if files:
                        search = stripped

            if not files:
                if settings.get("spell_check", False):
                    return await advantage_spell_chok(client, msg, search)
                return
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
            display_name = clean_filename(raw_name)
            size_str = get_size(file_size)

            url_payload = f"https://t.me/{bot_username}?start={pre}_{file_id}"
            if settings.get("button", False):
                btn.append(
                    [
                        InlineKeyboardButton(
                            text=f"{size_str} | {display_name}", url=url_payload
                        )
                    ]
                )
            else:
                btn.append(
                    [
                        InlineKeyboardButton(text=f"{display_name}", url=url_payload),
                        InlineKeyboardButton(text=f"{size_str}", url=url_payload),
                    ]
                )

        btn.insert(
            0,
            [
                InlineKeyboardButton(
                    text="• Bᴀᴄᴋ Uᴘ Cʜᴀɴɴᴇʟ •",
                    url="https://t.me/KR_Picture",
                    icon_custom_emoji_id=5258503720928288433,
                    style=ButtonStyle.SUCCESS,
                )
            ],
        )

        if offset:
            key = f"{message.chat.id}_{message.id}"
            BUTTONS_CACHE.set(key, search)
            req = message.from_user.id if message.from_user else 0
            btn.append(
                [
                    InlineKeyboardButton(
                        text=f"1/{math.ceil(int(total_results) / 10)}",
                        callback_data="pages",
                    ),
                    InlineKeyboardButton(
                        text="NEXT ➡️", callback_data=f"next_{req}_{key}_{offset}"
                    ),
                ]
            )
        else:
            btn.append([InlineKeyboardButton(text="1/1", callback_data="pages")])

        m = None
        try:
            if auto_img and str(auto_img).startswith("http"):
                m = await message.reply_photo(
                    photo=auto_img,
                    caption=cap,
                    reply_markup=InlineKeyboardMarkup(btn),
                    parse_mode=enums.ParseMode.DEFAULT,
                )
            else:
                m = await message.reply_text(
                    cap,
                    reply_markup=InlineKeyboardMarkup(btn),
                    parse_mode=enums.ParseMode.DEFAULT,
                )
        except FloodWait as e:
            await asyncio.sleep(e.value + 1)
            try:
                m = await message.reply_text(
                    cap,
                    reply_markup=InlineKeyboardMarkup(btn),
                    parse_mode=enums.ParseMode.DEFAULT,
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

        delete_timer = getattr(info, "BUTTON_AUTO_DELETE", 1800)
        if delete_timer > 0 and m:
            asyncio.create_task(silent_auto_delete(m, delete_timer, message))
    except Exception as e:
        logger.error(f"Fatal error in auto_filter: {e}")


# ============================================================
# 🎯 MESSAGE LISTENER
# ============================================================
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


# ============================================================
# 📑 PAGINATION & SPELL CHECK CALLBACK HANDLER
# ============================================================
@Client.on_callback_query(filters.regex(r"^(next_|spolling#)"))
async def pagination_and_spell_handler(bot: Client, query: CallbackQuery):
    if getattr(info, "REPAIR_MODE", False):
        if str(query.from_user.id) not in [str(a) for a in info.ADMINS]:
            return await query.answer("🛠️ Bot is under maintenance!", show_alert=True)

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

    # Pagination logic
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
        display_name = clean_filename(raw_name)
        size_str = get_size(file_size)
        url_payload = f"https://t.me/{bot_username}?start={pre}_{file_id}"

        if settings.get("button", False):
            btn.append(
                [
                    InlineKeyboardButton(
                        text=f"{size_str} | {display_name}", url=url_payload
                    )
                ]
            )
        else:
            btn.append(
                [
                    InlineKeyboardButton(text=f"{display_name}", url=url_payload),
                    InlineKeyboardButton(text=f"{size_str}", url=url_payload),
                ]
            )

    if 0 < offset <= 10:
        off_set = 0
    elif offset == 0:
        off_set = None
    else:
        off_set = offset - 10

    total_pages = math.ceil(total / 10)
    current_page = math.ceil(int(offset) / 10) + 1

    if not n_offset:
        btn.append(
            [
                InlineKeyboardButton(
                    "⬅️ BACK", callback_data=f"next_{req}_{key}_{off_set}"
                ),
                InlineKeyboardButton(
                    f"Pages {current_page} / {total_pages}", callback_data="pages"
                ),
            ]
        )
    elif off_set is None:
        btn.insert(
            0,
            [
                InlineKeyboardButton(
                    text="• Bᴀᴄᴋ Uᴘ Cʜᴀɴɴᴇʟ •",
                    url="https://t.me/KR_Picture",
                    icon_custom_emoji_id=5258503720928288433,
                    style=ButtonStyle.SUCCESS,
                )
            ],
        )
        btn.append(
            [
                InlineKeyboardButton(
                    f"{current_page} / {total_pages}", callback_data="pages"
                ),
                InlineKeyboardButton(
                    "NEXT ➡️", callback_data=f"next_{req}_{key}_{n_offset}"
                ),
            ]
        )
    else:
        btn.append(
            [
                InlineKeyboardButton(
                    "⬅️ BACK", callback_data=f"next_{req}_{key}_{off_set}"
                ),
                InlineKeyboardButton(
                    f"{current_page} / {total_pages}", callback_data="pages"
                ),
                InlineKeyboardButton(
                    "NEXT ➡️", callback_data=f"next_{req}_{key}_{n_offset}"
                ),
            ]
        )

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
