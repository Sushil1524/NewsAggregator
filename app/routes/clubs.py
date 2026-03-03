from typing import List, Optional
from datetime import datetime
from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, status, Query
from app.dependencies import get_current_user_required, get_current_user_optional
from app.models.user import UserResponse
from app.models.club import (
    ClubResponse, ClubPostCreate, ClubPostResponse,
    ClubCommentCreate, ClubCommentResponse, SharedArticleEmbed
)
from app.db import (
    get_clubs_collection, get_club_posts_collection,
    get_club_comments_collection, get_users_collection,
    get_articles_collection
)

router = APIRouter()

@router.get("/", response_model=List[ClubResponse])
async def list_clubs():
    clubs = get_clubs_collection()
    cursor = clubs.find().sort("name", 1)
    results = await cursor.to_list(length=100)
    return [
        ClubResponse(id=str(c["_id"]), **{k: c[k] for k in c if k != "_id"})
        for c in results
    ]

@router.get("/{slug}", response_model=ClubResponse)
async def get_club(slug: str):
    clubs = get_clubs_collection()
    c = await clubs.find_one({"slug": slug})
    if not c:
        raise HTTPException(status_code=404, detail="Club not found")
    return ClubResponse(id=str(c["_id"]), **{k: c[k] for k in c if k != "_id"})

@router.post("/{slug}/join")
async def join_club(slug: str, current_user: UserResponse = Depends(get_current_user_required)):
    clubs = get_clubs_collection()
    users = get_users_collection()

    club = await clubs.find_one({"slug": slug})
    if not club:
        raise HTTPException(status_code=404, detail="Club not found")

    user_doc = await users.find_one({"email": current_user.email})
    if slug in (user_doc.get("joined_clubs") or []):
        raise HTTPException(status_code=400, detail="Already a member")

    await users.update_one(
        {"email": current_user.email},
        {"$addToSet": {"joined_clubs": slug}}
    )
    await clubs.update_one({"slug": slug}, {"$inc": {"member_count": 1}})
    return {"message": f"Joined {club['name']}"}

@router.post("/{slug}/leave")
async def leave_club(slug: str, current_user: UserResponse = Depends(get_current_user_required)):
    clubs = get_clubs_collection()
    users = get_users_collection()

    club = await clubs.find_one({"slug": slug})
    if not club:
        raise HTTPException(status_code=404, detail="Club not found")

    user_doc = await users.find_one({"email": current_user.email})
    if slug not in (user_doc.get("joined_clubs") or []):
        raise HTTPException(status_code=400, detail="Not a member")

    await users.update_one(
        {"email": current_user.email},
        {"$pull": {"joined_clubs": slug}}
    )
    await clubs.update_one({"slug": slug}, {"$inc": {"member_count": -1}})
    return {"message": f"Left {club['name']}"}

@router.get("/{slug}/members")
async def list_members(slug: str, limit: int = Query(50, le=100)):
    users = get_users_collection()
    cursor = users.find(
        {"joined_clubs": slug},
        {"username": 1, "full_name": 1, "created_at": 1}
    ).limit(limit)
    results = await cursor.to_list(length=limit)
    return [
        {"id": str(u["_id"]), "username": u["username"], "full_name": u.get("full_name")}
        for u in results
    ]


@router.get("/{slug}/posts", response_model=List[ClubPostResponse])
async def list_posts(
    slug: str,
    limit: int = Query(20, le=50),
    cursor: Optional[str] = None
):
    posts = get_club_posts_collection()
    query = {"club_slug": slug}
    if cursor:
        try:
            query["created_at"] = {"$lt": datetime.fromisoformat(cursor)}
        except ValueError:
            pass

    docs = await posts.find(query).sort("created_at", -1).to_list(length=limit)
    return [
        ClubPostResponse(
            id=str(d["_id"]),
            club_slug=d["club_slug"],
            author_username=d["author_username"],
            content=d["content"],
            shared_article=d.get("shared_article"),
            upvotes=d.get("upvotes", 0),
            downvotes=d.get("downvotes", 0),
            comments_count=d.get("comments_count", 0),
            created_at=d["created_at"],
        )
        for d in docs
    ]

