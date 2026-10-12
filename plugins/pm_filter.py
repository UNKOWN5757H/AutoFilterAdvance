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
from pyrogram.enums import ButtonStyle
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
from database.connections_mdb import active_connection
from database.filters_mdb import add_filter, delete_filter, find_filter, get_filters
from database.ia_filterdb import Media as _Media
from database.ia_filterdb import get_search_results
from database.plugin_dbs import plugin_db as _plugin_db
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


# ============================================================
# 👑 FULL POWER ADMIN CHECKER (GLOBAL + CHAT + ANONYMOUS)
# ============================================================
def get_admin_list():
    raw_admins = getattr(info, "ADMINS", [])
    if isinstance(raw_admins, (str, int)):
        raw_admins = str(raw_admins).replace(",", " ").split()
    return [int(x) for x in raw_admins if str(x).strip().lstrip("-").isdigit()]

async def is_user_admin(client: Client, message: Message):
    admin_list = get_admin_list()

    # 1. Global Admin Check (Direct User)
    if message.from_user and message.from_user.id in admin_list:
        return True

    # 2. Global Admin Check (Anonymous/Channel sending as Chat)
    if message.sender_chat and message.sender_chat.id in admin_list:
        return True

    # 3. Group Admin Check (Normal & Anonymous Admins)
    if message.chat and message.chat.type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
        if message.sender_chat and message.sender_chat.id == message.chat.id:
            return True
            
        if message.from_user:
            try:
                member = await client.get_chat_member(message.chat.id, message.from_user.id)
                return member.status in [enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER]
            except Exception:
                pass

    return False

async def admin_check(_, client: Client, message: Message):
    return await is_user_admin(client, message)

admin_filter = filters.create(admin_check)

async def get_target_group(client: Client, message: Message):
    if message.chat.type == enums.ChatType.PRIVATE:
        user_id = getattr(message.from_user, "id", None)
        if not user_id:
            return None, False
        active_grp = await active_connection(str(user_id))
        if not active_grp:
            await message.reply_text("⚠️ **Connect to a group first using /connect!**")
            return None, False
        return int(active_grp), True
    return message.chat.id, True


# ============================================================
# ⚡ CACHE SYSTEM
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

    def _cleanup(self):
        now = time.time()
        expired = [k for k, (exp, _) in self._data.items() if now > exp]
        for k in expired:
            self._data.pop(k, None)

GLOBAL_SEARCH_CACHE = TTLCache(maxsize=3000, ttl=600)
BUTTONS_CACHE = TTLCache(maxsize=3000, ttl=1800)
USER_LAST_REQ = TTLCache(maxsize=5000, ttl=60)

try:
    BTN_PRIMARY = getattr(ButtonStyle, "PRIMARY", 1)
    BTN_SUCCESS = getattr(ButtonStyle, "SUCCESS", 3)
    BTN_DANGER = getattr(ButtonStyle, "DANGER", 4)
except ImportError:
    BTN_PRIMARY, BTN_SUCCESS, BTN_DANGER = 1, 3, 4

def create_btn(text, url=None, callback_data=None, style=None):
    kwargs = {"text": text}
    if url: kwargs["url"] = url
    if callback_data: kwargs["callback_data"] = callback_data
    if style is not None: kwargs["style"] = style
    try:
        return InlineKeyboardButton(**kwargs)
    except TypeError:
        kwargs.pop("style", None)
        return InlineKeyboardButton(**kwargs)


