"""Data Chat pipeline — Streamlit-free.

Service layer for the Data Chat feature. Used by both the MCP server
(`query_data` tool) and the Streamlit dashboard. No Streamlit imports.

Key design points:
- Anthropic client is a module-level singleton (reuses httpx connection pool).
- System prompt for SQL generation is sent with `cache_control: ephemeral`
  so Anthropic prompt caching cuts ~90% of input-token cost on repeat calls.
- Multi-turn history is supported but hard-capped at MAX_HISTORY_TURNS=3
  server-side regardless of what the caller passes.
- Token usage (including cache_read / cache_creation) is logged structured
  via `extra={...}` for the Cloud Logging filter `jsonPayload.event="anthropic_usage"`.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date, timedelta
from functools import lru_cache
from typing import Any

import anthropic
import pandas as pd
from google.api_core.exceptions import BadRequest
from google.cloud import bigquery

from adp.secrets import get_secret
from adp.services.data_chat_prompts import (
    INTERPRETATION_SYSTEM_PROMPT,
    INTERPRETATION_USER_TEMPLATE,
    build_sql_system_prompt,
)

logger = logging.getLogger(__name__)

# Hard-cap server-side. Claude Desktop SHOULD pass 1-3 turns; this is the safety net.
MAX_HISTORY_TURNS = 3
MAX_DATA_ROWS = 500

_MODEL = "claude-sonnet-4-6"


@lru_cache(maxsize=1)
def _anthropic_client() -> anthropic.Anthropic:
    """Module-level singleton — reuses httpx connection pool across calls."""
    return anthropic.Anthropic(api_key=get_secret("ANTHROPIC_API_KEY"))


def _log_token_usage(phase: str, response: anthropic.types.Message) -> None:
    """Log Anthropic token usage with cache-hit metrics for cost monitoring.

    Cloud Logging filter: `jsonPayload.event="anthropic_usage"`.
    The pipeline phase ("sql" / "interpret") is logged as `chat_phase` to
    avoid collision with the engine's `phase` ContextVar (used for
    request/collect/etc. workflow phases).
    """
    u = response.usage
    cache_read = getattr(u, "cache_read_input_tokens", 0) or 0
    cache_create = getattr(u, "cache_creation_input_tokens", 0) or 0
    logger.info(
        "anthropic_usage chat_phase=%s input=%d output=%d cache_read=%d cache_create=%d",
        phase,
        u.input_tokens,
        u.output_tokens,
        cache_read,
        cache_create,
        extra={
            "event": "anthropic_usage",
            "chat_phase": phase,
            "input_tokens": u.input_tokens,
            "output_tokens": u.output_tokens,
            "cache_read_input_tokens": cache_read,
            "cache_creation_input_tokens": cache_create,
        },
    )


def generate_sql(
    question: str,
    dataset: str,
    gcp_project: str,
    start_date: date,
    end_date: date,
    history: list[dict] | None = None,  # [{"question": str, "sql": str}]
    previous_sql: str | None = None,  # für Retry: fehlgeschlagenes SQL
    bq_error: str | None = None,  # für Retry: BQ-Fehlermeldung
) -> str:
    """Generate BQ SQL via Claude with prompt caching on the system prompt."""
    client = _anthropic_client()
    system_prompt = build_sql_system_prompt(gcp_project, dataset)
    date_ctx = f"Date range: {start_date.isoformat()} to {end_date.isoformat()}"

    messages: list[dict] = []
    for turn in (history or [])[-MAX_HISTORY_TURNS:]:
        messages.append(
            {"role": "user", "content": f"{date_ctx}\n\nQuestion: {turn['question']}"}
        )
        messages.append({"role": "assistant", "content": turn["sql"]})
    messages.append({"role": "user", "content": f"{date_ctx}\n\nQuestion: {question}"})

    if previous_sql and bq_error:
        messages.append({"role": "assistant", "content": previous_sql})
        messages.append({
            "role": "user",
            "content": f"The previous query failed with this BigQuery error:\n{bq_error}\n\nPlease fix the SQL.",
        })

    response = client.messages.create(
        model=_MODEL,
        max_tokens=8192,
        system=[
            {
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"},  # ← Prompt Caching
            }
        ],
        messages=messages,
    )
    _log_token_usage("sql", response)

    if response.stop_reason == "max_tokens":
        raise ValueError("Generated SQL was truncated. Ask a simpler question.")

    sql = response.content[0].text.strip()
    sql = re.sub(r"^```sql\s*", "", sql, flags=re.MULTILINE)
    sql = re.sub(r"^```\s*", "", sql, flags=re.MULTILINE)
    sql = re.sub(r"\s*```$", "", sql)
    return sql.strip()


def interpret_results(
    question: str,
    df: pd.DataFrame,
    history: list[dict] | None = None,  # [{"question": str, "answer": str}]
) -> tuple[str, dict | None]:
    """Interpret BQ results via Claude with multi-turn history."""
    client = _anthropic_client()

    if len(df) > 50:
        results_md = df.head(50).to_markdown(index=False)
        results_md += f"\n\n... (showing first 50 of {len(df)} rows)"
    else:
        results_md = df.to_markdown(index=False)

    messages: list[dict] = []
    for turn in (history or [])[-MAX_HISTORY_TURNS:]:
        messages.append({"role": "user", "content": turn["question"]})
        messages.append({"role": "assistant", "content": turn["answer"]})
    messages.append(
        {
            "role": "user",
            "content": INTERPRETATION_USER_TEMPLATE.format(
                question=question,
                results=results_md,
                row_count=len(df),
            ),
        }
    )

    response = client.messages.create(
        model=_MODEL,
        max_tokens=2048,
        system=INTERPRETATION_SYSTEM_PROMPT,
        messages=messages,
    )
    _log_token_usage("interpret", response)
    answer = response.content[0].text.strip()

    chart_spec = None
    chart_match = re.search(r'\{[^}]*"chart_type"[^}]*\}', answer)
    if chart_match:
        try:
            chart_spec = json.loads(chart_match.group())
            answer = answer.replace(chart_match.group(), "").strip()
        except json.JSONDecodeError:
            pass

    return answer, chart_spec


# Word-boundary regex avoids false positives on column names like INSERTED_AT.
_FORBIDDEN_RE = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|TRUNCATE|ALTER|CREATE|GRANT|REVOKE|MERGE)\b",
    re.IGNORECASE,
)
_LINE_COMMENT_RE = re.compile(r"--[^\n]*")
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_SINGLE_QUOTED_RE = re.compile(r"'[^']*'")
_DOUBLE_QUOTED_RE = re.compile(r'"[^"]*"')


def validate_sql(sql: str) -> tuple[bool, str]:
    """Validate that the SQL is read-only and looks well-formed.

    Strips comments and string literals before keyword checking so that
    legitimate values like `WHERE event = 'INSERT'` are not flagged.
    Returns (ok, reason). reason is empty when ok=True.
    """
    sql_clean = sql.strip()
    if not sql_clean:
        return False, "Empty SQL"

    sql_no_comments = _LINE_COMMENT_RE.sub("", sql_clean)
    sql_no_comments = _BLOCK_COMMENT_RE.sub("", sql_no_comments)
    sql_upper = sql_no_comments.upper().strip()

    if not (sql_upper.startswith("SELECT") or sql_upper.startswith("WITH")):
        return False, "Only SELECT/WITH queries are allowed."

    sql_no_strings = _SINGLE_QUOTED_RE.sub("''", sql_upper)
    sql_no_strings = _DOUBLE_QUOTED_RE.sub('""', sql_no_strings)

    m = _FORBIDDEN_RE.search(sql_no_strings)
    if m:
        return False, f"Query contains forbidden keyword: {m.group(1).upper()}"

    if re.search(r"\{(\w+)\}", sql_clean):
        placeholders = re.findall(r"\{(\w+)\}", sql_clean)
        return False, f"Query contains unresolved placeholders: {{{', '.join(placeholders)}}}"

    return True, ""


def execute_query(sql: str, gcp_project: str) -> tuple[pd.DataFrame, str]:
    """Execute *sql* against BigQuery and return (df, job_id)."""
    bq = bigquery.Client(project=gcp_project)
    job = bq.query(sql)
    return job.to_dataframe(create_bqstorage_client=False), job.job_id


def run_query(
    client_id: str,
    question: str,
    start_date: date | None = None,
    end_date: date | None = None,
    history: list[dict] | None = None,
) -> dict[str, Any]:
    """Full Data Chat pipeline. Returns structured result dict.

    `history` items use the shape:
    {"question": str, "sql": str | None, "answer": str | None}
    Only entries with `sql` feed the SQL-history; only entries with `answer`
    feed the interpretation-history.
    """
    # Lazy imports — `adp.clients` pulls in `adp.config.settings` which loads
    # YAML at import; keeping these local avoids inflating module import cost
    # for callers that only want `validate_sql` etc. (Also reduces circular
    # dependency surface area between services and config.)
    from adp.clients import load_clients
    from adp.config import settings

    all_clients = load_clients()
    cfg = all_clients.get(client_id)
    if not cfg:
        return {"error": f"Client '{client_id}' not found."}

    # Defaults aligned with dashboard: last 30 days ending yesterday.
    ed = end_date or (date.today() - timedelta(days=1))
    sd = start_date or (ed - timedelta(days=30))
    gcp_project = settings.gcp_project
    dataset = cfg.bq_dataset

    sql_history = [
        {"question": h["question"], "sql": h["sql"]}
        for h in (history or [])
        if h.get("sql")
    ]
    interp_history = [
        {"question": h["question"], "answer": h["answer"]}
        for h in (history or [])
        if h.get("answer")
    ]

    try:
        sql = generate_sql(
            question, dataset, gcp_project, sd, ed, history=sql_history
        )
    except Exception as e:
        logger.exception("sql_generation_failed client=%s", client_id)
        return {"error": f"SQL generation failed: {e}"}

    valid, reason = validate_sql(sql)
    if not valid:
        return {"error": f"Invalid SQL: {reason}", "sql": sql}

    if "LIMIT" not in sql.upper():
        sql = sql.rstrip(";") + " LIMIT 1000"

    try:
        df, job_id = execute_query(sql, gcp_project)
    except BadRequest as e:
        bq_error_msg = str(e)
        logger.warning(
            "bq_query_failed_retrying client=%s error=%s",
            client_id,
            bq_error_msg[:200],
        )
        try:
            sql = generate_sql(
                question, dataset, gcp_project, sd, ed,
                history=sql_history,
                previous_sql=sql,
                bq_error=bq_error_msg,
            )
        except Exception as gen_err:
            logger.exception("sql_retry_generation_failed client=%s", client_id)
            return {"error": f"SQL retry generation failed: {gen_err}", "sql": sql}

        valid, reason = validate_sql(sql)
        if not valid:
            return {"error": f"Invalid SQL after retry: {reason}", "sql": sql}
        if "LIMIT" not in sql.upper():
            sql = sql.rstrip(";") + " LIMIT 1000"

        try:
            df, job_id = execute_query(sql, gcp_project)
        except Exception as e2:
            logger.exception("bq_query_failed_after_retry client=%s", client_id)
            return {"error": f"Query failed after retry: {e2}", "sql": sql}

    except Exception as e:
        logger.exception("bq_query_failed client=%s", client_id)
        return {"error": f"Query failed: {e}", "sql": sql}

    if df.empty:
        return {
            "client_id": client_id,
            "client_name": cfg.name,
            "question": question,
            "answer": "Keine Daten für diese Anfrage im gewählten Zeitraum.",
            "chart_spec": None,
            "data": [],
            "sql": sql,
            "row_count": 0,
            "date_range": f"{sd} → {ed}",
            "truncated": False,
            "render_as": "text_only",
            "note": None,
        }

    try:
        answer, chart_spec = interpret_results(question, df, history=interp_history)
    except Exception as e:
        logger.exception("interpretation_failed client=%s", client_id)
        return {"error": f"Interpretation failed: {e}", "sql": sql}

    truncated = len(df) > MAX_DATA_ROWS
    rows = df.head(MAX_DATA_ROWS).to_dict(orient="records")
    for row in rows:
        for k, v in row.items():
            if hasattr(v, "isoformat"):
                row[k] = v.isoformat()

    note = None
    if truncated:
        note = (
            f"{len(df)} Zeilen total — nur die ersten {MAX_DATA_ROWS} sind in `data` enthalten. "
            f"Das Chart sollte aggregierte Sicht zeigen oder die Frage präziser eingegrenzt werden."
        )

    return {
        "client_id": client_id,
        "client_name": cfg.name,
        "question": question,
        "answer": answer,
        "chart_spec": chart_spec,
        "data": rows,
        "sql": sql,
        "row_count": len(df),
        "date_range": f"{sd} → {ed}",
        "truncated": truncated,
        "render_as": "plotly_artifact" if chart_spec else "text_only",
        "note": note,
    }
