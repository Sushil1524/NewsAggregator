import os
from functools import lru_cache
from typing import List
from dotenv import load_dotenv

load_dotenv()

class Settings:
    def __init__(self):
        self.app_name: str = "IntelliNews"
        self.debug: bool = os.getenv("DEBUG", "False").lower() == "true"
        self.secret_key: str = os.getenv("SECRET_KEY", "change-me-in-production")
        self.algorithm: str = os.getenv("ALGORITHM", "HS256")
        self.access_token_expire_minutes: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
        self.refresh_token_expire_days: int = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))
        
        frontend_urls_raw = os.getenv("FRONTEND_URLS", "http://localhost:3000")
        self.frontend_urls: list[str] = [url.strip() for url in frontend_urls_raw.split(",") if url.strip()]

        self.mongodb_url: str = os.getenv("MONGODB_URL", "mongodb://localhost:27017")
        self.mongodb_database: str = os.getenv("MONGODB_DATABASE", "intellinews")

        self.redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")

        self.huggingface_api_key: str = os.getenv("HUGGINGFACE_API_KEY", "")
        self.huggingface_model: str = os.getenv("HUGGINGFACE_MODEL", "facebook/bart-large-cnn")
        self.huggingface_sentiment_model: str = os.getenv("HUGGINGFACE_SENTIMENT_MODEL", "distilbert-base-uncased-finetuned-sst-2-english")
        self.huggingface_classification_model: str = os.getenv("HUGGINGFACE_CLASSIFICATION_MODEL", "MoritzLaurer/DeBERTa-v3-base-mnli-xnli")

        self.rss_fetch_interval_minutes: int = int(os.getenv("RSS_FETCH_INTERVAL_MINUTES", "15"))
        self.max_articles_per_fetch: int = int(os.getenv("MAX_ARTICLES_PER_FETCH", "50"))

        self.rss_feeds: dict[str, list[str]] = {
            "Global News": [
                "https://www.theguardian.com/world/rss",
                "https://feeds.bbci.co.uk/news/world/rss.xml",
                "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",
                "http://rss.cnn.com/rss/cnn_topstories.rss",
            ],
            "India": [
                "https://www.thehindu.com/news/international/feeder/default.rss",
                "https://timesofindia.indiatimes.com/rssfeedstopstories.cms",
                "https://www.hindustantimes.com/feeds/rss/india-news/rssfeed.xml",
                "https://www.ndtv.com/rss/india",
                "https://economictimes.indiatimes.com/rssfeedstopstories.cms",
            ],
            "UK": [
                "https://feeds.bbci.co.uk/news/uk/rss.xml",
            ],
            "USA": [
                "https://rss.nytimes.com/services/xml/rss/nyt/US.xml",
            ]
        }

@lru_cache
def get_settings() -> Settings:
    return Settings()