# ============================================================
# 🔮 GOD-TIER "ZERO-CLICK" FUZZY SEARCH ENGINE
# ============================================================
def sanitize_search_query(text: str) -> str:
    if not text: return ""
    q = text.strip().lower()
    q = re.sub(r"https?://\S+|t\.me/\S+|@\w+", "", q)
    q = re.sub(r"(?i)\b(1080p|720p|480p|2160p|4k|mkv|mp4|avi|hdrip|web-?dl|webrip|bluray|brrip|dvdrip|x264|x265|hevc|dual audio|hindi|kannada|telugu|tamil|malayalam|english|subtitles|subs|episodes|season\s*\d+|s\d+e\d+|complete)\b", "", q)
    q = re.sub(r"[^a-zA-Z0-9]", " ", q)
    active_stops = get_stopwords()
    if active_stops:
        pattern = r"\b(" + "|".join(re.escape(w) for w in active_stops if w.strip()) + r")\b"
        q = re.sub(pattern, " ", q, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", q).strip()


async def god_tier_search(query: str) -> Tuple[list, int, int, str, bool]:
    clean_query = sanitize_search_query(query)
    if not clean_query:
        return [], 0, 0, query, False

    files, offset, total = await get_search_results(clean_query, max_results=10, offset=0, filter=True)
    if files:
        return files, offset, total, clean_query, False

    sample_docs = await _Media.collection.find({}, {"file_name": 1}).limit(2000).to_list(length=2000)
    db_titles = list(set([sanitize_search_query(d.get("file_name", "")) for d in sample_docs if d.get("file_name")]))

    matches = difflib.get_close_matches(clean_query, db_titles, n=1, cutoff=0.45)
    if matches:
        corrected_query = matches[0]
        c_files, c_offset, c_total = await get_search_results(corrected_query, max_results=10, offset=0, filter=True)
        if c_files:
            return c_files, c_offset, c_total, corrected_query, True

    return [], 0, 0, query, False


# ============================================================
# ⏳ SILENT AUTO-DELETE ENGINE
# ============================================================
def get_auto_delete_timer() -> int:
    try: return int(getattr(info, "AUTO_DELETE_TIME", 0))
    except Exception: return 0

async def silent_auto_delete(msg: Message, delay: int):
    await asyncio.sleep(delay)
    try: await msg.delete()
    except Exception: pass

async def _send_not_found(msg: Message, img: Optional[str], text: str):
    k_msg = None
    try:
        final_text, final_markup = parse_text_and_markup(text)
        final_text = final_text or "<b>🚫 File not found.</b>"
        if img:
            try: k_msg = await msg.reply_photo(photo=img, caption=final_text, reply_markup=final_markup, parse_mode=enums.ParseMode.HTML)
            except Exception: k_msg = await msg.reply_text(text=final_text, reply_markup=final_markup, parse_mode=enums.ParseMode.HTML)
        else:
            k_msg = await msg.reply_text(text=final_text, reply_markup=final_markup, parse_mode=enums.ParseMode.HTML)
    except Exception: pass

    if k_msg:
        delete_timer = get_auto_delete_timer()
        if delete_timer > 0:
            asyncio.create_task(silent_auto_delete(k_msg, delete_timer))


# ============================================================
# 📁 CORE AUTO FILTER ENGINE
# ============================================================
async def auto_filter(client: Client, msg: Message):
    try:
        b_set = await get_bot_settings()
        auto_img = b_set.get("auto_img")

        if not msg or not msg.text or msg.text.startswith(("/", "!", "#", ".", ",", "?", "@")):
            return

        search = re.sub(r"https?://\S+|t\.me/\S+|@\w+", "", msg.text).strip()
        if not search: return

        settings = await get_settings(msg.chat.id)
        cache_key = search.lower()
        cached_data = GLOBAL_SEARCH_CACHE.get(cache_key)

        if cached_data:
            files, offset, total_results, search_query, was_corrected = cached_data
        else:
            files, offset, total_results, search_query, was_corrected = await god_tier_search(search)
            if files:
                GLOBAL_SEARCH_CACHE.set(cache_key, (files, offset, total_results, search_query, was_corrected))

        if not files:
            fnf_img = b_set.get("not_found_img", getattr(info, "NOT_FOUND_IMG", None))
            fnf_txt = b_set.get("not_found_text", getattr(info, "NOT_FOUND_MSG", "<b>🚫 File not found.</b>"))
            return await _send_not_found(msg, fnf_img, fnf_txt)

        files.sort(key=lambda x: (x.get("file_size", 0) if isinstance(x, dict) else getattr(x, "file_size", 0)), reverse=True)

        pre = "filep" if settings.get("file_secure", False) else "file"
        btn = []
        bot_username = temp.U_NAME or (await client.get_me()).username or "bot"
        mention = msg.from_user.mention if msg.from_user else "User"

        cap = f"<b>Hᴇʏ {mention} 👋🏻\n\n🪄 Aᴜᴛᴏ-Cᴏʀʀᴇᴄᴛᴇᴅ: <del>{search.title()}</del> ➔ <code>{search_query.title()}</code>\n➤ Yᴏᴜʀ Fɪʟᴇꜱ Rᴇᴀᴅʏ Nᴏᴡ 👇</b>" if was_corrected else f"<b>Hᴇʏ {mention} 👋🏻\n\n➤ Tɪᴛʟᴇ : <code>{search_query.title()}</code>\n➤ Yᴏᴜʀ Fɪʟᴇꜱ Rᴇᴀᴅʏ Nᴏᴡ 👇</b>"

        key = f"{msg.chat.id}-{msg.id}"
        BUTTONS_CACHE.set(key, search_query)
        req = msg.from_user.id if msg.from_user else 0
        clean_words = await get_clean_words()

        btn.insert(0, [create_btn(text="• Bᴀᴄᴋ Uᴘ Cʜᴀɴɴᴇʟ •", url="https://t.me/KR_Picture", style=BTN_SUCCESS)])

        for file in files:
            file_id = str(file.get("file_id", "") if isinstance(file, dict) else getattr(file, "file_id", ""))
            raw_name = str(file.get("file_name", "Unknown") if isinstance(file, dict) else getattr(file, "file_name", "Unknown"))
            file_size = int(file.get("file_size", 0) if isinstance(file, dict) else getattr(file, "file_size", 0))

            display_name = clean_filename(raw_name, clean_words)
            size_str = get_size(file_size)
            url_payload = f"https://t.me/{bot_username}?start={pre}_{file_id}"

            if settings.get("button", False):
                btn.append([create_btn(text=f"{size_str} | {display_name}", url=url_payload)])
            else:
                btn.append([create_btn(text=f"{display_name}", url=url_payload), create_btn(text=f"{size_str}", url=url_payload)])

        try: total_results = int(total_results)
        except Exception: total_results = 0
        
        total_pages = math.ceil(total_results / 10) if total_results > 0 else 1

        if offset:
            btn.append([create_btn(text=f"1/{total_pages}", callback_data="pages", style=BTN_SUCCESS), create_btn(text="NEXT ➡️", callback_data=f"next_{req}_{key}_{offset}", style=BTN_PRIMARY)])
        else:
            btn.append([create_btn(text="1/1", callback_data="pages", style=BTN_SUCCESS)])

        final_caption, final_markup = parse_text_and_markup(cap, InlineKeyboardMarkup(btn))
        m = None
        
        try:
            if auto_img and str(auto_img).startswith("http"):
                m = await msg.reply_photo(photo=auto_img, caption=final_caption, reply_markup=final_markup, parse_mode=enums.ParseMode.HTML)
            else:
                m = await msg.reply_text(final_caption, reply_markup=final_markup, parse_mode=enums.ParseMode.HTML)
        except FloodWait as e:
            await asyncio.sleep(e.value + 1)
            try: m = await msg.reply_text(final_caption, reply_markup=final_markup, parse_mode=enums.ParseMode.HTML)
            except Exception: return
        except Exception: return

        delete_timer = get_auto_delete_timer()
        if delete_timer > 0 and m:
            asyncio.create_task(silent_auto_delete(m, delete_timer))
            
    except Exception as e:
        logger.error(f"Fatal error in auto_filter: {e}")


@Client.on_message(filters.group & filters.text & filters.incoming)
async def give_filter(client: Client, message: Message):
    if getattr(info, "REPAIR_MODE", False) and not await is_user_admin(client, message):
        return

    user_id = message.from_user.id if message.from_user else 0
    if user_id and await _plugin_db.is_banned(user_id):
        return

    if user_id != 0:
        last_req = USER_LAST_REQ.get(str(user_id))
        if last_req and (time.time() - last_req) < 2.0:
            return
        USER_LAST_REQ.set(str(user_id), time.time())

    try: await auto_filter(client, message)
    except Exception as e: logger.error(f"give_filter top-level error: {e}")


# ============================================================
# 🎛️ INLINE CALLBACK HANDLERS (PAGINATION)
# ============================================================
@Client.on_callback_query(filters.regex(r"^(next_)"))
async def pagination_handler(bot: Client, query: CallbackQuery):
    try: _, req, key, offset_str = query.data.split("_", 3)
    except ValueError: return await query.answer("Invalid button data!", show_alert=True)

    if int(req) not in [query.from_user.id, 0]:
        return await query.answer("⚠️ That's not for you! Request your own file in the group.", show_alert=True)

    offset = int(offset_str) if offset_str.isdigit() else 0
    search = BUTTONS_CACHE.get(key)
    if not search: return await query.answer("⌛ This search expired. Please type the movie name again!", show_alert=True)

    files, n_offset, total = await get_search_results(search, max_results=10, offset=offset, filter=True)
    if not files: return await query.answer("No more files found.", show_alert=True)

    files.sort(key=lambda x: (x.get("file_size", 0) if isinstance(x, dict) else getattr(x, "file_size", 0)), reverse=True)
    settings = await get_settings(query.message.chat.id)
    btn = []
    bot_username = temp.U_NAME or (await bot.get_me()).username or "bot"
    pre = "filep" if settings.get("file_secure", False) else "file"
    clean_words = await get_clean_words()

    btn.insert(0, [create_btn(text="• Bᴀᴄᴋ Uᴘ Cʜᴀɴɴᴇʟ •", url="https://t.me/KR_Picture", style=BTN_SUCCESS)])

    for file in files:
        file_id = str(file.get("file_id", "") if isinstance(file, dict) else getattr(file, "file_id", ""))
        raw_name = str(file.get("file_name", "Unknown") if isinstance(file, dict) else getattr(file, "file_name", "Unknown"))
        file_size = int(file.get("file_size", 0) if isinstance(file, dict) else getattr(file, "file_size", 0))

        display_name = clean_filename(raw_name, clean_words)
        size_str = get_size(file_size)
        url_payload = f"https://t.me/{bot_username}?start={pre}_{file_id}"

        if settings.get("button", False):
            btn.append([create_btn(text=f"{size_str} | {display_name}", url=url_payload)])
        else:
            btn.append([create_btn(text=f"{display_name}", url=url_payload), create_btn(text=f"{size_str}", url=url_payload)])

    off_set = 0 if 0 < offset <= 10 else None if offset == 0 else offset - 10
    try: total = int(total)
    except Exception: total = 0

    total_pages = math.ceil(total / 10) if total > 0 else 1
    current_page = math.ceil(offset / 10) + 1 if offset > 0 else 1

    nav_row = []
    if not n_offset: nav_row = [create_btn("⬅️ BACK", callback_data=f"next_{req}_{key}_{off_set}", style=BTN_PRIMARY), create_btn(f"Pages {current_page} / {total_pages}", callback_data="pages", style=BTN_SUCCESS)]
    elif off_set is None: nav_row = [create_btn(f"{current_page} / {total_pages}", callback_data="pages", style=BTN_SUCCESS), create_btn("NEXT ➡️", callback_data=f"next_{req}_{key}_{n_offset}", style=BTN_PRIMARY)]
    else: nav_row = [create_btn("⬅️ BACK", callback_data=f"next_{req}_{key}_{off_set}", style=BTN_PRIMARY), create_btn(f"{current_page} / {total_pages}", callback_data="pages", style=BTN_SUCCESS), create_btn("NEXT ➡️", callback_data=f"next_{req}_{key}_{n_offset}", style=BTN_PRIMARY)]

    btn.append(nav_row)

    try: await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(btn))
    except (MessageNotModified, MessageIdInvalid, ButtonUrlInvalid): pass
    except FloodWait as e:
        await asyncio.sleep(e.value + 1)
        try: await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(btn))
        except Exception: pass
    try: await query.answer()
    except QueryIdInvalid: pass


