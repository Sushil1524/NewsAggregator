import aiohttp
import asyncio
import re
from typing import List, Tuple
from app.config import get_settings
from app.utils.helpers import categorize_article, strip_bullets

settings = get_settings()
HF_API = "https://api-inference.huggingface.co/models/"

# Minimum HF classification confidence to trust the model result
CLASSIFICATION_MIN_CONFIDENCE = 0.35

# ---------------------------------------------------------------------------
# Internal label mapping for zero-shot classification.
# Keys are the EXACT category names stored in DB / shown on frontend.
# Values are richer descriptive phrases sent to BART-MNLI for better accuracy.
# The result is ALWAYS mapped BACK to the key before being returned.
# ---------------------------------------------------------------------------
_LABEL_TO_DESCRIPTION: dict[str, str] = {
    "Technology":    "technology, computing, artificial intelligence, and gadgets",
    "Politics":      "politics, government, elections, and international diplomacy",
    "Business":      "business, finance, economy, markets, and corporate news",
    "Health":        "health, medicine, disease, healthcare, and wellness",
    "Sports":        "sports, athletics, football, cricket, and competitions",
    "Entertainment": "entertainment, movies, music, celebrities, and pop culture",
    "Science":       "science, research, space exploration, and scientific discoveries",
    "Crime":         "crime, law enforcement, criminal justice, and legal proceedings",
    "Education":     "education, schools, universities, exams, and academic news",
    "Environment":   "environment, climate change, pollution, and sustainability",
    "Travel":        "travel, tourism, destinations, and airlines",
    "Lifestyle":     "lifestyle, fashion, food, relationships, and personal wellness",
    "General":       "general news, miscellaneous topics, and public interest stories",
}

# Reverse map: description → short label (built at module load time)
_DESCRIPTION_TO_LABEL: dict[str, str] = {v: k for k, v in _LABEL_TO_DESCRIPTION.items()}


def _build_candidate_descriptions(category_names: List[str]) -> List[str]:
    """Convert a list of short category names to their richer HF descriptions."""
    return [_LABEL_TO_DESCRIPTION.get(name, name) for name in category_names]


def _map_description_back(description: str) -> str:
    """Map an HF result description back to the short category name."""
    # Exact match first
    if description in _DESCRIPTION_TO_LABEL:
        return _DESCRIPTION_TO_LABEL[description]
    # Fuzzy: check if any short label appears in the description
    for label, desc in _LABEL_TO_DESCRIPTION.items():
        if description.lower() == desc.lower():
            return label
    # Fallback: try to match the raw description as a title-cased label
    title_cased = description.strip().title()
    if title_cased in _LABEL_TO_DESCRIPTION:
        return title_cased
    return description  # Return as-is; caller will normalise


# ---------------------------------------------------------------------------
# Summarisation
# ---------------------------------------------------------------------------

async def summarize_text(title: str, text: str) -> Tuple[str, str]:
    """
    Summarise an article using HuggingFace BART.

    Args:
        title: Article headline (used to anchor the summary).
        text:  Cleaned article body text.

    Returns:
        (summary_text, summary_source) where source is one of:
        "ai" | "extractive" | "rss" | "truncated"
    """
    combined = f"{title}. {text}".strip() if title else text.strip()

    if not combined or len(combined.split()) < 30:
        return (_truncate_to_sentences(combined, max_chars=900), "truncated")

    if not settings.huggingface_api_key:
        # No API key — use local extractive summariser
        return (_extractive_summary(combined, max_sentences=4), "extractive")

    url = f"{HF_API}{settings.huggingface_model}"
    headers = {"Authorization": f"Bearer {settings.huggingface_api_key}"}
    payload = {
        "inputs": combined[:5000],
        "parameters": {
            "max_length": 400,
            "min_length": 130,
            "do_sample": False,
            "no_repeat_ngram_size": 3,
        },
        "options": {"wait_for_model": True},
    }

    backoffs = [5, 10, 15]  # seconds between retries
    for attempt in range(3):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url, headers=headers, json=payload,
                    timeout=aiohttp.ClientTimeout(total=90)
                ) as resp:
                    if resp.status == 503:
                        # Model loading — wait longer on each attempt
                        wait = backoffs[attempt]
                        print(f"[summarizer] HF model loading, waiting {wait}s (attempt {attempt+1})")
                        await asyncio.sleep(wait)
                        continue
                    if resp.status != 200:
                        body = await resp.text()
                        print(f"[summarizer] HF error {resp.status}: {body[:200]}")
                        break

                    result = await resp.json()

                    if isinstance(result, list) and result:
                        raw = result[0].get("summary_text", "").strip()
                        if raw:
                            summary = strip_bullets(raw)
                            summary = _trim_to_last_sentence(summary)
                            if len(summary.split()) >= 20:
                                return (summary, "ai")

        except asyncio.TimeoutError:
            if attempt < 2:
                await asyncio.sleep(backoffs[attempt])
            continue
        except Exception as e:
            print(f"[summarizer] Exception: {e}")
            break

    # HF failed — fall back to local extractive summariser
    return (_extractive_summary(combined, max_sentences=4), "extractive")


