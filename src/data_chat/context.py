"""The three context stages — what the model knows about the data besides the question.

``schema``   Table and column names with their types, read from the database.
             What a model gets when nobody has written anything down. (Giving
             it nothing at all would only measure that it cannot guess table
             names, which says nothing.)
``freetext`` The same, plus a hand-written note per table — the way the Nakoa
             Brain started on 2026-03-08 (``SCHEMA_CONTEXT`` in
             ``history/dashboard/chat_schema.py``): what each table holds, in a
             sentence or two, at table level.
``catalog``  The field-level data catalog: every column with a description
             and, where misuse would give a plausible wrong number, a
             definition. The Brain's state from 2026-05-07 on (``definition``
             on every column, ``history/config/data_catalog.yaml``).
``catalog_selected``
             The same catalog, but only the views a first step picked for the
             question (``selection.py``) — the Brain's view router from
             2026-10-06. Its context block is chosen per question by
             ``pipeline.ask``; ``build_context`` returns the full catalog,
             which is what it falls back to.

Between the first three stages only this block changes. The question, the
rules, the model and the database stay the same. The fourth adds a step in
front of the SQL step and changes the block per question.
"""

from __future__ import annotations

from pathlib import Path

from data_chat.backend import SqlBackend
from data_chat.catalog import load_catalog, render_catalog

STAGES = ("schema", "freetext", "catalog", "catalog_selected")
#: The stage that selects views per question before the SQL step.
SELECTED = "catalog_selected"

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FREETEXT = REPO_ROOT / "catalog" / "freetext.md"
DEFAULT_CATALOG = REPO_ROOT / "catalog" / "data_catalog.yaml"


def render_schema(backend: SqlBackend) -> str:
    parts = ["## Available Tables", ""]
    for table, columns in sorted(backend.list_columns().items()):
        parts.append(f"### {table}")
        parts += [f"- {c.name} ({c.type})" for c in columns]
        parts.append("")
    return "\n".join(parts).rstrip() + "\n"


def build_context(
    stage: str,
    backend: SqlBackend,
    *,
    freetext_path: str | Path = DEFAULT_FREETEXT,
    catalog_path: str | Path = DEFAULT_CATALOG,
) -> str:
    """The context block for *stage*."""
    if stage == "schema":
        return render_schema(backend)
    if stage == "freetext":
        note = Path(freetext_path).read_text(encoding="utf-8").strip()
        return render_schema(backend) + "\n## Notes on the data\n\n" + note + "\n"
    if stage in ("catalog", SELECTED):
        return render_catalog(load_catalog(catalog_path), qualify=backend.qualify)
    raise ValueError(f"unknown stage {stage!r} — use one of {STAGES}")


def selection_setup(stage: str, backend: SqlBackend, *, model: str,
                    catalog_path: str | Path = DEFAULT_CATALOG):
    """The ``SelectionSetup`` for the selected stage, None for the others."""
    if stage != SELECTED:
        return None
    from data_chat.pipeline import SelectionSetup

    return SelectionSetup(catalog=load_catalog(catalog_path), model=model, qualify=backend.qualify)
