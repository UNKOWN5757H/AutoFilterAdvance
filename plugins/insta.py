import asyncio
import json
import logging
import os
import re
import shutil
import time
import uuid

import requests
import yt_dlp
from motor.motor_asyncio import AsyncIOMotorClient
from pyrogram import Client, enums, filters
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

import info

logger = logging.getLogger(__name__)

DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
download_semaphore = asyncio.Semaphore(3)  # Max 3 parallel downloads


# ============================================================
# 🛡️ BULLETPROOF ADMIN FILTERS
# ============================================================
def get_admin_list():
    raw_admins = getattr(info, "ADMINS", [])
    if isinstance(raw_admins, str):
        return [x.strip() for x in raw_admins.replace(",", " ").split() if x.strip()]
    elif isinstance(raw_admins, int):
        return [str(raw_admins)]
    elif isinstance(raw_admins, list):
        return [str(a) for a in raw_admins]
    return []


async def admin_check(_, __, message: Message):
    if not message.from_user:
        return False
    return str(message.from_user.id) in get_admin_list()


admin_filter = filters.create(admin_check)


async def cb_admin_check(_, __, query: CallbackQuery):
    if not query.from_user:
        return False
    return str(query.from_user.id) in get_admin_list()


cb_admin_filter = filters.create(cb_admin_check)


# ============================================================
# 🗄️ LAZY-INITIALIZED INSTAGRAM DATABASE MANAGER (WITH TIMEOUT)
# ============================================================
class InstaDatabase:
    def __init__(self):
        self.client = None
        self.db = None

    def _ensure_connected(self):
        if not self.client:
            try:
                db_uri = getattr(
                    info, "DATABASE_URI", getattr(info, "DATABASE_URL", None)
                )
                if db_uri:
                    # 5-second timeout prevents the bot from hanging if DB goes offline
                    self.client = AsyncIOMotorClient(
                        db_uri, serverSelectionTimeoutMS=5000
                    )
                    self.db = self.client["InstaBotPlugin"]
            except Exception as e:
                logger.error(f"InstaDB Connection Error: {e}")
                self.db = None

    async def get_settings(self):
        self._ensure_connected()
        if not self.db:
            return "both"
        try:
            doc = await self.db.settings.find_one({"_id": "insta_config"})
            return doc["mode"] if doc else "both"
        except Exception:
            return "both"

    async def set_settings(self, mode):
        self._ensure_connected()
        if not self.db:
            return
        try:
            await self.db.settings.update_one(
                {"_id": "insta_config"}, {"$set": {"mode": mode}}, upsert=True
            )
        except Exception:
            pass

    async def inc_success(self, user_id, name, username, url):
        self._ensure_connected()
        if not self.db:
            return
        try:
            await self.db.stats.update_one(
                {"_id": "global_stats"}, {"$inc": {"success": 1}}, upsert=True
            )
            await self.db.users.update_one(
                {"user_id": user_id},
                {"$inc": {"count": 1}, "$set": {"name": name, "username": username}},
                upsert=True,
            )
            await self.db.links.insert_one(
                {"url": url, "user_id": user_id, "time": time.time()}
            )
        except Exception:
            pass

    async def inc_failed(self):
        self._ensure_connected()
        if not self.db:
            return
        try:
            await self.db.stats.update_one(
                {"_id": "global_stats"}, {"$inc": {"failed": 1}}, upsert=True
            )
        except Exception:
            pass

    async def get_stats(self):
        self._ensure_connected()
        if not self.db:
            return 0, 0
        try:
            doc = await self.db.stats.find_one({"_id": "global_stats"})
            if doc:
                return doc.get("success", 0), doc.get("failed", 0)
        except Exception:
            pass
        return 0, 0

    async def get_top_users(self):
        self._ensure_connected()
        if not self.db:
            return []
        try:
            cursor = self.db.users.find({}).sort("count", -1).limit(10)
            return await cursor.to_list(length=10)
        except Exception:
            return []

    async def get_all_links(self):
        self._ensure_connected()
        if not self.db:
            return []
        try:
            cursor = self.db.links.find({})
            links = await cursor.to_list(length=None)
            return [doc["url"] for doc in links if "url" in doc]
        except Exception:
            return []


