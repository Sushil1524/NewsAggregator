import asyncio
import aiohttp
import feedparser
from datetime import datetime
from bs4 import BeautifulSoup
from app.config import get_settings
from app.db import get_raw_articles_collection
from app.utils.helpers import clean_html, extract_tags_from_text

settings = get_settings()

async def fetch_feed(session: aiohttp.ClientSession, feed_url: str) -> list[dict]:
    try:
        timeout = aiohttp.ClientTimeout(total=30)
        async with session.get(feed_url, timeout=timeout) as resp:
            if resp.status != 200:
                return []

            text = await resp.text()
            feed = feedparser.parse(text)
            source = feed.feed.get("title", feed_url.split("/")[2])

            articles = []
            for entry in feed.entries[: settings.max_articles_per_fetch]:
                article = _parse_entry(entry, source)
                if article:
                    articles.append(article)

            return articles

    except Exception as e:
        print(f"Error fetching {feed_url}: {e}")
        return []

def _parse_entry(entry, source: str) -> dict | None:
    url = entry.get("link", "")
    if not url:
        return None

    title = entry.get("title", "Untitled")
    published = _get_date(entry)
    image_url = _get_image(entry)

    raw_html = ""
    if hasattr(entry, "content") and entry.content:
        raw_html = entry.content[0].get("value", "")
    elif hasattr(entry, "summary"):
        raw_html = entry.summary

    content = clean_html(raw_html)
    summary = clean_html(entry.get("summary", ""))[:500]

    tags = []
    if hasattr(entry, "tags"):
        tags = [t.get("term", "") for t in entry.tags if t.get("term")]
    if not tags:
        tags = extract_tags_from_text(title + " " + content)

    return {
        "title": title,
        "url": url,
        "image_url": image_url,
        "summary": summary,
        "content": content or summary,
        "source": source,
        "published_at": published,
        "tags": tags[:5],
        "is_processed": False,
        "created_at": datetime.utcnow(),
    }

def _get_date(entry) -> datetime | None:
    for attr in ("published_parsed", "updated_parsed"):
        parsed = getattr(entry, attr, None)
        if parsed:
            return datetime(*parsed[:6])
    return None

def _get_image(entry) -> str | None:
    if hasattr(entry, "media_content") and entry.media_content:
        for media in entry.media_content:
            if "url" in media:
                return media["url"]

    if hasattr(entry, "links"):
        for link in entry.links:
            if link.get("rel") == "enclosure" and "image" in link.get("type", ""):
                return link.get("href")

    html = ""
    if hasattr(entry, "content") and entry.content:
        html = entry.content[0].get("value", "")
    elif hasattr(entry, "summary"):
        html = entry.summary
    if html:
        img = BeautifulSoup(html, "html.parser").find("img")
        if img and img.get("src"):
            return img["src"]

    return None

async def fetch_all_feeds() -> list[dict]:
    async with aiohttp.ClientSession() as session:
        tasks = [fetch_feed(session, url) for url in settings.rss_feeds]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    all_articles = []
    for result in results:
        if isinstance(result, list):
            all_articles.extend(result)

    print(f"Fetched {len(all_articles)} articles from {len(settings.rss_feeds)} feeds")
    return all_articles

async def save_raw_articles(articles: list[dict]) -> int:
    if not articles:
        return 0

    collection = get_raw_articles_collection()
    saved = 0

    for article in articles:
        existing = await collection.find_one({"url": article["url"]})
        if not existing:
            await collection.insert_one(article)
            saved += 1

    print(f"Saved {saved} new articles")
    return saved

async def fetch_and_store_feeds() -> int:
    articles = await fetch_all_feeds()
    return await save_raw_articles(articles)

async def get_unprocessed_articles(limit: int = 50) -> list[dict]:
    collection = get_raw_articles_collection()
    cursor = collection.find({"is_processed": False}).limit(limit)
    return await cursor.to_list(length=limit)

async def mark_article_processed(url: str):
    collection = get_raw_articles_collection()
    await collection.update_one({"url": url}, {"$set": {"is_processed": True}})
