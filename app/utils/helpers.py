import re
from datetime import datetime
from typing import Optional

import html

def clean_html(text: str) -> str:
    if not text:
        return ""
    # 1. Unescape HTML entities (&amp;, &nbsp;, &#39;, &quot;)
    cleaned = html.unescape(text)
    # 2. Insert spacing and paragraph separation for block tags so words aren't fused together
    cleaned = re.sub(r"<\s*/?(?:p|div|br|hr|h[1-6]|li|tr|blockquote)[^>]*>", "\n\n", cleaned, flags=re.IGNORECASE)
    # 3. Strip remaining HTML tags
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    # 4. Remove common trailing RSS clickbait ("Continue reading...", "Read more...")
    cleaned = re.sub(r"\b(?:Continue reading|Read more|Click here to read more|Read full story)\b[\s.…—–-]*", "", cleaned, flags=re.IGNORECASE)
    # 5. Normalize whitespace while keeping clean paragraph breaks
    paragraphs = [re.sub(r"\s+", " ", p).strip() for p in cleaned.split("\n\n")]
    return "\n\n".join(p for p in paragraphs if p)

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
    "also", "said", "says", "new", "according", "year", "years",
    "time", "day", "week", "month", "percent", "report", "more",
    "over", "such", "there", "than", "after", "about", "been",
}

def extract_tags_from_text(text: str, max_tags: int = 6) -> list[str]:
    """
    NER-lite tag extraction:
    1. Extract capitalized multi-word proper nouns (weight 3)
    2. Extract single capitalized words that aren't at sentence starts (weight 2)
    3. Fall back to high-frequency non-stopword words (weight 1)
    """
    tags: dict[str, int] = {}

    # Step 1: Extract capitalized multi-word phrases (2-3 consecutive capitalized words)
    # These are likely proper nouns / named entities
    proper_noun_pattern = re.compile(r'\b([A-Z][a-z]{1,}(?:\s+[A-Z][a-z]{1,}){1,2})\b')
    for match in proper_noun_pattern.finditer(text):
        phrase = match.group(1).strip()
        if len(phrase) > 3 and phrase.lower() not in STOPWORDS:
            tags[phrase] = tags.get(phrase, 0) + 3

    # Step 2: Single capitalized words mid-sentence (not at start of sentence, not ALL_CAPS abbreviations)
    # These are likely proper names or org names
    single_cap = re.compile(r'(?<=[.!?]\s|[,;:]\s|\s{2})([A-Z][a-z]{2,})\b')
    for match in single_cap.finditer(text):
        word = match.group(1)
        if word.lower() not in STOPWORDS and len(word) >= 4:
            tags[word] = tags.get(word, 0) + 2

    # Step 3: Frequency-based fallback for non-stopword words
    words = re.findall(r"\b[a-zA-Z]{4,}\b", text.lower())
    freq: dict[str, int] = {}
    for word in words:
        if word not in STOPWORDS:
            freq[word] = freq.get(word, 0) + 1

    for word, count in freq.items():
        if count >= 2:
            capitalized = word.capitalize()
            if capitalized not in tags:
                tags[capitalized] = count

    # Sort by weight descending, deduplicate (don't return a tag that is a substring of another tag)
    sorted_tags = sorted(tags.items(), key=lambda x: x[1], reverse=True)

    result = []
    for tag, _ in sorted_tags:
        tag_lower = tag.lower()
        # Skip if it's a substring of an already-added tag or vice versa
        if not any(tag_lower in existing.lower() or existing.lower() in tag_lower for existing in result):
            result.append(tag)
        if len(result) >= max_tags:
            break

    return result


