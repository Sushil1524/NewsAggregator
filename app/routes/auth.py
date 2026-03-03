from datetime import datetime
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from app.dependencies import get_current_user_required
from app.models.user import UserCreate, UserUpdate, UserResponse, Gamification, NotificationSettings, PushSubscription
from app.db import get_users_collection
from app.utils.security import hash_password, verify_password, create_tokens, decode_token

router = APIRouter()

class LoginRequest(BaseModel):
    identifier: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"

class RefreshRequest(BaseModel):
    refresh_token: str

@router.post("/register", response_model=TokenResponse)
async def register(user_data: UserCreate):
    users_coll = get_users_collection()
    
    if await users_coll.find_one({"email": user_data.email}):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered")
    
    if await users_coll.find_one({"username": user_data.username}):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Username already taken")
    
    user_id = str(uuid4())
    now = datetime.utcnow().isoformat()
    
    user_db = {
        "id": user_id,
        "email": user_data.email,
        "username": user_data.username,
        "password_hash": hash_password(user_data.password),
        "full_name": user_data.full_name,
        "dob": user_data.dob.isoformat() if user_data.dob else None,
        "role": "user",
        "vocab_proficiency": user_data.vocab_proficiency,
        "daily_practice_target": user_data.daily_practice_target,
        "news_preferences": {},
        "preferred_languages": ["en"],
        "notification_settings": NotificationSettings().model_dump(),
        "gamification": Gamification().model_dump(),
        "vocab_cards": [],
        "bookmarks": [],
        "reading_history": [],
        "created_at": now,
        "updated_at": now,
    }
    
    await users_coll.insert_one(user_db)
    
    return create_tokens(user_id, user_data.email)

@router.post("/login", response_model=TokenResponse)
async def login(login_data: LoginRequest):
    users_coll = get_users_collection()
    
    user = await users_coll.find_one({
        "$or": [
            {"email": login_data.identifier},
            {"username": login_data.identifier}
        ]
    })
    
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    
    if not verify_password(login_data.password, user["password_hash"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    
    await users_coll.update_one(
        {"id": user["id"]},
        {"$set": {"last_login_at": datetime.utcnow().isoformat()}}
    )
    
    return create_tokens(user["id"], user["email"])

@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(refresh_data: RefreshRequest):
    token_data = decode_token(refresh_data.refresh_token)
    if not token_data or token_data.token_type != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")
    return create_tokens(token_data.user_id, token_data.email)

@router.get("/me", response_model=UserResponse)
async def get_me(current_user: UserResponse = Depends(get_current_user_required)):
    return current_user

@router.put("/me", response_model=UserResponse)
async def update_me(update_data: UserUpdate, current_user: UserResponse = Depends(get_current_user_required)):
    users_coll = get_users_collection()
    
    update_dict = {k: v for k, v in update_data.model_dump().items() if v is not None}
    update_dict["updated_at"] = datetime.utcnow().isoformat()
    
    if "notification_settings" in update_dict:
        update_dict["notification_settings"] = update_dict["notification_settings"].model_dump()
    
    await users_coll.update_one({"id": current_user.id}, {"$set": update_dict})
    
    user = await users_coll.find_one({"id": current_user.id})
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        
    return UserResponse(
        id=user["id"],
        email=user["email"],
        username=user["username"],
        full_name=user.get("full_name"),
        dob=user.get("dob"),
        role=user["role"],
        vocab_proficiency=user["vocab_proficiency"],
        daily_practice_target=user["daily_practice_target"],
        news_preferences=user.get("news_preferences", {}),
        preferred_languages=user.get("preferred_languages", ["en"]),
        gamification=Gamification(**user.get("gamification", {})),
        bookmarks=user.get("bookmarks", []),
        joined_clubs=user.get("joined_clubs", []),
        created_at=user["created_at"],
    )

@router.post("/logout")
async def logout(current_user: UserResponse = Depends(get_current_user_required)):
    return {"message": "Successfully logged out"}

@router.post("/push/subscribe")
async def subscribe_push(sub: PushSubscription, current_user: UserResponse = Depends(get_current_user_required)):
    users_coll = get_users_collection()

    await users_coll.update_one(
        {"id": current_user.id},
        {"$addToSet": {"push_subscriptions": sub.model_dump()}}
    )
    return {"message": "Subscribed to push notifications"}

@router.delete("/push/unsubscribe")
async def unsubscribe_push(endpoint: str, current_user: UserResponse = Depends(get_current_user_required)):
    users_coll = get_users_collection()

    await users_coll.update_one(
        {"id": current_user.id},
        {"$pull": {"push_subscriptions": {"endpoint": endpoint}}}
    )
    return {"message": "Unsubscribed from push notifications"}

@router.get("/me/stats")
async def get_my_stats(current_user: UserResponse = Depends(get_current_user_required)):
    users_coll = get_users_collection()
    
    user = await users_coll.find_one({"id": current_user.id})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
        
    g = user.get("gamification", {})
    total_articles = g.get("total_articles_read", 0)
    streak = g.get("streak", 0)
    current_badges = set(g.get("badges", []))
    new_badges = []
    
    if total_articles >= 10 and "Novice Reader" not in current_badges:
        new_badges.append("Novice Reader")
    if total_articles >= 50 and "Avid Reader" not in current_badges:
        new_badges.append("Avid Reader")
    if total_articles >= 100 and "Scholar" not in current_badges:
        new_badges.append("Scholar")
    if streak >= 7 and "Week Streak" not in current_badges:
        new_badges.append("Week Streak")
    if streak >= 30 and "Month Streak" not in current_badges:
        new_badges.append("Month Streak")
        
    if new_badges:
        all_badges = list(current_badges) + new_badges
        await users_coll.update_one(
            {"id": current_user.id},
            {"$set": {"gamification.badges": all_badges}}
        )
        g["badges"] = all_badges
        
    stats = {
        "points": g.get("points", 0),
        "streak": streak,
        "articles_read_today": g.get("articles_read_today", 0),
        "total_articles_read": total_articles,
        "total_reading_time_minutes": g.get("total_reading_time_minutes", 0),
        "badges": g.get("badges", []),
        "newly_unlocked": new_badges
    }
    
    return stats