instadb = InstaDatabase()


# ============================================================
# ⚙️ ADMIN COMMANDS
# ============================================================
@Client.on_message(filters.command("enableinsta") & admin_filter, group=1)
async def enable_insta_cmd(client: Client, message: Message):
    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🏢 Group Only", callback_data="instamode_group"),
                InlineKeyboardButton("👤 PM Only", callback_data="instamode_pm"),
            ],
            [
                InlineKeyboardButton(
                    "🌐 Both (Group & PM)", callback_data="instamode_both"
                )
            ],
        ]
    )
    await message.reply_text(
        "⚙️ **Where should the Instagram Downloader work?**\nChoose an option below:",
        reply_markup=kb,
    )


@Client.on_callback_query(
    filters.regex(r"^instamode_(group|pm|both)$") & cb_admin_filter, group=1
)
async def set_insta_mode_cb(client: Client, query: CallbackQuery):
    mode = query.matches[0].group(1)
    await instadb.set_settings(mode)
    await query.message.edit_text(
        f"✅ **Instagram Downloads are now ENABLED globally for:** `{mode.upper()}`"
    )
    await query.answer("Settings updated!", show_alert=False)


@Client.on_message(
    filters.command(["disableinsta", "disableintsa"]) & admin_filter, group=1
)
async def disable_insta_cmd(client: Client, message: Message):
    await instadb.set_settings("off")
    await message.reply_text(
        "🚫 **Instagram Downloads are now completely DISABLED globally.**"
    )


@Client.on_message(
    filters.command(["instastats", "instastatas"]) & admin_filter, group=1
)
async def insta_stats_cmd(client: Client, message: Message):
    msg = await message.reply_text("⏳ Fetching statistics...")
    success, failed = await instadb.get_stats()
    mode = await instadb.get_settings()
    status = "🔴 DISABLED" if mode == "off" else f"🟢 ENABLED ({mode.upper()})"
    text = (
        "📊 **Instagram Downloader Statistics**\n━━━━━━━━━━━━━━━━━━━━\n"
        f"⚙️ **Global Status:** {status}\n\n✅ **Total Downloaded:** `{success}` links\n❌ **Total Failed:** `{failed}` links\n━━━━━━━━━━━━━━━━━━━━"
    )
    await msg.edit_text(text)


@Client.on_message(filters.command("instatop") & admin_filter, group=1)
async def insta_top_cmd(client: Client, message: Message):
    msg = await message.reply_text("⏳ Fetching Top 10 users...")
    top_users = await instadb.get_top_users()
    if not top_users:
        return await msg.edit_text("⚠️ No users have downloaded anything yet.")
    text = "🏆 **Top 10 Instagram Downloaders**\n━━━━━━━━━━━━━━━━━━━━\n\n"
    for i, u in enumerate(top_users, 1):
        name = u.get("name", "Unknown")
        uid = u.get("user_id", "N/A")
        username = f"@{u.get('username')}" if u.get("username") else "No Username"
        count = u.get("count", 0)
        text += f"**{i}.** <a href='tg://user?id={uid}'>{name}</a>\n├ 🆔 `{uid}` | {username}\n└ 📥 **Downloaded:** `{count}` links\n\n"
    await msg.edit_text(text, disable_web_page_preview=True)


