"""Shared utilities for chat-driven dashboard pages (SQL validation, widget spec extraction, Claude client)."""

import json
import os
import re

import streamlit as st


def validate_sql(sql: str) -> tuple[bool, str]:
    """Validate SQL is a safe read-only query.

    Returns (True, "") if valid, or (False, reason) if not.
    """
    sql_clean = sql.strip()
    if not sql_clean:
        return False, "Empty SQL query."

    # Strip leading comments (-- or /* */)
    sql_no_comments = re.sub(r"--[^\n]*", "", sql_clean)
    sql_no_comments = re.sub(r"/\*.*?\*/", "", sql_no_comments, flags=re.DOTALL)
    sql_upper = sql_no_comments.upper().strip()

    # Must start with SELECT or WITH (CTE)
    if not (sql_upper.startswith("SELECT") or sql_upper.startswith("WITH")):
        return False, "Only SELECT/WITH queries are allowed."

    # Strip string literals before keyword checking to avoid false positives
    sql_no_strings = re.sub(r"'[^']*'", "''", sql_upper)
    sql_no_strings = re.sub(r'"[^"]*"', '""', sql_no_strings)

    dangerous = [
        "INSERT", "UPDATE", "DELETE", "DROP", "TRUNCATE",
        "ALTER", "CREATE", "GRANT", "REVOKE", "MERGE",
    ]
    for keyword in dangerous:
        if re.search(rf"\b{keyword}\b", sql_no_strings):
            return False, f"Query contains forbidden keyword: {keyword}"
    return True, ""


def extract_widget_specs(text: str) -> list[dict]:
    """Extract widget_spec JSON blocks from Claude's response text."""
    specs = []
    pattern = r"```widget_spec\s*\n(.*?)```"
    for match in re.finditer(pattern, text, re.DOTALL):
        try:
            spec = json.loads(match.group(1).strip())
            specs.append(spec)
        except json.JSONDecodeError:
            continue
    return specs


def clean_response(text: str) -> str:
    """Remove widget_spec JSON blocks from response text for display."""
    return re.sub(r"```widget_spec\s*\n.*?```", "", text, flags=re.DOTALL).strip()


@st.cache_resource
def get_anthropic_client():
    """Get Anthropic client, checking for API key.

    Shared by Data Chat and Views pages. Cached as a resource singleton.
    """
    try:
        import anthropic
    except ImportError:
        st.error("Anthropic SDK not installed. Run: `pip install anthropic`")
        st.stop()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        try:
            api_key = st.secrets.get("ANTHROPIC_API_KEY")
        except Exception:
            pass

    if not api_key:
        st.error(
            "Anthropic API key not found. Set the `ANTHROPIC_API_KEY` environment variable "
            "or add it to `.streamlit/secrets.toml`."
        )
        st.stop()

    return anthropic.Anthropic(api_key=api_key)
