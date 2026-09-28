import re

import pytest

from data_chat.catalog import load_catalog, render_catalog
from data_chat.context import DEFAULT_CATALOG


def test_demo_catalog_loads():
    catalog = load_catalog(DEFAULT_CATALOG)
    assert set(catalog.views) == {
        "ads_campaign_daily", "campaigns", "products", "shop_orders_daily", "web_sessions_daily",
    }


def test_every_column_has_a_description():
    """The Brain's rule: description on every column, definition where misuse is plausible."""
    for view in load_catalog(DEFAULT_CATALOG).views.values():
        assert view.description, view.name
        for col in view.columns:
            assert col.description, f"{view.name}.{col.name}"


def test_catalog_describes_exactly_the_demo_tables(backend):
    """A described column the database lacks would send the model to a column that does not exist."""
    catalog = load_catalog(DEFAULT_CATALOG)
    live = {t: {c.name for c in cols} for t, cols in backend.list_columns().items()}
    assert set(catalog.views) == set(live)
    for name, view in catalog.views.items():
        assert {c.name for c in view.columns} == live[name], name


def test_render_puts_definitions_next_to_columns():
    text = render_catalog(load_catalog(DEFAULT_CATALOG))
    assert re.search(r"- cost \(BIGINT\): Ad spend in euro cents\. — Divide by 100", text)
    assert "| ads_campaign_daily | campaigns | `campaign_id` |" in text
    assert "## Important Notes" in text


def test_render_qualifies_tables_in_query_patterns():
    text = render_catalog(load_catalog(DEFAULT_CATALOG), qualify=lambda t: f"`p.d.{t}`")
    assert "FROM `p.d.ads_campaign_daily` a" in text
    assert "{ads_campaign_daily}" not in text


def test_a_catalog_without_views_fails_loud(tmp_path):
    path = tmp_path / "empty.yaml"
    path.write_text("join_notes: []\n")
    with pytest.raises(ValueError, match="views"):
        load_catalog(path)