# ============================================================
# 🎨 KEYBOARD AND BUTTON PARSERS
# ============================================================
def build_keyboard(btn_str: str):
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
                    style_map = {1: ButtonStyle.PRIMARY, 3: ButtonStyle.SUCCESS, 4: ButtonStyle.DANGER}
                    final_style = style_map.get(style_val, style_val)
                    btn_row.append(create_btn(text=b_copy.get("text", "Button"), url=b_copy.get("url"), callback_data=b_copy.get("callback_data"), style=final_style))
                else:
                    btn_row.append(b)
            button_layout.append(btn_row)
        return button_layout
    except Exception as e:
        logger.error(f"Button parsing error: {e}")
        return None

def parse_markdown_buttons(text: str):
    if not text: return "", "[]"
    buttons, clean_lines = [], []
    for line in text.split("\n"):
        row_btns = []
        matches = list(re.finditer(r"\[([^\[\]]+)\]\(([^()]+)\)", line)) + list(re.finditer(r"\[([^\[\]]+)\|([^()]+)\]", line))
        matches.sort(key=lambda m: m.start())

        for match in matches:
            btn_text, btn_url = match.group(1).strip(), match.group(2).strip()
            row_btns.append({"text": btn_text, "url": btn_url})
        if row_btns: buttons.append(row_btns)

        clean_line = re.sub(r"\[([^\[\]]+)\]\(([^()]+)\)", "", line)
        clean_line = re.sub(r"\[([^\[\]]+)\|([^()]+)\]", "", clean_line).strip()
        if clean_line: clean_lines.append(clean_line)
        elif not matches: clean_lines.append("")

    clean_text = "\n".join(clean_lines).strip()
    return clean_text, (str(buttons) if buttons else "[]")


