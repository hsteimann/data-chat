"""BigQuery schema context for Claude AI Data Chat.

Builds the schema context dynamically by reading the queryable layer through
the ``adp.data_context`` API and filtering it down to what physically exists
in the client's BigQuery dataset.

This module is Streamlit-free — used by both the Streamlit dashboard and the
MCP server.

Phase 1c (see ``docs/plan-data-context-api.md``):

- All catalog/registry access goes through ``adp.data_context`` — no direct
  ``yaml.safe_load`` on ``data_catalog.yaml`` and no ``RegistryService``.
- The previous ``_FALLBACK_SCHEMA_CONTEXT`` string has been removed: a
  missing catalog now raises (fail-loud, plan F6). If the catalog is gone,
  much more is broken than a chart, and a hardcoded fallback drifted silently.
- "Existing tables filtering" (which views the BQ dataset actually has) is
  kept here because it's BQ introspection, not metadata.
"""

from __future__ import annotations

import logging
from threading import Lock

from cachetools import TTLCache, cached
from google.cloud import bigquery

from adp.data_context import (
    JoinRelationship,
    QueryExample,
    ViewMetadata,
    get_ai_warnings,
    get_join_notes,
    get_join_relationships,
    get_kpis,
    get_query_examples,
    get_view_metadata,
    list_views,
)

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
# Formatting helpers
# ---------------------------------------------------------------------------


def _format_columns(view: ViewMetadata) -> str:
    lines = []
    for col in view.columns:
        desc = col.description or ""
        defn = col.definition or ""
        if desc and defn:
            suffix = f": {desc} — {defn}"
        elif desc:
            suffix = f": {desc}"
        elif defn:
            suffix = f": {defn}"
        else:
            suffix = ""
        bq_type = col.bq_type or ""
        type_part = f" ({bq_type})" if bq_type else ""
        lines.append(f"- {col.name}{type_part}{suffix}")
    return "\n".join(lines)


def _format_view(view: ViewMetadata) -> str:
    parts = []
    if view.is_raw_table:
        parts.append(f"### {view.name} (raw table — {view.description})")
    else:
        parts.append(f"### {view.name}")

    parts.append(view.description)
    if view.grain:
        parts.append(view.grain)
    if view.extra_context:
        parts.append(view.extra_context)

    if view.use_for:
        parts.append(f"Use this for: {view.use_for}")
    if view.typical_questions:
        questions = ", ".join(f'"{q}"' for q in view.typical_questions)
        parts.append(f"Typical questions: {questions}")

    if view.important:
        parts.append(f"**Important:** {view.important}")

    parts.append("Columns:")
    parts.append(_format_columns(view))

    return "\n".join(parts)


def _format_joins_filtered(
    relationships: list[JoinRelationship],
    notes: list[str],
    existing: frozenset[str],
) -> str:
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
    for rel in relationships:
        if rel.view_a in existing and rel.view_b in existing:
            keys = " + ".join(rel.keys)
            parts.append(f"| {rel.view_a} | {rel.view_b} | {keys} |")
            has_joins = True

    if not has_joins:
        return ""

    parts.append("")
    parts.append("Notes:")
    for note in notes:
        if any(t in note for t in existing):
            parts.append(f"- {note}")

    return "\n".join(parts)


def _format_examples_filtered(
    examples: list[QueryExample],
    catalog_view_names: frozenset[str],
    dataset: str,
    existing: frozenset[str],
) -> str:
    parts = ["## Query Patterns"]

    for ex in examples:
        sql = ex.sql.strip()
        skip = False
        for view_name in catalog_view_names:
            if view_name in sql and view_name not in existing:
                skip = True
                break
        if skip:
            continue

        sql = sql.replace("adp_client_07", dataset)
        parts.append(f"\n### {ex.name}")
        parts.append(f"```sql\n{sql}\n```")

    return "\n".join(parts)


def _format_warnings(warnings: list[str]) -> str:
    parts = ["## Important Notes"]
    for warning in warnings:
        parts.append(f"- {warning}")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# KPI section — cached, reads from data_context API
# ---------------------------------------------------------------------------


@cached(_kpi_cache, lock=_kpi_lock)
def _build_kpi_section() -> str:
    """Format KPI definitions from the data_context API as a markdown block.

    Unfiltered (global catalog): the SQL generation prompt is per-client by
    way of the ``existing`` views filter, but KPI definitions themselves are
    universal — formulae and warnings don't change between clients.
    """
    kpis = get_kpis()
    if not kpis:
        return ""

    lines = [
        "## KPI Definitions",
        "Use these formulas when calculating or interpreting KPIs.",
        "For aggregated queries always recalculate ratio KPIs from summed components — never average them.",
        "",
    ]

    direction_label = {
        "lower_is_better": "lower is better",
        "higher_is_better": "higher is better",
    }

    for key, k in kpis.items():
        parts = [f"**{key.upper()}**"]
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
        logger.warning(
            "Failed to list tables for %s.%s", gcp_project, dataset, exc_info=True
        )
        return frozenset()


# ---------------------------------------------------------------------------
# Public entry point — used by SQL system prompt builder
# ---------------------------------------------------------------------------


def build_client_schema(gcp_project: str, dataset: str) -> str:
    """Build a schema context containing only views/tables that exist for this client.

    Fails loud (via the underlying ``data_context`` API) if ``data_catalog.yaml``
    is missing or unparseable — there is no silent fallback by design (plan F6).
    """
    existing = _discover_client_tables(gcp_project, dataset)

    catalog_view_names = frozenset(list_views())
    relevant = [name for name in catalog_view_names if name in existing]

    # If BQ introspection returned nothing (transient error, dataset
    # unreachable) fall back to the full catalog so the prompt is still
    # complete — better an over-broad schema than an empty one.
    if not relevant:
        logger.warning(
            "No catalog views found in %s, using full catalog", dataset
        )
        relevant = sorted(catalog_view_names)

    parts = [f"## Dataset: `{gcp_project}.{dataset}`", ""]

    parts.append("## Available Tables and Views")
    parts.append("")
    parts.append(
        "All views contain a `client_id` (STRING) column that identifies the client."
    )
    parts.append("")

    for name in relevant:
        parts.append(_format_view(get_view_metadata(name)))
        parts.append("")

    parts.append(
        _format_joins_filtered(
            get_join_relationships(),
            get_join_notes(),
            existing,
        )
    )
    parts.append("")

    parts.append(
        _format_examples_filtered(
            get_query_examples(), catalog_view_names, dataset, existing
        )
    )
    parts.append("")

    parts.append(_format_warnings(get_ai_warnings()))

    kpi_section = _build_kpi_section()
    if kpi_section:
        parts.append("")
        parts.append(kpi_section)

    return "\n".join(parts)
