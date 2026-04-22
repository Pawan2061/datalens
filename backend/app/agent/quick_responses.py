"""Quick response interceptor and response cache.

Handles greetings, small-talk, and caches responses for similar questions
to eliminate unnecessary LLM calls and reduce token usage.
"""
from __future__ import annotations

import hashlib
import time
import re
from typing import Optional

# ── Greeting / small-talk patterns ────────────────────────────────
_GREETING_PATTERNS = [
    r"^(hi|hello|hey|howdy|hola|greetings|good\s*(morning|afternoon|evening|day))[\s!.,?]*$",
    r"^(what'?s?\s*up|sup|yo)[\s!.,?]*$",
    r"^(thanks?|thank\s*you|thx|ty|cheers)[\s!.,?]*$",
    r"^(ok|okay|sure|got\s*it|alright|cool|nice|great|awesome|perfect)[\s!.,?]*$",
    r"^(bye|goodbye|see\s*ya|later|cya)[\s!.,?]*$",
    r"^(help|what\s*can\s*you\s*do|capabilities|features)[\s!.,?]*$",
    r"^(who\s*are\s*you|what\s*are\s*you)[\s!.,?]*$",
]

_GREETING_RESPONSE = {
    "greeting": (
        "TITLE: Welcome to DataLens\n\n"
        "Hey there! I'm your data analyst — ready to explore your database and uncover insights. "
        "Just ask me anything about your data!\n\n"
        "INSIGHTS:\n"
        "- **Data Exploration** | Ask me to analyze trends, distributions, and patterns | high\n"
        "- **Comparisons** | Compare metrics across categories, time periods, or segments | medium\n"
        "- **Deep Dives** | Get detailed breakdowns with charts and key findings | medium\n\n"
        "QUESTIONS:\n"
        "- What tables and data do I have available?\n"
        "- Show me the top trends in my data?\n"
        "- What are the key metrics I should track?\n"
    ),
    "thanks": "You're welcome! Let me know if you need anything else from the data.",
    "bye": "Goodbye! Your workspace and chat history are saved — come back anytime.",
    "ok": "Got it! What would you like to explore next?",
    "help": (
        "TITLE: How I Can Help\n\n"
        "I can query your connected database, analyze results, and create visualizations. "
        "Here's what I do best:\n\n"
        "INSIGHTS:\n"
        "- **Ask Questions in Plain English** | I'll write the SQL and analyze the results for you | high\n"
        "- **Charts & Visualizations** | I automatically pick the best chart type for your data | medium\n"
        "- **Quick vs Deep Analysis** | Toggle between fast answers and thorough deep-dives | medium\n\n"
        "QUESTIONS:\n"
        "- What data sources are connected?\n"
        "- Show me a summary of all tables?\n"
        "- What are the most common values in my data?\n"
    ),
}


def detect_quick_response(message: str) -> Optional[str]:
    """Check if a message is a greeting/small-talk that doesn't need LLM.

    Returns a pre-built response string, or None if the message needs LLM processing.
    """
    cleaned = message.strip().lower()
    cleaned = re.sub(r'[^\w\s?!.,\']', '', cleaned)

    if len(cleaned) > 60:
        return None  # Too long to be a greeting

    for pattern in _GREETING_PATTERNS:
        if re.match(pattern, cleaned, re.IGNORECASE):
            # Classify and return appropriate response
            if any(w in cleaned for w in ("thank", "thx", "ty", "cheers")):
                return _GREETING_RESPONSE["thanks"]
            if any(w in cleaned for w in ("bye", "goodbye", "see", "later", "cya")):
                return _GREETING_RESPONSE["bye"]
            if any(w in cleaned for w in ("ok", "okay", "sure", "got it", "alright", "cool", "nice", "great", "awesome", "perfect")):
                return _GREETING_RESPONSE["ok"]
            if any(w in cleaned for w in ("help", "what can", "capabilities", "features")):
                return _GREETING_RESPONSE["help"]
            return _GREETING_RESPONSE["greeting"]

    return None


# ── Conversational message classifier ────────────────────────────
# These are messages that need an LLM but don't need the full ReAct
# agent with SQL tools. Route these to the cheapest model (Haiku).

_CONVERSATIONAL_PATTERNS = [
    # Questions about capabilities / self
    r"what (can|do) you",
    r"how (can|do) you",
    r"tell me about (yourself|you|this|the data)",
    r"what (is|are) (this|these|the) (data|table|database)",
    r"describe (the|this|my)",
    r"explain (the|this|how)",
    r"what (kind|type) of (data|analysis|question)",
    r"how (does|do) (this|it) work",
    r"give me (a|an) (overview|summary|intro)",
    r"summarize (the|this|my)",
    # General chit-chat
    r"^(that'?s? (interesting|cool|great|nice|good|amazing|awesome))",
    r"^(i see|i understand|makes sense|got it|understood)",
    r"^(no|nope|not really|never\s*mind|forget)",
    r"^(yes|yeah|yep|yup|correct|right|exactly)[\s!.,?]*$",
    r"^(hmm|huh|oh|ah|wow)[\s!.,?]*$",
    # Short acknowledgments (< 20 chars, no data keywords)
]

