from __future__ import annotations

import os

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

def get_agent_llm():
    """Haiku — reliable tool-calling model for the ReAct agent."""
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

def get_generation_llm():
    """Gemini Flash — free model for text generation (synthesis, charts, etc.)."""
    if settings.google_api_key:
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            model=settings.gemini_model,
            google_api_key=settings.google_api_key,
            temperature=0,
            max_output_tokens=8192,
        )
    # Fallback to Haiku
    return get_agent_llm()


# ── 3. Deep analysis LLM — Sonnet ────────────────────────────────
# Only used for deep analysis mode (thorough, multi-step reasoning).

def get_planner_llm():
    """Sonnet — high-quality model for deep analysis mode."""
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
get_worker_llm = get_generation_llm
