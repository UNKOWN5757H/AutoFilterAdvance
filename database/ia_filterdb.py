import asyncio
import base64
import hashlib
import logging
import re
import time
import unicodedata
from struct import pack, unpack
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import BulkWriteError, DuplicateKeyError, OperationFailure
from pyrogram.file_id import FileId, FileType
from umongo import Document, fields
from umongo.frameworks.motor_asyncio import MotorAsyncIOInstance

from info import COLLECTION_NAME, DATABASE_NAME, DATABASE_URI, USE_CAPTION_FILTER

logger = logging.getLogger(__name__)
logger.setLevel(logging.ERROR)

# ============================================================
# 🔤 STYLISH UNICODE FONT STRIPPER FOR INDEXED FILENAMES
# ============================================================
_DB_STYLISH_MAP: Dict[int, str] = {}
for _sc_k, _sc_v in (
    ("ᴀ", "a"),
    ("ʙ", "b"),
    ("ᴄ", "c"),
    ("ᴅ", "d"),
    ("ᴇ", "e"),
    ("ꜰ", "f"),
    ("ɢ", "g"),
    ("ʜ", "h"),
    ("ɪ", "i"),
    ("ᴊ", "j"),
    ("ᴋ", "k"),
    ("ʟ", "l"),
    ("ᴍ", "m"),
    ("ɴ", "n"),
    ("ᴏ", "o"),
    ("ᴘ", "p"),
    ("ǫ", "q"),
    ("ʀ", "r"),
    ("ꜱ", "s"),
    ("ᴛ", "t"),
    ("ᴜ", "u"),
    ("ᴠ", "v"),
    ("ᴡ", "w"),
    ("x", "x"),
    ("ʏ", "y"),
    ("ᴢ", "z"),
):
    _DB_STYLISH_MAP[ord(_sc_k)] = _sc_v

for _i in range(26):
    _DB_STYLISH_MAP[0x24B6 + _i] = chr(ord("A") + _i)
    _DB_STYLISH_MAP[0x24D0 + _i] = chr(ord("a") + _i)
    _DB_STYLISH_MAP[0x1F110 + _i] = chr(ord("A") + _i)
    _DB_STYLISH_MAP[0x1F130 + _i] = chr(ord("A") + _i)
    _DB_STYLISH_MAP[0x1F150 + _i] = chr(ord("A") + _i)
    _DB_STYLISH_MAP[0x1F170 + _i] = chr(ord("A") + _i)
    _DB_STYLISH_MAP[0x1F1E6 + _i] = chr(ord("A") + _i)

for _start_cp, _base_ch, _cnt in (
    (0x1D400, "A", 26),
    (0x1D41A, "a", 26),
    (0x1D434, "A", 26),
    (0x1D44E, "a", 26),
    (0x1D468, "A", 26),
    (0x1D482, "a", 26),
    (0x1D49C, "A", 26),
    (0x1D4B6, "a", 26),
    (0x1D4D0, "A", 26),
    (0x1D4EA, "a", 26),
    (0x1D504, "A", 26),
    (0x1D51E, "a", 26),
    (0x1D538, "A", 26),
    (0x1D552, "a", 26),
    (0x1D56C, "A", 26),
    (0x1D586, "a", 26),
    (0x1D5A0, "A", 26),
    (0x1D5BA, "a", 26),
    (0x1D5D4, "A", 26),
    (0x1D5EE, "a", 26),
    (0x1D608, "A", 26),
    (0x1D622, "a", 26),
    (0x1D63C, "A", 26),
    (0x1D656, "a", 26),
    (0x1D670, "A", 26),
    (0x1D68A, "a", 26),
):
    for _i in range(_cnt):
        _DB_STYLISH_MAP[_start_cp + _i] = chr(ord(_base_ch) + _i)

for _d_start in (0x1D7CE, 0x1D7D8, 0x1D7E2, 0x1D7EC, 0x1D7F6):
    for _i in range(10):
        _DB_STYLISH_MAP[_d_start + _i] = str(_i)