_DATA_KEYWORDS = [
    "show", "chart", "graph", "plot", "table", "query", "sql",
    "count", "sum", "average", "avg", "total", "top", "bottom",
    "trend", "compare", "breakdown", "distribution", "group by",
    "filter", "where", "between", "monthly", "weekly", "daily",
    "revenue", "sales", "cost", "profit", "growth", "rate",
    "how many", "how much", "what is the", "list all", "give me the",
    "which", "highest", "lowest", "most", "least", "rank",
    # Hinglish / transliterated-Hindi signals of a data question.
    # These are common in Indian business users' messages and must NOT
    # be routed to the cheap conversational model (which has no tools).
    "kitna", "kitne", "kitni",           # "how much/many"
    "mera", "meri", "mere", "mujhe",     # "my / to me"
    "dikhao", "dikhade", "dikha",        # "show"
    "batao", "bata",                     # "tell"
    # Language-neutral business/ops nouns — their presence is a strong
    # signal that this is a data request, regardless of surrounding grammar.
    "outstanding", "overdue", "pending", "payable", "receivable",
    "balance", "due", "payment", "receipt",
    "invoice", "bill", "order", "purchase",
    "amount", "value",
    "stock", "inventory", "shipment", "delivery",
    "status",
]


def is_conversational(message: str, has_history: bool = False) -> bool:
    """Detect if a message is conversational (no data query needed).

    Returns True for chit-chat that should use the cheap model.
    Returns False for data/analysis requests that need the full agent.

    When has_history=True, the 20-char shortcut is skipped — a short message
    in an active conversation is likely a follow-up data request, not chit-chat.
    This makes the classifier language-agnostic for follow-ups (Hindi, etc.).
    """
    cleaned = message.strip().lower()

    # If it contains data keywords, it's an analysis request
    for kw in _DATA_KEYWORDS:
        if kw in cleaned:
            return False

    # Very short messages without data keywords are likely conversational —
    # but only when there's no prior history. With history, a short message
    # is probably a follow-up data instruction ("ok go ahead", "unke list dedo").
    if len(cleaned) < 20 and not has_history:
        return True

    # Check against conversational patterns
    for pattern in _CONVERSATIONAL_PATTERNS:
        if re.search(pattern, cleaned, re.IGNORECASE):
            return True

    # Messages ending with ? but < 50 chars and no data keywords → probably conversational
    if cleaned.endswith("?") and len(cleaned) < 50:
        return True

    return False


# ── Response cache for similar questions ──────────────────────────

class ResponseCache:
    """LRU cache for similar question-response pairs.

    Uses normalized question text as cache key to match similar questions.
    Cached entries expire after TTL seconds.
    """

    def __init__(self, max_size: int = 200, ttl_seconds: int = 3600):
        self._cache: dict[str, dict] = {}  # hash -> {response, timestamp, hit_count}
        self._max_size = max_size
        self._ttl = ttl_seconds

    def _normalize(
        self,
        question: str,
        connection_id: str,
        customer_scope: str = "",
        analysis_mode: str = "quick",
        selected_tables: Optional[list[str]] = None,
    ) -> str:
        """Normalize a question + scope into a cache key.

        The key MUST include every input that changes the produced answer.
        Missing a field here silently serves one scope's result to another
        (e.g. admin data leaked to a customer view) — so be conservative.
        """
        q = question.strip().lower()
        q = re.sub(r'\s+', ' ', q)
        q = re.sub(r'\b(please|can you|could you|i want to|show me|give me|tell me|i need)\b', '', q)
        q = q.strip()
        tables_key = ",".join(sorted(selected_tables)) if selected_tables else ""
        composite = f"{connection_id}|{customer_scope}|{analysis_mode}|{tables_key}|{q}"
        return hashlib.sha256(composite.encode()).hexdigest()[:16]

    def get(
        self,
        question: str,
        connection_id: str,
        customer_scope: str = "",
        analysis_mode: str = "quick",
        selected_tables: Optional[list[str]] = None,
    ) -> Optional[dict]:
        """Look up a cached response. Returns InsightResult dict or None."""
        key = self._normalize(question, connection_id, customer_scope, analysis_mode, selected_tables)
        entry = self._cache.get(key)
        if entry is None:
            return None
        # Check TTL
        if time.time() - entry["timestamp"] > self._ttl:
            del self._cache[key]
            return None
        entry["hit_count"] += 1
        return entry["response"]

    def put(
        self,
        question: str,
        connection_id: str,
        response: dict,
        customer_scope: str = "",
        analysis_mode: str = "quick",
        selected_tables: Optional[list[str]] = None,
    ) -> None:
        """Cache a response for a question."""
        # Don't cache error responses or empty results
        meta = response.get("execution_metadata", {})
        if meta.get("total_rows", 0) == 0:
            return

        key = self._normalize(question, connection_id, customer_scope, analysis_mode, selected_tables)

        # Evict oldest if at capacity
        if len(self._cache) >= self._max_size and key not in self._cache:
            oldest_key = min(self._cache, key=lambda k: self._cache[k]["timestamp"])
            del self._cache[oldest_key]

        self._cache[key] = {
            "response": response,
            "timestamp": time.time(),
            "hit_count": 0,
        }

    def stats(self) -> dict:
        """Return cache statistics."""
        total_hits = sum(e["hit_count"] for e in self._cache.values())
        return {
            "entries": len(self._cache),
            "max_size": self._max_size,
            "total_hits": total_hits,
        }


# Global instance
response_cache = ResponseCache()
