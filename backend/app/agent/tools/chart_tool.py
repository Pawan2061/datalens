from __future__ import annotations

import json

from langchain_core.tools import tool

from app.agent.chart_recommender import recommend_chart, _merge_compatible_charts
from app.schemas.insight import ChartRecommendation, SubQueryResult


@tool
def recommend_charts_tool(results_json: str) -> str:
    """Recommend chart visualizations for SQL query results.

    Uses heuristic column classification to pick the best chart type
    (bar, grouped_bar, horizontal_bar, stacked_bar, line, multi_line,
    area, pie, scatter, treemap, funnel, radar, radial_bar, heatmap,
    waterfall, gauge, KPI, table) based on data shape.

    grouped_bar: side-by-side bars when data has 2 categorical + 1 numeric
                 (e.g., metric by category1 AND category2).
    multi_line:  lines per series when data has 2 categorical + 1 numeric
                 with many x-values (trend-like).

    Args:
        results_json: JSON string of query results. Should be a list of objects,
            each with keys: description, sql, columns, data, row_count.

    Returns:
        JSON array of chart recommendations with chart_type, title, axes, and data.
    """
    try:
        results_list = json.loads(results_json)
    except json.JSONDecodeError:
        return json.dumps([])

    # Normalize: accept either a list of result objects or a single one
    if isinstance(results_list, dict):
        results_list = [results_list]

    raw_recs: list[ChartRecommendation] = []
    for i, r in enumerate(results_list):
        if not r.get("data"):
            continue

        sub_result = SubQueryResult(
            index=r.get("index", i),
            description=r.get("description", f"Query {i + 1}"),
            sql=r.get("sql", ""),
            data=r["data"],
            columns=r.get("columns", list(r["data"][0].keys()) if r["data"] else []),
            row_count=r.get("row_count", len(r["data"])),
            duration_ms=r.get("duration_ms", 0),
            error=r.get("error"),
        )
        raw_recs.append(recommend_chart(sub_result))

    # Merge charts that share the same x-axis into multi-series charts
    merged = _merge_compatible_charts(raw_recs)

    return json.dumps([c.model_dump() for c in merged], default=str)
