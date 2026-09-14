import asyncio
import time
from datetime import datetime, timedelta
from app.config import get_settings
from app.logging import get_logger
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

logger = get_logger("app.pipeline")
VALID_CATEGORIES = set(CATEGORIES.keys())
PIPELINE_CONCURRENCY = 5

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
    if cfg.use_local_engine:
        summary_text, summary_source = local_summarize(title, clean_content, clean_rss_summary)
        sentiment_label, sentiment_score = local_sentiment(title, summary_text)
        if feed_category:
            category = _normalize_category(feed_category)
        else:
            category = _normalize_category(local_classify(title, summary_text))
    else:
        summary_text, summary_source = await summarize_text(title, source_text)
        sentiment_label, sentiment_score = await analyze_sentiment(f"{title}. {summary_text}")
        if feed_category:
            category = _normalize_category(feed_category)
        else:
            classified_cat = await classify_text(f"{title}. {summary_text}")
            category = _normalize_category(classified_cat)

    key_takeaways = []
    if summary_text:
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", summary_text) if len(s.strip()) > 15]
        key_takeaways = sentences[:3] if len(sentences) >= 2 else [summary_text]

    combined_text = f"{title} {summary_text} {clean_content}"
    tags = extract_tags_from_text(combined_text)
    locations = extract_locations_from_text(combined_text)

    raw_publisher = raw.get("source", "Unknown")
    canonical_source = normalize_publisher(raw_publisher, raw.get("url", ""))

    word_count = len((clean_content or summary_text).split())
    read_time = estimate_reading_time(word_count)

    now = datetime.utcnow()
    pub_date = raw.get("published_at")
    if not pub_date or (isinstance(pub_date, datetime) and (now - pub_date) > timedelta(days=7)):
        pub_date = now

    is_breaking = False
    if (now - pub_date) <= timedelta(hours=6):
        breaking_words = {"breaking", "urgent", "just in", "alert", "developing"}
        if any(w in title.lower() for w in breaking_words):
            is_breaking = True

    return {
        "title": title,
        "summary": summary_text,
        "content": clean_content or summary_text,
        "category": category,
        "sentiment": sentiment_label,
        "sentiment_score": sentiment_score,
        "key_takeaways": key_takeaways,
        "source": canonical_source,
        "source_country": raw.get("country_code"),
        "url": raw.get("url", ""),
        "image_url": raw.get("image_url"),
        "published_at": pub_date,
        "created_at": now,
        "read_time": read_time,
        "word_count": word_count,
        "tags": tags,
        "locations": locations,
        "is_breaking": is_breaking,
        "summary_source": summary_source,
        "views": 0,
        "upvotes": 0,
        "downvotes": 0,
    }

async def process_single_article(raw: dict) -> bool:
    """Processes a single raw article doc and stores the enriched version in 'articles'."""
    collection = get_articles_collection()
    one_day_ago = datetime.utcnow() - timedelta(days=1)

    try:
        is_duplicate = await collection.find_one({
            "title": raw.get("title", ""),
            "created_at": {"$gte": one_day_ago}
        })

        if is_duplicate:
            logger.debug(f"Duplicate, skipping: {raw.get('title', '')[:60]}")
            await mark_article_processed(raw["url"])
            return False

        processed_data = await process_article(raw)

        await collection.update_one(
            {"url": processed_data["url"]},
            {"$set": processed_data},
            upsert=True,
        )

        await mark_article_processed(raw["url"])
        logger.info(
            f"Enriched: {processed_data['title'][:60]} -> {processed_data['category']} [{processed_data['sentiment']}] [{processed_data.get('summary_source')}]",
            extra={
                "title": processed_data["title"][:80],
                "category": processed_data["category"],
                "sentiment": processed_data["sentiment"],
                "source": processed_data.get("summary_source"),
            }
        )
        return True

    except Exception as e:
        logger.error(f"Error processing article '{raw.get('title', '')}': {e}", exc_info=True)
        return False

