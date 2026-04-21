"""Layer 4: Response output guard.

Scans LLM-generated output (narrative, key findings, etc.) for leaked
credentials, connection strings, PII patterns, or system internals before
sending to the user.
"""
from __future__ import annotations

import re
import logging

logger = logging.getLogger(__name__)

# ── Credential / secret patterns ────────────────────────────────
_SECRET_PATTERNS = [
    # Connection strings
    (re.compile(r"(postgresql|postgres|mysql|mssql|mongodb)://[^\s\"']+", re.IGNORECASE), "[CONNECTION_STRING_REDACTED]"),
    (re.compile(r"Server=\S+;.*Password=\S+", re.IGNORECASE), "[CONNECTION_STRING_REDACTED]"),
    (re.compile(r"AccountEndpoint=https://\S+;AccountKey=\S+", re.IGNORECASE), "[COSMOS_CONNECTION_REDACTED]"),

    # API keys and tokens
    (re.compile(r"\b(sk-[a-zA-Z0-9]{20,})\b"), "[API_KEY_REDACTED]"),
    (re.compile(r"\b(AIza[a-zA-Z0-9_-]{35})\b"), "[GOOGLE_KEY_REDACTED]"),
    (re.compile(r"\b(ghp_[a-zA-Z0-9]{36})\b"), "[GITHUB_TOKEN_REDACTED]"),
    (re.compile(r"\b(xox[bpas]-[a-zA-Z0-9-]+)\b"), "[SLACK_TOKEN_REDACTED]"),
    (re.compile(r"Bearer\s+[a-zA-Z0-9._-]{20,}"), "[BEARER_TOKEN_REDACTED]"),
    (re.compile(r"\b(AKIA[0-9A-Z]{16})\b"), "[AWS_KEY_REDACTED]"),
    (re.compile(r"\bJWT_SECRET\s*[=:]\s*\S+", re.IGNORECASE), "[JWT_SECRET_REDACTED]"),

    # Generic long hex/base64 strings that look like keys
    (re.compile(r"(?<![a-zA-Z0-9/+])[a-zA-Z0-9/+]{40,}={0,2}(?![a-zA-Z0-9/+=])"), None),  # Checked separately
]

# ── PII patterns ────────────────────────────────────────────────
_PII_PATTERNS = [
    # SSN
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[SSN_REDACTED]"),
    # Credit card (basic Luhn-like patterns)
    (re.compile(r"\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13}|6(?:011|5[0-9]{2})[0-9]{12})\b"), "[CARD_REDACTED]"),
    # Card-like with separators
    (re.compile(r"\b\d{4}[-\s]\d{4}[-\s]\d{4}[-\s]\d{4}\b"), "[CARD_REDACTED]"),
]

# ── System internals that shouldn't leak ────────────────────────
_SYSTEM_LEAK_PATTERNS = [
    (re.compile(r"COSMOS_KEY\s*[=:]\s*\S+", re.IGNORECASE), "[CREDENTIAL_REDACTED]"),
    (re.compile(r"COSMOS_ENDPOINT\s*[=:]\s*\S+", re.IGNORECASE), "[CREDENTIAL_REDACTED]"),
    (re.compile(r"ANTHROPIC_FOUNDRY_KEY\s*[=:]\s*\S+", re.IGNORECASE), "[CREDENTIAL_REDACTED]"),
    (re.compile(r"GOOGLE_API_KEY\s*[=:]\s*\S+", re.IGNORECASE), "[CREDENTIAL_REDACTED]"),
    (re.compile(r"password\s*[=:]\s*[\"']?[^\s\"']{8,}[\"']?", re.IGNORECASE), "[PASSWORD_REDACTED]"),
]


def scrub_response(text: str) -> tuple[str, list[str]]:
    """Scrub sensitive data from LLM output.

    Returns:
        (cleaned_text, list_of_redaction_reasons)
    """
    if not text:
        return text, []

    redactions: list[str] = []
    result = text

    # Scrub secrets
    for pattern, replacement in _SECRET_PATTERNS:
        if replacement is None:
            continue  # Skip the generic long-key check for replacement
        if pattern.search(result):
            result = pattern.sub(replacement, result)
            redactions.append(f"Redacted: {replacement}")

    # Scrub PII
    for pattern, replacement in _PII_PATTERNS:
        if pattern.search(result):
            result = pattern.sub(replacement, result)
            redactions.append(f"Redacted: {replacement}")

    # Scrub system internals
    for pattern, replacement in _SYSTEM_LEAK_PATTERNS:
        if pattern.search(result):
            result = pattern.sub(replacement, result)
            redactions.append(f"Redacted: {replacement}")

    if redactions:
        logger.warning("Response guard redacted %d items: %s", len(redactions), redactions)

    return result, redactions


