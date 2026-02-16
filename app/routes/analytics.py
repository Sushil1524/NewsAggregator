from datetime import datetime, timedelta
from typing import List
from collections import defaultdict
from fastapi import APIRouter, Depends, Query
from app.dependencies import get_current_user_required
from app.models.user import UserResponse
from app.models.analytics import TrendingArticle, CategoryStats, DailyCount, DashboardStats, UserReadingInsights
from app.db import get_articles_collection, get_user_interactions_collection, cache_get, cache_set
import json

router = APIRouter()

async def get_trending_articles(limit: int) -> List[TrendingArticle]:
    cache_key = f"trending:{limit}"
    cached = await cache_get(cache_key)
    if cached:
        return [TrendingArticle(**a) for a in json.loads(cached)]
    
    collection = get_articles_collection()
    yesterday = datetime.utcnow() - timedelta(hours=24)
    
    pipeline = [
        {"$match": {"created_at": {"$gte": yesterday}}},
        {"$addFields": {
            "trending_score": {
                "$add": [
                    "$views",
                    {"$multiply": ["$upvotes", 3]},
                    {"$multiply": ["$comments_count", 5]}
                ]
            }
        }},
        {"$sort": {"trending_score": -1}},
        {"$limit": limit},
        {"$project": {
            "article_id": {"$toString": "$_id"},
            "title": 1,
            "views": 1,
            "upvotes": 1,
            "comments_count": 1,
            "trending_score": 1
        }}
    ]
    
    cursor = collection.aggregate(pipeline)
    results = await cursor.to_list(length=limit)
    
    trending = [
        TrendingArticle(
            article_id=r["article_id"],
            title=r["title"],
            views=r.get("views", 0),
            upvotes=r.get("upvotes", 0),
            comments_count=r.get("comments_count", 0),
            trending_score=r.get("trending_score", 0),
        )
        for r in results
    ]
    
    await cache_set(cache_key, json.dumps([t.model_dump() for t in trending]), 300)
    
    return trending

async def _get_top_categories(limit: int) -> List[CategoryStats]:
    collection = get_articles_collection()
    pipeline = [
        {"$group": {
            "_id": "$category",
            "article_count": {"$sum": 1},
            "total_views": {"$sum": "$views"},
            "avg_upvotes": {"$avg": "$upvotes"}
        }},
        {"$sort": {"article_count": -1}},
        {"$limit": limit}
    ]
    
    cursor = collection.aggregate(pipeline)
    results = await cursor.to_list(length=limit)
    
    return [
        CategoryStats(
            category=r["_id"] or "General",
            article_count=r["article_count"],
            total_views=r.get("total_views", 0),
            avg_upvotes=r.get("avg_upvotes", 0),
        )
        for r in results
    ]

async def _get_daily_counts(days: int) -> List[DailyCount]:
    collection = get_articles_collection()
    start_date = datetime.utcnow() - timedelta(days=days)
    pipeline = [
        {"$match": {"created_at": {"$gte": start_date}}},
        {"$group": {
            "_id": {
                "$dateToString": {"format": "%Y-%m-%d", "date": "$created_at"}
            },
            "count": {"$sum": 1}
        }},
        {"$sort": {"_id": 1}}
    ]
    
    cursor = collection.aggregate(pipeline)
    results = await cursor.to_list(length=days)
    return [DailyCount(date=r["_id"], count=r["count"]) for r in results]

async def _get_user_reading_insights(user_id: str) -> UserReadingInsights:
    collection = get_user_interactions_collection()
    cursor = collection.find({"user_id": user_id})
    interactions = await cursor.to_list(length=1000)
    
    if not interactions:
        return UserReadingInsights(
            total_articles_read=0,
            total_reading_time_minutes=0,
            favorite_categories=[],
            avg_reading_time_per_article=0,
            reading_streak_days=0,
            articles_read_this_week=0,
        )
    total_read = len([i for i in interactions if i["interaction_type"] in ["view", "read"]])
    total_time = sum(i.get("reading_duration_seconds", 0) or 0 for i in interactions) // 60
    articles_collection = get_articles_collection()
    article_ids = list(set(i["article_id"] for i in interactions))
    category_counts = defaultdict(int)
    for aid in article_ids[:100]: 
        try:
            from bson import ObjectId
            article = await articles_collection.find_one({"_id": ObjectId(aid)})
            if article and article.get("category"):
                category_counts[article["category"]] += 1
        except Exception:
            pass
    
    favorite_categories = sorted(category_counts, key=category_counts.get, reverse=True)[:3]
    
    week_ago = datetime.utcnow() - timedelta(days=7)
    this_week = len([i for i in interactions if i["timestamp"] >= week_ago])
    
    return UserReadingInsights(total_articles_read=total_read, total_reading_time_minutes=total_time,
        favorite_categories=favorite_categories,
        avg_reading_time_per_article=total_time / total_read if total_read > 0 else 0,
                               reading_streak_days=0, articles_read_this_week=this_week)

async def _get_dashboard_stats(user_id: str, daily_target: int) -> DashboardStats:
    insights = await _get_user_reading_insights(user_id)
    goal_progress = min(100, (insights.articles_read_this_week / (daily_target * 7)) * 100)
    top_categories = await _get_top_categories(10)
    all_categories = [c.category for c in top_categories]
    recommended = [c for c in all_categories if c not in insights.favorite_categories][:3]
    
    return DashboardStats(
        user_insights=insights,
        recommended_categories=recommended,
        reading_goal_progress=goal_progress,
    )

@router.get("/trending", response_model=List[TrendingArticle])
async def trending(limit: int = Query(10, ge=1, le=50)):
    return await get_trending_articles(limit)

@router.get("/top-categories", response_model=List[CategoryStats])
async def top_categories(limit: int = Query(5, ge=1, le=20)):
    return await _get_top_categories(limit)

@router.get("/daily-counts", response_model=List[DailyCount])
async def daily_counts(days: int = Query(7, ge=1, le=30)):
    return await _get_daily_counts(days)

@router.get("/reading-insights", response_model=UserReadingInsights)
async def reading_insights(current_user: UserResponse = Depends(get_current_user_required)):
    return await _get_user_reading_insights(current_user.id)

@router.get("/dashboard", response_model=DashboardStats)
async def dashboard(current_user: UserResponse = Depends(get_current_user_required)):
    return await _get_dashboard_stats(current_user.id, current_user.daily_practice_target)
