from datetime import datetime
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from app.dependencies import get_current_user_required
from app.models.user import UserCreate, UserUpdate, UserResponse, Gamification, NotificationSettings
from app.db import get_supabase
from app.utils.security import hash_password, verify_password, create_tokens, decode_token

router = APIRouter()

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"

class RefreshRequest(BaseModel):
    refresh_token: str

@router.post("/register", response_model=TokenResponse)
async def register(user_data: UserCreate):
    supabase = get_supabase()
    
    existing = supabase.table("users").select("id").eq("email", user_data.email).execute()
    if existing.data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered")
    
    existing = supabase.table("users").select("id").eq("username", user_data.username).execute()
    if existing.data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Username already taken")
    
    user_id = str(uuid4())
    now = datetime.utcnow().isoformat()
    
    user_db = {
        "id": user_id,
        "email": user_data.email,
        "username": user_data.username,
        "password_hash": hash_password(user_data.password),
        "full_name": user_data.full_name,
        "role": "user",
        "vocab_proficiency": "intermediate",
        "daily_practice_target": 10,
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
    
    result = supabase.table("users").insert(user_db).execute()
    if not result.data:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create user")
    
    return create_tokens(user_id, user_data.email)

@router.post("/login", response_model=TokenResponse)
async def login(login_data: LoginRequest):
    supabase = get_supabase()
    result = supabase.table("users").select("*").eq("email", login_data.email).execute()
    
    if not result.data:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
    
    user = result.data[0]
    if not verify_password(login_data.password, user["password_hash"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
    
    supabase.table("users").update({
        "last_login_at": datetime.utcnow().isoformat()
    }).eq("id", user["id"]).execute()
    
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
    supabase = get_supabase()
    update_dict = {k: v for k, v in update_data.model_dump().items() if v is not None}
    update_dict["updated_at"] = datetime.utcnow().isoformat()
    
    if "notification_settings" in update_dict:
        update_dict["notification_settings"] = update_dict["notification_settings"].model_dump()
    
    result = supabase.table("users").update(update_dict).eq("id", current_user.id).execute()
    if not result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    
    result = supabase.table("users").select("*").eq("id", current_user.id).execute()
    user = result.data[0]
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
        created_at=user["created_at"],
    )

@router.post("/logout")
async def logout(current_user: UserResponse = Depends(get_current_user_required)):
    return {"message": "Successfully logged out"}
