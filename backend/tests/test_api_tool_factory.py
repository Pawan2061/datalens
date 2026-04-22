"""Tests for backend/app/agent/tools/api_tool_factory.py.

Covers:
- static-path behavior preserved (regression guard)
- two-step happy path (one token fetch, one data call)
- token caching across calls
- refresh-and-retry on non-PASS response
- bounded retry (no third attempt if refresh fails)
- SSRF block on token_endpoint
- concurrent-call stampede protection (single token fetch)
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from app.agent.tools import api_token_cache
from app.agent.tools.api_tool_factory import create_api_tool


@pytest.fixture(autouse=True)
def _reset_token_cache():
    """Clear token cache between tests so each test starts clean."""
    api_token_cache._entries.clear()
    api_token_cache._locks.clear()
    yield
    api_token_cache._entries.clear()
    api_token_cache._locks.clear()


class _FakeResponse:
    def __init__(self, payload: dict, status: int = 200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import httpx
            raise httpx.HTTPStatusError(
                "error", request=None, response=self,  # type: ignore[arg-type]
            )

    def json(self) -> dict:
        return self._payload


class _FakeClient:
    """Records URLs hit, returns queued payloads."""

    def __init__(self, responses: list[Any]):
        self._responses = list(responses)
        self.calls: list[tuple[str, str]] = []  # (method, url)
        # Full per-call payloads: (method, url, params-or-body-dict).
        # Used by newer tests that need to assert on request body contents.
        self.payloads: list[tuple[str, str, dict]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return None

    def _pop(self) -> Any:
        if not self._responses:
            raise AssertionError("Unexpected extra HTTP call")
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def get(self, url: str, params: dict | None = None, headers: dict | None = None):
        self.calls.append(("GET", url))
        self.payloads.append(("GET", url, dict(params or {})))
        return self._pop()

    async def post(self, url: str, json: dict | None = None, headers: dict | None = None):
        self.calls.append(("POST", url))
        self.payloads.append(("POST", url, dict(json or {})))
        return self._pop()


@pytest.fixture
def patch_client(monkeypatch):
    """Return a helper that installs a fake httpx.AsyncClient."""
    def _install(responses: list[Any]) -> _FakeClient:
        fake = _FakeClient(responses)

        def _factory(*_a, **_k):
            return fake

        import httpx
        monkeypatch.setattr(httpx, "AsyncClient", _factory)
        return fake

    return _install


# ── Static-path regression ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_static_path_unchanged(patch_client):
    client = patch_client([
        _FakeResponse({
            "RESULT_CODE": "PASS",
            "RESULT_MSG": "ok",
            "ITEMS": [{"a": 1}, {"a": 2}],
        }),
    ])
    tool = create_api_tool({
        "id": "t1", "name": "Test", "enabled": True,
        "endpoint_url": "https://api.example.com/action",
        "req_code": "getX", "method": "GET",
        "auth_config": {"apikey": "K"},
        "input_parameters": [{"name": "FOO", "required": True}],
        "response_path": "ITEMS",
    }, workspace_id="ws1")
    assert tool is not None

    out = json.loads(await tool.coroutine(FOO="bar"))
    assert out["row_count"] == 2
    assert out["data"] == [{"a": 1}, {"a": 2}]
    assert len(client.calls) == 1
    assert "reqCode=getX" in client.calls[0][1]


# ── Customer scope injection ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_customer_scope_autofills_customer_param(patch_client):
    """A workspace scoped to a customer must pre-fill CUSTOMER_CODE without
    the LLM (or user) having to supply it."""
    client = patch_client([
        _FakeResponse({"RESULT_CODE": "PASS", "ITEMS": [{"INV": "I1"}]}),
    ])
    tool = create_api_tool({
        "id": "t1", "name": "Outstanding", "enabled": True,
        "endpoint_url": "https://api.example.com/x",
        "req_code": "getOutstanding", "method": "GET",
        "auth_config": {"apikey": "K"},
        "input_parameters": [{"name": "CUSTOMER_CODE", "required": True}],
        "response_path": "ITEMS",
    }, workspace_id="ws1", customer_scope="CUST-42", customer_scope_name="Acme")
    assert tool is not None

    # Call with NO CUSTOMER_CODE — the scope should fill it in.
    out = json.loads(await tool.coroutine())
    assert out["row_count"] == 1
    # The outgoing request body/query must carry the scoped customer.
    assert client.payloads[0][2].get("CUSTOMER_CODE") == "CUST-42"


@pytest.mark.asyncio
async def test_customer_scope_reasserts_when_blanked(patch_client):
    """Even if the LLM passes an empty string, the scope is re-injected
    (closes a silent un-scoping loophole)."""
    client = patch_client([
        _FakeResponse({"RESULT_CODE": "PASS", "ITEMS": [{"x": 1}]}),
    ])
    tool = create_api_tool({
        "id": "t1", "name": "Outstanding", "enabled": True,
        "endpoint_url": "https://api.example.com/x",
        "method": "GET",
        "input_parameters": [{"name": "customer_id", "required": True}],
        "response_path": "ITEMS",
    }, workspace_id="ws1", customer_scope="C9")

    await tool.coroutine(customer_id="")
    assert client.payloads[0][2].get("customer_id") == "C9"


@pytest.mark.asyncio
async def test_admin_mode_leaves_params_untouched(patch_client):
    """With no scope set, the customer param must stay required and NOT be
    auto-populated — the LLM is expected to ask / pass an explicit value."""
    patch_client([
        _FakeResponse({"RESULT_CODE": "PASS", "ITEMS": [{"x": 1}]}),
    ])
    tool = create_api_tool({
        "id": "t1", "name": "Outstanding", "enabled": True,
        "endpoint_url": "https://api.example.com/x",
        "method": "GET",
        "input_parameters": [{"name": "CUSTOMER_CODE", "required": True}],
        "response_path": "ITEMS",
    }, workspace_id="ws1")
    # The schema must still mark CUSTOMER_CODE as required (no default).
    schema = tool.args_schema.model_json_schema()
    assert "CUSTOMER_CODE" in schema.get("required", [])


# ── Two-step happy path ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_two_step_fetches_token_then_calls(patch_client):
    client = patch_client([
        _FakeResponse({"RESULT_CODE": "PASS", "AUTH_TOKEN": "TOK123"}),
        _FakeResponse({"RESULT_CODE": "PASS", "ORDER_DETAILS": [{"ORDER_NO": "O1"}]}),
    ])
    tool = create_api_tool({
        "id": "t1", "name": "OrderStatus", "enabled": True,
        "endpoint_url": "https://api.example.com/ediApiAction.do",
        "req_code": "getBIOrderStatus", "method": "GET",
        "auth_config": {"apikey": "K"},
        "input_parameters": [{"name": "ORDER_ID", "required": True}],
        "response_path": "ORDER_DETAILS",
        "auth_mode": "two_step_token",
        "token_endpoint": "https://api.example.com/ediApiAction.do?reqCode=getAuthToken",
        "token_response_path": "AUTH_TOKEN",
        "token_param_name": "TOKEN",
    }, workspace_id="ws1")
    assert tool is not None

    out = json.loads(await tool.coroutine(ORDER_ID="ABC"))
    assert out["row_count"] == 1
    assert len(client.calls) == 2
    # Second call must carry token
    assert "TOKEN=TOK123" in client.calls[1][1]


@pytest.mark.asyncio
async def test_two_step_token_cached_across_calls(patch_client):
    client = patch_client([
        _FakeResponse({"RESULT_CODE": "PASS", "AUTH_TOKEN": "TOK_A"}),
        _FakeResponse({"RESULT_CODE": "PASS", "ORDER_DETAILS": [{"O": 1}]}),
        _FakeResponse({"RESULT_CODE": "PASS", "ORDER_DETAILS": [{"O": 2}]}),
    ])
    tool = create_api_tool({
        "id": "t1", "name": "T", "enabled": True,
        "endpoint_url": "https://api.example.com/x",
        "method": "GET",
        "auth_config": {"apikey": "K"},
        "input_parameters": [{"name": "Q", "required": True}],
        "response_path": "ORDER_DETAILS",
        "auth_mode": "two_step_token",
        "token_endpoint": "https://api.example.com/auth",
    }, workspace_id="ws1")

    await tool.coroutine(Q="a")
    await tool.coroutine(Q="b")
    # 1 token fetch + 2 data calls = 3
    assert len(client.calls) == 3


# ── Refresh-and-retry ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_two_step_retries_once_on_non_pass(patch_client):
    client = patch_client([
        _FakeResponse({"RESULT_CODE": "PASS", "AUTH_TOKEN": "OLD"}),
        _FakeResponse({"RESULT_CODE": "FAIL", "RESULT_MSG": "expired"}),
        _FakeResponse({"RESULT_CODE": "PASS", "AUTH_TOKEN": "NEW"}),
        _FakeResponse({"RESULT_CODE": "PASS", "ORDER_DETAILS": [{"O": 1}]}),
    ])
    tool = create_api_tool({
        "id": "t1", "name": "T", "enabled": True,
        "endpoint_url": "https://api.example.com/x",
        "method": "GET",
        "auth_config": {"apikey": "K"},
        "input_parameters": [{"name": "Q", "required": True}],
        "response_path": "ORDER_DETAILS",
        "auth_mode": "two_step_token",
        "token_endpoint": "https://api.example.com/auth",
    }, workspace_id="ws1")

    out = json.loads(await tool.coroutine(Q="x"))
    assert out["row_count"] == 1
    # token, failed data, refresh token, successful data = 4
    assert len(client.calls) == 4
    assert "TOKEN=OLD" in client.calls[1][1]
    assert "TOKEN=NEW" in client.calls[3][1]


@pytest.mark.asyncio
async def test_two_step_stops_after_one_retry(patch_client):
    """If refresh-then-retry still fails, no third attempt."""
    client = patch_client([
        _FakeResponse({"RESULT_CODE": "PASS", "AUTH_TOKEN": "T1"}),
        _FakeResponse({"RESULT_CODE": "FAIL", "RESULT_MSG": "nope"}),
        _FakeResponse({"RESULT_CODE": "PASS", "AUTH_TOKEN": "T2"}),
        _FakeResponse({"RESULT_CODE": "FAIL", "RESULT_MSG": "still nope"}),
    ])
    tool = create_api_tool({
        "id": "t1", "name": "T", "enabled": True,
        "endpoint_url": "https://api.example.com/x",
        "method": "GET",
        "auth_config": {"apikey": "K"},
        "input_parameters": [{"name": "Q", "required": True}],
        "response_path": "ORDER_DETAILS",
        "auth_mode": "two_step_token",
        "token_endpoint": "https://api.example.com/auth",
    }, workspace_id="ws1")

    out = json.loads(await tool.coroutine(Q="x"))
    assert "error" in out
    assert "still nope" in out["error"]
    # exactly 4 HTTP round-trips, never 5
    assert len(client.calls) == 4


@pytest.mark.asyncio
async def test_retry_disabled_does_not_refresh(patch_client):
    client = patch_client([
        _FakeResponse({"RESULT_CODE": "PASS", "AUTH_TOKEN": "T1"}),
        _FakeResponse({"RESULT_CODE": "FAIL", "RESULT_MSG": "nope"}),
    ])
    tool = create_api_tool({
        "id": "t1", "name": "T", "enabled": True,
        "endpoint_url": "https://api.example.com/x",
        "method": "GET",
        "auth_config": {"apikey": "K"},
        "input_parameters": [{"name": "Q", "required": True}],
        "response_path": "ORDER_DETAILS",
        "auth_mode": "two_step_token",
        "token_endpoint": "https://api.example.com/auth",
        "retry_on_auth_failure": False,
    }, workspace_id="ws1")

    out = json.loads(await tool.coroutine(Q="x"))
    assert "error" in out
    assert len(client.calls) == 2  # token + one failed data call, no refresh


# ── SSRF guards ─────────────────────────────────────────────────────────

def test_ssrf_blocks_private_token_endpoint():
    tool = create_api_tool({
        "id": "t1", "name": "T", "enabled": True,
        "endpoint_url": "https://api.example.com/x",
        "auth_mode": "two_step_token",
        "token_endpoint": "http://10.0.0.5/auth",
        "input_parameters": [{"name": "Q", "required": True}],
    }, workspace_id="ws1")
    assert tool is None


def test_missing_token_endpoint_rejected():
    tool = create_api_tool({
        "id": "t1", "name": "T", "enabled": True,
        "endpoint_url": "https://api.example.com/x",
        "auth_mode": "two_step_token",
        "token_endpoint": "",
        "input_parameters": [{"name": "Q", "required": True}],
    }, workspace_id="ws1")
    assert tool is None


# ── Concurrency ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_large_response_truncated_for_llm(patch_client):
    """Responses bigger than the LLM cap keep row_count honest but trim data."""
    big_rows = [{"i": i, "x": "y" * 20} for i in range(250)]
    patch_client([
        _FakeResponse({"RESULT_CODE": "PASS", "ITEMS": big_rows}),
    ])
    tool = create_api_tool({
        "id": "t1", "name": "T", "enabled": True,
        "endpoint_url": "https://api.example.com/x",
        "method": "GET",
        "input_parameters": [{"name": "Q", "required": True}],
        "response_path": "ITEMS",
    }, workspace_id="ws1")

    out = json.loads(await tool.coroutine(Q="q"))
    assert out["row_count"] == 250
    assert len(out["data"]) == 25  # LLM_ROW_CAP
    assert out["truncated_for_llm"] is True
    assert "250" in out["note"]


@pytest.mark.asyncio
async def test_small_response_not_truncated(patch_client):
    rows = [{"i": i} for i in range(10)]
    patch_client([
        _FakeResponse({"RESULT_CODE": "PASS", "ITEMS": rows}),
    ])
    tool = create_api_tool({
        "id": "t1", "name": "T", "enabled": True,
        "endpoint_url": "https://api.example.com/x",
        "method": "GET",
        "input_parameters": [{"name": "Q", "required": True}],
        "response_path": "ITEMS",
    }, workspace_id="ws1")

    out = json.loads(await tool.coroutine(Q="q"))
    assert out["row_count"] == 10
    assert len(out["data"]) == 10
    assert "truncated_for_llm" not in out


@pytest.mark.asyncio
async def test_nested_arrays_replaced_with_counts(patch_client):
    """Heavy nested arrays per row get replaced with {__count__: N} for the LLM."""
    rows = [
        {"INVOICE_NO": "INV1", "LINE_ITEMS_ARRAY": [{"i": 1}, {"i": 2}, {"i": 3}]},
        {"INVOICE_NO": "INV2", "LINE_ITEMS_ARRAY": []},
    ]
    patch_client([
        _FakeResponse({"RESULT_CODE": "PASS", "ITEMS": rows}),
    ])
    tool = create_api_tool({
        "id": "t1", "name": "T", "enabled": True,
        "endpoint_url": "https://api.example.com/x",
        "method": "GET",
        "input_parameters": [{"name": "Q", "required": True}],
        "response_path": "ITEMS",
    }, workspace_id="ws1")

    out = json.loads(await tool.coroutine(Q="q"))
    assert out["data"][0]["INVOICE_NO"] == "INV1"
    assert out["data"][0]["LINE_ITEMS_ARRAY"] == {"__count__": 3}
    assert out["data"][1]["LINE_ITEMS_ARRAY"] == {"__count__": 0}


@pytest.mark.asyncio
async def test_concurrent_calls_fetch_token_once(patch_client):
    """Fire N concurrent tool invocations with an empty cache. Exactly one
    token fetch should occur thanks to the per-key lock."""
    # 1 token fetch + 5 data calls
    client = patch_client([
        _FakeResponse({"RESULT_CODE": "PASS", "AUTH_TOKEN": "TOK"}),
        _FakeResponse({"RESULT_CODE": "PASS", "ORDER_DETAILS": [{"O": 1}]}),
        _FakeResponse({"RESULT_CODE": "PASS", "ORDER_DETAILS": [{"O": 2}]}),
        _FakeResponse({"RESULT_CODE": "PASS", "ORDER_DETAILS": [{"O": 3}]}),
        _FakeResponse({"RESULT_CODE": "PASS", "ORDER_DETAILS": [{"O": 4}]}),
        _FakeResponse({"RESULT_CODE": "PASS", "ORDER_DETAILS": [{"O": 5}]}),
    ])
    tool = create_api_tool({
        "id": "t1", "name": "T", "enabled": True,
        "endpoint_url": "https://api.example.com/x",
        "method": "GET",
        "auth_config": {"apikey": "K"},
        "input_parameters": [{"name": "Q", "required": True}],
        "response_path": "ORDER_DETAILS",
        "auth_mode": "two_step_token",
        "token_endpoint": "https://api.example.com/auth",
    }, workspace_id="ws1")

    results = await asyncio.gather(*(tool.coroutine(Q=str(i)) for i in range(5)))
    assert all(json.loads(r)["row_count"] == 1 for r in results)

    # exactly one token fetch, five data calls
    token_fetches = [c for c in client.calls if "/auth" in c[1]]
    assert len(token_fetches) == 1
    assert len(client.calls) == 6
