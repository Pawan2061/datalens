from __future__ import annotations

import sys
import types
from datetime import date

from app.agent.graph import _estimate_cost, _should_use_strong_model
from app.agent.tools.api_tool_factory import describe_api_tools_for_prompt
from app.config import settings
from app.llm.pricing import estimate_token_cost_usd, resolve_model_pricing


def test_quick_moderate_stays_on_cheap_model():
    assert _should_use_strong_model("quick", "simple") is False
    assert _should_use_strong_model("quick", "moderate") is False
    assert _should_use_strong_model("quick", "complex") is True
    assert _should_use_strong_model("deep", "simple") is True


def test_sonnet_5_intro_pricing_and_cache_math():
    pricing, matched = resolve_model_pricing(
        "claude-sonnet-5-20260701",
        as_of=date(2026, 7, 8),
    )
    assert matched is True
    assert pricing == {"input": 2.0, "output": 10.0}

    assert estimate_token_cost_usd(
        10_000,
        2_000,
        "claude-sonnet-5",
        cache_read_tokens=4_000,
        cache_creation_tokens=2_000,
        as_of=date(2026, 7, 8),
    ) == 0.0338


def test_sonnet_5_standard_pricing_after_intro_window():
    pricing, matched = resolve_model_pricing(
        "claude-sonnet-5",
        as_of=date(2026, 9, 1),
    )
    assert matched is True
    assert pricing == {"input": 3.0, "output": 15.0}


def test_graph_cost_estimator_uses_shared_pricing():
    assert _estimate_cost(
        1_000,
        1_000,
        "claude-haiku-4-5",
        cache_read_tokens=200,
        cache_creation_tokens=100,
    ) == 0.005845


def test_api_tool_prompt_is_compact_and_keeps_scope_rules():
    prompt = describe_api_tools_for_prompt(
        [
            {
                "enabled": True,
                "name": "Stock Availability",
                "tool_name": "stock_availability",
                "description": " ".join(["Detailed live stock lookup"] * 30),
                "input_parameters": [
                    {
                        "name": "CUSTOMER_CODE",
                        "type": "string",
                        "required": True,
                        "description": "Customer code to scope the lookup",
                    },
                    {
                        "name": "ITEM_CODE",
                        "type": "string",
                        "required": True,
                        "description": "Item or fabric code",
                    },
                ],
                "response_fields": [f"FIELD_{i}" for i in range(30)],
            }
        ],
        customer_scope="C001",
        customer_scope_name="Acme",
    )

    assert "stock_availability" in prompt
    assert "CUSTOMER_CODE:string:auto" in prompt
    assert "...+10" in prompt
    assert "call directly" in prompt
    assert len(prompt) < 900


def test_anthropic_clients_use_task_specific_caps(monkeypatch):
    calls: list[dict] = []

    class FakeChatAnthropic:
        def __init__(self, **kwargs):
            calls.append(kwargs)

    fake_module = types.SimpleNamespace(ChatAnthropic=FakeChatAnthropic)
    monkeypatch.setitem(sys.modules, "langchain_anthropic", fake_module)
    monkeypatch.setattr(settings, "llm_provider", "anthropic")
    monkeypatch.setattr(settings, "google_api_key", "")
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(settings, "anthropic_foundry_key", "")
    monkeypatch.setattr(settings, "anthropic_foundry_url", "")
    monkeypatch.setattr(settings, "anthropic_agent_max_tokens", 2048)
    monkeypatch.setattr(settings, "anthropic_conversational_max_tokens", 700)
    monkeypatch.setattr(settings, "anthropic_synthesis_max_tokens", 1400)
    monkeypatch.setattr(settings, "anthropic_planner_max_tokens", 4096)

    from app.llm import openai_llm

    openai_llm.get_agent_llm.cache_clear()
    openai_llm.get_conversational_llm.cache_clear()
    openai_llm.get_synthesis_llm.cache_clear()
    openai_llm.get_planner_llm.cache_clear()

    openai_llm.get_agent_llm()
    openai_llm.get_conversational_llm()
    openai_llm.get_synthesis_llm()
    openai_llm.get_planner_llm()

    assert [call["max_tokens"] for call in calls] == [2048, 700, 1400, 4096]
