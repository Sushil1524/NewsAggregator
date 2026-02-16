from datetime import datetime, date
from enum import Enum
from typing import Optional, List, Dict
from pydantic import BaseModel, EmailStr, Field

class UserRole(str, Enum):
    USER = "user"
    ADMIN = "admin"

class VocabProficiency(str, Enum):
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"

class VocabCard(BaseModel):
    word: str
    meaning: Optional[str] = None
    example: Optional[str] = None
    level: int = Field(default=1, ge=1, le=5)
    added_at: datetime = Field(default_factory=datetime.utcnow)

class Gamification(BaseModel):
    points: int = 0
    streak: int = 0
    articles_read_today: int = 0
    total_articles_read: int = 0
    total_reading_time_minutes: int = 0
    last_read_date: Optional[date] = None
    badges: List[str] = Field(default_factory=list)

class NotificationSettings(BaseModel):
    email_digest: bool = True
    breaking_news: bool = True
    weekly_summary: bool = True

class UserBase(BaseModel):
    email: EmailStr
    username: str = Field(..., min_length=3, max_length=50)
    full_name: Optional[str] = None
    dob: Optional[date] = None

class UserCreate(UserBase):
    password: str = Field(..., min_length=8)
    vocab_proficiency: str = "intermediate"
    daily_practice_target: int = 10

class UserInDB(UserBase):
    id: str
    password_hash: str
    role: str = "user"
    vocab_proficiency: str = "intermediate"
    daily_practice_target: int = 10
    news_preferences: Dict[str, bool] = {}
    preferred_languages: List[str] = ["en"]
    notification_settings: NotificationSettings = NotificationSettings()
    gamification: Gamification = Gamification()
    vocab_cards: List[VocabCard] = []
    bookmarks: List[str] = []
    reading_history: List[str] = []
    created_at: datetime
    updated_at: datetime
    last_login_at: Optional[datetime] = None

class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    dob: Optional[date] = None
    vocab_proficiency: Optional[str] = None
    daily_practice_target: Optional[int] = None
    news_preferences: Optional[Dict[str, bool]] = None
    preferred_languages: Optional[List[str]] = None
    notification_settings: Optional[NotificationSettings] = None

class UserResponse(BaseModel):
    id: str
    email: EmailStr
    username: str
    full_name: Optional[str] = None
    dob: Optional[date] = None
    role: str = "user"
    vocab_proficiency: str = "intermediate"
    daily_practice_target: int = 10
    news_preferences: Dict[str, bool] = {}
    preferred_languages: List[str] = ["en"]
    gamification: Gamification = Gamification()
    bookmarks: List[str] = []
    created_at: datetime

