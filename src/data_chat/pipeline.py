"""Question → SQL → result → answer, with one retry on a database error.

The flow of the Nakoa Brain's ``run_query`` (``src/adp/services/data_chat.py``
at b054abe, 2026-09-28), with its dependencies passed in instead of looked
up: the model (``LlmClient``), the database (``SqlBackend``) and the context
block. What stays behind in the Brain: client lookup, dataset scope guard,
cost ceiling, usage tracking, the failure explainer and its evidence probes,
and the Amazon-specific correction for campaigns without delivery.

The SQL is the product. It is returned with every answer so the person who
asked can read and rerun exactly what produced the number.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

import pandas as pd

from data_chat.backend import SqlBackend, SqlRejected
from data_chat.llm import LlmClient
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
) -> tuple[str, dict | None]:
    """The answer text and an optional chart spec, from the result rows."""
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
    text = llm.complete(
        phase="interpret", model=model, system=INTERPRETATION_SYSTEM,
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
) -> Answer:
    """The whole pipeline for one question."""
    result = Answer(question=question)
    system_prompt = sql_system_prompt(backend.dialect, context)
    sql_history = [h for h in (history or []) if h.get("sql")]

    def _generate(**retry) -> str:
        return generate_sql(
            question, llm=llm, model=model, system_prompt=system_prompt,
            start_date=start_date, end_date=end_date, history=sql_history, **retry,
        )

    try:
        sql = _generate()
    except Exception as e:
        return _failed(result, "internal_error", f"SQL generation failed: {e}")
    ok, reason = validate_sql(sql)
    if not ok:
        return _failed(result, "unanswerable", f"Invalid SQL: {reason}", sql)
    sql = _with_limit(sql)

    try:
        df = backend.execute(sql)
    except SqlRejected as e:
        result.retried = True
        try:
            sql = _generate(previous_sql=sql, error=str(e))
        except Exception as gen_err:
            return _failed(result, "internal_error", f"SQL retry generation failed: {gen_err}", sql)
        ok, reason = validate_sql(sql)
        if not ok:
            return _failed(result, "unanswerable", f"Invalid SQL after retry: {reason}", sql)
        sql = _with_limit(sql)
        try:
            df = backend.execute(sql)
        except Exception as e2:
            return _failed(result, "unanswerable", f"Query failed after retry: {e2}", sql)
    except Exception as e:
        return _failed(result, "internal_error", f"Query failed: {e}", sql)

    result.sql, result.data = sql, df
    if df.empty:
        result.answer = "The query ran and returned no rows."
    elif answer_in_words:
        interp_history = [h for h in (history or []) if h.get("answer")]
        result.answer, result.chart_spec = interpret(
            question, df, llm=llm, model=model, history=interp_history
        )
    return result


def _failed(result: Answer, category: str, error: str, sql: str | None = None) -> Answer:
    result.failure, result.error, result.sql = category, error, sql
    return result