async def run_pipeline(max_articles: int | None = None, batches: int | None = None):
    from app.config import get_settings
    import os
    cfg = get_settings()
    if cfg.dev_mode or os.getenv("DEV_MODE", "false").strip().lower() == "true":
        logger.info("DEV_MODE active — pipeline bypassed", extra={"dev_mode": True})
        return {"processed": 0, "total_unprocessed": 0}

    batch_size = max_articles if max_articles is not None else cfg.pipeline_batch_size
    batch_count = batches if batches is not None else cfg.pipeline_batches

    started_at = datetime.utcnow()
    run_start = time.perf_counter()
    logger.info(
        f"Starting news pipeline (batch_size={batch_size}, batches={batch_count})...",
        extra={"batch_size": batch_size, "batches": batch_count}
    )

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
    logger.info(
        f"Queue status: {initial_unprocessed} total unprocessed raw articles in DB",
        extra={"initial_unprocessed": initial_unprocessed}
    )

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
                    logger.debug(f"Dropping newsletter/promo article: {title[:60]}")
                    await mark_article_processed(raw["url"])
                    return False

                is_duplicate = await articles_coll.find_one({
                    "title": title,
                    "created_at": {"$gte": one_day_ago}
                })

                if is_duplicate:
                    logger.debug(f"Duplicate, skipping: {title[:60]}")
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

                logger.info(
                    f"[OK] {processed_data['title'][:60]} -> {cat} [{processed_data['sentiment']}] [{src}]",
                    extra={
                        "title": processed_data["title"][:80],
                        "category": cat,
                        "sentiment": processed_data["sentiment"],
                        "summary_source": src,
                    }
                )
                return True

            except Exception as e:
                logger.error(f"Error processing article: {e}", exc_info=True)
                return False

    if cfg.use_local_engine:
        # High-performance local engine (<2ms/article): process entire raw queue until empty
        b = 0
        while True:
            unprocessed = await get_unprocessed_articles(limit=batch_size)
            if not unprocessed:
                logger.info("All raw articles processed. Queue is empty!", extra={"queue_empty": True})
                break
            b += 1
            logger.info(
                f"Processing batch {b} ({len(unprocessed)} articles, source-diverse)...",
                extra={"batch_num": b, "batch_size": len(unprocessed)}
            )
            results = await asyncio.gather(*[_process_and_track(raw) for raw in unprocessed])
            batch_processed = sum(1 for r in results if r)
            total_processed += batch_processed
            if batch_processed > 0:
                from app.db import clear_cache_pattern
                await clear_cache_pattern("article_list:*")
            logger.info(
                f"Batch {b} finished: {batch_processed} articles enriched.",
                extra={"batch_num": b, "batch_processed": batch_processed}
            )
    else:
        for b in range(batch_count):
            unprocessed = await get_unprocessed_articles(limit=batch_size)
            if not unprocessed:
                logger.info("No more unprocessed articles available.", extra={"queue_empty": True})
                break

            logger.info(
                f"Processing batch {b + 1}/{batch_count} ({len(unprocessed)} articles, source-diverse)...",
                extra={"batch_num": b + 1, "batch_count": batch_count, "batch_size": len(unprocessed)}
            )
            results = await asyncio.gather(*[_process_and_track(raw) for raw in unprocessed])
            batch_processed = sum(1 for r in results if r)
            total_processed += batch_processed
            if batch_processed > 0:
                from app.db import clear_cache_pattern
                await clear_cache_pattern("article_list:*")
            logger.info(
                f"Batch {b + 1}/{batch_count} finished: {batch_processed} articles enriched.",
                extra={"batch_num": b + 1, "batch_processed": batch_processed}
            )

    remaining_unprocessed = await raw_coll.count_documents({"is_processed": False})
    logger.info(
        f"Queue status after run: {remaining_unprocessed} unprocessed articles remaining.",
        extra={"remaining_unprocessed": remaining_unprocessed}
    )

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
            "total_unprocessed": remaining_unprocessed,
            "summary_sources": summary_sources,
            "category_breakdown": category_counts,
            "failed_feeds": failed_feeds,
        })
        logger.info(
            f"Run record saved ({duration_seconds}s, {processed_count} processed).",
            extra={"duration_seconds": duration_seconds, "processed_count": processed_count}
        )
    except Exception as e:
        logger.warning(f"Could not save run record: {e}", extra={"error": str(e)})

    logger.info(
        f"Pipeline run finished: Processed {processed_count} articles in {duration_seconds}s.",
        extra={"processed_count": processed_count, "duration_seconds": duration_seconds}
    )
    return {"processed": processed_count, "total_unprocessed": remaining_unprocessed}


async def refresh_breaking_news():
    logger.info("Refreshing breaking news flags...")
    collection = get_articles_collection()
    await collection.update_many(
        {"title": {"$regex": "breaking|urgent|live", "$options": "i"}},
        {"$set": {"is_breaking": True}},
    )
    logger.info("Breaking news refresh done.")
