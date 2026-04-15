from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel


class ChartType(str, Enum):
    bar = "bar"
    grouped_bar = "grouped_bar"
    line = "line"
    multi_line = "multi_line"
    pie = "pie"
    scatter = "scatter"
    stacked_bar = "stacked_bar"
    area = "area"
    kpi = "kpi"
    table = "table"
    horizontal_bar = "horizontal_bar"
    treemap = "treemap"
    funnel = "funnel"
    radar = "radar"
    radial_bar = "radial_bar"
    heatmap = "heatmap"
    waterfall = "waterfall"
    gauge = "gauge"


class SubQuery(BaseModel):
    index: int
    description: str
    sql: str
    depends_on: list[int] = []


class QueryPlan(BaseModel):
    reasoning: str
    sub_queries: list[SubQuery]


class SubQueryResult(BaseModel):
    index: int
    description: str
    sql: str
    data: list[dict]
    columns: list[str]
    row_count: int
    duration_ms: float
    error: str | None = None


class KeyFinding(BaseModel):
    headline: str
    detail: str
    significance: Literal["high", "medium", "low"]


class InsightSummary(BaseModel):
    title: str
    narrative: str
    key_findings: list[KeyFinding]
    follow_up_questions: list[str]


class ChartRecommendation(BaseModel):
    chart_type: ChartType
    title: str
    x_axis: str | None
    y_axis: str | list[str] | None
    color_by: str | None = None
    data: list[dict]
    reasoning: str
    config: dict | None = None


class TableData(BaseModel):
    title: str
    columns: list[str]
    data: list[dict]


class ExecutionMetadata(BaseModel):
    total_duration_ms: float
    sub_query_count: int
    total_rows: int
    # Token usage tracking
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    model_name: str = ""
    estimated_cost_usd: float = 0.0
    cached: bool = False


class InsightResult(BaseModel):
    summary: InsightSummary
    charts: list[ChartRecommendation]
    tables: list[TableData]
    execution_metadata: ExecutionMetadata
