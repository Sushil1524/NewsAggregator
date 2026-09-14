from datetime import datetime, timedelta
import hashlib
import json
from typing import Dict, List, Optional
from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, status, Header, Query
from pydantic import BaseModel
from app.dependencies import get_current_user_required, get_current_user_optional
from app.models.user import UserResponse
from app.models.article import ArticleResponse, ArticleListItem
from app.db import (
    get_articles_collection, get_user_interactions_collection, get_users_collection,
    record_view_in_redis, get_user_vote_status, set_user_vote, get_redis,
    cache_get, cache_set,
)

router = APIRouter()

# Article list cache TTL in seconds — data only changes when the pipeline runs (~15 min)
_ARTICLE_LIST_CACHE_TTL = 180  # 3 minutes


def _make_list_cache_key(
    cursor: Optional[datetime],
    limit: int,
    category: Optional[str],
    tag: Optional[str],
    sort_by: str,
    date_filter: Optional[str],
    location: Optional[str],
    is_breaking: Optional[bool],
) -> str:
    """Stable cache key from all query parameters."""
    parts = (
        f"{cursor.isoformat() if cursor else ''}"
        f"|{limit}|{category or ''}|{tag or ''}|{sort_by}"
        f"|{date_filter or ''}|{location or ''}|{is_breaking}"
    )
    digest = hashlib.md5(parts.encode()).hexdigest()
    return f"article_list:{digest}"


async def _get_articles_helper(
    cursor: Optional[datetime],
    limit: int,
    category: Optional[str],
    tag: Optional[str],
    sort_by: str,
    date_filter: Optional[str],
    location: Optional[str] = None,
    is_breaking: Optional[bool] = None,
) -> List[ArticleListItem]:
    # ── Redis cache check ────────────────────────────────────────────────────
    cache_key = _make_list_cache_key(cursor, limit, category, tag, sort_by, date_filter, location, is_breaking)
    try:
        cached_raw = await cache_get(cache_key)
        if cached_raw:
            data = json.loads(cached_raw)
            return [ArticleListItem(**item) for item in data]
    except Exception:
        pass  # Cache miss or parse error — fall through to DB

    collection = get_articles_collection()
    query = {}

    if cursor:
        if sort_by == "old":
            query["created_at"] = {"$gt": cursor}
        else:
            query["created_at"] = {"$lt": cursor}

    if category:
        query["category"] = category.title()

    if tag:
        query["tags"] = tag

    if location:
        query["locations"] = location

    if is_breaking is not None:
        query["is_breaking"] = is_breaking

    if date_filter == "today":
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        query["created_at"] = {"$gte": today_start}
    elif date_filter == "last_hour":
        hour_ago = datetime.utcnow() - timedelta(hours=1)
        query["created_at"] = {"$gte": hour_ago}
    elif date_filter == "week":
        week_ago = datetime.utcnow() - timedelta(days=7)
        query["created_at"] = {"$gte": week_ago}
    elif date_filter == "month":
        month_ago = datetime.utcnow() - timedelta(days=30)
        query["created_at"] = {"$gte": month_ago}

    if sort_by == "top" or sort_by == "hot":
        sort = [("upvotes", -1), ("created_at", -1)]
    elif sort_by == "views":
        sort = [("views", -1), ("created_at", -1)]
    elif sort_by == "old":
        sort = [("created_at", 1)]
    else:
        sort = [("created_at", -1)]

    cursor_result = collection.find(query).sort(sort).limit(limit)
    articles = await cursor_result.to_list(length=limit)

    result = [
        ArticleListItem(
            id=str(article["_id"]),
            title=article["title"],
            url=article.get("url") or "",
            image_url=article.get("image_url"),
            summary=article.get("summary") or "Click to read the full story.",
            category=article.get("category"),
            sentiment=article.get("sentiment"),
            tags=article.get("tags", []),
            locations=article.get("locations", []),
            source=article.get("source", "Unknown"),
            country_code=article.get("country_code"),
            reading_time_minutes=article.get("reading_time_minutes", 5),
            is_breaking=article.get("is_breaking", False),
            upvotes=article.get("upvotes", 0),
            downvotes=article.get("downvotes", 0),
            views=article.get("views", 0),
            summary_source=article.get("summary_source"),
            created_at=article["created_at"],
        )
        for article in articles
    ]

    # ── Store in Redis cache ─────────────────────────────────────────────────
    try:
        payload = json.dumps([item.model_dump(mode="json") for item in result], default=str)
        await cache_set(cache_key, payload, expire_seconds=_ARTICLE_LIST_CACHE_TTL)
    except Exception:
        pass

    return result



