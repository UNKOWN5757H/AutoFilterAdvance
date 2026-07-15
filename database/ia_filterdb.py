import asyncio
import base64
import logging
import re
import time
from struct import pack

from marshmallow.exceptions import ValidationError
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import BulkWriteError, DuplicateKeyError
from pyrogram.file_id import FileId
from umongo import Document, fields
from umongo.frameworks.motor_asyncio import MotorAsyncIOInstance

from info import COLLECTION_NAME, DATABASE_NAME, DATABASE_URI, USE_CAPTION_FILTER

# ==========================================
# TYPO TOLERANCE DEPENDENCY
# ==========================================
try:
    from thefuzz import process
except ImportError:
    process = None
    logging.getLogger(__name__).warning(
        "thefuzz is missing! Run 'pip install thefuzz[speedup]' to enable Typo Tolerance."
    )

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

client = AsyncIOMotorClient(DATABASE_URI)
db = client[DATABASE_NAME]
instance = MotorAsyncIOInstance(db)


# ==========================================
# 1. LIGHTWEIGHT IN-MEMORY CACHE
# ==========================================
class SimpleCache:
    def __init__(self, ttl_seconds=300):
        self.cache = {}
        self.ttl = ttl_seconds

    def get(self, key):
        if key in self.cache:
            if time.time() - self.cache[key]["time"] < self.ttl:
                return self.cache[key]["data"]
            else:
                del self.cache[key]
        return None

    def set(self, key, data):
        self.cache[key] = {"time": time.time(), "data": data}


search_cache = SimpleCache(ttl_seconds=300)


# ==========================================
# 2. FUZZY SEARCH VOCABULARY ENGINE
# ==========================================
KNOWN_TITLES = set()


def add_to_vocab(file_name):
    """Cleans a filename and adds its base title to the spellchecker vocabulary."""
    if not process:
        return
    # Strip out common technical metadata to isolate the actual movie name
    clean = re.sub(
        r"\b(mkv|mp4|avi|1080p|720p|480p|2160p|bluray|x264|hevc|web-dl|hdrip)\b",
        "",
        file_name,
        flags=re.IGNORECASE,
    )
    clean = re.sub(r"[_\-\.\+\[\]\(\)]", " ", clean)
    clean = re.sub(r"\s+", " ", clean).strip()
    if clean:
        KNOWN_TITLES.add(clean)


async def load_known_titles():
    """Builds the spellchecker dictionary on startup."""
    if not process:
        return
    try:
        # Load up to 50,000 recent unique names to prevent high RAM usage on VPS
        cursor = (
            db[COLLECTION_NAME].find({}, {"file_name": 1}).sort("_id", -1).limit(50000)
        )
        async for doc in cursor:
            add_to_vocab(doc.get("file_name", ""))

        logger.info(
            f"Typo Tolerance Active: Loaded {len(KNOWN_TITLES)} unique titles into memory."
        )
    except Exception as e:
        logger.error(f"Error loading known titles for spellcheck: {e}")


# ==========================================
# 3. DATABASE SCHEMA
# ==========================================
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
        indexes = [
            {
                "key": [("file_name", "text"), ("caption", "text")],
                "name": "media_text_index",
                "weights": {"file_name": 10, "caption": 2},
            }
        ]
        collection_name = COLLECTION_NAME


async def save_batch(media_list):
    if not media_list:
        return 0, 0, 0

    documents = []
    for media in media_list:
        try:
            file_id, file_ref = unpack_new_file_id(media.file_id)
            raw_name = getattr(media, "file_name", "") or ""
            file_name = re.sub(r"[_\-\.\+]", " ", str(raw_name))

            # Auto-feed the new file into the spellchecker dictionary live
            add_to_vocab(file_name)

            caption = getattr(media, "caption", None)
            caption_text = str(caption) if caption else None

            doc = {
                "_id": file_id,
                "file_ref": file_ref,
                "file_name": file_name,
                "file_size": getattr(media, "file_size", 0),
                "file_type": getattr(media, "file_type", None),
                "mime_type": getattr(media, "mime_type", None),
                "caption": caption_text,
            }
            documents.append(doc)
        except Exception as e:
            logger.error(f"Error parsing media for batch: {e}")

    if not documents:
        return 0, 0, len(media_list)

    try:
        result = await db[COLLECTION_NAME].insert_many(documents, ordered=False)
        return len(result.inserted_ids), 0, 0
    except BulkWriteError as bwe:
        inserted = bwe.details.get("nInserted", 0)
        duplicates = sum(
            1 for err in bwe.details.get("writeErrors", []) if err["code"] == 11000
        )
        errors = len(media_list) - inserted - duplicates
        return inserted, duplicates, errors


async def save_file(media):
    try:
        file_id, file_ref = unpack_new_file_id(media.file_id)
        raw_name = getattr(media, "file_name", "") or ""
        file_name = re.sub(r"[_\-\.\+]", " ", str(raw_name))

        # Auto-feed new file into spellchecker
        add_to_vocab(file_name)

        caption = getattr(media, "caption", None)
        caption_text = str(caption) if caption else None

        file = Media(
            file_id=file_id,
            file_ref=file_ref,
            file_name=file_name,
            file_size=getattr(media, "file_size", 0),
            file_type=getattr(media, "file_type", None),
            mime_type=getattr(media, "mime_type", None),
            caption=caption_text,
        )
    except ValidationError:
        logger.error("Error occurred while mapping file in database")
        return False, 2
    except Exception as e:
        logger.error(f"Error extracting file metadata: {e}")
        return False, 2

    try:
        await file.commit()
        return True, 1
    except DuplicateKeyError:
        return False, 0
    except Exception as e:
        logger.error(f"Error saving file: {e}")
        return False, 2


