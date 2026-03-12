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

from chat_schema import SCHEMA_CONTEXT, SQL_GENERATION_PROMPT, INTERPRETATION_PROMPT
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
    prompt = SQL_GENERATION_PROMPT.format(
        schema=SCHEMA_CONTEXT,
        dataset=dataset,
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
        question=question,
    )

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
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
        model="claude-sonnet-4-20250514",
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


def execute_query(sql: str) -> pd.DataFrame:
    """Execute SQL query against BigQuery."""
    client = get_bq_client()
    return client.query(sql).to_dataframe(create_bqstorage_client=False)


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

def _render_chat_tab(session: dict, dataset: str, clients: dict):
    """Render the chat interface for one session."""
    session_id = session["id"]

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

    # --- Chat input ---
    if prompt := st.chat_input("Ask a question about your data...", key=f"dc_input_{session_id}"):
        session["messages"].append({"role": "user", "content": prompt})

        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                try:
                    anthropic_client = get_anthropic_client()

                    if dataset == "all":
                        query_dataset = list(clients.keys())[0]
                    else:
                        query_dataset = dataset

                    # Step 1: Generate SQL
                    sql = generate_sql(anthropic_client, prompt, query_dataset, start_date, end_date)

                    is_valid, error_msg = validate_sql(sql)
                    if not is_valid:
                        st.error(f"Invalid query: {error_msg}")
                        session["messages"].append({
                            "role": "assistant",
                            "content": f"I couldn't generate a safe query: {error_msg}",
                        })
                        st.stop()

                    sql = ensure_limit(sql)

                    with st.expander("View SQL Query", expanded=False):
                        st.code(sql, language="sql")

                    # Step 2: Execute query
                    with st.spinner("Running query..."):
                        df = execute_query(sql)

                    if df.empty:
                        answer = "The query returned no results. Try adjusting your date range or question."
                        st.markdown(answer)
                        session["messages"].append({
                            "role": "assistant",
                            "content": answer,
                            "sql": sql,
                        })
                    else:
                        cache_result(session, sql, df)

                        st.dataframe(df, width="stretch", hide_index=True, height=min(400, len(df) * 35 + 40))

                        with st.spinner("Analyzing results..."):
                            answer, chart_spec = interpret_results(anthropic_client, prompt, df)

                        st.markdown(answer)

                        if chart_spec:
                            render_chart(df, chart_spec)

                        session["messages"].append({
                            "role": "assistant",
                            "content": answer,
                            "sql": sql,
                            "chart_spec": chart_spec,
                        })

                except Exception as e:
                    error_msg = f"Error: {str(e)}"
                    st.error(error_msg)
                    session["messages"].append({
                        "role": "assistant",
                        "content": error_msg,
                    })


# ---------------------------------------------------------------------------
# Main page layout
# ---------------------------------------------------------------------------

st.title("Data Chat")
st.caption("Ask questions about your Amazon advertising data using natural language.")

clients = get_ads_clients()
if not clients:
    st.warning("No client datasets found.")
    st.stop()

client_options = {"all": "All Clients", **clients}

# --- Top bar: Client selector + New Chat button ---
col_client, col_spacer, col_new = st.columns([3, 5, 2])

with col_client:
    selected_client = st.selectbox(
        "Client",
        options=list(client_options.keys()),
        format_func=lambda k: client_options[k],
        key="dc_client",
    )

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
        _render_chat_tab(session, selected_client, clients)
