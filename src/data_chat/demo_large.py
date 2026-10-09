"""GENERATED demo data, large — the same fictional outdoor-sports shop, seen the
way a real client's data platform sees it: 35 tables over the own web shop,
two marketplaces, five ad channels and web analytics. Not a real business.

The small demo (``demo_data.py``, five tables) shows what a field-level
catalog does for a query. This one exists for the next question: how much of
that catalog should the model see at once? So the tables are many, and some
of them are easy to mix up on purpose — the way they are in practice:

- the same figures as a daily, a weekly and a monthly table;
- one table per ad channel with similar columns, and a cross-channel table
  whose conversions mix the channels' attribution windows;
- gross and net revenue, revenue before and after returns, and a
  marketplace that reports net where the other reports gross;
- the shop's orders under three attribution models (last click, first
  click, data-driven) that agree on the total and disagree per channel;
- two deprecated tables (``*_v1``) next to the current ones;
- tables that are close to a question's subject but do not answer it
  (inventory, fees, site search, email sends, budgets).

Every number comes from a seeded random generator, and every aggregate is
computed from the rows below it, so a question has one right answer.

Period: 2026-06-01 (a Monday) to 2026-09-27 (a Sunday) — 17 full weeks;
September is a partial month.
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

START = date(2026, 6, 1)
END = date(2026, 9, 27)
SEED = 20261009
VAT = 0.19
FREE_SHIPPING_FROM = 75.0
SHIPPING_FEE = 4.95

PRODUCTS = [
    # sku, name, category, subcategory, brand, list price incl. VAT, on Amazon, on Otto
    ("RUN-001", "Trail Runner Pro", "Running", "Shoes", "Northpeak", 139.95, True, True),
    ("RUN-002", "Road Runner Lite", "Running", "Shoes", "Northpeak", 99.95, True, True),
    ("RUN-003", "Running Socks 3-Pack", "Running", "Socks", "Trailwerk", 19.95, True, False),
    ("RUN-004", "Running Tights Thermo", "Running", "Apparel", "Trailwerk", 59.95, True, True),
    ("RUN-005", "Hydration Vest 5L", "Running", "Packs", "Northpeak", 79.95, False, False),
    ("HIK-001", "Alpine Hiking Boot", "Hiking", "Shoes", "Alpenlicht", 179.95, True, True),
    ("HIK-002", "Day Hike Backpack 22L", "Hiking", "Packs", "Northpeak", 69.95, True, True),
    ("HIK-003", "Trekking Poles Carbon", "Hiking", "Equipment", "Alpenlicht", 89.95, True, False),
    ("HIK-004", "Hiking Pants Convertible", "Hiking", "Apparel", "Trailwerk", 74.95, False, True),
    ("HIK-005", "Trekking Backpack 45L", "Hiking", "Packs", "Alpenlicht", 149.95, True, True),
    ("OUT-001", "Rain Shell Jacket", "Outerwear", "Jackets", "Northpeak", 149.95, True, True),
    ("OUT-002", "Softshell Vest", "Outerwear", "Vests", "Trailwerk", 79.95, True, False),
    ("OUT-003", "Down Jacket Light", "Outerwear", "Jackets", "Alpenlicht", 199.95, False, True),
    ("OUT-004", "Fleece Midlayer", "Outerwear", "Midlayers", "Northpeak", 64.95, True, True),
    ("CMP-001", "Tent Ultralight 2P", "Camping", "Tents", "Alpenlicht", 299.95, True, False),
    ("CMP-002", "Sleeping Bag 3-Season", "Camping", "Sleeping", "Northpeak", 129.95, True, True),
    ("CMP-003", "Camping Stove Compact", "Camping", "Cooking", "Trailwerk", 49.95, True, False),
    ("CMP-004", "Sleeping Mat Inflatable", "Camping", "Sleeping", "Alpenlicht", 89.95, False, True),
    ("ACC-001", "Insulated Bottle 750ml", "Accessories", "Bottles", "Northpeak", 29.95, True, True),
    ("ACC-002", "Merino Beanie", "Accessories", "Headwear", "Trailwerk", 24.95, True, True),
    ("ACC-003", "Headlamp 400lm", "Accessories", "Lights", "Alpenlicht", 44.95, True, False),
    ("ACC-004", "Sun Cap", "Accessories", "Headwear", "Northpeak", 22.95, False, False),
]
#: Share of ordered units that come back, per category.
RETURN_RATE = {"Running": 0.14, "Hiking": 0.08, "Outerwear": 0.12, "Camping": 0.05, "Accessories": 0.03}
#: Relative demand per category (orders pick products by these weights).
DEMAND = {"Running": 1.4, "Hiking": 1.1, "Outerwear": 0.8, "Camping": 0.6, "Accessories": 1.6}

CAMPAIGNS = [
    # id, name, channel, objective, daily budget EUR, CTR, CPC EUR, start date
    (1001, "Search - Brand", "google_search", "conversions", 55, 0.090, 0.30, date(2025, 3, 1)),
    (1002, "Search - Running Shoes", "google_search", "conversions", 130, 0.045, 0.85, date(2025, 3, 1)),
    (1003, "Search - Hiking Boots", "google_search", "conversions", 105, 0.040, 0.95, date(2025, 4, 15)),
    (1004, "Search - Rain Jackets", "google_search", "conversions", 70, 0.038, 0.80, date(2025, 9, 1)),
    (1005, "Search - Generic Outdoor", "google_search", "traffic", 85, 0.025, 0.60, date(2025, 3, 1)),
    (1101, "Shopping - All Products", "google_shopping", "conversions", 120, 0.012, 0.45, date(2025, 5, 1)),
    (1102, "Shopping - Bestsellers", "google_shopping", "conversions", 60, 0.015, 0.50, date(2026, 2, 1)),
    (2001, "Meta - Prospecting", "meta", "conversions", 90, 0.011, 0.55, date(2025, 6, 1)),
    (2002, "Meta - Retargeting", "meta", "conversions", 45, 0.018, 0.40, date(2025, 6, 1)),
    (2003, "Meta - Summer Sale", "meta", "conversions", 70, 0.014, 0.45, date(2026, 6, 25)),
    (3001, "Bing - Brand", "microsoft", "conversions", 15, 0.080, 0.25, date(2025, 8, 1)),
    (3002, "Bing - Generic Outdoor", "microsoft", "traffic", 25, 0.030, 0.45, date(2025, 8, 1)),
    (4001, "SP - Auto", "amazon_sp", "conversions", 40, 0.004, 0.55, date(2025, 10, 1)),
    (4002, "SP - Running", "amazon_sp", "conversions", 35, 0.005, 0.70, date(2025, 10, 1)),
    (4003, "SP - Hiking", "amazon_sp", "conversions", 30, 0.005, 0.75, date(2025, 10, 1)),
]
#: Campaigns that stopped during the period: last active day.
PAUSED_FROM = {1004: date(2026, 8, 20), 2003: date(2026, 8, 31)}
#: Campaigns that started during the period: first active day.
STARTED_ON = {2003: date(2026, 6, 25)}
#: Platform-reported conversion rate per click and average order value (EUR, gross).
CONV = {
    "google_search": (0.032, 98.0), "google_shopping": (0.022, 84.0), "meta": (0.012, 76.0),
    "microsoft": (0.028, 92.0), "amazon_sp": (0.090, 61.0),
}

#: Web channel groups: base orders per day (true last touch) and sessions per order.
CHANNEL_GROUPS = {
    "paid_search": (34, 38), "paid_shopping": (16, 45), "paid_social": (12, 70),
    "organic_search": (42, 52), "direct": (24, 30), "email": (9, 25), "referral": (5, 60),
}
#: Which ad channels drive which web channel group.
AD_CHANNEL_GROUP = {"google_search": "paid_search", "microsoft": "paid_search",
                    "google_shopping": "paid_shopping", "meta": "paid_social"}

LANDING_PAGES = ["/", "/running", "/hiking", "/outerwear", "/camping", "/sale", "/blog/trail-guide"]
SEARCH_TERMS = ["rain jacket", "trail shoes", "tent", "backpack", "socks", "headlamp",
                "sleeping bag", "gift card", "size guide", "returns"]
EMAIL_CAMPAIGNS = ["newsletter_weekly", "abandoned_cart", "summer_sale", "new_arrivals"]
FEE_TYPES = {"referral_fee": 0.15, "fulfillment_fee": 0.11, "storage_fee": 0.01}
MONTHLY_BUDGET = {"google_search": 13500, "google_shopping": 5400, "meta": 6000,
                  "microsoft": 1200, "amazon_sp": 3150}


def _days():
    d = START
    while d <= END:
        yield d
        d += timedelta(days=1)


def _season(d: date) -> float:
    """A summer-sale bump in July and a weekend lift."""
    return (1.25 if d.month == 7 else 1.0) * (1.12 if d.weekday() >= 5 else 1.0)


def _week(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _month(d: date) -> date:
    return d.replace(day=1)


def _r2(x: float) -> float:
    return round(x + 0.0, 2)


def _ads(rng: random.Random) -> dict[str, pd.DataFrame]:
    """One row per day and campaign (Shopping: per day, campaign and SKU)."""
    rows: dict[str, list] = {c: [] for c in CONV}
    shopping_skus = [p[0] for p in PRODUCTS]
    for d in _days():
        for cid, _, channel, _, budget, ctr, cpc, _ in CAMPAIGNS:
            if cid in PAUSED_FROM and d > PAUSED_FROM[cid]:
                continue
            if cid in STARTED_ON and d < STARTED_ON[cid]:
                continue
            cvr, aov = CONV[channel]
            spend = budget * _season(d) * rng.uniform(0.75, 1.05)
            clicks = max(1, round(spend / (cpc * rng.uniform(0.85, 1.15))))
            impressions = round(clicks / (ctr * rng.uniform(0.8, 1.2)))
            conv = clicks * cvr * rng.uniform(0.7, 1.3)
            value = conv * aov * rng.uniform(0.85, 1.15)
            if channel == "google_shopping":
                weights = [rng.uniform(0.3, 1.7) for _ in shopping_skus]
                total = sum(weights)
                for sku, w in zip(shopping_skus, weights):
                    share = w / total
                    rows[channel].append((
                        d, cid, sku, round(impressions * share), round(clicks * share),
                        round(spend * share * 1_000_000), _r2(conv * share), _r2(value * share),
                    ))
            elif channel == "google_search":
                rows[channel].append((d, cid, impressions, clicks, round(spend * 1_000_000),
                                      _r2(conv), _r2(value)))
            elif channel == "meta":
                reach = round(impressions / rng.uniform(1.4, 2.2))
                rows[channel].append((d, cid, impressions, reach, clicks, _r2(spend),
                                      round(conv), _r2(value)))
            elif channel == "microsoft":
                rows[channel].append((d, cid, impressions, clicks, _r2(spend), _r2(conv), _r2(value)))
            else:  # amazon_sp: 7-day attribution is a subset of 14-day
                orders_14 = round(conv)
                orders_7 = round(orders_14 * rng.uniform(0.78, 0.9))
                sales_14 = _r2(value)
                sales_7 = _r2(sales_14 * (orders_7 / orders_14 if orders_14 else 0))
                rows[channel].append((d, cid, impressions, clicks, _r2(spend),
                                      orders_7, orders_14, sales_7, sales_14))
    return {
        "ads_google_search_campaign_daily": pd.DataFrame(rows["google_search"], columns=[
            "date", "campaign_id", "impressions", "clicks", "cost_micros", "conversions", "conversion_value"]),
        "ads_google_shopping_product_daily": pd.DataFrame(rows["google_shopping"], columns=[
            "date", "campaign_id", "sku", "impressions", "clicks", "cost_micros", "conversions",
            "conversion_value"]),
        "ads_meta_campaign_daily": pd.DataFrame(rows["meta"], columns=[
            "date", "campaign_id", "impressions", "reach", "link_clicks", "spend", "purchases",
            "purchase_value"]),
        "ads_microsoft_campaign_daily": pd.DataFrame(rows["microsoft"], columns=[
            "date", "campaign_id", "impressions", "clicks", "spend", "conversions", "revenue"]),
        "ads_amazon_sp_campaign_daily": pd.DataFrame(rows["amazon_sp"], columns=[
            "date", "campaign_id", "impressions", "clicks", "cost", "attributed_orders_7d",
            "attributed_orders_14d", "attributed_sales_7d", "attributed_sales_14d"]),
    }


def _ads_all_channels(ads: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """The channels side by side, in euros, each with its own platform's conversions."""
    gs = ads["ads_google_search_campaign_daily"]
    sh = ads["ads_google_shopping_product_daily"]
    me = ads["ads_meta_campaign_daily"]
    ms = ads["ads_microsoft_campaign_daily"]
    am = ads["ads_amazon_sp_campaign_daily"]
    parts = [
        gs.assign(channel="google_search", cost_eur=gs.cost_micros / 1e6,
                  platform_conversions=gs.conversions, platform_conversion_value=gs.conversion_value),
        sh.assign(channel="google_shopping", cost_eur=sh.cost_micros / 1e6,
                  platform_conversions=sh.conversions, platform_conversion_value=sh.conversion_value),
        me.assign(channel="meta", clicks=me.link_clicks, cost_eur=me.spend,
                  platform_conversions=me.purchases, platform_conversion_value=me.purchase_value),
        ms.assign(channel="microsoft", cost_eur=ms.spend,
                  platform_conversions=ms.conversions, platform_conversion_value=ms.revenue),
        am.assign(channel="amazon_sp", cost_eur=am.cost,
                  platform_conversions=am.attributed_orders_14d,
                  platform_conversion_value=am.attributed_sales_14d),
    ]
    cols = ["date", "channel", "impressions", "clicks", "cost_eur", "platform_conversions",
            "platform_conversion_value"]
    df = pd.concat([p[cols] for p in parts]).groupby(["date", "channel"], as_index=False).sum()
    for c in ("cost_eur", "platform_conversions", "platform_conversion_value"):
        df[c] = df[c].round(2)
    return df.sort_values(["date", "channel"]).reset_index(drop=True)


