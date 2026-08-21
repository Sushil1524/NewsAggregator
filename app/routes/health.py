import os
import sys
import time
import platform
from datetime import datetime
from fastapi import APIRouter, HTTPException, status
from app.config import get_settings
from app.db import get_database, get_redis, get_articles_collection, get_users_collection, get_clubs_collection

router = APIRouter()
settings = get_settings()

START_TIME = time.time()

@router.get("/health", tags=["Health"])
@router.get("/healthz", tags=["Health"])
async def health_check():
    """Comprehensive health check for load balancers & monitoring services."""
    db_status = "disconnected"
    cache_status = "disconnected"
    db_latency_ms = None
    is_healthy = True

    # Probe MongoDB
    try:
        t0 = time.perf_counter()
        db = get_database()
        await db.command("ping")
        t1 = time.perf_counter()
        db_latency_ms = round((t1 - t0) * 1000, 2)
        db_status = "connected"
    except Exception as e:
        is_healthy = False
        db_status = f"error: {str(e)}"

    # Probe Redis
    try:
        redis_client = get_redis()
        if redis_client:
            await redis_client.ping()
            cache_status = "connected"
        else:
            cache_status = "disabled/unavailable"
    except Exception as e:
        cache_status = f"error: {str(e)}"

    uptime_seconds = int(time.time() - START_TIME)

    health_payload = {
        "status": "healthy" if is_healthy else "unhealthy",
        "app": settings.app_name,
        "environment": "development" if settings.dev_mode else "production",
        "dev_mode": settings.dev_mode,
        "uptime_seconds": uptime_seconds,
        "services": {
            "database": {
                "status": db_status,
                "latency_ms": db_latency_ms,
            },
            "cache": {
                "status": cache_status,
            },
        },
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }

    if not is_healthy:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=health_payload
        )

    return health_payload


@router.get("/ready", tags=["Health"])
@router.get("/readiness", tags=["Health"])
async def readiness_probe():
    """Readiness probe for container orchestrators (Kubernetes / Docker)."""
    try:
        db = get_database()
        await db.command("ping")
        return {"status": "ready", "timestamp": datetime.utcnow().isoformat() + "Z"}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"status": "not_ready", "error": str(e)}
        )


@router.get("/metrics", tags=["Health & Tracking"])
async def tracking_metrics():
    """Application tracking metrics for system monitoring and dashboard displays."""
    uptime_seconds = int(time.time() - START_TIME)
    
    total_articles = 0
    processed_articles = 0
    total_users = 0
    total_clubs = 0

    try:
        articles_coll = get_articles_collection()
        total_articles = await articles_coll.count_documents({})
        processed_articles = await articles_coll.count_documents({"is_processed": True})

        users_coll = get_users_collection()
        total_users = await users_coll.count_documents({})

        clubs_coll = get_clubs_collection()
        total_clubs = await clubs_coll.count_documents({})
    except Exception as e:
        print(f"Metrics query error: {e}")

    return {
        "app": settings.app_name,
        "dev_mode": settings.dev_mode,
        "uptime_seconds": uptime_seconds,
        "metrics": {
            "total_articles": total_articles,
            "processed_articles": processed_articles,
            "raw_articles": total_articles - processed_articles,
            "total_users": total_users,
            "total_clubs": total_clubs,
        },
        "system": {
            "python_version": sys.version.split()[0],
            "platform": platform.platform(),
            "process_id": os.getpid(),
        },
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


@router.get("/dev-status", tags=["Health"])
async def dev_status():
    """Dev mode status probe."""
    return {
        "dev_mode": settings.dev_mode,
        "pipeline_running": not settings.dev_mode,
        "app": settings.app_name,
        "message": "Pipeline DISABLED — dev mode active" if settings.dev_mode else "Pipeline ACTIVE — production mode"
    }
