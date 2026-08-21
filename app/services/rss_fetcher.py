import asyncio
import aiohttp
import feedparser
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from app.config import get_settings
from app.db import get_raw_articles_collection
from app.utils.helpers import clean_html, extract_tags_from_text

settings = get_settings()

# Track consecutive feed failures to avoid hammering dead feeds
_feed_failures: dict[str, int] = {}
_feed_skip_until: dict[str, datetime] = {}
FEED_FAILURE_THRESHOLD = 3
FEED_SKIP_MINUTES = 60

# Minimum words to consider content "useful" — very short stubs still accepted
# if the title is meaningful (≥ 6 words)
MIN_CONTENT_WORDS = 20

# Topic-based feed groups that map 1:1 to a category — used to skip classification
TOPIC_FEED_GROUPS = {
    "Technology", "Science", "Sports", "Business", "Environment",
}

# Extended boilerplate patterns to strip from article text
_BOILERPLATE_PATTERNS = [
    r"(?i)click\s+to\s+read\s+(the\s+)?full\s+stor(y|ies)\.?",
    r"(?i)click\s+here\s+to\s+read(\s+the)?\s+full\s+stor(y|ies)\.?",
    r"(?i)read\s+full\s+stor(y|ies)\s+on\s+\S+",
    r"(?i)full\s+stor(y|ies)\s+available\s+at\s+\S+",
    r"(?i)read\s+also\s*[:\-]\s*.*",
    r"(?i)also\s+read\s*[:\-]\s*.*",
    r"(?i)watch\s*[:\-]\s*.*",
    r"(?i)\d+\s+min(ute)?\s+read",
    r"(?i)subscribe\s+to\s+read.*",
    r"(?i)this\s+article\s+is\s+behind\s+a\s+paywall.*",
    r"(?i)sign\s+in\s+to\s+read.*",
    r"(?i)\[[\+\-]?\d+\s+chars?\]",          # feedparser truncation marker
    r"(?i)&lt;!--.*?--&gt;",                  # HTML comment artifacts
    r"(?i)\(function\s*\(.*?\}\)\s*;",         # inline JS snippets
    r"(?i)cookies?\s+help\s+us.*",
    r"(?i)by\s+accepting\s+our\s+cookies.*",
    r"(?i)privacy\s+policy.*",
    r"(?i)advertisement\b.*",
    r"(?i)sponsored\s+content\b.*",
]


async def fetch_feed(
    session: aiohttp.ClientSession,
    feed_url: str,
    feed_location: str,
    country_code: str | None,
    feed_category: str | None = None,
) -> list[dict]:
    """Fetch one RSS feed and return a list of raw article dicts."""
    # Skip feeds that have been failing repeatedly
    skip_until = _feed_skip_until.get(feed_url)
    if skip_until and datetime.utcnow() < skip_until:
        return []

    try:
        timeout = aiohttp.ClientTimeout(total=30)
        async with session.get(feed_url, timeout=timeout) as resp:
            if resp.status != 200:
                _record_failure(feed_url)
                return []

            text = await resp.text()
            feed = feedparser.parse(text)
            source = feed.feed.get("title", feed_url.split("/")[2])

            articles = []
            for entry in feed.entries[: settings.max_articles_per_fetch]:
                article = _parse_entry(entry, source, country_code)
                if article:
                    # Location signal for geographic feeds
                    if feed_location and feed_location not in (
                        "Global News", "Technology", "Science",
                        "Sports", "Business", "Environment",
                    ):
                        article["rss_location"] = feed_location
                    if country_code:
                        article["country_code"] = country_code
                    # Topic-feed category shortcut (avoids expensive HF call)
                    if feed_category:
                        article["feed_category"] = feed_category
                    articles.append(article)

            # Success — reset failure counter
            _feed_failures[feed_url] = 0
            _feed_skip_until.pop(feed_url, None)
            return articles

    except Exception as e:
        print(f"Error fetching {feed_url}: {e}")
        _record_failure(feed_url)
        return []


def _record_failure(feed_url: str):
    _feed_failures[feed_url] = _feed_failures.get(feed_url, 0) + 1
    if _feed_failures[feed_url] >= FEED_FAILURE_THRESHOLD:
        skip_until = datetime.utcnow() + timedelta(minutes=FEED_SKIP_MINUTES)
        _feed_skip_until[feed_url] = skip_until
        print(
            f"Feed {feed_url} failed {FEED_FAILURE_THRESHOLD} times "
            f"— skipping for {FEED_SKIP_MINUTES} min"
        )


def _clean_boilerplate(text: str) -> str:
    """Strip common RSS boilerplate patterns from article text."""
    if not text:
        return ""
    import re
    cleaned = text
    for pat in _BOILERPLATE_PATTERNS:
        cleaned = re.sub(pat, "", cleaned, flags=re.DOTALL).strip()
    # Collapse excessive whitespace
    cleaned = re.sub(r"\s{3,}", " ", cleaned).strip()
    return cleaned