def _roll(df: pd.DataFrame, key: str, fn, by: list[str], sums: list[str]) -> pd.DataFrame:
    out = df.assign(**{key: df["date"].map(fn)}).groupby([key, *by], as_index=False)[sums].sum()
    for c in sums:
        if out[c].dtype.kind == "f":
            out[c] = out[c].round(2)
    return out.sort_values([key, *by]).reset_index(drop=True)


def _shop(rng: random.Random) -> dict[str, pd.DataFrame]:
    """Orders, their items and returns — and everything the shop aggregates from them."""
    weights = [DEMAND[p[2]] for p in PRODUCTS]
    orders, items, returns, attribution, customers = [], [], [], [], []
    next_order, next_customer, next_return = 100001, 50001, 900001
    known_customers: list[int] = []
    groups = list(CHANNEL_GROUPS)
    for d in _days():
        for group, (base, _) in CHANNEL_GROUPS.items():
            for _ in range(max(0, round(base * _season(d) * rng.uniform(0.75, 1.25)))):
                oid, next_order = next_order, next_order + 1
                new = not known_customers or rng.random() < 0.35
                if new:
                    cid, next_customer = next_customer, next_customer + 1
                    known_customers.append(cid)
                    customers.append((cid, d, rng.choice(["DE"] * 8 + ["AT", "CH"]), rng.random() < 0.4))
                else:
                    cid = rng.choice(known_customers)
                cancelled = rng.random() < 0.04
                gross = list_total = 0.0
                lines: list[tuple] = []  # distinct products per order: one line per sku
                for _ in range(rng.choice([1, 1, 1, 2, 2, 3])):
                    pick = rng.choices(PRODUCTS, weights=weights)[0]
                    if pick not in lines:
                        lines.append(pick)
                for prod in lines:
                    sku, _, category, _, _, price, _, _ = prod
                    units = rng.choice([1, 1, 1, 2])
                    paid = _r2(units * price * (0.8 if d.month == 7 else 1.0))
                    gross += paid
                    list_total += units * price
                    items.append((oid, d, sku, units, paid))
                    if not cancelled:
                        back = sum(rng.random() < RETURN_RATE[category] for _ in range(units))
                        rdate = d + timedelta(days=rng.randint(4, 24))
                        if back and rdate <= END:
                            rid, next_return = next_return, next_return + 1
                            returns.append((rid, oid, rdate, sku, back, _r2(paid * back / units)))
                gross = _r2(gross)
                shipping = 0.0 if gross >= FREE_SHIPPING_FROM else SHIPPING_FEE
                orders.append((oid, d, cid, new, "cancelled" if cancelled else "completed",
                               gross, _r2(gross / (1 + VAT)), shipping, _r2(list_total - gross)))
                if not cancelled:
                    attribution.append((d, oid, group, gross, rng.choice(groups), rng.random()))

    shop_orders = pd.DataFrame(orders, columns=[
        "order_id", "order_date", "customer_id", "is_new_customer", "order_status",
        "revenue_gross", "revenue_net", "shipping_fee_gross", "discount_gross"])
    shop_items = pd.DataFrame(items, columns=["order_id", "order_date", "sku", "units", "item_revenue_gross"])
    shop_returns = pd.DataFrame(returns, columns=[
        "return_id", "order_id", "return_date", "sku", "units_returned", "refund_gross"])

    done = shop_orders[shop_orders.order_status == "completed"]
    items_done = shop_items[shop_items.order_id.isin(done.order_id)]
    units_per_order = items_done.groupby("order_id").units.sum()
    daily = done.assign(date=done.order_date, units=done.order_id.map(units_per_order),
                        new_customer_orders=done.is_new_customer.astype(int), orders=1)
    sums = ["orders", "new_customer_orders", "units", "revenue_gross", "revenue_net", "shipping_fee_gross"]
    shop_daily = _roll(daily, "date", lambda x: x, [], sums)
    shop_weekly = _roll(daily, "week_start", _week, [], sums)
    shop_monthly = _roll(daily, "month", _month, [], sums)

    refunds = shop_returns.assign(date=shop_returns.return_date).groupby("date").refund_gross.sum()
    after = shop_daily[["date", "revenue_net"]].copy()
    after["refunds_net"] = after.date.map(refunds).fillna(0).map(lambda v: _r2(v / (1 + VAT)))
    after["revenue_net_after_returns"] = (after.revenue_net - after.refunds_net).round(2)

    v1 = shop_orders.assign(date=shop_orders.order_date, orders=1,
                            revenue=shop_orders.revenue_gross + shop_orders.shipping_fee_gross)
    shop_v1 = _roll(v1, "date", lambda x: x, [], ["orders", "revenue"])

    product_daily = items_done.assign(date=items_done.order_date, units_ordered=items_done.units,
                                      revenue_gross=items_done.item_revenue_gross)
    product_daily = _roll(product_daily, "date", lambda x: x, ["sku"], ["units_ordered", "revenue_gross"])
    product_daily["revenue_net"] = (product_daily.revenue_gross / (1 + VAT)).round(2)

    stock, inventory = {p[0]: rng.randint(80, 220) for p in PRODUCTS}, []
    sold = product_daily.set_index(["date", "sku"]).units_ordered
    for d in _days():
        for sku in stock:
            stock[sku] = max(0, stock[sku] - int(sold.get((d, sku), 0)))
            if stock[sku] < 25:
                stock[sku] += rng.randint(100, 200)
            inventory.append((d, sku, stock[sku]))

    attr = pd.DataFrame(attribution, columns=["date", "order_id", "last", "revenue", "other", "u"])
    first = attr.assign(channel_group=[o if u < 0.3 else last for last, o, u in
                                       zip(attr["last"], attr["other"], attr["u"])])
    dd_rows = []
    for row in attr.itertuples(index=False):
        if row.other == row.last:
            dd_rows.append((row.date, row.last, 1.0, row.revenue))
        else:
            dd_rows += [(row.date, row.last, 0.6, row.revenue * 0.6),
                        (row.date, row.other, 0.4, row.revenue * 0.4)]
    data_driven = pd.DataFrame(dd_rows, columns=["date", "channel_group", "purchases", "purchase_revenue_gross"])

    def per_group(df: pd.DataFrame) -> pd.DataFrame:
        out = (df.groupby(["date", "channel_group"], as_index=False)[["purchases", "purchase_revenue_gross"]]
               .sum().sort_values(["date", "channel_group"]).reset_index(drop=True))
        out["purchase_revenue_gross"] = out.purchase_revenue_gross.round(2)
        return out

    last_click = per_group(attr.assign(channel_group=attr["last"], purchases=1, purchase_revenue_gross=attr.revenue))
    first_click = per_group(first.assign(purchases=1, purchase_revenue_gross=first.revenue))
    dd = per_group(data_driven)
    dd["purchases"] = dd.purchases.round(2)

    return {
        "customers": pd.DataFrame(customers, columns=["customer_id", "first_order_date", "country",
                                                      "newsletter_optin"]),
        "shop_orders": shop_orders,
        "shop_order_items": shop_items,
        "shop_returns": shop_returns,
        "shop_sales_daily": shop_daily,
        "shop_sales_weekly": shop_weekly,
        "shop_sales_monthly": shop_monthly,
        "shop_sales_net_of_returns_daily": after,
        "shop_sales_daily_v1": shop_v1,
        "shop_product_sales_daily": product_daily[["date", "sku", "units_ordered", "revenue_gross", "revenue_net"]],
        "shop_inventory_daily": pd.DataFrame(inventory, columns=["date", "sku", "stock_units"]),
        "web_conversions_last_click_daily": last_click,
        "web_conversions_first_click_daily": first_click,
        "web_conversions_data_driven_daily": dd,
    }