def _trim_to_last_sentence(text: str) -> str:
    """Trim to the last complete sentence boundary."""
    last_punct = max(text.rfind("."), text.rfind("!"), text.rfind("?"))
    if last_punct > len(text) * 0.3:
        return text[: last_punct + 1].strip()
    return text.strip()


def _truncate_to_sentences(text: str, max_chars: int = 900) -> str:
    """Return up to max_chars, stopping at a sentence boundary."""
    if len(text) <= max_chars:
        return text.strip()
    truncated = text[:max_chars]
    last_punct = max(truncated.rfind("."), truncated.rfind("!"), truncated.rfind("?"))
    if last_punct > 50:
        return truncated[: last_punct + 1].strip()
    return truncated.strip() + "…"


def _extractive_summary(text: str, max_sentences: int = 4) -> str:
    """
    Simple extractive summariser: score sentences by TF-IDF-like word
    frequency and return the top-ranked ones in original order.
    Falls back to the first N sentences if scoring produces nothing useful.
    """
    # Split into sentences
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    sentences = [s.strip() for s in sentences if len(s.split()) >= 8]

    if not sentences:
        return _truncate_to_sentences(text, max_chars=900)

    if len(sentences) <= max_sentences:
        return " ".join(sentences)

    # Word frequency (lowercase, no stopwords)
    _STOP = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been",
        "have", "has", "had", "do", "does", "did", "will", "would",
        "could", "should", "to", "of", "in", "for", "on", "with",
        "at", "by", "from", "and", "but", "or", "not", "this", "that",
        "it", "its", "he", "she", "they", "their", "who", "what",
        "said", "says", "also", "just", "more", "than", "over",
    }
    words = re.findall(r"\b[a-z]{4,}\b", text.lower())
    freq: dict[str, int] = {}
    for w in words:
        if w not in _STOP:
            freq[w] = freq.get(w, 0) + 1

    def score(sentence: str) -> float:
        tokens = re.findall(r"\b[a-z]{4,}\b", sentence.lower())
        if not tokens:
            return 0.0
        return sum(freq.get(t, 0) for t in tokens) / len(tokens)

    scored = sorted(enumerate(sentences), key=lambda x: score(x[1]), reverse=True)
    top_indices = sorted(i for i, _ in scored[:max_sentences])
    selected = [sentences[i] for i in top_indices]
    result = " ".join(selected)
    return _truncate_to_sentences(result, max_chars=1200)


# ---------------------------------------------------------------------------
# Sentiment Analysis
# ---------------------------------------------------------------------------

async def analyze_sentiment(title: str, text: str) -> str:
    """
    Analyse sentiment of an article.
    Sends `title + " " + text[:700]` for a richer signal.
    """
    combined = f"{title} {text[:700]}".strip() if title else text[:700].strip()
    if not combined:
        return "neutral"

    if settings.huggingface_api_key:
        result = await _hf_sentiment(combined[:600])
        if result:
            return result

    return _keyword_sentiment(combined)


async def _hf_sentiment(text: str) -> str | None:
    url = f"{HF_API}{settings.huggingface_sentiment_model}"
    headers = {"Authorization": f"Bearer {settings.huggingface_api_key}"}
    payload = {"inputs": text, "options": {"wait_for_model": True}}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url, headers=headers, json=payload,
                timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                if resp.status != 200:
                    return None
                result = await resp.json()

                if isinstance(result, list) and result and isinstance(result[0], list):
                    best = max(result[0], key=lambda x: x.get("score", 0))
                    label = best.get("label", "").upper()
                elif isinstance(result, list) and result and isinstance(result[0], dict):
                    best = max(result, key=lambda x: x.get("score", 0))
                    label = best.get("label", "").upper()
                else:
                    return None

                if "POSITIVE" in label:
                    return "positive"
                if "NEGATIVE" in label:
                    return "negative"
                return "neutral"

    except Exception:
        pass

    return None


# ---------------------------------------------------------------------------
# Category Classification
# ---------------------------------------------------------------------------

