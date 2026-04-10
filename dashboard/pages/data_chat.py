"""ADP Dashboard — AI-powered data exploration chat."""

import json
import re
import sys
import uuid
from datetime import date, timedelta

import pandas as pd
import plotly.express as px
import streamlit as st
from pathlib import Path

_dashboard_dir = str(Path(__file__).resolve().parent.parent)
if _dashboard_dir not in sys.path:
    sys.path.insert(0, _dashboard_dir)

from chat_schema import build_client_schema, SQL_GENERATION_PROMPT, INTERPRETATION_PROMPT
from chat_utils import get_anthropic_client, validate_sql
from sidebar import (
    GCP_PROJECT,
    get_ads_clients,
    get_bq_client,
    client_label_from_dataset,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MAX_ROWS = 1000
MAX_CACHED_RESULTS = 20  # Max DataFrames kept in session cache


# ---------------------------------------------------------------------------
# Chat session management
# ---------------------------------------------------------------------------

def _get_chat_sessions() -> list[dict]:
    """Return list of chat sessions for the current client."""
    if "dc_sessions" not in st.session_state:
        st.session_state.dc_sessions = []
    return st.session_state.dc_sessions


def _create_session(label: str | None = None) -> dict:
    """Create a new chat session and return it."""
    sessions = _get_chat_sessions()
    idx = len(sessions) + 1
    session = {
        "id": uuid.uuid4().hex[:8],
        "label": label or f"Chat {idx}",
        "messages": [],
        "df_cache": {},
    }
    sessions.append(session)
    return session


def _get_session(session_id: str) -> dict | None:
    """Find a session by ID."""
    for s in _get_chat_sessions():
        if s["id"] == session_id:
            return s
    return None


# ---------------------------------------------------------------------------
# DataFrame result cache — per-session
# ---------------------------------------------------------------------------


def cache_result(session: dict, sql: str, df: pd.DataFrame) -> None:
    """Store a query result in the session cache."""
    cache = session["df_cache"]
    cache[sql] = df
    while len(cache) > MAX_CACHED_RESULTS:
        oldest_key = next(iter(cache))
        del cache[oldest_key]


def get_cached_result(session: dict, sql: str) -> pd.DataFrame | None:
    """Retrieve a cached query result, or None if missing."""
    return session["df_cache"].get(sql)


# ---------------------------------------------------------------------------
# Claude API integration
# ---------------------------------------------------------------------------


def generate_sql(client, question: str, dataset: str, start_date: date, end_date: date) -> str:
    """Use Claude to generate a SQL query from natural language."""
    schema = build_client_schema(GCP_PROJECT, dataset)
    prompt = SQL_GENERATION_PROMPT.format(
        schema=schema,
        dataset=dataset,
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
        question=question,
    )

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8192,
        messages=[{"role": "user", "content": prompt}],
    )

    if response.stop_reason == "max_tokens":
        raise ValueError(
            "The generated SQL was too long and got truncated. "
            "Try asking a simpler question or breaking it into smaller parts."
        )

    sql = response.content[0].text.strip()

    # Clean up: remove markdown code blocks if present
    sql = re.sub(r'^```sql\s*', '', sql)
    sql = re.sub(r'^```\s*', '', sql)
    sql = re.sub(r'\s*```$', '', sql)

    return sql.strip()


def interpret_results(client, question: str, df: pd.DataFrame) -> tuple[str, dict | None]:
    """Use Claude to interpret query results and suggest visualization."""
    if len(df) > 50:
        results_md = df.head(50).to_markdown(index=False)
        results_md += f"\n\n... (showing first 50 of {len(df)} rows)"
    else:
        results_md = df.to_markdown(index=False)

    prompt = INTERPRETATION_PROMPT.format(
        results=results_md,
        row_count=len(df),
    )

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        messages=[
            {"role": "user", "content": f"Original question: {question}"},
            {"role": "user", "content": prompt},
        ],
    )

    answer = response.content[0].text.strip()

    chart_spec = None
    chart_match = re.search(r'\{[^}]*"chart_type"[^}]*\}', answer)
    if chart_match:
        try:
            chart_spec = json.loads(chart_match.group())
            answer = answer.replace(chart_match.group(), '').strip()
        except json.JSONDecodeError:
            pass

    return answer, chart_spec


# ---------------------------------------------------------------------------
# SQL execution
# ---------------------------------------------------------------------------

def ensure_limit(sql: str) -> str:
    """Add LIMIT clause if not present."""
    sql_upper = sql.upper()
    if "LIMIT" not in sql_upper:
        sql = sql.rstrip(";") + f" LIMIT {MAX_ROWS}"
    return sql