@Client.on_message(filters.command("instalinks") & admin_filter, group=1)
async def insta_links_cmd(client: Client, message: Message):
    msg = await message.reply_text("⏳ Fetching and exporting all links...")
    links = await instadb.get_all_links()
    if not links:
        return await msg.edit_text("⚠️ No links downloaded yet.")
    file_path = "instalinks.txt"
    with open(file_path, "w", encoding="utf-8") as f:
        f.write("\n".join(links))
    caption = f"📁 **Exported {len(links)} Instagram Links.**"
    await message.reply_document(document=file_path, caption=caption)

    log_channel = getattr(info, "LOG_CHANNEL", None)
    if log_channel:
        try:
            await client.send_document(
                chat_id=int(log_channel), document=file_path, caption=caption
            )
        except Exception:
            pass
    await msg.delete()
    if os.path.exists(file_path):
        os.remove(file_path)


# ============================================================
# 📥 INSTAGRAM DOWNLOADER ENGINE
# ============================================================
class InstaDownloader:
    @staticmethod
    def extract_url(text):
        if not text:
            return None
        m = re.search(
            r"(https?://(?:www\.)?instagram\.com/(?:p|reel|tv|stories)/[a-zA-Z0-9_\-\.]+)",
            text,
        )
        return m.group(1) if m else None

    @staticmethod
    def get_shortcode(url):
        m = re.search(r"/(p|reel|tv|stories)/([a-zA-Z0-9_\-]+)", url)
        return m.group(2) if m else None

    @staticmethod
    def download_media(url, task_dir):
        shortcode = InstaDownloader.get_shortcode(url)
        if not shortcode:
            return {"success": False, "error": "Invalid Link"}
        is_reel_or_story = "/reel/" in url or "/tv/" in url or "/stories/" in url
        if is_reel_or_story:
            return InstaDownloader._download_video(shortcode, url, task_dir)
        else:
            return InstaDownloader._download_photo(shortcode, url, task_dir)

    @staticmethod
    def _download_video(shortcode, url, task_dir):
        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "outtmpl": os.path.join(task_dir, f"{shortcode}.%(ext)s"),
            "format": "bv*+ba/b",
            "merge_output_format": "mp4",
            "socket_timeout": 30,
            "ignoreerrors": True,
            "http_headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            },
        }
        if os.path.exists("cookies.txt"):
            ydl_opts["cookiefile"] = "cookies.txt"
        if shutil.which("ffmpeg"):
            ydl_opts["ffmpeg_location"] = shutil.which("ffmpeg")

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
        except Exception:
            pass

        time.sleep(1)
        for f in os.listdir(task_dir):
            fp = os.path.join(task_dir, f)
            if f.endswith((".mp4", ".mkv", ".webm")) and os.path.getsize(fp) > 50000:
                return {"success": True, "file_path": fp, "is_video": True}

        ydl_opts["format"] = "best[ext=mp4]/best"
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
        except Exception:
            pass

        time.sleep(1)
        for f in os.listdir(task_dir):
            fp = os.path.join(task_dir, f)
            if f.endswith((".mp4", ".mkv", ".webm")) and os.path.getsize(fp) > 50000:
                return {"success": True, "file_path": fp, "is_video": True}

        return {
            "success": False,
            "error": "Unable to fetch video. Ensure cookies.txt is valid.",
        }

    @staticmethod
    def _download_photo(shortcode, url, task_dir):
        result = InstaDownloader._method_scrape_multi(shortcode, url, task_dir)
        if result.get("success"):
            return result
        for method in [
            InstaDownloader._method_ytdlp,
            InstaDownloader._method_scrape_single,
            InstaDownloader._method_cdn,
        ]:
            result = method(shortcode, task_dir)
            if result.get("success"):
                return result
        return {"success": False, "error": "Unable to fetch photo."}

    @staticmethod
    def _method_scrape_multi(shortcode, url, task_dir):
        try:
            session = requests.Session()
            session.headers.update(
                {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X)"}
            )
            resp = session.get(url, timeout=15)
            if resp.status_code != 200:
                return {"success": False}
            html = resp.text
            image_urls = []

            nd = re.search(
                r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL
            )
            if nd:
                try:
                    data_str = json.dumps(json.loads(nd.group(1)))
                    for carousel in re.findall(
                        r'"edge_sidecar_to_children"[^}]*"edges":\s*\[(.*?)\]',
                        data_str,
                        re.DOTALL,
                    ):
                        for du in re.findall(r'"display_url":"([^"]+)"', carousel):
                            cleaned = du.replace("\\u0026", "&")
                            if cleaned not in image_urls and ".mp4" not in cleaned:
                                image_urls.append(cleaned)
                except Exception:
                    pass

            if not image_urls:
                image_urls = [
                    u.replace("\\u0026", "&")
                    for u in re.findall(r'"display_url":"([^"]+)"', html)
                    if ".mp4" not in u
                ]
            if not image_urls:
                image_urls = list(
                    set(
                        re.findall(
                            r'<meta\s+property="og:image"\s+content="([^"]+)"', html
                        )
                    )
                )
            image_urls = list(dict.fromkeys(image_urls))

            if not image_urls:
                return {"success": False}

            downloaded = []
            for i, img_url in enumerate(image_urls[:10]):
                try:
                    fp = os.path.join(task_dir, f"multi_{shortcode}_{i}.jpg")
                    r = session.get(
                        img_url,
                        headers={"User-Agent": "Mozilla/5.0"},
                        stream=True,
                        timeout=15,
                    )
                    if r.status_code == 200:
                        with open(fp, "wb") as f:
                            for chunk in r.iter_content(8192):
                                f.write(chunk)
                        if os.path.getsize(fp) > 1000:
                            downloaded.append(fp)
                except Exception:
                    continue

            if downloaded:
                return {
                    "success": True,
                    "file_path": downloaded[0],
                    "file_paths": downloaded,
                    "is_video": False,
                    "is_multiple": len(downloaded) > 1,
                }
            return {"success": False}
        except Exception:
            return {"success": False}

    @staticmethod
    def _method_ytdlp(shortcode, task_dir):
        try:
            url = f"https://www.instagram.com/p/{shortcode}/"
            ydl_opts = {
                "quiet": True,
                "outtmpl": os.path.join(task_dir, f"{shortcode}.%(ext)s"),
                "format": "best",
            }
            if os.path.exists("cookies.txt"):
                ydl_opts["cookiefile"] = "cookies.txt"
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.extract_info(url, download=True)
                time.sleep(0.5)
                for f in os.listdir(task_dir):
                    fp = os.path.join(task_dir, f)
                    if (
                        shortcode in f
                        and not f.endswith((".mp4", ".mov", ".webm"))
                        and os.path.getsize(fp) > 1000
                    ):
                        return {"success": True, "file_path": fp, "is_video": False}
        except Exception:
            pass
        return {"success": False}

    @staticmethod
    def _method_scrape_single(shortcode, task_dir):
        try:
            session = requests.Session()
            session.headers.update({"User-Agent": "Mozilla/5.0"})
            resp = session.get(f"https://www.instagram.com/p/{shortcode}/", timeout=10)
            if resp.status_code != 200:
                return {"success": False}
            image_urls = re.findall(
                r'"display_url":"([^"]+)"', resp.text
            ) or re.findall(
                r'<meta\s+property="og:image"\s+content="([^"]+)"', resp.text
            )
            for img_url in list(set(image_urls))[:3]:
                try:
                    if ".mp4" in img_url:
                        continue
                    fp = os.path.join(task_dir, f"{shortcode}.jpg")
                    r = session.get(img_url, stream=True, timeout=15)
                    if r.status_code == 200:
                        with open(fp, "wb") as f:
                            for chunk in r.iter_content(8192):
                                f.write(chunk)
                        if os.path.getsize(fp) > 1000:
                            return {"success": True, "file_path": fp, "is_video": False}
                except Exception:
                    continue
            return {"success": False}
        except Exception:
            return {"success": False}

    @staticmethod
    def _method_cdn(shortcode, task_dir):
        try:
            cdn_urls = [
                f"https://www.instagram.com/p/{shortcode}/media/?size=l",
                f"https://i.instagram.com/{shortcode}.jpg",
            ]
            for cdn_url in cdn_urls:
                try:
                    r = requests.get(
                        cdn_url,
                        headers={"User-Agent": "Mozilla/5.0"},
                        stream=True,
                        timeout=15,
                    )
                    if r.status_code == 200 and "image" in r.headers.get(
                        "content-type", ""
                    ):
                        fp = os.path.join(task_dir, f"{shortcode}.jpg")
                        with open(fp, "wb") as f:
                            for chunk in r.iter_content(8192):
                                f.write(chunk)
                        if os.path.getsize(fp) > 1000:
                            return {"success": True, "file_path": fp, "is_video": False}
                except Exception:
                    continue
        except Exception:
            pass
        return {"success": False}