async def _track_user_interaction(
    user_id: str,
    article_id: str,
    interaction_type: str,
    duration: Optional[int] = None
):
    collection = get_user_interactions_collection()
    await collection.insert_one({
        "user_id": user_id,
        "article_id": article_id,
        "interaction_type": interaction_type,
        "reading_duration_seconds": duration,
        "timestamp": datetime.utcnow(),
    })


@router.get("", response_model=List[ArticleListItem])
@router.get("/", response_model=List[ArticleListItem])
async def list_articles(
    cursor: Optional[datetime] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    category: Optional[str] = Query(None),
    tag: Optional[str] = Query(None),
    location: Optional[str] = Query(None),
    is_breaking: Optional[bool] = Query(None),
    sort_by: str = Query("new", pattern="^(new|old|top|hot|views)$"),
    date_filter: Optional[str] = Query(None, pattern="^(today|last_hour|week|month)$"),
):
    return await _get_articles_helper(cursor, limit, category, tag, sort_by, date_filter, location, is_breaking)


@router.get("/search", response_model=List[ArticleListItem])
async def search_articles(
    q: str = Query(..., min_length=2, max_length=200, description="Search query"),
    limit: int = Query(20, ge=1, le=50),
    category: Optional[str] = Query(None, description="Filter results by category"),
):
    """
    Full-text search across article titles and content.
    Results are ranked by MongoDB text relevance score (textScore).
    Supports optional category filtering.
    """
    if not q.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    collection = get_articles_collection()
    query: dict = {"$text": {"$search": q.strip()}}
    if category:
        query["category"] = category.title()

    cursor_result = (
        collection.find(
            query,
            {"score": {"$meta": "textScore"}},  # include relevance score
        )
        .sort([("score", {"$meta": "textScore"}), ("created_at", -1)])
        .limit(limit)
    )
    articles = await cursor_result.to_list(length=limit)

    if not articles:
        return []

    return [
        ArticleListItem(
            id=str(article["_id"]),
            title=article["title"],
            url=article.get("url") or "",
            image_url=article.get("image_url"),
            summary=article.get("summary") or "",
            category=article.get("category"),
            sentiment=article.get("sentiment"),
            tags=article.get("tags", []),
            locations=article.get("locations", []),
            source=article.get("source", "Unknown"),
            country_code=article.get("country_code"),
            reading_time_minutes=article.get("reading_time_minutes", 5),
            is_breaking=article.get("is_breaking", False),
            upvotes=article.get("upvotes", 0),
            downvotes=article.get("downvotes", 0),
            views=article.get("views", 0),
            summary_source=article.get("summary_source"),
            created_at=article["created_at"],
        )
        for article in articles
    ]


