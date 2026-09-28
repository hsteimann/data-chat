# Plan: Client-Specific Dynamic Chat Schema

**Priority:** Medium
**Status:** Ready to implement
**Replaces:** Hardcoded `SCHEMA_CONTEXT` in `chat_schema.py`
**Backlog ref:** Data Chat Schema Drift (long-term fix)

## Problem

Data Chat sends a schema description to Claude for SQL generation. Today this schema is built from `data_catalog.yaml` and includes **all** views and tables — regardless of which client is selected. This causes two problems:

1. **Drift** — Every new client, view, or PMA source requires a manual catalog update. We've already had schema drift once (bug `77a8877`).
2. **Noise** — Claude sees tables the selected client doesn't have (e.g., PMA tables for ads-only clients, Rainforest tables for clients without collections). This wastes context and risks generating SQL against non-existent tables.

## Solution

Generate the schema context **per-client at query time**. When the user selects a client, build a schema that contains only the views and tables that actually exist in that client's BQ dataset.

## Design

### Core idea

```
User selects client → check which BQ tables/views exist → 
filter catalog to matching entries → build schema string → pass to Claude
```

### Data flow

```
data_catalog.yaml          (static: view definitions, columns, JOINs, warnings)
        +
BQ table discovery         (dynamic: which tables/views exist for this client)
        ↓
build_client_schema()      (filter catalog to client's actual tables)
        ↓
SQL_GENERATION_PROMPT      (client-specific schema, single dataset)
```

### What stays in `data_catalog.yaml`

The catalog remains the **source of truth** for view metadata — descriptions, column definitions, grain, usage hints, typical questions, JOIN relationships, AI warnings. This is hand-curated domain knowledge that can't be auto-generated.

### What becomes dynamic

- **Which views/tables appear in the schema** — determined by checking BQ at runtime
- **Dataset reference** — always the selected client's dataset, no list of all datasets
- **JOIN relationships** — filtered to only include pairs where both tables exist for the client
- **Query examples** — rewritten to use the selected client's dataset name

## Implementation

### Step 1: Add `build_client_schema(dataset: str)` function

New function in `chat_schema.py` that replaces the current `build_schema_context(datasets)`:

```python
@st.cache_data(ttl=300)
def _discover_client_tables(dataset: str) -> set[str]:
    """Check which catalog tables/views actually exist in this BQ dataset."""
    bq = get_bq_client()
    try:
        return {t.table_id for t in bq.list_tables(f"{GCP_PROJECT}.{dataset}")}
    except Exception:
        return set()


def build_client_schema(dataset: str) -> str:
    """Build a schema context containing only views/tables that exist for this client."""
    catalog = load_data_catalog()
    existing = _discover_client_tables(dataset)
    
    # Filter views to those that exist in this dataset
    client_views = {
        name: defn for name, defn in catalog["views"].items()
        if name in existing
    }
    
    # Filter JOINs to pairs where both sides exist
    client_joins = [
        j for j in catalog.get("join_relationships", [])
        if j["view_a"] in existing and j["view_b"] in existing
    ]
    
    # Build the schema markdown (same format as today, just filtered)
    ...
```

### Step 2: Update `generate_sql()` call site

In `data_chat.py`, change:

```python
# Before (passes all datasets)
schema = build_schema_context(all_datasets or [dataset])

# After (passes only selected client's dataset)
schema = build_client_schema(dataset)
```

The `all_datasets` parameter is no longer needed — schema is always scoped to one client.

### Step 3: Simplify `SQL_GENERATION_PROMPT`

The prompt no longer needs to explain multiple datasets or cross-dataset querying. Simplify to:

```
You are querying BigQuery dataset `example-gcp-project.{dataset}`.

{schema}

Generate a SQL query to answer: {question}
Date range: {start_date} to {end_date}
```

Rules about UNION ALL across datasets can be removed since we're always in a single dataset context.

### Step 4: Filter query examples

Rewrite the `query_examples` section to use `{dataset}` placeholder instead of hardcoded `adp_client_07`. Only include examples that reference tables the client has. Skip the Rainforest JOIN example for ads-only clients.

### Step 5: Cache the discovery result

`_discover_client_tables()` is cached with `@st.cache_data(ttl=300)` — same pattern as other BQ lookups. This means one `list_tables` call per client per 5 minutes, not per question.

## Files to change

| File | Change |
|------|--------|
| `dashboard/chat_schema.py` | Replace `build_schema_context()` with `build_client_schema()`, add `_discover_client_tables()` |
| `dashboard/pages/data_chat.py` | Call `build_client_schema(dataset)` instead of `build_schema_context(all_datasets)` |

## What does NOT change

- `data_catalog.yaml` — stays as-is, still the source of truth for view metadata
- `SQL_GENERATION_PROMPT` rules — most stay (SAFE_DIVIDE, LIMIT, date format, etc.)
- `INTERPRETATION_PROMPT` — unrelated to schema
- `chat_utils.py` — validation, Anthropic client unchanged
- SQL views themselves — no changes

## Example: what Claude sees

### Ads-only client (e.g., client_06)

```
Dataset: example-gcp-project.adp_client_06

Available tables:
- v_ads_summary_daily — Client-level daily totals...
- v_ads_campaign_daily — Campaign-level daily metrics...
- v_ads_adgroup_daily — Ad group-level daily metrics...
- v_ads_asin_daily — ASIN-level performance per campaign...
- v_ads_searchterm_daily — Search term performance...

[columns for each]
[JOIN relationships between ads views only]
[query examples using adp_client_06]
[AI warnings]
```

### Client with Ads + Rainforest + PMA (e.g., client_01)

```
Dataset: example-gcp-project.adp_client_01

Available tables:
- v_ads_summary_daily — ...
- v_ads_campaign_daily — ...
- v_ads_adgroup_daily — ...
- v_ads_asin_daily — ...
- v_ads_searchterm_daily — ...
- rf_products — Daily product snapshot (Buy Box, pricing, reviews)...
- pma_sales_traffic_by_date — Seller Central daily totals...
- pma_sales_traffic_by_asin — Per-ASIN sales and traffic...
- pma_orders — Order line items...
- pma_inventory — Merchant fulfilled inventory...
- pma_inventory_fba — FBA inventory levels...

[columns for each]
[all JOIN relationships including cross-source]
[query examples including Rainforest and PMA joins]
[AI warnings including PMA-specific rules]
```

## Verification

1. Select an ads-only client (client_06) → ask about Rainforest data → Claude should say it's not available (not generate broken SQL)
2. Select client_01 → ask about inventory → Claude should query `pma_inventory_fba`
3. Add a new PMA table for a client → it should appear in schema on next question without any code change (just needs to be in `data_catalog.yaml`)
4. Schema drift is now limited to catalog ↔ reality for *column definitions* only, not for which tables exist

## Future enhancements (not in scope)

- **Auto-discover columns from BQ `INFORMATION_SCHEMA`** — would eliminate even column-level drift, but adds a BQ query per table. Consider if catalog maintenance becomes burdensome.
- **Per-client query examples** — generate examples using the client's actual campaign/ASIN names from recent data. Nice but complex.
- **Conversation memory** — pass previous Q&A pairs so Claude can refine queries. Separate feature.
