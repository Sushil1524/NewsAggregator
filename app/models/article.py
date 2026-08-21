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
    ENVIRONMENT = "Environment"
    CRIME = "Crime"
    EDUCATION = "Education"
    TRAVEL = "Travel"
    LIFESTYLE = "Lifestyle"
    GENERAL = "General"

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
    country_code: Optional[str] = None

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
    country_code: Optional[str] = None
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
    summary_source: Optional[str] = None   # "ai" | "rss" | "truncated"
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
    country_code: Optional[str] = None
    reading_time_minutes: int = 5
    is_breaking: bool = False
    upvotes: int = 0
    downvotes: int = 0
    views: int = 0
    summary_source: Optional[str] = None
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
    country_code: Optional[str] = None
    sentiment: Optional[str] = None
    difficulty_level: str = "medium"
    reading_time_minutes: int = 5
    is_breaking: bool = False
    upvotes: int = 0
    downvotes: int = 0
    comments_count: int = 0
    views: int = 0
    summary_source: Optional[str] = None
    published_at: Optional[datetime] = None
    created_at: datetime
