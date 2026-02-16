import re
from datetime import datetime
from typing import Optional

def clean_html(text: str) -> str:
    return re.sub(r"<.*?>", "", text)

STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "must", "shall", "can", "need", "dare",
    "to", "of", "in", "for", "on", "with", "at", "by", "from", "as",
    "into", "through", "during", "before", "after", "above", "below",
    "between", "under", "again", "further", "then", "once", "and",
    "but", "or", "nor", "so", "yet", "both", "either", "neither",
    "not", "only", "own", "same", "than", "too", "very", "just",
    "this", "that", "these", "those", "it", "its", "he", "she", "they",
    "his", "her", "their", "who", "whom", "which", "what", "where",
    "when", "why", "how", "all", "each", "every", "any", "some",
}

def extract_tags_from_text(text: str, max_tags: int = 5) -> list[str]:
    words = re.findall(r"\b[a-zA-Z]{4,}\b", text.lower())

    freq = {}
    for word in words:
        if word not in STOPWORDS:
            freq[word] = freq.get(word, 0) + 1

    sorted_words = sorted(freq.items(), key=lambda x: x[1], reverse=True)
    return [word.capitalize() for word, _ in sorted_words[:max_tags]]

CATEGORIES = {
    "Technology": [
        "software", "artificial intelligence", "startup", "google", "microsoft",
        "apple", "programming", "digital", "gadget", "cyber", "robot", "browser",
        "app", "algorithm", "code", "linux", "windows", "android", "ios",
    ],
    "Business": [
        "business", "economy", "market", "stock", "trade", "company", "investment",
        "finance", "bank", "revenue", "inflation", "cpi", "sensex", "nifty",
        "corporate", "ceo", "merger", "acquisition", "profit", "loss",
        "manufacturing", "semiconductor",
    ],
    "Politics": [
        "government", "election", "parliament", "minister", "policy", "vote",
        "political", "democracy", "congress", "legislation", "senate", "law",
        "court", "supreme court", "president", "pm", "modi", "biden", "trump",
        "campaign", "party",
    ],
    "Sports": [
        "sports", "cricket", "football", "tennis", "olympics", "match", "player",
        "championship", "tournament", "score", "medal", "cup", "league",
        "athlete", "nba", "nfl", "fifa", "ipl",
    ],
    "Science": [
        "science", "research", "study", "discovery", "space", "nasa",
        "experiment", "scientist", "physics", "biology", "astronomy", "planet",
        "mars", "moon", "galaxy", "telescope",
    ],
    "Health": [
        "health", "medical", "doctor", "hospital", "disease", "vaccine",
        "treatment", "patient", "covid", "wellness", "virus", "cancer",
        "medicine", "nutrition", "mental health",
    ],
    "Entertainment": [
        "movie", "film", "music", "celebrity", "entertainment", "actor",
        "singer", "award", "hollywood", "bollywood", "cinema", "concert",
        "album", "netflix", "streaming",
    ],
    "India": [
        "delhi", "mumbai", "bengaluru", "chennai", "kolkata", "hyderabad",
        "indian", "rupee", "lok sabha", "rajya sabha", "karnataka",
        "maharashtra", "kerala",
    ],
    "World": [
        "international", "global", "united nations", "europe", "china",
        "russia", "america", "foreign", "diplomatic", "ukraine", "war",
        "conflict", "airport", "flight", "aviation", "protest", "border",
        "treaty", "climate summit",
    ],
    "Environment": [
        "climate", "environment", "pollution", "carbon", "renewable",
        "sustainability", "ecosystem", "wildlife", "conservation",
        "global warming", "emissions", "energy",
    ],
}

def categorize_article(title: str, content: str) -> str:
    title_lower = title.lower()
    text_lower = (title + " " + content).lower()

    scores = {}
    for category, keywords in CATEGORIES.items():
        score = 0
        for kw in keywords:
            if kw in title_lower:
                score += 3
            elif kw in text_lower:
                score += 1
        scores[category] = score

    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "Other"

def estimate_reading_time(text: str, wpm: int = 200) -> int:
    if not text:
        return 1
    return max(1, round(len(text.split()) / wpm))

def format_datetime(dt: Optional[datetime]) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S") if dt else ""
