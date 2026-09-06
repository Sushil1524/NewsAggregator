import os
from functools import lru_cache
from typing import List
from dotenv import load_dotenv

load_dotenv()

class Settings:
    def __init__(self):
        self.app_name: str = "IntelliNews"
        self.dev_mode: bool = os.getenv("DEV_MODE", "False").strip().lower() == "true"
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
        self.huggingface_sentiment_model: str = os.getenv("HUGGINGFACE_SENTIMENT_MODEL", "cardiffnlp/twitter-roberta-base-sentiment-latest")
        self.huggingface_classification_model: str = os.getenv("HUGGINGFACE_CLASSIFICATION_MODEL", "facebook/bart-large-mnli")

        self.rss_fetch_interval_minutes: int = int(os.getenv("RSS_FETCH_INTERVAL_MINUTES", "15"))
        self.max_articles_per_fetch: int = int(os.getenv("MAX_ARTICLES_PER_FETCH", "50"))
        self.pipeline_batch_size: int = int(os.getenv("PIPELINE_BATCH_SIZE", "50"))
        self.pipeline_batches: int = int(os.getenv("PIPELINE_BATCHES", "2"))
        self.use_local_engine: bool = os.getenv("USE_LOCAL_ENGINE", "true").strip().lower() == "true"

        # RSS feeds organised by location/topic — each entry maps to a (country_code, url) pair
        # Format: { "location_label": { "country_code": "XX", "urls": [...] } }
        self.rss_feeds: dict[str, dict] = {
            "Global News": {
                "country_code": None,
                "urls": [
                    "https://www.theguardian.com/world/rss",
                    "https://feeds.bbci.co.uk/news/world/rss.xml",
                    "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",
                    # "http://rss.cnn.com/rss/cnn_topstories.rss",
                    "https://www.france24.com/en/rss",
                    # "https://feeds.a.dj.com/rss/RSSWorldNews.xml",
                ],
            },
            "India": {
                "country_code": "IN",
                "urls": [
                    # "https://www.thehindu.com/news/feeder/default.rss",
                    "https://timesofindia.indiatimes.com/rssfeedstopstories.cms",
                    "https://www.hindustantimes.com/feeds/rss/india-news/rssfeed.xml",
                    "https://www.ndtv.com/rss/india",
                    "https://economictimes.indiatimes.com/rssfeedstopstories.cms",
                    "https://scroll.in/feed",
                    "https://www.livemint.com/rss/news",
                ],
            },
            "UK": {
                "country_code": "GB",
                "urls": [
                    "https://feeds.bbci.co.uk/news/uk/rss.xml",
                    "https://www.theguardian.com/uk/rss",
                    "https://www.independent.co.uk/rss",
                ],
            },
            "USA": {
                "country_code": "US",
                "urls": [
                    "https://rss.nytimes.com/services/xml/rss/nyt/US.xml",
                    "https://feeds.npr.org/1001/rss.xml",
                    "https://www.pbs.org/newshour/feeds/rss/headlines",
                    "https://feeds.washingtonpost.com/rss/politics",
                ],
            },
            "Europe": {
                "country_code": "EU",
                "urls": [
                    "https://www.euronews.com/rss?format=mrss&level=theme&name=news",
                    "https://www.politico.com/rss/politics08.xml",
                ],
            },
            "East Asia": {
                "country_code": "ASIA",
                "urls": [
                    "https://www.scmp.com/rss/91/feed",
                    "https://www3.nhk.or.jp/rj/podcast/rss/english.xml",
                ],
            },
            "Middle East": {
                "country_code": "ME",
                "urls": [
                    "https://www.aljazeera.com/xml/rss/all.xml",
                    "https://www.arabnews.com/rss.xml",
                ],
            },
            "Australia": {
                "country_code": "AU",
                "urls": [
                    "https://www.abc.net.au/news/feed/51120/rss.xml",
                    "https://www.smh.com.au/rss/feed.xml",
                ],
            },
            "Canada": {
                "country_code": "CA",
                "urls": [
                    "https://rss.cbc.ca/lineup/topstories.xml",
                    "https://globalnews.ca/feed/",
                ],
            },

            # Topic-based feeds (no specific country)
            "Technology": {
                "country_code": None,
                "urls": [
                    "https://feeds.arstechnica.com/arstechnica/index",
                    "https://www.wired.com/feed/rss",
                    "https://techcrunch.com/feed/",
                    "https://hnrss.org/frontpage",
                ],
            },
            "Science": {
                "country_code": None,
                "urls": [
                    "https://www.sciencedaily.com/rss/top/science.xml",
                    "https://phys.org/rss-feed/",
                ],
            },
            "Sports": {
                "country_code": None,
                "urls": [
                    "https://feeds.bbci.co.uk/sport/rss.xml",
                    "https://www.espn.com/espn/rss/news",
                ],
            },
            "Business": {
                "country_code": None,
                "urls": [
                    "https://feeds.content.dowjones.io/public/rss/mw_topstories",
                    "https://www.bloomberg.com/feeds/news.rss",
                    #"https://rss.app/feeds/KKDXBm38OuWGJXH5.xml",  
                ],
            },
            "Environment": {
                "country_code": None,
                "urls": [
                    "https://www.theguardian.com/environment/rss",
                    "https://www.carbonbrief.org/feed/",
                ],
            },
        }

@lru_cache
def get_settings() -> Settings:
    return Settings()
