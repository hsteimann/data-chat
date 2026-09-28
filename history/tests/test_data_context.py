"""Tests for the data_context Reasoning API.

Covers Phase 1a per ``docs/plan-data-context-api.md``:

- Pydantic typing of every public return.
- Snapshot for ``get_kpi("acos")``.
- Process-level cache + ``reload()`` behaviour.
- Fail-loud on missing catalog.
- Filter chain monotonicity for ``list_views``.
- Scope semantics for ``get_kpis``.
- Empty filter result vs. unknown scope/client (empty list/dict vs raise).
"""

from __future__ import annotations

import pytest

from adp import data_context
from adp.data_context import (
    SCOPES,
    get_ai_warnings,
    get_cross_source_warnings,
    get_join_notes,
    get_join_relationships,
    get_kpi,
    get_kpis,
    get_query_examples,
    get_view_metadata,
    list_views,
    reload,
)
from adp.models.data_context import (
    CrossSourceWarning,
    JoinRelationship,
    KpiDefinition,
    QueryExample,
    ViewMetadata,
)


@pytest.fixture(autouse=True)
def _clean_cache():
    """Make sure each test sees a freshly-loaded bundle."""
    reload()
    yield
    reload()


# ---------------------------------------------------------------------------
# Pydantic typing
# ---------------------------------------------------------------------------


class TestPydanticTyping:
    def test_list_views_returns_list_of_strings(self):
        names = list_views()
        assert isinstance(names, list)
        assert names, "registry should expose at least one view"
        assert all(isinstance(n, str) for n in names)

    def test_get_view_metadata_returns_model(self):
        meta = get_view_metadata("v_ads_summary_daily")
        assert isinstance(meta, ViewMetadata)
        assert meta.name == "v_ads_summary_daily"
        assert meta.source == "ads"
        assert meta.is_raw_table is False
        assert meta.columns and meta.columns[0].name == "date"

    def test_get_view_metadata_raw_table_flag(self):
        meta = get_view_metadata("rf_products")
        assert isinstance(meta, ViewMetadata)
        assert meta.is_raw_table is True
        assert meta.source == "rainforest"

    def test_get_kpi_returns_model(self):
        kpi = get_kpi("acos")
        assert isinstance(kpi, KpiDefinition)

    def test_get_kpis_returns_dict_of_models(self):
        kpis = get_kpis()
        assert isinstance(kpis, dict)
        assert kpis
        for key, kpi in kpis.items():
            assert isinstance(key, str)
            assert isinstance(kpi, KpiDefinition)
            assert kpi.key == key

    def test_get_cross_source_warnings_returns_list_of_models(self):
        warnings = get_cross_source_warnings()
        assert isinstance(warnings, list)
        assert warnings
        for w in warnings:
            assert isinstance(w, CrossSourceWarning)


# ---------------------------------------------------------------------------
# Snapshot for the canonical KPI
# ---------------------------------------------------------------------------


class TestKpiSnapshot:
    def test_acos_snapshot(self):
        acos = get_kpi("acos")
        assert acos.key == "acos"
        assert acos.name == "Advertising Cost of Sales"
        assert acos.formula == "cost / sales * 100"
        assert acos.unit == "percentage"
        assert acos.direction == "lower_is_better"
        assert acos.typical_range == (5.0, 50.0)
        assert acos.components is not None
        assert "cost" in acos.components
        assert "sales" in acos.components
        assert acos.interpretation
        assert acos.warning


# ---------------------------------------------------------------------------
# Caching + reload()
# ---------------------------------------------------------------------------


class TestCaching:
    def test_second_call_is_cached(self):
        first = data_context._bundle()
        second = data_context._bundle()
        # Same object identity → cache hit.
        assert first is second

    def test_reload_invalidates(self):
        first = data_context._bundle()
        reload()
        second = data_context._bundle()
        assert first is not second


# ---------------------------------------------------------------------------
# Fail-loud
# ---------------------------------------------------------------------------


