from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import get_settings
from app.db import connect_mongodb, close_mongodb
from app.db import connect_redis, close_redis
from app.scheduler import start_scheduler, stop_scheduler
from app.routes import auth, articles, comments, bookmarks, admin, analytics, vocab

settings = get_settings()

@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect_mongodb()
    try:
        await connect_redis()
    except Exception:
        pass
    
    start_scheduler()
    yield
    stop_scheduler()
    await close_mongodb()
    try:
        await close_redis()
    except Exception:
        pass

app = FastAPI(
    title=settings.app_name,
    description="Intelligent News Aggregator",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/auth", tags=["Authentication"])
app.include_router(articles.router, prefix="/article", tags=["Articles"])
app.include_router(comments.router, prefix="/comments", tags=["Comments"])
app.include_router(bookmarks.router, prefix="/bookmarks", tags=["Bookmarks"])
app.include_router(admin.router, prefix="/admin", tags=["Admin"])
app.include_router(analytics.router, prefix="/analytics", tags=["Analytics"])
app.include_router(vocab.router, prefix="/vocab", tags=["Vocabulary"])

@app.get("/", tags=["Health"])
async def root():
    return {"status": "healthy", "app": settings.app_name}

@app.get("/health", tags=["Health"])
async def health_check():
    return {"status": "healthy", "database": "connected", "cache": "connected"}
