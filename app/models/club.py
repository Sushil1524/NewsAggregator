from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field

class ClubResponse(BaseModel):
    id: str
    slug: str
    name: str
    description: str
    icon: str = "📰"
    banner_gradient: str = "from-indigo-500 to-purple-700"
    member_count: int = 0
    created_at: datetime

class SharedArticleEmbed(BaseModel):
    article_id: str
    title: str
    url: Optional[str] = None
    image_url: Optional[str] = None
    category: Optional[str] = None

class ClubPostCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=5000)
    shared_article_id: Optional[str] = None

class ClubPostResponse(BaseModel):
    id: str
    club_slug: str
    author_username: str
    content: str
    shared_article: Optional[SharedArticleEmbed] = None
    upvotes: int = 0
    downvotes: int = 0
    comments_count: int = 0
    created_at: datetime

class ClubCommentCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=2000)
    parent_id: Optional[str] = None

class ClubCommentResponse(BaseModel):
    id: str
    post_id: str
    author_username: str
    content: str
    parent_id: Optional[str] = None
    upvotes: int = 0
    downvotes: int = 0
    created_at: datetime
