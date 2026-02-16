import traceback
from datetime import datetime, timedelta
from app.db import get_articles_collection
from app.services.rss_fetcher import fetch_and_store_feeds, get_unprocessed_articles, mark_article_processed
from app.services.summarizer import summarize_text, analyze_sentiment, classify_text
from app.utils.helpers import estimate_reading_time, extract_tags_from_text, CATEGORIES

async def process_article(raw: dict) -> dict:
    title = raw.get("title", "")
    content = raw.get("content", "") or raw.get("summary", "")

    summary = await summarize_text(content[:3000])
    sentiment = await analyze_sentiment(summary)
    
    category_labels = list(CATEGORIES.keys())
    category = await classify_text(f"{title} {summary}", category_labels)

    tags = extract_tags_from_text(f"{title} {summary}")
    reading_time = estimate_reading_time(content)

    return {
        "title": title,
        "url": raw.get("url"),
        "image_url": raw.get("image_url"),
        "summary": summary,
        "content": content,
        "category": category,
        "sentiment": sentiment,
        "tags": tags,
        "source": raw.get("source"),
        "published_at": raw.get("published_at"),
        "created_at": datetime.utcnow(),
        "reading_time_minutes": reading_time,
        "views": 0,
        "upvotes": 0,
        "downvotes": 0,
        "comments_count": 0,
        "is_breaking": False,
        "difficulty_level": "medium",
    }

async def run_pipeline(max_articles: int = 10):
    print("Starting news pipeline...")
    await fetch_and_store_feeds()
    
    unprocessed = await get_unprocessed_articles(limit=max_articles)
    print(f"Found {len(unprocessed)} unprocessed articles.")
    
    collection = get_articles_collection()
    processed_count = 0
    
    for raw in unprocessed:
        try:
            processed_data = await process_article(raw)
            
            await collection.update_one(
                {"url": processed_data["url"]},
                {"$set": processed_data},
                upsert=True
            )
            
            print(f"Marking processed: {raw.get('url')}")
            await mark_article_processed(raw["url"])
            print(f"Processed: {processed_data['title']} -> {processed_data['category']}")
            processed_count += 1
            
        except Exception as e:
            print(f"Error processing {raw.get('title')}: {e}")
            traceback.print_exc()

    print("Pipeline finished.")
    return {"processed": processed_count, "total_unprocessed": len(unprocessed)}

async def refresh_breaking_news():
    print("Refreshing breaking news...")
    collection = get_articles_collection()
    await collection.update_many(
        {"title": {"$regex": "breaking|urgent|live", "$options": "i"}},
        {"$set": {"is_breaking": True}}
    )
    print("Breaking news refreshed.")
