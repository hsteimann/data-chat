from datetime import date

from data_chat.context import build_context
from data_chat.llm import LlmReply
from data_chat.pipeline import ask
from tests.conftest import ScriptedLlm

PERIOD = dict(start_date=date(2026, 6, 1), end_date=date(2026, 9, 27))


def _ask(llm, backend, question="What was our ad spend in August 2026?", **kw):
    return ask(question, llm=llm, model="m", backend=backend,
               context=build_context("catalog", backend), **PERIOD, **kw)


def test_the_generated_sql_runs_and_is_returned(backend):
    llm = ScriptedLlm(
        "SELECT SUM(cost) / 100 AS spend_eur FROM ads_campaign_daily "
        "WHERE date BETWEEN '2026-08-01' AND '2026-08-31'",
        'Spend was 18,536.05 EUR.\n{"chart_type": "bar", "x": "spend_eur", "y": "spend_eur"}',
    )
    result = _ask(llm, backend)
    assert result.failure is None
    assert result.sql.endswith("LIMIT 1000")
    assert round(float(result.data.spend_eur[0]), 2) == 18536.05
    assert result.answer == "Spend was 18,536.05 EUR."
    assert result.chart_spec["chart_type"] == "bar"
    assert [c["phase"] for c in llm.calls] == ["sql", "interpret"]


def test_the_question_arrives_with_its_date_range(backend):
    llm = ScriptedLlm("SELECT 1 AS x", "ok")
    _ask(llm, backend)
    assert llm.calls[0]["messages"][-1]["content"] == (
        "Date range: 2026-06-01 to 2026-09-27\n\nQuestion: What was our ad spend in August 2026?"
    )
    assert "euro cents" in llm.calls[0]["system"]


def test_a_database_error_is_fed_back_once(backend):
    llm = ScriptedLlm(
        "SELECT SUM(spend) FROM ads_campaign_daily",
        "SELECT SUM(cost) / 100 AS spend FROM ads_campaign_daily",
        "answer",
    )
    result = _ask(llm, backend)
    assert result.retried and result.failure is None
    retry = llm.calls[1]["messages"]
    assert retry[-2] == {"role": "assistant", "content": "SELECT SUM(spend) FROM ads_campaign_daily LIMIT 1000"}
    assert retry[-1]["content"].startswith("The previous query failed with this database error:")
    assert "spend" in retry[-1]["content"]


def test_refused_twice_is_unanswerable(backend):
    llm = ScriptedLlm("SELECT nope FROM ads_campaign_daily")
    result = _ask(llm, backend)
    assert result.failure == "unanswerable"
    assert result.error.startswith("Query failed after retry")
    assert len(llm.calls) == 2


def test_prose_instead_of_sql_is_unanswerable(backend):
    result = _ask(ScriptedLlm("I cannot answer that from these tables."), backend)
    assert result.failure == "unanswerable" and result.error.startswith("Invalid SQL")


def test_a_write_is_never_executed(backend):
    result = _ask(ScriptedLlm("DELETE FROM campaigns"), backend)
    assert result.failure == "unanswerable"
    assert int(backend.execute("SELECT COUNT(*) AS n FROM campaigns").n[0]) == 8


def test_truncated_sql_is_our_error_not_the_data(backend):
    result = _ask(ScriptedLlm(LlmReply("SELECT SUM(co", "max_tokens")), backend)
    assert result.failure == "internal_error"


def test_an_empty_result_is_said_plainly(backend):
    llm = ScriptedLlm("SELECT * FROM campaigns WHERE campaign_id = -1")
    result = _ask(llm, backend)
    assert result.failure is None and result.data.empty
    assert result.answer == "The query ran and returned no rows."
    assert len(llm.calls) == 1  # no interpretation call for nothing


def test_history_becomes_prior_turns(backend):
    llm = ScriptedLlm("SELECT 1 AS x", "ok")
    _ask(llm, backend, question="And in July?",
         history=[{"question": "Spend in August?", "sql": "SELECT 2", "answer": "2"}])
    roles = [m["role"] for m in llm.calls[0]["messages"]]
    assert roles == ["user", "assistant", "user"]
    assert llm.calls[1]["messages"][0] == {"role": "user", "content": "Spend in August?"}
