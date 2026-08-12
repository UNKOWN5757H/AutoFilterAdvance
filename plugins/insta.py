import os
import re
import shutil
import time
import json
import urllib.parse
import asyncio
import requests
import yt_dlp
import subprocess
import uuid
import concurrent.futures
import logging

from pyrogram import Client, filters, enums
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from motor.motor_asyncio import AsyncIOMotorClient

import info

logger = logging.getLogger(__name__)

DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
download_semaphore = asyncio.Semaphore(3)  # Max 3 parallel downloads

# ============================================================
# 🛡️ SAFE ADMIN FILTERS
# ============================================================
async def admin_check(_, __, message: Message):
    if not message.from_user: return False
    return message.from_user.id in info.ADMINS or str(message.from_user.id) in info.ADMINS

admin_filter = filters.create(admin_check)

async def cb_admin_check(_, __, query: CallbackQuery):
    if not query.from_user: return False
    return query.from_user.id in info.ADMINS or str(query.from_user.id) in info.ADMINS

cb_admin_filter = filters.create(cb_admin_check)


# ============================================================
# 🗄️ INSTAGRAM DATABASE MANAGER
# ============================================================
class InstaDatabase:
    def __init__(self):
        try:
            db_uri = getattr(info, "DATABASE_URI", getattr(info, "DATABASE_URL", None))
            self.client = AsyncIOMotorClient(db_uri)
            self.db = self.client["InstaBotPlugin"]
        except Exception as e:
            logger.error(f"InstaDB Connection Error: {e}")
            self.db = None

    async def get_settings(self):
        if not self.db: return "both"
        doc = await self.db.settings.find_one({"_id": "insta_config"})
        return doc["mode"] if doc else "both"

    async def set_settings(self, mode):
        if not self.db: return
        await self.db.settings.update_one({"_id": "insta_config"}, {"$set": {"mode": mode}}, upsert=True)

    async def inc_success(self, user_id, name, username, url):
        if not self.db: return
        # Global stats
        await self.db.stats.update_one({"_id": "global_stats"}, {"$inc": {"success": 1}}, upsert=True)
        # User stats
        await self.db.users.update_one(
            {"user_id": user_id},
            {"$inc": {"count": 1}, "$set": {"name": name, "username": username}},
            upsert=True
        )
        # Store Link
        await self.db.links.insert_one({"url": url, "user_id": user_id, "time": time.time()})

    async def inc_failed(self):
        if not self.db: return
        await self.db.stats.update_one({"_id": "global_stats"}, {"$inc": {"failed": 1}}, upsert=True)

    async def get_stats(self):
        if not self.db: return 0, 0
        doc = await self.db.stats.find_one({"_id": "global_stats"})
        if doc: return doc.get("success", 0), doc.get("failed", 0)
        return 0, 0

    async def get_top_users(self):
        if not self.db: return []
        cursor = self.db.users.find({}).sort("count", -1).limit(10)
        return await cursor.to_list(length=10)

    async def get_all_links(self):
        if not self.db: return []
        cursor = self.db.links.find({})
        links = await cursor.to_list(length=None)
        return [doc["url"] for doc in links]

instadb = InstaDatabase()


# ============================================================
# ⚙️ ADMIN COMMANDS
# ============================================================

@Client.on_message(filters.command("enableinsta") & admin_filter)
async def enable_insta_cmd(client: Client, message: Message):
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🏢 Group Only", callback_data="instamode_group"),
            InlineKeyboardButton("👤 PM Only", callback_data="instamode_pm")
        ],
        [
            InlineKeyboardButton("🌐 Both (Group & PM)", callback_data="instamode_both")
        ]
    ])
    await message.reply_text(
        "⚙️ **Where should the Instagram Downloader work?**\nChoose an option below:",
        reply_markup=kb
    )

@Client.on_callback_query(filters.regex(r"^instamode_(group|pm|both)$") & cb_admin_filter)
async def set_insta_mode_cb(client: Client, query: CallbackQuery):
    mode = query.matches[0].group(1)
    await instadb.set_settings(mode)
    await query.message.edit_text(f"✅ **Instagram Downloads are now ENABLED globally for:** `{mode.upper()}`")
    await query.answer("Settings updated!", show_alert=False)

@Client.on_message(filters.command(["disableinsta", "disableintsa"]) & admin_filter)
async def disable_insta_cmd(client: Client, message: Message):
    await instadb.set_settings("off")
    await message.reply_text("🚫 **Instagram Downloads are now completely DISABLED globally.**")