@router.get("/personalized", response_model=List[ArticleListItem])
async def get_personalized(limit: int = Query(20, ge=1, le=100), current_user: UserResponse = Depends(get_current_user_required)):
    collection = get_articles_collection()
    preferences = current_user.news_preferences

    enabled_categories = [cat for cat, enabled in preferences.items() if enabled]

    query = {}
    if enabled_categories:
        query["category"] = {"$in": enabled_categories}

    cursor = collection.find(query).sort("created_at", -1).limit(limit * 2)
    all_articles = await cursor.to_list(length=limit * 2)

    breaking = [a for a in all_articles if a.get("is_breaking")]
    regular = [a for a in all_articles if not a.get("is_breaking")]

    sorted_articles = (breaking + regular)[:limit]

    return [
        ArticleListItem(
            id=str(article["_id"]),
            title=article["title"],
            url=article.get("url") or "",
            image_url=article.get("image_url"),
            summary=article.get("summary"),
            category=article.get("category"),
            sentiment=article.get("sentiment"),
            tags=article.get("tags", []),
            locations=article.get("locations", []),
            source=article.get("source", "Unknown"),
            country_code=article.get("country_code"),
            reading_time_minutes=article.get("reading_time_minutes", 5),
            is_breaking=article.get("is_breaking", False),
            upvotes=article.get("upvotes", 0),
            downvotes=article.get("downvotes", 0),
            views=article.get("views", 0),
            summary_source=article.get("summary_source"),
            created_at=article["created_at"],
        )
        for article in sorted_articles
    ]


@router.get("/{article_id}", response_model=ArticleResponse)
async def get_article(
    article_id: str,
    x_reading_duration: Optional[int] = Header(None),
    current_user: Optional[UserResponse] = Depends(get_current_user_optional),
):
    collection = get_articles_collection()
    try:
        article = await collection.find_one({"_id": ObjectId(article_id)})
    except Exception:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Article not found")

    if not article:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Article not found")

    if current_user:
        await _track_user_interaction(current_user.id, article_id, "view")

        from datetime import date
        users_coll = get_users_collection()

        # Calculate reading time
        if x_reading_duration and x_reading_duration > 0:
            reading_time = max(1, round(x_reading_duration / 60))
        else:
            reading_time = article.get("reading_time_minutes", 2)

        today = datetime.utcnow().date()
        today_str = today.isoformat()

        # ── Atomic gamification update ─────────────────────────────────────────
        # First: fetch ONLY the fields we need to compute streak logic.
        # We use a projection to avoid loading the whole user document.
        user_snap = await users_coll.find_one(
            {"id": current_user.id},
            {"gamification.last_read_date": 1, "gamification.streak": 1}
        )

        g_snap = (user_snap or {}).get("gamification", {})
        last_read_raw = g_snap.get("last_read_date")
        current_streak = g_snap.get("streak", 0)

        # Determine streak delta and today's read count reset atomically
        if last_read_raw:
            try:
                last_read_date = (
                    date.fromisoformat(last_read_raw)
                    if isinstance(last_read_raw, str)
                    else last_read_raw
                )
            except (ValueError, TypeError):
                last_read_date = None

            if last_read_date and last_read_date == today:
                # Same day — just increment today counter, streak unchanged
                streak_update = {"$inc": {"gamification.articles_read_today": 1}}
            elif last_read_date and (today - last_read_date).days == 1:
                # Consecutive day — extend streak
                streak_update = {
                    "$inc": {"gamification.streak": 1},
                    "$set": {"gamification.articles_read_today": 1},
                }
            else:
                # Streak broken or first ever — reset
                streak_update = {
                    "$set": {
                        "gamification.streak": 1,
                        "gamification.articles_read_today": 1,
                    }
                }
        else:
            streak_update = {
                "$set": {
                    "gamification.streak": 1,
                    "gamification.articles_read_today": 1,
                }
            }

        # Build the full atomic update combining $inc and $set safely
        inc_ops = streak_update.get("$inc", {})
        set_ops = streak_update.get("$set", {})

        inc_ops.update({
            "gamification.total_articles_read": 1,
            "gamification.total_reading_time_minutes": reading_time,
            "gamification.points": 10 + reading_time,
        })
        set_ops.update({
            "gamification.last_read_date": today_str,
            "updated_at": datetime.utcnow().isoformat(),
        })

        atomic_update: dict = {"$inc": inc_ops, "$set": set_ops}

        # Atomically prepend to reading_history (max 100 entries) and deduplicate
        # $pull first removes the article if already present, then $push adds it to front
        await users_coll.update_one(
            {"id": current_user.id},
            {"$pull": {"reading_history": article_id}}
        )
        await users_coll.update_one(
            {"id": current_user.id},
            {
                **atomic_update,
                "$push": {
                    "reading_history": {
                        "$each": [article_id],
                        "$position": 0,
                        "$slice": 100,
                    }
                },
            }
        )

    return ArticleResponse(
        id=str(article["_id"]),
        title=article["title"],
        url=article.get("url") or "",
        image_url=article.get("image_url"),
        summary=article.get("summary"),
        content=article["content"],
        category=article.get("category"),
        tags=article.get("tags", []),
        locations=article.get("locations", []),
        source=article.get("source", "Unknown"),
        country_code=article.get("country_code"),
        sentiment=article.get("sentiment"),
        difficulty_level=article.get("difficulty_level", "medium"),
        reading_time_minutes=article.get("reading_time_minutes", 5),
        is_breaking=article.get("is_breaking", False),
        upvotes=article.get("upvotes", 0),
        downvotes=article.get("downvotes", 0),
        comments_count=article.get("comments_count", 0),
        views=article.get("views", 0),
        summary_source=article.get("summary_source"),
        published_at=article.get("published_at"),
        created_at=article["created_at"],
    )


