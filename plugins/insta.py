import asyncio
import concurrent.futures
import json
import os
import re
import shutil
import subprocess
import time
import urllib.parse
import uuid

import requests
import yt_dlp
from pyrogram import Client, filters
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
download_semaphore = asyncio.Semaphore(3)  # Max 3 parallel downloads


# ============================================================
# 📥 INSTAGRAM DOWNLOADER ENGINE
# ============================================================
class InstaDownloader:

    @staticmethod
    def extract_url(text):
        if not text:
            return None
        m = re.search(
            r"(https?://)?(www\.)?instagram\.com/(p|reel|tv)/([a-zA-Z0-9_\-]+)", text
        )
        if m:
            return f"https://www.instagram.com/{m.group(3)}/{m.group(4)}/"
        return None

    @staticmethod
    def get_shortcode(url):
        m = re.search(r"/(p|reel|tv)/([a-zA-Z0-9_\-]+)", url)
        return m.group(2) if m else None

    @staticmethod
    def download_media(url, task_dir):
        shortcode = InstaDownloader.get_shortcode(url)
        if not shortcode:
            return {"success": False, "error": "Invalid Link"}
        is_reel = "/reel/" in url or "/tv/" in url
        if is_reel:
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
            "socket_timeout": 60,
            "ignoreerrors": True,
            "http_headers": {
                "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)",
            },
        }

        if shutil.which("ffmpeg"):
            ydl_opts["ffmpeg_location"] = shutil.which("ffmpeg")

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
        except Exception:
            pass

        time.sleep(1)
        for f in os.listdir(task_dir):
            if f.endswith((".mp4", ".mkv", ".webm")):
                fp = os.path.join(task_dir, f)
                if os.path.getsize(fp) > 50000:
                    return {"success": True, "file_path": fp, "is_video": True}

        # Fallback format
        ydl_opts["format"] = "best[ext=mp4]/best"
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
        except Exception:
            pass

        time.sleep(1)
        for f in os.listdir(task_dir):
            if f.endswith((".mp4", ".mkv", ".webm")):
                fp = os.path.join(task_dir, f)
                if os.path.getsize(fp) > 50000:
                    return {"success": True, "file_path": fp, "is_video": True}

        return {"success": False, "error": "Server busy, unable to fetch video."}

    @staticmethod
    def _download_photo(shortcode, url, task_dir):
        # Fallback to multiple methods for scraping photos
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
                {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0)"}
            )
            resp = session.get(url, timeout=15)
            if resp.status_code != 200:
                return {"success": False}
            html = resp.text
            image_urls = []

            # Basic parsing logic for JSON data inside page
            nd = re.search(
                r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL
            )
            if nd:
                try:
                    data_str = json.dumps(json.loads(nd.group(1)))
                    carousel_matches = re.findall(
                        r'"edge_sidecar_to_children"[^}]*"edges":\s*\[(.*?)\]',
                        data_str,
                        re.DOTALL,
                    )
                    if carousel_matches:
                        for carousel in carousel_matches:
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

            image_urls = list(dict.fromkeys(image_urls))  # Unique

            if not image_urls:
                return {"success": False}

            downloaded = []
            for i, img_url in enumerate(image_urls[:10]):  # Cap at 10 images
                try:
                    fp = os.path.join(task_dir, f"multi_{shortcode}_{i}.jpg")
                    r = session.get(
                        img_url,
                        headers={"User-Agent": "Mozilla/5.0"},
                        stream=True,
                        timeout=30,
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
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.extract_info(url, download=True)
                time.sleep(0.5)
                for f in os.listdir(task_dir):
                    if shortcode in f and not f.endswith((".mp4", ".mov", ".webm")):
                        fp = os.path.join(task_dir, f)
                        if os.path.getsize(fp) > 1000:
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
                    r = session.get(img_url, stream=True, timeout=20)
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
                        timeout=20,
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

    @staticmethod
    def extract_audio(video_path, audio_name="Extracted_Audio"):
        try:
            ap = os.path.join(os.path.dirname(video_path), f"{audio_name}.mp3")
            if not shutil.which("ffmpeg"):
                return {"success": False, "error": "FFmpeg not installed"}
            subprocess.run(
                [
                    "ffmpeg",
                    "-i",
                    video_path,
                    "-vn",
                    "-acodec",
                    "libmp3lame",
                    "-ab",
                    "192k",
                    "-y",
                    ap,
                ],
                capture_output=True,
                timeout=300,
            )
            if os.path.exists(ap) and os.path.getsize(ap) > 1000:
                return {"success": True, "file_path": ap}
            return {"success": False, "error": "Audio extraction failed"}
        except Exception as e:
            return {"success": False, "error": str(e)[:50]}


# ============================================================
# 🤖 PYROGRAM MESSAGE HANDLERS
# ============================================================
@Client.on_message(
    filters.regex(r"(https?://)?(www\.)?instagram\.com/(p|reel|tv)/([a-zA-Z0-9_\-]+)")
    & filters.incoming
)
async def handle_instagram_link(client: Client, message: Message):
    url = InstaDownloader.extract_url(message.text)
    if not url:
        return

    status_msg = await message.reply_text("⏳ Processing Link...", quote=True)
    task_id = str(uuid.uuid4())[:8]
    task_dir = os.path.join(DOWNLOAD_DIR, f"task_{task_id}")
    os.makedirs(task_dir, exist_ok=True)

    async with download_semaphore:
        try:
            await status_msg.edit_text("📥 Downloading Media...")

            # Run blocking download in a separate thread so it doesn't freeze the bot
            with concurrent.futures.ThreadPoolExecutor() as pool:
                result = await asyncio.get_event_loop().run_in_executor(
                    pool, InstaDownloader.download_media, url, task_dir
                )

            if not result or not result.get("success"):
                return await status_msg.edit_text(
                    f"❌ Failed: {result.get('error', 'Unknown error')}"
                )

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
                shortcode = InstaDownloader.get_shortcode(url)
                kb = InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                "🎵 Extract Audio", callback_data=f"igaud_{shortcode}"
                            )
                        ]
                    ]
                )

                await message.reply_video(
                    video=result["file_path"],
                    reply_markup=kb,
                    supports_streaming=True,
                    quote=True,
                )

            # Single Photo
            else:
                await status_msg.edit_text("📤 Uploading Photo...")
                await message.reply_photo(photo=result["file_path"], quote=True)

            await status_msg.delete()

        except Exception as e:
            await status_msg.edit_text(f"❌ Error occurred: {str(e)[:50]}")
        finally:
            # Clean up task directory
            if os.path.exists(task_dir):
                shutil.rmtree(task_dir, ignore_errors=True)


