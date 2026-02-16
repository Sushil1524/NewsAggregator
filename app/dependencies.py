from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional

from app.utils.security import decode_token
from app.models.user import UserResponse, Gamification
from app.db import get_supabase

security = HTTPBearer()

async def get_current_user(user_id: str) -> UserResponse:
    supabase = get_supabase()
    result = supabase.table("users").select("*").eq("id", user_id).execute()
    
    if not result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    
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

async def get_current_user_required(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> UserResponse:
    token = credentials.credentials
    token_data = decode_token(token)
    
    if not token_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    return await get_current_user(token_data.user_id)

async def get_current_user_optional(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(HTTPBearer(auto_error=False))
) -> Optional[UserResponse]:
    if not credentials:
        return None
    
    token_data = decode_token(credentials.credentials)
    if not token_data:
        return None
    
    try:
        return await get_current_user(token_data.user_id)
    except HTTPException:
        return None

async def require_admin(user: UserResponse = Depends(get_current_user_required)) -> UserResponse:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user
