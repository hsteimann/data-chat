"""BigQuery schema context for Claude AI chat integration.

Builds the schema context dynamically from config/data_catalog.yaml,
filtered to only the tables/views that exist for the selected client.
Falls back to a static string if the YAML is not available.
"""

import logging
from pathlib import Path

import streamlit as st
import yaml

from adp.config import _resolve_config_dir

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Load data catalog from config
# ---------------------------------------------------------------------------


def load_data_catalog() -> dict | None:
    """Load data_catalog.yaml from the resolved config directory."""
    try:
        config_dir = _resolve_config_dir()
    except FileNotFoundError:
        return None
    path = config_dir / "data_catalog.yaml"
    if not path.exists():
        return None
    with open(path) as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Build schema context from data catalog
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


def _format_joins_filtered(catalog: dict, existing: frozenset[str]) -> str:
    """Format JOIN relationships, filtered to tables that exist for this client."""
    parts = [
        "## View Relationships (for JOINs)",
        "",
        "The views share common columns that can be used as JOIN keys.",
        "Always include `date` in JOIN conditions to keep the join at the daily grain.",
        "",
        "| View A | View B | JOIN keys |",
        "|--------|--------|-----------|",
    ]

    has_joins = False
    for rel in catalog.get("join_relationships", []):
        if rel["view_a"] in existing and rel["view_b"] in existing:
            keys = " + ".join(rel["keys"])
            parts.append(f"| {rel['view_a']} | {rel['view_b']} | {keys} |")
            has_joins = True

    if not has_joins:
        return ""

    parts.append("")
    parts.append("Notes:")
    for note in catalog.get("join_notes", []):
        # Only include notes that reference tables the client has
        # Check if any existing table name appears in the note
        if any(t in note for t in existing):
            parts.append(f"- {note}")

    return "\n".join(parts)


def _format_examples_filtered(catalog: dict, dataset: str, existing: frozenset[str]) -> str:
    """Format query examples, rewritten for this client's dataset."""
    parts = ["## Query Patterns"]

    for ex in catalog.get("query_examples", []):
        sql = ex["sql"].strip()
        # Check if all tables referenced in the example exist for this client
        # Skip examples that reference tables the client doesn't have
        skip = False
        for view_name in catalog.get("views", {}):
            if view_name in sql and view_name not in existing:
                skip = True
                break
        if skip:
            continue

        # Rewrite dataset references to use the selected client's dataset
        sql = sql.replace("adp_client_07", dataset)
        parts.append(f"\n### {ex['name']}")
        parts.append(f"```sql\n{sql}\n```")

    return "\n".join(parts)


def _format_warnings(catalog: dict) -> str:
    """Format AI warnings section."""
    parts = ["## Important Notes"]
    for warning in catalog.get("ai_warnings", []):
        parts.append(f"- {warning}")
    return "\n".join(parts)


@st.cache_data(ttl=300)
def _discover_client_tables(gcp_project: str, dataset: str) -> frozenset[str]:
    """Check which catalog tables/views actually exist in this BQ dataset."""
    from sidebar import get_bq_client
    bq = get_bq_client()
    try:
        return frozenset(t.table_id for t in bq.list_tables(f"{gcp_project}.{dataset}"))
    except Exception:
        return frozenset()


def build_client_schema(gcp_project: str, dataset: str) -> str:
    """Build a schema context containing only views/tables that exist for this client.

    Parameters
    ----------
    gcp_project:
        GCP project ID (e.g., "example-gcp-project").
    dataset:
        Client dataset name (e.g., "adp_client_07").
    """
    catalog = load_data_catalog()
    if catalog is None:
        logger.warning("data_catalog.yaml not found, using fallback")
        return _FALLBACK_SCHEMA_CONTEXT

    existing = _discover_client_tables(gcp_project, dataset)

    # Filter views to those that exist in this dataset
    client_views = {
        name: view for name, view in catalog.get("views", {}).items()
        if name in existing
    }

    if not client_views:
        logger.warning("No catalog views found in %s, using full catalog", dataset)
        client_views = catalog.get("views", {})

    parts = []

    # Dataset section (single client)
    parts.append(f"## Dataset: `{gcp_project}.{dataset}`")
    parts.append("")

    # Views section — only those that exist
    parts.append("## Available Tables and Views")
    parts.append("")
    parts.append("All views contain a `client_id` (STRING) column that identifies the client.")
    parts.append("")

    for name, view in client_views.items():
        parts.append(_format_view(name, view))
        parts.append("")

    # JOINs — only where both sides exist
    parts.append(_format_joins_filtered(catalog, existing))
    parts.append("")

    # Examples — rewritten for this dataset
    parts.append(_format_examples_filtered(catalog, dataset, existing))
    parts.append("")

    # Warnings
    parts.append(_format_warnings(catalog))

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Prompt templates (these are prompt engineering logic, not data)
# ---------------------------------------------------------------------------

SQL_GENERATION_PROMPT = """You are a SQL expert for Amazon data stored in BigQuery.
Given a user question, generate a SQL query to answer it.

You are querying dataset `{dataset}`. Only the tables listed below exist for this client.

{schema}

## Rules
1. Use fully qualified table names: `example-gcp-project.{dataset}.{{table}}`
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

## Current Context
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
# Fallback: used only if data_catalog.yaml is not found
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
