from datetime import datetime, timedelta
from typing import List, Optional
from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, status, Header, Query
from app.dependencies import get_current_user_required, get_current_user_optional
from app.models.user import UserResponse
from app.models.article import ArticleResponse, ArticleListItem
from app.db import get_articles_collection, get_user_interactions_collection, get_users_collection
from app.db import increment_view_count

router = APIRouter()

async def _get_articles_helper(
    cursor: Optional[datetime],
    limit: int,
    category: Optional[str],
    tag: Optional[str],
    sort_by: str,
    date_filter: Optional[str]
) -> List[ArticleListItem]:
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
    
    if date_filter == "today":
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        query["created_at"] = {"$gte": today_start}
    elif date_filter == "last_hour":
        hour_ago = datetime.utcnow() - timedelta(hours=1)
        query["created_at"] = {"$gte": hour_ago}

    if sort_by == "top":
        sort = [("upvotes", -1), ("created_at", -1)]
    elif sort_by == "old":
        sort = [("created_at", 1)]
    else:  
        sort = [("created_at", -1)]
    
    cursor_result = collection.find(query).sort(sort).limit(limit)
    articles = await cursor_result.to_list(length=limit)
    
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
            source=article.get("source", "Unknown"),
            reading_time_minutes=article.get("reading_time_minutes", 5),
            is_breaking=article.get("is_breaking", False),
            upvotes=article.get("upvotes", 0),
            downvotes=article.get("downvotes", 0),
            views=article.get("views", 0),
            created_at=article["created_at"],
        )
        for article in articles
    ]

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


@router.get("/", response_model=List[ArticleListItem])
async def list_articles(
    cursor: Optional[datetime] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    category: Optional[str] = Query(None),
    tag: Optional[str] = Query(None),
    sort_by: str = Query("new", pattern="^(new|old|top)$"),
    date_filter: Optional[str] = Query(None, pattern="^(today|last_hour)$"),
):
    return await _get_articles_helper(cursor, limit, category, tag, sort_by, date_filter)

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
            source=article.get("source", "Unknown"),
            reading_time_minutes=article.get("reading_time_minutes", 5),
            is_breaking=article.get("is_breaking", False),
            upvotes=article.get("upvotes", 0),
            downvotes=article.get("downvotes", 0),
            views=article.get("views", 0),
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
        
        users_coll = get_users_collection()
        user_data = await users_coll.find_one({"id": current_user.id})
        
        if user_data:
            history = user_data.get("reading_history", [])
            if article_id in history:
                history.remove(article_id)
            history.insert(0, article_id)
            
            reading_time = x_reading_duration // 60 if x_reading_duration else article.get("reading_time_minutes", 5)
            gamification = user_data.get("gamification", {})
            today = datetime.utcnow().date()
            last_read = gamification.get("last_read_date")
            
            gamification["total_articles_read"] = gamification.get("total_articles_read", 0) + 1
            gamification["total_reading_time_minutes"] = gamification.get("total_reading_time_minutes", 0) + reading_time
            gamification["points"] = gamification.get("points", 0) + 10 + reading_time
            
            if last_read:
                from datetime import date
                last_read_date = date.fromisoformat(last_read) if isinstance(last_read, str) else last_read
                if last_read_date == today:
                    gamification["articles_read_today"] = gamification.get("articles_read_today", 0) + 1
                elif (today - last_read_date).days == 1:
                    gamification["streak"] = gamification.get("streak", 0) + 1
                    gamification["articles_read_today"] = 1
                else:
                    gamification["streak"] = 1
                    gamification["articles_read_today"] = 1
            else:
                gamification["streak"] = 1
                gamification["articles_read_today"] = 1
            
            gamification["last_read_date"] = today.isoformat()
            
            await users_coll.update_one(
                {"id": current_user.id},
                {"$set": {
                    "reading_history": history[:100],
                    "gamification": gamification,
                    "updated_at": datetime.utcnow().isoformat()
                }}
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
        source=article.get("source", "Unknown"),
        sentiment=article.get("sentiment"),
        difficulty_level=article.get("difficulty_level", "medium"),
        reading_time_minutes=article.get("reading_time_minutes", 5),
        is_breaking=article.get("is_breaking", False),
        upvotes=article.get("upvotes", 0),
        downvotes=article.get("downvotes", 0),
        comments_count=article.get("comments_count", 0),
        views=article.get("views", 0),
        published_at=article.get("published_at"),
        created_at=article["created_at"],
    )

@router.post("/{article_id}/upvote")
async def upvote(article_id: str, current_user: UserResponse = Depends(get_current_user_required)):
    collection = get_articles_collection()
    result = await collection.update_one(
        {"_id": ObjectId(article_id)},
        {"$inc": {"upvotes": 1}}
    )
    if result.modified_count == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Article not found")
        
    await _track_user_interaction(current_user.id, article_id, "upvote")
    return {"message": "Upvoted successfully"}

@router.post("/{article_id}/downvote")
async def downvote(article_id: str, current_user: UserResponse = Depends(get_current_user_required)):
    collection = get_articles_collection()
    result = await collection.update_one(
        {"_id": ObjectId(article_id)},
        {"$inc": {"downvotes": 1}}
    )
    if result.modified_count == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Article not found")
        
    await _track_user_interaction(current_user.id, article_id, "downvote")
    return {"message": "Downvoted successfully"}

@router.post("/{article_id}/share")
async def share_article(article_id: str, current_user: UserResponse = Depends(get_current_user_required)):
    await _track_user_interaction(current_user.id, article_id, "share")
    return {"message": "Share tracked"}

@router.post("/{article_id}/view")
async def record_view(article_id: str, x_forwarded_for: Optional[str] = Header(None)):
    from app.db import record_view_in_redis
    ip = x_forwarded_for.split(",")[0] if x_forwarded_for else "unknown"
    
    success = await record_view_in_redis(article_id, ip)
    return {"message": "View recorded" if success else "View debounced"}