def _marketplaces(rng: random.Random) -> dict[str, pd.DataFrame]:
    amazon, otto = [], []
    for d in _days():
        for sku, _, category, _, _, price, on_amazon, on_otto in PRODUCTS:
            demand = DEMAND[category] * _season(d)
            if on_amazon:
                units = max(0, round(2.2 * demand * rng.uniform(0.3, 1.7)))
                sessions = max(units, round(units * rng.uniform(9, 16)) + rng.randint(5, 30))
                amazon.append((d, sku, units, _r2(units * price * rng.uniform(0.92, 1.0)), sessions,
                               round(sessions * rng.uniform(1.2, 1.6)), _r2(rng.uniform(0.82, 1.0))))
            if on_otto:
                units = max(0, round(1.1 * demand * rng.uniform(0.2, 1.8)))
                back = sum(rng.random() < RETURN_RATE[category] for _ in range(units))
                otto.append((d, sku, units, _r2(units * price * rng.uniform(0.95, 1.0) / (1 + VAT)), back))
    am = pd.DataFrame(amazon, columns=["date", "sku", "units_ordered", "ordered_product_sales",
                                       "sessions", "page_views", "buy_box_share"])
    ot = pd.DataFrame(otto, columns=["date", "sku", "units_sold", "revenue_net", "units_returned"])
    both = pd.concat([
        am.assign(marketplace="amazon", units=am.units_ordered, revenue_gross=am.ordered_product_sales),
        ot.assign(marketplace="otto", units=ot.units_sold, revenue_gross=(ot.revenue_net * (1 + VAT))),
    ])[["date", "marketplace", "units", "revenue_gross"]]
    combined = both.groupby(["date", "marketplace"], as_index=False).sum()
    combined["revenue_gross"] = combined.revenue_gross.round(2)
    monthly_sales = am.assign(month=am.date.map(_month)).groupby("month").ordered_product_sales.sum()
    fees = [(m, fee, _r2(-monthly_sales[m] * rate * rng.uniform(0.95, 1.05)))
            for m in monthly_sales.index for fee, rate in FEE_TYPES.items()]
    return {
        "marketplace_amazon_sales_daily": am,
        "marketplace_otto_sales_daily": ot,
        "marketplace_sales_daily": combined.sort_values(["date", "marketplace"]).reset_index(drop=True),
        "marketplace_amazon_fees_monthly": pd.DataFrame(fees, columns=["month", "fee_type", "amount_eur"]),
    }