async def classify_text(
    title: str,
    text: str,
    candidate_labels: List[str],
    feed_category: str | None = None,
) -> str:
    """
    Zero-shot category classification using HuggingFace BART-MNLI.

    If `feed_category` is provided and it matches a valid short label, it is
    returned immediately without calling the API (fast-path shortcut).

    Candidate labels are sent as richer descriptive phrases internally;
    the result is always mapped back to the original short label.

    Falls back to keyword-based categorisation if:
    - API key is missing
    - API errors or timeouts
    - Top confidence score < CLASSIFICATION_MIN_CONFIDENCE
    """
    from app.utils.helpers import CATEGORIES

    # --- Feed-category fast path ---
    if feed_category and feed_category in CATEGORIES:
        return feed_category

    combined = f"{title} {text}".strip() if title else text.strip()
    if not combined or not candidate_labels:
        return "General"

    if not settings.huggingface_api_key:
        return categorize_article(title, text)

    # Build richer descriptions for HF but keep the short labels for lookup
    descriptions = _build_candidate_descriptions(candidate_labels)

    # --- Redis cache (keyed on title + first 200 chars of text) ---
    cache_key = None
    try:
        from app.db import cache_get, cache_set
        import hashlib
        cache_key = f"cls2:{hashlib.md5((title + combined[:200]).encode()).hexdigest()}"
        cached = await cache_get(cache_key)
        if cached:
            return cached
    except Exception:
        cache_key = None

    url = f"{HF_API}{settings.huggingface_classification_model}"
    headers = {"Authorization": f"Bearer {settings.huggingface_api_key}"}
    payload = {
        "inputs": combined[:1200],
        "parameters": {"candidate_labels": descriptions},
        "options": {"wait_for_model": True},
    }

    for attempt in range(3):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url, headers=headers, json=payload,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as resp:
                    if resp.status == 503:
                        await asyncio.sleep(2 ** attempt)
                        continue
                    if resp.status != 200:
                        if resp.status != 410:
                            print(f"[classify] API error: {resp.status}")
                        return categorize_article(title, text)

                    result = await resp.json()

                    if isinstance(result, dict) and "labels" in result and "scores" in result:
                        labels = result["labels"]   # these are the descriptions we sent
                        scores = result["scores"]
                        if labels and scores:
                            top_desc = labels[0]
                            top_score = scores[0]

                            # Map description → short label
                            short_label = _map_description_back(top_desc)

                            # Reject low-confidence results
                            if top_score < CLASSIFICATION_MIN_CONFIDENCE:
                                fallback = categorize_article(title, text)
                                print(
                                    f"[classify] Low confidence {top_score:.2f} "
                                    f"({short_label}) — keyword fallback: {fallback}"
                                )
                                return fallback

                            # Cache the short label
                            if cache_key:
                                try:
                                    await cache_set(cache_key, short_label, expire_seconds=3600)
                                except Exception:
                                    pass

                            return short_label

                    return categorize_article(title, text)

        except asyncio.TimeoutError:
            if attempt < 2:
                await asyncio.sleep(2 ** attempt)
            continue
        except Exception as e:
            print(f"[classify] Exception: {e}")
            break

    return categorize_article(title, text)


# ---------------------------------------------------------------------------
# Keyword sentiment fallback
# ---------------------------------------------------------------------------

def _keyword_sentiment(text: str) -> str:
    text_lower = text.lower()

    POSITIVE = {
        "success": 2, "breakthrough": 2, "profit": 2, "surge": 2, "victory": 2,
        "triumph": 2, "excellent": 2, "amazing": 2, "win": 2, "peace": 2,
        "growth": 1, "gain": 1, "good": 1, "great": 1, "best": 1,
        "boost": 1, "recovery": 1, "deal": 1, "agreement": 1, "strong": 1,
        "upgrade": 1, "rally": 1, "innovative": 1, "promising": 1,
        "record": 1, "historic": 1, "milestone": 1, "approved": 1,
    }

    NEGATIVE = {
        "fail": 2, "failure": 2, "crash": 2, "crisis": 2, "disaster": 2,
        "death": 2, "kill": 2, "war": 2, "attack": 2, "conflict": 2,
        "scandal": 2, "corruption": 2, "collapse": 2, "fraud": 2, "layoff": 2,
        "terrible": 2, "loss": 2, "killed": 2, "dead": 2, "casualties": 2,
        "bad": 1, "poor": 1, "warning": 1, "threat": 1, "decline": 1,
        "drop": 1, "plunge": 1, "risk": 1, "ban": 1, "cancel": 1, "delay": 1,
        "fears": 1, "concern": 1, "accused": 1, "detained": 1, "arrested": 1,
        "sentenced": 1, "guilty": 1, "indicted": 1,
    }

    pos_score = sum(w for word, w in POSITIVE.items() if word in text_lower)
    neg_score = sum(w for word, w in NEGATIVE.items() if word in text_lower)

    if pos_score > neg_score:
        return "positive"
    if neg_score > pos_score:
        return "negative"
    return "neutral"
