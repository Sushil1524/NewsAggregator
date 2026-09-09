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

    # ── articles collection ───────────────────────────────────────────────────
    # Primary sort index (most queries sort by created_at desc)
    await _database.articles.create_index([("created_at", -1)])
    # Compound: category feed + sort
    await _database.articles.create_index([("category", 1), ("created_at", -1)])
    # Compound: breaking news feed
    await _database.articles.create_index([("is_breaking", 1), ("created_at", -1)])
    # URL index for fast lookup (not unique — dedup is enforced by raw_articles)
    await _database.articles.create_index("url")
    # Multikey: tag and location filtering
    await _database.articles.create_index("tags")
    await _database.articles.create_index("locations")
    await _database.articles.create_index("country_code")
    # Full-text search on title + content
    await _database.articles.create_index([("title", "text"), ("content", "text")])

    # ── raw_articles ──────────────────────────────────────────────────────────
    await _database.raw_articles.create_index("url", unique=True)
    # Pipeline query: unprocessed articles sorted by ingestion time
    await _database.raw_articles.create_index([("is_processed", 1), ("created_at", 1)])
    # TTL: auto-delete processed raw articles after 7 days (keep DB lean)
    await _database.raw_articles.create_index(
        "created_at", expireAfterSeconds=604800, name="raw_articles_ttl"
    )

    # ── users ────────────────────────────────────────────────────────────────
    await _database.users.create_index("email", unique=True)
    await _database.users.create_index("username", unique=True)
    await _database.users.create_index("id", unique=True)

    # ── comments ─────────────────────────────────────────────────────────────
    await _database.comments.create_index([("article_id", 1), ("created_at", -1)])

    # ── user_interactions ─────────────────────────────────────────────────────
    await _database.user_interactions.create_index([("user_id", 1), ("timestamp", -1)])
    await _database.user_interactions.create_index("article_id")
    # TTL: auto-archive interactions older than 90 days
    await _database.user_interactions.create_index(
        "timestamp", expireAfterSeconds=7776000, name="user_interactions_ttl"
    )

    # ── article_votes ─────────────────────────────────────────────────────────
    await _database.article_votes.create_index(
        [("article_id", 1), ("user_id", 1)], unique=True
    )
    await _database.article_votes.create_index("article_id")
    await _database.article_votes.create_index("user_id")

    # ── clubs ─────────────────────────────────────────────────────────────────
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

def get_votes_collection():
    return get_database().article_votes

def get_pipeline_runs_collection():
    return get_database().pipeline_runs


# ─── Redis ─────────────────────────────────────────────────────────────────────

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


async def clear_cache_pattern(pattern: str = "article_list:*"):
    client = get_redis()
    if client:
        try:
            keys = await client.keys(pattern)
            if keys:
                await client.delete(*keys)
        except Exception:
            pass


# ─── JWT Blacklist (token revocation) ─────────────────────────────────────────

async def blacklist_token(jti: str, ttl_seconds: int):
    """
    Add a JWT ID to the Redis blacklist.
    ttl_seconds should match the token's remaining lifetime so the key
    auto-expires when the token would have anyway.
    """
    client = get_redis()
    if client and jti:
        await client.set(f"jti_blacklist:{jti}", "1", ex=max(ttl_seconds, 1))


async def is_token_blacklisted(jti: str) -> bool:
    """Return True if the token JTI has been revoked."""
    if not jti:
        return False
    client = get_redis()
    if client:
        return bool(await client.exists(f"jti_blacklist:{jti}"))
    return False


async def increment_view_count(article_id: str) -> int:
    client = get_redis()
    if client:
        return await client.incr(f"views:{article_id}")
    return 0


async def record_view_in_redis(article_id: str, ip: str, user_id: str | None = None) -> bool:
    client = get_redis()
    if not client:
        return False

    # Per-user dedup takes priority (30 min window)
    if user_id:
        user_debounce_key = f"view_user:{article_id}:{user_id}"
        if await client.get(user_debounce_key):
            return False
        await client.set(user_debounce_key, "1", ex=1800)
    else:
        # IP-based fallback debounce (20 seconds)
        ip_debounce_key = f"view_debounce:{article_id}:{ip}"
        if await client.get(ip_debounce_key):
            return False
        await client.set(ip_debounce_key, "1", ex=20)

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


# ─── Vote Management (Persistent + Redis-cached) ───────────────────────────────

async def get_user_vote_status(article_id: str, user_id: str) -> str | None:
    """Returns "up", "down", or None for the user's current vote on an article."""
    # Check Redis cache first (fast path)
    client = get_redis()
    if client:
        cached = await client.get(f"user_vote:{article_id}:{user_id}")
        if cached:
            return cached if cached != "none" else None

    # Fall back to MongoDB (persistent truth)
    try:
        votes_coll = get_votes_collection()
        doc = await votes_coll.find_one({"article_id": article_id, "user_id": user_id})
        if doc:
            vote_type = doc.get("vote_type")
            # Warm the cache
            if client:
                await client.set(f"user_vote:{article_id}:{user_id}", vote_type or "none", ex=2592000)
            return vote_type
    except Exception as e:
        print(f"Error fetching vote status: {e}")

    return None


async def set_user_vote(article_id: str, user_id: str, vote_type: str | None):
    """
    Insert, update, or delete a user's vote record.
    vote_type: "up" | "down" | None (None = remove the vote)
    """
    votes_coll = get_votes_collection()
    client = get_redis()

    if vote_type is None:
        # Remove vote
        await votes_coll.delete_one({"article_id": article_id, "user_id": user_id})
        if client:
            await client.set(f"user_vote:{article_id}:{user_id}", "none", ex=2592000)
    else:
        from datetime import datetime as dt
        await votes_coll.update_one(
            {"article_id": article_id, "user_id": user_id},
            {"$set": {"vote_type": vote_type, "updated_at": dt.utcnow()}},
            upsert=True
        )
        if client:
            await client.set(f"user_vote:{article_id}:{user_id}", vote_type, ex=2592000)


async def check_and_lock_vote(article_id: str, user_id: str, vote_type: str) -> bool:
    """
    Legacy compatibility: returns True if vote should be allowed (new vote).
    Use get_user_vote_status + set_user_vote for toggle-aware logic in routes.
    """
    existing = await get_user_vote_status(article_id, user_id)
    if existing == vote_type:
        return False  # Already voted this direction
    return True
