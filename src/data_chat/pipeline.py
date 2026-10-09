"""Question → SQL → result → answer, with one retry on a database error.

The flow of the Nakoa Brain's ``run_query`` (``src/adp/services/data_chat.py``
at b054abe, 2026-09-28), with its dependencies passed in instead of looked
up: the model (``LlmClient``), the database (``SqlBackend``) and the context
block. What stays behind in the Brain: client lookup, dataset scope guard,
cost ceiling, usage tracking, the failure explainer and its evidence probes,
and the Amazon-specific correction for campaigns without delivery.

The SQL is the product. It is returned with every answer so the person who
asked can read and rerun exactly what produced the number.

With ``selection`` (the ``catalog_selected`` stage) a step runs first that
picks the views the question needs (``selection.select_views``), and the SQL
prompt describes only those. Its fallbacks follow the Brain: no selection →
the full catalog; a narrowed prompt that yields no query on the catalog's
tables → asked once more with the full catalog; the retry after a database
error → always the full catalog. The interpretation then also reads the
catalog entries of the views the query used. Every model call is recorded
with its tokens and time (``Answer.steps``), in every stage.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import pandas as pd

from data_chat.backend import SqlBackend, SqlRejected
from data_chat.catalog import Catalog, render_catalog, render_views, tables_in
from data_chat.llm import NO_USAGE, LlmClient, Usage
from data_chat.prompts import (
    DATE_LINE,
    INTERPRETATION_SYSTEM,
    INTERPRETATION_USER_TEMPLATE,
    RETRY_TEMPLATE,
    answer_language_line,
    sql_system_prompt,
)
from data_chat.sql import extract_chart_spec, extract_sql, validate_sql

MAX_HISTORY_TURNS = 3
ROW_LIMIT = 1000


@dataclass(frozen=True)
class Step:
    """One model call: which phase, its tokens, how long it took."""

    phase: str
    usage: Usage
    seconds: float


class _Metered:
    """An ``LlmClient`` that records every call it passes on as a ``Step``."""

    def __init__(self, llm: LlmClient, steps: list[Step]):
        self._llm, self._steps = llm, steps

    def complete(self, **kwargs):
        started = time.perf_counter()
        reply = self._llm.complete(**kwargs)
        self._steps.append(Step(kwargs["phase"], getattr(reply, "usage", NO_USAGE), time.perf_counter() - started))
        return reply

    def call_tool(self, **kwargs):
        started = time.perf_counter()
        reply = self._llm.call_tool(**kwargs)
        self._steps.append(Step(kwargs["phase"], getattr(reply, "usage", NO_USAGE), time.perf_counter() - started))
        return reply


@dataclass(frozen=True)
class SelectionSetup:
    """What the selected stage needs besides the full context: the catalog to
    select from and render, how tables are referenced, and the model that
    selects."""

    catalog: Catalog
    model: str
    qualify: Any = lambda t: t


@dataclass
class Answer:
    question: str
    sql: str | None = None
    data: pd.DataFrame | None = None
    answer: str | None = None
    chart_spec: dict | None = None
    retried: bool = False
    #: None on success; else "internal_error" (our side), "unanswerable" (the
    #: database refused the SQL twice, or no valid query came back).
    failure: str | None = None
    error: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)
    #: The views the SQL prompt described, when a selection ran; None = all.
    selected_views: list[str] | None = None
    #: Why no selection was used ("small catalog", "selection failed: …", …).
    selection_skipped: str | None = None
    #: When the selected stage fell back to the full catalog, and why.
    fallback: str | None = None
    steps: list[Step] = field(default_factory=list)
    seconds: float = 0.0


def generate_sql(
    question: str,
    *,
    llm: LlmClient,
    model: str,
    system_prompt: str,
    start_date: date,
    end_date: date,
    history: list[dict] | None = None,
    previous_sql: str | None = None,
    error: str | None = None,
) -> str:
    """Ask the model for SQL. ``previous_sql`` + ``error`` make it the retry turn."""
    date_ctx = DATE_LINE.format(start_date=start_date.isoformat(), end_date=end_date.isoformat())
    messages: list[dict] = []
    for turn in (history or [])[-MAX_HISTORY_TURNS:]:
        messages.append({"role": "user", "content": f"{date_ctx}\n\nQuestion: {turn['question']}"})
        messages.append({"role": "assistant", "content": turn["sql"]})
    messages.append({"role": "user", "content": f"{date_ctx}\n\nQuestion: {question}"})
    if previous_sql and error:
        messages.append({"role": "assistant", "content": previous_sql})
        messages.append({"role": "user", "content": RETRY_TEMPLATE.format(error=error)})

    # An empty reply is a hiccup, not a verdict: ask once more.
    for _ in range(2):
        reply = llm.complete(
            phase="sql", model=model, system=system_prompt, messages=messages, max_tokens=8192
        )
        if reply.stop_reason == "max_tokens":
            raise ValueError("Generated SQL was truncated. Ask a simpler question.")
        if reply.text.strip():
            return extract_sql(reply.text)
    raise ValueError("The model returned no SQL twice in a row.")


def interpret(
    question: str,
    df: pd.DataFrame,
    *,
    llm: LlmClient,
    model: str,
    history: list[dict] | None = None,
    view_notes: str | None = None,
) -> tuple[str, dict | None]:
    """The answer text and an optional chart spec, from the result rows.

    ``view_notes`` — the catalog entries of the views the query used — is
    added to the system prompt when given (the selected stage)."""
    if len(df) > 50:
        results_md = df.head(50).to_markdown(index=False)
        results_md += f"\n\n... (showing first 50 of {len(df)} rows)"
    else:
        results_md = df.to_markdown(index=False)
    messages: list[dict] = []
    for turn in (history or [])[-MAX_HISTORY_TURNS:]:
        messages.append({"role": "user", "content": turn["question"]})
        messages.append({"role": "assistant", "content": turn["answer"]})
    messages.append({
        "role": "user",
        "content": INTERPRETATION_USER_TEMPLATE.format(
            question=question,
            results=results_md,
            row_count=len(df),
            language_line=answer_language_line(question),
        ),
    })
    system = INTERPRETATION_SYSTEM
    if view_notes:
        system += "\n\n## The views the query used\n\n" + view_notes
    text = llm.complete(
        phase="interpret", model=model, system=system,
        messages=messages, max_tokens=2048,
    ).text.strip()
    return extract_chart_spec(text)


def _with_limit(sql: str) -> str:
    return sql if "LIMIT" in sql.upper() else sql.rstrip().rstrip(";") + f" LIMIT {ROW_LIMIT}"


def ask(
    question: str,
    *,
    llm: LlmClient,
    model: str,
    backend: SqlBackend,
    context: str,
    start_date: date,
    end_date: date,
    history: list[dict] | None = None,
    answer_in_words: bool = True,
    selection: SelectionSetup | None = None,
) -> Answer:
    """The whole pipeline for one question.

    ``context`` is the full context block of the stage. ``selection`` turns
    on the view-selection step in front of it (see the module docstring).
    """
    started = time.perf_counter()
    result = Answer(question=question)
    llm = _Metered(llm, result.steps)
    full_prompt = system_prompt = sql_system_prompt(backend.dialect, context)
    sql_history = [h for h in (history or []) if h.get("sql")]

    if selection is not None:
        from data_chat.selection import select_views

        previous = next((h["question"] for h in reversed(history or []) if h.get("question")), None)
        picked = select_views(question, selection.catalog, llm=llm, model=selection.model,
                              previous_question=previous)
        result.selected_views, result.selection_skipped = picked.views, picked.skipped
        if picked.views:
            system_prompt = sql_system_prompt(
                backend.dialect,
                render_catalog(selection.catalog, qualify=selection.qualify, views=picked.views),
            )

    def _generate(prompt: str, **retry) -> str:
        return generate_sql(
            question, llm=llm, model=model, system_prompt=prompt,
            start_date=start_date, end_date=end_date, history=sql_history, **retry,
        )

    def _done(r: Answer) -> Answer:
        r.seconds = time.perf_counter() - started
        return r

    try:
        sql = _generate(system_prompt)
        if result.selected_views and not _answers(sql, selection.catalog):
            # The narrowed prompt may lack the view the question needs: what
            # yields no query on the catalog gets one more look with everything.
            result.fallback = "no query from the selected views"
            sql = _generate(full_prompt)
    except Exception as e:
        return _done(_failed(result, "internal_error", f"SQL generation failed: {e}"))
    ok, reason = validate_sql(sql)
    if not ok:
        return _done(_failed(result, "unanswerable", f"Invalid SQL: {reason}", sql))
    sql = _with_limit(sql)

    try:
        df = backend.execute(sql)
    except SqlRejected as e:
        result.retried = True
        if result.selected_views and result.fallback is None:
            result.fallback = "retry after a database error"
        try:
            # A retry gets the full catalog: the error may be a missing view.
            sql = _generate(full_prompt, previous_sql=sql, error=str(e))
        except Exception as gen_err:
            return _done(_failed(result, "internal_error", f"SQL retry generation failed: {gen_err}", sql))
        ok, reason = validate_sql(sql)
        if not ok:
            return _done(_failed(result, "unanswerable", f"Invalid SQL after retry: {reason}", sql))
        sql = _with_limit(sql)
        try:
            df = backend.execute(sql)
        except Exception as e2:
            return _done(_failed(result, "unanswerable", f"Query failed after retry: {e2}", sql))
    except Exception as e:
        return _done(_failed(result, "internal_error", f"Query failed: {e}", sql))

    result.sql, result.data = sql, df
    if df.empty:
        result.answer = "The query ran and returned no rows."
    elif answer_in_words:
        interp_history = [h for h in (history or []) if h.get("answer")]
        notes = None
        if selection is not None:
            notes = render_views(selection.catalog, tables_in(sql, selection.catalog.views)) or None
        result.answer, result.chart_spec = interpret(
            question, df, llm=llm, model=model, history=interp_history, view_notes=notes,
        )
    return _done(result)


def _answers(sql: str, catalog: Catalog) -> bool:
    """A query, and one that reads at least one table of the catalog — not a
    sentence dressed as SELECT (the Brain's ``_answers`` / literal-only check)."""
    ok, _ = validate_sql(sql)
    return ok and bool(tables_in(sql, catalog.views))


def _failed(result: Answer, category: str, error: str, sql: str | None = None) -> Answer:
    result.failure, result.error, result.sql = category, error, sql
    return result