def execute_query(sql: str) -> tuple[pd.DataFrame, str | None]:
    """Execute SQL query against BigQuery.

    Returns (DataFrame, job_id) so callers can cancel the job if needed.
    """
    client = get_bq_client()
    job = client.query(sql)
    return job.to_dataframe(create_bqstorage_client=False), job.job_id


def cancel_bq_job(job_id: str) -> None:
    """Best-effort cancellation of a running BigQuery job."""
    try:
        client = get_bq_client()
        client.cancel_job(job_id)
    except Exception:
        pass  # Job may already be finished


# ---------------------------------------------------------------------------
# Chart rendering
# ---------------------------------------------------------------------------

def render_chart(df: pd.DataFrame, spec: dict):
    """Render a Plotly chart based on Claude's specification."""
    chart_type = spec.get("chart_type", "bar")
    x = spec.get("x")
    y = spec.get("y")
    color = spec.get("color")

    if x and x not in df.columns:
        st.warning(f"Chart column '{x}' not found in results.")
        return
    if y and y not in df.columns:
        st.warning(f"Chart column '{y}' not found in results.")
        return
    if color and color not in df.columns:
        color = None

    try:
        if chart_type == "bar":
            fig = px.bar(df, x=x, y=y, color=color, height=400)
        elif chart_type == "line":
            fig = px.line(df, x=x, y=y, color=color, height=400, markers=True)
        elif chart_type == "scatter":
            fig = px.scatter(df, x=x, y=y, color=color, height=400)
        elif chart_type == "pie":
            fig = px.pie(df, names=x, values=y, height=400)
        else:
            st.warning(f"Unknown chart type: {chart_type}")
            return

        fig.update_layout(margin=dict(t=30, b=40))
        st.plotly_chart(fig, width="stretch")
    except Exception as e:
        st.warning(f"Could not render chart: {e}")


# ---------------------------------------------------------------------------
# Render a single chat session inside its tab
# ---------------------------------------------------------------------------

def _proc_key(session_id: str) -> str:
    return f"dc_proc_{session_id}"


def _cancel_processing(session_id: str) -> None:
    """Cancel the current processing pipeline for a session."""
    key = _proc_key(session_id)
    proc = st.session_state.get(key)
    if proc and proc.get("bq_job_id"):
        cancel_bq_job(proc["bq_job_id"])
    st.session_state.pop(key, None)


