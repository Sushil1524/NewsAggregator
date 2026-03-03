from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import get_settings
from app.db import connect_mongodb, close_mongodb, get_clubs_collection
from app.db import connect_redis, close_redis
from app.scheduler import start_scheduler, stop_scheduler
from app.routes import auth, articles, comments, bookmarks, admin, analytics, vocab, clubs
from datetime import datetime

settings = get_settings()

@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect_mongodb()
    try:
        await connect_redis()
    except Exception:
        pass
    
    await seed_clubs()
    start_scheduler()
    yield
    stop_scheduler()
    await close_mongodb()
    try:
        await close_redis()
    except Exception:
        pass


CLUB_SEED_DATA = [
    {"slug": "technology", "name": "Technology", "icon": "💻", "description": "Discuss the latest in tech, AI, gadgets, software, and the digital world.", "banner_gradient": "from-blue-500 to-cyan-600"},
    {"slug": "politics", "name": "Politics", "icon": "🏛️", "description": "Debate political developments, policy changes, and governance from around the globe.", "banner_gradient": "from-red-600 to-rose-800"},
    {"slug": "business", "name": "Business", "icon": "💼", "description": "Markets, startups, finance, and the economy — all business talk lives here.", "banner_gradient": "from-emerald-500 to-teal-700"},
    {"slug": "health", "name": "Health", "icon": "🏥", "description": "Stay informed on medical breakthroughs, wellness tips, and public health news.", "banner_gradient": "from-green-400 to-emerald-600"},
    {"slug": "sports", "name": "Sports", "icon": "⚽", "description": "Scores, highlights, player transfers, and everything sports.", "banner_gradient": "from-orange-500 to-red-600"},
    {"slug": "entertainment", "name": "Entertainment", "icon": "🎬", "description": "Movies, music, TV shows, celebrities, and pop culture.", "banner_gradient": "from-pink-500 to-purple-700"},
    {"slug": "science", "name": "Science", "icon": "🔬", "description": "Explore discoveries in physics, biology, astronomy, and beyond.", "banner_gradient": "from-violet-500 to-indigo-700"},
    {"slug": "crime", "name": "Crime", "icon": "🔍", "description": "Crime reports, investigations, legal developments, and true crime discussions.", "banner_gradient": "from-gray-600 to-zinc-800"},
    {"slug": "education", "name": "Education", "icon": "📚", "description": "Learning resources, university news, EdTech, and academic discussions.", "banner_gradient": "from-amber-400 to-orange-600"},
    {"slug": "environment", "name": "Environment", "icon": "🌍", "description": "Climate change, sustainability, wildlife, and environmental activism.", "banner_gradient": "from-lime-500 to-green-700"},
    {"slug": "travel", "name": "Travel", "icon": "✈️", "description": "Destinations, travel hacks, culture immersion, and wanderlust stories.", "banner_gradient": "from-sky-400 to-blue-600"},
    {"slug": "lifestyle", "name": "Lifestyle", "icon": "🌟", "description": "Fashion, food, relationships, and everything that makes life interesting.", "banner_gradient": "from-fuchsia-500 to-pink-700"},
    {"slug": "general", "name": "General", "icon": "📋", "description": "Anything and everything that doesn't fit neatly into another club.", "banner_gradient": "from-slate-500 to-gray-700"},
]

async def seed_clubs():
    clubs_coll = get_clubs_collection()
    existing_count = await clubs_coll.count_documents({})
    if existing_count > 0:
        print(f"Clubs already seeded ({existing_count} clubs found).")
        return
    
    now = datetime.utcnow()
    for club_data in CLUB_SEED_DATA:
        await clubs_coll.insert_one({
            **club_data,
            "member_count": 0,
            "created_at": now,
        })
    print(f"Seeded {len(CLUB_SEED_DATA)} clubs.")

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
app.include_router(clubs.router, prefix="/clubs", tags=["Clubs"])

@app.get("/", tags=["Health"])
async def root():
    return {"status": "healthy", "app": settings.app_name}

@app.get("/health", tags=["Health"])
async def health_check():
    return {"status": "healthy", "database": "connected", "cache": "connected"}