# ==========================================
# 4. HIGH-SPEED SEARCH (With Typo Correction & Partial Matching)
# ==========================================
async def get_search_results(
    query_text,
    file_type=None,
    max_results=10,
    offset=0,
    filter=False,
    is_autocorrect=False,
):
    # Base Cache Key ensures queries get cached
    cache_key = f"{query_text}_{file_type}_{max_results}_{offset}_{filter}"
    cached_data = search_cache.get(cache_key)
    if cached_data:
        return cached_data

    from utils import parse_ultra_advanced_query

    parsed = parse_ultra_advanced_query(query_text)
    conditions = []

    # 1. Regex Search (Restored for perfect Partial Matching e.g., "ave" -> "avengers")
    if parsed.get("title_words"):
        for word in parsed["title_words"]:
            conditions.append({"file_name": {"$regex": re.escape(word), "$options": "i"}})

    if parsed.get("season") is not None:
        s_regex = rf"(s0?{parsed['season']}\b|season\s*0?{parsed['season']}\b)"
        conditions.append({"file_name": {"$regex": s_regex, "$options": "i"}})

    if parsed.get("episode") is not None:
        e_regex = rf"(e0?{parsed['episode']}\b|ep\s*0?{parsed['episode']}\b|episode\s*0?{parsed['episode']}\b)"
        conditions.append({"file_name": {"$regex": e_regex, "$options": "i"}})

    for y in parsed.get("years", []):
        conditions.append({"file_name": {"$regex": rf"\b{y}\b", "$options": "i"}})
    for q in parsed.get("qualities", []):
        conditions.append({"file_name": {"$regex": rf"\b{q}\b", "$options": "i"}})
    for l in parsed.get("languages", []):
        if USE_CAPTION_FILTER:
            conditions.append(
                {
                    "$or": [
                        {"file_name": {"$regex": rf"\b{l}\b", "$options": "i"}},
                        {"caption": {"$regex": rf"\b{l}\b", "$options": "i"}},
                    ]
                }
            )
        else:
            conditions.append({"file_name": {"$regex": rf"\b{l}\b", "$options": "i"}})

    if not conditions:
        safe_query = re.escape(query_text).replace(r"\ ", r".*[\s\.\+\-_]")
        conditions.append({"file_name": {"$regex": safe_query, "$options": "i"}})

    mongo_query = {"$and": conditions} if len(conditions) > 1 else conditions[0]
    if file_type:
        mongo_query = {"$and": [mongo_query, {"file_type": file_type}]}

    try:
        total_results = await db[COLLECTION_NAME].count_documents(mongo_query)

        # ==========================================
        # TYPO TOLERANCE FALLBACK
        # ==========================================
        # If no results found, check the dictionary for a spelling mistake
        if total_results == 0 and not is_autocorrect and process and KNOWN_TITLES:
            best_match = process.extractOne(query_text, KNOWN_TITLES)
            if best_match:
                match_text, score = best_match
                # A score above 75 means it's a likely typo
                if 75 <= score <= 100:
                    logger.info(
                        f"Typo corrected: '{query_text}' -> '{match_text}' (Score: {score})"
                    )

                    # Recursively run the search with the correctly spelled title
                    corrected_results = await get_search_results(
                        match_text,
                        file_type,
                        max_results,
                        offset,
                        filter,
                        is_autocorrect=True,
                    )

                    # Cache this corrected output under the TYPO's cache key 
                    # ONLY if it found results.
                    if corrected_results[2] > 0:
                        search_cache.set(cache_key, corrected_results)
                    return corrected_results
        # ==========================================

        next_offset = offset + max_results
        if next_offset > total_results:
            next_offset = ""

        # Fetch from DB (Sorted newest first, standard PyMongo retrieval)
        cursor = db[COLLECTION_NAME].find(mongo_query).sort("_id", -1)
        cursor = cursor.skip(offset).limit(max_results)
        files = await cursor.to_list(length=max_results)

        media_files = [Media(**f) for f in files]

        result_tuple = (media_files, next_offset, total_results)
        
        # MEMORY LEAK & BUG FIX: 
        # ONLY cache the query if we successfully found files! 
        # This prevents locking failed searches in the system for 5 minutes.
        if total_results > 0:
            search_cache.set(cache_key, result_tuple)

        return result_tuple

    except Exception as e:
        logger.error(f"Database search error: {e}")
        return [], "", 0


async def get_file_details(query):
    try:
        filter_query = {"_id": query}
        cursor = Media.find(filter_query)
        filedetails = await cursor.to_list(length=1)
        return filedetails
    except Exception as e:
        logger.error(f"Error fetching file details: {e}")
        return []


def encode_file_id(s: bytes) -> str:
    r = b""
    n = 0
    for i in s + bytes([22]) + bytes([4]):
        if i == 0:
            n += 1
        else:
            if n:
                r += b"\x00" + bytes([n])
                n = 0
            r += bytes([i])
    return base64.urlsafe_b64encode(r).decode().rstrip("=")


def encode_file_ref(file_ref: bytes) -> str:
    return base64.urlsafe_b64encode(file_ref).decode().rstrip("=")


def unpack_new_file_id(new_file_id):
    decoded = FileId.decode(new_file_id)
    file_type = getattr(decoded.file_type, "value", decoded.file_type)

    media_id = getattr(decoded, "media_id", None) or getattr(decoded, "id", 0)
    access_hash = getattr(decoded, "access_hash", 0)
    dc_id = getattr(decoded, "dc_id", 0)
    file_ref_bytes = getattr(decoded, "file_reference", b"")

    file_id = encode_file_id(
        pack("<iiqq", int(file_type), dc_id, media_id, access_hash)
    )
    file_ref = encode_file_ref(file_ref_bytes)
    return file_id, file_ref
