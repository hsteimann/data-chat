"""Architecture boundary test for the reasoning layer.

Reasoning consumers (Insights, Data Chat, Alerts, Feedback) must go through
``adp.data_context`` and **not** import from ``adp.services.registry``. The
import surface is how design principle 4 of the data-context plan is enforced
mechanically — see ``docs/plan-data-context-api.md``.

This test is currently expected to fail: at the start of Phase 1a none of the
consumers have been migrated yet, and ``adp.services.data_chat_schema``
explicitly imports ``RegistryService``. The migration happens in Phase 1b/1c.
The xfail keeps the gate visible in the test report so we notice the moment
it flips green.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

# Source files that constitute the reasoning layer. Anything that takes a
# `client_id` and produces text/charts/insights belongs here.
_REASONING_CONSUMERS: tuple[str, ...] = (
    "src/adp/services/insights.py",
    "src/adp/services/insights_store.py",
    "src/adp/services/insight_state.py",
    "src/adp/services/data_chat.py",
    "src/adp/services/data_chat_prompts.py",
    "src/adp/services/data_chat_render.py",
    "src/adp/services/data_chat_schema.py",
    "src/adp/services/alerts.py",
    "src/adp/services/feedback.py",
)

_FORBIDDEN_PREFIX = "adp.services.registry"


def _imports_registry(file_path: Path) -> bool:
    """Return True if ``file_path`` imports anything from adp.services.registry."""
    tree = ast.parse(file_path.read_text(), filename=str(file_path))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module and node.module.startswith(_FORBIDDEN_PREFIX):
                return True
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith(_FORBIDDEN_PREFIX):
                    return True
    return False


@pytest.mark.xfail(
    reason=(
        "Enabled after Phase 1b/1c migration. data_chat_schema.py still "
        "imports RegistryService directly until it's switched to "
        "adp.data_context."
    ),
    strict=False,
)
def test_reasoning_consumers_do_not_import_registry():
    repo_root = Path(__file__).resolve().parents[1]
    offenders: list[str] = []
    for rel in _REASONING_CONSUMERS:
        path = repo_root / rel
        if not path.exists():
            continue
        if _imports_registry(path):
            offenders.append(rel)
    assert not offenders, (
        f"Reasoning consumers must not import {_FORBIDDEN_PREFIX}: {offenders}"
    )
