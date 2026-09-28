"""GENERATED demo data — a fictional outdoor-sports shop, not a real business.

Every number here comes from a seeded random generator. The shape follows
what marketing data looks like in practice, including the properties that
make a plausible query return a wrong number:

- ``ads_campaign_daily.cost`` is stored in euro **cents** (integer), as some
  ad platforms deliver it; ``attributed_sales_14d`` is in euros.
- ``shop_orders_daily.revenue_gross`` includes 19 % VAT.
- ``web_sessions_daily`` has one row per date **and channel**, so an average
  over its rows is not a daily average.
- Campaign names live only in ``campaigns``; the performance table carries
  the id.

Period: 2026-06-01 to 2026-09-27, fixed, so questions and expected answers
stay reproducible.
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

START = date(2026, 6, 1)
END = date(2026, 9, 27)
SEED = 20260928
VAT = 0.19

CAMPAIGNS = [
    # id, name, channel, status, daily budget in EUR, CTR, CPC in EUR, conv. rate, AOV in EUR
    (101, "Search - Brand", "search", "active", 60, 0.080, 0.35, 0.090, 72),
    (102, "Search - Running Shoes", "search", "active", 140, 0.045, 0.85, 0.035, 95),
    (103, "Search - Hiking Boots", "search", "active", 110, 0.040, 0.95, 0.030, 130),
    (104, "Search - Rain Jackets", "search", "paused", 70, 0.038, 0.80, 0.028, 110),
    (105, "Search - Generic Outdoor", "search", "active", 90, 0.025, 0.60, 0.015, 65),
    (201, "Display - Retargeting", "display", "active", 50, 0.009, 0.45, 0.020, 80),
    (202, "Display - Prospecting", "display", "active", 80, 0.004, 0.30, 0.006, 70),
    (203, "Display - Summer Sale", "display", "paused", 60, 0.006, 0.35, 0.012, 60),
]
#: Last active day of the paused campaigns.
PAUSED_FROM = {104: date(2026, 8, 20), 203: date(2026, 8, 31)}

PRODUCTS = [
    ("RUN-001", "Trail Runner Pro", "Running", 139.95),
    ("RUN-002", "Road Runner Lite", "Running", 99.95),
    ("RUN-003", "Running Socks 3-Pack", "Running", 19.95),
    ("HIK-001", "Alpine Hiking Boot", "Hiking", 179.95),
    ("HIK-002", "Day Hike Backpack 22L", "Hiking", 69.95),
    ("HIK-003", "Trekking Poles Carbon", "Hiking", 89.95),
    ("OUT-001", "Rain Shell Jacket", "Outerwear", 149.95),
    ("OUT-002", "Softshell Vest", "Outerwear", 79.95),
    ("ACC-001", "Insulated Bottle 750ml", "Accessories", 29.95),
    ("ACC-002", "Merino Beanie", "Accessories", 24.95),
]
#: Share of ordered units that come back, per category.
RETURN_RATE = {"Running": 0.14, "Hiking": 0.08, "Outerwear": 0.11, "Accessories": 0.03}

CHANNELS = [
    # channel, sessions/day, engaged share, purchase rate per session
    ("paid_search", 1400, 0.62, 0.024),
    ("display", 900, 0.35, 0.004),
    ("organic", 2100, 0.58, 0.018),
    ("direct", 800, 0.66, 0.030),
    ("email", 300, 0.71, 0.041),
]


def _days():
    d = START
    while d <= END:
        yield d
        d += timedelta(days=1)


def _season(d: date) -> float:
    """A little seasonality: a summer-sale bump in July, a weekend lift."""
    bump = 1.25 if d.month == 7 else 1.0
    weekend = 1.12 if d.weekday() >= 5 else 1.0
    return bump * weekend


def build_tables(seed: int = SEED) -> dict[str, pd.DataFrame]:
    rng = random.Random(seed)

    campaigns = pd.DataFrame(
        [(c[0], c[1], c[2], c[3]) for c in CAMPAIGNS],
        columns=["campaign_id", "campaign_name", "channel", "status"],
    )

    ads = []
    for d in _days():
        for cid, _, _, _, budget, ctr, cpc, cvr, aov in CAMPAIGNS:
            if cid in PAUSED_FROM and d > PAUSED_FROM[cid]:
                continue
            spend = budget * _season(d) * rng.uniform(0.75, 1.05)
            clicks = max(1, round(spend / (cpc * rng.uniform(0.85, 1.15))))
            impressions = round(clicks / (ctr * rng.uniform(0.8, 1.2)))
            orders = sum(rng.random() < cvr for _ in range(clicks))
            sales = round(orders * aov * rng.uniform(0.85, 1.15), 2)
            ads.append((d, cid, impressions, clicks, round(spend * 100), sales, orders))
    ads_daily = pd.DataFrame(ads, columns=[
        "date", "campaign_id", "impressions", "clicks", "cost",
        "attributed_sales_14d", "attributed_orders_14d",
    ])

    products = pd.DataFrame(PRODUCTS, columns=["sku", "product_name", "category", "list_price"])

    orders = []
    for d in _days():
        for sku, _, category, price in PRODUCTS:
            base = {"Running": 9, "Hiking": 6, "Outerwear": 4, "Accessories": 12}[category]
            units = max(0, round(base * _season(d) * rng.uniform(0.4, 1.6)))
            returned = sum(rng.random() < RETURN_RATE[category] for _ in range(units))
            discount = 0.8 if d.month == 7 else 1.0
            revenue = round(units * price * discount, 2)  # list prices include VAT
            orders.append((d, sku, units, returned, revenue))
    shop_orders = pd.DataFrame(
        orders, columns=["date", "sku", "units_ordered", "units_returned", "revenue_gross"]
    )

    sessions = []
    for d in _days():
        for channel, base, engaged, pr in CHANNELS:
            n = round(base * _season(d) * rng.uniform(0.85, 1.15))
            e = round(n * engaged * rng.uniform(0.9, 1.1))
            p = round(n * pr * rng.uniform(0.7, 1.3))
            sessions.append((d, channel, n, e, p))
    web_sessions = pd.DataFrame(
        sessions, columns=["date", "channel", "sessions", "engaged_sessions", "purchases"]
    )

    return {
        "campaigns": campaigns,
        "ads_campaign_daily": ads_daily,
        "products": products,
        "shop_orders_daily": shop_orders,
        "web_sessions_daily": web_sessions,
    }


_TYPES = {
    "date": "DATE",
    "campaign_id": "INTEGER", "impressions": "INTEGER", "clicks": "INTEGER",
    "cost": "BIGINT", "attributed_orders_14d": "INTEGER",
    "units_ordered": "INTEGER", "units_returned": "INTEGER",
    "sessions": "INTEGER", "engaged_sessions": "INTEGER", "purchases": "INTEGER",
}


def write_duckdb(path: str | Path, seed: int = SEED) -> Path:
    """Write the demo tables to a fresh DuckDB file and return its path."""
    import duckdb

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    con = duckdb.connect(str(path))
    try:
        for name, df in build_tables(seed).items():
            con.register("_df", df)
            casts = ", ".join(
                f"CAST({c} AS {_TYPES[c]}) AS {c}" if c in _TYPES else c for c in df.columns
            )
            con.execute(f"CREATE TABLE {name} AS SELECT {casts} FROM _df")
            con.unregister("_df")
            con.execute(
                f"COMMENT ON TABLE {name} IS 'GENERATED DEMO DATA (seed {seed}) - not a real business'"
            )
    finally:
        con.close()
    return path
