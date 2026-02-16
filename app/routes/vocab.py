from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from datetime import datetime
from app.dependencies import get_current_user_required
from app.models.user import UserResponse, VocabCard
from app.db import get_users_collection

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
    users_coll = get_users_collection()
    user = await users_coll.find_one({"id": current_user.id})
    if not user:
        return []
        
    cards = user.get("vocab_cards", [])
    target = user.get("daily_practice_target", 10)
    sorted_cards = sorted(cards, key=lambda x: x.get("level", 1))
    return [VocabCard(**c) for c in sorted_cards[:target]]

@router.post("/practice/done")
async def practice_done(practice_data: PracticeComplete, current_user: UserResponse = Depends(get_current_user_required)):
    users_coll = get_users_collection()
    user = await users_coll.find_one({"id": current_user.id})
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    
    cards = user.get("vocab_cards", [])
    gamification = user.get("gamification", {})
    
    card_map = {c.get("word"): c for c in cards}
    for word in practice_data.words:
        if word in card_map:
            card_map[word]["level"] = min(5, card_map[word].get("level", 1) + 1)
    
    points_earned = len(practice_data.words) * 5 + practice_data.time_spent_minutes
    gamification["points"] = gamification.get("points", 0) + points_earned
    
    gamification["total_reading_time_minutes"] = gamification.get("total_reading_time_minutes", 0) + practice_data.time_spent_minutes
    
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
    
    await users_coll.update_one(
        {"id": current_user.id},
        {"$set": {
            "vocab_cards": cards,
            "gamification": gamification,
            "updated_at": datetime.utcnow().isoformat()
        }}
    )
    
    return {
        "message": "Practice recorded",
        "points_earned": points_earned,
        "new_streak": gamification["streak"]
    }

@router.get("/progress", response_model=VocabProgress)
async def get_vocab_progress(current_user: UserResponse = Depends(get_current_user_required)):
    users_coll = get_users_collection()
    user = await users_coll.find_one({"id": current_user.id})
    if not user:
        return VocabProgress(total_cards=0, cards_by_level={}, streak=0, points=0)
    
    cards = user.get("vocab_cards", [])
    gamification = user.get("gamification", {})
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
    users_coll = get_users_collection()
    user = await users_coll.find_one({"id": current_user.id})
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    
    cards = user.get("vocab_cards", [])
    if any(c.get("word", "").lower() == card.word.lower() for c in cards):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Word already exists")
    
    await users_coll.update_one(
        {"id": current_user.id},
        {"$push": {"vocab_cards": card.model_dump()}, "$set": {"updated_at": datetime.utcnow().isoformat()}}
    )
    return {"message": "Card added"}