def _web(rng: random.Random, ads_all: pd.DataFrame, last_click: pd.DataFrame) -> dict[str, pd.DataFrame]:
    clicks = ads_all.assign(group=ads_all.channel.map(AD_CHANNEL_GROUP)).dropna(subset=["group"])
    clicks = clicks.groupby(["date", "group"]).clicks.sum()
    purchases = last_click.set_index(["date", "channel_group"]).purchases
    sessions, funnel, landing, search, email = [], [], [], [], []
    for d in _days():
        day_sessions = 0
        for group, (_, per_order) in CHANNEL_GROUPS.items():
            bought = int(purchases.get((d, group), 0))
            n = int(clicks.get((d, group), 0) * rng.uniform(0.85, 0.95)) or round(bought * per_order * rng.uniform(0.9, 1.1))
            n = max(n, bought)
            sessions.append((d, group, n, round(n * rng.uniform(0.45, 0.7)), round(n * rng.uniform(0.25, 0.5))))
            day_sessions += n
        total_purchases = int(purchases.loc[d].sum()) if d in purchases.index.get_level_values(0) else 0
        # Devices split the day's sessions and purchases exactly: mobile takes the remainder.
        mobile = rng.uniform(0.58, 0.68)
        split = {"desktop": 1 - mobile - 0.05, "tablet": 0.05}
        s_by = {k: round(day_sessions * v) for k, v in split.items()}
        p_by = {k: round(total_purchases * v) for k, v in split.items()}
        s_by["mobile"] = day_sessions - sum(s_by.values())
        p_by["mobile"] = total_purchases - sum(p_by.values())
        for device in ("mobile", "desktop", "tablet"):
            s, p = s_by[device], p_by[device]
            pv = round(s * rng.uniform(0.55, 0.7))
            atc = max(p, round(pv * rng.uniform(0.12, 0.18)))
            funnel.append((d, device, s, pv, atc, max(p, round(atc * rng.uniform(0.45, 0.6))), p))
        for page in LANDING_PAGES:
            s = round(day_sessions * rng.uniform(0.05, 0.25))
            landing.append((d, page, s, round(s * rng.uniform(0.4, 0.7)), round(s * rng.uniform(0.005, 0.03))))
        if d.weekday() == 0:
            for term in SEARCH_TERMS:
                n = rng.randint(40, 600)
                search.append((d, term, n, round(n * rng.uniform(0.1, 0.4))))
        for name in EMAIL_CAMPAIGNS:
            if name == "newsletter_weekly" and d.weekday() != 3:
                continue
            if name == "summer_sale" and d.month != 7:
                continue
            sends = {"newsletter_weekly": 18000, "abandoned_cart": 260, "summer_sale": 9000,
                     "new_arrivals": 1200}[name]
            sends = round(sends * rng.uniform(0.9, 1.1))
            opens = round(sends * rng.uniform(0.25, 0.45))
            email.append((d, name, sends, opens, round(opens * rng.uniform(0.05, 0.15))))
    for i, row in enumerate(funnel):  # checkouts never below purchases
        d, dev, s, pv, atc, co, p = row
        funnel[i] = (d, dev, s, pv, atc, max(co, p), p)
    return {
        "web_sessions_daily": pd.DataFrame(sessions, columns=[
            "date", "channel_group", "sessions", "engaged_sessions", "new_users"]),
        "web_funnel_daily": pd.DataFrame(funnel, columns=[
            "date", "device", "sessions", "product_views", "add_to_carts", "checkouts", "purchases"]),
        "web_landing_pages_daily": pd.DataFrame(landing, columns=[
            "date", "landing_page", "sessions", "engaged_sessions", "purchases"]),
        "web_site_search_weekly": pd.DataFrame(search, columns=[
            "week_start", "search_term", "searches", "search_exits"]),
        "email_sends_daily": pd.DataFrame(email, columns=["date", "email_campaign", "sends", "opens", "clicks"]),
    }


