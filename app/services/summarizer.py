import aiohttp
import asyncio
import re
from typing import List, Tuple
from app.config import get_settings
from app.utils.helpers import categorize_article, strip_bullets

settings = get_settings()
HF_API = "https://router.huggingface.co/hf-inference/models/"

# Minimum HF classification confidence to trust the model result
CLASSIFICATION_MIN_CONFIDENCE = 0.35
SENTIMENT_MIN_CONFIDENCE = 0.60

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
    if description in _DESCRIPTION_TO_LABEL:
        return _DESCRIPTION_TO_LABEL[description]
    for label, desc in _LABEL_TO_DESCRIPTION.items():
        if description.lower() == desc.lower():
            return label
    title_cased = description.strip().title()
    if title_cased in _LABEL_TO_DESCRIPTION:
        return title_cased
    return description 

# ---------------------------------------------------------------------------
# Summarisation
# ---------------------------------------------------------------------------

async def summarize_text(title: str, text: str) -> Tuple[str, str]:
    combined = f"{title}. {text}".strip() if title else text.strip()

    if not combined or len(combined.split()) < 30:
        return (_truncate_to_sentences(combined, max_chars=900), "truncated")

    if not settings.huggingface_api_key:
        return (_extractive_summary(combined, max_sentences=4), "extractive")

    url = f"{HF_API}{settings.huggingface_model}"
    headers = {"Authorization": f"Bearer {settings.huggingface_api_key}"}
    input_words = len(combined.split())
    calc_min = max(25, min(60, input_words // 3))
    calc_max = max(calc_min + 30, min(250, input_words // 2 + 40))

    payload = {
        "inputs": combined[:5000],
        "parameters": {
            "max_length": calc_max,
            "min_length": calc_min,
            "do_sample": False,
            "no_repeat_ngram_size": 3,
        },
        "options": {"wait_for_model": True},
    }

    backoffs = [3, 6, 10]  # seconds between retries
    for attempt in range(3):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url, headers=headers, json=payload,
                    timeout=aiohttp.ClientTimeout(total=45)
                ) as resp:
                    if resp.status in (502, 503, 504):
                        wait = backoffs[attempt]
                        print(f"[summarizer] HF gateway error {resp.status}, retrying in {wait}s (attempt {attempt+1})")
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
                            cleaned_ai = re.sub(
                                r"(?i)(?:for confidential support\s+)?(?:call|contact)\s+(?:the\s+)?samaritans.*",
                                "", raw
                            ).strip()
                            cleaned_ai = re.sub(r"(?i)\b(?:in the us,?|in the uk,?)\s+call\s+\d+.*", "", cleaned_ai).strip()
                            summary = strip_bullets(cleaned_ai)
                            summary = _trim_to_last_sentence(summary)
                            if len(summary.split()) >= 15:
                                return (summary, "ai")

        except asyncio.TimeoutError:
            if attempt < 2:
                await asyncio.sleep(backoffs[attempt])
            continue
        except Exception as e:
            print(f"[summarizer] Exception: {e}")
            break

    return (_extractive_summary(combined, max_sentences=3), "extractive")

_WIRE_PREAMBLE_PATTERNS = [
    # Wire datelines e.g. "WASHINGTON (Reuters) —", "NEW DELHI: ", "LONDON (AP) -"
    r"^(?:[A-Z\s]{2,25}\s*(?:\([^)]+\))?\s*[-—–:]\s*)",
    # Bylines e.g. "By John Smith | Updated 10:00 AM —"
    r"^(?:By\s+[\w\s.-]+(?:\s*\|\s*[\w\s,:-]+)?\s*[-—–:]?\s*)",
    # Datetime headers e.g. "Published: Jan 25, 2026 -"
    r"^(?:Published|Updated|Last modified)\s*:\s*.*?\s*[-—–]\s*",
]

_COMMON_ABBREVS = [
    "U.S.", "U.K.", "E.U.", "Dr.", "Mr.", "Mrs.", "Ms.", "Prof.",
    "Gov.", "Sen.", "Rep.", "Gen.", "Col.", "Lt.", "Sgt.", "St.",
    "Inc.", "Ltd.", "Corp.", "Co.", "vs.", "No.", "Jan.", "Feb.",
    "Mar.", "Apr.", "Aug.", "Sept.", "Oct.", "Nov.", "Dec.", "Rs.",
    "i.e.", "e.g.", "a.m.", "p.m."
]

def _strip_wire_preamble(text: str) -> str:
    if not text:
        return ""
    cleaned = text.strip()
    for pattern in _WIRE_PREAMBLE_PATTERNS:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE).strip()
    return cleaned

def _split_into_sentences(text: str) -> list[str]:
    if not text:
        return []
    temp = text.strip()
    for i, abbr in enumerate(_COMMON_ABBREVS):
        temp = re.sub(re.escape(abbr), f"__ABBR{i}__", temp, flags=re.IGNORECASE)
    # Mask decimal numbers like 3.5, 20.4
    temp = re.sub(r"(\d+)\.(\d+)", r"\1__DEC__\2", temp)

    # Split on sentence terminals
    parts = re.split(r"(?<=[.!?])\s+", temp)

    sentences = []
    for part in parts:
        # Restore masks
        for i, abbr in enumerate(_COMMON_ABBREVS):
            part = part.replace(f"__ABBR{i}__", abbr)
        part = part.replace("__DEC__", ".")
        clean_part = part.strip()
        if len(clean_part.split()) >= 6:  # meaningful sentence length
            sentences.append(clean_part)
    return sentences

def _trim_to_last_sentence(text: str) -> str:
    last_punct = max(text.rfind("."), text.rfind("!"), text.rfind("?"))
    if last_punct > len(text) * 0.3:
        return text[: last_punct + 1].strip()
    return text.strip()

def _truncate_to_sentences(text: str, max_chars: int = 900) -> str:
    if len(text) <= max_chars:
        return text.strip()
    truncated = text[:max_chars]
    last_punct = max(truncated.rfind("."), truncated.rfind("!"), truncated.rfind("?"))
    if last_punct > 50:
        return truncated[: last_punct + 1].strip()
    return truncated.strip() + "…"

def _extractive_summary(text: str, max_sentences: int = 3) -> str:
    cleaned_text = _strip_wire_preamble(text)
    sentences = _split_into_sentences(cleaned_text)

    if not sentences:
        return _truncate_to_sentences(cleaned_text, max_chars=900)

    if len(sentences) <= 2:
        return " ".join(sentences)

    _STOP = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been",
        "have", "has", "had", "do", "does", "did", "will", "would",
        "could", "should", "to", "of", "in", "for", "on", "with",
        "at", "by", "from", "and", "but", "or", "not", "this", "that",
        "it", "its", "he", "she", "they", "their", "who", "what",
        "said", "says", "also", "just", "more", "than", "over",
    }
    words = re.findall(r"\b[a-z]{4,}\b", cleaned_text.lower())
    freq: dict[str, int] = {}
    for w in words:
        if w not in _STOP:
            freq[w] = freq.get(w, 0) + 1

    def score(idx: int, sentence: str) -> float:
        tokens = re.findall(r"\b[a-z]{4,}\b", sentence.lower())
        if not tokens:
            return 0.0
        base = sum(freq.get(t, 0) for t in tokens) / len(tokens)
        lead_boost = 1.0 / (idx + 1)
        return base * (1.0 + lead_boost)

    scored = sorted(enumerate(sentences), key=lambda x: score(x[0], x[1]), reverse=True)
    top_indices = sorted(i for i, _ in scored[:max_sentences])
    selected = [sentences[i] for i in top_indices]

    if len(selected) >= 2:
        return "\n".join(f"• {s}" for s in selected)
    return " ".join(selected)

# ---------------------------------------------------------------------------
# Sentiment Analysis
# ---------------------------------------------------------------------------
async def analyze_sentiment(title: str, text: str) -> str:

    combined = f"{title} {text[:700]}".strip() if title else text[:700].strip()
    if not combined:
        return "neutral"
    # 1. Immediate Domain Check: Unmistakable fatal, violent, or conflict signals
    kw_result = _keyword_sentiment(combined)
    if kw_result == "negative":
        return "negative"

    # 2. HuggingFace 3-Class Sentiment Model
    if settings.huggingface_api_key:
        result = await _hf_sentiment(combined[:600])
        if result:
            return result

    return kw_result

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
                elif isinstance(result, list) and result and isinstance(result[0], dict):
                    best = max(result, key=lambda x: x.get("score", 0))
                else:
                    return None

                label = str(best.get("label", "")).strip().upper()
                score = float(best.get("score", 0.0))

                if score < 0.45:
                    return "neutral"

                if "POS" in label or label == "LABEL_2":
                    return "positive"
                if "NEG" in label or label == "LABEL_0":
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
    from app.utils.helpers import CATEGORIES

    if feed_category and feed_category in CATEGORIES:
        return feed_category

    combined = f"{title} {text}".strip() if title else text.strip()
    if not combined or not candidate_labels:
        return "General"

    if not settings.huggingface_api_key:
        return categorize_article(title, text)

    descriptions = _build_candidate_descriptions(candidate_labels)

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

                            short_label = _map_description_back(top_desc)

                            if top_score < CLASSIFICATION_MIN_CONFIDENCE:
                                fallback = categorize_article(title, text)
                                print(
                                    f"[classify] Low confidence {top_score:.2f} "
                                    f"({short_label}) — keyword fallback: {fallback}"
                                )
                                return fallback

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
# High-Accuracy Rule & Valence Sentiment Engine (News-Tailored)
# ---------------------------------------------------------------------------
_POS_WORDS: dict[str, int] = {
    # Strong positive (+2)
    "breakthrough": 2, "triumph": 2, "miracle": 2, "milestone": 2, "historic": 2,
    "peace": 2, "victory": 2, "rebound": 2, "cure": 2, "rescue": 2, "innovative": 2,
    "celebrate": 2, "celebrates": 2, "celebrated": 2, "celebration": 2,
    # Moderate positive (+1)
    "success": 1, "successful": 1, "profit": 1, "profits": 1, "profitable": 1,
    "surge": 1, "surged": 1, "surging": 1, "surges": 1,
    "growth": 1, "growing": 1, "gain": 1, "gains": 1, "gained": 1, "boost": 1, "boosted": 1, "boosting": 1,
    "recovery": 1, "recovered": 1, "recovering": 1, "deal": 1, "deals": 1, "agreement": 1, "agreements": 1,
    "approved": 1, "approval": 1, "strong": 1, "upgrade": 1, "upgraded": 1, "rally": 1, "rallied": 1, "rallies": 1,
    "promising": 1, "relief": 1, "relieved": 1, "progress": 1, "prosper": 1, "prosperity": 1,
    "revenue": 1, "revenues": 1, "accelerate": 1, "accelerated": 1, "accelerating": 1,
    "honored": 1, "award": 1, "awarded": 1, "awards": 1, "hope": 1, "hopeful": 1, "win": 1, "won": 1, "wins": 1,
}

_NEG_WORDS: dict[str, int] = {
    # Strong negative verbs, violence, fatalities (+2)
    "die": 2, "dies": 2, "dying": 2, "dead": 2, "death": 2, "deaths": 2, "deadly": 2,
    "fatality": 2, "fatalities": 2, "fatal": 2, "kill": 2, "kills": 2, "killed": 2, "killing": 2, "killer": 2,
    "murder": 2, "murders": 2, "murdered": 2, "murderer": 2, "hostility": 2, "hostilities": 2, "hostile": 2,
    "strike": 2, "strikes": 2, "striking": 2, "struck": 2,
    "attack": 2, "attacks": 2, "attacked": 2, "attacking": 2, "bomb": 2, "bombed": 2, "bombing": 2, "bombs": 2,
    "disaster": 2, "catastrophe": 2, "crisis": 2, "tragedy": 2, "tragic": 2,
    "massacre": 2, "genocide": 2, "war": 2, "terrorist": 2, "terrorism": 2,
    "hostage": 2, "hostages": 2, "crash": 2, "crashed": 2, "casualties": 2, "collapse": 2, "collapsed": 2,
    "devastation": 2, "devastated": 2, "devastating": 2,
    # Moderate negative (-1)
    "scandal": 1, "corruption": 1, "fraud": 1, "fraudulent": 1, "layoff": 1, "layoffs": 1,
    "loss": 1, "losses": 1, "warning": 1, "warns": 1, "warned": 1,
    "threat": 1, "threats": 1, "threaten": 1, "threatens": 1, "threatened": 1,
    "decline": 1, "declined": 1, "drop": 1, "dropped": 1, "plunge": 1, "plunged": 1,
    "risk": 1, "risks": 1, "ban": 1, "banned": 1, "cancel": 1, "canceled": 1, "cancelled": 1,
    "delay": 1, "delayed": 1, "fears": 1, "feared": 1, "concern": 1, "concerns": 1,
    "arrest": 1, "arrested": 1, "detained": 1, "guilty": 1, "indicted": 1, "sentenced": 1,
    "fail": 1, "failed": 1, "failure": 1, "injury": 1, "injured": 1, "injuries": 1,
    "damage": 1, "damaged": 1, "damages": 1, "struggle": 1, "struggles": 1, "struggling": 1,
}

_NEGATION_WORDS = {
    "no", "not", "never", "neither", "nor", "barely", "hardly", "scarcely",
    "without", "failed", "fails", "failure", "cannot", "cant", "wont",
    "dont", "didnt", "isnt", "arent", "wasnt", "werent", "hasnt", "havent",
}

def _keyword_sentiment(text: str) -> str:
    if not text:
        return "neutral"

    text_lower = text.lower()
    words = re.findall(r"\b[\w'-]+\b", text_lower)
    if not words:
        return "neutral"

    pos_score = 0
    neg_score = 0
    window = 3

    for i, word in enumerate(words):
        preceding = words[max(0, i - window):i]
        is_negated = any(p in _NEGATION_WORDS for p in preceding)

        if word in _POS_WORDS:
            weight = _POS_WORDS[word]
            if is_negated:
                neg_score += weight
            else:
                pos_score += weight

        elif word in _NEG_WORDS:
            weight = _NEG_WORDS[word]
            if not is_negated:
                neg_score += weight

    diff = pos_score - neg_score

    if neg_score >= 2 or (neg_score >= 1 and pos_score == 0):
        return "negative"

    if pos_score >= 2 and neg_score == 0:
        return "positive"

    # Decisive diff threshold
    if diff >= 2:
        return "positive"
    if diff <= -2:
        return "negative"

    return "neutral"
