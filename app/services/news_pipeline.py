import asyncio
import traceback
from datetime import datetime, timedelta
from app.config import get_settings
from app.db import get_articles_collection, get_raw_articles_collection
from app.services.rss_fetcher import fetch_and_store_feeds, get_unprocessed_articles, mark_article_processed
from app.services.summarizer import summarize_text, analyze_sentiment, classify_text
from app.services.local_nlp import (
    local_summarize,
    local_sentiment,
    local_classify,
    normalize_publisher
)
from app.utils.helpers import estimate_reading_time, extract_tags_from_text, extract_locations_from_text, CATEGORIES

VALID_CATEGORIES = set(CATEGORIES.keys())

PIPELINE_CONCURRENCY = 5

def _safe_print(msg: str):
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode("ascii", "replace").decode("ascii"))

def _normalize_category(category: str) -> str:
    if not category:
        return "General"
    normalized = category.strip().title()
    if normalized in VALID_CATEGORIES:
        return normalized
    for valid in VALID_CATEGORIES:
        if valid.lower() == normalized.lower():
            return valid
    return "General"

async def process_article(raw: dict) -> dict:
    title = raw.get("title", "").strip()
    content = (raw.get("content", "") or raw.get("summary", "")).strip()
    rss_summary = raw.get("summary", "").strip()
    feed_category = raw.get("feed_category")   # may be None

    from app.utils.helpers import strip_bullets
    import re

    def _clean(t: str) -> str:
        t = re.sub(r"(?i)click\s+to\s+read.*", "", t)
        t = re.sub(r"(?i)read\s+also\s*[:\-].*", "", t)
        t = re.sub(r"(?i)\[\+?\d+\s+chars?\]", "", t)
        return strip_bullets(t).strip()

    clean_content = _clean(content)
    clean_rss_summary = _clean(rss_summary)

    if clean_content and len(clean_content.split()) >= 30:
        source_text = clean_content[:5000]
    elif clean_rss_summary and len(clean_rss_summary.split()) >= 8:
        source_text = clean_rss_summary[:2000]
    else:
        source_text = (clean_content or clean_rss_summary)[:1000]

    cfg = get_settings()
    source_name = normalize_publisher(raw.get("source"))

    if cfg.use_local_engine:
        summary, summary_source = local_summarize(title, source_text)
        sentiment = local_sentiment(title, summary)
        category = _normalize_category(local_classify(title, summary, feed_category=feed_category))
    else:
        summary, summary_source = await summarize_text(title, source_text)
        sentiment = await analyze_sentiment(title, summary)
        category_labels = list(CATEGORIES.keys())
        category_raw = await classify_text(title, summary, category_labels, feed_category=feed_category)
        category = _normalize_category(category_raw)

    tags = raw.get("tags") or []
    if not tags or len(tags) < 2:
        tags = extract_tags_from_text(f"{title} {summary}")

    location_text = f"{title} {summary} {clean_content[:500]}"
    locations = extract_locations_from_text(location_text)
    rss_location = raw.get("rss_location")
    if rss_location and rss_location not in locations:
        locations.insert(0, rss_location)

    reading_time = estimate_reading_time(content)
    country_code = raw.get("country_code")

    is_breaking = False
    title_lower = title.lower()
    source_lower = raw.get("source", "").lower()
    reliable_breaking = ["cnn", "al jazeera", "bbc", "reuters", "nytimes", "ap news", "ndtv"]
    breaking_kws = ["live", "urgent", "breaking", "update", "just in"]

    if any(s in source_lower for s in reliable_breaking) and any(kw in title_lower for kw in breaking_kws):
        is_breaking = True
    elif any(f"{kw}:" in title_lower for kw in ["breaking", "urgent"]):
        is_breaking = True

    return {
        "title": title,
        "url": raw.get("url"),
        "image_url": raw.get("image_url"),
        "summary": summary,
        "summary_source": summary_source,
        "content": content,
        "category": category,
        "sentiment": sentiment,
        "tags": tags[:6],
        "locations": locations,
        "country_code": country_code,
        "source": source_name,
        "published_at": raw.get("published_at"),
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
        "reading_time_minutes": reading_time,
        "views": 0,
        "upvotes": 0,
        "downvotes": 0,
        "comments_count": 0,
        "is_breaking": is_breaking,
        "difficulty_level": "medium",
    }

