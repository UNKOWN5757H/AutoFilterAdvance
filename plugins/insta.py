import asyncio
import os
import random
import re
import traceback

import aiohttp
from pyrogram import Client, filters

try:
    import yt_dlp
except ImportError:
    yt_dlp = None

try:
    from info import LOG_CHANNEL as DUMP_GROUP
except ImportError:
    DUMP_GROUP = None


def ytdlp_downloader(link: str) -> list:
    if not yt_dlp:
        return []
    base_id = str(random.randint(1000000, 9999999))
    ydl_opts = {
        "outtmpl": f"{base_id}_%(autonumber)s.%(ext)s",
        "quiet": True,
        "no_warnings": True,
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15"
        },
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.extract_info(link, download=True)
    except Exception:
        pass
    return [f for f in os.listdir(".") if f.startswith(base_id)]


async def fetch_api_urls(link: str) -> list:
    urls = []
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.post(
                "https://api.cobalt.tools/api/json",
                json={"url": link, "aFormat": "mp4", "filenamePattern": "classic"},
                timeout=10,
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("status") in ["redirect", "stream", "success"]:
                        urls.append(data.get("url"))
                    elif data.get("status") == "picker":
                        urls.extend(
                            [item.get("url") for item in data.get("picker", [])]
                        )
    except Exception:
        pass

    if not urls:
        try:
            headers.update(
                {
                    "Origin": "https://saveig.app",
                    "Referer": "https://saveig.app/en",
                    "X-Requested-With": "XMLHttpRequest",
                }
            )
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.post(
                    "https://saveig.app/api/ajaxSearch",
                    data={"q": link, "t": "media", "lang": "en"},
                    timeout=10,
                ) as resp:
                    if resp.status == 200:
                        meta = re.findall(
                            r'href="(https?://[^"]+)"',
                            (await resp.json()).get("data", ""),
                        )
                        urls.extend(
                            [
                                m
                                for m in meta
                                if "instagram" in m or "dl.php" in m or "cdn" in m
                            ]
                        )
        except Exception:
            pass
    return list(dict.fromkeys(urls))


@Client.on_message(filters.command("insta") & filters.private)
async def insta_command_handler(client, message):
    if len(message.command) < 2:
        return await message.reply_text("⚠️ **Usage:** `/insta <link>`")
    link = message.command[1]
    if "instagram.com" not in link:
        return await message.reply_text("⚠️ **Invalid Instagram link!**")

    clean_link = link.split("?")[0] if "?igsh=" in link else link
    m = await message.reply_text("⏳ **Downloading media... Please wait.**")
    caption = "𝐷𝑜𝑤𝑛𝑙𝑜𝑎𝑑 𝐵𝑦 👉 @sandalwood_kannada_moviesz"
    successful_messages, local_files = [], []

    try:
        if yt_dlp:
            local_files = await asyncio.to_thread(ytdlp_downloader, clean_link)
        if not local_files:
            urls = await fetch_api_urls(clean_link)
            if not urls:
                raise Exception("All extraction methods failed.")
            for url in urls:
                ext = (
                    ".jpg"
                    if any(x in url.lower() for x in [".jpg", ".jpeg", ".webp", ".png"])
                    else ".mp4"
                )
                filename = f"{random.randint(100000, 9999999)}{ext}"
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(url, timeout=20) as resp:
                            if resp.status == 200:
                                with open(filename, "wb") as f:
                                    f.write(await resp.read())
                                local_files.append(filename)
                except Exception:
                    pass

        if not local_files:
            raise Exception("Failed to save media to disk.")

        for file in local_files:
            try:
                if file.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
                    sent_msg = await message.reply_photo(photo=file, caption=caption)
                else:
                    sent_msg = await message.reply_video(video=file, caption=caption)
                successful_messages.append(sent_msg)
            except Exception:
                pass
            await asyncio.sleep(1.5)

        if not successful_messages:
            raise Exception("Upload rejected by Telegram.")
    except Exception as e:
        if DUMP_GROUP:
            try:
                await client.send_message(
                    DUMP_GROUP,
                    f"**Insta Error:** `{e}`\n**Link:** {link}\n```{traceback.format_exc()}```",
                )
            except Exception:
                pass
        await message.reply_text(
            "❌ Sorry, Unable to Download. The post might be private."
        )
    finally:
        try:
            await m.delete()
        except Exception:
            pass
        for file in local_files:
            if os.path.exists(file):
                os.remove(file)
        if DUMP_GROUP and successful_messages:
            for msg in successful_messages:
                try:
                    await msg.copy(DUMP_GROUP)
                except Exception:
                    pass
        if successful_messages:
            await message.reply_text(
                "<a href='https://t.me/sandalwood_kannada_moviesz'>Sandalwood Kannada Movies</a>",
                disable_web_page_preview=True,
            )
