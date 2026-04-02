"""BigQuery schema context for Claude AI chat integration.

Builds the schema context dynamically from config/views_registry.yaml
instead of hardcoding it. Falls back to a static string if the YAML
is not available (e.g., during migration).
"""

import logging
from pathlib import Path

import yaml

from adp.config import _resolve_config_dir

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Load views registry from config
# ---------------------------------------------------------------------------


def _load_views_registry() -> dict | None:
    """Load views_registry.yaml from the resolved config directory."""
    try:
        config_dir = _resolve_config_dir()
    except FileNotFoundError:
        return None
    path = config_dir / "views_registry.yaml"
    if not path.exists():
        return None
    with open(path) as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Build schema context from registry
# ---------------------------------------------------------------------------


def _format_columns(columns: list[dict]) -> str:
    """Format a column list into the markdown format Claude expects."""
    lines = []
    for col in columns:
        desc = col.get("description", "")
        suffix = f": {desc}" if desc else ""
        lines.append(f"- {col['name']} ({col['type']}){suffix}")
    return "\n".join(lines)


def _format_view(name: str, view: dict) -> str:
    """Format a single view/table definition."""
    parts = []

    # Header
    if view.get("is_raw_table"):
        parts.append(f"### {name} (raw table — {view['description']})")
    else:
        parts.append(f"### {name}")

    # Description and grain
    parts.append(view["description"])
    if view.get("grain"):
        parts.append(view["grain"])
    if view.get("extra_context"):
        parts.append(view["extra_context"])

    # Usage hints
    if view.get("use_for"):
        parts.append(f"Use this for: {view['use_for']}")
    if view.get("typical_questions"):
        questions = ", ".join(f'"{q}"' for q in view["typical_questions"])
        parts.append(f"Typical questions: {questions}")

    # Important notes (e.g., deduplication for raw tables)
    if view.get("important"):
        parts.append(f"**Important:** {view['important']}")

    # Columns
    parts.append("Columns:")
    parts.append(_format_columns(view["columns"]))

    return "\n".join(parts)


def _format_joins(registry: dict) -> str:
    """Format JOIN relationships section."""
    parts = [
        "## View Relationships (for JOINs)",
        "",
        "The views share common columns that can be used as JOIN keys.",
        "Always include `date` in JOIN conditions to keep the join at the daily grain.",
        "",
        "| View A | View B | JOIN keys |",
        "|--------|--------|-----------|",
    ]

    for rel in registry.get("join_relationships", []):
        keys = " + ".join(rel["keys"])
        parts.append(f"| {rel['view_a']} | {rel['view_b']} | {keys} |")

    parts.append("")
    parts.append("Notes:")
    for note in registry.get("join_notes", []):
        parts.append(f"- {note}")

    return "\n".join(parts)


def _format_examples(registry: dict) -> str:
    """Format query examples section."""
    parts = ["## Query Patterns"]

    for ex in registry.get("query_examples", []):
        parts.append(f"\n### {ex['name']}")
        parts.append(f"```sql\n{ex['sql'].strip()}\n```")

    return "\n".join(parts)


def _format_warnings(registry: dict) -> str:
    """Format AI warnings section."""
    parts = ["## Important Notes"]
    for warning in registry.get("ai_warnings", []):
        parts.append(f"- {warning}")
    return "\n".join(parts)


def build_schema_context(datasets: list[str]) -> str:
    """Build the schema context string from views_registry.yaml.

    Parameters
    ----------
    datasets:
        List of client dataset names (e.g., ["adp_client_07", "adp_client_01"]).
    """
    registry = _load_views_registry()
    if registry is None:
        logger.warning("views_registry.yaml not found, using fallback")
        return _FALLBACK_SCHEMA_CONTEXT

    parts = []

    # Datasets section
    parts.append("## Available Datasets")
    parts.append("Each client has their own dataset prefixed with `adp_`:")
    for ds in sorted(datasets):
        parts.append(f"- {ds}")
    parts.append("")

    # Views section
    parts.append("## Views (recommended - deduplicated with pre-calculated KPIs)")
    parts.append("")
    parts.append("All views contain a `client_id` (STRING) column that identifies the client.")
    parts.append("")

    for name, view in registry.get("views", {}).items():
        parts.append(_format_view(name, view))
        parts.append("")

    # JOINs
    parts.append(_format_joins(registry))
    parts.append("")

    # Examples
    parts.append(_format_examples(registry))
    parts.append("")

    # Warnings
    parts.append(_format_warnings(registry))

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Prompt templates (these are prompt engineering logic, not data)
# ---------------------------------------------------------------------------

