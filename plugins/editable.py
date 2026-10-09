import asyncio
import re
import requests
from logging import ERROR, getLogger

from motor.motor_asyncio import AsyncIOMotorClient
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

import info

logger = getLogger(__name__)
logger.setLevel(ERROR)

# ============================================================
# ⚙️ MONGODB SETUP
# ============================================================
_ui_settings = None

def get_db():
    global _ui_settings
    if _ui_settings is None:
        client = AsyncIOMotorClient(info.DATABASE_URI)
        _ui_settings = client[info.DATABASE_NAME]["ui_config"]
    return _ui_settings

async def get_ui():
    doc = await get_db().find_one({"_id": "bot_ui"})
    return doc or {}

async def update_ui(key, value):
    await get_db().update_one({"_id": "bot_ui"}, {"$set": {key: value}}, upsert=True)

# ============================================================
# 👑 FOOLPROOF ADMIN CHECKER
# ============================================================
def get_admin_list():
    raw_admins = getattr(info, "ADMINS", [])
    if isinstance(raw_admins, str): return [int(x) for x in raw_admins.replace(",", " ").split() if x.strip().lstrip("-").isdigit()]
    elif isinstance(raw_admins, int): return [raw_admins]
    elif isinstance(raw_admins, list): return [int(x) for x in raw_admins if str(x).strip().lstrip("-").isdigit()]
    return []

async def admin_check(_, __, msg):
    if not msg.from_user: return False
    return msg.from_user.id in get_admin_list()

admin_filter = filters.create(admin_check)

# ============================================================
# ⚡ 10-LAYER TITANIUM UPLOAD ENGINE (ZERO-FAIL)
# ============================================================
def _upload_sync(file_bytes):
    headers = {"User-Agent": "Mozilla/5.0"}
    
    try: res = requests.post("https://catbox.moe/user/api.php", data={"reqtype": "fileupload"}, files={"fileToUpload": ("img.jpg", file_bytes, "image/jpeg")}, timeout=6)
    except: res = None
    if res and res.status_code == 200 and res.text.startswith("http"): return res.text.strip()
    
    try: res = requests.post("https://graph.org/upload", files={"file": ("img.jpg", file_bytes, "image/jpeg")}, timeout=6)
    except: res = None
    if res and res.status_code == 200: return "https://graph.org" + res.json()[0]["src"]
        
    try: res = requests.post("https://envs.sh", files={"file": ("img.jpg", file_bytes, "image/jpeg")}, headers=headers, timeout=6)
    except: res = None
    if res and res.status_code == 200 and res.text.startswith("http"): return res.text.strip()
        
    try: res = requests.post("https://x0.at", files={"file": ("img.jpg", file_bytes, "image/jpeg")}, headers=headers, timeout=6)
    except: res = None
    if res and res.status_code == 200 and res.text.startswith("http"): return res.text.strip()
        
    try: res = requests.post("https://ttm.sh", files={"file": ("img.jpg", file_bytes, "image/jpeg")}, headers=headers, timeout=6)
    except: res = None
    if res and res.status_code == 200 and res.text.startswith("http"): return res.text.strip()
        
    try: res = requests.post("https://0x0.st", files={"file": ("img.jpg", file_bytes, "image/jpeg")}, headers=headers, timeout=6)
    except: res = None
    if res and res.status_code == 200 and res.text.startswith("http"): return res.text.strip()
        
    try: res = requests.post("https://pixeldrain.com/api/file", files={"file": ("img.jpg", file_bytes, "image/jpeg")}, headers=headers, timeout=6)
    except: res = None
    if res and res.status_code in [200, 201] and res.json().get("success"): return "https://pixeldrain.com/api/file/" + res.json()["id"]
        
    try: res = requests.post("https://file.io", files={"file": ("img.jpg", file_bytes, "image/jpeg")}, headers=headers, timeout=6)
    except: res = None
    if res and res.status_code == 200 and res.json().get("success"): return res.json()["link"]
        
    try: res = requests.post("https://telegra.ph/upload", files={"file": ("img.jpg", file_bytes, "image/jpeg")}, timeout=6)
    except: res = None
    if res and res.status_code == 200: return "https://telegra.ph" + res.json()[0]["src"]

    return None

