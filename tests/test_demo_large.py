"""The large demo dataset: 35 tables, its catalog, and the promise that every
aggregate is computed from the rows below it — so a question has one answer."""

from __future__ import annotations

import pytest

from data_chat.backend import DuckDbBackend
from data_chat.catalog import load_catalog
from data_chat.datasets import DATASETS, get_dataset
from data_chat.demo_large import build_tables, write_duckdb

LARGE = get_dataset("demo-large")


@pytest.fixture(scope="module")
def large_db(tmp_path_factory):
    return write_duckdb(tmp_path_factory.mktemp("large") / "demo-large.duckdb")


@pytest.fixture(scope="module")
def large(large_db):
    return DuckDbBackend(large_db)


def _one(backend, sql):
    return backend.execute(sql).iloc[0, 0]


def test_the_original_demo_is_still_the_default():
    demo = get_dataset("demo")
    assert demo.db.name == "demo.duckdb" and demo.catalog.name == "data_catalog.yaml"
    assert demo.questions.as_posix().endswith("eval/questions.yaml")
    assert set(DATASETS) == {"demo", "demo-large"}


def test_an_unknown_dataset_is_named():
    with pytest.raises(ValueError, match="demo-large"):
        get_dataset("huge")


def test_it_is_large_enough_to_matter(large):
    assert 30 <= len(large.list_columns()) <= 40


def test_the_catalog_describes_exactly_the_tables_and_columns(large):
    catalog = load_catalog(LARGE.catalog)
    live = {t: {c.name for c in cols} for t, cols in large.list_columns().items()}
    assert set(catalog.views) == set(live)
    for name, view in catalog.views.items():
        assert {c.name for c in view.columns} == live[name], name


def test_every_view_has_what_the_selection_card_reads():
    """The selection step sees description, grain, use_for and typical
    questions — a view without them could only be picked by its name."""
    for view in load_catalog(LARGE.catalog).views.values():
        assert view.description and view.grain and view.use_for and view.typical_questions, view.name
        for col in view.columns:
            assert col.description, f"{view.name}.{col.name}"


def test_deprecated_views_say_so_where_both_steps_read():
    views = load_catalog(LARGE.catalog).views
    deprecated = {n for n, v in views.items() if v.description.startswith("DEPRECATED")}
    assert deprecated == {"shop_sales_daily_v1", "ads_all_channels_daily_v1"}
    for name in deprecated:
        assert views[name].important.startswith("DEPRECATED"), name


def test_the_data_is_deterministic():
    a, b = build_tables(), build_tables()
    assert a.keys() == b.keys() and all(a[k].equals(b[k]) for k in a)


@pytest.mark.parametrize("table,key", [("shop_sales_weekly", "week_start"), ("shop_sales_monthly", "month")])
def test_shop_aggregates_are_the_daily_figures_summed(large, table, key):
    for col in ("orders", "units", "revenue_gross", "revenue_net"):
        daily = _one(large, f"SELECT SUM({col}) FROM shop_sales_daily")
        assert _one(large, f"SELECT SUM({col}) FROM {table}") == pytest.approx(daily, rel=1e-9), col


def test_shop_sales_daily_is_the_completed_orders(large):
    assert _one(large, "SELECT SUM(orders) FROM shop_sales_daily") == _one(
        large, "SELECT COUNT(*) FROM shop_orders WHERE order_status = 'completed'")
    assert _one(large, "SELECT SUM(orders) FROM shop_sales_daily_v1") == _one(large, "SELECT COUNT(*) FROM shop_orders")


@pytest.mark.parametrize("table", ["ads_all_channels_weekly", "ads_all_channels_monthly"])
def test_ad_aggregates_are_the_daily_figures_summed(large, table):
    daily = _one(large, "SELECT SUM(cost_eur) FROM ads_all_channels_daily")
    assert _one(large, f"SELECT SUM(cost_eur) FROM {table}") == pytest.approx(daily, rel=1e-6)