@Client.on_message(filters.command(["instastats", "instastatas"]) & admin_filter)
async def insta_stats_cmd(client: Client, message: Message):
    msg = await message.reply_text("⏳ Fetching statistics...")
    success, failed = await instadb.get_stats()
    mode = await instadb.get_settings()
    
    status = "🔴 DISABLED" if mode == "off" else f"🟢 ENABLED ({mode.upper()})"
    
    text = (
        "📊 **Instagram Downloader Statistics**\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"⚙️ **Global Status:** {status}\n\n"
        f"✅ **Total Downloaded:** `{success}` links\n"
        f"❌ **Total Failed:** `{failed}` links\n"
        "━━━━━━━━━━━━━━━━━━━━"
    )
    await msg.edit_text(text)

@Client.on_message(filters.command("instatop") & admin_filter)
async def insta_top_cmd(client: Client, message: Message):
    msg = await message.reply_text("⏳ Fetching Top 10 users...")
    top_users = await instadb.get_top_users()
    
    if not top_users:
        return await msg.edit_text("⚠️ No users have downloaded anything yet.")
        
    text = "🏆 **Top 10 Instagram Downloaders**\n━━━━━━━━━━━━━━━━━━━━\n\n"
    for i, u in enumerate(top_users, 1):
        name = u.get('name', 'Unknown')
        uid = u.get('user_id', 'N/A')
        username = f"@{u.get('username')}" if u.get('username') else "No Username"
        count = u.get('count', 0)
        
        text += f"**{i}.** <a href='tg://user?id={uid}'>{name}</a>\n"
        text += f"├ 🆔 `{uid}` | {username}\n"
        text += f"└ 📥 **Downloaded:** `{count}` links\n\n"
        
    await msg.edit_text(text, disable_web_page_preview=True)

@Client.on_message(filters.command("instalinks") & admin_filter)
async def insta_links_cmd(client: Client, message: Message):
    msg = await message.reply_text("⏳ Fetching and exporting all links...")
    links = await instadb.get_all_links()
    
    if not links:
        return await msg.edit_text("⚠️ No links downloaded yet.")
        
    file_path = "instalinks.txt"
    with open(file_path, "w", encoding="utf-8") as f:
        f.write("\n".join(links))
        
    caption = f"📁 **Exported {len(links)} Instagram Links.**"
    
    # Send to User
    await message.reply_document(document=file_path, caption=caption)
    
    # Send to LOG_CHANNEL
    log_channel = getattr(info, "LOG_CHANNEL", None)
    if log_channel:
        try:
            await client.send_document(chat_id=int(log_channel), document=file_path, caption=caption)
        except Exception as e:
            logger.error(f"Failed to send instalinks to log channel: {e}")
            
    await msg.delete()
    os.remove(file_path)


