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
        indexes = ('$file_name', )
        collection_name = COLLECTION_NAME


async def save_batch(media_list):
    """
    ULTRA SPEED BULK INSERT: 
    Saves a list of media objects to the database in a single network request.
    Returns: (inserted_count, duplicate_count, error_count)
    """
    if not media_list:
        return 0, 0, 0

    documents = []
    for media in media_list:
        try:
            file_id, file_ref = unpack_new_file_id(media.file_id)
            # Safely get file_name, fallback to empty string if missing
            raw_name = getattr(media, "file_name", "") or ""
            file_name = re.sub(r"(_|\-|\.|\+)", " ", str(raw_name))
            
            caption = getattr(media, "caption", None)
            
            # Construct standard dictionary for raw Motor insertion (faster than ODM mapping)
            doc = {
                "_id": file_id,
                "file_ref": file_ref,
                "file_name": file_name,
                "file_size": getattr(media, "file_size", 0),
                "file_type": getattr(media, "file_type", None),
                "mime_type": getattr(media, "mime_type", None),
                "caption": caption.html if caption else None,
            }
            documents.append(doc)
        except Exception as e:
            logger.exception(f"Error parsing media for batch: {e}")

    if not documents:
        return 0, 0, len(media_list)

    try:
        # ordered=False tells MongoDB to keep inserting the rest even if it hits a duplicate
        result = await db[COLLECTION_NAME].insert_many(documents, ordered=False)
        return len(result.inserted_ids), 0, 0
    except BulkWriteError as bwe:
        # Tally up successful inserts, duplicates (error code 11000), and other errors
        inserted = bwe.details.get('nInserted', 0)
        duplicates = sum(1 for err in bwe.details.get('writeErrors', []) if err['code'] == 11000)
        errors = len(media_list) - inserted - duplicates
        return inserted, duplicates, errors


async def save_file(media):
    """Save single file in database (Kept for backward compatibility)"""
    file_id, file_ref = unpack_new_file_id(media.file_id)
    raw_name = getattr(media, "file_name", "") or ""
    file_name = re.sub(r"(_|\-|\.|\+)", " ", str(raw_name))
    
    try:
        file = Media(
            file_id=file_id,
            file_ref=file_ref,
            file_name=file_name,
            file_size=getattr(media, "file_size", 0),
            file_type=getattr(media, "file_type", None),
            mime_type=getattr(media, "mime_type", None),
            caption=media.caption.html if getattr(media, "caption", None) else None,
        )
    except ValidationError:
        logger.exception('Error occurred while mapping file in database')
        return False, 2
        
    try:
        await file.commit()
        return True, 1
    except DuplicateKeyError:      
        return False, 0
    except Exception as e:
        logger.exception(f'Error saving file: {e}')
        return False, 2


async def get_search_results(query, file_type=None, max_results=10, offset=0, filter=False):
    """For given query return (results, next_offset, total_results)"""
    query = query.strip()
    
    if not query:
        raw_pattern = '.'
    elif ' ' not in query:
        raw_pattern = r'(\b|[\.\+\-_])' + query + r'(\b|[\.\+\-_])'
    else:
        raw_pattern = query.replace(' ', r'.*[\s\.\+\-_]')
    
    try:
        regex = re.compile(raw_pattern, flags=re.IGNORECASE)
    except re.error:
        return [], '', 0

    db_filter = {'$or': [{'file_name': regex}, {'caption': regex}]} if USE_CAPTION_FILTER else {'file_name': regex}

    if file_type:
        db_filter['file_type'] = file_type

    total_results = await Media.count_documents(db_filter)
    next_offset = offset + max_results

    if next_offset > total_results:
        next_offset = ''

    cursor = Media.find(db_filter)
    cursor.sort('$natural', -1)
    cursor.skip(offset).limit(max_results)
    
    files = await cursor.to_list(length=max_results)
    return files, next_offset, total_results


async def get_file_details(query):
    filter = {'_id': query} # Changed to '_id' to match database schema correctly
    cursor = Media.find(filter)
    filedetails = await cursor.to_list(length=1)
    return filedetails


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
    """Return file_id, file_ref"""
    decoded = FileId.decode(new_file_id)
    # Handle Pyrogram 2.x ENUM conversions gracefully
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
