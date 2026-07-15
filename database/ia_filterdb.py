import base64
import logging
import re
from struct import pack

from marshmallow.exceptions import ValidationError
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import BulkWriteError, DuplicateKeyError
from pyrogram.file_id import FileId
from umongo import Document, fields
from umongo.frameworks.motor_asyncio import MotorAsyncIOInstance

from info import COLLECTION_NAME, DATABASE_NAME, DATABASE_URI, USE_CAPTION_FILTER

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

client = AsyncIOMotorClient(DATABASE_URI)
db = client[DATABASE_NAME]

instance = MotorAsyncIOInstance(db)


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
        # Text index on file_name ensures lightning-fast keyword searches
        indexes = ("$file_name",)
        collection_name = COLLECTION_NAME


async def save_batch(media_list):
    if not media_list:
        return 0, 0, 0

    documents = []
    for media in media_list:
        try:
            file_id, file_ref = unpack_new_file_id(media.file_id)
            raw_name = getattr(media, "file_name", "") or ""
            # Replace common delimiters with spaces to make text indexing highly effective
            file_name = re.sub(r"[_\-\.\+]", " ", str(raw_name))

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
        # Bypassing umongo for bulk inserts maximizes write speed
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


async def get_search_results(
    query_text, file_type=None, max_results=10, offset=0, filter=False
):
    from utils import parse_ultra_advanced_query

    parsed = parse_ultra_advanced_query(query_text)
    conditions = []
    use_text_search = False

    # 1. Primary Text Search (Fast & Relevant)
    # Group all title words together to leverage MongoDB's text index
    if parsed.get("title_words"):
        search_string = ' '.join(parsed["title_words"])
        # Adding quotes around words forces exact word matching in Mongo
        conditions.append({"$text": {"$search": f'"{search_string}"'}})
        use_text_search = True

    # 2. Strict TV Show Matching (Regex is okay here because it's filtering a smaller subset)
    if parsed.get("season") is not None:
        s_regex = rf"(s0?{parsed['season']}\b|season\s*0?{parsed['season']}\b)"
        conditions.append({"file_name": {"$regex": s_regex, "$options": "i"}})

    if parsed.get("episode") is not None:
        e_regex = rf"(e0?{parsed['episode']}\b|ep\s*0?{parsed['episode']}\b|episode\s*0?{parsed['episode']}\b)"
        conditions.append({"file_name": {"$regex": e_regex, "$options": "i"}})

    # 3. Attributes filtering
    for y in parsed.get("years", []):
        conditions.append({"file_name": {"$regex": rf"\b{y}\b", "$options": "i"}})
    for q in parsed.get("qualities", []):
        conditions.append({"file_name": {"$regex": rf"\b{q}\b", "$options": "i"}})
    for l in parsed.get("languages", []):
        conditions.append({"file_name": {"$regex": rf"\b{l}\b", "$options": "i"}})

    # 4. Fallback if the parser didn't catch anything
    if not conditions:
        safe_query = re.escape(query_text).replace(r"\ ", r".*[\s\.\+\-_]")
        conditions.append({"file_name": {"$regex": safe_query, "$options": "i"}})

    # Combine queries safely
    mongo_query = {"$and": conditions} if len(conditions) > 1 else conditions[0]

    if file_type:
        mongo_query = {"$and": [mongo_query, {"file_type": file_type}]}

    try:
        total_results = await db[COLLECTION_NAME].count_documents(mongo_query)

        next_offset = offset + max_results
        if next_offset > total_results:
            next_offset = ""

        # 5. Sorting by Relevance
        # If we used $text search, sort by textScore to show best matches first.
        # Otherwise, sort by _id descending (newest first).
        if use_text_search:
            cursor = db[COLLECTION_NAME].find(
                mongo_query, 
                {"score": {"$meta": "textScore"}}
            ).sort([("score", {"$meta": "textScore"})])
        else:
            cursor = db[COLLECTION_NAME].find(mongo_query).sort("_id", -1)

        cursor = cursor.skip(offset).limit(max_results)
        files = await cursor.to_list(length=max_results)

        # Re-map bare dictionaries back into umongo Media objects for compatibility
        # if the rest of your bot expects Umongo objects rather than dicts.
        media_files = [Media(**f) for f in files]

        return media_files, next_offset, total_results

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
    """
    Decodes the file_id and safely extracts attributes regardless of the Pyrogram media type.
    """
    decoded = FileId.decode(new_file_id)
    file_type = getattr(decoded.file_type, "value", decoded.file_type)

    # Fallback cascade to prevent attribute errors on different Pyrogram versions
    media_id = getattr(decoded, "media_id", None) or getattr(decoded, "id", 0)
    access_hash = getattr(decoded, "access_hash", 0)
    dc_id = getattr(decoded, "dc_id", 0)
    file_ref_bytes = getattr(decoded, "file_reference", b"")

    file_id = encode_file_id(
        pack(
            "<iiqq",
            int(file_type),
            dc_id,
            media_id,
            access_hash,
        )
    )
    file_ref = encode_file_ref(file_ref_bytes)
    return file_id, file_ref
