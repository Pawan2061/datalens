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