@router.post("/{slug}/posts", response_model=ClubPostResponse, status_code=status.HTTP_201_CREATED)
async def create_post(
    slug: str,
    post_data: ClubPostCreate,
    current_user: UserResponse = Depends(get_current_user_required)
):
    clubs = get_clubs_collection()
    club = await clubs.find_one({"slug": slug})
    if not club:
        raise HTTPException(status_code=404, detail="Club not found")

    users = get_users_collection()
    user_doc = await users.find_one({"email": current_user.email})
    if slug not in (user_doc.get("joined_clubs") or []):
        raise HTTPException(status_code=403, detail="Join the club first to post")

    shared_article = None
    if post_data.shared_article_id:
        articles = get_articles_collection()
        try:
            article = await articles.find_one({"_id": ObjectId(post_data.shared_article_id)})
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid article ID")
        if article:
            shared_article = {
                "article_id": str(article["_id"]),
                "title": article.get("title", ""),
                "url": article.get("url"),
                "image_url": article.get("image_url"),
                "category": article.get("category"),
            }

    now = datetime.utcnow()
    post_doc = {
        "club_slug": slug,
        "author_username": current_user.username,
        "content": post_data.content,
        "shared_article": shared_article,
        "upvotes": 0,
        "downvotes": 0,
        "comments_count": 0,
        "created_at": now,
    }

    result = await get_club_posts_collection().insert_one(post_doc)
    return ClubPostResponse(
        id=str(result.inserted_id),
        club_slug=slug,
        author_username=current_user.username,
        content=post_data.content,
        shared_article=SharedArticleEmbed(**shared_article) if shared_article else None,
        upvotes=0,
        downvotes=0,
        comments_count=0,
        created_at=now,
    )

@router.post("/{slug}/posts/{post_id}/upvote")
async def upvote_post(slug: str, post_id: str, current_user: UserResponse = Depends(get_current_user_required)):
    posts = get_club_posts_collection()
    try:
        result = await posts.update_one({"_id": ObjectId(post_id), "club_slug": slug}, {"$inc": {"upvotes": 1}})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid post ID")
    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="Post not found")
    return {"message": "Upvoted"}

@router.post("/{slug}/posts/{post_id}/downvote")
async def downvote_post(slug: str, post_id: str, current_user: UserResponse = Depends(get_current_user_required)):
    posts = get_club_posts_collection()
    try:
        result = await posts.update_one({"_id": ObjectId(post_id), "club_slug": slug}, {"$inc": {"downvotes": 1}})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid post ID")
    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="Post not found")
    return {"message": "Downvoted"}


@router.get("/{slug}/posts/{post_id}/comments", response_model=List[ClubCommentResponse])
async def list_post_comments(slug: str, post_id: str):
    comments = get_club_comments_collection()
    docs = await comments.find({"post_id": post_id}).sort("created_at", 1).to_list(length=500)
    return [
        ClubCommentResponse(
            id=str(c["_id"]),
            post_id=c["post_id"],
            author_username=c["author_username"],
            content=c["content"],
            parent_id=c.get("parent_id"),
            upvotes=c.get("upvotes", 0),
            downvotes=c.get("downvotes", 0),
            created_at=c["created_at"],
        )
        for c in docs
    ]

@router.post("/{slug}/posts/{post_id}/comments", response_model=ClubCommentResponse, status_code=status.HTTP_201_CREATED)
async def create_post_comment(
    slug: str, post_id: str,
    comment_data: ClubCommentCreate,
    current_user: UserResponse = Depends(get_current_user_required)
):
    posts = get_club_posts_collection()
    try:
        post = await posts.find_one({"_id": ObjectId(post_id), "club_slug": slug})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid post ID")
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    if comment_data.parent_id:
        comments_coll = get_club_comments_collection()
        try:
            parent = await comments_coll.find_one({"_id": ObjectId(comment_data.parent_id)})
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid parent ID")
        if not parent:
            raise HTTPException(status_code=404, detail="Parent comment not found")

    now = datetime.utcnow()
    comment_doc = {
        "post_id": post_id,
        "author_username": current_user.username,
        "content": comment_data.content,
        "parent_id": comment_data.parent_id,
        "upvotes": 0,
        "downvotes": 0,
        "created_at": now,
    }

    result = await get_club_comments_collection().insert_one(comment_doc)
    await posts.update_one({"_id": ObjectId(post_id)}, {"$inc": {"comments_count": 1}})

    return ClubCommentResponse(
        id=str(result.inserted_id),
        post_id=post_id,
        author_username=current_user.username,
        content=comment_data.content,
        parent_id=comment_data.parent_id,
        upvotes=0,
        downvotes=0,
        created_at=now,
    )
