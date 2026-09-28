"""Schema/prompt re-exports for the Streamlit dashboard.

The actual implementation lives in `adp.services.data_chat_schema` and
`adp.services.data_chat_prompts` — Streamlit-free, also used by the MCP
server's `query_data` tool. This shim keeps existing dashboard imports
working without duplicating logic.

``load_data_catalog`` is provided here as a thin convenience for the
dashboard's Custom-Views page, which still wants the raw YAML dict for its
template rendering. Reasoning consumers must not use this — go through
``adp.data_context`` instead.
"""

from __future__ import annotations

import yaml

from adp.config import _resolve_config_dir
from adp.services.data_chat_prompts import (
    INTERPRETATION_PROMPT,
    INTERPRETATION_SYSTEM_PROMPT,
    INTERPRETATION_USER_TEMPLATE,
    SQL_GENERATION_PROMPT,
    SQL_USER_TEMPLATE,
    build_sql_system_prompt,
)
from adp.services.data_chat_schema import build_client_schema


def load_data_catalog() -> dict | None:
    """Load the raw ``data_catalog.yaml`` dict for dashboard pages that need it.

    Returns ``None`` if the catalog is not resolvable on disk — historical
    behaviour the Custom-Views page already handles. Reasoning consumers
    must not call this; use ``adp.data_context`` for typed access.
    """
    try:
        config_dir = _resolve_config_dir()
    except FileNotFoundError:
        return None
    path = config_dir / "data_catalog.yaml"
    if not path.exists():
        return None
    with open(path) as f:
        return yaml.safe_load(f)


__all__ = [
    "INTERPRETATION_PROMPT",
    "INTERPRETATION_SYSTEM_PROMPT",
    "INTERPRETATION_USER_TEMPLATE",
    "SQL_GENERATION_PROMPT",
    "SQL_USER_TEMPLATE",
    "build_client_schema",
    "build_sql_system_prompt",
    "load_data_catalog",
]