# ============================================================
# 🎯 FILTER COMMANDS (Fully Admin Protected)
# ============================================================
@Client.on_message(filters.command("filter") & admin_filter)
async def add_filter_cmd(client: Client, message: Message):
    grp_id, ok = await get_target_group(client, message)
    if not ok: return
    if not message.reply_to_message:
        return await message.reply_text("⚠️ **Reply to a message to set it as a filter.**")
    if len(message.command) < 2:
        return await message.reply_text("⚙️ **Usage:** `/filter <keyword>`")

    keyword = message.text.split(None, 1)[1].lower().strip()
    replied = message.reply_to_message
    raw_text = replied.text or replied.caption or ""
    text, btn = parse_markdown_buttons(raw_text)

    fileid = "None"
    for media_attr in ["photo", "video", "document", "audio", "animation", "sticker"]:
        media_obj = getattr(replied, media_attr, None)
        if media_obj:
            fileid = media_obj.file_id
            break

    await add_filter(grp_id, keyword, text, btn, "[]", fileid)
    await message.reply_text(f"✅ **Filter successfully added!**\n\n**Keyword:** `{keyword}`")

@Client.on_message(filters.command("addfilter") & admin_filter)
async def add_premade_filter_cmd(client: Client, message: Message):
    grp_id, ok = await get_target_group(client, message)
    if not ok: return
    if not message.reply_to_message:
        return await message.reply_text("⚠️ **Reply to a message containing inline buttons.**")
    if len(message.command) < 2:
        return await message.reply_text("⚙️ **Usage:** `/addfilter <keyword>`")

    keyword = message.text.split(None, 1)[1].lower().strip()
    replied = message.reply_to_message
    text = replied.text or replied.caption or ""

    buttons = []
    if replied.reply_markup and replied.reply_markup.inline_keyboard:
        for row in replied.reply_markup.inline_keyboard:
            row_btns = []
            for btn in row:
                btn_dict = {"text": btn.text}
                if btn.url: btn_dict["url"] = btn.url
                elif btn.callback_data: btn_dict["callback_data"] = btn.callback_data
                if hasattr(btn, "style") and btn.style: btn_dict["style"] = int(btn.style)
                row_btns.append(btn_dict)
            if row_btns: buttons.append(row_btns)

    btn_str = str(buttons) if buttons else "[]"
    fileid = "None"
    for media_attr in ["photo", "video", "document", "audio", "animation", "sticker"]:
        media_obj = getattr(replied, media_attr, None)
        if media_obj:
            fileid = media_obj.file_id
            break

    await add_filter(grp_id, keyword, text, btn_str, "[]", fileid)
    await message.reply_text(f"✅ **Filter with buttons added!**\n\n**Keyword:** `{keyword}`")