async def upload_image_safely(client: Client, message: Message):
    try:
        file_io = await client.download_media(message, in_memory=True)
        if not file_io: return None, "❌ Failed to download the image."
        url = await asyncio.to_thread(_upload_sync, file_io.getvalue())
        if not url: return None, "❌ All 10 cloud uploaders failed."
        return url, None
    except Exception as e: return None, f"❌ Internal Error: {e}"

# ============================================================
# 🛠️ BUTTON PARSER HELPERS
# ============================================================
def parse_button_cmd(text):
    try:
        if "|" in text:
            parts = text.split(None, 1)[1].split("|", 1)
            return parts[0].strip(), parts[1].strip()
        match = re.search(r'["“]([^"”]+)["”]\s+(https?://\S+)', text)
        if match: return match.group(1).strip(), match.group(2).strip()
    except Exception: pass
    return None, None

def format_btn_list(btns):
    if not btns: return "No custom buttons."
    res = ""
    for i, b in enumerate(btns, 1):
        res += f"**{i}.** `{b['text']}` | Layout: `{b['layout']}` | Color: `{b['color']}`\n"
    return res

async def process_image_upload(client: Client, message: Message, db_key: str, menu_name: str):
    if not message.reply_to_message or not message.reply_to_message.photo:
        return await message.reply_text(f"⚠️ **Usage:** Reply to a photo with the command.")
    
    status = await message.reply_text("⏳ **Uploading to Cloud (Testing 10 Hosters)...**")
    url, err = await upload_image_safely(client, message.reply_to_message)
    
    if url:
        await update_ui(db_key, url)
        await status.edit_text(f"✅ **{menu_name} Image updated!**\n*(Saved permanently to cloud)*")
    else:
        file_id = message.reply_to_message.photo.file_id
        await update_ui(db_key, file_id)
        await status.edit_text(f"⚠️ Cloud blocked. **{menu_name} Image updated!**\n*(Saved as Telegram File_ID)*")

# ============================================================
# 🏠 START MENU CUSTOMIZATION
# ============================================================
@Client.on_message(filters.command("setstarttext") & admin_filter)
async def set_start_text(client, message):
    if len(message.command) < 2: return await message.reply_text("⚠️ **Usage:** `/setstarttext <text>`")
    await update_ui("start_text", message.text.split(None, 1)[1])
    await message.reply_text("✅ **Start Menu Text updated!**")

@Client.on_message(filters.command("defaultstarttext") & admin_filter)
async def def_start_text(client, message):
    await update_ui("start_text", None)
    await message.reply_text("✅ **Start Menu Text reset to default.**")

@Client.on_message(filters.command("setstartimage") & admin_filter)
async def set_start_img(client, message):
    await process_image_upload(client, message, "start_img", "Start Menu")

@Client.on_message(filters.command("remstartimage") & admin_filter)
async def rem_start_img(client, message):
    await update_ui("start_img", None)
    await message.reply_text("🗑️ **Start Menu Image removed.**")

@Client.on_message(filters.command("addstartbutton") & admin_filter)
async def add_start_btn(client, message):
    btn_text, url = parse_button_cmd(message.text)
    if not btn_text: return await message.reply_text('⚠️ **Usage:** `/addstartbutton Text | https://link.com`')
    ui = await get_ui()
    btns = ui.get("start_buttons", [])
    btns.append({"text": btn_text, "url": url, "layout": "belowside", "color": "blue"})
    await update_ui("start_buttons", btns)
    await message.reply_text(f"✅ **Start Button Added!**\n\nCurrent Buttons:\n{format_btn_list(btns)}")

