import asyncio
import os
import random
import re
import traceback

import aiohttp
import bs4
from pyrogram import Client, filters

# Ensure DUMP_GROUP is handled gracefully if missing from info.py
try:
    from info import LOG_CHANNEL as DUMP_GROUP
except ImportError:
    DUMP_GROUP = None

async def fetch_media_urls(link: str) -> list:
    """Helper function to fetch direct media URLs using multiple fallback APIs."""
    urls = []

    # Attempt 1: Cobalt API (Currently the most reliable and fastest for TG Bots)
    try:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
        }
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.post("https://api.cobalt.tools/api/json", json={"url": link}, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("status") in ["redirect", "stream", "success"]:
                        urls.append(data.get("url"))
                    elif data.get("status") == "picker":
                        # Extracts all items if the post is a carousel (multiple images/videos)
                        for item in data.get("picker", []):
                            urls.append(item.get("url"))
    except Exception:
        pass

    # Attempt 2: SaveIG API Fallback (Your original method, hardened)
    if not urls:
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                "Origin": "https://saveig.app",
                "Referer": "https://saveig.app/en",
                "X-Requested-With": "XMLHttpRequest",
            }
            async with aiohttp.ClientSession(headers=headers) as session:
                data = {"q": link, "t": "media", "lang": "en"}
                async with session.post("https://saveig.app/api/ajaxSearch", data=data, timeout=10) as resp:
                    if resp.status == 200:
                        res = await resp.json()
                        meta = re.findall(r'href="(https?://[^"]+)"', res.get("data", ""))
                        for m in meta:
                            if "instagram" in m or "dl.php" in m or "cdn" in m:
                                urls.append(m)
        except Exception:
            pass

    # Attempt 3: DDInstagram HTML Meta Tag Scraping
    if not urls:
        try:
            dd_link = link.replace("instagram.com", "ddinstagram.com")
            async with aiohttp.ClientSession() as session:
                async with session.get(dd_link, timeout=10) as resp:
                    html = await resp.text()
                    soup = bs4.BeautifulSoup(html, "html.parser")
                    meta_vid = soup.find("meta", attrs={"property": "og:video"})
                    if meta_vid and meta_vid.get("content"):
                        urls.append(meta_vid["content"])
        except Exception:
            pass

    # Return unique URLs while preserving the order
    return list(dict.fromkeys(urls))


@Client.on_message(filters.command("insta") & filters.private)
async def insta_command_handler(client, message):
    if len(message.command) < 2:
        return await message.reply_text(
            "⚠️ **Please provide an Instagram link!**\n\n**Usage:** `/insta <instagram_link>`"
        )

    link = message.command[1]

    # Strip query parameters (like ?igsh=...) for cleaner API processing
    clean_link = link.split("?")[0] if "?igsh=" in link else link

    if "instagram.com" not in clean_link:
        return await message.reply_text(
            "⚠️ **That doesn't look like a valid Instagram link!**\nPlease check the URL and try again."
        )

    # Send waiting sticker
    m = await message.reply_sticker(
        "CAACAgUAAxkBAAJwgmYsfgvGbfH7xYqlNzyFsMSOpPdXAAIGBwACc7LBVBHH8bMK6dZAHgQ"
    )

    caption = "𝐷𝑜𝑤𝑛𝑙𝑜𝑎𝑑 𝐵𝑦 👉 @sandalwood_kannada_moviesz"
    successful_messages = []

    try:
        urls = await fetch_media_urls(clean_link)

        if not urls:
            raise Exception("No media found. The account might be private or the APIs are down.")

        for url in urls:
            # Check whether media is a photo or a video to prevent Pyrogram crashing
            ext = ".mp4"
            if any(x in url.lower() for x in [".jpg", ".jpeg", ".webp", ".png"]):
                ext = ".jpg"
            
            filename = f"{random.randint(100000, 9999999)}{ext}"
            
            try:
                # 1. Download locally to avoid Telegram `WebpageCurlFailed` errors
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, timeout=20) as resp:
                        if resp.status == 200:
                            with open(filename, "wb") as f:
                                f.write(await resp.read())
                        else:
                            continue
                
                # 2. Upload file securely to Telegram
                if ext == ".jpg":
                    sent_msg = await message.reply_photo(photo=filename, caption=caption)
                else:
                    sent_msg = await message.reply_video(video=filename, caption=caption)
                
                successful_messages.append(sent_msg)

            except Exception as inner_e:
                print(f"Failed to send media part: {inner_e}")
            finally:
                # 3. Always clean up the temporary file
                if os.path.exists(filename):
                    os.remove(filename)
            
            # Anti-FloodWait spacing
            await asyncio.sleep(1.5) 

        if not successful_messages:
            raise Exception("Found media links but failed to download/upload them.")

    except Exception as e:
        if DUMP_GROUP:
            try:
                await client.send_message(
                    DUMP_GROUP,
                    f"**Instagram Error:** `{e}`\n**Link:** {link}\n\n```{traceback.format_exc()}```"
                )
            except Exception:
                pass
        
        await message.reply_text(
            "400: Sorry, Unable To Find It. Make Sure It's Publicly Available or try again later :)"
        )

    finally:
        # Delete waiting sticker safely
        try:
            await m.delete()
        except Exception:
            pass

        # Forward copies to the Dump Group
        if DUMP_GROUP and successful_messages:
            for msg in successful_messages:
                try:
                    await msg.copy(DUMP_GROUP)
                    await asyncio.sleep(1)
                except Exception:
                    pass

        # Send footer message
        await message.reply_text(
            "<a href='https://t.me/sandalwood_kannada_moviesz'>Sandalwood Kannada Movies</a>",
            disable_web_page_preview=True,
        )
