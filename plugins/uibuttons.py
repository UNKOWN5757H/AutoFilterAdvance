import inspect
from typing import Any, Dict, List, Optional

from pyrogram import Client
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import info

# ============================================================
# 🎨 SAFE TELEGRAM BUTTON STYLE DETECTION
# ============================================================
BTN_PRIMARY = None
BTN_SUCCESS = None
BTN_DANGER = None
_SUPPORTS_BTN_STYLE = False

try:
    from pyrogram.enums import ButtonStyle

    if "style" in inspect.signature(InlineKeyboardButton.__init__).parameters:
        BTN_PRIMARY = getattr(ButtonStyle, "PRIMARY", None)
        BTN_SUCCESS = getattr(ButtonStyle, "SUCCESS", None)
        BTN_DANGER = getattr(ButtonStyle, "DANGER", None)
        _SUPPORTS_BTN_STYLE = True
except (ImportError, ValueError, TypeError):
    BTN_PRIMARY = BTN_SUCCESS = BTN_DANGER = None
    _SUPPORTS_BTN_STYLE = False


def get_admin_list() -> List[int]:
    raw_admins = getattr(info, "ADMINS", [])
    if isinstance(raw_admins, (str, int)):
        raw_admins = str(raw_admins).replace(",", " ").split()
    elif isinstance(raw_admins, (list, tuple, set)):
        raw_admins = list(raw_admins)
    else:
        raw_admins = []
    return [int(x) for x in raw_admins if str(x).strip().lstrip("-").isdigit()]


async def is_global_admin(user_id: int) -> bool:
    if not user_id:
        return False
    return int(user_id) in get_admin_list()


def create_btn(
    text: str,
    url: Optional[str] = None,
    callback_data: Optional[str] = None,
    style: Any = None,
) -> InlineKeyboardButton:
    """Creates an InlineKeyboardButton safely. Pass style=None for no colour."""
    kwargs: Dict[str, Any] = {"text": str(text)}
    if url:
        kwargs["url"] = str(url).strip()
    elif callback_data:
        kwargs["callback_data"] = str(callback_data)[:64]

    if _SUPPORTS_BTN_STYLE and style is not None:
        kwargs["style"] = style

    try:
        return InlineKeyboardButton(**kwargs)
    except Exception:
        kwargs.pop("style", None)
        return InlineKeyboardButton(**kwargs)


# ============================================================
# 🔘 GENERAL KEYBOARD & BUTTON BUILDERS
# ============================================================
def get_close_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[create_btn("🔐 Close", callback_data="close_data")]])


def get_back_close_keyboard(back_cb: str = "help") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                create_btn("🔙 Back", callback_data=back_cb),
                create_btn("🔐 Close", callback_data="close_data"),
            ]
        ]
    )


def get_cancel_input_keyboard(back_cb: str = "help") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[create_btn("❌ Cancel", callback_data=f"hact#cancel_input#{back_cb}")]]
    )


def get_deleted_file_notify_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                create_btn(
                    "Movie Request 📝",
                    url="https://t.me/Sandalwood_Kannada_Group",
                    style=BTN_SUCCESS,
                )
            ]
        ]
    )


def get_default_file_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                create_btn(
                    text="🎥 ಕನ್ನಡ ಹೊಸ ಮೂವೀಗಳು 🎥",
                    url="https://t.me/sandalwood_kannada_moviesz",
                    style=BTN_SUCCESS,
                )
            ]
        ]
    )


def get_pm_autoreply_keyboard(
    btn_text: Optional[str],
    btn_url: Optional[str],
    btn_color_str: str = "red",
) -> Optional[InlineKeyboardMarkup]:
    if not btn_text or not btn_url:
        return None
    color_map = {
        "green": BTN_SUCCESS,
        "red": BTN_DANGER,
        "blue": BTN_PRIMARY,
        "normal": None,
    }
    return InlineKeyboardMarkup(
        [
            [
                create_btn(
                    btn_text,
                    url=btn_url,
                    style=color_map.get(str(btn_color_str).lower(), None),
                )
            ]
        ]
    )


