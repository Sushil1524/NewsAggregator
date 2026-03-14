from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
import redis.asyncio as redis
from app.config import get_settings

settings = get_settings()

_mongo_client: AsyncIOMotorClient | None = None
_database: AsyncIOMotorDatabase | None = None

async def connect_mongodb():
    global _mongo_client, _database
    _mongo_client = AsyncIOMotorClient(settings.mongodb_url)
    _database = _mongo_client[settings.mongodb_database]
    
    await _database.articles.create_index("created_at")
    await _database.articles.create_index("category")
    await _database.articles.create_index([("title", "text"), ("content", "text")])
    await _database.comments.create_index("article_id")
    await _database.raw_articles.create_index("url", unique=True)
    await _database.users.create_index("email", unique=True)
    await _database.users.create_index("username", unique=True)
    await _database.clubs.create_index("slug", unique=True)
    await _database.club_posts.create_index([("club_slug", 1), ("created_at", -1)])
    await _database.club_comments.create_index("post_id")
    print(f"Connected to MongoDB: {settings.mongodb_database}")

async def close_mongodb():
    global _mongo_client
    if _mongo_client:
        _mongo_client.close()
        print("MongoDB connection closed")

def get_database() -> AsyncIOMotorDatabase:
    if _database is None:
        raise RuntimeError("MongoDB not connected. Call connect_mongodb() first.")
    return _database

def get_articles_collection():
    return get_database().articles

def get_comments_collection():
    return get_database().comments

def get_raw_articles_collection():
    return get_database().raw_articles

def get_user_interactions_collection():
    return get_database().user_interactions

def get_users_collection():
    return get_database().users

def get_clubs_collection():
    return get_database().clubs

def get_club_posts_collection():
    return get_database().club_posts

def get_club_comments_collection():
    return get_database().club_comments


_redis_client: redis.Redis | None = None

async def connect_redis():
    global _redis_client
    redis_url = settings.redis_url
    
    if redis_url.startswith("rediss://") and "ssl_cert_reqs" not in redis_url:
        redis_url += "?ssl_cert_reqs=none" if "?" not in redis_url else "&ssl_cert_reqs=none"
    
    _redis_client = redis.from_url(redis_url, encoding="utf-8", decode_responses=True)
    await _redis_client.ping()
    print("Connected to Redis")

async def close_redis():
    global _redis_client
    if _redis_client:
        await _redis_client.close()
        print("Redis connection closed")

def get_redis() -> redis.Redis | None:
    return _redis_client

async def cache_set(key: str, value: str, expire_seconds: int = 300):
    client = get_redis()
    if client:
        await client.set(key, value, ex=expire_seconds)

async def cache_get(key: str) -> str | None:
    client = get_redis()
    if client:
        return await client.get(key)
    return None

async def cache_delete(key: str):
    client = get_redis()
    if client:
        await client.delete(key)

async def increment_view_count(article_id: str) -> int:
    client = get_redis()
    if client:
        return await client.incr(f"views:{article_id}")
    return 0

async def record_view_in_redis(article_id: str, ip: str) -> bool:
    client = get_redis()
    if not client:
        return False
    
    debounce_key = f"view_debounce:{article_id}:{ip}"
    if await client.get(debounce_key):
        return False
    
    await client.set(debounce_key, "1", ex=20)
    
    await client.sadd("pending_views_set", article_id)
    await client.hincrby("pending_views_h", article_id, 1)
    
    return True

async def sync_views_to_mongodb():
    client = get_redis()
    if not client:
        return
    
    article_ids = await client.smembers("pending_views_set")
    if not article_ids:
        return
    
    articles_coll = get_articles_collection()
    from bson import ObjectId
    
    for article_id in article_ids:
        try:
            pipe = client.pipeline()
            pipe.hget("pending_views_h", article_id)
            pipe.hdel("pending_views_h", article_id)
            pipe.srem("pending_views_set", article_id)
            results = await pipe.execute()
            
            count = int(results[0]) if results[0] else 0
            if count > 0:
                await articles_coll.update_one(
                    {"_id": ObjectId(article_id)},
                    {"$inc": {"views": count}}
                )
        except Exception as e:
            print(f"Error syncing views for {article_id}: {e}")