@Client.on_message(filters.command("filterimage") & admin_filter)
async def edit_filter_image_cmd(client: Client, message: Message):
    grp_id, ok = await get_target_group(client, message)
    if not ok: return
    if not message.reply_to_message or not message.reply_to_message.media:
        return await message.reply_text("⚠️ **Reply to a photo, video, or document to set the new image.**")
    if len(message.command) < 2:
        return await message.reply_text("⚙️ **Usage:** `/filterimage <keyword>`")

    keyword = message.text.split(None, 1)[1].lower().strip()
    replied = message.reply_to_message
    reply_text, btn, alert, old_fileid = await find_filter(grp_id, keyword)

    if not reply_text and (not old_fileid or old_fileid == "None"):
        return await message.reply_text(f"❌ Filter `{keyword}` not found.")

    fileid = "None"
    for media_attr in ["photo", "video", "document", "audio", "animation", "sticker"]:
        media_obj = getattr(replied, media_attr, None)
        if media_obj:
            fileid = media_obj.file_id
            break

    if fileid == "None":
        return await message.reply_text("❌ Could not extract valid media.")

    await add_filter(grp_id, keyword, reply_text, btn, alert, fileid)
    await message.reply_text(f"✅ **Filter image updated!**\n\n**Keyword:** `{keyword}`")

