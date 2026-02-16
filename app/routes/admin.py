from fastapi import APIRouter, Depends
from app.dependencies import require_admin
from app.models.user import UserResponse
from app.services.news_pipeline import run_news_pipeline, refresh_breaking_news
from app.db import get_articles_collection, get_comments_collection, get_raw_articles_collection
from app.db import get_supabase

router = APIRouter()

@router.post("/refresh")
async def refresh_news(admin_user: UserResponse = Depends(require_admin)):
    stats = await run_news_pipeline(max_articles=50)
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
    supabase = get_supabase()
    
    article_count = await articles.count_documents({})
    comment_count = await comments.count_documents({})
    raw_count = await raw_articles.count_documents({})
    unprocessed_count = await raw_articles.count_documents({"is_processed": False})
    users = supabase.table("users").select("id", count="exact").execute()
    user_count = users.count if users else 0
    
    return {"articles": article_count, "comments": comment_count, "raw_articles": raw_count,"unprocessed_articles": unprocessed_count, "users": user_count}