def build_tables(seed: int = SEED) -> dict[str, pd.DataFrame]:
    rng = random.Random(seed)
    products = pd.DataFrame([p[:6] for p in PRODUCTS], columns=[
        "sku", "product_name", "category", "subcategory", "brand", "list_price_gross"])
    campaigns = pd.DataFrame([
        (cid, name, channel, "paused" if cid in PAUSED_FROM else "active", objective, start)
        for cid, name, channel, objective, _, _, _, start in CAMPAIGNS
    ], columns=["campaign_id", "campaign_name", "channel", "status", "objective", "start_date"])

    ads = _ads(rng)
    ads_all = _ads_all_channels(ads)
    sums = ["impressions", "clicks", "cost_eur", "platform_conversions", "platform_conversion_value"]
    v1 = ads_all[ads_all.channel.isin(["google_search", "meta"])]
    ads_v1 = v1.assign(cost=(v1.cost_eur * 100).round().astype("int64"))[["date", "channel", "clicks", "cost"]]
    budget = pd.DataFrame([
        (m, ch, amount) for m in (date(2026, 6, 1), date(2026, 7, 1), date(2026, 8, 1), date(2026, 9, 1))
        for ch, amount in MONTHLY_BUDGET.items()
    ], columns=["month", "channel", "planned_budget_eur"])

    shop = _shop(rng)
    tables = {
        "products": products,
        "campaigns": campaigns,
        **ads,
        "ads_all_channels_daily": ads_all,
        "ads_all_channels_weekly": _roll(ads_all, "week_start", _week, ["channel"], sums),
        "ads_all_channels_monthly": _roll(ads_all, "month", _month, ["channel"], sums),
        "ads_all_channels_daily_v1": ads_v1.reset_index(drop=True),
        "marketing_budget_monthly": budget,
        **shop,
        **_marketplaces(rng),
    }
    tables.update(_web(rng, ads_all, shop["web_conversions_last_click_daily"]))
    _enrich(tables, random.Random(seed + 1))
    return tables