class TestFailLoud:
    def test_missing_catalog_raises(self, monkeypatch, tmp_path):
        # Point the catalog loader at a non-existent file by patching settings.
        # Loader reads ``settings.data_catalog_file``; redirect it to a missing path.
        from adp import data_context as dc
        from adp.data_context import _catalog
        from adp.config import settings as adp_settings

        missing = tmp_path / "does_not_exist.yaml"

        # ``settings.data_catalog_file`` is a property; intercept the loader's
        # default-resolution by patching the module-level lookup.
        monkeypatch.setattr(
            adp_settings.__class__,
            "data_catalog_file",
            property(lambda self: missing),
        )

        dc.reload()
        with pytest.raises(FileNotFoundError, match="Data catalog file not found"):
            dc.list_views()

        # Also direct-loader path.
        with pytest.raises(FileNotFoundError):
            _catalog.load_views()

    def test_unknown_kpi_raises(self):
        with pytest.raises(KeyError, match="Unknown KPI"):
            get_kpi("does_not_exist_kpi")

    def test_unknown_view_raises(self):
        with pytest.raises(KeyError, match="Unknown view"):
            get_view_metadata("does_not_exist_view")

    def test_unknown_scope_raises(self):
        with pytest.raises(ValueError, match="Unknown scope"):
            list_views(scope="bogus")
        with pytest.raises(ValueError, match="Unknown scope"):
            get_kpis(scope="bogus")
        with pytest.raises(ValueError, match="Unknown scope"):
            get_cross_source_warnings(scope="bogus")

    def test_unknown_client_raises(self):
        with pytest.raises(KeyError, match="Unknown client"):
            list_views(client="not_a_real_client")
        with pytest.raises(KeyError):
            get_kpis(client="not_a_real_client")
        with pytest.raises(KeyError):
            get_cross_source_warnings(client="not_a_real_client")


# ---------------------------------------------------------------------------
# Filter chain — monotonicity
# ---------------------------------------------------------------------------


class TestFilterChain:
    def test_list_views_filter_chain(self):
        all_views = set(list_views())
        ads_views = set(list_views(scope="ads"))
        client_07_ads = set(list_views(client="client_07", scope="ads"))

        # ⊂ ⊂
        assert client_07_ads <= ads_views
        assert ads_views <= all_views

        # The ads slice must be non-empty (client_07 has amazon_ads).
        assert client_07_ads

    def test_list_views_client_alone_subset_of_all(self):
        all_views = set(list_views())
        kfrau = set(list_views(client="client_07"))
        assert kfrau <= all_views
        # client_07 has ads + sc + rainforest, so it should see the v_ads_*
        # views as well as rf_/pma_ entries (system views excluded by filter).
        assert "v_ads_summary_daily" in kfrau
        assert "rf_products" in kfrau
        assert "pma_orders" in kfrau

    def test_system_views_excluded_when_filter_active(self):
        # data_chat_feedback_summary should appear unfiltered, but never under
        # a scope or client filter.
        all_views = set(list_views())
        assert "data_chat_feedback_summary" in all_views
        assert "data_chat_feedback_summary" not in set(list_views(scope="ads"))
        assert "data_chat_feedback_summary" not in set(list_views(client="client_07"))

    def test_scope_excludes_other_scopes(self):
        rf_views = set(list_views(scope="rainforest"))
        sc_views = set(list_views(scope="sc"))
        ads_views = set(list_views(scope="ads"))

        # No leakage.
        assert rf_views.isdisjoint(ads_views)
        assert rf_views.isdisjoint(sc_views)
        assert ads_views.isdisjoint(sc_views)


# ---------------------------------------------------------------------------
# KPI scope semantics
# ---------------------------------------------------------------------------


class TestKpiScope:
    def test_ads_scope_includes_acos_and_roas(self):
        ads_kpis = get_kpis(scope="ads")
        assert "acos" in ads_kpis
        assert "roas" in ads_kpis

    def test_ads_scope_excludes_rainforest_only_kpis(self):
        ads_kpis = get_kpis(scope="ads")
        assert "buybox_win_rate" not in ads_kpis
        assert "listing_quality_score" not in ads_kpis

    def test_rainforest_scope_includes_buybox(self):
        rf_kpis = get_kpis(scope="rainforest")
        assert "buybox_win_rate" in rf_kpis
        assert "listing_quality_score" in rf_kpis

    def test_client_filter_drops_unsupported_kpis(self):
        # client_12 has only amazon_ads + rainforest, no PMA → no tacos
        # (tacos requires pma_sales_traffic_by_date).
        kfrau_kpis = get_kpis(client="client_07")
        ns_kpis = get_kpis(client="client_12")
        assert "tacos" in kfrau_kpis  # has PMA
        assert "tacos" not in ns_kpis  # no PMA


# ---------------------------------------------------------------------------
# Cross-source warnings
# ---------------------------------------------------------------------------


