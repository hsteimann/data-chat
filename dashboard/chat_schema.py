"""BigQuery schema context for Claude AI chat integration."""

SCHEMA_CONTEXT = """
## Available Datasets
Each client has their own dataset prefixed with `adp_`:
- adp_client_07
- adp_client_05
- adp_client_01
- adp_client_12
- adp_client_06
- adp_client_03
- adp_client_10
- adp_client_14

## Views (recommended - deduplicated with pre-calculated KPIs)

All views contain a `client_id` (STRING) column that identifies the client.

### v_ads_summary_daily
Client-level daily totals (aggregated across all campaigns).
One row per client per day — the big-picture numbers.
Use this for: overall spend trends, total sales over time, daily/weekly/monthly performance summaries, comparing time periods, checking if spend or sales are up or down.
Typical questions: "How much did we spend last month?", "What's our overall ACoS trend?", "Compare this week vs last week."
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
- client_id (STRING)

### v_ads_campaign_daily
Campaign-level daily performance metrics. One row per campaign per day.
Use this for: identifying top/bottom campaigns, checking campaign budgets and status, analyzing spend distribution across campaigns, finding paused or underperforming campaigns.
Typical questions: "Which campaigns have the highest ACoS?", "Show me paused campaigns that were still spending", "Which campaign has the best ROAS?", "How is budget distributed across campaigns?"
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
- client_id (STRING)

### v_ads_adgroup_daily
Ad group level daily performance. One row per ad group per day.
Ad groups sit inside campaigns and group related keywords/targets together.
Use this for: finding which ad groups within a campaign perform best or worst, optimizing at the ad group level, comparing ad group strategies.
Typical questions: "Which ad groups are wasting spend?", "Show me the top ad groups by sales", "Which ad groups have high clicks but no conversions?"
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
- client_id (STRING)

### v_ads_asin_daily
ASIN-level daily performance (product-level metrics). One row per ASIN per campaign per day.
Each ASIN is a specific product. This view shows how each product performs in advertising.
Use this for: identifying best/worst-selling products, finding products with high ad spend but low sales, product-level profitability analysis, comparing product performance across campaigns.
Typical questions: "Which products have the worst ACoS?", "Show me the top 10 products by sales", "Which ASINs are getting clicks but no purchases?", "What's the ad performance for ASIN B0xxxxx?"
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
- client_id (STRING)

### v_ads_searchterm_daily
Search term performance — which customer search queries triggered ads. One row per search term per campaign per ad group per day.
This is the most granular view. It shows what customers actually typed into Amazon search and how those searches performed.
Use this for: keyword research, finding high-performing or wasted search terms, negative keyword candidates, match type analysis, understanding customer search behavior.
Typical questions: "Which search terms drive the most sales?", "Show me search terms with spend but zero purchases", "What are customers searching for?", "Which broad match terms should become exact match?", "Find negative keyword candidates (high cost, no sales)."
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

### rf_products (raw table — Rainforest product data)
Product catalog data collected via the Rainforest API. One row per ASIN per snapshot.
Contains product names, brand names, prices, ratings, Buy Box info, and availability — data that the ads views do NOT have.
Use this for: looking up product names or brands for ASINs, combining product info with ad performance, checking availability or Buy Box status alongside ad spend.
Typical questions: "Show top ASINs with product name and brand", "Which products have high ad spend but are out of stock?", "List advertised products with their ratings and prices."
**Important:** This is a raw table (not a view), and it may have multiple snapshots per ASIN. Always use the latest snapshot by filtering with ROW_NUMBER() OVER (PARTITION BY asin ORDER BY snapshot_date DESC) = 1.
Columns:
- snapshot_date (STRING): Date the product data was collected (YYYY-MM-DD)
- asin (STRING): Amazon Standard Identification Number — JOIN key with v_ads_asin_daily
- collection_id (STRING): Rainforest collection identifier
- title (STRING): Product title / name
- brand (STRING): Brand name
- link (STRING): Amazon product page URL
- rating (FLOAT64): Average star rating (1-5)
- ratings_total (INT64): Total number of ratings
- images_count (INT64)
- has_a_plus_content (BOOLEAN)
- has_brand_story (BOOLEAN)
- feature_bullets_count (INT64)
- videos_count (INT64)
- bestsellers_rank_flat (STRING): BSR as text
- bestsellers_rank_1 (INT64): Primary BSR rank
- bestsellers_rank_1_category (STRING): Primary BSR category
- categories_flat (STRING)
- recent_sales (STRING)
- buybox_price (FLOAT64)
- buybox_currency (STRING)
- buybox_rrp (FLOAT64): Recommended retail price
- buybox_seller_name (STRING)
- buybox_seller_id (STRING)
- is_sold_by_amazon (BOOLEAN)
- is_fulfilled_by_amazon (BOOLEAN)
- is_prime (BOOLEAN)
- availability_type (STRING)
- availability_raw (STRING)
- client_id (STRING)
- loaded_at (STRING): When the data was loaded into BigQuery

## View Relationships (for JOINs)

The views share common columns that can be used as JOIN keys.
Always include `date` in JOIN conditions to keep the join at the daily grain.

| View A | View B | JOIN keys |
|--------|--------|-----------|
| v_ads_campaign_daily | v_ads_searchterm_daily | campaign_id + date |
| v_ads_campaign_daily | v_ads_asin_daily | campaign_name + date |
| v_ads_adgroup_daily | v_ads_searchterm_daily | adgroup_id = ad_group_id + date |
| v_ads_asin_daily | rf_products | asin |
| v_ads_campaign_daily | rf_products | (via v_ads_asin_daily as bridge: campaign_name + asin) |

Notes:
- v_ads_asin_daily does NOT have campaign_id — use campaign_name to join with campaign data.
- v_ads_adgroup_daily does NOT have campaign_id or campaign_name — join it only with searchterm_daily via adgroup_id.
- v_ads_summary_daily is an aggregation of campaign_daily. Do not JOIN them — query campaign_daily directly instead.
- rf_products is a raw table, NOT a view. Always deduplicate to the latest snapshot per ASIN using: ROW_NUMBER() OVER (PARTITION BY asin ORDER BY snapshot_date DESC) = 1.
- rf_products uses the fully qualified name `example-gcp-project.{dataset}.rf_products` (same dataset as the views).
- All views share client_id and date. Always include both in JOIN conditions when applicable.

## Query Patterns

### Single client query
```sql
SELECT date, campaign_name, cost, sales, acos
FROM `example-gcp-project.adp_client_07.v_ads_campaign_daily`
WHERE date BETWEEN '2025-01-01' AND '2025-01-31'
ORDER BY cost DESC
LIMIT 10
```

### Cross-client comparison (use client_id within a single view)
```sql
SELECT client_id, SUM(cost) AS total_cost, SUM(sales) AS total_sales
FROM `example-gcp-project.adp_client_07.v_ads_summary_daily`
WHERE date BETWEEN '2025-01-01' AND '2025-01-31'
GROUP BY client_id
```

### JOIN: Campaign budget + status with ASIN product performance
```sql
SELECT
  c.date,
  c.campaign_name,
  c.campaign_status,
  c.budget,
  a.asin,
  a.sku,
  a.impressions,
  a.clicks,
  a.cost,
  a.sales,
  a.acos
FROM `example-gcp-project.adp_client_07.v_ads_campaign_daily` c
JOIN `example-gcp-project.adp_client_07.v_ads_asin_daily` a
  ON c.campaign_name = a.campaign_name AND c.date = a.date
WHERE c.date BETWEEN '2025-01-01' AND '2025-01-31'
ORDER BY a.cost DESC
LIMIT 100
```

### JOIN: Campaign details with search term performance
```sql
SELECT
  c.campaign_name,
  c.campaign_status,
  c.budget,
  s.search_term,
  s.match_type,
  s.impressions,
  s.clicks,
  s.cost,
  s.sales,
  s.acos
FROM `example-gcp-project.adp_client_07.v_ads_campaign_daily` c
JOIN `example-gcp-project.adp_client_07.v_ads_searchterm_daily` s
  ON c.campaign_id = s.campaign_id AND c.date = s.date
WHERE c.date BETWEEN '2025-01-01' AND '2025-01-31'
  AND s.clicks > 0
ORDER BY s.cost DESC
LIMIT 100
```

### JOIN: Top ASINs with product name and brand from Rainforest data
```sql
WITH rf_latest AS (
  SELECT *, ROW_NUMBER() OVER (PARTITION BY asin ORDER BY snapshot_date DESC) AS _rn
  FROM `example-gcp-project.adp_client_07.rf_products`
)
SELECT
  a.asin,
  rf.title AS product_name,
  rf.brand,
  SUM(a.impressions) AS impressions,
  SUM(a.clicks) AS clicks,
  ROUND(SUM(a.cost), 2) AS cost,
  SUM(a.purchases) AS purchases,
  ROUND(SUM(a.sales), 2) AS sales,
  ROUND(SAFE_DIVIDE(SUM(a.cost), SUM(a.sales)) * 100, 2) AS acos
FROM `example-gcp-project.adp_client_07.v_ads_asin_daily` a
LEFT JOIN rf_latest rf ON a.asin = rf.asin AND rf._rn = 1
WHERE a.date BETWEEN '2025-01-01' AND '2025-01-31'
GROUP BY a.asin, rf.title, rf.brand
ORDER BY sales DESC
LIMIT 10
```

## Important Notes
- All monetary values (cost, sales, budget) are in EUR (except US marketplace clients like client_06 which use USD)
- ACoS, CTR, and CVR are stored as percentages (e.g., 25.5 means 25.5%)
- ROAS is a ratio (e.g., 4.0 means 4x return)
- Always use LIMIT to avoid returning too many rows
- Use SAFE_DIVIDE for calculations to avoid division by zero
- Date format is YYYY-MM-DD
- Each view has different columns. NEVER use UNION ALL across different views (e.g., do NOT combine v_ads_summary_daily with v_ads_campaign_daily). Only UNION ALL the same view across different datasets.
"""

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