@Client.on_message(filters.command("editstartbuttons") & admin_filter)
async def edit_start_btn(client, message):
    try:
        parts = message.text.split()[1:]
        if len(parts) < 3: raise ValueError
        idx, layout, color = int(parts[0]) - 1, parts[1].lower(), parts[2].lower()
        if layout not in ["sidebyside", "belowside"]: return await message.reply_text("⚠️ Layout must be `sidebyside` or `belowside`")
        if color not in ["green", "red", "blue", "gray"]: return await message.reply_text("⚠️ Color must be `green`, `red`, `blue`, or `gray`")

        ui = await get_ui()
        btns = ui.get("start_buttons", [])
        btns[idx]["layout"] = layout
        btns[idx]["color"] = color
        await update_ui("start_buttons", btns)
        await message.reply_text(f"✅ **Start Button #{idx+1} Edited!**\n\n{format_btn_list(btns)}")
    except (IndexError, ValueError):
        await message.reply_text("⚠️ **Usage:** `/editstartbuttons <number> <sidebyside/belowside> <color>`\n*Example:* `/editstartbuttons 1 sidebyside green`")

@Client.on_message(filters.command("remstartbutton") & admin_filter)
async def rem_start_btn(client, message):
    await update_ui("start_buttons", [])
    await message.reply_text("🗑️ **All custom Start Menu buttons cleared.**")

# ============================================================
# ℹ️ HELP MENU CUSTOMIZATION
# ============================================================
@Client.on_message(filters.command("sethelptext") & admin_filter)
async def set_help_text(client, message):
    if len(message.command) < 2: return await message.reply_text("⚠️ **Usage:** `/sethelptext <text>`")
    await update_ui("help_text", message.text.split(None, 1)[1])
    await message.reply_text("✅ **Help Menu Text updated!**")

@Client.on_message(filters.command("defaulthelptext") & admin_filter)
async def def_help_text(client, message):
    await update_ui("help_text", None)
    await message.reply_text("✅ **Help Menu Text reset to default.**")

@Client.on_message(filters.command("sethelpimage") & admin_filter)
async def set_help_img(client, message):
    await process_image_upload(client, message, "help_img", "Help Menu")

@Client.on_message(filters.command("remhelpimage") & admin_filter)
async def rem_help_img(client, message):
    await update_ui("help_img", None)
    await message.reply_text("🗑️ **Help Menu Image removed.**")

@Client.on_message(filters.command("addhelpbutton") & admin_filter)
async def add_help_btn(client, message):
    btn_text, url = parse_button_cmd(message.text)
    if not btn_text: return await message.reply_text('⚠️ **Usage:** `/addhelpbutton Text | https://link.com`')
    ui = await get_ui()
    btns = ui.get("help_buttons", [])
    btns.append({"text": btn_text, "url": url, "layout": "belowside", "color": "blue"})
    await update_ui("help_buttons", btns)
    await message.reply_text(f"✅ **Help Button Added!**\n\nCurrent Buttons:\n{format_btn_list(btns)}")

@Client.on_message(filters.command("edithelpbuttons") & admin_filter)
async def edit_help_btn(client, message):
    try:
        parts = message.text.split()[1:]
        idx, layout, color = int(parts[0]) - 1, parts[1].lower(), parts[2].lower()
        if layout not in ["sidebyside", "belowside"]: return await message.reply_text("⚠️ Layout must be `sidebyside` or `belowside`")
        if color not in ["green", "red", "blue", "gray"]: return await message.reply_text("⚠️ Color must be `green`, `red`, `blue`, or `gray`")
        ui = await get_ui()
        btns = ui.get("help_buttons", [])
        btns[idx]["layout"] = layout
        btns[idx]["color"] = color
        await update_ui("help_buttons", btns)
        await message.reply_text(f"✅ **Help Button #{idx+1} Edited!**\n\n{format_btn_list(btns)}")
    except (IndexError, ValueError): await message.reply_text("⚠️ **Usage:** `/edithelpbuttons <number> <sidebyside/belowside> <color>`")

@Client.on_message(filters.command("remhelpbutton") & admin_filter)
async def rem_help_btn(client, message):
    await update_ui("help_buttons", [])
    await message.reply_text("🗑️ **All custom Help Menu buttons cleared.**")

# ============================================================
# 📖 ABOUT MENU CUSTOMIZATION
# ============================================================
@Client.on_message(filters.command("setabouttext") & admin_filter)
async def set_about_text(client, message):
    if len(message.command) < 2: return await message.reply_text("⚠️ **Usage:** `/setabouttext <text>`")
    await update_ui("about_text", message.text.split(None, 1)[1])
    await message.reply_text("✅ **About Menu Text updated!**")

