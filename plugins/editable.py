import re
from logging import ERROR, getLogger

from motor.motor_asyncio import AsyncIOMotorClient
from pyrogram import Client, filters
from pyrogram.types import Message

import info
from Script import script

logger = getLogger(__name__)
logger.setLevel(ERROR)

# ⚡ Safely alias DB to prevent Pyrogram scanner crash
_DB_CLIENT = AsyncIOMotorClient(info.DATABASE_URI)
_BOT_DB = _DB_CLIENT[info.DATABASE_NAME]
_ui_settings = _BOT_DB["ui_config"]

# ==========================================
# 🗄️ DATABASE HELPERS
# ==========================================
async def get_ui():
    doc = await _ui_settings.find_one({"_id": "bot_ui"})
    return doc or {}

async def update_ui(key, value):
    await _ui_settings.update_one({"_id": "bot_ui"}, {"$set": {key: value}}, upsert=True)

admin_filter = filters.create(lambda _, __, msg: msg.from_user and msg.from_user.id in info.ADMINS)

def parse_button_cmd(text):
    match = re.search(r'"([^"]+)"\s+(https?://\S+)', text)
    if match: return match.group(1), match.group(2)
    return None, None

def format_btn_list(btns):
    if not btns: return "No custom buttons."
    res = ""
    for i, b in enumerate(btns, 1):
        res += f"**{i}.** `{b['text']}` | Layout: `{b['layout']}` | Color: `{b['color']}`\n"
    return res

# ==========================================
# 🏠 START MENU CUSTOMIZATION
# ==========================================
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
    if not message.reply_to_message or not message.reply_to_message.photo:
        return await message.reply_text("⚠️ **Usage:** Reply to a photo with `/setstartimage`")
    await update_ui("start_img", message.reply_to_message.photo.file_id)
    await message.reply_text("✅ **Start Menu Image updated!**")

@Client.on_message(filters.command("remstartimage") & admin_filter)
async def rem_start_img(client, message):
    await update_ui("start_img", None)
    await message.reply_text("🗑️ **Start Menu Image removed.**")

@Client.on_message(filters.command("addstartbutton") & admin_filter)
async def add_start_btn(client, message):
    btn_text, url = parse_button_cmd(message.text)
    if not btn_text: return await message.reply_text("⚠️ **Usage:** `/addstartbutton \"Button Text\" https://link.com`")
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

# ==========================================
# ℹ️ HELP MENU CUSTOMIZATION
# ==========================================
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
    if not message.reply_to_message or not message.reply_to_message.photo:
        return await message.reply_text("⚠️ **Usage:** Reply to a photo with `/sethelpimage`")
    await update_ui("help_img", message.reply_to_message.photo.file_id)
    await message.reply_text("✅ **Help Menu Image updated!**")

@Client.on_message(filters.command("remhelpimage") & admin_filter)
async def rem_help_img(client, message):
    await update_ui("help_img", None)
    await message.reply_text("🗑️ **Help Menu Image removed.**")

@Client.on_message(filters.command("addhelpbutton") & admin_filter)
async def add_help_btn(client, message):
    btn_text, url = parse_button_cmd(message.text)
    if not btn_text: return await message.reply_text("⚠️ **Usage:** `/addhelpbutton \"Button Text\" https://link.com`")
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
    except (IndexError, ValueError):
        await message.reply_text("⚠️ **Usage:** `/edithelpbuttons <number> <sidebyside/belowside> <color>`")

@Client.on_message(filters.command("remhelpbutton") & admin_filter)
async def rem_help_btn(client, message):
    await update_ui("help_buttons", [])
    await message.reply_text("🗑️ **All custom Help Menu buttons cleared.**")

# ==========================================
# 📖 ABOUT MENU CUSTOMIZATION
# ==========================================
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
    if not message.reply_to_message or not message.reply_to_message.photo:
        return await message.reply_text("⚠️ **Usage:** Reply to a photo with `/setaboutimage`")
    await update_ui("about_img", message.reply_to_message.photo.file_id)
    await message.reply_text("✅ **About Menu Image updated!**")

@Client.on_message(filters.command("remaboutimage") & admin_filter)
async def rem_about_img(client, message):
    await update_ui("about_img", None)
    await message.reply_text("🗑️ **About Menu Image removed.**")

@Client.on_message(filters.command("addaboutbutton") & admin_filter)
async def add_about_btn(client, message):
    btn_text, url = parse_button_cmd(message.text)
    if not btn_text: return await message.reply_text("⚠️ **Usage:** `/addaboutbutton \"Button Text\" https://link.com`")
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
    except (IndexError, ValueError):
        await message.reply_text("⚠️ **Usage:** `/editaboutbuttons <number> <sidebyside/belowside> <color>`")

@Client.on_message(filters.command("remaboutbutton") & admin_filter)
async def rem_about_btn(client, message):
    await update_ui("about_buttons", [])
    await message.reply_text("🗑️ **All custom About Menu buttons cleared.**")