# ============================================================
# 📥 INSTAGRAM DOWNLOADER ENGINE
# ============================================================
class InstaDownloader:
    @staticmethod
    def extract_url(text):
        if not text: return None
        m = re.search(r'(https?://)?(www\.)?instagram\.com/(p|reel|tv)/([a-zA-Z0-9_\-]+)', text)
        return f"https://www.instagram.com/{m.group(3)}/{m.group(4)}/" if m else None
    
    @staticmethod
    def get_shortcode(url):
        m = re.search(r'/(p|reel|tv)/([a-zA-Z0-9_\-]+)', url)
        return m.group(2) if m else None
    
    @staticmethod
    def download_media(url, task_dir):
        shortcode = InstaDownloader.get_shortcode(url)
        if not shortcode: return {"success": False, "error": "Invalid Link"}
        is_reel = '/reel/' in url or '/tv/' in url
        if is_reel: 
            return InstaDownloader._download_video(shortcode, url, task_dir)
        else: 
            return InstaDownloader._download_photo(shortcode, url, task_dir)
    
    @staticmethod
    def _download_video(shortcode, url, task_dir):
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'outtmpl': os.path.join(task_dir, f'{shortcode}.%(ext)s'),
            'format': 'bv*+ba/b',
            'merge_output_format': 'mp4',
            'socket_timeout': 60,
            'ignoreerrors': True,
            'http_headers': {'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0)'}
        }
    
        if shutil.which('ffmpeg'):
            ydl_opts['ffmpeg_location'] = shutil.which('ffmpeg')
    
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
        except Exception:
            pass
    
        time.sleep(1)
        for f in os.listdir(task_dir):
            if f.endswith(('.mp4', '.mkv', '.webm')):
                fp = os.path.join(task_dir, f)
                if os.path.getsize(fp) > 50000:
                    return {"success": True, "file_path": fp, "is_video": True}
        
        # Fallback format
        ydl_opts['format'] = 'best[ext=mp4]/best'
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
        except Exception:
            pass
            
        time.sleep(1)
        for f in os.listdir(task_dir):
            if f.endswith(('.mp4', '.mkv', '.webm')):
                fp = os.path.join(task_dir, f)
                if os.path.getsize(fp) > 50000:
                    return {"success": True, "file_path": fp, "is_video": True}
    
        return {"success": False, "error": "Server busy, unable to fetch video."}
    
    @staticmethod
    def _download_photo(shortcode, url, task_dir):
        result = InstaDownloader._method_scrape_multi(shortcode, url, task_dir)
        if result.get("success"): return result
        
        for method in [InstaDownloader._method_ytdlp, InstaDownloader._method_scrape_single, InstaDownloader._method_cdn]:
            result = method(shortcode, task_dir)
            if result.get("success"): return result
            
        return {"success": False, "error": "Unable to fetch photo."}
    
    @staticmethod
    def _method_scrape_multi(shortcode, url, task_dir):
        try:
            session = requests.Session()
            session.headers.update({'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0)'})
            resp = session.get(url, timeout=15)
            if resp.status_code != 200: return {"success": False}
            html = resp.text
            image_urls = []
            
            nd = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
            if nd:
                try:
                    data_str = json.dumps(json.loads(nd.group(1)))
                    carousel_matches = re.findall(r'"edge_sidecar_to_children"[^}]*"edges":\s*\[(.*?)\]', data_str, re.DOTALL)
                    if carousel_matches:
                        for carousel in carousel_matches:
                            for du in re.findall(r'"display_url":"([^"]+)"', carousel):
                                cleaned = du.replace('\\u0026', '&')
                                if cleaned not in image_urls and '.mp4' not in cleaned:
                                    image_urls.append(cleaned)
                except Exception: pass
            
            if not image_urls:
                image_urls = [u.replace('\\u0026', '&') for u in re.findall(r'"display_url":"([^"]+)"', html) if '.mp4' not in u]
            if not image_urls:
                image_urls = list(set(re.findall(r'<meta\s+property="og:image"\s+content="([^"]+)"', html)))
            
            image_urls = list(dict.fromkeys(image_urls))
            
            if not image_urls: return {"success": False}
            
            downloaded = []
            for i, img_url in enumerate(image_urls[:10]):
                try:
                    fp = os.path.join(task_dir, f"multi_{shortcode}_{i}.jpg")
                    r = session.get(img_url, headers={'User-Agent': 'Mozilla/5.0'}, stream=True, timeout=30)
                    if r.status_code == 200:
                        with open(fp, 'wb') as f:
                            for chunk in r.iter_content(8192): f.write(chunk)
                        if os.path.getsize(fp) > 1000: downloaded.append(fp)
                except Exception: continue
            
            if downloaded:
                return {
                    "success": True, 
                    "file_path": downloaded[0], 
                    "file_paths": downloaded, 
                    "is_video": False, 
                    "is_multiple": len(downloaded) > 1
                }
            return {"success": False}
        except Exception: return {"success": False}
    
    @staticmethod
    def _method_ytdlp(shortcode, task_dir):
        try:
            url = f"https://www.instagram.com/p/{shortcode}/"
            ydl_opts = {'quiet': True, 'outtmpl': os.path.join(task_dir, f'{shortcode}.%(ext)s'), 'format': 'best'}
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.extract_info(url, download=True)
                time.sleep(0.5)
                for f in os.listdir(task_dir):
                    if shortcode in f and not f.endswith(('.mp4','.mov','.webm')):
                        fp = os.path.join(task_dir, f)
                        if os.path.getsize(fp) > 1000: return {"success": True, "file_path": fp, "is_video": False}
        except Exception: pass
        return {"success": False}
    
    @staticmethod
    def _method_scrape_single(shortcode, task_dir):
        try:
            session = requests.Session()
            session.headers.update({'User-Agent': 'Mozilla/5.0'})
            resp = session.get(f"https://www.instagram.com/p/{shortcode}/", timeout=10)
            if resp.status_code != 200: return {"success": False}
            image_urls = re.findall(r'"display_url":"([^"]+)"', resp.text) or re.findall(r'<meta\s+property="og:image"\s+content="([^"]+)"', resp.text)
            
            for img_url in list(set(image_urls))[:3]:
                try:
                    if '.mp4' in img_url: continue
                    fp = os.path.join(task_dir, f"{shortcode}.jpg")
                    r = session.get(img_url, stream=True, timeout=20)
                    if r.status_code == 200:
                        with open(fp, 'wb') as f:
                            for chunk in r.iter_content(8192): f.write(chunk)
                        if os.path.getsize(fp) > 1000: return {"success": True, "file_path": fp, "is_video": False}
                except Exception: continue
            return {"success": False}
        except Exception: return {"success": False}
    
    @staticmethod
    def _method_cdn(shortcode, task_dir):
        try:
            cdn_urls = [f"https://www.instagram.com/p/{shortcode}/media/?size=l", f"https://i.instagram.com/{shortcode}.jpg"]
            for cdn_url in cdn_urls:
                try:
                    r = requests.get(cdn_url, headers={'User-Agent': 'Mozilla/5.0'}, stream=True, timeout=20)
                    if r.status_code == 200 and 'image' in r.headers.get('content-type', ''):
                        fp = os.path.join(task_dir, f"{shortcode}.jpg")
                        with open(fp, 'wb') as f:
                            for chunk in r.iter_content(8192): f.write(chunk)
                        if os.path.getsize(fp) > 1000: return {"success": True, "file_path": fp, "is_video": False}
                except Exception: continue
        except Exception: pass
        return {"success": False}


