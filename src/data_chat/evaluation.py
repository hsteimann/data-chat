"""Run the same questions through each context stage and score the results.

A question counts as answered when the generated SQL returns the same
numbers as the reference query — compared on the result table, not on the
prose answer, because the SQL is what the reader is asked to trust.

Scoring rules (``results_match``):

- same number of rows;
- every column of the expected result has a counterpart in the actual
  result: numeric columns match when their sorted values agree within 0.5 %,
  text columns when their sets of values are equal;
- a ratio column (every value between -1 and 1) also matches in percent
  (×100) — only a ratio: for money, ×100 is exactly the cents-as-euros
  mistake the questions test for;
- a numeric column also matches when rounded to
  two decimals as the prompt's rounding rule asks — but only where two
  decimals still leave three significant digits (|value| ≥ 1). A rate of
  0.005 rounded to 0.01 would pass for any rate between 0.005 and 0.015;
- extra columns in the actual result are fine.

Column order, row order and column names are ignored.

With ``charts=True`` each question also gets its answer, and the chart spec
is checked against the result (`chart.check_chart`): ``drawn``,
``no chart``, or the reason it cannot be drawn. ``chart_ok`` then says
whether that is what the prompt asks for (``chart_as_asked``): a chart for a
result with more than one row, none for a single value. Both are recorded
next to the score and do not change it — a right chart over a wrong number
is still a wrong number.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

import pandas as pd
import yaml

from data_chat.backend import SqlBackend
from data_chat.chart import check_chart
from data_chat.context import STAGES, build_context
from data_chat.llm import LlmClient
from data_chat.pipeline import ask

REL_TOL = 0.005


@dataclass(frozen=True)
class Question:
    id: str
    question: str
    expected_sql: str
    trap: str = ""


@dataclass
class Outcome:
    stage: str
    question_id: str
    correct: bool
    sql: str | None
    failure: str | None
    error: str | None
    retried: bool
    #: None when charts were not asked for; else "drawn", "no chart" or the reason.
    chart: str | None = None
    #: Whether ``chart`` is what the prompt asks for (`chart_as_asked`).
    chart_ok: bool | None = None
    #: The spec as the model wrote it, for the record.
    chart_spec: dict | None = None


def chart_as_asked(status: str, rows: int) -> bool:
    """The interpretation prompt: a chart spec for every result, skipped only
    for a single value or an empty result."""
    return status == ("drawn" if rows > 1 else "no chart")


def load_questions(path: str | Path) -> list[Question]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return [Question(**q) for q in raw["questions"]]


def _numeric(series: pd.Series) -> list[float] | None:
    values = pd.to_numeric(series, errors="coerce")
    if values.isna().any():
        return None
    return sorted(float(v) for v in values)


def _close(a: list[float], b: list[float]) -> bool:
    return len(a) == len(b) and all(
        math.isclose(x, y, rel_tol=REL_TOL, abs_tol=1e-9) for x, y in zip(a, b)
    )


def _round2(v: float) -> float:
    return round(v, 2) if abs(v) >= 1 else v


def _column_matches(expected: pd.Series, actual: pd.Series) -> bool:
    exp_num = _numeric(expected)
    if exp_num is not None:
        act_num = _numeric(actual)
        if act_num is None:
            return False
        candidates = [exp_num, sorted(_round2(v) for v in exp_num)]
        if all(abs(v) <= 1 for v in exp_num):  # a ratio: percent is the same answer
            candidates += [[v * 100 for v in exp_num], sorted(_round2(v * 100) for v in exp_num)]
        return any(_close(c, act_num) for c in candidates)
    return set(expected.astype(str)) == set(actual.astype(str))


def results_match(expected: pd.DataFrame, actual: pd.DataFrame | None) -> bool:
    if actual is None or len(expected) != len(actual):
        return False
    unused = list(actual.columns)
    for col in expected.columns:
        hit = next((a for a in unused if _column_matches(expected[col], actual[a])), None)
        if hit is None:
            return False
        unused.remove(hit)
    return True


def run_eval(
    questions: list[Question],
    *,
    llm: LlmClient,
    model: str,
    backend: SqlBackend,
    stages: tuple[str, ...] = STAGES,
    start_date: date,
    end_date: date,
    charts: bool = False,
    catalog_path: str | Path | None = None,
    freetext_path: str | Path | None = None,
) -> list[Outcome]:
    outcomes = []
    paths = {k: v for k, v in (("catalog_path", catalog_path), ("freetext_path", freetext_path)) if v}
    for stage in stages:
        context = build_context(stage, backend, **paths)
        for q in questions:
            expected = backend.execute(q.expected_sql)
            result = ask(
                q.question, llm=llm, model=model, backend=backend, context=context,
                start_date=start_date, end_date=end_date, answer_in_words=charts,
            )
            rows = 0 if result.data is None else len(result.data)
            chart = check_chart(result.chart_spec, result.data)[1] if charts else None
            outcomes.append(Outcome(
                stage=stage,
                question_id=q.id,
                correct=result.failure is None and results_match(expected, result.data),
                sql=result.sql,
                failure=result.failure,
                error=result.error,
                retried=result.retried,
                chart=chart,
                chart_ok=None if chart is None else chart_as_asked(chart, rows),
                chart_spec=result.chart_spec,
            ))
    return outcomes


def summary_table(outcomes: list[Outcome], questions: list[Question]) -> str:
    stages = list(dict.fromkeys(o.stage for o in outcomes))
    by = {(o.stage, o.question_id): o for o in outcomes}
    header = "| Question | " + " | ".join(stages) + " |"
    lines = [header, "|" + "---|" * (len(stages) + 1)]
    for q in questions:
        cells = []
        for s in stages:
            o = by.get((s, q.id))
            cells.append("—" if o is None else ("✓" if o.correct else "✗"))
        lines.append(f"| {q.id} | " + " | ".join(cells) + " |")
    totals = []
    for s in stages:
        got = [o for o in outcomes if o.stage == s]
        totals.append(f"**{sum(o.correct for o in got)}/{len(got)}**")
    lines.append("| **correct** | " + " | ".join(totals) + " |")
    if any(o.chart is not None for o in outcomes):
        asked = []
        for s in stages:
            got = [o for o in outcomes if o.stage == s and o.chart is not None]
            asked.append(f"{sum(bool(o.chart_ok) for o in got)}/{len(got)}")
        lines.append("| chart as the prompt asks | " + " | ".join(asked) + " |")
    return "\n".join(lines)


def write_outcomes(outcomes: list[Outcome], path: str | Path, meta: dict) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"meta": meta, "outcomes": [asdict(o) for o in outcomes]}, indent=2),
        encoding="utf-8",
    )
    return path
