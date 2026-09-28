"""Shared utilities for chat-driven dashboard pages (widget spec extraction, Claude client).

`validate_sql` is re-exported from the service layer (`adp.services.data_chat`)
so the dashboard and the MCP server share a single implementation.
"""

import json
import re

import streamlit as st

from adp.services.data_chat import validate_sql

__all__ = [
    "validate_sql",
    "extract_widget_specs",
    "clean_response",
    "get_anthropic_client",
]


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
    """Get Anthropic client, loading API key from Secret Manager.

    Shared by Data Chat and Views pages. Cached as a resource singleton.
    """
    try:
        import anthropic
    except ImportError:
        st.error("Anthropic SDK not installed. Run: `pip install anthropic`")
        st.stop()

    try:
        from adp.secrets import get_secret

        api_key = get_secret("ANTHROPIC_API_KEY")
    except Exception as e:
        st.error(f"Failed to load Anthropic API key from Secret Manager: {e}")
        st.stop()

    return anthropic.Anthropic(api_key=api_key)
