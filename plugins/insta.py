import os
import re
import random
import asyncio
import traceback
import aiohttp
import bs4
from pyrogram import filters, Client

# Make sure you have DUMP_GROUP defined in your info.py
from info import LOG_CHANNEL as DUMP_GROUP

# Headers for the fallback API scraper
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:105.0) Gecko/20100101 Firefox/105.0",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.5",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "X-Requested-With": "XMLHttpRequest",
    "Origin": "https://saveig.app",
    "Connection": "keep-alive",
    "Referer": "https://saveig.app/en",
}

@Client.on_message(filters.command("insta") & filters.private)
async def insta_command_handler(client, message):
    # Check if the user actually provided a link after the command
    if len(message.command) < 2:
        await message.reply_text("⚠️ **Please provide an Instagram link!**\n\n**Usage:** `/insta <instagram_link>`")
        return
        
    link = message.command[1]
    
    # Basic validation to ensure it's an Instagram link
    if "instagram.com" not in link:
        await message.reply_text("⚠️ **That doesn't look like a valid Instagram link!**\nPlease check the URL and try again.")
        return
    
    # Send waiting sticker
    m = await message.reply_sticker("CAACAgUAAxkBAAJwgmYsfgvGbfH7xYqlNzyFsMSOpPdXAAIGBwACc7LBVBHH8bMK6dZAHgQ")
    
    # Clean and convert the URL for ddinstagram
    url = link.replace("instagram.com", "ddinstagram.com")
    url = url.replace("==", "%3D%3D")
    if url.endswith("="):
        url = url[:-1]

    dump_file = None
    downfile = None

    try:
        # Attempt 1: Direct Telegram URL Fetch (Fastest)
        dump_file = await message.reply_video(url, caption="𝐷𝑜𝑤𝑛𝑙𝑜𝑎𝑑 𝐵𝑦 👉 [@sandalwood_kannada_moviesz]")
        
    except Exception as e:
        # Attempt 2: Fallback to Scraping via aiohttp if direct link fails
        try:
            async with aiohttp.ClientSession(headers=HEADERS) as session:
                
                # Check if it's a Reel
                if "/reel/" in url:
                    # Fetching the meta tag from ddinstagram
                    async with session.get(url) as resp:
                        getdata = await resp.text()
                        soup = bs4.BeautifulSoup(getdata, 'html.parser')
                        meta_tag = soup.find('meta', attrs={'property': 'og:video'})
                        
                    content_value = None
                    if meta_tag and meta_tag.get('content'):
                        content_value = f"https://ddinstagram.com{meta_tag['content']}"
                    else:
                        # Fallback to SaveIG API
                        async with session.post("https://saveig.app/api/ajaxSearch", data={"q": link, "t": "media", "lang": "en"}) as saveig_resp:
                            if saveig_resp.status == 200:
                                res = await saveig_resp.json()
                                meta = re.findall(r'href="(https?://[^"]+)"', res.get('data', ''))
                                if meta:
                                    content_value = meta[0]
                            else:
                                return await message.reply("Oops, something went wrong with the scraper API.")
                    
                    if not content_value:
                        raise Exception("Could not find media content.")

                    # Try sending the URL directly again
                    try:
                        dump_file = await message.reply_video(content_value, caption="𝐷𝑜𝑤𝑛𝑙𝑜𝑎𝑑 𝐵𝑦 👉 @sandalwood_kannada_moviesz")
                    except Exception:
                        # If URL sending fails, download it locally and send
                        downfile = f"{os.getcwd()}/{random.randint(1, 10000000)}.mp4"
                        async with session.get(content_value) as media_resp:
                            with open(downfile, 'wb') as f:
                                f.write(await media_resp.read())
                        dump_file = await message.reply_video(downfile, caption="𝐷𝑜𝑤𝑛𝑙𝑜𝑎𝑑 𝐵𝑦 👉 @sandalwood_kannada_moviesz")

                # Check if it's a Post or Story
                elif "/p/" in url or "stories" in url:
                    async with session.post("https://saveig.app/api/ajaxSearch", data={"q": link, "t": "media", "lang": "en"}) as saveig_resp:
                        if saveig_resp.status == 200:
                            res = await saveig_resp.json()
                            meta = re.findall(r'href="(https?://[^"]+)"', res.get('data', ''))
                        else:
                            return await message.reply("Oops, something went wrong.")

                    if not meta:
                        raise Exception("No media found.")

                    # Send all media found in the post/story
                    for media_url in meta:
                        try:
                            dump_file = await message.reply_video(media_url, caption="𝐷𝑜𝑤𝑛𝑙𝑜𝑎𝑑 𝐵𝑦 👉 @sandalwood_kannada_moviesz")
                            await asyncio.sleep(1) # Prevent FloodWaits
                        except Exception:
                            pass 

        except KeyError:
            await message.reply("400: Sorry, Unable To Find It. Make Sure It's Publicly Available :)")
            
        except Exception as inner_e:
            if DUMP_GROUP:
                await client.send_message(DUMP_GROUP, f"**Instagram Error:** `{inner_e}`\n**Link:** {link}\n\n```{traceback.format_exc()}```")
            await message.reply("400: Sorry, Unable To Find It. Try another or report it to @SandalwoodSupportBot")

    finally:
        # 1. Forward/Copy to Dump Group
        if dump_file and DUMP_GROUP:
            try:
                await dump_file.copy(DUMP_GROUP)
            except Exception:
                pass
        
        # 2. Delete the waiting sticker safely
        try:
            await m.delete()
        except Exception:
            pass
        
        # 3. Clean up the downloaded local file if it exists
        if downfile and os.path.exists(downfile):
            try:
                os.remove(downfile)
            except Exception:
                pass
        
        # 4. Send the footer message
        await message.reply("<a href='https://t.me/sandalwood_kannada_moviesz'>Sandalwood Kannada Movies</a>", disable_web_page_preview=True)