def _ratio(a: pd.Series, b: pd.Series, digits: int = 4) -> pd.Series:
    return (a / b.where(b != 0)).fillna(0.0).round(digits)


def _noise(rng: random.Random, n: int, lo: float, hi: float) -> list[float]:
    return [rng.uniform(lo, hi) for _ in range(n)]


def _enrich(t: dict[str, pd.DataFrame], rng: random.Random) -> None:
    """The columns real reports carry besides the ones a question usually needs.

    Many of them are precomputed per-row ratios (CTR, CPC, ACoS, frequency,
    engagement rate). They are right on their row and wrong when averaged or
    summed over rows — which is exactly how a real report invites a plausible
    wrong number. A separate random stream, so the base figures above stay
    the same whatever is added here.
    """
    names = {c[0]: c[1] for c in CAMPAIGNS}
    status = {c[0]: ("paused" if c[0] in PAUSED_FROM else "active") for c in CAMPAIGNS}
    prod = {p[0]: p for p in PRODUCTS}

    gs = t["ads_google_search_campaign_daily"]
    n = len(gs)
    gs["campaign_name"] = gs.campaign_id.map(names)
    gs["ctr"] = _ratio(gs.clicks, gs.impressions)
    gs["average_cpc"] = _ratio(gs.cost_micros / 1e6, gs.clicks, 2)
    gs["search_impression_share"] = [round(rng.uniform(0.35, 0.92), 4) for _ in range(n)]
    gs["search_top_impression_share"] = (gs.search_impression_share * _noise(rng, n, 0.55, 0.85)).round(4)
    gs["search_lost_is_budget"] = [round(rng.uniform(0.0, 0.25), 4) for _ in range(n)]
    gs["search_lost_is_rank"] = (1 - gs.search_impression_share - gs.search_lost_is_budget).clip(lower=0).round(4)
    gs["all_conversions"] = (gs.conversions * _noise(rng, n, 1.05, 1.35)).round(2)
    gs["all_conversions_value"] = (gs.conversion_value * _noise(rng, n, 1.05, 1.3)).round(2)
    gs["view_through_conversions"] = [rng.randint(0, 3) for _ in range(n)]
    gs["cost_per_conversion"] = _ratio(gs.cost_micros / 1e6, gs.conversions, 2)
    gs["conversion_rate"] = _ratio(gs.conversions, gs.clicks)

    sh = t["ads_google_shopping_product_daily"]
    n = len(sh)
    sh["campaign_name"] = sh.campaign_id.map(names)
    sh["product_title"] = sh.sku.map(lambda s: prod[s][1])
    sh["product_brand"] = sh.sku.map(lambda s: prod[s][4])
    sh["product_category_l1"] = sh.sku.map(lambda s: prod[s][2])
    sh["ctr"] = _ratio(sh.clicks, sh.impressions)
    sh["average_cpc"] = _ratio(sh.cost_micros / 1e6, sh.clicks, 2)
    sh["benchmark_cpc"] = (sh.average_cpc * _noise(rng, n, 0.8, 1.25)).round(2)
    sh["search_impression_share"] = [round(rng.uniform(0.2, 0.8), 4) for _ in range(n)]
    sh["all_conversions"] = (sh.conversions * _noise(rng, n, 1.05, 1.3)).round(2)
    sh["all_conversions_value"] = (sh.conversion_value * _noise(rng, n, 1.05, 1.3)).round(2)

    me = t["ads_meta_campaign_daily"]
    n = len(me)
    me["campaign_name"] = me.campaign_id.map(names)
    me["frequency"] = _ratio(me.impressions, me.reach, 2)
    me["cpm"] = _ratio(me.spend * 1000, me.impressions, 2)
    me["link_ctr"] = _ratio(me.link_clicks, me.impressions)
    me["landing_page_views"] = (me.link_clicks * pd.Series(_noise(rng, n, 0.6, 0.85))).round().astype("int64")
    me["add_to_cart"] = (me.landing_page_views * pd.Series(_noise(rng, n, 0.06, 0.12))).round().astype("int64")
    me["initiate_checkout"] = (me.add_to_cart * pd.Series(_noise(rng, n, 0.35, 0.6))).round().astype("int64")
    me["purchases_1d_click"] = (me.purchases * pd.Series(_noise(rng, n, 0.45, 0.7))).round().astype("int64")
    me["purchase_value_1d_click"] = _ratio(me.purchase_value * me.purchases_1d_click, me.purchases, 2)
    me["cost_per_purchase"] = _ratio(me.spend, me.purchases, 2)
    me["video_3s_views"] = (me.impressions * pd.Series(_noise(rng, n, 0.08, 0.2))).round().astype("int64")
    me["thruplays"] = (me.video_3s_views * pd.Series(_noise(rng, n, 0.2, 0.4))).round().astype("int64")

    ms = t["ads_microsoft_campaign_daily"]
    n = len(ms)
    ms["campaign_name"] = ms.campaign_id.map(names)
    ms["ctr"] = _ratio(ms.clicks, ms.impressions)
    ms["average_cpc"] = _ratio(ms.spend, ms.clicks, 2)
    ms["impression_share"] = [round(rng.uniform(0.3, 0.85), 4) for _ in range(n)]
    ms["all_conversions"] = (ms.conversions * _noise(rng, n, 1.05, 1.3)).round(2)
    ms["assists"] = [rng.randint(0, 6) for _ in range(n)]
    ms["return_on_ad_spend"] = _ratio(ms.revenue, ms.spend, 2)

    am = t["ads_amazon_sp_campaign_daily"]
    n = len(am)
    am["campaign_name"] = am.campaign_id.map(names)
    am["campaign_status"] = am.campaign_id.map(status)
    am["daily_budget"] = am.campaign_id.map({c[0]: float(c[4]) for c in CAMPAIGNS})
    am["ctr"] = _ratio(am.clicks, am.impressions)
    am["cpc"] = _ratio(am.cost, am.clicks, 2)
    am["acos_14d"] = _ratio(am.cost, am.attributed_sales_14d)
    am["roas_14d"] = _ratio(am.attributed_sales_14d, am.cost, 2)
    am["units_sold_14d"] = (am.attributed_orders_14d * pd.Series(_noise(rng, n, 1.0, 1.3))).round().astype("int64")
    am["sales_same_sku_14d"] = (am.attributed_sales_14d * pd.Series(_noise(rng, n, 0.7, 0.9))).round(2)
    am["sales_other_sku_14d"] = (am.attributed_sales_14d - am.sales_same_sku_14d).round(2)
    am["new_to_brand_orders_14d"] = (am.attributed_orders_14d * pd.Series(_noise(rng, n, 0.3, 0.6))).round().astype("int64")
    am["top_of_search_impression_share"] = [round(rng.uniform(0.05, 0.4), 4) for _ in range(n)]

    for name in ("ads_all_channels_daily", "ads_all_channels_weekly", "ads_all_channels_monthly"):
        df = t[name]
        df["ctr"] = _ratio(df.clicks, df.impressions)
        df["cpc"] = _ratio(df.cost_eur, df.clicks, 2)
        df["platform_roas"] = _ratio(df.platform_conversion_value, df.cost_eur, 2)

    orders = t["shop_orders"]
    n = len(orders)
    items = t["shop_order_items"].groupby("order_id").units.sum()
    orders["items_count"] = orders.order_id.map(items).astype("int64")
    orders["payment_method"] = [rng.choice(["paypal"] * 4 + ["credit_card"] * 3 + ["invoice"] * 2 + ["apple_pay"])
                                for _ in range(n)]
    orders["device"] = [rng.choice(["mobile"] * 6 + ["desktop"] * 3 + ["tablet"]) for _ in range(n)]
    orders["coupon_code"] = [rng.choice(["", "", "", "", "", "", "WELCOME10", "SUMMER20", "NEWSLETTER5"])
                             for _ in range(n)]
    country = dict(zip(t["customers"].customer_id, t["customers"].country))
    orders["shipping_country"] = orders.customer_id.map(country)

    done = orders[orders.order_status == "completed"]
    per_day = done.groupby("order_date")
    cancelled = orders[orders.order_status == "cancelled"].groupby("order_date").size()
    for name, key, fn in (("shop_sales_daily", "date", lambda d: d),
                          ("shop_sales_weekly", "week_start", _week),
                          ("shop_sales_monthly", "month", _month)):
        df = t[name]
        disc = per_day.discount_gross.sum().groupby(lambda d: fn(d)).sum()
        canc = cancelled.groupby(lambda d: fn(d)).sum()
        df["discount_gross"] = df[key].map(disc).fillna(0).round(2)
        df["cancelled_orders"] = df[key].map(canc).fillna(0).astype("int64")
        df["returning_customer_orders"] = df.orders - df.new_customer_orders
        df["avg_order_value_net"] = _ratio(df.revenue_net, df.orders, 2)

    stats = done.groupby("customer_id").agg(orders_count=("order_id", "count"),
                                            lifetime_revenue_net=("revenue_net", "sum"))
    cu = t["customers"]
    cu["orders_count"] = cu.customer_id.map(stats.orders_count).fillna(0).astype("int64")
    cu["lifetime_revenue_net"] = cu.customer_id.map(stats.lifetime_revenue_net).fillna(0).round(2)
    cu["acquisition_channel_group"] = [rng.choice(list(CHANNEL_GROUPS)) for _ in range(len(cu))]

    p = t["products"]
    p["cost_price_net"] = (p.list_price_gross / (1 + VAT) * pd.Series(_noise(rng, len(p), 0.38, 0.52))).round(2)
    p["ean"] = [f"40{rng.randint(10**10, 10**11 - 1)}" for _ in range(len(p))]
    p["color"] = [rng.choice(["black", "blue", "green", "red", "grey", "orange"]) for _ in range(len(p))]
    p["weight_grams"] = [rng.randint(80, 2400) for _ in range(len(p))]
    p["season"] = [rng.choice(["all-season", "summer", "winter"]) for _ in range(len(p))]
    p["is_active"] = True

    c = t["campaigns"]
    c["daily_budget_eur"] = c.campaign_id.map({x[0]: float(x[4]) for x in CAMPAIGNS})
    c["bidding_strategy"] = c.channel.map({"google_search": "target_roas", "google_shopping": "maximize_conversion_value",
                                           "meta": "lowest_cost", "microsoft": "enhanced_cpc",
                                           "amazon_sp": "dynamic_bids_down_only"})
    c["target_roas"] = c.channel.map({"google_search": 4.0, "google_shopping": 3.5}).fillna(0.0)

    az = t["marketplace_amazon_sales_daily"]
    n = len(az)
    az["units_ordered_b2b"] = (az.units_ordered * pd.Series(_noise(rng, n, 0.0, 0.12))).round().astype("int64")
    az["ordered_product_sales_b2b"] = _ratio(az.ordered_product_sales * az.units_ordered_b2b, az.units_ordered, 2)
    az["unit_session_percentage"] = _ratio(az.units_ordered, az.sessions)
    az["mobile_sessions"] = (az.sessions * pd.Series(_noise(rng, n, 0.55, 0.7))).round().astype("int64")
    az["browser_sessions"] = az.sessions - az.mobile_sessions

    ws = t["web_sessions_daily"]
    n = len(ws)
    ws["returning_users"] = (ws.sessions * pd.Series(_noise(rng, n, 0.2, 0.4))).round().astype("int64")
    ws["engagement_rate"] = _ratio(ws.engaged_sessions, ws.sessions)
    ws["avg_session_duration_sec"] = [round(rng.uniform(60, 260), 1) for _ in range(n)]
    ws["pages_per_session"] = [round(rng.uniform(1.8, 5.5), 2) for _ in range(n)]

    fu = t["web_funnel_daily"]
    fu["cart_to_purchase_rate"] = _ratio(fu.purchases, fu.add_to_carts)

    lp = t["web_landing_pages_daily"]
    n = len(lp)
    lp["engagement_rate"] = _ratio(lp.engaged_sessions, lp.sessions)
    lp["avg_engagement_time_sec"] = [round(rng.uniform(20, 180), 1) for _ in range(n)]
    lp["purchase_revenue_gross"] = (lp.purchases * pd.Series(_noise(rng, n, 70, 140))).round(2)

    # Second pass: the long tail of report columns nobody asks about often.
    n = len(gs)
    gs["absolute_top_impression_share"] = (gs.search_top_impression_share * _noise(rng, n, 0.4, 0.7)).round(4)
    gs["average_cpm"] = _ratio(gs.cost_micros / 1e3, gs.impressions, 2)
    gs["cross_device_conversions"] = (gs.conversions * _noise(rng, n, 0.05, 0.15)).round(2)
    gs["new_customer_conversions"] = (gs.conversions * _noise(rng, n, 0.3, 0.6)).round(2)
    gs["conversion_value_per_cost"] = _ratio(gs.conversion_value, gs.cost_micros / 1e6, 2)

    n = len(sh)
    sh["product_type_l2"] = sh.sku.map(lambda s: prod[s][3])
    sh["product_price"] = sh.sku.map(lambda s: prod[s][5])
    sh["click_share"] = [round(rng.uniform(0.1, 0.6), 4) for _ in range(n)]
    sh["conversion_value_per_cost"] = _ratio(sh.conversion_value, sh.cost_micros / 1e6, 2)

    n = len(me)
    me["unique_link_clicks"] = (me.link_clicks * pd.Series(_noise(rng, n, 0.82, 0.95))).round().astype("int64")
    me["outbound_clicks"] = (me.link_clicks * pd.Series(_noise(rng, n, 0.9, 1.0))).round().astype("int64")
    me["post_engagement"] = (me.impressions * pd.Series(_noise(rng, n, 0.01, 0.04))).round().astype("int64")
    me["cost_per_landing_page_view"] = _ratio(me.spend, me.landing_page_views, 2)
    me["website_purchase_roas"] = _ratio(me.purchase_value, me.spend, 2)

    n = len(ms)
    ms["top_impression_share"] = (ms.impression_share * pd.Series(_noise(rng, n, 0.5, 0.8))).round(4)
    ms["conversion_rate"] = _ratio(ms.conversions, ms.clicks)
    ms["cost_per_conversion"] = _ratio(ms.spend, ms.conversions, 2)
    ms["view_through_conversions"] = [rng.randint(0, 2) for _ in range(n)]

    n = len(am)
    am["units_sold_7d"] = (am.units_sold_14d * pd.Series(_noise(rng, n, 0.78, 0.92))).round().astype("int64")
    am["sales_same_sku_7d"] = (am.attributed_sales_7d * pd.Series(_noise(rng, n, 0.7, 0.9))).round(2)
    am["new_to_brand_sales_14d"] = _ratio(am.attributed_sales_14d * am.new_to_brand_orders_14d,
                                          am.attributed_orders_14d, 2)
    am["detail_page_views_14d"] = (am.clicks * pd.Series(_noise(rng, n, 0.7, 1.1))).round().astype("int64")

    n = len(az)
    az["units_refunded"] = (az.units_ordered * pd.Series(_noise(rng, n, 0.0, 0.08))).round().astype("int64")
    az["total_order_items"] = (az.units_ordered * pd.Series(_noise(rng, n, 0.85, 1.0))).round().astype("int64")
    az["average_selling_price"] = _ratio(az.ordered_product_sales, az.units_ordered, 2)

    n = len(orders)
    source = {"paid_search": ("google", "cpc"), "paid_shopping": ("google", "shopping"),
              "paid_social": ("meta", "paid_social"), "organic_search": ("google", "organic"),
              "direct": ("(direct)", "(none)"), "email": ("newsletter", "email"), "referral": ("partner", "referral")}
    picked = [source[rng.choice(list(source))] for _ in range(n)]
    orders["utm_source"] = [s for s, _ in picked]
    orders["utm_medium"] = [m for _, m in picked]
    orders["delivery_days"] = [rng.choice([1, 2, 2, 2, 3, 3, 4]) for _ in range(n)]

    n = len(ws)
    ws["bounce_rate"] = (1 - ws.engagement_rate).round(4)
    ws["sessions_with_site_search"] = (ws.sessions * pd.Series(_noise(rng, n, 0.04, 0.12))).round().astype("int64")


