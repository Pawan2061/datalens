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

import httpx
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field, create_model

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


def create_api_tool(config: dict) -> StructuredTool | None:
    """Create a LangChain StructuredTool from an ApiToolConfig dict.

    Returns None if the config is invalid or disabled.
    """
    if not config.get("enabled", True):
        return None

    endpoint_url = config.get("endpoint_url", "")
    if not endpoint_url:
        return None

    # SSRF protection
    from urllib.parse import urlparse
    parsed = urlparse(endpoint_url)
    if _BLOCKED_HOSTS.match(parsed.hostname or ""):
        logger.warning("Blocked internal URL for API tool: %s", endpoint_url)
        return None

    tool_name = config.get("tool_name") or _sanitize_tool_name(config.get("name", "api"))
    description = config.get("description", "") or f"Call the {config.get('name', '')} external API"
    req_code = config.get("req_code", "")
    method = config.get("method", "POST").upper()
    auth_config = config.get("auth_config", {})
    input_params = config.get("input_parameters", [])
    response_path = config.get("response_path", "")
    timeout = config.get("timeout_seconds", 30)
    body_template = config.get("body_template", "")
    extra_headers = config.get("headers", {})

    # Build a dynamic Pydantic model for the tool's input schema
    # so the LLM knows exactly what parameters to provide
    field_definitions: dict[str, Any] = {}
    for p in input_params:
        pname = p.get("name", "")
        if not pname:
            continue
        ptype = str
        pdesc = p.get("description", pname)
        default = p.get("default_value", "")
        if p.get("required", True) and not default:
            field_definitions[pname] = (ptype, Field(description=pdesc))
        else:
            field_definitions[pname] = (ptype, Field(default=default or "", description=pdesc))

    if not field_definitions:
        # If no explicit params, accept a generic kwargs string
        field_definitions["parameters"] = (str, Field(
            default="{}",
            description="JSON object with parameters to send to the API",
        ))

    InputModel = create_model(f"{tool_name}_Input", **field_definitions)

    async def _call_api(**kwargs: str) -> str:
        """Execute the external API call and return results as JSON string."""
        start = time.perf_counter()

        # Build the request body
        body: dict[str, Any] = {}

        # Start from template if provided
        if body_template:
            try:
                body = json.loads(body_template)
            except json.JSONDecodeError:
                pass

        # Merge auth credentials
        if auth_config.get("apikey"):
            body["APIKEY"] = auth_config["apikey"]
        if auth_config.get("token"):
            body["TOKEN"] = auth_config["token"]

        # Merge LLM-provided input parameters
        if "parameters" in kwargs:
            try:
                extra = json.loads(kwargs["parameters"])
                body.update(extra)
            except (json.JSONDecodeError, TypeError):
                pass
        else:
            for k, v in kwargs.items():
                if v:  # Only include non-empty values
                    body[k] = v

        # Build URL
        url = endpoint_url
        if req_code:
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}reqCode={req_code}"

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                headers = {"Content-Type": "application/json"}
                headers.update(extra_headers)

                if method == "POST":
                    resp = await client.post(url, json=body, headers=headers)
                else:
                    resp = await client.get(url, params=body, headers=headers)

                resp.raise_for_status()
                data = resp.json()
        except httpx.TimeoutException:
            return json.dumps({
                "error": f"API call timed out after {timeout}s",
                "api_name": config.get("name", tool_name),
                "data": [],
                "row_count": 0,
            })
        except httpx.HTTPStatusError as e:
            return json.dumps({
                "error": f"API returned HTTP {e.response.status_code}",
                "api_name": config.get("name", tool_name),
                "data": [],
                "row_count": 0,
            })
        except Exception as e:
            return json.dumps({
                "error": f"API call failed: {str(e)}",
                "api_name": config.get("name", tool_name),
                "data": [],
                "row_count": 0,
            })

        duration_ms = (time.perf_counter() - start) * 1000

        # Check result code
        result_code = data.get("RESULT_CODE", "")
        result_msg = data.get("RESULT_MSG", "")

        if result_code and result_code != "PASS":
            return json.dumps({
                "error": f"API returned: {result_msg}",
                "api_name": config.get("name", tool_name),
                "data": [],
                "row_count": 0,
                "duration_ms": round(duration_ms, 2),
            })

        # Extract the data array using response_path
        extracted = _extract_nested(data, response_path)

        # Normalize to a list of dicts
        if isinstance(extracted, list):
            rows = extracted
        elif isinstance(extracted, dict):
            # Sometimes the path leads to an object with an array inside
            # Try to find the first array value
            for v in extracted.values():
                if isinstance(v, list):
                    rows = v
                    break
            else:
                rows = [extracted]
        else:
            rows = [{"value": extracted}]

        # Extract column names from first row
        columns = list(rows[0].keys()) if rows else []

        return json.dumps({
            "api_name": config.get("name", tool_name),
            "data": rows[:500],  # Cap at 500 rows
            "columns": columns,
            "row_count": len(rows),
            "duration_ms": round(duration_ms, 2),
            "source": "api",
        })

    # Create the StructuredTool
    return StructuredTool.from_function(
        coroutine=_call_api,
        name=tool_name,
        description=description,
        args_schema=InputModel,
    )


def build_workspace_api_tools(api_tool_configs: list[dict]) -> list[StructuredTool]:
    """Build LangChain tools from a workspace's api_tools list.

    Filters to enabled tools only and returns ready-to-use StructuredTool instances.
    """
    tools = []
    for cfg in api_tool_configs:
        if not cfg.get("enabled", True):
            continue
        try:
            tool = create_api_tool(cfg)
            if tool:
                tools.append(tool)
        except Exception as e:
            logger.warning("Failed to create API tool '%s': %s", cfg.get("name", "?"), e)
    return tools


def describe_api_tools_for_prompt(api_tool_configs: list[dict]) -> str:
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
                req = "required" if p.get("required", True) else "optional"
                param_strs.append(f"{p['name']} ({req}, {p.get('type', 'string')}): {p.get('description', '')}")
            lines.append(f"  Input: {'; '.join(param_strs)}")
        if resp_fields:
            lines.append(f"  Returns fields: {', '.join(resp_fields)}")
        lines.append("")

    lines.append("ROUTING DECISION:")
    lines.append("- If the question can be answered from the database schema above → use execute_sql")
    lines.append("- If the question requires live/real-time data from external systems → use the appropriate API tool")
    lines.append("- You may combine both: query the DB for context, then call an API for live details")
    lines.append("- API tool results can be passed to analyze_results and recommend_charts_tool just like SQL results")
    lines.append("")

    return "\n".join(lines)