CATEGORIES = {
    "Technology": [
        "software", "artificial intelligence", "startup", "google", "microsoft",
        "apple", "programming", "digital", "gadget", "cyber", "robot", "browser",
        "app", "algorithm", "code", "linux", "windows", "android", "ios",
        "cloudflare", "amazon", "aws", "meta", "facebook", "twitter", "x.com",
        "openai", "anthropic", "nvidia", "intel", "amd", "semiconductor",
        "quantum", "cryptocurrency", "blockchain", "bitcoin", "ethereum",
        "cybersecurity", "hacking", "encryption", "tech", "gadgets", "innovation",
        "smartphone", "laptop", "chip", "data center", "cloud", "machine learning",
        "deep learning", "neural", "automation", "drone", "electric vehicle", "ev",
        "robotics", "ai model", "gpu", "processor", "broadband", "5g", "wi-fi",
    ],
    "Politics": [
        "government", "election", "parliament", "minister", "policy", "vote",
        "political", "democracy", "congress", "legislation", "senate", "law",
        "supreme court", "president", "pm", "modi", "biden", "trump",
        "campaign", "party", "diplomacy", "treaty", "alliance", "sanctions",
        "referendum", "coalition", "opposition", "bill", "constitution",
        "geopolitics", "nato", "united nations", "un", "g20", "g7",
        "geopolitical", "ambassador", "statesman", "white house", "kremlin",
        "prime minister", "chancellor", "cabinet", "foreign minister",
    ],
    "Business": [
        "business", "economy", "market", "stock", "trade", "company", "investment",
        "finance", "bank", "revenue", "inflation", "cpi", "sensex", "nifty",
        "corporate", "ceo", "merger", "acquisition", "profit", "loss",
        "manufacturing", "investor", "valuation",
        "oil", "petroleum", "energy", "commodity", "export", "import", "retail",
        "telecom", "infrastructure", "billion", "million", "earnings", "gdp",
        "ipo", "shares", "dividend", "fiscal", "quarter", "interest rate",
        "federal reserve", "rbi", "recession", "growth", "supply chain",
        "cost", "attendance", "venue costs", "industry", "economic", "layoffs",
        "bankruptcy", "startup", "entrepreneur", "founder",
    ],
    "Health": [
        "health", "medical", "doctor", "hospital", "disease", "vaccine",
        "treatment", "patient", "covid", "wellness", "virus", "cancer",
        "medicine", "nutrition", "mental health", "surgery", "drug",
        "pharmaceutical", "clinical", "research", "outbreak", "epidemic",
        "pandemic", "who", "fda", "diabetes", "heart", "obesity", "therapy",
        "healthcare", "public health", "nursing", "prescription", "symptom",
        "diagnosis", "cure", "prevention", "mortality", "infection",
    ],
    "Sports": [
        "sports", "cricket", "football", "tennis", "olympics", "match", "player",
        "championship", "tournament", "score", "medal", "cup", "league",
        "athlete", "nba", "nfl", "fifa", "ipl", "formula", "rugby", "golf",
        "boxing", "wrestling", "swimming", "athletics", "badminton", "hockey",
        "baseball", "basketball", "world cup", "premier league",
        "coach", "goal", "wicket", "innings", "grand prix", "transfer",
        "signed", "contract", "season", "playoff", "final", "semifinal",
        "stadium", "fan", "squad", "team",
    ],
    "Entertainment": [
        "movie", "film", "music", "celebrity", "entertainment", "actor",
        "singer", "award", "hollywood", "bollywood", "cinema", "concert",
        "album", "netflix", "streaming", "tv show", "series", "oscar",
        "grammy", "emmy", "box office", "trailer", "director", "producer",
        "spotify", "youtube", "tiktok", "podcast",
        "indie", "band", "venue", "gig", "tour", "festival", "recording",
        "artist", "musician", "rapper", "pop", "rock", "hip-hop",
        "television", "premiere", "release", "sequel",
        "comedy", "drama", "documentary", "animated",
    ],
    "Science": [
        "science", "research", "study", "discovery", "space", "nasa",
        "experiment", "scientist", "physics", "biology", "astronomy", "planet",
        "mars", "moon", "galaxy", "telescope", "genetics", "dna",
        "fossil", "evolution", "particle", "quantum physics", "chemistry",
        "oceanography", "geology", "esa", "isro", "spacex",
        "laboratory", "peer-reviewed", "breakthrough", "hypothesis",
        "universe", "comet", "asteroid", "rover",
    ],
    "Crime": [
        "police", "crime", "murder", "arrest", "theft", "victim", "suspect",
        "shooting", "illegal", "investigation", "court", "prison", "jail",
        "drug trafficking", "smuggling", "fraud", "terrorism", "kidnapping",
        "assault", "robbery", "verdict", "sentence", "fbi", "interpol",
        "bomb", "explosion", "blast", "attack", "gunman", "hostage",
        "stabbing", "homicide", "manslaughter", "criminal", "gang",
        "weapon", "firearm", "massacre", "riot", "violence", "militant",
        "suicide bomber", "extremist", "abduction", "detained",
        "charged", "indicted", "convicted", "trial", "prosecutor", "defendant",
        "kills", "killed", "dead", "deaths", "fatalities", "casualties",
    ],
    "Education": [
        "neet", "ug-neet", "pg-neet", "counselling", "admission", "seat matrix", "dme",
        "entrance exam", "rank", "scorecard", "cutoff", "quota", "result", "syllabus",
        "board exam", "cbse", "icse", "jee", "upsc", "ugc", "aicte", "coaching",
        "schooling", "higher education", "admissions", "seat allocation",
        "school", "university", "college", "student", "teacher", "education",
        "exam", "learning", "degree", "campus", "scholarship", "academy",
        "curriculum", "tuition", "academic", "edtech", "literacy",
        "graduation", "professor", "phd",
    ],
    "Environment": [
        "river", "sediment", "hazardous", "contamination", "riverfront", "environmental",
        "environmentalist", "activist", "sanitation", "waste", "toxic", "chemical",
        "sewage", "conservation", "ecology", "ecological", "soil", "water quality",
        "smog", "clean water", "hydrology", "nature", "forest", "wildlife",
        "climate", "pollution", "carbon", "renewable", "sustainability",
        "ecosystem", "global warming", "emissions", "solar", "wind power",
        "deforestation", "biodiversity", "plastic", "ocean", "flood",
        "drought", "wildfire", "glacier", "net zero", "cop",
        "temperature record", "heatwave", "greenhouse gas",
    ],
    "Travel": [
        "travel", "tourism", "vacation", "flight", "hotel", "destination",
        "trip", "tourist", "resort", "voyage", "airline", "passport",
        "visa", "cruise", "backpacking", "adventure", "itinerary",
    ],
    "Lifestyle": [
        "fashion", "lifestyle", "food", "recipe", "home", "design", "culture",
        "luxury", "style", "living", "wellness", "fitness",
        "yoga", "meditation", "relationships", "dating", "parenting",
    ],
    "General": [
        "general", "news", "update", "info", "public", "notice",
    ],
}

