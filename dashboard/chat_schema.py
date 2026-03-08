"""BigQuery schema context for Claude AI chat integration."""

SCHEMA_CONTEXT = """
## Available Datasets
Each client has their own dataset prefixed with `adp_`:
- adp_client_07
- adp_client_01
- adp_client_12
- adp_client_18
- adp_client_05
- adp_client_21
- adp_client_22
- adp_client_19
- adp_client_17
- adp_client_20
- adp_client_16

## Views (recommended - deduplicated with pre-calculated KPIs)

### v_ads_campaign_daily
Campaign-level daily performance metrics.
Columns:
- date (DATE): The reporting date
- campaign_id (STRING): Unique campaign identifier
- campaign_name (STRING): Human-readable campaign name
- campaign_status (STRING): e.g., ENABLED, PAUSED
- budget (FLOAT64): Daily budget in currency
- currency (STRING): Currency code (e.g., EUR)
- impressions (INT64): Number of ad impressions
- clicks (INT64): Number of ad clicks
- cost (FLOAT64): Total ad spend
- purchases (INT64): Number of attributed purchases
- sales (FLOAT64): Total attributed sales revenue
- units_sold (INT64): Number of units sold
- acos (FLOAT64): Advertising Cost of Sales (cost/sales * 100), as percentage
- roas (FLOAT64): Return on Ad Spend (sales/cost)
- ctr (FLOAT64): Click-through rate (clicks/impressions * 100), as percentage
- cpc (FLOAT64): Cost per click (cost/clicks)
- cvr (FLOAT64): Conversion rate (purchases/clicks * 100), as percentage

### v_ads_adgroup_daily
Ad group level daily performance.
Columns:
- date (DATE)
- adgroup_id (STRING)
- adgroup_name (STRING)
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

### v_ads_asin_daily
ASIN-level daily performance (product-level metrics).
Columns:
- date (DATE)
- asin (STRING): Amazon Standard Identification Number
- sku (STRING): Stock Keeping Unit
- campaign_name (STRING)
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

### v_ads_summary_daily
Client-level daily totals (aggregated across all campaigns).
Columns:
- date (DATE)
- active_campaigns (INT64): Number of active campaigns that day
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

## Query Patterns

### Single client query
```sql
SELECT date, campaign_name, cost, sales, acos
FROM `example-gcp-project.adp_client_07.v_ads_campaign_daily`
WHERE date BETWEEN '2025-01-01' AND '2025-01-31'
ORDER BY cost DESC
LIMIT 10
```

### Cross-client comparison (use UNION ALL)
```sql
SELECT 'client_07' AS client, SUM(cost) AS total_cost, SUM(sales) AS total_sales
FROM `example-gcp-project.adp_client_07.v_ads_summary_daily`
WHERE date BETWEEN '2025-01-01' AND '2025-01-31'
UNION ALL
SELECT 'client_01' AS client, SUM(cost) AS total_cost, SUM(sales) AS total_sales
FROM `example-gcp-project.adp_client_01.v_ads_summary_daily`
WHERE date BETWEEN '2025-01-01' AND '2025-01-31'
```

## Important Notes
- All monetary values (cost, sales, budget) are in EUR
- ACoS, CTR, and CVR are stored as percentages (e.g., 25.5 means 25.5%)
- ROAS is a ratio (e.g., 4.0 means 4x return)
- Always use LIMIT to avoid returning too many rows
- Use SAFE_DIVIDE for calculations to avoid division by zero
- Date format is YYYY-MM-DD
"""

SQL_GENERATION_PROMPT = """You are a SQL expert for Amazon advertising data stored in BigQuery.
Given a user question, generate a SQL query to answer it.

{schema}

## Rules
1. Use fully qualified table names: `example-gcp-project.{{dataset}}.{{view}}`
2. Always include LIMIT (maximum 1000 rows)
3. Use the views (v_ads_*) not raw tables
4. For date ranges, use BETWEEN with 'YYYY-MM-DD' format
5. Use SAFE_DIVIDE for any division operations
6. Return ONLY the SQL query, no explanations or markdown code blocks
7. If asked about "all clients" or comparing clients, use UNION ALL across datasets
8. For aggregations, use appropriate GROUP BY clauses
9. Round numeric results to 2 decimal places where appropriate

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
