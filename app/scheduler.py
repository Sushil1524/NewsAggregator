import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from app.config import get_settings

settings = get_settings()
scheduler = AsyncIOScheduler()

async def scheduled_news_refresh():
    from app.services.news_pipeline import run_news_pipeline
    try:
        await run_news_pipeline(max_articles=30)
    except Exception as e:
        print(f"Error: {e}")

async def scheduled_trending_update():
    from app.services.analytics_service import get_trending_articles
    try:
        await get_trending_articles(limit=20)
    except Exception as e:
        print(f"Trending error: {e}")

def start_scheduler():
    asyncio.create_task(scheduled_news_refresh())
    asyncio.create_task(scheduled_trending_update())

    scheduler.add_job(
        scheduled_news_refresh,
        IntervalTrigger(minutes=settings.rss_fetch_interval_minutes),
        id="news_refresh",
        replace_existing=True,
    )
    scheduler.add_job(
        scheduled_trending_update,
        IntervalTrigger(hours=1),
        id="trending_update",
        replace_existing=True,
    )

    scheduler.start()

def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown()
