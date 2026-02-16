from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field

class CommentCreate(BaseModel):
    article_id: str
    content: str = Field(..., min_length=1, max_length=2000)
    parent_id: Optional[str] = None

class CommentUpdate(BaseModel):
    content: str = Field(..., min_length=1, max_length=2000)

class CommentResponse(BaseModel):
    id: str
    article_id: str
    author_username: str
    content: str
    parent_id: Optional[str] = None
    upvotes: int = 0
    downvotes: int = 0
    is_edited: bool = False
    created_at: datetime
