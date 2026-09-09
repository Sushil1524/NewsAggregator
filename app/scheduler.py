import asyncio
import time
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from app.config import get_settings
from app.services.news_pipeline import run_pipeline
from app.routes.analytics import get_trending_articles
from app.db import sync_views_to_mongodb

settings = get_settings()
scheduler = AsyncIOScheduler()

# Bulletproof async lock to guarantee ZERO pipeline overlaps
_pipeline_lock = asyncio.Lock()

# In-memory status tracker for health checks and status endpoints
_scheduler_status = {
    "status": "stopped",
    "running": False,
    "last_run_started_at": None,
    "last_run_finished_at": None,
    "last_run_duration_seconds": None,
    "last_run_articles_processed": 0,
    "last_run_status": "none",
    "last_error": None,
    "total_runs": 0,
}

def get_scheduler_status() -> dict:
    """Return in-memory scheduler health and run status."""
    return {
        **_scheduler_status,
        "scheduler_running": scheduler.running if scheduler else False,
    }

async def scheduled_news_refresh():
    if _pipeline_lock.locked():
        print("[scheduler] ⏳ Previous pipeline run is still active. Skipping overlapping execution.")
        return

    async with _pipeline_lock:
        start_time = time.perf_counter()
        started_at = datetime.utcnow()
        _scheduler_status["last_run_started_at"] = started_at.isoformat()
        _scheduler_status["last_run_status"] = "running"
        _scheduler_status["total_runs"] += 1

        try:
            res = await run_pipeline()
            processed = res.get("processed", 0) if isinstance(res, dict) else 0

            duration = round(time.perf_counter() - start_time, 2)
            _scheduler_status["last_run_finished_at"] = datetime.utcnow().isoformat()
            _scheduler_status["last_run_duration_seconds"] = duration
            _scheduler_status["last_run_articles_processed"] = processed
            _scheduler_status["last_run_status"] = "success"
            _scheduler_status["last_error"] = None
        except Exception as e:
            duration = round(time.perf_counter() - start_time, 2)
            err_msg = str(e)
            print(f"[scheduler] ❌ Error in news refresh pipeline: {err_msg}")
            _scheduler_status["last_run_finished_at"] = datetime.utcnow().isoformat()
            _scheduler_status["last_run_duration_seconds"] = duration
            _scheduler_status["last_run_status"] = "error"
            _scheduler_status["last_error"] = err_msg

async def scheduled_trending_update():
    try:
        await get_trending_articles(limit=20)
    except Exception as e:
        print(f"[scheduler] Trending error: {e}")

async def scheduled_view_sync():
    try:
        await sync_views_to_mongodb()
    except Exception as e:
        print(f"[scheduler] View sync error: {e}")

def start_scheduler():
    current_settings = get_settings()
    import os
    is_dev = current_settings.dev_mode or os.getenv("DEV_MODE", "false").strip().lower() == "true"

    if is_dev:
        print("[DEV MODE] Pipeline disabled — no article fetching, processing, or trending refresh.")
        print("[DEV MODE] Existing DB articles are served normally.")
        _scheduler_status["status"] = "dev_bypassed"
        _scheduler_status["running"] = True
        if not scheduler.running:
            scheduler.start()
        return

    # Production: Start scheduler loop
    _scheduler_status["status"] = "active"
    _scheduler_status["running"] = True

    # Delayed initial run (configurable via PIPELINE_STARTUP_DELAY_SECONDS in config.py)
    async def _delayed_startup():
        delay = current_settings.pipeline_startup_delay_seconds
        if delay > 0:
            print(f"[scheduler] Startup delay active — waiting {delay}s before executing initial pipeline run...")
            await asyncio.sleep(delay)
        await scheduled_news_refresh()
        await scheduled_trending_update()

    asyncio.create_task(_delayed_startup())

    # Add scheduled jobs with max_instances=1 and coalesce=True
    scheduler.add_job(
        scheduled_news_refresh,
        IntervalTrigger(minutes=current_settings.rss_fetch_interval_minutes),
        id="news_refresh",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    scheduler.add_job(
        scheduled_trending_update,
        IntervalTrigger(hours=1),
        id="trending_update",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    scheduler.add_job(
        scheduled_view_sync,
        IntervalTrigger(minutes=2),
        id="view_sync",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )

    if not scheduler.running:
        scheduler.start()

def stop_scheduler():
    _scheduler_status["status"] = "stopped"
    _scheduler_status["running"] = False
    if scheduler.running:
        scheduler.shutdown(wait=False)
        print("[scheduler] Scheduler shutdown complete.")