@Client.on_message(filters.command("defaultabouttext") & admin_filter)
async def def_about_text(client, message):
    await update_ui("about_text", None)
    await message.reply_text("✅ **About Menu Text reset to default.**")

@Client.on_message(filters.command("setaboutimage") & admin_filter)
async def set_about_img(client, message):
    await process_image_upload(client, message, "about_img", "About Menu")

@Client.on_message(filters.command("remaboutimage") & admin_filter)
async def rem_about_img(client, message):
    await update_ui("about_img", None)
    await message.reply_text("🗑️ **About Menu Image removed.**")

@Client.on_message(filters.command("addaboutbutton") & admin_filter)
async def add_about_btn(client, message):
    btn_text, url = parse_button_cmd(message.text)
    if not btn_text: return await message.reply_text('⚠️ **Usage:** `/addaboutbutton Text | https://link.com`')
    ui = await get_ui()
    btns = ui.get("about_buttons", [])
    btns.append({"text": btn_text, "url": url, "layout": "belowside", "color": "blue"})
    await update_ui("about_buttons", btns)
    await message.reply_text(f"✅ **About Button Added!**\n\nCurrent Buttons:\n{format_btn_list(btns)}")

@Client.on_message(filters.command("editaboutbuttons") & admin_filter)
async def edit_about_btn(client, message):
    try:
        parts = message.text.split()[1:]
        idx, layout, color = int(parts[0]) - 1, parts[1].lower(), parts[2].lower()
        if layout not in ["sidebyside", "belowside"]: return await message.reply_text("⚠️ Layout must be `sidebyside` or `belowside`")
        if color not in ["green", "red", "blue", "gray"]: return await message.reply_text("⚠️ Color must be `green`, `red`, `blue`, or `gray`")
        ui = await get_ui()
        btns = ui.get("about_buttons", [])
        btns[idx]["layout"] = layout
        btns[idx]["color"] = color
        await update_ui("about_buttons", btns)
        await message.reply_text(f"✅ **About Button #{idx+1} Edited!**\n\n{format_btn_list(btns)}")
    except (IndexError, ValueError): await message.reply_text("⚠️ **Usage:** `/editaboutbuttons <number> <sidebyside/belowside> <color>`")

@Client.on_message(filters.command("remaboutbutton") & admin_filter)
async def rem_about_btn(client, message):
    await update_ui("about_buttons", [])
    await message.reply_text("🗑️ **All custom About Menu buttons cleared.**")


# ============================================================
# 🎯 LIVE UI PREVIEW ENGINE
# ============================================================
@Client.on_message(filters.command(["preview_ui", "preview"]) & admin_filter)
async def preview_ui_cmd(client: Client, message: Message):
    if len(message.command) < 2 or message.command[1].lower() not in ["start", "help", "about"]:
        return await message.reply_text(
            "⚠️ **Usage:**\n`/preview_ui start`\n`/preview_ui help`\n`/preview_ui about`"
        )
    
    menu = message.command[1].lower()
    ui = await get_ui()
    
    # Fetch Data
    text = ui.get(f"{menu}_text", f"*(Default {menu.title()} Text Not Set)*\n\nPlease set it using `/set{menu}text`.")
    img = ui.get(f"{menu}_img")
    btns_data = ui.get(f"{menu}_buttons", [])
    
    # Process Mentions
    mention = message.from_user.mention if message.from_user else "Admin"
    text = text.replace("{mention}", mention)
    
    # Process Buttons & Layout (Side-by-Side vs Below)
    keyboard = []
    for b in btns_data:
        btn_obj = InlineKeyboardButton(b["text"], url=b["url"])
        if b.get("layout") == "sidebyside" and keyboard and len(keyboard[-1]) < 2:
            keyboard[-1].append(btn_obj)
        else:
            keyboard.append([btn_obj])
            
    reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
    
    try:
        if img:
            await message.reply_photo(photo=img, caption=text, reply_markup=reply_markup)
        else:
            await message.reply_text(text=text, reply_markup=reply_markup, disable_web_page_preview=True)
    except Exception as e:
        await message.reply_text(f"❌ **Preview Render Error:**\n`{e}`\n\n*(Check if your image URL or File ID is broken)*")