def test_the_cross_channel_table_is_the_channel_tables_in_euros(large):
    per_channel = _one(large, """
        SELECT (SELECT SUM(cost_micros) FROM ads_google_search_campaign_daily) / 1e6
             + (SELECT SUM(cost_micros) FROM ads_google_shopping_product_daily) / 1e6
             + (SELECT SUM(spend) FROM ads_meta_campaign_daily)
             + (SELECT SUM(spend) FROM ads_microsoft_campaign_daily)
             + (SELECT SUM(cost) FROM ads_amazon_sp_campaign_daily)""")
    assert _one(large, "SELECT SUM(cost_eur) FROM ads_all_channels_daily") == pytest.approx(per_channel, rel=1e-6)


def test_the_three_attribution_models_agree_on_the_total_and_not_per_channel(large):
    totals = [
        _one(large, f"SELECT SUM(purchases) FROM web_conversions_{m}_daily")
        for m in ("last_click", "first_click", "data_driven")
    ]
    assert totals[0] == pytest.approx(totals[1]) == pytest.approx(totals[2], abs=1.0)
    assert totals[0] == _one(large, "SELECT SUM(orders) FROM shop_sales_daily")
    split = large.execute("""
        SELECT l.channel_group, SUM(l.purchases) AS last, SUM(f.purchases) AS first
        FROM web_conversions_last_click_daily l
        JOIN web_conversions_first_click_daily f USING (date, channel_group)
        GROUP BY 1""")
    assert (split["last"] != split["first"]).any()


def test_the_funnel_adds_up_to_the_shop_orders(large):
    assert _one(large, "SELECT SUM(purchases) FROM web_funnel_daily") == _one(
        large, "SELECT SUM(orders) FROM shop_sales_daily")


def test_amazon_seven_day_attribution_is_inside_the_fourteen_day(large):
    assert _one(large, """SELECT COUNT(*) FROM ads_amazon_sp_campaign_daily
                          WHERE attributed_sales_7d > attributed_sales_14d
                             OR attributed_orders_7d > attributed_orders_14d""") == 0


def test_otto_is_net_in_its_own_table_and_gross_in_the_combined_one(large):
    net = _one(large, "SELECT SUM(revenue_net) FROM marketplace_otto_sales_daily")
    gross = _one(large, "SELECT SUM(revenue_gross) FROM marketplace_sales_daily WHERE marketplace = 'otto'")
    assert gross == pytest.approx(net * 1.19, rel=1e-4)


def test_revenue_after_returns_starts_from_the_same_net_revenue(large):
    assert _one(large, "SELECT SUM(revenue_net) FROM shop_sales_net_of_returns_daily") == pytest.approx(
        _one(large, "SELECT SUM(revenue_net) FROM shop_sales_daily"))
    assert _one(large, "SELECT SUM(refunds_net) FROM shop_sales_net_of_returns_daily") > 0


def test_the_cli_prints_the_large_prompt_without_an_api_key(large_db, capsys):
    from data_chat.cli import main

    main(["--dataset", "demo-large", "--db", str(large_db), "prompt", "--stage", "catalog"])
    out = capsys.readouterr().out
    for name in load_catalog(LARGE.catalog).views:
        assert f"### {name}" in out


def test_an_order_has_each_product_on_one_line_only(large):
    """Returns join items on order_id AND sku; a repeated sku would double them."""
    assert _one(large, """SELECT COUNT(*) FROM (SELECT order_id, sku FROM shop_order_items
                          GROUP BY 1, 2 HAVING COUNT(*) > 1)""") == 0


def test_every_query_pattern_runs(large):
    from data_chat.catalog import load_catalog

    catalog = load_catalog(LARGE.catalog)
    for ex in catalog.query_examples:
        sql = ex["sql"]
        for table in catalog.views:
            sql = sql.replace(f"{{{table}}}", table)
        assert len(large.execute(sql)) > 0, ex["name"]