def scrub_insight_result(insight: dict) -> dict:
    """Scrub an entire InsightResult dict (summary, charts, tables, etc.)."""
    if not insight:
        return insight

    # Fix common LLM currency-unit confusions (million vs crore) FIRST so we
    # don't accidentally redact a corrected number downstream.
    insight = normalize_currency_units(insight)

    all_redactions: list[str] = []

    # Scrub summary
    summary = insight.get("summary", {})
    if summary:
        if summary.get("title"):
            summary["title"], r = scrub_response(summary["title"])
            all_redactions.extend(r)
        if summary.get("narrative"):
            summary["narrative"], r = scrub_response(summary["narrative"])
            all_redactions.extend(r)
        for finding in summary.get("key_findings", []):
            if finding.get("headline"):
                finding["headline"], r = scrub_response(finding["headline"])
                all_redactions.extend(r)
            if finding.get("detail"):
                finding["detail"], r = scrub_response(finding["detail"])
                all_redactions.extend(r)

    # Scrub chart titles and reasoning
    for chart in insight.get("charts", []):
        if chart.get("title"):
            chart["title"], r = scrub_response(chart["title"])
            all_redactions.extend(r)
        if chart.get("reasoning"):
            chart["reasoning"], r = scrub_response(chart["reasoning"])
            all_redactions.extend(r)

    if all_redactions:
        logger.info("Scrubbed %d items from insight result", len(all_redactions))

    return insight


# ── INR unit normalizer ─────────────────────────────────────────────
# The synthesis LLM occasionally confuses "million" with "crore" (1 Cr = 10 M,
# not 1 M) and renders ₹8.87 Cr as ₹88.74 Cr. We detect this by cross-checking
# every "X.XX Cr" / "X.XX L" mention in the narrative against the raw numeric
# values present in the result's tables and charts, and auto-correct when the
# LLM's value equals raw/1,000,000 (wrong) instead of raw/10,000,000 (right).

_CR_RE = re.compile(
    r"(?P<num>\d[\d,]*\.?\d*)\s*(?:Cr(?:ore)?s?)\b",
    re.IGNORECASE,
)
_L_RE = re.compile(
    r"(?P<num>\d[\d,]*\.?\d*)\s*(?:L(?:akh)?s?)\b",
    re.IGNORECASE,
)


def _collect_numeric_values(insight: dict) -> list[float]:
    """Positive numeric values (≥ 1,000) from all tables and chart data."""
    values: list[float] = []
    containers = (insight.get("tables") or []) + (insight.get("charts") or [])
    for container in containers:
        for row in container.get("data") or []:
            if not isinstance(row, dict):
                continue
            for v in row.values():
                if isinstance(v, bool):
                    continue
                if isinstance(v, (int, float)) and v >= 1_000:
                    values.append(float(v))
    return values


def _close(a: float, b: float) -> bool:
    """Values are equal within 2% (or 0.05 absolute for tiny numbers)."""
    return abs(a - b) < max(0.05, abs(b) * 0.02)


def _fix_currency_units(
    text: str, raw_values: list[float], correct_div: float, wrong_div: float, unit: str, pattern: re.Pattern
) -> tuple[str, int]:
    """Rewrite 'X Cr' / 'X L' values that were computed with the wrong divisor."""
    if not text or not raw_values:
        return text, 0

    fixes = 0

    def _sub(match: re.Match) -> str:
        nonlocal fixes
        num_str = match.group("num").replace(",", "")
        try:
            llm_val = float(num_str)
        except ValueError:
            return match.group(0)
        for raw in raw_values:
            wrong = raw / wrong_div
            correct = raw / correct_div
            # LLM value matches the WRONG divisor AND a different correct value
            # exists for the same raw number → classic million/crore mixup.
            if _close(wrong, llm_val) and not _close(correct, llm_val):
                fixes += 1
                return f"{correct:.2f} {unit}"
        return match.group(0)

    new_text = pattern.sub(_sub, text)
    return new_text, fixes


def normalize_currency_units(insight: dict) -> dict:
    """Correct Cr/L values in narrative/title/key_findings that were produced
    by dividing by 1,000,000 instead of 10,000,000 (or 10,000 instead of 100,000).

    Ground truth is the raw numeric values already present in `tables` and
    `charts[].data`. No change is made when the LLM's value is ambiguous
    (matches both divisors) or when no matching raw value exists.
    """
    if not insight:
        return insight
    raw_values = _collect_numeric_values(insight)
    if not raw_values:
        return insight

    total_fixes = 0
    fields_touched: list[str] = []

    def _apply(text: str) -> str:
        nonlocal total_fixes
        t1, n1 = _fix_currency_units(text, raw_values, 10_000_000, 1_000_000, "Cr", _CR_RE)
        t2, n2 = _fix_currency_units(t1, raw_values, 100_000, 10_000, "L", _L_RE)
        total_fixes += n1 + n2
        return t2

    summary = insight.get("summary") or {}
    for field in ("title", "narrative"):
        original = summary.get(field)
        if isinstance(original, str) and original:
            fixed = _apply(original)
            if fixed != original:
                summary[field] = fixed
                fields_touched.append(f"summary.{field}")
    for kf in summary.get("key_findings") or []:
        for field in ("headline", "detail"):
            original = kf.get(field)
            if isinstance(original, str) and original:
                fixed = _apply(original)
                if fixed != original:
                    kf[field] = fixed
                    fields_touched.append(f"key_finding.{field}")

    if total_fixes:
        logger.warning(
            "Currency normalizer corrected %d Cr/L value(s) in: %s",
            total_fixes, ", ".join(fields_touched),
        )
    return insight
