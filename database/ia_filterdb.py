import logging
import re
import base64
from struct import pack
from pyrogram.file_id import FileId
from pymongo.errors import DuplicateKeyError, BulkWriteError
from umongo import Instance, Document, fields
from motor.motor_asyncio import AsyncIOMotorClient
from marshmallow.exceptions import ValidationError

from info import DATABASE_URI, DATABASE_NAME, COLLECTION_NAME, USE_CAPTION_FILTER

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

client = AsyncIOMotorClient(DATABASE_URI)
db = client[DATABASE_NAME]

# Restored the correct dynamic initialization method
instance = Instance.from_db(db)

@instance.register
class Media(Document):
    file_id = fields.StrField(attribute='_id')
    file_ref = fields.StrField(allow_none=True)
    file_name = fields.StrField(required=True)
    file_size = fields.IntField(required=True)
    file_type = fields.StrField(allow_none=True)
    mime_type = fields.StrField(allow_none=True)
    caption = fields.StrField(allow_none=True)

    class Meta:
        indexes = ('$file_name', ) # The '$' symbol tells MongoDB to make this a Text Index
        collection_name = COLLECTION_NAME

async def save_batch(media_list):
    if not media_list:
        return 0, 0, 0

    documents = []
    for media in media_list:
        try:
            file_id, file_ref = unpack_new_file_id(media.file_id)
            raw_name = getattr(media, "file_name", "") or ""
            file_name = re.sub(r"(_|\-|\.|\+)", " ", str(raw_name))
            
            # Safely handle Pyrogram caption object which might not always have .html
            caption = getattr(media, "caption", None)
            caption_text = getattr(caption, "html", str(caption)) if caption else None
            
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
            logger.exception(f"Error parsing media for batch: {e}")

    if not documents:
        return 0, 0, len(media_list)

    try:
        # Bypassing umongo for bulk inserts to maximize speed
        result = await db[COLLECTION_NAME].insert_many(documents, ordered=False)
        return len(result.inserted_ids), 0, 0
    except BulkWriteError as bwe:
        inserted = bwe.details.get('nInserted', 0)
        duplicates = sum(1 for err in bwe.details.get('writeErrors', []) if err['code'] == 11000)
        errors = len(media_list) - inserted - duplicates
        return inserted, duplicates, errors

async def save_file(media):
    try:
        file_id, file_ref = unpack_new_file_id(media.file_id)
        raw_name = getattr(media, "file_name", "") or ""
        file_name = re.sub(r"(_|\-|\.|\+)", " ", str(raw_name))
        
        caption = getattr(media, "caption", None)
        caption_text = getattr(caption, "html", str(caption)) if caption else None
        
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
        logger.exception('Error occurred while mapping file in database')
        return False, 2
    except Exception as e:
        logger.exception(f'Error extracting file metadata: {e}')
        return False, 2
        
    try:
        await file.commit()
        return True, 1
    except DuplicateKeyError:      
        return False, 0
    except Exception as e:
        logger.exception(f'Error saving file: {e}')
        return False, 2

async def get_search_results(query_text, file_type=None, max_results=10, offset=0, filter=False):
    # Lazy import to avoid circular dependencies
    from utils import parse_ultra_advanced_query
    
    parsed = parse_ultra_advanced_query(query_text)
    conditions = []
    
    # 1. Flexible Regex Search instead of strict Text Search (FIXED)
    if parsed["title_words"]:
        for word in parsed["title_words"]:
            # This searches for the word anywhere in the file name, ignoring case
            conditions.append({"file_name": {"$regex": word, "$options": "i"}})
            
    # 2. Strict TV Show Matching
    if parsed["season"] is not None:
        s_regex = rf"(s0?{parsed['season']}\b|season\s*0?{parsed['season']}\b)"
        conditions.append({"file_name": {"$regex": s_regex, "$options": "i"}})
        
    if parsed["episode"] is not None:
        e_regex = rf"(e0?{parsed['episode']}\b|ep\s*0?{parsed['episode']}\b|episode\s*0?{parsed['episode']}\b)"
        conditions.append({"file_name": {"$regex": e_regex, "$options": "i"}})
        
    # 3. Add required Years, Qualities, and Languages
    for y in parsed["years"]:
        conditions.append({"file_name": {"$regex": rf"\b{y}\b", "$options": "i"}})
    for q in parsed["qualities"]:
        q_reg = q.replace(" ", ".*")
        conditions.append({"file_name": {"$regex": q_reg, "$options": "i"}})
    for l in parsed["languages"]:
        conditions.append({"file_name": {"$regex": rf"\b{l}\b", "$options": "i"}})

    # Fail-safe: if the user typed nothing but junk words and our parser emptied the string
    if not conditions:
        raw_pattern = query_text.replace(' ', r'.*[\s\.\+\-_]')
        conditions.append({"file_name": {"$regex": raw_pattern, "$options": "i"}})
        
    # Combine everything safely
    mongo_query = {"$and": conditions} if len(conditions) > 1 else conditions[0]
    
    if file_type:
        mongo_query = {"$and": [mongo_query, {"file_type": file_type}]}

    try:
        # Route count directly through motor collection to avoid umongo version mapping errors
        total_results = await db[COLLECTION_NAME].count_documents(mongo_query)
        
        next_offset = offset + max_results
        if next_offset > total_results:
            next_offset = ''

        # Search Database (Fixed cursor sorting and chaining)
        cursor = Media.find(mongo_query).sort([('$natural', -1)]).skip(offset).limit(max_results)
        files = await cursor.to_list(length=max_results)
        
        return files, next_offset, total_results
    except Exception as e:
        logger.exception(f"Database search error: {e}")
        return [], '', 0

async def get_file_details(query):
    try:
        filter_query = {'_id': query} 
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
    file_type = getattr(decoded.file_type, 'value', decoded.file_type) 
    
    file_id = encode_file_id(
        pack(
            "<iiqq",
            int(file_type),
            decoded.dc_id,
            decoded.media_id,
            decoded.access_hash
        )
    )
    file_ref = encode_file_ref(decoded.file_reference)
    return file_id, file_ref
