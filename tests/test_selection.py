"""The catalog_selected stage, offline: the selection step, the narrowed
prompt, the fallbacks, the interpretation's view notes and the token record."""

from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace

import pytest

from data_chat.backend import DuckDbBackend
from data_chat.catalog import load_catalog, render_catalog, tables_in
from data_chat.context import selection_setup
from data_chat.datasets import get_dataset
from data_chat.demo_large import write_duckdb
from data_chat.llm import AnthropicLlm, LlmReply, OpenAILlm, ToolInput, Usage
from data_chat.pipeline import SelectionSetup, ask
from data_chat.selection import MIN_VIEWS, card, select_views, selection_prompt

LARGE = get_dataset("demo-large")
PERIOD = dict(start_date=date(2026, 6, 1), end_date=date(2026, 9, 27))


@pytest.fixture(scope="module")
def catalog():
    return load_catalog(LARGE.catalog)


@pytest.fixture(scope="module")
def large(tmp_path_factory):
    return DuckDbBackend(write_duckdb(tmp_path_factory.mktemp("sel") / "demo-large.duckdb"))


class FakeLlm:
    """Scripted replies for both calls, each with a usage, and a record of every call."""

    def __init__(self, *, pick=None, sql=(), answer="It was a good month.", fail=False):
        self.pick, self.sql, self.answer, self.fail = pick, list(sql), answer, fail
        self.calls: list[dict] = []

    def call_tool(self, **kw):
        self.calls.append(kw)
        if self.fail:
            raise RuntimeError("overloaded")
        out = ToolInput({"views": self.pick or []})
        out.usage = Usage(input_tokens=20, output_tokens=12, cache_read_tokens=4000)
        return out

    def complete(self, **kw):
        self.calls.append(kw)
        if kw["phase"] == "sql":
            text = self.sql.pop(0) if len(self.sql) > 1 else self.sql[0]
            return LlmReply(text, "end_turn", Usage(input_tokens=len(kw["system"]) // 4, output_tokens=60))
        return LlmReply(self.answer, "end_turn", Usage(input_tokens=500, output_tokens=40))


def _ask(question, llm, backend, catalog, **kw):
    full = render_catalog(catalog, qualify=backend.qualify)
    return ask(question, llm=llm, model="m", backend=backend, context=full,
               selection=SelectionSetup(catalog=catalog, model="small"), **PERIOD, **kw)


# ── the selection step ─────────────────────────────────────────────────────

def test_a_card_has_names_and_purpose_but_not_the_column_definitions(catalog):
    text = card(catalog.views["ads_google_search_campaign_daily"])
    assert text.startswith("### ads_google_search_campaign_daily")
    assert "Grain:" in text and "Use for:" in text and "cost_micros" in text
    assert "Divide by 1,000,000" not in text  # a definition: the SQL step's business


def test_the_selection_prompt_is_the_same_for_every_question(catalog):
    """So it is cached across questions — only the question is new."""
    llm = FakeLlm(pick=["shop_sales_daily"])
    select_views("Revenue in August?", catalog, llm=llm, model="small")
    select_views("Spend per channel?", catalog, llm=llm, model="small")
    assert llm.calls[0]["system"] == llm.calls[1]["system"] == selection_prompt(catalog)
    assert llm.calls[0]["messages"] != llm.calls[1]["messages"]


def test_the_tool_only_accepts_the_catalogs_view_names(catalog):
    llm = FakeLlm(pick=["shop_sales_daily"])
    select_views("q", catalog, llm=llm, model="small")
    enum = llm.calls[0]["tool"]["input_schema"]["properties"]["views"]["items"]["enum"]
    assert enum == sorted(catalog.views)
    assert llm.calls[0]["phase"] == "select" and llm.calls[0]["model"] == "small"


def test_an_invented_name_is_dropped_and_nothing_left_means_the_full_catalog(catalog):
    sel = select_views("q", catalog, llm=FakeLlm(pick=["revenue_table"]), model="small")
    assert sel.views is None and sel.skipped == "nothing selected"


def test_a_failing_selection_is_no_selection_not_a_failed_question(catalog):
    sel = select_views("q", catalog, llm=FakeLlm(fail=True), model="small")
    assert sel.views is None and sel.skipped.startswith("selection failed: overloaded")


def test_a_small_catalog_is_not_narrowed():
    small = load_catalog(get_dataset("demo").catalog)
    assert len(small.views) < MIN_VIEWS
    llm = FakeLlm(pick=["campaigns"])
    sel = select_views("q", small, llm=llm, model="small")
    assert sel.views is None and sel.skipped == "small catalog" and llm.calls == []


def test_a_follow_up_carries_the_previous_question(catalog):
    llm = FakeLlm(pick=["shop_sales_daily"])
    select_views("And in July?", catalog, llm=llm, model="small", previous_question="Revenue in August?")
    assert "Previous question in this conversation: Revenue in August?" in llm.calls[0]["messages"][0]["content"]


# ── the narrowed catalog ───────────────────────────────────────────────────

def test_narrowing_keeps_only_the_views_and_the_joins_and_patterns_among_them(catalog):
    text = render_catalog(catalog, views=["ads_google_search_campaign_daily", "campaigns"])
    described = {line[4:] for line in text.splitlines() if line.startswith("### ") and line[4:] in catalog.views}
    assert described == {"ads_google_search_campaign_daily", "campaigns"}
    assert "| ads_google_search_campaign_daily | campaigns | `campaign_id` |" in text
    assert "| ads_meta_campaign_daily | campaigns |" not in text
    assert "Google micros to euros, with campaign names" in text      # uses only those two
    assert "Return rate of an order cohort" not in text                # needs other views
    assert "## Important Notes" in text                                # general rules stay


def test_tables_in_finds_bare_braced_and_qualified_names(catalog):
    sql = "SELECT * FROM `p.d.shop_sales_daily` s JOIN {products} p ON 1=1 -- shop_orders_x"
    assert tables_in(sql, catalog.views) == {"shop_sales_daily", "products"}


# ── the pipeline ───────────────────────────────────────────────────────────

SQL_REVENUE = "SELECT SUM(revenue_net) AS revenue_net FROM shop_sales_daily WHERE date BETWEEN '2026-08-01' AND '2026-08-31'"


def test_the_sql_step_sees_only_the_selected_views(large, catalog):
    llm = FakeLlm(pick=["shop_sales_daily"], sql=[SQL_REVENUE])
    result = _ask("What was our revenue in August 2026?", llm, large, catalog)
    sql_call = next(c for c in llm.calls if c["phase"] == "sql")
    assert "### shop_sales_daily" in sql_call["system"]
    assert "### shop_orders" not in sql_call["system"] and "### ads_meta_campaign_daily" not in sql_call["system"]
    assert result.selected_views == ["shop_sales_daily"] and result.fallback is None
    assert result.failure is None and len(result.data) == 1


def test_every_call_is_recorded_with_its_tokens_and_time(large, catalog):
    llm = FakeLlm(pick=["shop_sales_daily"], sql=[SQL_REVENUE])
    result = _ask("What was our revenue in August 2026?", llm, large, catalog)
    assert [s.phase for s in result.steps] == ["select", "sql", "interpret"]
    assert result.steps[0].usage.cache_read_tokens == 4000
    assert all(s.seconds >= 0 for s in result.steps) and result.seconds >= sum(s.seconds for s in result.steps)


def test_the_interpretation_reads_the_entries_of_the_views_the_query_used(large, catalog):
    llm = FakeLlm(pick=["shop_sales_daily", "products"], sql=[SQL_REVENUE])
    _ask("What was our revenue in August 2026?", llm, large, catalog)
    system = next(c for c in llm.calls if c["phase"] == "interpret")["system"]
    assert "## The views the query used" in system and "### shop_sales_daily" in system
    assert "### products" not in system  # selected, but not used by the query


def test_the_other_stages_interpretation_is_unchanged(large, catalog):
    """Decision 2026-10-09: only the new stage reads view notes, so the old
    stages' answers stay what they were."""
    llm = FakeLlm(sql=[SQL_REVENUE])
    ask("Revenue?", llm=llm, model="m", backend=large, context="ctx", **PERIOD)
    system = next(c for c in llm.calls if c["phase"] == "interpret")["system"]
    assert "## The views the query used" not in system


def test_no_query_from_the_selected_views_asks_again_with_everything(large, catalog):
    llm = FakeLlm(pick=["products"], sql=["SELECT 'not answerable from these tables' AS note", SQL_REVENUE])
    result = _ask("What was our revenue in August 2026?", llm, large, catalog)
    sql_calls = [c for c in llm.calls if c["phase"] == "sql"]
    assert len(sql_calls) == 2
    assert "### shop_sales_daily" not in sql_calls[0]["system"]
    assert "### shop_sales_daily" in sql_calls[1]["system"] and "### email_sends_daily" in sql_calls[1]["system"]
    assert result.fallback == "no query from the selected views" and result.failure is None


def test_the_retry_after_a_database_error_gets_the_full_catalog(large, catalog):
    llm = FakeLlm(pick=["shop_sales_daily"], sql=["SELECT revenue FROM shop_sales_daily", SQL_REVENUE])
    result = _ask("What was our revenue in August 2026?", llm, large, catalog)
    sql_calls = [c for c in llm.calls if c["phase"] == "sql"]
    assert result.retried and result.fallback == "retry after a database error"
    assert "### email_sends_daily" in sql_calls[1]["system"]


def test_a_failed_selection_runs_on_the_full_catalog(large, catalog):
    llm = FakeLlm(fail=True, sql=[SQL_REVENUE])
    result = _ask("What was our revenue in August 2026?", llm, large, catalog)
    sql_call = next(c for c in llm.calls if c["phase"] == "sql")
    assert "### email_sends_daily" in sql_call["system"]
    assert result.selected_views is None and result.selection_skipped.startswith("selection failed")
    assert result.failure is None


def test_selection_setup_only_for_the_selected_stage(large):
    assert selection_setup("catalog", large, model="m", catalog_path=LARGE.catalog) is None
    setup = selection_setup("catalog_selected", large, model="m", catalog_path=LARGE.catalog)
    assert setup.model == "m" and "shop_sales_daily" in setup.catalog.views


# ── the evaluation ─────────────────────────────────────────────────────────

def test_the_eval_scores_the_selection_against_the_needed_views(large, tmp_path):
    from data_chat.evaluation import Question, run_eval, summary_table, write_outcomes

    q = Question(id="rev", question="Revenue in August 2026?", expected_sql=SQL_REVENUE,
                 views=("shop_sales_daily",))
    llm = FakeLlm(pick=["shop_sales_daily", "shop_orders"], sql=[SQL_REVENUE])
    outcomes = run_eval([q], llm=llm, model="m", backend=large, stages=("catalog", "catalog_selected"),
                        catalog_path=LARGE.catalog, freetext_path=LARGE.freetext, **PERIOD)
    full, sel = outcomes
    assert full.correct and sel.correct
    assert full.selected_views is None and full.recall is None
    assert sel.recall == 1.0 and sel.precision == 0.5
    assert [s["phase"] for s in sel.steps] == ["select", "sql"]
    table = summary_table(outcomes, [q])
    assert "selection recall / precision | — | 100% / 50% |" in table
    assert "prompt tokens / question, SQL" in table
    path = write_outcomes(outcomes, tmp_path / "run.json", {"model": "m"})
    assert json.loads(path.read_text())["outcomes"][1]["steps"][0]["usage"]["cache_read_tokens"] == 4000


def test_questions_without_views_still_load(tmp_path):
    from data_chat.evaluation import load_questions

    path = tmp_path / "q.yaml"
    path.write_text("questions:\n  - {id: a, question: q, expected_sql: SELECT 1}\n")
    assert load_questions(path)[0].views == ()


# ── the adapters carry usage ───────────────────────────────────────────────

def test_anthropic_usage_and_tool_input():
    usage = SimpleNamespace(input_tokens=7, output_tokens=3, cache_creation_input_tokens=100,
                            cache_read_input_tokens=900)
    messages = SimpleNamespace(create=lambda **kw: SimpleNamespace(
        stop_reason="tool_use", usage=usage,
        content=[SimpleNamespace(type="tool_use", input={"views": ["a"]})]))
    out = AnthropicLlm(SimpleNamespace(messages=messages)).call_tool(
        phase="select", model="m", system="S", messages=[], tool={"name": "t"}, max_tokens=5)
    assert out == {"views": ["a"]} and isinstance(out, dict)
    assert out.usage == Usage(7, 3, 100, 900) and out.usage.prompt_tokens == 1007


def test_openai_usage_splits_cached_tokens():
    response = SimpleNamespace(
        usage=SimpleNamespace(prompt_tokens=1000, completion_tokens=20,
                              prompt_tokens_details=SimpleNamespace(cached_tokens=800)),
        choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content="SELECT 1"))])
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: response)))
    reply = OpenAILlm(client).complete(phase="sql", model="m", system="S", messages=[], max_tokens=5)
    assert reply.usage == Usage(input_tokens=200, output_tokens=20, cache_read_tokens=800)
