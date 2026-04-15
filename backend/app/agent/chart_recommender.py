from __future__ import annotations

import re
from enum import Enum

from app.schemas.insight import ChartRecommendation, ChartType, SubQueryResult


class ColumnType(str, Enum):
    NUMERIC = "numeric"
    CATEGORICAL = "categorical"
    TEMPORAL = "temporal"
    BOOLEAN = "boolean"
    TEXT = "text"


_TEMPORAL_KEYWORDS: set[str] = {
    "date", "time", "month", "year", "day", "quarter", "week",
    "timestamp", "created", "updated", "modified", "posted",
    "processed", "completed", "started", "ended", "period",
}

# Patterns that strongly suggest a date/datetime value
_DATE_PATTERNS = [
    re.compile(r"^\d{4}-\d{2}-\d{2}"),          # 2025-01-01 or 2025-01-01 00:00:00
    re.compile(r"^\d{2}/\d{2}/\d{4}"),           # 01/31/2025
    re.compile(r"^\d{4}/\d{2}/\d{2}"),           # 2025/01/31
    re.compile(r"^\d{2}-\w{3}-\d{4}"),           # 01-Jan-2025
]


def _looks_like_date(value: str) -> bool:
    """Check if a string value looks like a date/datetime."""
    s = str(value).strip()
    return any(p.match(s) for p in _DATE_PATTERNS)


def classify_column(col_name: str, values: list) -> ColumnType:
    """Classify a column based on its name and sample values."""

    non_null_values = [v for v in values if v is not None]

    # --- Pre-check: are the values predominantly numeric? ---
    # This MUST run first so that columns like "avg_processing_time" (numeric
    # values despite "time" in the name) are not misclassified as TEMPORAL.
    is_numeric = False
    if non_null_values:
        numeric_count = 0
        for v in non_null_values:
            try:
                float(v)
                numeric_count += 1
            except (ValueError, TypeError):
                pass
        is_numeric = numeric_count / len(non_null_values) > 0.8

    # --- Temporal check (name-based) ---
    # Only trust name-based temporal hints when values are NOT plain numbers.
    # Columns like "avg_time", "processing_time", "total_time" hold numeric
    # durations, not date/datetime values — these must stay NUMERIC.
    name_lower = col_name.lower()
    tokens = re.split(r"[_\s\-]+", name_lower)
    name_is_temporal = False
    for keyword in _TEMPORAL_KEYWORDS:
        if keyword in tokens:
            name_is_temporal = True
            break
    if not name_is_temporal and len(tokens) > 1 and tokens[-1] in ("at", "on", "dt"):
        name_is_temporal = True

    if name_is_temporal and not is_numeric:
        # Name says temporal AND values aren't plain numbers → TEMPORAL
        return ColumnType.TEMPORAL

    # --- Temporal check (value-based) — sample first few non-null values ---
    if non_null_values and not is_numeric:
        sample = non_null_values[:10]
        date_hits = sum(1 for v in sample if _looks_like_date(v))
        if date_hits / len(sample) > 0.6:
            return ColumnType.TEMPORAL

    # --- Numeric check (value-based) ---
    if is_numeric:
        return ColumnType.NUMERIC

    # --- Categorical check ---
    # For small result sets (e.g. GROUP BY with 3 rows), string columns
    # with few unique values are clearly categorical.
    total = len(non_null_values)
    if total > 0:
        unique_count = len(set(str(v) for v in non_null_values))
        if unique_count <= 20:
            return ColumnType.CATEGORICAL

    return ColumnType.TEXT


def _extract_column_values(data: list[dict], column: str) -> list:
    """Extract all values for a given column from the data rows."""
    return [row.get(column) for row in data]


def _avg_label_length(data: list[dict], col: str) -> float:
    """Average string length of values in a categorical column."""
    lengths = [len(str(row.get(col, ""))) for row in data]
    return sum(lengths) / max(len(lengths), 1)


def _is_monotonically_decreasing(data: list[dict], col: str) -> bool:
    """Check if numeric values are roughly monotonically decreasing (funnel)."""
    values = [row.get(col) for row in data if row.get(col) is not None]
    try:
        nums = [float(v) for v in values]
    except (ValueError, TypeError):
        return False
    if len(nums) < 3:
        return False
    decreasing_count = sum(1 for i in range(1, len(nums)) if nums[i] <= nums[i - 1])
    return decreasing_count / (len(nums) - 1) >= 0.8


