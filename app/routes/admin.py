from fastapi import APIRouter, Depends, Query
from typing import Optional
from app.dependencies import require_admin
from app.models.user import UserResponse
from app.services.news_pipeline import run_pipeline, refresh_breaking_news
from app.db import (
    get_articles_collection, get_comments_collection,
    get_raw_articles_collection, get_users_collection,
    get_pipeline_runs_collection,
)

router = APIRouter()


@router.post("/refresh")
async def refresh_news(admin_user: UserResponse = Depends(require_admin)):
    stats = await run_pipeline(max_articles=50)
    return {"message": "News pipeline completed", "stats": stats}


@router.post("/refresh-breaking")
async def refresh_breaking(admin_user: UserResponse = Depends(require_admin)):
    await refresh_breaking_news()
    return {"message": "Breaking news updated"}


@router.get("/stats")
async def get_admin_stats(admin_user: UserResponse = Depends(require_admin)):
    articles = get_articles_collection()
    comments = get_comments_collection()
    raw_articles = get_raw_articles_collection()
    users_coll = get_users_collection()

    article_count = await articles.count_documents({})
    comment_count = await comments.count_documents({})
    raw_count = await raw_articles.count_documents({})
    unprocessed_count = await raw_articles.count_documents({"is_processed": False})
    user_count = await users_coll.count_documents({})

    return {
        "articles": article_count,
        "comments": comment_count,
        "raw_articles": raw_count,
        "unprocessed_articles": unprocessed_count,
        "users": user_count,
    }


@router.get("/pipeline-history")
async def get_pipeline_history(
    limit: int = Query(20, ge=1, le=100),
    admin_user: UserResponse = Depends(require_admin),
):
    """
    Returns the N most recent pipeline run records, newest first.
    Each record includes: timing, article counts, summary source breakdown,
    category breakdown, and any feeds that were failing at run time.
    """
    runs_coll = get_pipeline_runs_collection()
    cursor = runs_coll.find({}, {"_id": 0}).sort("started_at", -1).limit(limit)
    runs = await cursor.to_list(length=limit)

    # Convert datetimes to ISO strings for JSON serialisation
    for run in runs:
        for field in ("started_at", "finished_at"):
            if field in run and hasattr(run[field], "isoformat"):
                run[field] = run[field].isoformat() + "Z"

    return {
        "total_runs_returned": len(runs),
        "runs": runs,
    }


@router.delete("/pipeline-history")
async def clear_pipeline_history(admin_user: UserResponse = Depends(require_admin)):
    """Delete all pipeline run history records (admin maintenance)."""
    runs_coll = get_pipeline_runs_collection()
    result = await runs_coll.delete_many({})
    return {"deleted": result.deleted_count}