def append_fsub_back_button(
    f_markup: Optional[InlineKeyboardMarkup],
) -> InlineKeyboardMarkup:
    rows = (
        list(f_markup.inline_keyboard)
        if f_markup and getattr(f_markup, "inline_keyboard", None)
        else []
    )
    rows.append(
        [
            create_btn("🔙 Back", callback_data="helps_forcesub"),
            create_btn("🔐 Close", callback_data="close_data"),
        ]
    )
    return InlineKeyboardMarkup(rows)


async def get_start_keyboard(client: Client, user_id: int) -> InlineKeyboardMarkup:
    buttons = [
        [
            create_btn(
                "✈️ Gʀᴏᴜᴘ 1",
                url="https://t.me/Sandalwood_Kannada_Group",
                style=BTN_PRIMARY,
            ),
            create_btn(
                "✈️ Gʀᴏᴜᴘ 2",
                url="https://t.me/Kannada_Filmy_Group",
                style=BTN_PRIMARY,
            ),
            create_btn(
                "✈️ Gʀᴏᴜᴘ 3",
                url="https://t.me/+GLsPkRgLGGszMzY1",
                style=BTN_PRIMARY,
            ),
        ]
    ]
    if await is_global_admin(user_id):
        buttons.append(
            [
                create_btn("ℹ️ 𝙷𝚎𝚕𝚙", callback_data="help"),
                create_btn("😊 𝙰𝚋𝚘𝚞𝚝", callback_data="about"),
            ]
        )
    buttons.append(
        [
            create_btn(
                "🔗 Nᴇᴡ Rᴇʟᴇᴀꜱᴇꜱ & Oᴛᴛ Uᴘᴅᴀᴛᴇꜱ",
                url="https://t.me/sandalwood_kannada_moviesz",
                style=BTN_SUCCESS,
            )
        ]
    )
    return InlineKeyboardMarkup(buttons)


async def get_help_keyboard() -> InlineKeyboardMarkup:
    """Main Help Menu Keyboard with all 20 categories and zero colours."""
    return InlineKeyboardMarkup(
        [
            [
                create_btn("🖥️ UI Start", callback_data="helps_uistart"),
                create_btn("🖥️ UI Help", callback_data="helps_uihelp"),
                create_btn("🖥️ UI About", callback_data="helps_uiabout"),
            ],
            [
                create_btn("👋 Welcome", callback_data="helps_welcome"),
                create_btn("🖼️ Images", callback_data="helps_images"),
            ],
            [
                create_btn("🔍 Spell Check", callback_data="helps_spell"),
                create_btn("📝 Filters", callback_data="helps_filters"),
            ],
            [
                create_btn("📱 Force Sub", callback_data="helps_forcesub"),
                create_btn("👥 Force Add", callback_data="helps_forceadd"),
            ],
            [
                create_btn("🚫 Bans", callback_data="helps_bans"),
                create_btn("🗑️ Delete", callback_data="helps_delete"),
            ],
            [
                create_btn("📢 Promotions", callback_data="helps_promotions"),
                create_btn("📚 Index", callback_data="helps_index"),
            ],
            [
                create_btn("⚙️ Settings", callback_data="helps_settings"),
                create_btn("🌐 Connections", callback_data="helps_connections"),
            ],
            [
                create_btn("📊 Utilities", callback_data="helps_utilities"),
                create_btn("💬 Custom Messages", callback_data="helps_custommessages"),
            ],
            [
                create_btn("📝 Post Handle", callback_data="helps_posthand"),
                create_btn("📝 Custom Captions", callback_data="helps_customcaption"),
            ],
            [
                create_btn("💬 PM Auto Reply", callback_data="helps_pmautoreply"),
                create_btn("🧹 Clean Filename", callback_data="helps_cleanfile"),
            ],
            [
                create_btn("💾 Backup", callback_data="helps_backup"),
            ],
            [
                create_btn("🔙 Back", callback_data="start"),
                create_btn("🔐 Close", callback_data="close_data"),
            ],
        ]
    )


async def get_about_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [create_btn("📊 Sᴛᴀᴛᴜs", callback_data="stats")],
            [
                create_btn("🏘 Hᴏᴍᴇ", callback_data="start"),
                create_btn("🔐 Cʟᴏsᴇ", callback_data="close_data"),
            ],
        ]
    )