CATEGORY_CONFIDENCE_THRESHOLD = 2

def categorize_article(title: str, content: str) -> str:
    title_lower = title.lower()
    text_lower = (title + " " + content).lower()

    scores: dict[str, int] = {}
    for category, keywords in CATEGORIES.items():
        score = 0
        for kw in keywords:
            kw_pattern = r'\b' + re.escape(kw) + r'\b'
            if re.search(kw_pattern, title_lower):
                score += 3  # Title match is strong signal
            elif re.search(kw_pattern, text_lower):
                score += 1
        scores[category] = score

    best = max(scores, key=scores.get)
    return best if scores[best] >= CATEGORY_CONFIDENCE_THRESHOLD else "General"


MAJOR_LOCATIONS = [
    # North America
    "New York", "Los Angeles", "Chicago", "Houston", "Phoenix", "Philadelphia",
    "San Francisco", "Seattle", "Boston", "Miami", "Washington", "Texas",
    "California", "Florida", "New Jersey", "Georgia", "Michigan", "Ohio",
    "USA", "United States", "America", "Canada", "Toronto", "Vancouver",
    "Montreal", "Ottawa", "Mexico", "Mexico City",

    # Europe
    "London", "UK", "United Kingdom", "England", "Scotland", "Wales",
    "Paris", "France", "Berlin", "Germany", "Madrid", "Spain", "Rome",
    "Italy", "Amsterdam", "Netherlands", "Brussels", "Belgium",
    "Vienna", "Austria", "Warsaw", "Poland", "Prague", "Czech Republic",
    "Stockholm", "Sweden", "Oslo", "Norway", "Copenhagen", "Denmark",
    "Helsinki", "Finland", "Zurich", "Switzerland", "Lisbon", "Portugal",
    "Athens", "Greece", "Budapest", "Hungary", "Bucharest", "Romania",
    "Europe", "European Union", "EU",

    # Russia & Eastern Europe
    "Moscow", "Russia", "Kyiv", "Ukraine", "Kiev", "Minsk", "Belarus",

    # South Asia
    "India", "Delhi", "New Delhi", "Mumbai", "Bengaluru", "Bangalore",
    "Chennai", "Kolkata", "Hyderabad", "Pune", "Ahmedabad", "Surat",
    "Jaipur", "Lucknow", "Chandigarh", "Bhopal", "Kochi", "Goa",
    "Kerala", "Maharashtra", "Karnataka", "Tamil Nadu", "Gujarat",
    "Rajasthan", "Punjab", "Uttar Pradesh", "Bihar", "West Bengal",
    "Pakistan", "Islamabad", "Karachi", "Lahore",
    "Bangladesh", "Dhaka", "Sri Lanka", "Colombo",
    "Nepal", "Kathmandu", "Afghanistan", "Kabul",

    # East Asia
    "China", "Beijing", "Shanghai", "Shenzhen", "Hong Kong",
    "Japan", "Tokyo", "Osaka", "Kyoto",
    "South Korea", "Seoul", "North Korea", "Pyongyang",
    "Taiwan", "Taipei",

    # Southeast Asia
    "Singapore", "Indonesia", "Jakarta", "Thailand", "Bangkok",
    "Vietnam", "Hanoi", "Ho Chi Minh City", "Philippines", "Manila",
    "Malaysia", "Kuala Lumpur", "Myanmar", "Yangon",

    # Middle East
    "Israel", "Tel Aviv", "Jerusalem", "Palestine", "Gaza",
    "Saudi Arabia", "Riyadh", "UAE", "Dubai", "Abu Dhabi",
    "Iran", "Tehran", "Iraq", "Baghdad", "Turkey", "Istanbul", "Ankara",
    "Qatar", "Doha", "Kuwait", "Jordan", "Amman", "Lebanon", "Beirut",
    "Syria", "Damascus", "Yemen", "Oman", "Bahrain",
    "Middle East",

    # Africa
    "Nigeria", "Lagos", "Abuja", "South Africa", "Johannesburg", "Cape Town",
    "Kenya", "Nairobi", "Ethiopia", "Addis Ababa", "Egypt", "Cairo",
    "Morocco", "Casablanca", "Ghana", "Accra", "Tanzania", "Dar es Salaam",
    "Uganda", "Kampala", "Senegal", "Dakar", "Zimbabwe", "Harare",
    "Africa",

    # South America
    "Brazil", "São Paulo", "Rio de Janeiro", "Brasília",
    "Argentina", "Buenos Aires", "Colombia", "Bogotá",
    "Chile", "Santiago", "Peru", "Lima", "Venezuela", "Caracas",
    "South America", "Latin America",

    # Oceania
    "Australia", "Sydney", "Melbourne", "Brisbane", "Perth", "Canberra",
    "New Zealand", "Auckland", "Wellington",

    # Global
    "Global", "International", "Worldwide",
]

def extract_locations_from_text(text: str) -> list[str]:
    found = []
    # Use original text for case-sensitive proper-noun matching
    for loc in MAJOR_LOCATIONS:
        # Word-boundary search (case-insensitive)
        if re.search(r'\b' + re.escape(loc) + r'\b', text, re.IGNORECASE):
            found.append(loc)
    # Deduplicate: if both "New Delhi" and "Delhi" found, keep longer one only
    deduplicated = []
    for loc in found:
        if not any(loc != other and loc.lower() in other.lower() for other in found):
            deduplicated.append(loc)
    return deduplicated


def estimate_reading_time(text: str, wpm: int = 200) -> int:
    if not text:
        return 1
    return max(1, round(len(text.split()) / wpm))

def format_datetime(dt: Optional[datetime]) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S") if dt else ""

def strip_bullets(text: str) -> str:
    """Remove bullet-point formatting characters from summary text."""
    if not text:
        return text
    # Remove leading • - * characters from lines
    text = re.sub(r'^[•\-\*]\s*', '', text, flags=re.MULTILINE)
    # Collapse multiple newlines into single
    text = re.sub(r'\n{2,}', ' ', text).strip()
    return text
