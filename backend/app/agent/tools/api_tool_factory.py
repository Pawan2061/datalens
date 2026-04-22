"""Dynamic LangChain tool factory for external API tools.

Converts workspace ApiToolConfig records into LangChain StructuredTools
that the ReAct agent can call at runtime alongside execute_sql.
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any
from urllib.parse import urlparse

import httpx
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field, create_model
from urllib.parse import urlencode

from app.agent.tools.api_token_cache import (
    get_cached_token,
    invalidate_token,
    set_cached_token,
    with_token_lock,
)

logger = logging.getLogger(__name__)

# Safety: block internal/private URLs to prevent SSRF
_BLOCKED_HOSTS = re.compile(
    r"^(localhost|127\.|10\.|172\.(1[6-9]|2\d|3[01])\.|192\.168\.)",
    re.IGNORECASE,
)


def _extract_nested(data: Any, path: str) -> Any:
    """Walk a dot-notation path like 'STOCK_DETAILS.STOCK_ARRAY' into a dict."""
    if not path:
        return data
    for key in path.split("."):
        if isinstance(data, dict):
            data = data.get(key, data)
        else:
            return data
    return data


def _sanitize_tool_name(name: str) -> str:
    """Convert a human name like 'SKU Stock Info' to 'sku_stock_info'."""
    s = re.sub(r"[^a-zA-Z0-9]+", "_", name).strip("_").lower()
    return s or "api_tool"


# Parameter names that represent the "which customer" slot across common
# ERP APIs. When a workspace is scoped to a single customer, we inject that
# value so the LLM never has to ask the end-user to repeat it.
_CUSTOMER_PARAM_ALIASES = {
    "customer_id", "customer_code", "customerid", "customercode",
    "cust_id", "cust_code", "custid", "custcode",
    "customer", "cust", "client_id", "client_code",
    "party_id", "party_code", "account_id", "account_code",
}


def _is_customer_scope_param(param_name: str) -> bool:
    """Return True if an API tool's input param maps to the scoped customer.

    Matching is case-insensitive and ignores a leading/trailing underscore
    or the common `p_` / `@` prefixes seen on stored-procedure wrappers.
    """
    if not param_name:
        return False
    norm = param_name.strip().lower().lstrip("@").lstrip("_")
    if norm.startswith("p_"):
        norm = norm[2:]
    if norm in _CUSTOMER_PARAM_ALIASES:
        return True
    # Loose suffix match: foo_customer_code, X_CUSTOMER_ID etc.
    return norm.endswith("_customer_id") or norm.endswith("_customer_code")


def _is_blocked_url(raw_url: str) -> bool:
    try:
        host = urlparse(raw_url).hostname or ""
    except ValueError:
        return True
    return bool(_BLOCKED_HOSTS.match(host))


def _mask_token(token: str | None) -> str:
    if not token:
        return "none"
    if len(token) <= 4:
        return "***"
    return f"***{token[-4:]}"


def _is_success(data: dict, success_field: str, success_value: str) -> bool:
    """Check whether the API response indicates success.

    If the response doesn't carry the configured field, treat as success
    (HTTP-level errors are caught separately).
    """
    if not success_field:
        return True
    if success_field not in data:
        return True
    return str(data.get(success_field, "")).upper() == str(success_value).upper()


def _log_outgoing_request(
    api_name: str,
    method: str,
    url: str,
    body: dict,
) -> None:
    """Log the final wire-format request so admins can cross-verify URL + params.

    The TOKEN query value is masked; everything else is rendered verbatim.
    """
    try:
        if method == "GET":
            query = urlencode(body) if body else ""
            sep = "&" if "?" in url else "?"
            full = f"{url}{sep}{query}" if query else url
            # Mask TOKEN=<value> anywhere in the final URL
            full_masked = re.sub(
                r"(TOKEN=)([^&]+)",
                lambda m: f"{m.group(1)}{_mask_token(m.group(2))}",
                full,
                flags=re.IGNORECASE,
            )
            logger.info("[api-tool] %s GET %s", api_name, full_masked)
        else:
            body_masked = dict(body or {})
            if "TOKEN" in body_masked:
                body_masked["TOKEN"] = _mask_token(body_masked["TOKEN"])
            logger.info("[api-tool] %s POST %s body=%s", api_name, url, body_masked)
    except Exception:  # noqa: BLE001 — logging must never break the call
        logger.info("[api-tool] %s %s %s (log formatter failed)", api_name, method, url)


async def _do_http_call(
    url: str,
    method: str,
    body: dict,
    headers: dict,
    timeout: float,
    log_label: str | None = None,
) -> dict:
    """Execute a single HTTP request and return decoded JSON.

    Raises httpx exceptions on failure. Pure I/O — no business logic.
    """
    if log_label is not None:
        _log_outgoing_request(log_label, method, url, body)
    async with httpx.AsyncClient(timeout=timeout) as client:
        if method == "POST":
            resp = await client.post(url, json=body, headers=headers)
        else:
            resp = await client.get(url, params=body, headers=headers)
        resp.raise_for_status()
        return resp.json()


async def _fetch_auth_token(
    token_endpoint: str,
    token_response_path: str,
    timeout: float,
) -> tuple[str | None, str | None]:
    """Fetch a fresh auth token.

    Returns (token, error_reason). On success error_reason is None; on failure
    token is None and error_reason carries a short diagnostic string suitable
    for surfacing to the agent/admin.
    """
    try:
        data = await _do_http_call(
            url=token_endpoint,
            method="GET",
            body={},
            headers={},
            timeout=timeout,
            log_label="token-fetch",
        )
    except httpx.HTTPStatusError as e:
        reason = f"token endpoint returned HTTP {e.response.status_code}"
        logger.warning("Token fetch failed for %s: %s", token_endpoint, reason)
        return None, reason
    except httpx.TimeoutException:
        reason = f"token endpoint timed out after {timeout}s"
        logger.warning("Token fetch failed for %s: %s", token_endpoint, reason)
        return None, reason
    except Exception as e:  # noqa: BLE001
        reason = f"token endpoint unreachable: {e}"
        logger.warning("Token fetch failed for %s: %s", token_endpoint, reason)
        return None, reason

    token_value = _extract_nested(data, token_response_path)
    if not isinstance(token_value, str) or not token_value.strip():
        return None, f"token endpoint response missing '{token_response_path}'"
    return token_value.strip(), None


async def _get_or_refresh_token(
    workspace_id: str,
    tool_id: str,
    token_endpoint: str,
    token_response_path: str,
    ttl_seconds: float,
    timeout: float,
    force_refresh: bool,
) -> tuple[str | None, str | None]:
    """Return (token, error_reason). Fetches under a per-tool lock if needed."""
    if not force_refresh:
        cached = get_cached_token(workspace_id, tool_id)
        if cached:
            return cached, None

    lock = await with_token_lock(workspace_id, tool_id)
    async with lock:
        if not force_refresh:
            cached = get_cached_token(workspace_id, tool_id)
            if cached:
                return cached, None

        token, reason = await _fetch_auth_token(token_endpoint, token_response_path, timeout)
        if token:
            set_cached_token(workspace_id, tool_id, token, ttl_seconds)
            logger.info(
                "Fetched new auth token for workspace=%s tool=%s token=%s",
                workspace_id, tool_id, _mask_token(token),
            )
        else:
            invalidate_token(workspace_id, tool_id)
        return token, reason


def _build_error(api_name: str, message: str, duration_ms: float | None = None) -> str:
    payload: dict[str, Any] = {
        "error": message,
        "api_name": api_name,
        "data": [],
        "row_count": 0,
    }
    if duration_ms is not None:
        payload["duration_ms"] = round(duration_ms, 2)
    return json.dumps(payload)


def _build_success(
    api_name: str,
    data: dict,
    response_path: str,
    duration_ms: float,
) -> str:
    extracted = _extract_nested(data, response_path)

    if isinstance(extracted, list):
        rows = extracted
    elif isinstance(extracted, dict):
        for v in extracted.values():
            if isinstance(v, list):
                rows = v
                break
        else:
            rows = [extracted]
    else:
        rows = [{"value": extracted}]

    columns = list(rows[0].keys()) if rows and isinstance(rows[0], dict) else []

    # Cap rows + compact each row to keep the ReAct context under budget.
    # ERP responses often embed nested arrays (e.g. LINE_ITEMS_ARRAY) that make
    # a single row worth thousands of tokens. The full untruncated dataset still
    # reaches the UI via a separate channel — this only bounds the LLM view.
    LLM_ROW_CAP = 25
    total_rows = len(rows)
    visible_rows = [_compact_row_for_llm(r) for r in rows[:LLM_ROW_CAP]]

    payload: dict[str, Any] = {
        "api_name": api_name,
        "data": visible_rows,
        "columns": columns,
        "row_count": total_rows,  # true total, so LLM reports accurate counts
        "duration_ms": round(duration_ms, 2),
        "source": "api",
    }
    if total_rows > LLM_ROW_CAP:
        payload["truncated_for_llm"] = True
        payload["visible_rows"] = len(visible_rows)
        payload["note"] = (
            f"Showing first {LLM_ROW_CAP} of {total_rows} rows in this tool result "
            "(nested arrays replaced with counts). Summarize patterns/totals; the "
            "full dataset is available to the user in the UI. If the user needs a "
            "specific row not shown here, ask them to narrow their query."
        )
    return json.dumps(payload, default=str)


def _compact_row_for_llm(row: Any) -> Any:
    """Strip heavy nested arrays from a response row for LLM consumption.

    Nested lists (e.g. LINE_ITEMS_ARRAY) are replaced with `{__count__: N}` so
    the LLM knows the shape without paying the token cost. Scalars and nested
    dicts pass through unchanged.
    """
    if not isinstance(row, dict):
        return row
    out: dict[str, Any] = {}
    for k, v in row.items():
        if isinstance(v, list):
            out[k] = {"__count__": len(v)}
        else:
            out[k] = v
    return out


def create_api_tool(
    config: dict,
    workspace_id: str = "",
    customer_scope: str = "",
    customer_scope_name: str = "",
) -> StructuredTool | None:
    """Create a LangChain StructuredTool from an ApiToolConfig dict.

    Returns None if the config is invalid or disabled.

    When ``customer_scope`` is set, any input parameter whose name matches a
    known "customer" alias (customer_id, CUSTOMER_CODE, cust_id, ...) is
    pre-filled with the scope value and relaxed to optional — the LLM no
    longer has to ask the end-user which customer they meant. Admin mode
    (scope == "") leaves the schema untouched.
    """
    if not config.get("enabled", True):
        return None

    endpoint_url = config.get("endpoint_url", "")
    if not endpoint_url:
        return None

    if _is_blocked_url(endpoint_url):
        logger.warning("Blocked internal URL for API tool: %s", endpoint_url)
        return None

    auth_mode = (config.get("auth_mode") or "static").lower()
    tool_id = config.get("id", "")

    # Validate two-step config up front so misconfigured tools don't load.
    token_endpoint = config.get("token_endpoint", "") or ""
    if auth_mode == "two_step_token":
        if not token_endpoint:
            logger.warning(
                "API tool '%s' uses two_step_token but has no token_endpoint; skipping",
                config.get("name", tool_id),
            )
            return None
        if _is_blocked_url(token_endpoint):
            logger.warning("Blocked internal URL for token endpoint: %s", token_endpoint)
            return None

    tool_name = config.get("tool_name") or _sanitize_tool_name(config.get("name", "api"))
    api_name = config.get("name", tool_name)
    description = config.get("description", "") or f"Call the {api_name} external API"
    req_code = config.get("req_code", "")
    method = (config.get("method", "POST") or "POST").upper()
    auth_config = config.get("auth_config", {}) or {}
    input_params = config.get("input_parameters", []) or []
    response_path = config.get("response_path", "")
    timeout = float(config.get("timeout_seconds", 30))
    body_template = config.get("body_template", "")
    extra_headers = config.get("headers", {}) or {}

    token_response_path = config.get("token_response_path") or "AUTH_TOKEN"
    token_param_name = config.get("token_param_name") or "TOKEN"
    token_ttl = float(config.get("token_ttl_seconds") or 1800)
    success_field = config.get("success_field") or "RESULT_CODE"
    success_value = config.get("success_value") or "PASS"
    retry_on_auth_failure = bool(config.get("retry_on_auth_failure", True))

    # Track which input params are the "customer" slot so we can log an
    # explicit scope-injection line whenever the tool runs.
    scoped_param_names: list[str] = []

    # Build a dynamic Pydantic model for the tool's input schema
    field_definitions: dict[str, Any] = {}
    for p in input_params:
        pname = p.get("name", "")
        if not pname:
            continue
        ptype = str
        pdesc = p.get("description", pname)
        default = p.get("default_value", "")

        # When this workspace session is scoped to a single customer, any
        # input param that clearly represents the customer slot gets the
        # scope value pre-filled so the LLM never has to ask the user.
        if customer_scope and _is_customer_scope_param(pname):
            scoped_param_names.append(pname)
            scoped_desc = (
                f"{pdesc} — pre-filled from customer scope "
                f"({customer_scope_name or customer_scope}). "
                "Leave empty to use the scope default."
            )
            field_definitions[pname] = (
                ptype,
                Field(default=customer_scope, description=scoped_desc),
            )
            continue

        if p.get("required", True) and not default:
            field_definitions[pname] = (ptype, Field(description=pdesc))
        else:
            field_definitions[pname] = (ptype, Field(default=default or "", description=pdesc))

    if not field_definitions:
        field_definitions["parameters"] = (str, Field(
            default="{}",
            description="JSON object with parameters to send to the API",
        ))

    InputModel = create_model(f"{tool_name}_Input", **field_definitions)

    if scoped_param_names:
        logger.info(
            "[api-tool] %s scope-bound params=%s → '%s' (workspace=%s)",
            api_name, scoped_param_names,
            customer_scope_name or customer_scope, workspace_id,
        )

    def _build_request_body(kwargs: dict, include_static_auth: bool) -> dict:
        body: dict[str, Any] = {}
        if body_template:
            try:
                body = json.loads(body_template)
            except json.JSONDecodeError:
                body = {}
        if include_static_auth:
            if auth_config.get("apikey"):
                body["APIKEY"] = auth_config["apikey"]
            if auth_config.get("token"):
                body["TOKEN"] = auth_config["token"]
        if "parameters" in kwargs:
            try:
                extra = json.loads(kwargs["parameters"])
                if isinstance(extra, dict):
                    body.update(extra)
            except (json.JSONDecodeError, TypeError):
                pass
        else:
            for k, v in kwargs.items():
                if v:  # Only include non-empty values
                    body[k] = v

        # Re-assert the customer scope even if the LLM sent an empty string
        # for the scope param. This closes a loophole where the agent could
        # otherwise call the API un-scoped by clearing the field.
        if customer_scope:
            for sp in scoped_param_names:
                if not body.get(sp):
                    body[sp] = customer_scope
        return body

    def _build_url(extra_token: str | None = None) -> str:
        url = endpoint_url
        parts: list[str] = []
        if req_code:
            parts.append(f"reqCode={req_code}")
        # Two-step mode keeps APIKEY + TOKEN in the URL (matches Incluziv shape).
        if auth_mode == "two_step_token":
            apikey = auth_config.get("apikey")
            if apikey:
                parts.append(f"APIKEY={apikey}")
            if extra_token:
                parts.append(f"{token_param_name}={extra_token}")
        if parts:
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}{'&'.join(parts)}"
        return url

    async def _call_static(kwargs: dict) -> str:
        """Legacy path — behavior identical to the original implementation."""
        start = time.perf_counter()
        body = _build_request_body(kwargs, include_static_auth=True)
        url = _build_url()
        headers = {"Content-Type": "application/json", **extra_headers}

        try:
            data = await _do_http_call(url, method, body, headers, timeout, log_label=api_name)
        except httpx.TimeoutException:
            return _build_error(api_name, f"API call timed out after {timeout}s")
        except httpx.HTTPStatusError as e:
            return _build_error(api_name, f"API returned HTTP {e.response.status_code}")
        except Exception as e:
            return _build_error(api_name, f"API call failed: {str(e)}")

        duration_ms = (time.perf_counter() - start) * 1000

        result_code = data.get("RESULT_CODE", "")
        result_msg = data.get("RESULT_MSG", "")
        if result_code and result_code != "PASS":
            return _build_error(api_name, f"API returned: {result_msg}", duration_ms)

        return _build_success(api_name, data, response_path, duration_ms)

    async def _call_two_step(kwargs: dict) -> str:
        start = time.perf_counter()

        token, token_err = await _get_or_refresh_token(
            workspace_id, tool_id, token_endpoint, token_response_path,
            token_ttl, timeout, force_refresh=False,
        )
        if not token:
            return _build_error(api_name, f"Auth token fetch failed: {token_err or 'unknown reason'}")

        async def _attempt(tok: str) -> dict | Exception:
            body = _build_request_body(kwargs, include_static_auth=False)
            url = _build_url(extra_token=tok)
            headers = {"Content-Type": "application/json", **extra_headers}
            try:
                return await _do_http_call(url, method, body, headers, timeout, log_label=api_name)
            except Exception as exc:  # noqa: BLE001 — surface to caller
                return exc

        result = await _attempt(token)

        if isinstance(result, Exception) or not _is_success(result, success_field, success_value):
            if retry_on_auth_failure:
                logger.info(
                    "Two-step API call non-success; refreshing token workspace=%s tool=%s",
                    workspace_id, tool_id,
                )
                invalidate_token(workspace_id, tool_id)
                token, token_err = await _get_or_refresh_token(
                    workspace_id, tool_id, token_endpoint, token_response_path,
                    token_ttl, timeout, force_refresh=True,
                )
                if not token:
                    return _build_error(
                        api_name,
                        f"Auth token refresh failed: {token_err or 'unknown reason'}",
                    )
                result = await _attempt(token)

        duration_ms = (time.perf_counter() - start) * 1000

        if isinstance(result, httpx.TimeoutException):
            return _build_error(api_name, f"API call timed out after {timeout}s", duration_ms)
        if isinstance(result, httpx.HTTPStatusError):
            return _build_error(
                api_name, f"API returned HTTP {result.response.status_code}", duration_ms,
            )
        if isinstance(result, Exception):
            return _build_error(api_name, f"API call failed: {str(result)}", duration_ms)

        if not _is_success(result, success_field, success_value):
            msg = result.get("RESULT_MSG") or result.get("message") or "Non-success response"
            return _build_error(api_name, f"API returned: {msg}", duration_ms)

        return _build_success(api_name, result, response_path, duration_ms)

    async def _call_api(**kwargs: str) -> str:
        if auth_mode == "two_step_token":
            return await _call_two_step(kwargs)
        return await _call_static(kwargs)

    return StructuredTool.from_function(
        coroutine=_call_api,
        name=tool_name,
        description=description,
        args_schema=InputModel,
    )


def build_workspace_api_tools(
    api_tool_configs: list[dict],
    workspace_id: str = "",
    customer_scope: str = "",
    customer_scope_name: str = "",
) -> list[StructuredTool]:
    """Build LangChain tools from a workspace's api_tools list.

    Filters to enabled tools only and returns ready-to-use StructuredTool instances.
    ``customer_scope`` is forwarded to each tool so customer-slot parameters
    (customer_id, CUSTOMER_CODE, ...) are auto-populated in customer-view mode.
    """
    tools = []
    for cfg in api_tool_configs:
        if not cfg.get("enabled", True):
            continue
        try:
            tool = create_api_tool(
                cfg,
                workspace_id=workspace_id,
                customer_scope=customer_scope,
                customer_scope_name=customer_scope_name,
            )
            if tool:
                tools.append(tool)
        except Exception as e:
            logger.warning("Failed to create API tool '%s': %s", cfg.get("name", "?"), e)
    return tools


def describe_api_tools_for_prompt(
    api_tool_configs: list[dict],
    customer_scope: str = "",
    customer_scope_name: str = "",
) -> str:
    """Generate a prompt section describing available API tools for the LLM."""
    enabled = [c for c in api_tool_configs if c.get("enabled", True)]
    if not enabled:
        return ""

    lines = [
        "\nEXTERNAL API TOOLS:",
        "You have access to these external APIs in addition to the database.",
        "Use them when the user asks about real-time/live data NOT stored in the database.\n",
    ]

    for cfg in enabled:
        tool_name = cfg.get("tool_name") or _sanitize_tool_name(cfg.get("name", "api"))
        desc = cfg.get("description", "")
        params = cfg.get("input_parameters", [])
        resp_fields = cfg.get("response_fields", [])

        lines.append(f"Tool: {tool_name}")
        lines.append(f"  Description: {desc}")
        if params:
            param_strs = []
            for p in params:
                is_scoped = bool(customer_scope) and _is_customer_scope_param(p.get("name", ""))
                req = (
                    "auto-filled from customer scope"
                    if is_scoped
                    else ("required" if p.get("required", True) else "optional")
                )
                param_strs.append(f"{p['name']} ({req}, {p.get('type', 'string')}): {p.get('description', '')}")
            lines.append(f"  Input: {'; '.join(param_strs)}")
        if resp_fields:
            lines.append(f"  Returns fields: {', '.join(resp_fields)}")
        lines.append("")

    if customer_scope:
        scope_label = customer_scope_name or customer_scope
        lines.append(
            f"CUSTOMER SCOPE FOR API TOOLS: Any parameter representing the customer "
            f"(customer_id, CUSTOMER_CODE, cust_id, etc.) is pre-filled with "
            f"'{customer_scope}' ({scope_label}). Do NOT ask the user for their "
            f"customer ID — call the tool directly."
        )
        lines.append("")
    else:
        lines.append(
            "ADMIN MODE FOR API TOOLS: No customer filter is pre-set. If the user asks "
            "a 'my/our'-style question without naming a customer, ask which customer "
            "(or which subset) they want — do NOT guess. For clearly scoped admin "
            "questions naming a specific customer, pass that customer's ID explicitly."
        )
        lines.append("")

    lines.append("ROUTING DECISION:")
    lines.append("- If the question can be answered from the database schema above → use execute_sql")
    lines.append("- If the question requires live/real-time data from external systems → use the appropriate API tool")
    lines.append("- You may combine both: query the DB for context, then call an API for live details")
    lines.append("- API tool results can be passed to analyze_results and recommend_charts_tool just like SQL results")
    lines.append("")

    return "\n".join(lines)
