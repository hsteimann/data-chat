"""ADP Dashboard — AI-powered data exploration chat."""

import json
import re
import sys
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
# DataFrame result cache — avoids storing DataFrames in chat messages
# ---------------------------------------------------------------------------


def _get_result_cache() -> dict:
    """Return the SQL→DataFrame cache from session state."""
    if "_df_cache" not in st.session_state:
        st.session_state._df_cache = {}
    return st.session_state._df_cache


def cache_result(sql: str, df: pd.DataFrame) -> None:
    """Store a query result, evicting oldest if cache is full."""
    cache = _get_result_cache()
    cache[sql] = df
    # Evict oldest entries if over limit
    while len(cache) > MAX_CACHED_RESULTS:
        oldest_key = next(iter(cache))
        del cache[oldest_key]


def get_cached_result(sql: str) -> pd.DataFrame | None:
    """Retrieve a cached query result, or None if expired/missing."""
    return _get_result_cache().get(sql)


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
    # Convert DataFrame to markdown for Claude
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

    # Try to extract chart specification from the answer
    chart_spec = None
    chart_match = re.search(r'\{[^}]*"chart_type"[^}]*\}', answer)
    if chart_match:
        try:
            chart_spec = json.loads(chart_match.group())
            # Remove the JSON from the answer text
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

    # Validate columns exist
    if x and x not in df.columns:
        st.warning(f"Chart column '{x}' not found in results.")
        return
    if y and y not in df.columns:
        st.warning(f"Chart column '{y}' not found in results.")
        return
    if color and color not in df.columns:
        color = None  # Silently ignore missing color column

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
# Main chat interface
# ---------------------------------------------------------------------------

st.title("Data Chat")
st.caption("Ask questions about your Amazon advertising data using natural language.")

# --- Top bar: client, date range, clear chat ---
clients = get_ads_clients()
if not clients:
    st.warning("No client datasets found.")
    st.stop()

client_options = {"all": "All Clients", **clients}

col_client, col_start, col_end, col_clear = st.columns([3, 2, 2, 1])

with col_client:
    selected_client = st.selectbox(
        "Client",
        options=list(client_options.keys()),
        format_func=lambda k: client_options[k],
        key="chat_client",
    )

default_start = date.today() - timedelta(days=30)
default_end = date.today() - timedelta(days=1)

with col_start:
    start_date = st.date_input("From", value=default_start, key="chat_date_start")
with col_end:
    end_date = st.date_input("To", value=default_end, key="chat_date_end")
with col_clear:
    st.markdown("<div style='height: 5px'></div>", unsafe_allow_html=True)
    if st.button("Clear", key="clear_chat_btn"):
        st.session_state.messages = []
        st.rerun()

if start_date > end_date:
    st.error("Start date must be before end date.")
    st.stop()

# Initialize chat history
if "messages" not in st.session_state:
    st.session_state.messages = []

# Display chat history
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

        # Show SQL if present (for assistant messages)
        if message.get("sql"):
            with st.expander("View SQL Query"):
                st.code(message["sql"], language="sql")

            # Look up cached DataFrame by SQL
            cached_df = get_cached_result(message["sql"])
            if cached_df is not None and not cached_df.empty:
                st.dataframe(cached_df, width="stretch", hide_index=True, height=min(400, len(cached_df) * 35 + 40))

                # Show chart if present
                if message.get("chart_spec"):
                    render_chart(cached_df, message["chart_spec"])

# Chat input
if prompt := st.chat_input("Ask a question about your data..."):
    # Add user message to history
    st.session_state.messages.append({"role": "user", "content": prompt})

    with st.chat_message("user"):
        st.markdown(prompt)

    # Process with Claude
    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            try:
                anthropic_client = get_anthropic_client()

                # Determine dataset context
                if selected_client == "all":
                    # Use first available client as reference, Claude will handle UNION
                    dataset = list(clients.keys())[0]
                else:
                    dataset = selected_client

                # Step 1: Generate SQL
                sql = generate_sql(anthropic_client, prompt, dataset, start_date, end_date)

                # Validate SQL
                is_valid, error_msg = validate_sql(sql)
                if not is_valid:
                    st.error(f"Invalid query: {error_msg}")
                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": f"I couldn't generate a safe query: {error_msg}",
                    })
                    st.stop()

                # Ensure LIMIT
                sql = ensure_limit(sql)

                # Show SQL
                with st.expander("View SQL Query", expanded=False):
                    st.code(sql, language="sql")

                # Step 2: Execute query
                with st.spinner("Running query..."):
                    df = execute_query(sql)

                if df.empty:
                    answer = "The query returned no results. Try adjusting your date range or question."
                    st.markdown(answer)
                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": answer,
                        "sql": sql,
                    })
                else:
                    # Cache the result (not in message)
                    cache_result(sql, df)

                    # Show results table
                    st.dataframe(df, width="stretch", hide_index=True, height=min(400, len(df) * 35 + 40))

                    # Step 3: Interpret results
                    with st.spinner("Analyzing results..."):
                        answer, chart_spec = interpret_results(anthropic_client, prompt, df)

                    st.markdown(answer)

                    # Render chart if suggested
                    if chart_spec:
                        render_chart(df, chart_spec)

                    # Save to history (DataFrame stored in cache, not here)
                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": answer,
                        "sql": sql,
                        "chart_spec": chart_spec,
                    })

            except Exception as e:
                error_msg = f"Error: {str(e)}"
                st.error(error_msg)
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": error_msg,
                })
