from __future__ import annotations

import asyncio

from app.config import settings
from app.schemas.insight import (
    InsightSummary,
    KeyFinding,
    QueryPlan,
    SubQuery,
    SubQueryResult,
)


class MockLLMService:
    """Mock LLM service that returns keyword-matched canned responses."""

    # ------------------------------------------------------------------ #
    #  decompose_question
    # ------------------------------------------------------------------ #
    async def decompose_question(
        self, question: str, schema_context: str
    ) -> QueryPlan:
        await asyncio.sleep(settings.mock_llm_delay_ms / 1000)

        q = question.lower()

        if "revenue" in q or "sales" in q:
            return self._revenue_plan()
        if "customer" in q or "user" in q:
            return self._customer_plan()
        if "trend" in q or "growth" in q or "over time" in q:
            return self._trend_plan()
        return self._default_plan()

    # ------------------------------------------------------------------ #
    #  consolidate_results
    # ------------------------------------------------------------------ #
    async def consolidate_results(
        self, question: str, sub_results: list[SubQueryResult]
    ) -> InsightSummary:
        await asyncio.sleep(settings.mock_llm_delay_ms / 1000)

        q = question.lower()

        if "revenue" in q or "sales" in q:
            return self._revenue_summary()
        if "customer" in q or "user" in q:
            return self._customer_summary()
        if "trend" in q or "growth" in q or "over time" in q:
            return self._trend_summary()
        return self._default_summary()

    # ================================================================== #
    #  Revenue scenario
    # ================================================================== #
    @staticmethod
    def _revenue_plan() -> QueryPlan:
        return QueryPlan(
            reasoning=(
                "To analyze revenue, I need to break down revenue by product "
                "category and then look at the monthly revenue trend to "
                "identify patterns."
            ),
            sub_queries=[
                SubQuery(
                    index=0,
                    description="Revenue by product category",
                    sql=(
                        "SELECT category, SUM(amount) as revenue "
                        "FROM sales "
                        "GROUP BY category "
                        "ORDER BY revenue DESC"
                    ),
                    depends_on=[],
                ),
                SubQuery(
                    index=1,
                    description="Monthly revenue trend",
                    sql=(
                        "SELECT DATE_TRUNC('month', sale_date) as month, "
                        "SUM(amount) as revenue "
                        "FROM sales "
                        "GROUP BY month "
                        "ORDER BY month"
                    ),
                    depends_on=[],
                ),
            ],
        )

    @staticmethod
    def _revenue_summary() -> InsightSummary:
        return InsightSummary(
            title="Revenue Analysis",
            narrative=(
                "Electronics leads all product categories with **$2.4M** in total "
                "revenue, accounting for 34% of overall sales. Clothing follows "
                "at **$1.8M** (25%), while Home & Garden rounds out the top three at "
                "$1.2M (16%). Monthly revenue shows a consistent upward trend "
                "with a notable **18% spike in November** driven by seasonal "
                "promotions. The total annual revenue reached **$10.2M** across "
                "all categories."
            ),
            key_findings=[
                KeyFinding(
                    headline="Electronics is the top revenue category",
                    detail="Electronics generated $2.4M, representing 34% of total revenue",
                    significance="high",
                ),
                KeyFinding(
                    headline="Top 3 categories dominate revenue",
                    detail="Electronics, Clothing, and Home & Garden account for 75% of total revenue",
                    significance="high",
                ),
                KeyFinding(
                    headline="Strong seasonal growth in Q4",
                    detail="Monthly revenue grew 12% on average, with an 18% spike in November",
                    significance="medium",
                ),
            ],
            follow_up_questions=[
                "What's the profit margin by category?",
                "Which region has the highest sales?",
                "How do sales compare to the same period last year?",
            ],
        )

    # ================================================================== #
    #  Customer scenario
    # ================================================================== #
    @staticmethod
    def _customer_plan() -> QueryPlan:
        return QueryPlan(
            reasoning=(
                "To understand the customer base, I need to segment customers "
                "and look at their distribution and value, then track "
                "acquisition trends over time."
            ),
            sub_queries=[
                SubQuery(
                    index=0,
                    description="Customer distribution by segment",
                    sql=(
                        "SELECT segment, COUNT(*) as count, "
                        "ROUND(AVG(total_spend), 2) as avg_value "
                        "FROM customers "
                        "GROUP BY segment "
                        "ORDER BY count DESC"
                    ),
                    depends_on=[],
                ),
                SubQuery(
                    index=1,
                    description="Customer acquisition over time",
                    sql=(
                        "SELECT DATE_TRUNC('month', signup_date) as month, "
                        "COUNT(*) as new_customers "
                        "FROM customers "
                        "GROUP BY month "
                        "ORDER BY month"
                    ),
                    depends_on=[],
                ),
            ],
        )

    @staticmethod
    def _customer_summary() -> InsightSummary:
        return InsightSummary(
            title="Customer Segment Analysis",
            narrative=(
                "The customer base is composed of four primary segments. "
                "**Individual** customers represent the largest group at 2,500 accounts "
                "but with the lowest average value ($250). **Enterprise** customers, "
                "while only 450 accounts (9%), contribute the highest value at "
                "$12,000 average spend. **SMB** customers form the sweet spot with "
                "1,200 accounts and $3,500 average value. Monthly customer "
                "acquisition shows a **steady upward trend**, growing from 120 to "
                "310 new customers per month over the year."
            ),
            key_findings=[
                KeyFinding(
                    headline="Enterprise customers are highest value",
                    detail="450 Enterprise accounts average $12,000 in spend, driving 45% of revenue",
                    significance="high",
                ),
                KeyFinding(
                    headline="Individual is the largest segment",
                    detail="2,500 Individual accounts but low $250 average value",
                    significance="medium",
                ),
                KeyFinding(
                    headline="Strong acquisition growth in 2024",
                    detail="Monthly new customer sign-ups grew from 120 to 310, a 158% increase",
                    significance="high",
                ),
            ],
            follow_up_questions=[
                "What's the customer retention rate by segment?",
                "Which segment has the highest lifetime value?",
                "How does acquisition cost vary by segment?",
            ],
        )

    # ================================================================== #
    #  Trend / Growth scenario
    # ================================================================== #
    @staticmethod
    def _trend_plan() -> QueryPlan:
        return QueryPlan(
            reasoning=(
                "To analyze growth trends, I need to track key metrics over "
                "time periods and then calculate period-over-period growth rates."
            ),
            sub_queries=[
                SubQuery(
                    index=0,
                    description="Revenue and orders by quarter",
                    sql=(
                        "SELECT DATE_TRUNC('quarter', sale_date) as quarter, "
                        "SUM(amount) as revenue, "
                        "COUNT(*) as orders "
                        "FROM sales "
                        "GROUP BY quarter "
                        "ORDER BY quarter"
                    ),
                    depends_on=[],
                ),
                SubQuery(
                    index=1,
                    description="Year-over-year growth rates",
                    sql=(
                        "SELECT period, "
                        "ROUND((curr_rev - prev_rev) / prev_rev * 100, 1) as revenue_growth, "
                        "ROUND((curr_orders - prev_orders) / prev_orders * 100, 1) as order_growth "
                        "FROM quarterly_comparison"
                    ),
                    depends_on=[0],
                ),
            ],
        )

    @staticmethod
    def _trend_summary() -> InsightSummary:
        return InsightSummary(
            title="Growth Trend Analysis",
            narrative=(
                "Revenue and order volume show a **strong upward trajectory** over "
                "the past 8 quarters. Revenue grew from **$2.1M in Q1 2023** to "
                "**$4.2M in Q4 2024**, representing a 100% increase. The average "
                "quarter-over-quarter growth rate is approximately **9%**. "
                "Year-over-year comparisons show consistent growth of **45-48%**, "
                "with order growth slightly outpacing revenue growth in Q3 2024 "
                "(49% vs 46.2%), suggesting a shift toward higher volume."
            ),
            key_findings=[
                KeyFinding(
                    headline="Revenue doubled in two years",
                    detail="From $2.1M (Q1 2023) to $4.2M (Q4 2024), a 100% increase",
                    significance="high",
                ),
                KeyFinding(
                    headline="Consistent YoY growth of 45-48%",
                    detail="All quarters show strong year-over-year growth, indicating sustainable momentum",
                    significance="high",
                ),
                KeyFinding(
                    headline="Order volume growing faster than revenue",
                    detail="Q3 2024 shows 49% order growth vs 46.2% revenue growth, suggesting volume shift",
                    significance="medium",
                ),
            ],
            follow_up_questions=[
                "What's driving the growth — new customers or existing?",
                "How does growth compare across product categories?",
                "What's the revenue forecast for the next quarter?",
            ],
        )

    # ================================================================== #
    #  Default / fallback scenario
    # ================================================================== #
    @staticmethod
    def _default_plan() -> QueryPlan:
        return QueryPlan(
            reasoning=(
                "For a general overview, I'll pull the key business metrics "
                "to give a high-level snapshot."
            ),
            sub_queries=[
                SubQuery(
                    index=0,
                    description="Key business metrics overview",
                    sql=(
                        "SELECT 'Total Revenue' as metric, SUM(amount) as value FROM sales "
                        "UNION ALL "
                        "SELECT 'Total Orders', COUNT(*) FROM sales "
                        "UNION ALL "
                        "SELECT 'Avg Order Value', ROUND(AVG(amount), 0) FROM sales"
                    ),
                    depends_on=[],
                ),
            ],
        )

    @staticmethod
    def _default_summary() -> InsightSummary:
        return InsightSummary(
            title="Business Overview",
            narrative=(
                "Here's a high-level snapshot of the business. **Total revenue** "
                "stands at **$7M** across **14,500 orders**, with an average "
                "order value of **$483**. These metrics provide a solid foundation "
                "for deeper analysis into specific areas."
            ),
            key_findings=[
                KeyFinding(
                    headline="$7M total revenue",
                    detail="Across all products, regions, and time periods",
                    significance="high",
                ),
                KeyFinding(
                    headline="14,500 total orders processed",
                    detail="Healthy order volume indicating strong customer demand",
                    significance="medium",
                ),
                KeyFinding(
                    headline="$483 average order value",
                    detail="Indicates a mid-to-high value product mix",
                    significance="medium",
                ),
            ],
            follow_up_questions=[
                "Show me revenue by product category",
                "What are the customer acquisition trends?",
                "How has growth trended over time?",
            ],
        )
