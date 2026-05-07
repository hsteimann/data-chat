"""Prompt templates for the Data Chat pipeline.

Split intentionally:
- System prompts (stable across turns) → cacheable via Anthropic prompt caching
- User-message templates (per-turn) → not cached

Used by both the Streamlit dashboard and the MCP server.
"""

from __future__ import annotations

from adp.services.data_chat_schema import build_client_schema


# ---------------------------------------------------------------------------
# SQL generation — system prompt is the cacheable block
# ---------------------------------------------------------------------------


def build_sql_system_prompt(gcp_project: str, dataset: str) -> str:
    """Build the cacheable system prompt for SQL generation.

    Contains the schema context and rules — everything stable across turns.
    Returned as a plain string; the caller wraps it in a cache_control block
    when calling the Anthropic API.
    """
    schema = build_client_schema(gcp_project, dataset)
    return f"""You are a SQL expert for Amazon data stored in BigQuery.
Given a user question, generate a SQL query to answer it.

You are querying dataset `{gcp_project}.{dataset}`. Only the tables listed below exist for this client.

{schema}

## Rules
1. Use fully qualified table names: `{gcp_project}.{dataset}.{{table}}`
2. Always include LIMIT (maximum 1000 rows)
3. Prefer views (v_ads_*) over raw tables for ads data
4. For date ranges, use BETWEEN with 'YYYY-MM-DD' format
5. Use SAFE_DIVIDE for any division operations
6. Return ONLY the SQL query, no explanations or markdown code blocks
7. For aggregations, use appropriate GROUP BY clauses
8. Round numeric results to 2 decimal places where appropriate
9. NEVER combine different tables/views in a UNION ALL — they have different columns
10. For search term analysis or keyword questions, use `v_ads_searchterm_daily`
11. JOINs across tables are allowed when the question requires it. Always JOIN on `date` plus the appropriate key column (see View Relationships). Use table aliases.
12. If the user asks about data that is not available in the listed tables, say so instead of guessing.
13. This is a multi-turn conversation. Use previous questions and SQL to understand follow-up requests."""


SQL_USER_TEMPLATE = "Date range: {start_date} to {end_date}\n\nQuestion: {question}"


# ---------------------------------------------------------------------------
# Result interpretation
# ---------------------------------------------------------------------------


INTERPRETATION_SYSTEM_PROMPT = """You are an Amazon advertising analyst. The user asked a question, a SQL query was run, and you received the results.

Provide:
1. A concise, actionable answer (2-4 sentences max)
2. If a visualization would help, suggest ONE chart as JSON on its own line:
   {"chart_type": "bar|line|scatter|pie", "x": "column_name", "y": "column_name", "color": "column_name_optional"}

Keep the response brief and focused on insights. Use bullet points for multiple findings.
Do not repeat the raw data — the table is already displayed to the user."""


INTERPRETATION_USER_TEMPLATE = """Question: {question}

Query results ({row_count} rows):
{results}"""


# ---------------------------------------------------------------------------
# Legacy templates kept for any external callers
# ---------------------------------------------------------------------------

SQL_GENERATION_PROMPT = (
    "You are a SQL expert for Amazon data stored in BigQuery.\n"
    "Given a user question, generate a SQL query to answer it.\n\n"
    "You are querying dataset `{dataset}`.\n\n{schema}\n\n"
    "Date range: {start_date} to {end_date}\n\nUser question: {question}"
)
INTERPRETATION_PROMPT = INTERPRETATION_USER_TEMPLATE
