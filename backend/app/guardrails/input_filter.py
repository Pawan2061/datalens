"""Layer 1: Fast rule-based input filter.

Zero-cost, zero-latency checks that run before anything else.
Returns a GuardrailResult with verdict and reason.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class Verdict(str, Enum):
    PASS = "pass"
    FLAG = "flag"        # Suspicious but allowed — log it
    BLOCK = "block"      # Rejected outright


@dataclass
class GuardrailResult:
    verdict: Verdict
    reason: str = ""
    layer: str = ""      # Which guardrail layer caught it


# ── Maximum input length ────────────────────────────────────────
MAX_INPUT_LENGTH = 4000  # chars — anything longer is suspicious

# ── SQL injection patterns ──────────────────────────────────────
_SQL_INJECTION_PATTERNS = [
    r";\s*(DROP|DELETE|TRUNCATE|ALTER|CREATE|INSERT|UPDATE|EXEC|EXECUTE)\b",
    r"'\s*;\s*--",
    r"'\s*OR\s+['\d]\s*=\s*['\d]",
    r"UNION\s+(ALL\s+)?SELECT\b",
    r"INTO\s+OUTFILE\b",
    r"INTO\s+DUMPFILE\b",
    r"LOAD_FILE\s*\(",
    r"xp_cmdshell",
    r"sp_executesql",
    r"WAITFOR\s+DELAY",
    r"BENCHMARK\s*\(",
    r"SLEEP\s*\(",
    r"pg_sleep\s*\(",
    r"UTL_HTTP",
    r"dbms_pipe",
]

# ── Prompt injection patterns ───────────────────────────────────
_PROMPT_INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?previous\s+instructions",
    r"ignore\s+(all\s+)?above\s+instructions",
    r"disregard\s+(all\s+)?previous",
    r"forget\s+(all\s+)?previous",
    r"you\s+are\s+now\s+(a|an)\b",
    r"new\s+instructions?\s*:",
    r"system\s*:\s*you",
    r"act\s+as\s+(a|an)\b(?!.*analyst)",  # "act as an analyst" is OK
    r"pretend\s+you\s+are",
    r"jailbreak",
    r"DAN\s+mode",
    r"developer\s+mode",
    r"override\s+safety",
    r"bypass\s+(safety|filter|guard)",
    r"reveal\s+(your\s+)?(system\s+)?prompt",
    r"show\s+(me\s+)?(your\s+)?(system\s+)?prompt",
    r"print\s+(your\s+)?instructions",
    r"what\s+are\s+your\s+instructions",
    r"output\s+your\s+(system\s+)?prompt",
    r"repeat\s+the\s+(text|words)\s+above",
]

# ── PII extraction attempts ─────────────────────────────────────
_PII_EXTRACTION_PATTERNS = [
    r"(give|show|list|extract|dump)\s+.*(email|phone|ssn|social\s+security|password|credit\s+card|address)\s*(number)?s?\b",
    r"(all|every)\s+(user|customer|employee).*\b(email|phone|password|credential)s?\b",
]

# ── Dangerous SQL keywords (should never appear in user's question) ──
_DANGEROUS_SQL_KEYWORDS = [
    r"\bDROP\s+TABLE\b",
    r"\bDELETE\s+FROM\b",
    r"\bTRUNCATE\s+TABLE\b",
    r"\bALTER\s+TABLE\b",
    r"\bGRANT\b",
    r"\bREVOKE\b",
    r"\bCREATE\s+(TABLE|DATABASE|INDEX)\b",
    r"\bSHUTDOWN\b",
]

# Compile all patterns for performance
_COMPILED_SQL_INJECTION = [re.compile(p, re.IGNORECASE) for p in _SQL_INJECTION_PATTERNS]
_COMPILED_PROMPT_INJECTION = [re.compile(p, re.IGNORECASE) for p in _PROMPT_INJECTION_PATTERNS]
_COMPILED_PII_EXTRACTION = [re.compile(p, re.IGNORECASE) for p in _PII_EXTRACTION_PATTERNS]
_COMPILED_DANGEROUS_SQL = [re.compile(p, re.IGNORECASE) for p in _DANGEROUS_SQL_KEYWORDS]


def check_input(text: str) -> GuardrailResult:
    """Run all rule-based checks on user input. Returns immediately."""

    # Length check
    if len(text) > MAX_INPUT_LENGTH:
        return GuardrailResult(
            verdict=Verdict.BLOCK,
            reason=f"Input too long ({len(text)} chars, max {MAX_INPUT_LENGTH})",
            layer="input_filter",
        )

    # Empty check
    if not text.strip():
        return GuardrailResult(
            verdict=Verdict.BLOCK,
            reason="Empty input",
            layer="input_filter",
        )

    # SQL injection
    for pattern in _COMPILED_SQL_INJECTION:
        if pattern.search(text):
            return GuardrailResult(
                verdict=Verdict.BLOCK,
                reason="Potential SQL injection detected",
                layer="input_filter",
            )

    # Dangerous SQL keywords in user question
    for pattern in _COMPILED_DANGEROUS_SQL:
        if pattern.search(text):
            return GuardrailResult(
                verdict=Verdict.BLOCK,
                reason="Destructive SQL command detected in question",
                layer="input_filter",
            )

    # Prompt injection — block
    for pattern in _COMPILED_PROMPT_INJECTION:
        if pattern.search(text):
            return GuardrailResult(
                verdict=Verdict.BLOCK,
                reason="Prompt injection attempt detected",
                layer="input_filter",
            )

    # PII extraction — flag (suspicious but might be legitimate business question)
    for pattern in _COMPILED_PII_EXTRACTION:
        if pattern.search(text):
            return GuardrailResult(
                verdict=Verdict.FLAG,
                reason="Possible PII extraction request",
                layer="input_filter",
            )

    return GuardrailResult(verdict=Verdict.PASS, layer="input_filter")
