from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from bson import ObjectId
from datetime import datetime
from app.dependencies import get_current_user_required
from app.models.user import UserResponse
from app.models.comment import CommentCreate, CommentResponse
from app.db import get_comments_collection, get_articles_collection

router = APIRouter()

@router.post("/", response_model=CommentResponse, status_code=status.HTTP_201_CREATED)
async def create_comment(comment_data: CommentCreate, current_user: UserResponse = Depends(get_current_user_required)):
    comments = get_comments_collection()
    articles = get_articles_collection()
    
    try:
        article = await articles.find_one({"_id": ObjectId(comment_data.article_id)})
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid article ID")
    
    if not article:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Article not found")
    
    if comment_data.parent_id:
        try:
            parent = await comments.find_one({"_id": ObjectId(comment_data.parent_id)})
        except Exception:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid parent ID")
        if not parent:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Parent comment not found")
    
    now = datetime.utcnow()
    comment_doc = {
        "article_id": comment_data.article_id,
        "author_email": current_user.email,
        "author_username": current_user.username,
        "content": comment_data.content,
        "parent_id": comment_data.parent_id,
        "upvotes": 0,
        "downvotes": 0,
        "is_edited": False,
        "created_at": now,
        "updated_at": now,
    }
    
    result = await comments.insert_one(comment_doc)
    await articles.update_one({"_id": ObjectId(comment_data.article_id)}, {"$inc": {"comments_count": 1}})
    
    return CommentResponse(
        id=str(result.inserted_id),
        article_id=comment_data.article_id,
        author_username=current_user.username,
        content=comment_data.content,
        parent_id=comment_data.parent_id,
        upvotes=0,
        downvotes=0,
        is_edited=False,
        created_at=now,
    )

@router.get("/{article_id}", response_model=List[CommentResponse])
async def get_comments(article_id: str):
    comments = get_comments_collection()
    cursor = comments.find({"article_id": article_id}).sort("created_at", 1)
    results = await cursor.to_list(length=500)
    
    return [
        CommentResponse(
            id=str(c["_id"]),
            article_id=c["article_id"],
            author_username=c["author_username"],
            content=c["content"],
            parent_id=c.get("parent_id"),
            upvotes=c.get("upvotes", 0),
            downvotes=c.get("downvotes", 0),
            is_edited=c.get("is_edited", False),
            created_at=c["created_at"],
        )
        for c in results
    ]

@router.delete("/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_comment(comment_id: str, current_user: UserResponse = Depends(get_current_user_required)):
    comments = get_comments_collection()
    articles = get_articles_collection()
    
    try:
        comment = await comments.find_one({"_id": ObjectId(comment_id)})
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid comment ID")
    
    if not comment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comment not found")
    if comment["author_email"] != current_user.email and current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")
    
    await comments.delete_one({"_id": ObjectId(comment_id)})
    await articles.update_one({"_id": ObjectId(comment["article_id"])}, {"$inc": {"comments_count": -1}})

@router.post("/{comment_id}/upvote")
async def upvote_comment(comment_id: str, current_user: UserResponse = Depends(get_current_user_required)):
    comments = get_comments_collection()
    try:
        result = await comments.update_one({"_id": ObjectId(comment_id)}, {"$inc": {"upvotes": 1}})
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid comment ID")
    if result.modified_count == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comment not found")
    return {"message": "Upvoted"}

@router.post("/{comment_id}/downvote")
async def downvote_comment(comment_id: str, current_user: UserResponse = Depends(get_current_user_required)):
    comments = get_comments_collection()
    try:
        result = await comments.update_one({"_id": ObjectId(comment_id)}, {"$inc": {"downvotes": 1}})
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid comment ID")
    if result.modified_count == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comment not found")
    return {"message": "Downvoted"}
