# Plan: Fix Data Chat Schema Drift

**Priority:** Medium
**Status:** Ready to implement
**Bug doc:** `docs/bug-data-chat-schema-drift.md`

## Problem

`dashboard/chat_schema.py` contains a hardcoded `SCHEMA_CONTEXT` string that is sent to Claude for SQL generation. It has drifted from reality:

1. **Stale client list** — 7 datasets listed don't exist, 4 real ones missing
2. **Missing `v_ads_searchterm_daily`** — added in `b5b6cd3`, never added to schema
3. **Missing `client_id` column** — all views have it, schema doesn't mention it
4. **No UNION ALL safety guidance** — Claude generates UNION ALL across views with different columns, causing SQL errors
5. **Stale model reference** — `data_chat.py:103` uses `claude-sonnet-4-20250514`, should use latest

## Short-Term Fix (this plan)

Manually update `chat_schema.py` to match current state. Quick, no architecture change.

### Step 1: Fix client/dataset list

Replace the hardcoded list with the 8 current clients from `clients.yaml`:

```
- adp_client_07
- adp_client_05
- adp_client_01
- adp_client_12
- adp_client_06
- adp_client_03
- adp_client_10
- adp_client_14
```

### Step 2: Add `v_ads_searchterm_daily`

Add the search term view with full column definitions (from `sql/views/ads_searchterm_daily.sql`):

```
### v_ads_searchterm_daily
Search term performance — which customer search queries trigger ads.
Columns:
- date (DATE)
- search_term (STRING): Customer's search query
- keyword (STRING): Matched keyword from campaign
- keyword_id (STRING)
- keyword_type (STRING)
- match_type (STRING): BROAD, PHRASE, EXACT
- campaign_name (STRING)
- campaign_id (STRING)
- ad_group_name (STRING)
- ad_group_id (STRING)
- impressions (INT64)
- clicks (INT64)
- cost (FLOAT64)
- purchases (INT64)
- sales (FLOAT64)
- units_sold (INT64)
- acos (FLOAT64): percentage
- roas (FLOAT64)
- ctr (FLOAT64): percentage
- cpc (FLOAT64)
- cvr (FLOAT64): percentage
- client_id (STRING)
```

### Step 3: Add `client_id` to all view definitions

Append `- client_id (STRING)` to every view's column list. This enables Claude to write single-view cross-client queries instead of always using UNION ALL.

### Step 4: Add UNION ALL guidance to SQL_GENERATION_PROMPT

Add rule to the `## Rules` section:

```
10. UNION ALL requires all SELECT statements to have the same number and type of columns.
    Do NOT combine different views (e.g., v_ads_summary_daily + v_ads_campaign_daily) in a UNION ALL.
    For cross-view queries, use separate queries or JOINs instead.
11. All views contain a `client_id` column. Use it for cross-client queries within a single view
    instead of UNION ALL across datasets when possible.
```

### Step 5: Update model reference

In `dashboard/pages/data_chat.py:103`, update the model to latest:

```python
model="claude-sonnet-4-6"
```

## Files to change

| File | Change |
|------|--------|
| `dashboard/chat_schema.py` | Update dataset list, add searchterm view, add client_id to all views, add UNION ALL guidance |
| `dashboard/pages/data_chat.py` | Update model ID |

## Long-Term Fix (future)

Generate `SCHEMA_CONTEXT` dynamically at dashboard startup:
- Read client list from `clients.yaml` (or BQ dataset discovery)
- Parse `sql/views/*.sql` for column definitions
- Build the schema string programmatically

This eliminates drift entirely but is a larger change. Tracked separately — not part of this plan.

## Verification

1. Start dashboard locally
2. Open Data Chat, select a client
3. Ask "give me an account overview for today" — should NOT produce UNION ALL across different views
4. Ask "show me top search terms by spend" — should use `v_ads_searchterm_daily`
5. Ask "compare spend across all clients" — should use `client_id` filter or same-view UNION ALL