@router.get("/{article_id}/my-vote")
async def get_my_vote(
    article_id: str,
    current_user: UserResponse = Depends(get_current_user_required)
):
    """Returns the current authenticated user's vote on an article."""
    vote = await get_user_vote_status(article_id, current_user.id)
    return {"vote": vote}  # "up", "down", or null


class BatchVoteRequest(BaseModel):
    article_ids: List[str]


@router.post("/votes/batch")
async def get_votes_batch(
    body: BatchVoteRequest,
    current_user: UserResponse = Depends(get_current_user_required),
) -> Dict[str, Optional[str]]:
    """
    Batch endpoint: return vote status for multiple articles in one call.
    Replaces the N+1 pattern of firing one GET /my-vote per article.

    Strategy:
    1. Build Redis keys for all requested article IDs.
    2. mget all keys in a single round-trip (O(N) but one call).
    3. For any cache misses, query MongoDB once using $in.
    4. Warm the cache for all DB hits.

    Returns: { "<article_id>": "up" | "down" | null, ... }
    """
    ids = body.article_ids[:50]  # cap at 50
    result: Dict[str, Optional[str]] = {aid: None for aid in ids}

    redis_client = get_redis()

    if redis_client:
        # ── Single Redis round-trip ────────────────────────────────────────────
        keys = [f"user_vote:{aid}:{current_user.id}" for aid in ids]
        cached_values = await redis_client.mget(keys)

        misses = []  # article IDs not found in Redis
        for aid, val in zip(ids, cached_values):
            if val is not None:
                result[aid] = None if val == "none" else val
            else:
                misses.append(aid)
    else:
        misses = list(ids)

    if misses:
        # ── Single MongoDB query for all cache misses ─────────────────────────
        from app.db import get_votes_collection, cache_set
        votes_coll = get_votes_collection()
        cursor = votes_coll.find(
            {"article_id": {"$in": misses}, "user_id": current_user.id},
            {"article_id": 1, "vote_type": 1},
        )
        async for doc in cursor:
            aid = doc["article_id"]
            vote_type = doc.get("vote_type")  # "up" | "down" | None
            result[aid] = vote_type
            # Warm the cache
            try:
                await cache_set(
                    f"user_vote:{aid}:{current_user.id}",
                    vote_type or "none",
                    expire_seconds=2592000,
                )
            except Exception:
                pass

    return result


