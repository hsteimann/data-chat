from datetime import date

import pandas as pd

from data_chat.context import REPO_ROOT
from data_chat.demo_data import build_tables
from data_chat.evaluation import load_questions, results_match, run_eval, summary_table
from tests.conftest import ScriptedLlm

QUESTIONS = load_questions(REPO_ROOT / "eval" / "questions.yaml")


def test_every_reference_query_runs_and_returns_rows(backend):
    for q in QUESTIONS:
        assert len(backend.execute(q.expected_sql)) > 0, q.id


def test_match_ignores_order_names_and_extra_columns():
    expected = pd.DataFrame({"channel": ["search", "display"], "roas": [5.1234, 2.4563]})
    actual = pd.DataFrame({"ch": ["display", "search"], "spend": [1, 2], "r": [2.4563, 5.1234]})
    assert results_match(expected, actual)


def test_match_accepts_percent_and_the_prompts_rounding():
    assert results_match(pd.DataFrame({"r": [0.02512]}), pd.DataFrame({"pct": [2.51]}))
    assert results_match(pd.DataFrame({"v": [18536.0512]}), pd.DataFrame({"v": [18536.05]}))


def test_match_refuses_a_small_rate_rounded_to_nothing():
    assert not results_match(pd.DataFrame({"ctr": [0.00501]}), pd.DataFrame({"ctr": [0.01]}))


def test_match_refuses_the_classic_mistakes():
    spend = pd.DataFrame({"spend_eur": [18536.05]})
    assert not results_match(spend, pd.DataFrame({"s": [1853605]}))          # cents as euros
    net = pd.DataFrame({"net": [159841.34]})
    assert not results_match(net, pd.DataFrame({"rev": [190211.20]}))        # gross as net
    assert not results_match(spend, pd.DataFrame({"s": [1.0, 2.0]}))         # wrong row count
    assert not results_match(spend, None)


def test_run_eval_scores_each_stage(backend):
    by_question = {q.question: q.expected_sql for q in QUESTIONS}

    def answer(kwargs):
        question = kwargs["messages"][-1]["content"].split("Question: ", 1)[1]
        # "Right" only when the prompt carries the catalog — a stand-in for a model.
        if "euro cents" in kwargs["system"]:
            return by_question[question]
        return "SELECT 0 AS wrong"

    outcomes = run_eval(QUESTIONS, llm=ScriptedLlm(answer), model="m", backend=backend,
                        stages=("schema", "catalog"),
                        start_date=date(2026, 6, 1), end_date=date(2026, 9, 27))
    score = {s: sum(o.correct for o in outcomes if o.stage == s) for s in ("schema", "catalog")}
    assert score == {"schema": 0, "catalog": len(QUESTIONS)}
    table = summary_table(outcomes, QUESTIONS)
    assert f"**0/{len(QUESTIONS)}**" in table and f"**{len(QUESTIONS)}/{len(QUESTIONS)}**" in table


def test_demo_data_is_deterministic():
    a, b = build_tables(), build_tables()
    for name in a:
        pd.testing.assert_frame_equal(a[name], b[name])


def test_the_rounded_score_accepts_a_rate_rounded_to_two_decimals_and_the_strict_one_does_not():
    import pandas as pd

    from data_chat.evaluation import results_match

    expected, actual = pd.DataFrame({"acos": [0.1153]}), pd.DataFrame({"acos_14d": [0.12]})
    assert not results_match(expected, actual)
    assert results_match(expected, actual, rounded=True)
    assert results_match(expected, pd.DataFrame({"pct": [11.53]}), rounded=True)
    assert not results_match(expected, pd.DataFrame({"acos": [0.13]}), rounded=True)
