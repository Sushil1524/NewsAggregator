from typing import List
from pydantic import BaseModel

class TrendingArticle(BaseModel):
    article_id: str
    title: str
    views: int = 0
    upvotes: int = 0
    comments_count: int = 0
    trending_score: float = 0

class CategoryStats(BaseModel):
    category: str
    article_count: int
    total_views: int = 0
    avg_upvotes: float = 0

class DailyCount(BaseModel):
    date: str
    count: int

class UserReadingInsights(BaseModel):
    total_articles_read: int
    total_reading_time_minutes: int
    favorite_categories: List[str]
    avg_reading_time_per_article: float
    reading_streak_days: int
    articles_read_this_week: int

class DashboardStats(BaseModel):
    user_insights: UserReadingInsights
    recommended_categories: List[str]
    reading_goal_progress: float
