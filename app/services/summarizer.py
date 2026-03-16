import aiohttp
import re
from typing import List
from app.config import get_settings
from app.utils.helpers import categorize_article

settings = get_settings()
HF_API = "https://api-inference.huggingface.co/models/"

async def summarize_text(text: str) -> str:
    if not text or len(text.strip()) < 100:
        return text[:500] if text else ""

    if not settings.huggingface_api_key:
        return text[:500]

    url = f"{HF_API}{settings.huggingface_model}"
    headers = {"Authorization": f"Bearer {settings.huggingface_api_key}"}
    payload = {
        "inputs": text[:5000],
        "parameters": {"max_length": 450, "min_length": 100, "do_sample": False},
        "options": {"wait_for_model": True},
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                if resp.status != 200:
                    return text[:500]
                
                result = await resp.json()

                if isinstance(result, list) and len(result) > 0:
                    summary = result[0].get("summary_text", text[:500]).strip()
                    last_punctuation = max(summary.rfind('.'), summary.rfind('!'), summary.rfind('?'))
                    
                    if last_punctuation != -1 and last_punctuation > len(summary) * 0.3:
                        summary = summary[:last_punctuation + 1]
                        
                    sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+(?=[A-Z0-9])', summary) if s.strip()]
                    if len(sentences) > 1:
                        summary = "\n\n".join([f"• {s}" for s in sentences])
                        
                    return summary

                return text[:500]
    except Exception:
        return text[:500]

async def analyze_sentiment(text: str) -> str:
    if not text:
        return "neutral"

    if settings.huggingface_api_key:
        result = await _hf_sentiment(text[:512])
        if result:
            return result

    return _keyword_sentiment(text)

async def _hf_sentiment(text: str) -> str | None:
    url = f"{HF_API}{settings.huggingface_sentiment_model}"
    headers = {"Authorization": f"Bearer {settings.huggingface_api_key}"}
    payload = {"inputs": text, "options": {"wait_for_model": True}}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    return None
                result = await resp.json()

                if isinstance(result, list) and result and isinstance(result[0], list):
                    best = max(result[0], key=lambda x: x.get("score", 0))
                    label = best.get("label", "").upper()

                    if "POSITIVE" in label:
                        return "positive"
                    if "NEGATIVE" in label:
                        return "negative"
                    return "neutral"
                
                elif isinstance(result, list) and result and isinstance(result[0], dict):
                     if "label" in result[0]:
                        best = max(result, key=lambda x: x.get("score", 0))
                        label = best.get("label", "").upper()
                        if "POSITIVE" in label: return "positive"
                        if "NEGATIVE" in label: return "negative"
                        return "neutral"

    except Exception:
        pass

    return None

async def classify_text(text: str, candidate_labels: List[str]) -> str:
    if not text or not candidate_labels:
        return "Other"
    
    if not settings.huggingface_api_key:
        return "Other"

    url = f"{HF_API}{settings.huggingface_classification_model}"
    headers = {"Authorization": f"Bearer {settings.huggingface_api_key}"}
    payload = {
        "inputs": text[:1000], 
        "parameters": {"candidate_labels": candidate_labels},
        "options": {"wait_for_model": True}
    }

    try:
         async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                if resp.status != 200:
                    if resp.status != 410:
                        print(f"Classification API Error: {resp.status}")
                    return categorize_article(text, "")
                
                result = await resp.json()
                   
                if isinstance(result, dict) and "labels" in result and "scores" in result:
                    labels = result["labels"]
                    scores = result["scores"]
                    if labels and scores:
                        return labels[0]
                
                print(f"Classification unexpected result: {result}")
                return "Other"
    except Exception as e:
        print(f"Classification Exception: {e}")
        return categorize_article(text, "")

def _keyword_sentiment(text: str) -> str:
    text_lower = text.lower()

    POSITIVE = {
        "success": 2, "breakthrough": 2, "profit": 2, "surge": 2, "victory": 2,
        "triumph": 2, "excellent": 2, "amazing": 2, "win": 2, "peace": 2,
        "growth": 1, "gain": 1, "good": 1, "great": 1, "best": 1,
        "boost": 1, "recovery": 1, "deal": 1, "agreement": 1, "strong": 1,
        "upgrade": 1, "rally": 1, "innovative": 1, "promising": 1,
    }

    NEGATIVE = {
        "fail": 2, "failure": 2, "crash": 2, "crisis": 2, "disaster": 2,
        "death": 2, "kill": 2, "war": 2, "attack": 2, "conflict": 2,
        "scandal": 2, "corruption": 2, "collapse": 2, "fraud": 2, "layoff": 2,
        "terrible": 2, "loss": 2,
        "bad": 1, "poor": 1, "warning": 1, "threat": 1, "decline": 1,
        "drop": 1, "plunge": 1, "risk": 1, "ban": 1, "cancel": 1, "delay": 1,
    }

    pos_score = sum(w for word, w in POSITIVE.items() if word in text_lower)
    neg_score = sum(w for word, w in NEGATIVE.items() if word in text_lower)

    if pos_score > neg_score:
        return "positive"
    if neg_score > pos_score:
        return "negative"
    return "neutral"