def normalize_db_filename(text: str) -> str:
    if not text:
        return "File"
    text = text.translate(_DB_STYLISH_MAP)
    out: List[str] = []
    for ch in text:
        cp = ord(ch)
        if 0x0900 <= cp <= 0x0D7F:
            out.append(ch)
        elif 0x0300 <= cp <= 0x036F or 0x20D0 <= cp <= 0x20FF or 0xFE00 <= cp <= 0xFE0F:
            continue
        elif cp > 127:
            norm_ch = unicodedata.normalize("NFKC", ch).translate(_DB_STYLISH_MAP)
            norm_kd = unicodedata.normalize("NFKD", norm_ch)
            ascii_only = "".join(c for c in norm_kd if ord(c) < 128)
            if ascii_only:
                out.append(ascii_only)
        else:
            out.append(ch)
    return "".join(out)


# ============================================================
# 🗄️ DYNAMIC UNLIMITED MULTI-DATABASE ENGINE (PRIMARY + /datadb)
# ============================================================
_MONGO_KWARGS = {
    "serverSelectionTimeoutMS": 5000,
    "connectTimeoutMS": 5000,
    "socketTimeoutMS": 30000,
    "retryWrites": True,
}

_PRIMARY_CLIENT = AsyncIOMotorClient(DATABASE_URI, **_MONGO_KWARGS)
db = _PRIMARY_CLIENT[DATABASE_NAME]
instance = MotorAsyncIOInstance(db)

MULTI_DB_ENABLED: bool = True
DYNAMIC_DB_CLIENTS: Dict[str, Any] = {}
_DYNAMIC_MOTOR_CLIENTS: Dict[str, AsyncIOMotorClient] = {}
DYNAMIC_DB_META: List[Dict[str, Any]] = []

_DEAD_READ_DBS: Dict[int, float] = {}
_QUOTA_FULL_DBS: Dict[int, float] = {}
ACTIVE_DB_INDEX = 1


def extract_db_label_from_uri(uri: str, fallback_idx: int = 1) -> Tuple[str, str]:
    uri_clean = uri.strip()
    db_name = DATABASE_NAME
    try:
        parsed = urlparse(uri_clean)
        if parsed.path and len(parsed.path.strip("/")) > 0:
            path_db = parsed.path.strip("/").split("/")[0].split("?")[0].strip()
            if path_db:
                db_name = path_db
        host = parsed.hostname or ""
        if host:
            short_host = host.split(".")[0]
            user = parsed.username or ""
            label = f"{user}@{short_host}" if user else short_host
            return label[:28], db_name
    except Exception:
        pass
    return f"DB URL #{fallback_idx}", db_name


def make_db_id(uri: str) -> str:
    return hashlib.md5(uri.strip().encode("utf-8")).hexdigest()[:10]