@Client.on_callback_query(filters.regex(r"^igaud_(.*)"))
async def extract_audio_callback(client: Client, query: CallbackQuery):
    shortcode = query.matches[0].group(1)
    url = f"https://www.instagram.com/reel/{shortcode}/"

    await query.answer("Extracting Audio... Please wait.", show_alert=False)
    status_msg = await query.message.reply_text(
        "🎧 Downloading & Extracting Audio...", quote=True
    )

    task_id = str(uuid.uuid4())[:8]
    task_dir = os.path.join(DOWNLOAD_DIR, f"audio_{task_id}")
    os.makedirs(task_dir, exist_ok=True)

    async with download_semaphore:
        try:
            with concurrent.futures.ThreadPoolExecutor() as pool:
                result = await asyncio.get_event_loop().run_in_executor(
                    pool, InstaDownloader.download_media, url, task_dir
                )

            if not result or not result.get("success"):
                return await status_msg.edit_text(
                    "❌ Failed to fetch video for audio extraction."
                )

            vp = result["file_path"]

            # Extract Audio from downloaded video
            with concurrent.futures.ThreadPoolExecutor() as pool:
                ar = await asyncio.get_event_loop().run_in_executor(
                    pool, InstaDownloader.extract_audio, vp, f"Audio_{shortcode}"
                )

            if ar.get("success"):
                await status_msg.edit_text("📤 Uploading Audio...")
                await query.message.reply_audio(
                    audio=ar["file_path"],
                    title=f"Audio Extract - {shortcode}",
                    performer="Insta Downloader",
                    quote=True,
                )
                await status_msg.delete()
            else:
                await status_msg.edit_text(
                    f"❌ Audio Extraction Failed: {ar.get('error')}"
                )

        except Exception as e:
            await status_msg.edit_text(f"❌ Error occurred: {str(e)[:50]}")
        finally:
            if os.path.exists(task_dir):
                shutil.rmtree(task_dir, ignore_errors=True)
