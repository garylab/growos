"""Transparent, deterministic text analysis used for AI answers and brand mentions.

- Entity mention extraction: case-insensitive whole-word matching on names + aliases.
- Position: order of first appearance among all tracked entities.
- List rank: rank within numbered/bulleted lists when the entity appears in a list item.
- Sentiment: small lexicon around the mention (method="lexicon"). It is a coarse signal, labelled as such.
- Intent: keyword heuristics for discussions (question / recommendation request / complaint / purchase intent).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

POSITIVE = {"best", "great", "excellent", "love", "recommend", "recommended", "reliable", "easy", "fast", "top",
            "leading", "popular", "favorite", "favourite", "good", "solid", "powerful", "intuitive", "affordable",
            "helpful", "impressive", "robust", "trusted"}
NEGATIVE = {"worst", "bad", "terrible", "hate", "avoid", "slow", "expensive", "buggy", "poor", "broken", "scam",
            "disappointing", "frustrating", "lacks", "lacking", "limited", "confusing", "unreliable", "complaint",
            "issue", "issues", "problem", "problems", "downside", "downsides", "overpriced"}

INTENT_PATTERNS = {
    "recommendation_request": re.compile(r"\b(any (good )?recommendations?|what (should|do) (i|you) use|which (one|tool|service) (is|should)|alternatives? to|looking for a|suggest(ions)? for|best .* for)\b", re.I),
    "purchase_intent": re.compile(r"\b(pricing|how much (does|is)|worth (it|the money|paying)|free trial|sign(ed)? up|switch(ing)? (to|from)|buy|subscription)\b", re.I),
    "complaint": re.compile(r"\b(doesn'?t work|not working|broken|refund|cancel(led|ing)?|support (is|was) (terrible|useless|slow)|frustrat|disappoint|scam)\b", re.I),
    "question": re.compile(r"\?|\b(how (do|can|to)|does anyone|is there a|what is)\b", re.I),
}

LIST_ITEM = re.compile(r"^\s*(?:(\d+)[.)]|[-*•])\s+(.*)$")


@dataclass
class EntityMention:
    entity_type: str  # brand | competitor
    entity_name: str
    position: int
    mention_count: int
    list_rank: int | None
    sentiment: str
    context_snippet: str
    first_offset: int
    matched_terms: list[str] = field(default_factory=list)


def _pattern(terms: list[str]) -> re.Pattern[str] | None:
    terms = [t.strip() for t in terms if t and t.strip()]
    if not terms:
        return None
    alts = "|".join(re.escape(t) for t in sorted(set(terms), key=len, reverse=True))
    return re.compile(rf"(?<![\w@/.-])(?:{alts})(?![\w-])", re.I)


def extract_mentions(text: str, brand: tuple[str, list[str]], competitors: list[tuple[str, list[str]]]) -> list[EntityMention]:
    """brand = (name, aliases); competitors = [(name, aliases), ...]."""
    if not text:
        return []
    entities = [("brand", brand[0], [brand[0], *brand[1]])] + [("competitor", n, [n, *a]) for n, a in competitors]
    found: list[EntityMention] = []
    for etype, name, terms in entities:
        pat = _pattern(terms)
        if not pat:
            continue
        matches = list(pat.finditer(text))
        if not matches:
            continue
        first = matches[0]
        snippet = _sentence_around(text, first.start(), first.end())
        found.append(EntityMention(entity_type=etype, entity_name=name, position=0, mention_count=len(matches),
                                   list_rank=_list_rank(text, first.start()), sentiment=lexicon_sentiment(snippet),
                                   context_snippet=snippet, first_offset=first.start(),
                                   matched_terms=sorted({m.group(0) for m in matches}, key=str.lower)))
    found.sort(key=lambda m: m.first_offset)
    for i, m in enumerate(found, start=1):
        m.position = i
    return found


def _sentence_around(text: str, start: int, end: int, window: int = 220) -> str:
    lo = max(0, start - window)
    hi = min(len(text), end + window)
    chunk = text[lo:hi]
    # trim to sentence-ish boundaries
    left = max(chunk.rfind(". ", 0, start - lo), chunk.rfind("\n", 0, start - lo))
    right_candidates = [i for i in (chunk.find(". ", end - lo), chunk.find("\n", end - lo)) if i != -1]
    right = min(right_candidates) if right_candidates else len(chunk)
    return chunk[left + 1 if left >= 0 else 0: right + 1].strip()


def _list_rank(text: str, offset: int) -> int | None:
    """If the offset lies inside a list item, return that item's rank (1-based) within its contiguous list."""
    line_start = text.rfind("\n", 0, offset) + 1
    line_end = text.find("\n", offset)
    line = text[line_start: line_end if line_end != -1 else len(text)]
    m = LIST_ITEM.match(line)
    if not m:
        return None
    if m.group(1):
        return int(m.group(1))
    # bullet list: count preceding consecutive bullet lines
    rank = 1
    pos = line_start
    while pos > 0:
        prev_end = pos - 1
        prev_start = text.rfind("\n", 0, prev_end) + 1
        prev_line = text[prev_start:prev_end]
        if LIST_ITEM.match(prev_line):
            rank += 1
            pos = prev_start
        else:
            break
    return rank


def lexicon_sentiment(snippet: str) -> str:
    words = re.findall(r"[a-z']+", snippet.lower())
    pos = sum(1 for w in words if w in POSITIVE)
    neg = sum(1 for w in words if w in NEGATIVE)
    # simple negation flip for "not good"
    for i, w in enumerate(words):
        if w in ("not", "no", "never") and i + 1 < len(words):
            if words[i + 1] in POSITIVE:
                pos -= 1
                neg += 1
            elif words[i + 1] in NEGATIVE:
                neg -= 1
                pos += 1
    if pos > neg:
        return "positive"
    if neg > pos:
        return "negative"
    return "neutral"


def detect_intent(text: str) -> str:
    for intent in ("complaint", "recommendation_request", "purchase_intent", "question"):
        if INTENT_PATTERNS[intent].search(text or ""):
            return intent
    return "none"


def classify_topics(text: str, topics: dict[str, list[str]]) -> list[str]:
    """topics: {"pricing": ["price", "cost"], ...} -> list of matched topic names."""
    out = []
    low = (text or "").lower()
    for name, kws in topics.items():
        if any(re.search(rf"\b{re.escape(k.lower())}\b", low) for k in kws):
            out.append(name)
    return out


DEFAULT_TOPICS = {
    "pricing": ["price", "pricing", "cost", "expensive", "cheap", "subscription", "plan"],
    "features": ["feature", "features", "integration", "api", "export", "dashboard"],
    "support": ["support", "customer service", "help desk", "response time"],
    "performance": ["slow", "fast", "performance", "latency", "speed"],
    "comparison": ["vs", "versus", "alternative", "alternatives", "compare", "comparison", "better than"],
    "hiring": ["hiring", "recruit", "interview", "candidate", "job"],
}
