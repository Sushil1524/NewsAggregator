from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel
from enum import Enum

class ArticleCategory(str, Enum):
    TECHNOLOGY = "Technology"
    BUSINESS = "Business"
    POLITICS = "Politics"
    SPORTS = "Sports"
    SCIENCE = "Science"
    HEALTH = "Health"
    ENTERTAINMENT = "Entertainment"
    INDIA = "India"
    WORLD = "World"
    ENVIRONMENT = "Environment"
    OTHER = "Other"

class RawArticle(BaseModel):
    title: str
    url: str
    image_url: Optional[str] = None
    summary: Optional[str] = None
    content: str
    source: str
    published_at: Optional[datetime] = None
    tags: List[str] = []
    locations: List[str] = []

class ArticleDB(BaseModel):
    title: str
    url: str
    image_url: Optional[str] = None
    summary: Optional[str] = None
    content: str
    category: Optional[str] = None
    tags: List[str] = []
    locations: List[str] = []
    source: str
    source_reliability: float = 0.8
    sentiment: Optional[str] = None
    difficulty_level: str = "medium"
    reading_time_minutes: int = 5
    is_breaking: bool = False
    upvotes: int = 0
    downvotes: int = 0
    comments_count: int = 0
    views: int = 0
    shares: int = 0
    related_articles: List[str] = []
    published_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

class ArticleListItem(BaseModel):
    id: str
    title: str
    url: str
    image_url: Optional[str] = None
    summary: Optional[str] = None
    category: Optional[str] = None
    sentiment: Optional[str] = None
    tags: List[str] = []
    locations: List[str] = []
    source: str
    reading_time_minutes: int = 5
    is_breaking: bool = False
    upvotes: int = 0
    downvotes: int = 0
    views: int = 0
    created_at: datetime

class ArticleResponse(BaseModel):
    id: str
    title: str
    url: str
    image_url: Optional[str] = None
    summary: Optional[str] = None
    content: str
    category: Optional[str] = None
    tags: List[str] = []
    locations: List[str] = []
    source: str
    sentiment: Optional[str] = None
    difficulty_level: str = "medium"
    reading_time_minutes: int = 5
    is_breaking: bool = False
    upvotes: int = 0
    downvotes: int = 0
    comments_count: int = 0
    views: int = 0
    published_at: Optional[datetime] = None
    created_at: datetime