_DATE_COLUMNS = {"date", "order_date", "return_date", "first_order_date", "week_start", "month", "start_date"}
_BIGINT_COLUMNS = {"cost_micros", "cost"}


def _sql_type(name: str, series: pd.Series) -> str:
    if name in _DATE_COLUMNS:
        return "DATE"
    if series.dtype.kind == "b":
        return "BOOLEAN"
    if series.dtype.kind in "iu":
        return "BIGINT" if name in _BIGINT_COLUMNS else "INTEGER"
    if series.dtype.kind == "f":
        return "DOUBLE"
    return "VARCHAR"


def write_duckdb(path: str | Path, seed: int = SEED) -> Path:
    """Write the large demo tables to a fresh DuckDB file and return its path."""
    import duckdb

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    con = duckdb.connect(str(path))
    try:
        for name, df in build_tables(seed).items():
            con.register("_df", df)
            casts = ", ".join(f"CAST({c} AS {_sql_type(c, df[c])}) AS {c}" for c in df.columns)
            con.execute(f"CREATE TABLE {name} AS SELECT {casts} FROM _df")
            con.unregister("_df")
            con.execute(
                f"COMMENT ON TABLE {name} IS 'GENERATED DEMO DATA (large, seed {seed}) - not a real business'"
            )
    finally:
        con.close()
    return path
