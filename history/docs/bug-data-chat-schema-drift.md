# Bug: Data Chat Schema Drift

**Reported:** 2026-03-13
**Severity:** Medium
**Component:** `dashboard/chat_schema.py`

## Problem

The Data Chat feature sends a hardcoded schema description to Claude for SQL generation (`chat_schema.py`). This schema has drifted from the actual project state in several ways:

### 1. Stale client/dataset list

The `SCHEMA_CONTEXT` lists datasets that don't exist in `clients.yaml`:

```
Listed in schema but NOT in clients.yaml:
- adp_client_18
- adp_client_22
- adp_client_19
- adp_client_17
- adp_client_20
- adp_client_16
- adp_client_21

In clients.yaml but NOT in schema:
- adp_client_06
- adp_client_03
- adp_client_10
- adp_client_14
```

This causes Claude to generate queries against non-existent datasets or miss available ones.

### 2. Missing `v_ads_searchterm_daily` view

The search term view was added (commit `b5b6cd3`) but never added to the schema context. Claude has no awareness of this view and won't use it for search term questions.

### 3. Missing `client_id` column

All views include a `client_id` column but it's not documented in the schema. This means Claude can't generate cross-client queries within a single view (which would be more efficient than UNION ALL).

### 4. No guidance on UNION ALL compatibility

Claude attempted a `UNION ALL` between `v_ads_summary_daily` and `v_ads_campaign_daily`, which have different column schemas. The SQL generation prompt doesn't warn that UNION ALL requires matching columns, or which views are compatible.

## Observed Error

```
Error: 400 Unrecognized name: cost at [35:10]
```

Claude generated a UNION ALL between summary and campaign views. The summary view's column set doesn't match the campaign view's column set, causing the query to fail.

## Root Cause

`chat_schema.py` is a static file that must be manually updated when views or clients change. There is no mechanism to keep it in sync with:
- `clients.yaml` (client/dataset list)
- `sql/views/*.sql` (view definitions)
- `data_registry.yaml` (source metadata)

## Recommended Fix

### Short term
Update `chat_schema.py` to:
1. Sync the dataset list with `clients.yaml`
2. Add `v_ads_searchterm_daily` with full column definitions
3. Add `client_id` to all view column lists
4. Add a note in `SQL_GENERATION_PROMPT` that UNION ALL requires matching column schemas

### Long term
Consider generating the schema context dynamically from `clients.yaml` and `sql/views/*.sql` at dashboard startup, so it can never drift.

## Key Files

| File | Role |
|------|------|
| `dashboard/chat_schema.py` | Static schema context sent to Claude |
| `sql/views/*.sql` | Actual view SQL definitions (source of truth) |
| `clients.yaml` | Client registry (source of truth for datasets) |
| `dashboard/pages/data_chat.py` | Data Chat page that uses the schema |
