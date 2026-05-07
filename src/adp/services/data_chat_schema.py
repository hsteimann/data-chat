"""BigQuery schema context for Claude AI Data Chat.

Builds the schema context dynamically from config/data_catalog.yaml,
filtered to the tables/views that actually exist for the selected client.
Falls back to a static string if the YAML is not available.

This module is Streamlit-free — used by both the Streamlit dashboard
and the MCP server.
"""

from __future__ import annotations

import logging
from threading import Lock

from cachetools import TTLCache, cached
from google.cloud import bigquery

from adp.config import _resolve_config_dir
from adp.services.registry import RegistryService

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Caches — TTL = 5 min, mirrors dashboard behavior. Required because the
# MCP server runs long-lived (min_instances=1) and would otherwise serve a
# stale schema after new views/tables get deployed.
# ---------------------------------------------------------------------------

_tables_cache: TTLCache = TTLCache(maxsize=32, ttl=300)
_kpi_cache: TTLCache = TTLCache(maxsize=1, ttl=300)
_tables_lock = Lock()
_kpi_lock = Lock()


# ---------------------------------------------------------------------------
# Catalog loading
# ---------------------------------------------------------------------------


def load_data_catalog() -> dict | None:
    """Load data_catalog.yaml from the resolved config directory."""
    import yaml

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
# Formatting helpers
# ---------------------------------------------------------------------------


def _format_columns(columns: list[dict]) -> str:
    lines = []
    for col in columns:
        desc = col.get("description", "")
        defn = col.get("definition", "")
        if desc and defn:
            suffix = f": {desc} — {defn}"
        elif desc:
            suffix = f": {desc}"
        elif defn:
            suffix = f": {defn}"
        else:
            suffix = ""
        lines.append(f"- {col['name']} ({col['type']}){suffix}")
    return "\n".join(lines)


def _format_view(name: str, view: dict) -> str:
    parts = []
    if view.get("is_raw_table"):
        parts.append(f"### {name} (raw table — {view['description']})")
    else:
        parts.append(f"### {name}")

    parts.append(view["description"])
    if view.get("grain"):
        parts.append(view["grain"])
    if view.get("extra_context"):
        parts.append(view["extra_context"])

    if view.get("use_for"):
        parts.append(f"Use this for: {view['use_for']}")
    if view.get("typical_questions"):
        questions = ", ".join(f'"{q}"' for q in view["typical_questions"])
        parts.append(f"Typical questions: {questions}")

    if view.get("important"):
        parts.append(f"**Important:** {view['important']}")

    parts.append("Columns:")
    parts.append(_format_columns(view["columns"]))

    return "\n".join(parts)


def _format_joins_filtered(catalog: dict, existing: frozenset[str]) -> str:
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
        if any(t in note for t in existing):
            parts.append(f"- {note}")

    return "\n".join(parts)


def _format_examples_filtered(catalog: dict, dataset: str, existing: frozenset[str]) -> str:
    parts = ["## Query Patterns"]

    for ex in catalog.get("query_examples", []):
        sql = ex["sql"].strip()
        skip = False
        for view_name in catalog.get("views", {}):
            if view_name in sql and view_name not in existing:
                skip = True
                break
        if skip:
            continue

        sql = sql.replace("adp_client_07", dataset)
        parts.append(f"\n### {ex['name']}")
        parts.append(f"```sql\n{sql}\n```")

    return "\n".join(parts)


def _format_warnings(catalog: dict) -> str:
    parts = ["## Important Notes"]
    for warning in catalog.get("ai_warnings", []):
        parts.append(f"- {warning}")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# KPI section — cached, reads from registry
# ---------------------------------------------------------------------------


@cached(_kpi_cache, lock=_kpi_lock)
def _build_kpi_section() -> str:
    """Format KPI definitions from the registry as a markdown block."""
    try:
        reg = RegistryService(load_schemas=False)
    except Exception:
        return ""

    kpis = reg.registry.kpis
    if not kpis:
        return ""

    lines = [
        "## KPI Definitions",
        "Use these formulas when calculating or interpreting KPIs.",
        "For aggregated queries always recalculate ratio KPIs from summed components — never average them.",
        "",
    ]

    direction_label = {"lower_is_better": "lower is better", "higher_is_better": "higher is better"}

    for name, k in kpis.items():
        parts = [f"**{name.upper()}**"]
        parts.append(f"= {k.formula}")
        if k.unit:
            parts.append(f"[{k.unit}]")
        if k.direction:
            parts.append(f"— {direction_label.get(k.direction, k.direction)}")
        if k.typical_range:
            lo, hi = k.typical_range[0], k.typical_range[1]
            parts.append(f"(typical {lo}–{hi})")
        line = " ".join(parts)
        if k.interpretation:
            line += f". {k.interpretation[:120].rstrip()}"
        if k.warning:
            line += f" ⚠️ {k.warning[:120].rstrip()}"
        lines.append(f"- {line}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Table discovery — cached per (project, dataset)
# ---------------------------------------------------------------------------


@cached(_tables_cache, lock=_tables_lock)
def _discover_client_tables(gcp_project: str, dataset: str) -> frozenset[str]:
    """Return the table_ids that exist in this client's BQ dataset."""
    bq = bigquery.Client(project=gcp_project)
    try:
        return frozenset(t.table_id for t in bq.list_tables(f"{gcp_project}.{dataset}"))
    except Exception:
        logger.warning("Failed to list tables for %s.%s", gcp_project, dataset, exc_info=True)
        return frozenset()


# ---------------------------------------------------------------------------
# Public entry point — used by SQL system prompt builder
# ---------------------------------------------------------------------------


def build_client_schema(gcp_project: str, dataset: str) -> str:
    """Build a schema context containing only views/tables that exist for this client."""
    catalog = load_data_catalog()
    if catalog is None:
        logger.warning("data_catalog.yaml not found, using fallback")
        return _FALLBACK_SCHEMA_CONTEXT

    existing = _discover_client_tables(gcp_project, dataset)

    client_views = {
        name: view for name, view in catalog.get("views", {}).items()
        if name in existing
    }

    if not client_views:
        logger.warning("No catalog views found in %s, using full catalog", dataset)
        client_views = catalog.get("views", {})

    parts = []

    parts.append(f"## Dataset: `{gcp_project}.{dataset}`")
    parts.append("")

    parts.append("## Available Tables and Views")
    parts.append("")
    parts.append("All views contain a `client_id` (STRING) column that identifies the client.")
    parts.append("")

    for name, view in client_views.items():
        parts.append(_format_view(name, view))
        parts.append("")

    parts.append(_format_joins_filtered(catalog, existing))
    parts.append("")

    parts.append(_format_examples_filtered(catalog, dataset, existing))
    parts.append("")

    parts.append(_format_warnings(catalog))

    kpi_section = _build_kpi_section()
    if kpi_section:
        parts.append("")
        parts.append(kpi_section)

    return "\n".join(parts)


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