def get_stats_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                create_btn("🔙 Back", callback_data="about"),
                create_btn("🔄 Refresh", callback_data="rfrsh"),
            ]
        ]
    )


def get_cleanwords_keyboard(use_default: bool = True) -> InlineKeyboardMarkup:
    mode_label = "defaultcleanfilename ✅" if use_default else "defaultcleanfilename"
    return InlineKeyboardMarkup(
        [
            [
                create_btn("➕ Add Words", callback_data="hact#cw_add"),
                create_btn("setcleanfilename", callback_data="hact#cw_set"),
            ],
            [
                create_btn(mode_label, callback_data="hact#cw_default"),
                create_btn("remcleanfilename", callback_data="hact#cw_clear"),
            ],
            [
                create_btn("🔙 Back", callback_data="help"),
                create_btn("🔐 Close", callback_data="close_data"),
            ],
        ]
    )


def get_help_section_keyboard(
    section_key: str, state: Optional[Dict[str, Any]] = None
) -> InlineKeyboardMarkup:
    """
    Builds the exact requested command & toggle buttons for every Help category.
    Strictly NO colours on any Help buttons.
    """
    st = state or {}
    rows: List[List[InlineKeyboardButton]] = []

    # 1. UI START MENU (helps_uistart)
    if section_key == "helps_uistart":
        rows.extend(
            [
                [
                    create_btn("setstarttext", callback_data="hact#cmd#setstarttext"),
                    create_btn(
                        "defaultstarttext", callback_data="hact#cmd#defaultstarttext"
                    ),
                    create_btn("setstartimage", callback_data="hact#cmd#setstartimage"),
                ],
                [
                    create_btn("remstartimage", callback_data="hact#cmd#remstartimage"),
                    create_btn(
                        "addstartbutton", callback_data="hact#cmd#addstartbutton"
                    ),
                ],
                [
                    create_btn(
                        "editstartbuttons", callback_data="hact#cmd#editstartbuttons"
                    ),
                    create_btn(
                        "remstartbutton", callback_data="hact#cmd#remstartbutton"
                    ),
                ],
            ]
        )

    # 2. UI HELP MENU (helps_uihelp)
    elif section_key == "helps_uihelp":
        rows.extend(
            [
                [
                    create_btn("sethelptext", callback_data="hact#cmd#sethelptext"),
                    create_btn(
                        "defaulthelptext", callback_data="hact#cmd#defaulthelptext"
                    ),
                    create_btn("sethelpimage", callback_data="hact#cmd#sethelpimage"),
                ],
                [
                    create_btn("remhelpimage", callback_data="hact#cmd#remhelpimage"),
                    create_btn("addhelpbutton", callback_data="hact#cmd#addhelpbutton"),
                ],
                [
                    create_btn(
                        "edithelpbuttons", callback_data="hact#cmd#edithelpbuttons"
                    ),
                    create_btn("remhelpbutton", callback_data="hact#cmd#remhelpbutton"),
                ],
            ]
        )

    # 3. UI ABOUT MENU (helps_uiabout)
    elif section_key == "helps_uiabout":
        rows.extend(
            [
                [
                    create_btn("setabouttext", callback_data="hact#cmd#setabouttext"),
                    create_btn(
                        "defaultabouttext", callback_data="hact#cmd#defaultabouttext"
                    ),
                    create_btn("setaboutimage", callback_data="hact#cmd#setaboutimage"),
                ],
                [
                    create_btn("remaboutimage", callback_data="hact#cmd#remaboutimage"),
                    create_btn(
                        "addaboutbutton", callback_data="hact#cmd#addaboutbutton"
                    ),
                ],
                [
                    create_btn(
                        "editaboutbuttons", callback_data="hact#cmd#editaboutbuttons"
                    ),
                    create_btn(
                        "remaboutbutton", callback_data="hact#cmd#remaboutbutton"
                    ),
                ],
            ]
        )

    # 4. WELCOME MENU (helps_welcome)
    elif section_key == "helps_welcome":
        welc_on = bool(st.get("welc_on", True))
        rows.extend(
            [
                [
                    create_btn(
                        f"On/Off: {'ON ✅' if welc_on else 'OFF ❌'}",
                        callback_data="hact#welc_toggle",
                    )
                ],
                [
                    create_btn("Set text", callback_data="hact#welc_settxt"),
                    create_btn("set image", callback_data="hact#cmd#setwelcomeimg"),
                ],
                [
                    create_btn("Set welcome", callback_data="hact#cmd#setwelcome"),
                    create_btn("del welcome", callback_data="hact#welc_del"),
                ],
            ]
        )

    # 5. IMAGES MENU (helps_images)
    elif section_key == "helps_images":
        rows.extend(
            [
                [
                    create_btn("setautoimg", callback_data="hact#cmd#setautoimg"),
                    create_btn("remautoimg", callback_data="hact#cmd#remautoimg"),
                ],
                [
                    create_btn(
                        "setfilenotfoundimg",
                        callback_data="hact#cmd#setfilenotfoundimg",
                    ),
                    create_btn(
                        "remfilenotfoundimg",
                        callback_data="hact#cmd#remfilenotfoundimg",
                    ),
                ],
                [
                    create_btn(
                        "defaultfilenotfoundimg",
                        callback_data="hact#cmd#defaultfilenotfoundimg",
                    ),
                    create_btn("setfsubimg", callback_data="hact#cmd#setfsubimg"),
                ],
            ]
        )

    # 6. SPELL CHECK & SMART SEARCH MENU (helps_spell)
    elif section_key == "helps_spell":
        at_on = bool(st.get("at_on", True))
        mc_on = bool(st.get("mc_on", True))
        spell_on = bool(st.get("spell_on", True))
        stops_count = int(st.get("stops_count", 0))

        rows.extend(
            [
                [
                    create_btn(
                        f"autotranslate: {'ON ✅' if at_on else 'OFF ❌'}",
                        callback_data="hact#at_toggle",
                    ),
                    create_btn(
                        f"multichoice: {'ON ✅' if mc_on else 'OFF ❌'}",
                        callback_data="hact#mc_toggle",
                    ),
                ],
                [
                    create_btn(
                        f"spellcheck: {'ON ✅' if spell_on else 'OFF ❌'}",
                        callback_data="hact#spell_toggle",
                    ),
                    create_btn(
                        f"stopwords ({stops_count})",
                        callback_data="hact#sw_list",
                    ),
                ],
                [
                    create_btn("addstopwords", callback_data="hact#sw_add"),
                    create_btn("remstopwords", callback_data="hact#cmd#remstopwords"),
                ],
                [
                    create_btn("defaultstopwords", callback_data="hact#sw_def"),
                    create_btn("remallstopwords", callback_data="hact#sw_clear"),
                ],
                [
                    create_btn(
                        "setnotfoundtext", callback_data="hact#cmd#setnotfoundtext"
                    ),
                    create_btn(
                        "defaultnotfoundtext",
                        callback_data="hact#cmd#defaultnotfoundtext",
                    ),
                ],
            ]
        )

    # 7. FILTERS MENU (helps_filters)
    elif section_key == "helps_filters":
        rows.extend(
            [
                [
                    create_btn("filter", callback_data="hact#cmd#filter"),
                    create_btn("addfilter", callback_data="hact#cmd#addfilter"),
                ],
                [
                    create_btn("filterimage", callback_data="hact#cmd#filterimage"),
                    create_btn(
                        "editfiltercolur", callback_data="hact#cmd#editfiltercolur"
                    ),
                ],
                [
                    create_btn("delfilter", callback_data="hact#cmd#delfilter"),
                    create_btn("listfilters", callback_data="hact#flt_list"),
                ],
            ]
        )

    # 8. FORCE SUBSCRIBE MENU (helps_forcesub)
    elif section_key == "helps_forcesub":
        f_on = bool(st.get("f_on", True))
        rot_on = bool(st.get("rot_on", False))

        rows.extend(
            [
                [
                    create_btn(
                        f"On/Off: {'ON ✅' if f_on else 'OFF ❌'}",
                        callback_data="hact#fsub_toggle",
                    ),
                    create_btn(
                        f"auto rotate: {'ON ✅' if rot_on else 'OFF ❌'}",
                        callback_data="hact#fsub_rot",
                    ),
                ],
                [
                    create_btn("Set fsub", callback_data="hact#cmd#setfsub"),
                    create_btn("rm fsub", callback_data="hact#cmd#rmfsub"),
                ],
                [
                    create_btn("Getallfsub", callback_data="hact#fsub_list"),
                    create_btn("totalrequests", callback_data="hact#cmd#totalrequests"),
                ],
                [
                    create_btn("purgerequests", callback_data="hact#cmd#purgerequests"),
                ],
            ]
        )

    # 9. FORCE ADD MENU (helps_forceadd)
    elif section_key == "helps_forceadd":
        fa_on = bool(st.get("fa_on", False))
        rows.extend(
            [
                [
                    create_btn(
                        f"On/Off: {'ON ✅' if fa_on else 'OFF ❌'}",
                        callback_data="hact#fa_toggle",
                    ),
                    create_btn("myadds", callback_data="hact#cmd#myadds"),
                ],
                [
                    create_btn("Set forceadd", callback_data="hact#cmd#setforceadd"),
                    create_btn("remforceadd", callback_data="hact#cmd#remforceadd"),
                ],
                [
                    create_btn("getforceadd", callback_data="hact#cmd#getforceadd"),
                    create_btn("topaddall", callback_data="hact#cmd#topaddall"),
                ],
                [
                    create_btn("topadd24", callback_data="hact#cmd#topadd24"),
                    create_btn("topadd7", callback_data="hact#cmd#topadd7"),
                ],
                [
                    create_btn("resetadddaily", callback_data="hact#cmd#resetadddaily"),
                    create_btn("resetadd", callback_data="hact#cmd#resetadd"),
                ],
            ]
        )

    # 10. BANS MENU (helps_bans)
    elif section_key == "helps_bans":
        rows.extend(
            [
                [
                    create_btn("ban", callback_data="hact#cmd#ban"),
                    create_btn("unban", callback_data="hact#cmd#unban"),
                ],
                [
                    create_btn("Banned users", callback_data="hact#cmd#bannedusers"),
                    create_btn("leave", callback_data="hact#cmd#leave"),
                ],
                [
                    create_btn("Enable", callback_data="hact#cmd#enable"),
                    create_btn("disable", callback_data="hact#cmd#disable"),
                ],
            ]
        )

    # 11. DELETE MENU (helps_delete)
    elif section_key == "helps_delete":
        rows.extend(
            [
                [
                    create_btn("Delete", callback_data="hact#cmd#delete"),
                    create_btn("del multi", callback_data="hact#cmd#delmulti"),
                ],
                [
                    create_btn("Autodelete", callback_data="hact#cmd#autodelete"),
                    create_btn("buttondel", callback_data="hact#cmd#buttondel"),
                    create_btn(
                        "purgeduplicates", callback_data="hact#cmd#purgeduplicates"
                    ),
                ],
            ]
        )

    # 12. PROMOTIONS & BROADCAST MENU (helps_promotions)
    elif section_key == "helps_promotions":
        rows.extend(
            [
                [
                    create_btn("addpromo", callback_data="hact#cmd#addpromo"),
                    create_btn("delpromo", callback_data="hact#cmd#delpromo"),
                ],
                [
                    create_btn("broadcast", callback_data="hact#cmd#broadcast"),
                    create_btn(
                        "group_broadcast", callback_data="hact#cmd#group_broadcast"
                    ),
                ],
                [
                    create_btn("listpromos", callback_data="hact#cmd#listpromos"),
                    create_btn("listbroadcast", callback_data="hact#cmd#listbroadcast"),
                ],
            ]
        )

    # 13. INDEX MENU (helps_index)
    elif section_key == "helps_index":
        rows.extend(
            [
                [
                    create_btn("index", callback_data="hact#cmd#index"),
                    create_btn("indexdoc", callback_data="hact#cmd#indexdoc"),
                    create_btn("indexvideo", callback_data="hact#cmd#indexvideo"),
                ],
                [
                    create_btn("indexaudio", callback_data="hact#cmd#indexaudio"),
                    create_btn("resumeindex", callback_data="hact#cmd#resumeindex"),
                ],
                [
                    create_btn("setskip", callback_data="hact#cmd#setskip"),
                    create_btn("deleteskip", callback_data="hact#cmd#deleteskip"),
                    create_btn("currentskip", callback_data="hact#cmd#currentskip"),
                ],
            ]
        )

    # 14. SETTINGS MENU (helps_settings)
    elif section_key == "helps_settings":
        rep_on = bool(st.get("rep_on", False))
        react_on = bool(st.get("react_on", True))
        rows.extend(
            [
                [
                    create_btn(
                        f"repairmode: {'ON ✅' if rep_on else 'OFF ❌'}",
                        callback_data="hact#repair_toggle",
                    ),
                    create_btn("adminsettings", callback_data="hact#cmd#adminsettings"),
                ],
                [
                    create_btn(
                        f"enablereaction {'✅' if react_on else ''}".strip(),
                        callback_data="hact#cmd#enablereaction",
                    ),
                    create_btn(
                        f"disablereaction {'✅' if not react_on else ''}".strip(),
                        callback_data="hact#cmd#disablereaction",
                    ),
                ],
            ]
        )

    # 15. CONNECTIONS MENU (helps_connections)
    elif section_key == "helps_connections":
        rows.extend(
            [
                [
                    create_btn("Connect", callback_data="hact#cmd#connect"),
                    create_btn("disconnect", callback_data="hact#cmd#disconnect"),
                ],
                [
                    create_btn("Connections", callback_data="hact#cmd#connections"),
                    create_btn("exportusers", callback_data="hact#cmd#exportusers"),
                ],
                [
                    create_btn("exportgroups", callback_data="hact#cmd#exportgroups"),
                    create_btn(
                        "exportchannels", callback_data="hact#cmd#exportchannels"
                    ),
                ],
                [
                    create_btn("channels", callback_data="hact#cmd#channels"),
                    create_btn("leavechannel", callback_data="hact#cmd#leavechannel"),
                ],
            ]
        )

    # 16. UTILITIES MENU (helps_utilities)
    elif section_key == "helps_utilities":
        rows.extend(
            [
                [
                    create_btn("Logs", callback_data="hact#cmd#logs"),
                    create_btn("server", callback_data="hact#cmd#server"),
                    create_btn("stats", callback_data="hact#cmd#stats"),
                ],
                [
                    create_btn("Optimize_db", callback_data="hact#cmd#optimize_db"),
                    create_btn("total", callback_data="hact#cmd#total"),
                    create_btn(
                        "clearfsubusers", callback_data="hact#cmd#clearfsubusers"
                    ),
                ],
                [
                    create_btn("clearfiles", callback_data="hact#cmd#clearfiles"),
                    create_btn("clearusers", callback_data="hact#cmd#clearusers"),
                    create_btn("cleanusers", callback_data="hact#cmd#cleanusers"),
                ],
            ]
        )

    # 17. CUSTOM MESSAGES MENU (helps_custommessages)
    elif section_key == "helps_custommessages":
        rows.extend(
            [
                [
                    create_btn("infomsg", callback_data="hact#cmd#infomsg"),
                    create_btn("infoimg", callback_data="hact#cmd#infoimg"),
                    create_btn("fsubmsg", callback_data="hact#cmd#fsubmsg"),
                ],
                [
                    create_btn("delmsg", callback_data="hact#cmd#delmsg"),
                    create_btn("delimg", callback_data="hact#cmd#delimg"),
                    create_btn("fsubimg", callback_data="hact#cmd#fsubimg"),
                ],
                [
                    create_btn("notfoundmsg", callback_data="hact#cmd#notfoundmsg"),
                    create_btn("notfoundimg", callback_data="hact#cmd#notfoundimg"),
                ],
            ]
        )

    # 18. CUSTOM CAPTIONS MENU (helps_customcaption)
    elif section_key == "helps_customcaption":
        rows.extend(
            [
                [
                    create_btn("customcaption", callback_data="hact#cmd#customcaption"),
                    create_btn("captionplus", callback_data="hact#cmd#captionplus"),
                ]
            ]
        )

    # 19. BACKUP MENU (helps_backup)
    elif section_key == "helps_backup":
        rows.extend(
            [
                [
                    create_btn("dbbackup", callback_data="hact#cmd#dbbackup"),
                    create_btn("dbrestore", callback_data="hact#cmd#dbrestore"),
                ],
                [
                    create_btn("dbstats", callback_data="hact#cmd#dbstats"),
                    create_btn("dbschedule", callback_data="hact#cmd#dbschedule"),
                ],
            ]
        )

    # 20. POST HANDLER MENU (helps_posthand)
    elif section_key == "helps_posthand":
        rows.extend(
            [
                [
                    create_btn("post", callback_data="hact#cmd#post"),
                    create_btn("editpost", callback_data="hact#cmd#editpost"),
                ],
                [
                    create_btn("edittitle", callback_data="hact#cmd#edittitle"),
                    create_btn("edityear", callback_data="hact#cmd#edityear"),
                ],
                [
                    create_btn("editlangs", callback_data="hact#cmd#editlangs"),
                    create_btn(
                        "editresolutions", callback_data="hact#cmd#editresolutions"
                    ),
                ],
                [
                    create_btn("editgenres", callback_data="hact#cmd#editgenres"),
                    create_btn("editotts", callback_data="hact#cmd#editotts"),
                ],
                [
                    create_btn("editbutton", callback_data="hact#cmd#editbutton"),
                    create_btn(
                        "editbuttoncolour", callback_data="hact#cmd#editbuttoncolour"
                    ),
                ],
                [
                    create_btn("editdirect", callback_data="hact#cmd#editdirect"),
                    create_btn(
                        "setpoststicker", callback_data="hact#cmd#setpoststicker"
                    ),
                    create_btn(
                        "rempoststicker", callback_data="hact#cmd#rempoststicker"
                    ),
                ],
            ]
        )

    # 21. PM AUTO-REPLY MENU (helps_pmautoreply)
    elif section_key == "helps_pmautoreply":
        pm_enabled = bool(st.get("pm_enabled", True))
        reply_admins = bool(st.get("reply_admins", True))

        rows.extend(
            [
                [
                    create_btn(
                        f"On/Off: {'ON ✅' if pm_enabled else 'OFF ❌'}",
                        callback_data="hact#pm_toggle",
                    ),
                    create_btn(
                        f"Reply Admins: {'ON ✅' if reply_admins else 'OFF ❌'}",
                        callback_data="hact#pm_adm_toggle",
                    ),
                ],
                [
                    create_btn("setpmtext", callback_data="hact#pm_settext"),
                    create_btn("rempmtext", callback_data="hact#pm_deftext"),
                ],
                [
                    create_btn("setpmimage", callback_data="hact#cmd#setpmimage"),
                    create_btn("rempmimage", callback_data="hact#pm_remimg"),
                ],
                [
                    create_btn("setpmbutton", callback_data="hact#pm_setbtn"),
                    create_btn("rempmbutton", callback_data="hact#pm_rembtn"),
                ],
            ]
        )

    rows.append(
        [
            create_btn("🔙 Back", callback_data="help"),
            create_btn("🔐 Close", callback_data="close_data"),
        ]
    )
    return InlineKeyboardMarkup(rows)


def get_channels_page_keyboard(page: int, total_pages: int) -> InlineKeyboardMarkup:
    buttons: List[List[InlineKeyboardButton]] = []
    nav_row: List[InlineKeyboardButton] = []
    if page > 1:
        nav_row.append(
            create_btn("⬅️ Previous", callback_data=f"channels_page#{page - 1}")
        )
    if page < total_pages:
        nav_row.append(create_btn("Next ➡️", callback_data=f"channels_page#{page + 1}"))
    if nav_row:
        buttons.append(nav_row)
    buttons.append([create_btn("🔐 Close", callback_data="close_data")])
    return InlineKeyboardMarkup(buttons)
