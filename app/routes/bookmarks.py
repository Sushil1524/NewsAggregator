from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from bson import ObjectId
from app.dependencies import get_current_user_required
from app.models.user import UserResponse
from app.models.article import ArticleListItem
from app.db import get_articles_collection, get_users_collection

router = APIRouter()

@router.post("/{article_id}", status_code=status.HTTP_201_CREATED)
async def add_bookmark(article_id: str, current_user: UserResponse = Depends(get_current_user_required)):
    articles = get_articles_collection()
    users_coll = get_users_collection()
    
    try:
        article = await articles.find_one({"_id": ObjectId(article_id)})
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid article ID")
    
    if not article:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Article not found")
    
    result = await users_coll.update_one(
        {"id": current_user.id},
        {"$addToSet": {"bookmarks": article_id}}
    )
    
    if result.matched_count == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        
    return {"message": "Bookmark added"}

@router.delete("/{article_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_bookmark(article_id: str, current_user: UserResponse = Depends(get_current_user_required)):
    users_coll = get_users_collection()
    
    result = await users_coll.update_one(
        {"id": current_user.id},
        {"$pull": {"bookmarks": article_id}}
    )
    
    if result.matched_count == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

@router.get("/", response_model=List[ArticleListItem])
async def get_bookmarks(current_user: UserResponse = Depends(get_current_user_required)):
    articles_collection = get_articles_collection()
    users_coll = get_users_collection()
    
    user = await users_coll.find_one({"id": current_user.id})
    if not user:
        return []
        
    bookmark_ids = user.get("bookmarks", [])
    
    if not bookmark_ids:
        return []
    
    articles = []
    for article_id in bookmark_ids:
        try:
            article = await articles_collection.find_one({"_id": ObjectId(article_id)})
            if article:
                articles.append(ArticleListItem(
                    id=str(article["_id"]), title=article["title"], url=article["url"],
                    summary=article.get("summary"), category=article.get("category"),
                    tags=article.get("tags", []), source=article.get("source", "Unknown"),
                    reading_time_minutes=article.get("reading_time_minutes", 5),
                    is_breaking=article.get("is_breaking", False), upvotes=article.get("upvotes", 0),
                    downvotes=article.get("downvotes", 0), views=article.get("views", 0),
                    created_at=article["created_at"]))
        except Exception:
            continue
    return articles