def _render_chat_tab(session: dict, dataset: str):
    """Render the chat interface for one session."""
    session_id = session["id"]
    proc_key = _proc_key(session_id)

    # --- Date range ---
    col_start, col_end = st.columns(2)
    start_date = col_start.date_input(
        "From",
        value=date.today() - timedelta(days=30),
        key=f"dc_start_{session_id}",
    )
    end_date = col_end.date_input(
        "To",
        value=date.today() - timedelta(days=1),
        key=f"dc_end_{session_id}",
    )

    if start_date > end_date:
        st.error("Start date must be before end date.")
        return

    st.divider()

    is_processing = proc_key in st.session_state

    # --- Display chat history ---
    for message in session["messages"]:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

            if message.get("sql"):
                with st.expander("View SQL Query"):
                    st.code(message["sql"], language="sql")

                cached_df = get_cached_result(session, message["sql"])
                if cached_df is not None and not cached_df.empty:
                    st.dataframe(cached_df, width="stretch", hide_index=True, height=min(400, len(cached_df) * 35 + 40))

                    if message.get("chart_spec"):
                        render_chart(cached_df, message["chart_spec"])

    # --- Processing pipeline (state machine) ---
    if is_processing:
        proc = st.session_state[proc_key]
        phase = proc["phase"]
        question = proc["question"]

        with st.chat_message("assistant"):
            # Cancel button — active between phases
            if st.button("Cancel", key=f"dc_cancel_{session_id}", type="secondary"):
                _cancel_processing(session_id)
                session["messages"].append({
                    "role": "assistant",
                    "content": "Cancelled.",
                })
                st.rerun()

            try:
                # ---- Phase 1: Generate SQL ----
                if phase == "generate_sql":
                    with st.spinner("Generating SQL..."):
                        anthropic_client = get_anthropic_client()
                        sql = generate_sql(
                            anthropic_client, question,
                            proc["dataset"], proc["start_date"], proc["end_date"],
                        )

                    is_valid, error_msg = validate_sql(sql)
                    if not is_valid:
                        st.error(f"Invalid query: {error_msg}")
                        session["messages"].append({
                            "role": "assistant",
                            "content": f"I couldn't generate a safe query: {error_msg}",
                        })
                        st.session_state.pop(proc_key, None)
                        st.rerun()

                    sql = ensure_limit(sql)
                    proc["sql"] = sql
                    proc["phase"] = "execute_query"
                    st.rerun()  # yield to UI so cancel button is responsive

                # ---- Phase 2: Execute BigQuery ----
                elif phase == "execute_query":
                    sql = proc["sql"]
                    with st.expander("View SQL Query", expanded=False):
                        st.code(sql, language="sql")

                    with st.spinner("Running query..."):
                        df, job_id = execute_query(sql)
                        proc["bq_job_id"] = job_id

                    if df.empty:
                        answer = "The query returned no results. Try adjusting your date range or question."
                        st.markdown(answer)
                        session["messages"].append({
                            "role": "assistant",
                            "content": answer,
                            "sql": sql,
                        })
                        st.session_state.pop(proc_key, None)
                        st.rerun()

                    cache_result(session, sql, df)
                    proc["phase"] = "interpret"
                    st.rerun()  # yield to UI

                # ---- Phase 3: Interpret results ----
                elif phase == "interpret":
                    sql = proc["sql"]
                    df = get_cached_result(session, sql)

                    with st.expander("View SQL Query", expanded=False):
                        st.code(sql, language="sql")

                    st.dataframe(df, width="stretch", hide_index=True, height=min(400, len(df) * 35 + 40))

                    with st.spinner("Analyzing results..."):
                        anthropic_client = get_anthropic_client()
                        answer, chart_spec = interpret_results(anthropic_client, question, df)

                    st.markdown(answer)

                    if chart_spec:
                        render_chart(df, chart_spec)

                    session["messages"].append({
                        "role": "assistant",
                        "content": answer,
                        "sql": sql,
                        "chart_spec": chart_spec,
                    })
                    st.session_state.pop(proc_key, None)
                    st.rerun()

            except Exception as e:
                error_msg = f"Error: {str(e)}"
                st.error(error_msg)
                session["messages"].append({
                    "role": "assistant",
                    "content": error_msg,
                })
                st.session_state.pop(proc_key, None)

    # --- Chat input (disabled while processing) ---
    if prompt := st.chat_input(
        "Ask a question about your data...",
        key=f"dc_input_{session_id}",
        disabled=is_processing,
    ):
        session["messages"].append({"role": "user", "content": prompt})

        st.session_state[proc_key] = {
            "phase": "generate_sql",
            "question": prompt,
            "dataset": dataset,
            "start_date": start_date,
            "end_date": end_date,
            "sql": None,
            "bq_job_id": None,
        }
        st.rerun()


# ---------------------------------------------------------------------------
# Main page layout
# ---------------------------------------------------------------------------

st.title("Data Chat")
st.caption("Ask questions about your Amazon advertising data using natural language.")

# Read workspace client from sidebar
selected_client = st.session_state.get("workspace_client")
clients = get_ads_clients()

if not selected_client or selected_client not in clients:
    client_label = (
        client_label_from_dataset(selected_client)
        if selected_client
        else "the selected client"
    )
    st.info(f"No Ads data available for **{client_label}**. Select a different client in the sidebar.")
    st.stop()

# --- Top bar: New Chat button ---
_, col_new = st.columns([8, 2])
with col_new:
    st.markdown("<div style='height: 28px'></div>", unsafe_allow_html=True)
    new_chat_clicked = st.button("+ New Chat", key="dc_new_chat_btn")

# --- Reset sessions when client changes ---
prev = st.session_state.get("dc_prev_client")
if prev is not None and prev != selected_client:
    st.session_state.dc_sessions = []
    st.session_state.pop("dc_active_tab", None)
    st.session_state.dc_prev_client = selected_client
    st.rerun()
st.session_state.dc_prev_client = selected_client

# --- Ensure at least one session exists ---
sessions = _get_chat_sessions()
if not sessions:
    _create_session("Chat 1")
    sessions = _get_chat_sessions()

# --- Handle new chat button ---
if new_chat_clicked:
    new_session = _create_session()
    st.session_state.dc_active_tab = new_session["label"]
    st.rerun()

# --- Build tabs ---
tab_labels = [s["label"] for s in sessions]

active = st.session_state.get("dc_active_tab")
if active not in tab_labels:
    st.session_state.dc_active_tab = tab_labels[0]

tabs = st.tabs(tab_labels)

# --- Render each tab ---
for tab, session in zip(tabs, sessions):
    with tab:
        _render_chat_tab(session, selected_client)