def _values_look_like_percentages(data: list[dict], col: str) -> bool:
    """Check if numeric values are in 0-100 range (percentage-like)."""
    values = [row.get(col) for row in data if row.get(col) is not None]
    try:
        nums = [float(v) for v in values]
    except (ValueError, TypeError):
        return False
    return all(0 <= n <= 100 for n in nums) if nums else False


def recommend_chart(result: SubQueryResult) -> ChartRecommendation:
    """Analyse a single sub-query result and recommend the best chart type."""

    columns = result.columns
    data = result.data

    # --- Classify every column ---
    col_types: dict[str, ColumnType] = {}
    for col in columns:
        values = _extract_column_values(data, col)
        col_types[col] = classify_column(col, values)

    numeric_cols: list[str] = [c for c, t in col_types.items() if t == ColumnType.NUMERIC]
    categorical_cols: list[str] = [c for c, t in col_types.items() if t == ColumnType.CATEGORICAL]
    temporal_cols: list[str] = [c for c, t in col_types.items() if t == ColumnType.TEMPORAL]

    num_numeric = len(numeric_cols)
    num_categorical = len(categorical_cols)
    num_temporal = len(temporal_cols)
    row_count = result.row_count
    col_count = len(columns)

    # --- Scoring matrix ---
    scores: dict[ChartType, int] = {ct: 0 for ct in ChartType}

    # Rule: single-row result → ALWAYS KPI (highest priority)
    # Even "top collection name" or "total revenue" should show as a tile
    if row_count == 1 and col_count <= 4:
        scores[ChartType.kpi] = 15  # unconditionally highest — never overridden

    # Rule: small comparison (2-4 rows, 1 categorical + 1-2 numeric) → KPI tiles
    # e.g. "VELMA avg sales vs FABRIC SWATCHES avg sales" → 2 rows, 2 cols
    # These are simple value comparisons, not chart-worthy data
    if 2 <= row_count <= 4 and num_categorical >= 1 and 1 <= num_numeric <= 2 and col_count <= 3:
        scores[ChartType.kpi] = 14  # highest after single-row — beats bar/pie

    # Rule: TABLE only for genuinely wide/long results
    if row_count > 10 and col_count > 3:
        scores[ChartType.table] = 5  # low priority — other charts preferred

    # Rule: 1 categorical + 1 numeric
    if num_categorical >= 1 and num_numeric >= 1:
        unique_values = len(set(
            str(row.get(categorical_cols[0])) for row in data
        ))
        if num_numeric > 1:
            # Multiple metrics → MUST be bar (multi-bar). Pie can only show 1 metric.
            scores[ChartType.bar] = 11
            scores[ChartType.pie] = 4
        elif unique_values <= 6:
            scores[ChartType.pie] = 10
            scores[ChartType.bar] = 8
        else:
            scores[ChartType.bar] = 10
            scores[ChartType.pie] = 6

    # Rule: Many rows → line is better than bar (bar becomes unreadable past ~15 values)
    if row_count > 15 and (num_numeric >= 1) and (num_categorical >= 1 or num_temporal >= 1):
        x_col = temporal_cols[0] if temporal_cols else categorical_cols[0]
        x_unique = len(set(str(row.get(x_col)) for row in data))
        if x_unique > 15:
            scores[ChartType.line] = max(scores.get(ChartType.line, 0), 11)
            # Reduce bar-family scores — thin bars are unreadable
            scores[ChartType.bar] = min(scores.get(ChartType.bar, 0), 7)
            scores[ChartType.pie] = min(scores.get(ChartType.pie, 0), 4)

    # Rule: 1 temporal + 1 numeric -> line / area
    if num_temporal >= 1 and num_numeric == 1:
        scores[ChartType.line] = 10
        scores[ChartType.area] = 8

    # Rule: 1 temporal + N numeric -> multi-series line
    if num_temporal >= 1 and num_numeric > 1:
        scores[ChartType.line] = 10

    # Rule: 2+ numeric (no categorical / temporal) -> scatter
    if num_numeric >= 2 and num_categorical == 0 and num_temporal == 0:
        scores[ChartType.scatter] = 10

    # ── Advanced chart scoring rules ─────────────────────────────────

    # Rule: Grouped Bar — 2 categorical + 1 numeric (side-by-side comparison)
    # Preferred over stacked when comparing individual values across groups
    if num_categorical >= 2 and num_numeric >= 1:
        scores[ChartType.grouped_bar] = 11
        scores[ChartType.stacked_bar] = 9

    # Rule: Multi-Line — 2 categorical + 1 numeric, many x-values suggest trend
    if num_categorical >= 2 and num_numeric >= 1:
        x_unique = len(set(str(row.get(categorical_cols[0])) for row in data))
        if x_unique >= 4:
            scores[ChartType.multi_line] = 10

    # Rule: Horizontal Bar — long labels or many categories
    # But NOT when there are 2+ categorical dims — grouped_bar handles that better
    if num_categorical >= 1 and num_numeric >= 1:
        avg_len = _avg_label_length(data, categorical_cols[0])
        unique_cats = len(set(str(row.get(categorical_cols[0])) for row in data))
        if avg_len > 15 or unique_cats > 8:
            # If we already have grouped_bar (2+ categories), keep horizontal_bar lower
            if num_categorical >= 2:
                scores[ChartType.horizontal_bar] = 8
            else:
                scores[ChartType.horizontal_bar] = 11
            scores[ChartType.bar] = max(scores[ChartType.bar] - 3, 0)

    # Rule: Treemap — 1 categorical + 1 numeric, many categories
    if num_categorical >= 1 and num_numeric >= 1:
        unique_cats = len(set(str(row.get(categorical_cols[0])) for row in data))
        if unique_cats > 10:
            scores[ChartType.treemap] = 9
        elif unique_cats > 5:
            scores[ChartType.treemap] = 7

    # Rule: Funnel — values monotonically decreasing
    if num_categorical >= 1 and num_numeric >= 1 and row_count >= 3:
        if _is_monotonically_decreasing(data, numeric_cols[0]):
            scores[ChartType.funnel] = 11

    # Rule: Radar — 3+ numeric columns, few rows (multi-dimensional)
    # Only prefer radar when there's NO clear categorical grouping dimension;
    # when there IS a categorical column, multi-bar is usually clearer.
    if num_numeric >= 3 and row_count <= 5:
        if num_categorical == 0:
            scores[ChartType.radar] = 10
        else:
            scores[ChartType.radar] = 7  # lower than bar so multi-bar wins

    # Rule: Radial Bar — 2-5 rows, percentage values
    if 2 <= row_count <= 5 and num_categorical >= 1 and num_numeric >= 1:
        if _values_look_like_percentages(data, numeric_cols[0]):
            scores[ChartType.radial_bar] = 9

    # Rule: Heatmap — 2 categorical + 1 numeric (matrix / pivot)
    if num_categorical >= 2 and num_numeric >= 1 and row_count > 4:
        cat1_unique = len(set(str(row.get(categorical_cols[0])) for row in data))
        cat2_unique = len(set(str(row.get(categorical_cols[1])) for row in data))
        if cat1_unique >= 2 and cat2_unique >= 2:
            scores[ChartType.heatmap] = 10

    # Rule: Gauge — single row, percentage value
    if row_count == 1 and num_numeric >= 1:
        if _values_look_like_percentages(data, numeric_cols[0]):
            scores[ChartType.gauge] = 11

    # Tiebreaker: grouped_bar / stacked_bar vs heatmap
    if num_categorical >= 2 and scores.get(ChartType.heatmap, 0) > 0:
        cat1_u = len(set(str(row.get(categorical_cols[0])) for row in data))
        cat2_u = len(set(str(row.get(categorical_cols[1])) for row in data))
        if row_count >= cat1_u * cat2_u * 0.7 and cat1_u >= 3 and cat2_u >= 3:
            # Near-complete matrix with enough cells → heatmap wins
            scores[ChartType.heatmap] = 12
        else:
            # Keep grouped_bar as the winner for comparison tasks
            scores[ChartType.grouped_bar] = max(scores.get(ChartType.grouped_bar, 0), 11)

    # --- Pick the highest scoring chart type ---
    best_type = max(scores, key=lambda ct: scores[ct])

    # Smart fallback when all scores are zero — prefer a visual chart over TABLE
    if scores[best_type] == 0:
        # If there are at least 2 columns, try bar chart
        if col_count >= 2 and row_count > 1:
            # Pick the first non-numeric column as x, first numeric as y
            non_numeric = [c for c in columns if col_types.get(c) != ColumnType.NUMERIC]
            if non_numeric and numeric_cols:
                best_type = ChartType.bar if row_count > 6 else ChartType.pie
                # Inject the inferred columns into the lists for axis mapping
                if not categorical_cols:
                    categorical_cols.append(non_numeric[0])
            elif numeric_cols and len(numeric_cols) >= 2:
                best_type = ChartType.scatter
            else:
                best_type = ChartType.bar
        elif row_count == 1:
            best_type = ChartType.kpi
        else:
            best_type = ChartType.table

    # --- Map axes ---
    x_axis: str | None = None
    y_axis: str | list[str] | None = None
    color_by: str | None = None
    config: dict | None = None
    reasoning_parts: list[str] = []

    if best_type == ChartType.kpi:
        # KPI: no axes needed
        reasoning_parts.append(
            f"Only {row_count} row(s) returned; a KPI card is the clearest presentation."
        )

    elif best_type == ChartType.table:
        reasoning_parts.append(
            f"Result has {row_count} rows and {col_count} columns; a table preserves full detail."
        )

    elif best_type in (ChartType.line, ChartType.area):
        x_axis = temporal_cols[0] if temporal_cols else (categorical_cols[0] if categorical_cols else columns[0])
        if num_numeric == 1:
            y_axis = numeric_cols[0]
        else:
            y_axis = numeric_cols
        reasoning_parts.append(
            f"Temporal column '{x_axis}' paired with numeric data suggests a {best_type.value} chart."
        )

    elif best_type == ChartType.bar:
        x_axis = categorical_cols[0] if categorical_cols else columns[0]
        # Multi-bar: use ALL numeric columns when there are multiple
        if num_numeric > 1:
            y_axis = numeric_cols
        else:
            y_axis = numeric_cols[0] if numeric_cols else columns[1] if len(columns) > 1 else None
        if num_categorical > 1:
            color_by = categorical_cols[1]
        reasoning_parts.append(
            f"Categorical column '{x_axis}' with {num_numeric} numeric value(s) suits a bar chart."
        )

    elif best_type == ChartType.pie:
        x_axis = categorical_cols[0] if categorical_cols else columns[0]
        y_axis = numeric_cols[0] if numeric_cols else columns[1] if len(columns) > 1 else None
        unique_count = len(set(str(row.get(x_axis)) for row in data))
        reasoning_parts.append(
            f"{unique_count} categories in '{x_axis}' — a pie chart shows proportions clearly."
        )

    elif best_type == ChartType.scatter:
        x_axis = numeric_cols[0]
        y_axis = numeric_cols[1]
        if num_categorical >= 1:
            color_by = categorical_cols[0]
        reasoning_parts.append(
            f"Two numeric columns ('{x_axis}' vs '{y_axis}') are best shown as a scatter plot."
        )

    # ── Advanced chart axis mapping ──────────────────────────────────

    elif best_type == ChartType.grouped_bar:
        x_axis = categorical_cols[0]
        y_axis = numeric_cols[0] if num_numeric == 1 else numeric_cols
        color_by = categorical_cols[1] if num_categorical > 1 else None
        reasoning_parts.append(
            f"Comparing '{y_axis}' across '{x_axis}' grouped by '{color_by}' — a grouped bar enables direct comparison."
        )

    elif best_type == ChartType.multi_line:
        x_axis = categorical_cols[0]
        y_axis = numeric_cols[0] if num_numeric == 1 else numeric_cols
        color_by = categorical_cols[1] if num_categorical > 1 else None
        reasoning_parts.append(
            f"Tracking '{y_axis}' across '{x_axis}' with series per '{color_by}' — a multi-line chart shows trends."
        )

    elif best_type == ChartType.stacked_bar:
        x_axis = categorical_cols[0]
        y_axis = numeric_cols[0] if num_numeric == 1 else numeric_cols
        color_by = categorical_cols[1] if num_categorical > 1 else None
        reasoning_parts.append(
            f"Multiple categories across '{x_axis}' grouped by '{color_by}' — a stacked bar shows composition."
        )

    elif best_type == ChartType.horizontal_bar:
        x_axis = categorical_cols[0] if categorical_cols else columns[0]
        y_axis = numeric_cols[0] if num_numeric == 1 else numeric_cols
        reasoning_parts.append(
            f"Long category labels in '{x_axis}' — horizontal bars prevent label overlap."
        )

    elif best_type == ChartType.treemap:
        x_axis = categorical_cols[0] if categorical_cols else columns[0]
        y_axis = numeric_cols[0] if numeric_cols else None
        reasoning_parts.append(
            f"Many categories in '{x_axis}' — treemap shows relative sizes at a glance."
        )

    elif best_type == ChartType.funnel:
        x_axis = categorical_cols[0] if categorical_cols else columns[0]
        y_axis = numeric_cols[0] if numeric_cols else None
        reasoning_parts.append(
            f"Values decrease across stages in '{x_axis}' — a funnel chart shows the pipeline."
        )

    elif best_type == ChartType.radar:
        x_axis = categorical_cols[0] if categorical_cols else None
        y_axis = numeric_cols
        reasoning_parts.append(
            f"{len(numeric_cols)} dimensions across {row_count} entities — radar chart enables multi-dimensional comparison."
        )

    elif best_type == ChartType.radial_bar:
        x_axis = categorical_cols[0] if categorical_cols else columns[0]
        y_axis = numeric_cols[0] if numeric_cols else None
        reasoning_parts.append(
            f"Percentage values for '{x_axis}' — radial bars show progress visually."
        )

    elif best_type == ChartType.heatmap:
        x_axis = categorical_cols[0]
        y_axis = numeric_cols[0] if numeric_cols else None
        color_by = categorical_cols[1] if len(categorical_cols) > 1 else None
        config = {
            "row_key": categorical_cols[0],
            "col_key": categorical_cols[1] if len(categorical_cols) > 1 else categorical_cols[0],
            "value_key": numeric_cols[0] if numeric_cols else columns[-1],
        }
        reasoning_parts.append(
            "Two categorical dimensions with numeric values — a heatmap reveals patterns in the matrix."
        )

    elif best_type == ChartType.waterfall:
        x_axis = categorical_cols[0] if categorical_cols else columns[0]
        y_axis = numeric_cols[0] if numeric_cols else None
        reasoning_parts.append(
            "Sequential additive/subtractive values — a waterfall shows running impact."
        )

    elif best_type == ChartType.gauge:
        x_axis = None
        y_axis = numeric_cols[0] if numeric_cols else columns[0]
        config = {"max": 100}
        reasoning_parts.append(
            "Single percentage metric — a gauge provides clear goal visualization."
        )

    reasoning = " ".join(reasoning_parts) if reasoning_parts else "Default chart recommendation."

    return ChartRecommendation(
        chart_type=best_type,
        title=result.description,
        x_axis=x_axis,
        y_axis=y_axis,
        color_by=color_by,
        data=data,
        reasoning=reasoning,
        config=config,
    )