def _parse_entry(entry, source: str, country_code: str | None) -> dict | None:
    url = entry.get("link", "")
    if not url:
        return None

    title = entry.get("title", "Untitled").strip()
    published = _get_date(entry)
    image_url = _get_image(entry)

    # --- Extract raw HTML content ---
    raw_html = ""
    if hasattr(entry, "content") and entry.content:
        raw_html = entry.content[0].get("value", "")
    elif hasattr(entry, "summary"):
        raw_html = entry.summary

    content = _clean_boilerplate(clean_html(raw_html))
    raw_summary = _clean_boilerplate(clean_html(entry.get("summary", "")))
    summary = raw_summary[:600] if raw_summary else (content[:600] if content else "")

    # --- Quality filter: skip genuinely empty stubs ---
    effective_text = content or summary
    word_count = len(effective_text.split())
    title_word_count = len(title.split())

    if word_count < MIN_CONTENT_WORDS:
        # Accept if the title is substantial (headline-only feeds)
        if title_word_count < 6:
            return None

    # --- Tags ---
    tags = []
    if hasattr(entry, "tags"):
        tags = [t.get("term", "") for t in entry.tags if t.get("term")]
    if not tags:
        tags = extract_tags_from_text(title + " " + (content or summary))

    return {
        "title": title,
        "url": url,
        "image_url": image_url,
        "summary": summary,
        "content": content or summary,
        "source": source,
        "published_at": published,
        "tags": tags[:6],
        "country_code": country_code,
        "is_processed": False,
        "created_at": datetime.utcnow(),
    }


def _get_date(entry) -> datetime | None:
    for attr in ("published_parsed", "updated_parsed"):
        parsed = getattr(entry, attr, None)
        if parsed:
            try:
                return datetime(*parsed[:6])
            except Exception:
                pass
    return None


def _get_image(entry) -> str | None:
    # 1. Media thumbnail (BBC, Reuters, DW, The Hindu, NYT, etc.)
    if hasattr(entry, "media_thumbnail") and entry.media_thumbnail:
        for thumb in entry.media_thumbnail:
            if isinstance(thumb, dict) and thumb.get("url"):
                return thumb["url"]

    # 2. Media content
    if hasattr(entry, "media_content") and entry.media_content:
        for media in entry.media_content:
            if isinstance(media, dict) and media.get("url"):
                w = media.get("width")
                if w and int(w) < 100:
                    continue
                return media["url"]

    # 3. Enclosures & Links
    if hasattr(entry, "enclosures") and entry.enclosures:
        for enc in entry.enclosures:
            if isinstance(enc, dict) and "image" in enc.get("type", "") and enc.get("href"):
                return enc["href"]

    if hasattr(entry, "links"):
        for link in entry.links:
            if (
                link.get("rel") in ("enclosure", "related")
                and "image" in link.get("type", "")
                and link.get("href")
            ):
                return link["href"]

    # 4. Entry image object
    if hasattr(entry, "image") and entry.image:
        if isinstance(entry.image, dict) and entry.image.get("href"):
            return entry.image["href"]

    # 5. Extract <img> tags from content / summary / description HTML
    html_sources = []
    if hasattr(entry, "content") and entry.content:
        for c in entry.content:
            if isinstance(c, dict) and c.get("value"):
                html_sources.append(c["value"])
    if hasattr(entry, "summary") and entry.summary:
        html_sources.append(entry.summary)
    if hasattr(entry, "description") and entry.description:
        html_sources.append(entry.description)

    for html in html_sources:
        if not html:
            continue
        soup = BeautifulSoup(html, "html.parser")
        for img in soup.find_all("img"):
            src = img.get("src") or img.get("data-src") or img.get("data-original")
            if not src and img.get("srcset"):
                src = img["srcset"].split(",")[0].split()[0]
            if (
                src
                and not src.endswith((".gif", ".svg"))
                and "1x1" not in src
                and "pixel" not in src
                and "spacer" not in src
            ):
                if src.startswith("//"):
                    src = "https:" + src
                return src

    return None


async def _fetch_og_image(session: aiohttp.ClientSession, url: str) -> str | None:
    """
    Lightweight fallback: fetch the article HTML and extract og:image.
    Times out quickly so it doesn't block the pipeline.
    """
    try:
        timeout = aiohttp.ClientTimeout(total=6)
        async with session.get(url, timeout=timeout, allow_redirects=True) as resp:
            if resp.status != 200:
                return None
            # Only read first 32 KB — the <meta> tags are always in <head>
            chunk = await resp.content.read(32768)
            html = chunk.decode("utf-8", errors="ignore")
            soup = BeautifulSoup(html, "html.parser")
            for prop in ("og:image", "twitter:image", "og:image:secure_url"):
                tag = soup.find("meta", property=prop) or soup.find("meta", attrs={"name": prop})
                if tag:
                    content = tag.get("content", "").strip()
                    if content and content.startswith("http"):
                        return content
    except Exception:
        pass
    return None


async def fetch_all_feeds() -> list[dict]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }
    async with aiohttp.ClientSession(headers=headers) as session:
        tasks = []
        for location, feed_config in settings.rss_feeds.items():
            country_code = feed_config.get("country_code")
            # Determine feed_category for topic feeds
            feed_category = location if location in TOPIC_FEED_GROUPS else None
            for url in feed_config.get("urls", []):
                tasks.append(fetch_feed(session, url, location, country_code, feed_category))
        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_articles: list[dict] = []
        for result in results:
            if isinstance(result, list):
                all_articles.extend(result)

        # og:image fallback pass — for articles still missing an image
        og_tasks = []
        og_indices = []
        for i, article in enumerate(all_articles):
            if not article.get("image_url") and article.get("url"):
                og_tasks.append(_fetch_og_image(session, article["url"]))
                og_indices.append(i)

        if og_tasks:
            og_results = await asyncio.gather(*og_tasks, return_exceptions=True)
            for idx, og_url in zip(og_indices, og_results):
                if isinstance(og_url, str) and og_url:
                    all_articles[idx]["image_url"] = og_url

    total_feeds = sum(len(fc.get("urls", [])) for fc in settings.rss_feeds.values())
    print(f"Fetched {len(all_articles)} articles from {total_feeds} feeds")
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