SQL_GENERATION_PROMPT = """You are a SQL expert for Amazon advertising data stored in BigQuery.
Given a user question, generate a SQL query to answer it.

{schema}

## Rules
1. Use fully qualified table names: `example-gcp-project.{{dataset}}.{{view}}`
2. Always include LIMIT (maximum 1000 rows)
3. Use the views (v_ads_*) for ads data. The only raw table you may query directly is `rf_products` (for product names, brands, etc.)
4. For date ranges, use BETWEEN with 'YYYY-MM-DD' format
5. Use SAFE_DIVIDE for any division operations
6. Return ONLY the SQL query, no explanations or markdown code blocks
7. For aggregations, use appropriate GROUP BY clauses
8. Round numeric results to 2 decimal places where appropriate
9. UNION ALL requires all SELECT statements to have identical columns. NEVER combine different views in a UNION ALL. Only UNION ALL the same view across different datasets.
10. All views have a `client_id` column. Prefer using it for cross-client queries within a single view instead of UNION ALL across datasets.
11. For search term analysis or keyword questions, use `v_ads_searchterm_daily`.
12. JOINs across views are allowed and encouraged when the question requires data from multiple views. Always JOIN on `date` plus the appropriate key column (see View Relationships table). Use table aliases (e.g., `c` for campaign, `a` for ASIN, `s` for searchterm). Be careful: v_ads_asin_daily has campaign_name but NOT campaign_id.

## Current Context
- Selected client dataset: {dataset}
- Date range: {start_date} to {end_date}

User question: {question}
"""

INTERPRETATION_PROMPT = """You analyzed Amazon advertising data. Here are the query results:

{results}

Row count: {row_count}

Please provide:
1. A concise, actionable answer to the user's question (2-4 sentences max)
2. If a visualization would help understand the data, suggest ONE chart as JSON on its own line:
   {{"chart_type": "bar|line|scatter|pie", "x": "column_name", "y": "column_name", "color": "column_name_optional"}}

Keep the response brief and focused on insights. Use bullet points for multiple findings.
Do not repeat the raw data - the table is already displayed.
"""


# ---------------------------------------------------------------------------
# Fallback: used only if views_registry.yaml is not found
# ---------------------------------------------------------------------------

_FALLBACK_SCHEMA_CONTEXT = """
## Available Datasets
Each client has their own dataset prefixed with `adp_`.
Check the client selector for available datasets.

## Views (recommended - deduplicated with pre-calculated KPIs)

All views contain a `client_id` (STRING) column that identifies the client.

### v_ads_summary_daily
Client-level daily totals. Columns: date, active_campaigns, impressions, clicks, cost, purchases, sales, units_sold, acos, roas, ctr, cpc, cvr, client_id

### v_ads_campaign_daily
Campaign-level daily metrics. Columns: date, campaign_id, campaign_name, campaign_status, budget, currency, impressions, clicks, cost, purchases, sales, units_sold, acos, roas, ctr, cpc, cvr, client_id

### v_ads_adgroup_daily
Ad group daily metrics. Columns: date, adgroup_id, adgroup_name, impressions, clicks, cost, purchases, sales, units_sold, acos, roas, ctr, cpc, cvr, client_id

### v_ads_asin_daily
ASIN daily metrics. Columns: date, asin, sku, campaign_name, impressions, clicks, cost, purchases, sales, units_sold, acos, roas, ctr, cpc, cvr, client_id

### v_ads_searchterm_daily
Search term daily metrics. Columns: date, search_term, keyword, keyword_id, keyword_type, match_type, campaign_name, campaign_id, ad_group_name, ad_group_id, impressions, clicks, cost, purchases, sales, units_sold, acos, roas, ctr, cpc, cvr, client_id

## Important Notes
- Use SAFE_DIVIDE for divisions
- Always include LIMIT
- Date format: YYYY-MM-DD
"""
