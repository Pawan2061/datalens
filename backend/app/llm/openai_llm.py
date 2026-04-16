from __future__ import annotations

import os
from functools import lru_cache

from langchain_openai import AzureChatOpenAI, ChatOpenAI

from app.config import settings


def _patch_anthropic_env():
    """Ensure the anthropic SDK picks up the correct credentials."""
    key = settings.anthropic_foundry_key or settings.anthropic_api_key
    if key:
        os.environ["ANTHROPIC_API_KEY"] = key
    if settings.anthropic_foundry_url:
        os.environ["ANTHROPIC_BASE_URL"] = settings.anthropic_foundry_url


# ── 1. Agent LLM (tool calling) — Haiku ──────────────────────────
# Used by the ReAct agent for planning + tool calls. Needs reliable
# tool calling, not heavy text generation.
# Cached as a singleton — LLM clients are thread-safe and expensive to
# re-instantiate (connection setup, token init) on every request.

@lru_cache(maxsize=1)
def get_agent_llm():
    """Haiku — reliable tool-calling model for the ReAct agent. Singleton."""
    if settings.llm_provider == "anthropic":
        _patch_anthropic_env()
        from langchain_anthropic import ChatAnthropic
        key = settings.anthropic_foundry_key or settings.anthropic_api_key
        return ChatAnthropic(
            model=settings.anthropic_worker_model,  # haiku
            api_key=key,
            base_url=settings.anthropic_foundry_url or None,
            temperature=0,
            max_tokens=8192,
        )
    if settings.llm_provider == "azure":
        return AzureChatOpenAI(
            azure_endpoint=settings.azure_endpoint,
            api_key=settings.azure_api_key,
            azure_deployment=settings.azure_worker_deployment,
            api_version=settings.azure_api_version,
            temperature=0,
        )
    return ChatOpenAI(
        model=settings.openai_worker_model,
        api_key=settings.openai_api_key,
        temperature=0,
    )


# ── 2. Generation LLM — Gemini Flash (FREE) ─────────────────────
# Used for output-heavy tasks: synthesis, charts, profile, chit-chat.
# Falls back to Haiku if no Google key.
# Thinking tokens are explicitly disabled for Gemini 2.5 Flash:
# thinking adds 2-5 s per call without improving structured JSON output.

@lru_cache(maxsize=1)
def get_generation_llm():
    """Gemini Flash — free model for text generation. Singleton.

    Thinking is disabled (thinking_budget=0) on Gemini 2.5 Flash to
    eliminate the 2-5 s thinking overhead — structured JSON tasks
    (SQL plans, synthesis) do not benefit from extended reasoning.
    """
    if settings.google_api_key:
        from langchain_google_genai import ChatGoogleGenerativeAI
        kwargs: dict = {
            "model": settings.gemini_model,
            "google_api_key": settings.google_api_key,
            "temperature": 0,
            "max_output_tokens": 8192,
        }
        # Gemini 2.5 Flash ships with thinking enabled by default.
        # thinking_budget=0 turns it off, cutting 2-5 s of latency per call.
        if "2.5" in settings.gemini_model:
            kwargs["thinking_budget"] = 0
        return ChatGoogleGenerativeAI(**kwargs)
    # Fallback to Haiku (re-use the same singleton)
    return get_agent_llm()


# ── 2b. Synthesis LLM — Gemini Flash, capped output ─────────────
# Used by analyze_results (synthesizer) and pre_planner.
# Same model as get_generation_llm() but capped at 2048 output tokens.
# Synthesis narratives are typically 500-800 tokens; capping prevents
# runaway verbosity and lets the API return the finish signal faster.

@lru_cache(maxsize=1)
def get_synthesis_llm():
    """Gemini Flash with 3500-token output cap for synthesis tasks. Singleton.

    3500 tokens is enough for a 5-section multi-part narrative + key findings
    (typical max ~1800 tokens) while still being well below the default 8192
    cap — prevents runaway verbosity without risking truncation.
    """
    if settings.google_api_key:
        from langchain_google_genai import ChatGoogleGenerativeAI
        kwargs: dict = {
            "model": settings.gemini_model,
            "google_api_key": settings.google_api_key,
            "temperature": 0,
            "max_output_tokens": 3500,
        }
        if "2.5" in settings.gemini_model:
            kwargs["thinking_budget"] = 0
        return ChatGoogleGenerativeAI(**kwargs)
    return get_agent_llm()


# ── 3. Deep analysis LLM — Sonnet ────────────────────────────────
# Only used for deep analysis mode (thorough, multi-step reasoning).

@lru_cache(maxsize=1)
def get_planner_llm():
    """Sonnet — high-quality model for deep analysis mode. Singleton."""
    if settings.llm_provider == "anthropic":
        _patch_anthropic_env()
        from langchain_anthropic import ChatAnthropic
        key = settings.anthropic_foundry_key or settings.anthropic_api_key
        return ChatAnthropic(
            model=settings.anthropic_planner_model,  # sonnet
            api_key=key,
            base_url=settings.anthropic_foundry_url or None,
            temperature=0,
            max_tokens=8192,
        )
    if settings.llm_provider == "azure":
        return AzureChatOpenAI(
            azure_endpoint=settings.azure_endpoint,
            api_key=settings.azure_api_key,
            azure_deployment=settings.azure_planner_deployment,
            api_version=settings.azure_api_version,
            temperature=0,
        )
    return ChatOpenAI(
        model=settings.openai_planner_model,
        api_key=settings.openai_api_key,
        temperature=0,
    )


# ── Legacy aliases ────────────────────────────────────────────────
# These are used by existing code (synthesizer, chart_recommender, profiler)
get_worker_llm = get_generation_llm  # kept for backward compat