def _x_axis_values(rec: ChartRecommendation) -> set[str]:
    """Extract the set of x-axis values from a chart's data."""
    if not rec.x_axis or not rec.data:
        return set()
    return {str(row.get(rec.x_axis, "")) for row in rec.data}


def _merge_compatible_charts(
    recommendations: list[ChartRecommendation],
) -> list[ChartRecommendation]:
    """Merge multiple single-series charts that share the same x-axis.

    When the agent writes separate queries for each metric (e.g., one for
    COUNT, one for AVG), this detects charts with the same x-axis column
    and merges them into a single multi-bar or multi-line chart.

    Matching is done in two passes:
    1. Exact x_axis column name match (fast path)
    2. Value-overlap match — if two charts have different x_axis column names
       but ≥70% of their x-axis values overlap, they are merged (handles cases
       like "tenant_id" vs "c.tenant_id" or aliased columns).
    """
    if len(recommendations) <= 1:
        return recommendations

    # Charts that can be merged into multi-series
    CATEGORICAL_TYPES = {ChartType.bar, ChartType.pie, ChartType.stacked_bar, ChartType.grouped_bar, ChartType.horizontal_bar}
    TEMPORAL_TYPES = {ChartType.line, ChartType.area, ChartType.multi_line}

    # Classify each chart into a merge group type
    chart_group_type: dict[int, str] = {}
    for i, rec in enumerate(recommendations):
        if not rec.x_axis:
            continue
        if rec.chart_type in CATEGORICAL_TYPES:
            chart_group_type[i] = "categorical"
        elif rec.chart_type in TEMPORAL_TYPES:
            chart_group_type[i] = "temporal"

    # Pass 1: Group by exact (merge_group, x_axis)
    merge_groups: dict[tuple[str, str], list[int]] = {}
    for i, group_key in chart_group_type.items():
        key = (group_key, recommendations[i].x_axis)
        merge_groups.setdefault(key, []).append(i)

    # Pass 2: Merge groups with different x_axis names but overlapping values
    # e.g. "tenant_id" and "tenant" both containing {"Acme", "Globex", "Initech"}
    group_keys = list(merge_groups.keys())
    merged_group_keys: set[tuple[str, str]] = set()
    for a_idx in range(len(group_keys)):
        if group_keys[a_idx] in merged_group_keys:
            continue
        a_key = group_keys[a_idx]
        a_group, a_xaxis = a_key
        # Collect x-axis values for all charts in group a
        a_values: set[str] = set()
        for i in merge_groups[a_key]:
            a_values |= _x_axis_values(recommendations[i])

        for b_idx in range(a_idx + 1, len(group_keys)):
            if group_keys[b_idx] in merged_group_keys:
                continue
            b_key = group_keys[b_idx]
            b_group, b_xaxis = b_key
            if a_group != b_group or a_xaxis == b_xaxis:
                continue  # Different chart families or already same x_axis

            b_values: set[str] = set()
            for i in merge_groups[b_key]:
                b_values |= _x_axis_values(recommendations[i])

            # Check overlap
            if not a_values or not b_values:
                continue
            overlap = len(a_values & b_values) / min(len(a_values), len(b_values))
            if overlap >= 0.7:
                # Merge group b into group a — remap x_axis column names
                # Keep a_xaxis as the canonical name
                for i in merge_groups[b_key]:
                    rec = recommendations[i]
                    old_x = rec.x_axis
                    if old_x and old_x != a_xaxis:
                        # Rename x_axis column in data rows
                        for row in rec.data:
                            if old_x in row and a_xaxis not in row:
                                row[a_xaxis] = row.pop(old_x)
                        rec.x_axis = a_xaxis
                merge_groups[a_key].extend(merge_groups[b_key])
                merged_group_keys.add(b_key)

    # Remove absorbed groups
    for gk in merged_group_keys:
        del merge_groups[gk]

    merged_indices: set[int] = set()
    merged_charts: list[ChartRecommendation] = []

    for (group_key, x_axis), indices in merge_groups.items():
        if len(indices) < 2:
            continue

        charts_to_merge = [recommendations[i] for i in indices]

        # Collect all y-axis column names — abort if there are collisions
        # (same metric name from different filters → keep separate)
        all_y_axes: list[str] = []
        seen_y: set[str] = set()
        has_collision = False
        for c in charts_to_merge:
            y_cols = c.y_axis if isinstance(c.y_axis, list) else ([c.y_axis] if c.y_axis else [])
            for y in y_cols:
                if y in seen_y:
                    has_collision = True
                    break
                seen_y.add(y)
                all_y_axes.append(y)
            if has_collision:
                break

        if has_collision or not all_y_axes:
            continue  # Don't merge — keep as separate charts

        merged_indices.update(indices)

        # Merge data rows by joining on x_axis value
        merged_data: dict[str, dict] = {}
        for c in charts_to_merge:
            for row in c.data:
                x_val = str(row.get(x_axis, ""))
                if x_val not in merged_data:
                    merged_data[x_val] = {x_axis: row.get(x_axis)}
                merged_data[x_val].update(row)

        # Pick chart type: bar for categorical merge, line for temporal merge
        result_type = ChartType.bar if group_key == "categorical" else ChartType.line

        # Combine titles
        titles = [c.title for c in charts_to_merge if c.title]
        combined_title = " vs ".join(titles) if titles else "Combined Chart"

        merged_charts.append(ChartRecommendation(
            chart_type=result_type,
            title=combined_title,
            x_axis=x_axis,
            y_axis=all_y_axes if len(all_y_axes) > 1 else all_y_axes[0],
            color_by=None,
            data=list(merged_data.values()),
            reasoning=(
                f"Merged {len(charts_to_merge)} related queries sharing "
                f"'{x_axis}' axis into a multi-series {result_type.value} chart."
            ),
        ))

    # Build final list: merged charts first, then unmerged originals
    result = list(merged_charts)
    for i, rec in enumerate(recommendations):
        if i not in merged_indices:
            result.append(rec)

    return result


def recommend_charts(results: list[SubQueryResult]) -> list[ChartRecommendation]:
    """Return chart recommendations for every sub-query result that contains data."""

    recommendations: list[ChartRecommendation] = []
    for result in results:
        if result.error is not None:
            continue
        if not result.data:
            continue
        recommendations.append(recommend_chart(result))

    # Merge compatible charts (e.g., two bar charts sharing the same
    # x-axis → single multi-bar chart with multiple series)
    recommendations = _merge_compatible_charts(recommendations)

    return recommendations