def register_dynamic_db_entry(
    uri: str, custom_name: Optional[str] = None, db_name: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    uri_str = str(uri or "").strip()
    if not uri_str.startswith(("mongodb://", "mongodb+srv://")):
        return None
    if uri_str == DATABASE_URI:
        return None

    db_id = make_db_id(uri_str)
    auto_label, parsed_db_name = extract_db_label_from_uri(
        uri_str, len(DYNAMIC_DB_META) + 1
    )
    final_name = (custom_name or auto_label).strip()
    final_db_name = (db_name or parsed_db_name or DATABASE_NAME).strip()

    if db_id not in DYNAMIC_DB_CLIENTS:
        try:
            client = AsyncIOMotorClient(uri_str, **_MONGO_KWARGS)
            _DYNAMIC_MOTOR_CLIENTS[db_id] = client
            DYNAMIC_DB_CLIENTS[db_id] = client[final_db_name]
        except Exception as e:
            logger.error(f"Failed to init dynamic DB {final_name}: {e}")
            return None

    entry = {
        "id": db_id,
        "name": final_name,
        "uri": uri_str,
        "db_name": final_db_name,
    }
    for idx, item in enumerate(DYNAMIC_DB_META):
        if item["id"] == db_id:
            DYNAMIC_DB_META[idx] = entry
            break
    else:
        DYNAMIC_DB_META.append(entry)
    return entry


def unregister_dynamic_db_entry(db_id: str) -> bool:
    global ACTIVE_DB_INDEX
    DYNAMIC_DB_CLIENTS.pop(db_id, None)
    motor_client = _DYNAMIC_MOTOR_CLIENTS.pop(db_id, None)
    if motor_client is not None:
        try:
            motor_client.close()
        except Exception:
            pass

    before = len(DYNAMIC_DB_META)
    DYNAMIC_DB_META[:] = [item for item in DYNAMIC_DB_META if item.get("id") != db_id]
    ACTIVE_DB_INDEX = 1
    _DEAD_READ_DBS.clear()
    _QUOTA_FULL_DBS.clear()
    search_cache.clear()
    return len(DYNAMIC_DB_META) < before


def clear_all_dynamic_db_entries() -> int:
    global ACTIVE_DB_INDEX
    cnt = len(DYNAMIC_DB_META)
    for motor_client in list(_DYNAMIC_MOTOR_CLIENTS.values()):
        try:
            motor_client.close()
        except Exception:
            pass
    _DYNAMIC_MOTOR_CLIENTS.clear()
    DYNAMIC_DB_CLIENTS.clear()
    DYNAMIC_DB_META.clear()
    ACTIVE_DB_INDEX = 1
    _DEAD_READ_DBS.clear()
    _QUOTA_FULL_DBS.clear()
    search_cache.clear()
    return cnt


def set_multi_db_enabled(enabled: bool):
    global MULTI_DB_ENABLED, ACTIVE_DB_INDEX
    MULTI_DB_ENABLED = bool(enabled)
    ACTIVE_DB_INDEX = 1
    search_cache.clear()


def is_multi_db_enabled() -> bool:
    return bool(MULTI_DB_ENABLED)


def get_all_configured_dbs(
    include_when_disabled: bool = False,
) -> List[Tuple[int, Any, str]]:
    out: List[Tuple[int, Any, str]] = [(1, db, "Primary DB")]
    if not MULTI_DB_ENABLED and not include_when_disabled:
        return out

    seen_uris = {DATABASE_URI}
    next_idx = 2
    for item in DYNAMIC_DB_META:
        u = item.get("uri", "")
        db_id = item.get("id", "")
        if not u or u in seen_uris:
            continue
        target_handle = DYNAMIC_DB_CLIENTS.get(db_id)
        if target_handle is not None:
            out.append((next_idx, target_handle, item.get("name", f"DB {next_idx}")))
            seen_uris.add(u)
            next_idx += 1

    return out


def get_writable_System_db():
    now = time.time()
    all_dbs = get_all_configured_dbs(include_when_disabled=True)
    for idx, target, _ in all_dbs:
        if target is None:
            continue
        if now < _DEAD_READ_DBS.get(idx, 0.0) or now < _QUOTA_FULL_DBS.get(idx, 0.0):
            continue
        return target
    for idx, target, _ in reversed(all_dbs):
        if target is not None and now >= _DEAD_READ_DBS.get(idx, 0.0):
            return target
    return db


def get_all_healthy_read_dbs() -> List[Tuple[int, Any]]:
    now = time.time()
    return [
        (idx, target)
        for idx, target, _ in get_all_configured_dbs(include_when_disabled=False)
        if target is not None and now >= _DEAD_READ_DBS.get(idx, 0.0)
    ]


def _is_auth_or_conn_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(
        k in msg
        for k in (
            "bad auth",
            "authentication failed",
            "connection pool paused",
            "serverselectiontimeout",
            "timed out",
            "dnspython",
            "configurationerror",
        )
    )


def _is_quota_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "space quota" in msg or "over your space" in msg or "8000" in msg


def mark_db_error(idx: int, exc: Exception):
    now = time.time()
    if _is_quota_error(exc):
        _QUOTA_FULL_DBS[idx] = now + 1800
    elif _is_auth_or_conn_error(exc):
        _DEAD_READ_DBS[idx] = now + 1800


# ============================================================
# ⚡ SMART TTL CACHE
# ============================================================
class SimpleCache:
    def __init__(self, ttl: int = 900, maxsize: int = 5000):
        self.cache: Dict[str, Tuple[float, Any]] = {}
        self.ttl = ttl
        self.maxsize = maxsize

    def get(self, key: str):
        item = self.cache.get(key)
        if not item:
            return None
        if time.time() < item[0]:
            return item[1]
        self.cache.pop(key, None)
        return None

    def set(self, key: str, data: Any):
        now = time.time()
        if len(self.cache) >= self.maxsize:
            expired = [k for k, (exp, _) in list(self.cache.items()) if now >= exp]
            for k in expired:
                self.cache.pop(k, None)
            if len(self.cache) >= self.maxsize:
                self.cache.pop(next(iter(self.cache)), None)
        self.cache[key] = (now + self.ttl, data)

    def clear(self):
        self.cache.clear()


search_cache = SimpleCache(ttl=900, maxsize=5000)
file_details_cache = SimpleCache(ttl=3600, maxsize=10000)


# ============================================================
# 📦 MEDIA SCHEMA, FILE_ID CODEC & WRAPPER
# ============================================================
def encode_file_id(s_pack: str, file_ref: str) -> str:
    if not s_pack:
        return ""
    try:
        padded_pack = s_pack + "=" * (-len(s_pack) % 4)
        s_unpack = unpack("<iiqq", base64.urlsafe_b64decode(padded_pack))
        ref_bytes = (
            base64.urlsafe_b64decode(file_ref + "=" * (-len(file_ref) % 4))
            if file_ref
            else b""
        )
        try:
            file_id_obj = FileId(
                file_type=FileType(s_unpack[0]),
                dc_id=s_unpack[1],
                media_id=s_unpack[2],
                access_hash=s_unpack[3],
                file_reference=ref_bytes,
                sub_type=0,
            )
        except TypeError:
            file_id_obj = FileId(
                file_type=FileType(s_unpack[0]),
                dc_id=s_unpack[1],
                media_id=s_unpack[2],
                access_hash=s_unpack[3],
                file_reference=ref_bytes,
            )
        return file_id_obj.encode()
    except Exception:
        return s_pack


@instance.register
class Media(Document):
    file_id = fields.StrField(attribute="_id")
    file_ref = fields.StrField(allow_none=True)
    file_name = fields.StrField(required=True)
    file_size = fields.IntField(required=True)
    file_type = fields.StrField(allow_none=True)
    mime_type = fields.StrField(allow_none=True)
    caption = fields.StrField(allow_none=True)

    class Meta:
        indexes = []
        collection_name = COLLECTION_NAME


class SafeMediaWrapper:
    def __init__(self, data: dict):
        self._id = data.get("_id")
        self.file_id = self._id
        self.file_ref = data.get("file_ref", "")
        self.file_name = data.get("file_name", "")
        self.file_size = data.get("file_size", 0)
        self.file_type = data.get("file_type")
        self.mime_type = data.get("mime_type")
        self.caption = data.get("caption")
        self.chat_id = data.get("chat_id")
        self.msg_id = data.get("msg_id")

        raw = data.get("file_id_raw")
        if raw and len(str(raw)) > 30:
            self.full_file_id = str(raw)
        else:
            self.full_file_id = encode_file_id(
                str(self._id or ""), str(self.file_ref or "")
            )

    def get(self, key, default=None):
        return getattr(self, key, default)

    def __getitem__(self, key):
        return getattr(self, key)


async def update_cached_file_id(
    short_id: str,
    new_raw_file_id: str,
    chat_id: Optional[int] = None,
    msg_id: Optional[int] = None,
):
    try:
        _, new_ref = unpack_new_file_id(new_raw_file_id)
    except Exception:
        new_ref = ""

    upd_fields: Dict[str, Any] = {"file_id_raw": new_raw_file_id}
    if new_ref:
        upd_fields["file_ref"] = new_ref
    if chat_id:
        upd_fields["chat_id"] = int(chat_id)
    if msg_id:
        upd_fields["msg_id"] = int(msg_id)

    cached = file_details_cache.get(str(short_id))
    if cached:
        cached[0].full_file_id = new_raw_file_id
        if new_ref:
            cached[0].file_ref = new_ref

    for _, target_db in get_all_healthy_read_dbs():
        try:
            res = await asyncio.wait_for(
                target_db[COLLECTION_NAME].update_one(
                    {"_id": str(short_id)}, {"$set": upd_fields}
                ),
                timeout=3.0,
            )
            if res.modified_count > 0:
                break
        except Exception:
            continue


# ============================================================
# 🔥 MULTI-DB WIPE, LIVE STATS & STORAGE COMPACTION
# ============================================================
async def nuke_all_media_dbs() -> Dict[str, Any]:
    global ACTIVE_DB_INDEX
    summary: Dict[str, Any] = {"total_deleted": 0, "dbs_cleared": []}

    for idx, target_db, label in get_all_configured_dbs(include_when_disabled=True):
        if target_db is None:
            continue

        col = target_db[COLLECTION_NAME]
        count = 0
        try:
            count = await col.estimated_document_count()
            if count == 0:
                count = await col.count_documents({})
        except Exception:
            pass

        wiped = False
        try:
            await col.drop()
            wiped = True
        except Exception:
            try:
                res = await col.delete_many({})
                count = max(count, getattr(res, "deleted_count", 0))
                wiped = True
            except Exception as e:
                logger.error(f"Failed to wipe DB {idx} ({label}): {e}")

        if wiped:
            summary[f"db{idx}_deleted"] = count
            summary["total_deleted"] += count
            summary["dbs_cleared"].append(f"{label} ({count:,} files)")

        for extra_col in (
            "genlink_files",
            "genlink_batches",
            "index_checkpoints",
            "index_resume",
        ):
            try:
                await target_db[extra_col].drop()
            except Exception:
                pass

    _QUOTA_FULL_DBS.clear()
    _DEAD_READ_DBS.clear()
    ACTIVE_DB_INDEX = 1
    search_cache.clear()
    file_details_cache.clear()

    try:
        import plugins.pm_filter as _pmf

        _pmf.GLOBAL_SEARCH_CACHE._data.clear()
        _pmf.POOL_SEARCH_CACHE._data.clear()
        _pmf.FUZZY_TITLES_CACHE._data.clear()
    except Exception:
        pass

    return summary


async def _fetch_single_db_stats(
    idx: int, target_db: Any, label: str = ""
) -> Dict[str, Any]:
    quota_limit = 536870912
    if target_db is None:
        return {
            "index": idx,
            "label": label or f"DB {idx}",
            "configured": False,
            "status": "⚪ Not Configured",
            "files": 0,
            "used_bytes": 0,
            "free_bytes": 0,
        }

    try:
        col = target_db[COLLECTION_NAME]

        async def _get_cnt():
            try:
                return int(await col.count_documents({}))
            except Exception:
                return int(await col.estimated_document_count())

        files_cnt, db_stats = await asyncio.wait_for(
            asyncio.gather(
                _get_cnt(), target_db.command("dbstats"), return_exceptions=True
            ),
            timeout=6.0,
        )

        if isinstance(files_cnt, Exception):
            raise files_cnt
        if isinstance(db_stats, Exception):
            db_stats = {}

        data_size = int(db_stats.get("dataSize", 0) or 0)
        storage_size = int(db_stats.get("storageSize", 0) or 0)
        index_size = int(db_stats.get("indexSize", 0) or 0)
        used_bytes = max(data_size + index_size, storage_size)
        free_bytes = max(0, quota_limit - used_bytes)

        is_full = used_bytes >= (500 * 1024 * 1024) or time.time() < _QUOTA_FULL_DBS.get(
            idx, 0.0
        )
        _DEAD_READ_DBS.pop(idx, None)

        return {
            "index": idx,
            "label": label or f"DB {idx}",
            "configured": True,
            "status": "⚠️ Quota Full" if is_full else "🟢 Connected",
            "files": int(files_cnt or 0),
            "used_bytes": used_bytes,
            "free_bytes": free_bytes,
        }
    except Exception as e:
        mark_db_error(idx, e)
        return {
            "index": idx,
            "label": label or f"DB {idx}",
            "configured": True,
            "status": "🔴 Error / Unreachable",
            "files": 0,
            "used_bytes": 0,
            "free_bytes": 0,
        }


async def get_all_dbs_stats() -> Dict[str, Any]:
    all_configured = get_all_configured_dbs(include_when_disabled=True)
    results = (
        list(
            await asyncio.gather(
                *[
                    _fetch_single_db_stats(idx, handle, lbl)
                    for idx, handle, lbl in all_configured
                ]
            )
        )
        if all_configured
        else []
    )

    by_idx = {r["index"]: r for r in results}
    configured_dbs = [d for d in results if d["configured"]]

    return {
        "db1": by_idx.get(1) or await _fetch_single_db_stats(1, db, "Primary DB"),
        "db2": by_idx.get(2) or await _fetch_single_db_stats(2, None, "DB 2"),
        "db3": by_idx.get(3) or await _fetch_single_db_stats(3, None, "DB 3"),
        "all_dbs": results,
        "multi_db_enabled": MULTI_DB_ENABLED,
        "configured_count": len(configured_dbs),
        "active_db_index": ACTIVE_DB_INDEX,
        "total_files": sum(d["files"] for d in configured_dbs),
        "total_used_bytes": sum(d["used_bytes"] for d in configured_dbs),
        "total_free_bytes": sum(d["free_bytes"] for d in configured_dbs),
        "total_capacity_bytes": len(configured_dbs) * 536870912,
    }


async def free_up_mongodb_storage() -> Dict[str, Any]:
    global ACTIVE_DB_INDEX
    report: Dict[str, Any] = {
        "dropped_indexes": [],
        "cleared_temp_docs": 0,
        "compacted_files": 0,
    }

    for idx, target_db, _ in get_all_configured_dbs(include_when_disabled=True):
        if target_db is None or time.time() < _DEAD_READ_DBS.get(idx, 0.0):
            continue

        try:
            indexes = await target_db[COLLECTION_NAME].index_information()
            for idx_name in list(indexes.keys()):
                if idx_name != "_id_":
                    try:
                        await target_db[COLLECTION_NAME].drop_index(idx_name)
                        report["dropped_indexes"].append(f"DB{idx}:{idx_name}")
                    except Exception:
                        pass
        except Exception as e:
            mark_db_error(idx, e)

        for temp_col in (
            "index_resume",
            "index_checkpoints",
            "broadcast_tasks",
            "countdown_tasks",
            "fsub_join_requests",
            "fsub_verified_users",
            "fsub_users",
        ):
            try:
                res = await target_db[temp_col].delete_many({})
                report["cleared_temp_docs"] += getattr(res, "deleted_count", 0)
            except Exception:
                pass

        try:
            unset_fields = {"mime_type": ""}
            if not USE_CAPTION_FILTER:
                unset_fields["caption"] = ""
            res_upd = await target_db[COLLECTION_NAME].update_many(
                {"mime_type": {"$exists": True}}, {"$unset": unset_fields}
            )
            report["compacted_files"] += getattr(res_upd, "modified_count", 0)
        except Exception:
            pass

    _QUOTA_FULL_DBS.clear()
    ACTIVE_DB_INDEX = 1
    search_cache.clear()
    return report


# ============================================================
# 🔍 PARALLEL MULTI-DB SEARCH & FILE RETRIEVAL
# ============================================================
async def get_search_results(
    query_text,
    file_type=None,
    max_results=10,
    offset=0,
    filter=False,
    is_autocorrect=False,
):
    cache_key = (
        f"{query_text}_{file_type}_{max_results}_{offset}_{filter}_{int(MULTI_DB_ENABLED)}"
    )
    if cached := search_cache.get(cache_key):
        return cached

    try:
        from utils import parse_ultra_advanced_query

        parsed = parse_ultra_advanced_query(query_text)
    except Exception:
        parsed = {}

    conditions = []
    if parsed.get("title_words"):
        ordered_regex = ".*".join(re.escape(w) for w in parsed["title_words"])
        conditions.append({"file_name": {"$regex": ordered_regex, "$options": "i"}})

    if parsed.get("season") is not None:
        s_num = parsed["season"]
        conditions.append(
            {
                "file_name": {
                    "$regex": rf"(s0?{s_num}\b|season\s*0?{s_num}\b)",
                    "$options": "i",
                }
            }
        )
    if parsed.get("episode") is not None:
        e_num = parsed["episode"]
        conditions.append(
            {
                "file_name": {
                    "$regex": rf"(e0?{e_num}\b|ep\s*0?{e_num}\b|episode\s*0?{e_num}\b)",
                    "$options": "i",
                }
            }
        )

    for y in parsed.get("years", []):
        conditions.append({"file_name": {"$regex": rf"\b{y}\b", "$options": "i"}})
    for q in parsed.get("qualities", []):
        conditions.append({"file_name": {"$regex": rf"\b{q}\b", "$options": "i"}})
    for l in parsed.get("languages", []):
        conditions.append(
            {
                "$or": [
                    {"file_name": {"$regex": rf"\b{l}\b", "$options": "i"}},
                    {"caption": {"$regex": rf"\b{l}\b", "$options": "i"}},
                ]
            }
            if USE_CAPTION_FILTER
            else {"file_name": {"$regex": rf"\b{l}\b", "$options": "i"}}
        )

    if not conditions:
        conditions.append(
            {
                "file_name": {
                    "$regex": re.escape(query_text).replace(r"\ ", r".*"),
                    "$options": "i",
                }
            }
        )

    mongo_query = {"$and": conditions} if len(conditions) > 1 else conditions[0]
    if file_type:
        mongo_query = {"$and": [mongo_query, {"file_type": file_type}]}

    healthy_dbs = get_all_healthy_read_dbs()
    per_db_limit = offset + max_results + 1

    async def _query_one_db(idx: int, target_db: Any) -> List[dict]:
        try:
            return await asyncio.wait_for(
                target_db[COLLECTION_NAME]
                .find(mongo_query)
                .sort("_id", -1)
                .limit(per_db_limit)
                .to_list(length=per_db_limit),
                timeout=6.0,
            )
        except Exception as e:
            mark_db_error(idx, e)
            return []

    batches = await asyncio.gather(*[_query_one_db(i, t) for i, t in healthy_dbs])
    combined: List[dict] = []
    for batch in batches:
        if batch:
            combined.extend(batch)

    total_found = len(combined)
    sliced = combined[offset : offset + max_results]
    next_offset = offset + max_results if (offset + max_results) < total_found else 0

    wrapped_files = []
    for f in sliced:
        wrapped = SafeMediaWrapper(f)
        if wrapped.file_id:
            file_details_cache.set(str(wrapped.file_id), [wrapped])
        wrapped_files.append(wrapped)

    result = (wrapped_files, next_offset, total_found)
    if total_found > 0:
        search_cache.set(cache_key, result)
    return result


# ============================================================
# 💾 COMPACT MEDIA SAVING & AUTO-OVERFLOW BATCH ENGINE
# ============================================================
def _build_compact_media_doc(media) -> Optional[dict]:
    try:
        raw_fid = str(getattr(media, "file_id", "") or "")
        file_id, file_ref = unpack_new_file_id(raw_fid)
        raw_name = str(getattr(media, "file_name", "") or "File")
        norm_name = normalize_db_filename(raw_name)
        file_name = re.sub(r"[_\-\.\+]", " ", norm_name)
        file_name = re.sub(r"\s+", " ", file_name).strip() or "File"

        doc: Dict[str, Any] = {
            "_id": file_id,
            "file_ref": file_ref,
            "file_id_raw": raw_fid,
            "file_name": file_name,
            "file_size": int(getattr(media, "file_size", 0) or 0),
        }
        ftype = getattr(media, "file_type", None)
        if ftype:
            doc["file_type"] = str(ftype)
        if getattr(media, "chat_id", None):
            doc["chat_id"] = int(getattr(media, "chat_id"))
        if getattr(media, "msg_id", None):
            doc["msg_id"] = int(getattr(media, "msg_id"))
        if USE_CAPTION_FILTER and getattr(media, "caption", None):
            doc["caption"] = normalize_db_filename(str(getattr(media, "caption", "")))[
                :300
            ]
        return doc
    except Exception:
        return None


async def save_file(media) -> Tuple[bool, int]:
    global ACTIVE_DB_INDEX
    doc = _build_compact_media_doc(media)
    if not doc:
        return False, 2

    now = time.time()
    all_dbs = get_all_configured_dbs(include_when_disabled=False)
    if ACTIVE_DB_INDEX > len(all_dbs):
        ACTIVE_DB_INDEX = 1

    for i, target_db, _ in all_dbs:
        if i < ACTIVE_DB_INDEX or target_db is None:
            continue
        if now < _DEAD_READ_DBS.get(i, 0.0) or now < _QUOTA_FULL_DBS.get(i, 0.0):
            continue

        try:
            await asyncio.wait_for(
                target_db[COLLECTION_NAME].insert_one(doc), timeout=6.0
            )
            ACTIVE_DB_INDEX = i
            search_cache.clear()
            file_details_cache.set(str(doc["_id"]), [SafeMediaWrapper(doc)])
            return True, 1
        except DuplicateKeyError:
            return False, 0
        except Exception as e:
            mark_db_error(i, e)
            if _is_quota_error(e) or _is_auth_or_conn_error(e):
                ACTIVE_DB_INDEX = i + 1
                continue
            return False, 2

    return False, 8000


async def save_batch(media_list) -> Tuple[int, int, int]:
    global ACTIVE_DB_INDEX
    if not media_list:
        return 0, 0, 0

    documents = [
        doc for doc in (_build_compact_media_doc(m) for m in media_list) if doc
    ]
    if not documents:
        return 0, 0, len(media_list)

    now = time.time()
    all_dbs = get_all_configured_dbs(include_when_disabled=False)
    if ACTIVE_DB_INDEX > len(all_dbs):
        ACTIVE_DB_INDEX = 1

    for i, target_db, _ in all_dbs:
        if i < ACTIVE_DB_INDEX or target_db is None:
            continue
        if now < _DEAD_READ_DBS.get(i, 0.0) or now < _QUOTA_FULL_DBS.get(i, 0.0):
            continue

        try:
            res = await asyncio.wait_for(
                target_db[COLLECTION_NAME].insert_many(documents, ordered=False),
                timeout=20.0,
            )
            ACTIVE_DB_INDEX = i
            search_cache.clear()
            return len(res.inserted_ids), 0, 0
        except BulkWriteError as bwe:
            search_cache.clear()
            write_errors = bwe.details.get("writeErrors", [])
            is_quota = any(
                err.get("code") == 8000
                or "space quota" in str(err.get("errmsg", "")).lower()
                or "over your space" in str(err.get("errmsg", "")).lower()
                for err in write_errors
            )
            if is_quota:
                _QUOTA_FULL_DBS[i] = now + 1800
                ACTIVE_DB_INDEX = i + 1
                continue

            inserted = bwe.details.get("nInserted", 0)
            duplicates = sum(1 for err in write_errors if err.get("code") == 11000)
            return inserted, duplicates, max(0, len(media_list) - inserted - duplicates)
        except Exception as e:
            mark_db_error(i, e)
            if _is_quota_error(e) or _is_auth_or_conn_error(e):
                ACTIVE_DB_INDEX = i + 1
                continue
            return 0, 0, len(media_list)

    raise OperationFailure(
        "ALL AVAILABLE MONGODB CLUSTERS ARE FULL (Code 8000).", code=8000
    )


async def get_file_details(query):
    q_str = str(query).strip()
    if cached := file_details_cache.get(q_str):
        return cached

    for idx, target_db in get_all_healthy_read_dbs():
        try:
            doc = await asyncio.wait_for(
                target_db[COLLECTION_NAME].find_one({"_id": q_str}), timeout=3.0
            )
            if not doc and len(q_str) >= 20:
                doc = await asyncio.wait_for(
                    target_db[COLLECTION_NAME].find_one(
                        {"_id": {"$regex": f"^{re.escape(q_str)}"}}
                    ),
                    timeout=3.0,
                )
            if doc:
                wrapped = [SafeMediaWrapper(doc)]
                file_details_cache.set(q_str, wrapped)
                return wrapped
        except Exception as e:
            mark_db_error(idx, e)
            continue

    return []


def unpack_new_file_id(new_file_id):
    decoded = FileId.decode(new_file_id)
    file_id = (
        base64.urlsafe_b64encode(
            pack(
                "<iiqq",
                int(getattr(decoded.file_type, "value", decoded.file_type)),
                getattr(decoded, "dc_id", 0),
                getattr(decoded, "media_id", None) or getattr(decoded, "id", 0),
                getattr(decoded, "access_hash", 0),
            )
        )
        .decode()
        .rstrip("=")
    )
    return file_id, base64.urlsafe_b64encode(
        getattr(decoded, "file_reference", b"")
    ).decode().rstrip("=")