# ============================================================
# 🔗 MAIN DOWNLOAD HANDLER
# ============================================================
@Client.on_message((filters.command("insta") | filters.regex(r'(https?://)?(www\.)?instagram\.com/(p|reel|tv)/([a-zA-Z0-9_\-]+)')) & filters.incoming)
async def handle_instagram_link(client: Client, message: Message):
    mode = await instadb.get_settings()
    
    if mode == "off":
        return
        
    is_pm = message.chat.type == enums.ChatType.PRIVATE
    
    if mode == "group" and is_pm:
        return await message.reply_text("⚠️ **Instagram downloading is currently restricted to Groups only.**")
    elif mode == "pm" and not is_pm:
        return await message.reply_text("⚠️ **Instagram downloading is currently restricted to PMs only.**")

    # Extract URL (Support both `/insta link` and pure regex link)
    url = InstaDownloader.extract_url(message.text)
    if not url and len(message.command) > 1:
        url = InstaDownloader.extract_url(message.command[1])
        
    if not url: 
        if message.text.startswith("/insta"):
            return await message.reply_text("⚠️ **Please provide a valid Instagram link.**\nExample: `/insta https://instagram.com/reel/...`")
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
            
            with concurrent.futures.ThreadPoolExecutor() as pool:
                result = await asyncio.get_event_loop().run_in_executor(
                    pool, InstaDownloader.download_media, url, task_dir
                )
                
            if not result or not result.get("success"):
                await instadb.inc_failed()
                return await status_msg.edit_text(f"❌ Failed: {result.get('error', 'Unknown error')}")
                
            await instadb.inc_success(user_id, name, username, url)
                
            # Multiple Photos (Carousel)
            if result.get("is_multiple"):
                await status_msg.edit_text("📤 Uploading Photos...")
                for path in result["file_paths"]:
                    if os.path.exists(path):
                        await message.reply_photo(photo=path, quote=True)
                        await asyncio.sleep(0.5)
                        
            # Single Video
            elif result.get("is_video"):
                await status_msg.edit_text("📤 Uploading Video...")
                await message.reply_video(
                    video=result["file_path"],
                    supports_streaming=True,
                    quote=True
                )
                
            # Single Photo
            else:
                await status_msg.edit_text("📤 Uploading Photo...")
                await message.reply_photo(photo=result["file_path"], quote=True)

            await status_msg.delete()
            
        except Exception as e:
            await instadb.inc_failed()
            await status_msg.edit_text(f"❌ Error occurred: {str(e)[:50]}")
        finally:
            if os.path.exists(task_dir):
                shutil.rmtree(task_dir, ignore_errors=True)