@Client.on_message(filters.command(["editfiltercolur", "editfiltercolour"]) & admin_filter)
async def edit_filter_colour_cmd(client: Client, message: Message):
    grp_id, ok = await get_target_group(client, message)
    if not ok: return
    args = message.command
    if len(args) < 4:
        return await message.reply_text("❌ **Usage:** `/editfiltercolur <keyword> <button_number> <colour>`\n\n**Colours:** `green`, `red`, `blue`")

    try:
        btn_num = int(args[-2])
        color_str = args[-1].lower()
        keyword = " ".join(args[1:-2]).lower().strip()
    except ValueError:
        return await message.reply_text("❌ Button number must be an integer.")

    color_map = {"green": 3, "red": 4, "blue": 1}
    if color_str not in color_map:
        return await message.reply_text("❌ Invalid colour. Choose from: `green`, `red`, `blue`.")

    reply_text, btn, alert, fileid = await find_filter(grp_id, keyword)
    if not reply_text and (not fileid or fileid == "None"):
        return await message.reply_text(f"❌ Filter `{keyword}` not found.")
    if not btn or btn in ["[]", "None", "False", ""]:
        return await message.reply_text(f"❌ Filter `{keyword}` has no buttons.")

    try: button_data = ast.literal_eval(btn)
    except Exception: return await message.reply_text("❌ Corrupted button format.")

    count, found = 0, False
    for r_idx, row in enumerate(button_data):
        for c_idx, b in enumerate(row):
            count += 1
            if count == btn_num:
                button_data[r_idx][c_idx]["style"] = color_map[color_str]
                found = True
                break
        if found: break

    if not found:
        return await message.reply_text(f"❌ Button {btn_num} not found. Filter has {count} buttons.")

    await add_filter(grp_id, keyword, reply_text, str(button_data), alert, fileid)
    await message.reply_text(f"✅ Filter `{keyword}` Button {btn_num} colour changed to {color_str.title()}!")

@Client.on_message(filters.command("delfilter") & admin_filter)
async def del_filter_cmd(client: Client, message: Message):
    grp_id, ok = await get_target_group(client, message)
    if not ok: return
    if len(message.command) < 2:
        return await message.reply_text("⚙️ **Usage:** `/delfilter <keyword>`")
    keyword = message.text.split(None, 1)[1].lower().strip()
    await delete_filter(message, keyword, grp_id)
    await message.reply_text(f"🗑️ **Filter `{keyword}` deleted.**")

