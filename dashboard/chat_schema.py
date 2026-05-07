"""Schema/prompt re-exports for the Streamlit dashboard.

The actual implementation lives in `adp.services.data_chat_schema` and
`adp.services.data_chat_prompts` — Streamlit-free, also used by the MCP
server's `query_data` tool. This shim keeps existing dashboard imports
working without duplicating logic.
"""

from adp.services.data_chat_prompts import (
    INTERPRETATION_PROMPT,
    INTERPRETATION_SYSTEM_PROMPT,
    INTERPRETATION_USER_TEMPLATE,
    SQL_GENERATION_PROMPT,
    SQL_USER_TEMPLATE,
    build_sql_system_prompt,
)
from adp.services.data_chat_schema import (
    build_client_schema,
    load_data_catalog,
)

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
