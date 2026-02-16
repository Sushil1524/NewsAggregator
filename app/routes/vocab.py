from typing import List
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from datetime import datetime
from app.dependencies import get_current_user_required
from app.models.user import UserResponse, VocabCard
from app.db import get_supabase

router = APIRouter()

class PracticeComplete(BaseModel):
    words: List[str]
    time_spent_minutes: int

class VocabProgress(BaseModel):
    total_cards: int
    cards_by_level: dict
    streak: int
    points: int

@router.get("/today", response_model=List[VocabCard])
async def get_today_vocab(current_user: UserResponse = Depends(get_current_user_required)):
    supabase = get_supabase()
    result = supabase.table("users").select("vocab_cards, daily_practice_target").eq("id", current_user.id).execute()
    if not result.data:
        return []
    cards = result.data[0].get("vocab_cards", [])
    target = result.data[0].get("daily_practice_target", 10)
    sorted_cards = sorted(cards, key=lambda x: x.get("level", 1))
    return [VocabCard(**c) for c in sorted_cards[:target]]

@router.post("/practice/done")
async def practice_done(practice_data: PracticeComplete, current_user: UserResponse = Depends(get_current_user_required)):
    supabase = get_supabase()
    result = supabase.table("users").select("vocab_cards, gamification").eq("id", current_user.id).execute()
    if not result.data:
        return {"message": "User not found"}
    
    cards = result.data[0].get("vocab_cards", [])
    gamification = result.data[0].get("gamification", {})
    
    for card in cards:
        if card.get("word") in practice_data.words:
            card["level"] = min(5, card.get("level", 1) + 1)
    
    points_earned = len(practice_data.words) * 5 + practice_data.time_spent_minutes
    gamification["points"] = gamification.get("points", 0) + points_earned
    
    today = datetime.utcnow().date()
    last_practice = gamification.get("last_read_date")
    if last_practice:
        from datetime import date
        last_date = date.fromisoformat(last_practice) if isinstance(last_practice, str) else last_practice
        if (today - last_date).days == 1:
            gamification["streak"] = gamification.get("streak", 0) + 1
        elif (today - last_date).days > 1:
            gamification["streak"] = 1
    else:
        gamification["streak"] = 1
    
    gamification["last_read_date"] = today.isoformat()
    
    supabase.table("users").update({
        "vocab_cards": cards,
        "gamification": gamification
    }).eq("id", current_user.id).execute()
    
    return {
        "message": "Practice recorded",
        "points_earned": points_earned,
        "new_streak": gamification["streak"]
    }

@router.get("/progress", response_model=VocabProgress)
async def get_vocab_progress(current_user: UserResponse = Depends(get_current_user_required)):
    supabase = get_supabase()
    result = supabase.table("users").select("vocab_cards, gamification").eq("id", current_user.id).execute()
    if not result.data:
        return VocabProgress(total_cards=0, cards_by_level={}, streak=0, points=0)
    
    cards = result.data[0].get("vocab_cards", [])
    gamification = result.data[0].get("gamification", {})
    level_counts = {}
    for card in cards:
        level = card.get("level", 1)
        level_counts[str(level)] = level_counts.get(str(level), 0) + 1
    
    return VocabProgress(
        total_cards=len(cards),
        cards_by_level=level_counts,
        streak=gamification.get("streak", 0),
        points=gamification.get("points", 0),
    )

@router.post("/add")
async def add_vocab_card(card: VocabCard, current_user: UserResponse = Depends(get_current_user_required)):
    supabase = get_supabase()
    result = supabase.table("users").select("vocab_cards").eq("id", current_user.id).execute()
    if not result.data:
        return {"error": "User not found"}
    
    cards = result.data[0].get("vocab_cards", [])
    existing = [c for c in cards if c.get("word", "").lower() == card.word.lower()]
    if existing:
        return {"error": "Word already exists"}
    
    cards.append(card.model_dump())
    supabase.table("users").update({"vocab_cards": cards}).eq("id", current_user.id).execute()
    return {"message": "Card added"}