async def _process_and_save(raw: dict, collection, semaphore: asyncio.Semaphore) -> bool:
    async with semaphore:
        try:
            one_day_ago = datetime.utcnow() - timedelta(days=1)
            is_duplicate = await collection.find_one({
                "title": raw.get("title", ""),
                "created_at": {"$gte": one_day_ago}
            })

            if is_duplicate:
                print(f"[pipeline] Duplicate, skipping: {raw.get('title', '')[:60]}")
                await mark_article_processed(raw["url"])
                return False

            processed_data = await process_article(raw)

            await collection.update_one(
                {"url": processed_data["url"]},
                {"$set": processed_data},
                upsert=True,
            )

            await mark_article_processed(raw["url"])
            print(
                f"[pipeline] ✓ {processed_data['title'][:60]} "
                f"→ {processed_data['category']} "
                f"[{processed_data['sentiment']}] "
                f"[{processed_data.get('summary_source')}]"
            )
            return True

        except Exception as e:
            print(f"[pipeline] Error processing '{raw.get('title', '')}': {e}")
            traceback.print_exc()
            return False

async def run_pipeline(max_articles: int | None = None, batches: int | None = None):
    import time
    from app.config import get_settings
    import os
    cfg = get_settings()
    if cfg.dev_mode or os.getenv("DEV_MODE", "false").strip().lower() == "true":
        print("[pipeline] DEV_MODE active — pipeline bypassed.")
        return {"processed": 0, "total_unprocessed": 0}

    batch_size = max_articles if max_articles is not None else cfg.pipeline_batch_size
    batch_count = batches if batches is not None else cfg.pipeline_batches

    started_at = datetime.utcnow()
    run_start = time.perf_counter()
    print(f"[pipeline] Starting news pipeline (batch_size={batch_size}, batches={batch_count})...")

    articles_coll = get_articles_collection()
    yesterday = datetime.utcnow() - timedelta(hours=24)
    await articles_coll.update_many(
        {"is_breaking": True, "created_at": {"$lt": yesterday}},
        {"$set": {"is_breaking": False}},
    )

    from app.services.rss_fetcher import _feed_failures, FEED_FAILURE_THRESHOLD
    saved_count = await fetch_and_store_feeds()
    articles_fetched = saved_count

    raw_coll = get_raw_articles_collection()
    initial_unprocessed = await raw_coll.count_documents({"is_processed": False})
    print(f"[pipeline] Queue status: {initial_unprocessed} total unprocessed raw articles in DB.")

    semaphore = asyncio.Semaphore(PIPELINE_CONCURRENCY)
    summary_sources: dict[str, int] = {}
    category_counts: dict[str, int] = {}
    total_processed = 0

    async def _process_and_track(raw: dict) -> bool:
        async with semaphore:
            try:
                one_day_ago = datetime.utcnow() - timedelta(days=1)
                title = raw.get("title", "")
                text = (raw.get("content") or raw.get("summary") or "")

                from app.services.rss_fetcher import _is_newsletter_or_digest, _is_promo_or_deal_article
                if _is_newsletter_or_digest(title, text) or _is_promo_or_deal_article(title, text):
                    _safe_print(f"[pipeline] Dropping newsletter/promo article: {title[:60]}")
                    await mark_article_processed(raw["url"])
                    return False

                is_duplicate = await articles_coll.find_one({
                    "title": title,
                    "created_at": {"$gte": one_day_ago}
                })

                if is_duplicate:
                    print(f"[pipeline] Duplicate, skipping: {title[:60]}")
                    await mark_article_processed(raw["url"])
                    return False

                processed_data = await process_article(raw)

                await articles_coll.update_one(
                    {"url": processed_data["url"]},
                    {"$set": processed_data},
                    upsert=True,
                )
                await mark_article_processed(raw["url"])

                src = processed_data.get("summary_source", "unknown")
                cat = processed_data.get("category", "General")
                summary_sources[src] = summary_sources.get(src, 0) + 1
                category_counts[cat] = category_counts.get(cat, 0) + 1

                _safe_print(
                    f"[pipeline] [OK] {processed_data['title'][:60]} "
                    f"-> {cat} [{processed_data['sentiment']}] [{src}]"
                )
                return True

            except Exception as e:
                _safe_print(f"[pipeline] Error processing article: {e}")
                traceback.print_exc()
                return False

    if cfg.use_local_engine:
        # High-performance local engine (<2ms/article): process entire raw queue until empty
        b = 0
        while True:
            unprocessed = await get_unprocessed_articles(limit=batch_size)
            if not unprocessed:
                print(f"[pipeline] All raw articles processed. Queue is empty!")
                break
            b += 1
            print(f"[pipeline] Processing batch {b} ({len(unprocessed)} articles, source-diverse)...")
            results = await asyncio.gather(*[_process_and_track(raw) for raw in unprocessed])
            batch_processed = sum(1 for r in results if r)
            total_processed += batch_processed
            if batch_processed > 0:
                from app.db import clear_cache_pattern
                await clear_cache_pattern("article_list:*")
            print(f"[pipeline] Batch {b} finished: {batch_processed} articles enriched.")
    else:
        for b in range(batch_count):
            unprocessed = await get_unprocessed_articles(limit=batch_size)
            if not unprocessed:
                print(f"[pipeline] No more unprocessed articles available.")
                break

            print(f"[pipeline] Processing batch {b + 1}/{batch_count} ({len(unprocessed)} articles, source-diverse)...")
            results = await asyncio.gather(*[_process_and_track(raw) for raw in unprocessed])
            batch_processed = sum(1 for r in results if r)
            total_processed += batch_processed
            if batch_processed > 0:
                from app.db import clear_cache_pattern
                await clear_cache_pattern("article_list:*")
            print(f"[pipeline] Batch {b + 1}/{batch_count} finished: {batch_processed} articles enriched.")

    remaining_unprocessed = await raw_coll.count_documents({"is_processed": False})
    print(f"[pipeline] Queue status after run: {remaining_unprocessed} unprocessed articles remaining.")

    processed_count = total_processed

    finished_at = datetime.utcnow()
    duration_seconds = round(time.perf_counter() - run_start, 2)

    failed_feeds = [
        url for url, count in _feed_failures.items()
        if count >= FEED_FAILURE_THRESHOLD
    ]

    try:
        from app.db import get_pipeline_runs_collection
        runs_coll = get_pipeline_runs_collection()
        await runs_coll.insert_one({
            "started_at": started_at,
            "finished_at": finished_at,
            "duration_seconds": duration_seconds,
            "articles_fetched": articles_fetched,
            "articles_saved": saved_count,
            "articles_processed": processed_count,
            "total_unprocessed": len(unprocessed),
            "summary_sources": summary_sources,
            "category_breakdown": category_counts,
            "failed_feeds": failed_feeds,
        })
        print(f"[pipeline] Run record saved ({duration_seconds}s, {processed_count} processed).")
    except Exception as e:
        print(f"[pipeline] Warning: could not save run record: {e}")

    print(f"[pipeline] Finished. Processed {processed_count}/{len(unprocessed)} articles.")
    return {"processed": processed_count, "total_unprocessed": len(unprocessed)}


async def refresh_breaking_news():
    print("[pipeline] Refreshing breaking news flags...")
    collection = get_articles_collection()
    await collection.update_many(
        {"title": {"$regex": "breaking|urgent|live", "$options": "i"}},
        {"$set": {"is_breaking": True}},
    )
    print("[pipeline] Breaking news refresh done.")