class TestCrossSourceWarnings:
    def test_unfiltered_returns_all(self):
        warnings = get_cross_source_warnings()
        ids = {w.id for w in warnings}
        # Sanity-check a couple of known IDs from data_registry.yaml.
        assert "ads_vs_pma_sales" in ids
        assert "buybox_vs_ads_spend" in ids

    def test_client_filter_drops_warnings_with_missing_sources(self):
        # client_12 has no PMA → ads_vs_pma_sales should drop out.
        ns_warnings = {w.id for w in get_cross_source_warnings(client="client_12")}
        assert "ads_vs_pma_sales" not in ns_warnings
        # But the rainforest-vs-ads warnings stay (client_12 has both).
        assert "buybox_vs_ads_spend" in ns_warnings

    def test_scope_filter_keeps_warnings_touching_scope(self):
        ads_warnings = {w.id for w in get_cross_source_warnings(scope="ads")}
        # Every cross-source warning in the registry today touches ads in some
        # way; the filter should preserve all of them.
        assert "ads_vs_pma_sales" in ads_warnings
        assert "buybox_vs_ads_spend" in ads_warnings


# ---------------------------------------------------------------------------
# Empty-but-valid vs unknown
# ---------------------------------------------------------------------------


class TestEmptyResults:
    def test_client_10_has_no_rainforest_views(self):
        # client_10 has only amazon_ads → rainforest scope is empty.
        result = list_views(client="client_10", scope="rainforest")
        assert result == []

    def test_kpis_can_be_empty_for_client_scope(self):
        # client_06 has only amazon_ads → rainforest scope yields no KPIs that
        # require rainforest sources.
        result = get_kpis(client="client_06", scope="rainforest")
        # Scope filter requires rainforest sources → buybox_win_rate etc.
        # would qualify, but client_06 doesn't have rainforest sources, so the
        # client filter (requires_sources ⊂ client_sources) drops them.
        assert "buybox_win_rate" not in result
        assert "listing_quality_score" not in result

    def test_warnings_can_be_empty_list(self):
        # A client with only ads (e.g. client_06) plus scope=rainforest has no
        # warnings: cross-source warnings need ≥2 client sources to overlap.
        result = get_cross_source_warnings(client="client_06", scope="rainforest")
        assert isinstance(result, list)
        # No exception even though the result may legitimately be empty.


# ---------------------------------------------------------------------------
# Sanity: SCOPES tuple is the documented set
# ---------------------------------------------------------------------------


def test_scopes_tuple_is_canonical():
    assert SCOPES == ("ads", "rainforest", "sc")


# ---------------------------------------------------------------------------
# JOIN relationships, query examples, AI warnings (Phase 1c additions)
# ---------------------------------------------------------------------------


class TestJoinRelationships:
    def test_returns_list_of_models(self):
        joins = get_join_relationships()
        assert isinstance(joins, list)
        assert joins, "data_catalog.yaml ships with several join_relationships"
        for rel in joins:
            assert isinstance(rel, JoinRelationship)
            assert rel.view_a
            assert rel.view_b
            assert rel.keys

    def test_snapshot_campaign_searchterm_join(self):
        joins = get_join_relationships()
        match = next(
            (
                r
                for r in joins
                if r.view_a == "v_ads_campaign_daily"
                and r.view_b == "v_ads_searchterm_daily"
            ),
            None,
        )
        assert match is not None
        assert "date" in match.keys

    def test_join_notes_are_strings(self):
        notes = get_join_notes()
        assert isinstance(notes, list)
        assert notes
        assert all(isinstance(n, str) for n in notes)


class TestQueryExamples:
    def test_returns_list_of_models(self):
        examples = get_query_examples()
        assert isinstance(examples, list)
        assert examples, "data_catalog.yaml ships with example queries"
        for ex in examples:
            assert isinstance(ex, QueryExample)
            assert ex.name
            assert "SELECT" in ex.sql.upper()

    def test_snapshot_first_example_name(self):
        examples = get_query_examples()
        names = [ex.name for ex in examples]
        assert "Single client query" in names


class TestAiWarnings:
    def test_returns_list_of_strings(self):
        warnings = get_ai_warnings()
        assert isinstance(warnings, list)
        assert warnings
        assert all(isinstance(w, str) for w in warnings)

    def test_snapshot_contains_known_warning(self):
        warnings = get_ai_warnings()
        # ROAS-as-ratio warning is a stable anchor.
        joined = "\n".join(warnings)
        assert "ROAS" in joined
        assert "SAFE_DIVIDE" in joined