# ============================================================
# 🔗 MAIN DOWNLOAD HANDLER
# ============================================================
@Client.on_message(
    (
        filters.command("insta")
        | filters.regex(
            r"(https?://)?(www\.)?instagram\.com/(p|reel|tv|stories)/([a-zA-Z0-9_\-\.]+)"
        )
    )
    & filters.incoming,
    group=1,
)
async def handle_instagram_link(client: Client, message: Message):
    mode = await instadb.get_settings()
    if mode == "off":
        return
    is_pm = message.chat.type == enums.ChatType.PRIVATE
    if mode == "group" and is_pm:
        return await message.reply_text(
            "⚠️ **Instagram downloading is currently restricted to Groups only.**"
        )
    elif mode == "pm" and not is_pm:
        return await message.reply_text(
            "⚠️ **Instagram downloading is currently restricted to PMs only.**"
        )

    raw_text = message.text or ""
    url = InstaDownloader.extract_url(raw_text)
    if not url and getattr(message, "command", None) and len(message.command) > 1:
        url = InstaDownloader.extract_url(message.command[1])

    if not url:
        if raw_text.startswith("/insta"):
            return await message.reply_text(
                "⚠️ **Please provide a valid Instagram link.**\nExample: `/insta https://instagram.com/reel/...`"
            )
        return

    status_msg = await message.reply_text("⏳ Processing Link...", quote=True)
    task_id = str(uuid.uuid4())[:8]
    task_dir = os.path.join(DOWNLOAD_DIR, f"task_{task_id}")
    os.makedirs(task_dir, exist_ok=True)

    user_id = message.from_user.id if message.from_user else 0
    name = message.from_user.first_name if message.from_user else "Unknown"
    username = message.from_user.username if message.from_user else ""

    async with download_semaphore:
        try:
            await status_msg.edit_text("📥 Downloading Media...")
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None, InstaDownloader.download_media, url, task_dir
            )

            if not result or not result.get("success"):
                await instadb.inc_failed()
                return await status_msg.edit_text(
                    f"❌ Failed: {result.get('error', 'Unknown error')}"
                )

            await instadb.inc_success(user_id, name, username, url)

            if result.get("is_multiple"):
                await status_msg.edit_text("📤 Uploading Photos...")
                for path in result["file_paths"]:
                    if os.path.exists(path):
                        await message.reply_photo(photo=path, quote=True)
                        await asyncio.sleep(0.5)
            elif result.get("is_video"):
                await status_msg.edit_text("📤 Uploading Video...")
                await message.reply_video(
                    video=result["file_path"], supports_streaming=True, quote=True
                )
            else:
                await status_msg.edit_text("📤 Uploading Photo...")
                await message.reply_photo(photo=result["file_path"], quote=True)

            await status_msg.delete()
        except Exception as e:
            logger.error(f"Error handling Instagram download: {e}")
            await instadb.inc_failed()
            await status_msg.edit_text(f"❌ Error occurred: {str(e)[:50]}")
        finally:
            if os.path.exists(task_dir):
                shutil.rmtree(task_dir, ignore_errors=True)