@router.post("/{article_id}/upvote")
async def upvote(article_id: str, current_user: UserResponse = Depends(get_current_user_required)):
    existing_vote = await get_user_vote_status(article_id, current_user.id)
    collection = get_articles_collection()

    try:
        obj_id = ObjectId(article_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Article not found")

    if existing_vote == "up":
        # Toggle off — remove upvote
        await set_user_vote(article_id, current_user.id, None)
        result = await collection.find_one_and_update(
            {"_id": obj_id},
            {"$inc": {"upvotes": -1}},
            return_document=True
        )
        if not result:
            raise HTTPException(status_code=404, detail="Article not found")
        await _track_user_interaction(current_user.id, article_id, "upvote_removed")
        return {"action": "removed", "upvotes": result.get("upvotes", 0), "downvotes": result.get("downvotes", 0)}

    elif existing_vote == "down":
        # Switch from downvote to upvote
        await set_user_vote(article_id, current_user.id, "up")
        result = await collection.find_one_and_update(
            {"_id": obj_id},
            {"$inc": {"upvotes": 1, "downvotes": -1}},
            return_document=True
        )
        if not result:
            raise HTTPException(status_code=404, detail="Article not found")
        await _track_user_interaction(current_user.id, article_id, "upvote")
        return {"action": "switched", "upvotes": result.get("upvotes", 0), "downvotes": result.get("downvotes", 0)}

    else:
        # Fresh upvote
        await set_user_vote(article_id, current_user.id, "up")
        result = await collection.find_one_and_update(
            {"_id": obj_id},
            {"$inc": {"upvotes": 1}},
            return_document=True
        )
        if not result:
            raise HTTPException(status_code=404, detail="Article not found")
        await _track_user_interaction(current_user.id, article_id, "upvote")
        return {"action": "added", "upvotes": result.get("upvotes", 0), "downvotes": result.get("downvotes", 0)}


@router.post("/{article_id}/downvote")
async def downvote(article_id: str, current_user: UserResponse = Depends(get_current_user_required)):
    existing_vote = await get_user_vote_status(article_id, current_user.id)
    collection = get_articles_collection()

    try:
        obj_id = ObjectId(article_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Article not found")

    if existing_vote == "down":
        # Toggle off — remove downvote
        await set_user_vote(article_id, current_user.id, None)
        result = await collection.find_one_and_update(
            {"_id": obj_id},
            {"$inc": {"downvotes": -1}},
            return_document=True
        )
        if not result:
            raise HTTPException(status_code=404, detail="Article not found")
        await _track_user_interaction(current_user.id, article_id, "downvote_removed")
        return {"action": "removed", "upvotes": result.get("upvotes", 0), "downvotes": result.get("downvotes", 0)}

    elif existing_vote == "up":
        # Switch from upvote to downvote
        await set_user_vote(article_id, current_user.id, "down")
        result = await collection.find_one_and_update(
            {"_id": obj_id},
            {"$inc": {"downvotes": 1, "upvotes": -1}},
            return_document=True
        )
        if not result:
            raise HTTPException(status_code=404, detail="Article not found")
        await _track_user_interaction(current_user.id, article_id, "downvote")
        return {"action": "switched", "upvotes": result.get("upvotes", 0), "downvotes": result.get("downvotes", 0)}

    else:
        # Fresh downvote
        await set_user_vote(article_id, current_user.id, "down")
        result = await collection.find_one_and_update(
            {"_id": obj_id},
            {"$inc": {"downvotes": 1}},
            return_document=True
        )
        if not result:
            raise HTTPException(status_code=404, detail="Article not found")
        await _track_user_interaction(current_user.id, article_id, "downvote")
        return {"action": "added", "upvotes": result.get("upvotes", 0), "downvotes": result.get("downvotes", 0)}


@router.post("/{article_id}/share")
async def share_article(article_id: str, current_user: UserResponse = Depends(get_current_user_required)):
    await _track_user_interaction(current_user.id, article_id, "share")
    return {"message": "Share tracked"}


@router.post("/{article_id}/view")
async def record_view(
    article_id: str,
    x_forwarded_for: Optional[str] = Header(None),
    current_user: Optional[UserResponse] = Depends(get_current_user_optional),
):
    ip = x_forwarded_for.split(",")[0].strip() if x_forwarded_for else "unknown"
    user_id = current_user.id if current_user else None

    success = await record_view_in_redis(article_id, ip, user_id=user_id)
    return {"message": "View recorded" if success else "View debounced"}