@Client.on_message(filters.command("listfilters") & admin_filter)
async def list_filters_cmd(client: Client, message: Message):
    grp_id, ok = await get_target_group(client, message)
    if not ok: return
    keywords = await get_filters(grp_id)
    if not keywords:
        return await message.reply_text("⚠️ **No active filters found.**")
    text = "📋 **Current Filters:**\n\n" + "\n".join([f"• `{kw}`" for kw in keywords])
    await message.reply_text(text)


# ============================================================
# 📤 4-LAYER MULTI-MEDIA FILTER DISPATCHER
# ============================================================
async def send_filter_media(client: Client, chat_id: int, fileid: str, reply_text: str, reply_markup, reply_id: int):
    try:
        return await client.send_cached_media(chat_id, fileid, caption=reply_text, reply_markup=reply_markup, reply_to_message_id=reply_id)
    except FloodWait as e:
        await asyncio.sleep(e.value + 1)
        return await send_filter_media(client, chat_id, fileid, reply_text, reply_markup, reply_id)
    except (UserIsBlocked, PeerIdInvalid):
        return None
    except Exception:
        pass

    try: return await client.send_cached_media(chat_id, fileid, caption=reply_text, reply_markup=reply_markup)
    except Exception: pass

    for send_fn, arg_name in [(client.send_photo, "photo"), (client.send_video, "video"), (client.send_document, "document"), (client.send_animation, "animation")]:
        try:
            return await send_fn(**{"chat_id": chat_id, arg_name: fileid, "caption": reply_text, "reply_markup": reply_markup})
        except Exception: continue

    try: return await client.send_message(chat_id, text=reply_text or "Here is your file:", reply_markup=reply_markup)
    except Exception as err:
        logger.error(f"Media filter failed all 4 layers: {err}")
        return None

async def safe_send_text_filter(client: Client, chat_id: int, text: str, reply_markup, reply_id: int):
    try:
        return await client.send_message(chat_id, text, disable_web_page_preview=True, reply_markup=reply_markup, reply_to_message_id=reply_id)
    except Exception:
        try: return await client.send_message(chat_id, text, disable_web_page_preview=True, reply_markup=reply_markup)
        except Exception as e:
            logger.error(f"Text filter failed: {e}")
            return None


# ============================================================
# ⚡ LIVE GROUP TRIGGER HANDLER
# ============================================================
async def manual_filters(client: Client, message: Message, text=False):
    if getattr(info, "REPAIR_MODE", False) and not await is_user_admin(client, message):
        return False

    group_id = message.chat.id
    if message.chat.type == enums.ChatType.PRIVATE:
        active_grp = await active_connection(str(message.from_user.id if message.from_user else 0))
        if active_grp: group_id = active_grp

    name = text or message.text or message.caption or ""
    reply_id = message.reply_to_message.id if message.reply_to_message else message.id
    keywords = await get_filters(group_id)
    if not keywords: return False

    for keyword in reversed(sorted(keywords, key=len)):
        pattern = r"( |^|[^\w])" + re.escape(keyword) + r"( |$|[^\w])"
        if re.search(pattern, name, flags=re.IGNORECASE):
            reply_text, btn, alert, fileid = await find_filter(group_id, keyword)
            if reply_text: reply_text = reply_text.replace("\\n", "\n").replace("\\t", "\t")

            button_layout = build_keyboard(btn)
            reply_markup = InlineKeyboardMarkup(button_layout) if button_layout else None
            sent_msg = None
            fileid_str = str(fileid).strip()

            if not fileid or fileid_str in ["None", "[]", "", "False"]:
                sent_msg = await safe_send_text_filter(client, message.chat.id, reply_text or "", reply_markup, reply_id)
            else:
                sent_msg = await send_filter_media(client, message.chat.id, fileid, reply_text or "", reply_markup, reply_id)

            if sent_msg:
                delete_timer = getattr(info, "BUTTON_AUTO_DELETE", 1800)
                if delete_timer > 0:
                    asyncio.create_task(silent_auto_delete(sent_msg, delete_timer))
            return True
    return False

@Client.on_message(filters.group & filters.text & ~filters.bot, group=5)
async def filter_listener_hook(client: Client, message: Message):
    if message.text.startswith("/"): return
    await manual_filters(client, message)
