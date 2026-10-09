"""The data catalog: every table and column described, in the Nakoa Brain's format.

The YAML shape is the one ``config/data_catalog.yaml`` has in the Brain:

    views:
      <table>:
        description, grain, use_for, typical_questions[], important
        columns: [{name, type, description, definition}]
    join_relationships: [{view_a, view_b, keys[]}]
    join_notes: [str]
    query_examples: [{name, sql}]
    ai_warnings: [str]

``description`` is the label, ``definition`` the instruction for use — the
line that stops a plausible wrong number (cents summed as euros, gross
revenue reported as net, an average of daily rates instead of a rate).

``render_catalog`` follows the Brain's schema rendering
(``_format_view`` / ``_format_columns`` / ``_format_joins_filtered`` /
``_format_examples_filtered`` / ``_format_warnings`` in
``src/adp/services/data_chat_schema.py`` at b054abe, 2026-09-28), without its
per-client filtering, KPI registry and coverage probe.

``views=`` narrows the rendering to a selection, as the Brain does for its
view router (#1052, 2026-10-06): only the selected views are described, and
the join table and the query patterns follow — a join or a pattern appears
only when every table it names is selected. The general notes stay, because
they are rules about the data, not about one table.
"""

from __future__ import annotations

import re

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass(frozen=True)
class CatalogColumn:
    name: str
    type: str = ""
    description: str = ""
    definition: str = ""


@dataclass(frozen=True)
class CatalogView:
    name: str
    description: str
    grain: str = ""
    use_for: str = ""
    typical_questions: tuple[str, ...] = ()
    important: str = ""
    columns: tuple[CatalogColumn, ...] = ()


@dataclass(frozen=True)
class Catalog:
    views: dict[str, CatalogView]
    join_relationships: list[dict] = field(default_factory=list)
    join_notes: list[str] = field(default_factory=list)
    query_examples: list[dict] = field(default_factory=list)
    ai_warnings: list[str] = field(default_factory=list)


def load_catalog(path: str | Path) -> Catalog:
    """Read a catalog file. Fails loud: no file or no ``views`` is an error."""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not raw.get("views"):
        raise ValueError(f"{path}: no 'views:' section")
    views = {}
    for name, v in raw["views"].items():
        views[name] = CatalogView(
            name=name,
            description=v.get("description", "").strip(),
            grain=v.get("grain", "").strip(),
            use_for=v.get("use_for", "").strip(),
            typical_questions=tuple(v.get("typical_questions") or ()),
            important=(v.get("important") or "").strip(),
            columns=tuple(
                CatalogColumn(
                    name=c["name"],
                    type=c.get("type", ""),
                    description=(c.get("description") or "").strip(),
                    definition=(c.get("definition") or "").strip(),
                )
                for c in v.get("columns") or ()
            ),
        )
    return Catalog(
        views=views,
        join_relationships=list(raw.get("join_relationships") or []),
        join_notes=list(raw.get("join_notes") or []),
        query_examples=list(raw.get("query_examples") or []),
        ai_warnings=list(raw.get("ai_warnings") or []),
    )


def _format_columns(view: CatalogView) -> str:
    lines = []
    for col in view.columns:
        if col.description and col.definition:
            suffix = f": {col.description} — {col.definition}"
        elif col.description or col.definition:
            suffix = f": {col.description or col.definition}"
        else:
            suffix = ""
        type_part = f" ({col.type})" if col.type else ""
        lines.append(f"- {col.name}{type_part}{suffix}")
    return "\n".join(lines)


def _format_view(view: CatalogView) -> str:
    parts = [f"### {view.name}", view.description]
    if view.grain:
        parts.append(view.grain)
    if view.use_for:
        parts.append(f"Use this for: {view.use_for}")
    if view.typical_questions:
        parts.append("Typical questions: " + ", ".join(f'"{q}"' for q in view.typical_questions))
    if view.important:
        parts.append(f"**Important:** {view.important}")
    parts.append("Columns:")
    parts.append(_format_columns(view))
    return "\n".join(parts)


def tables_in(sql: str, names) -> set[str]:
    """The catalog tables ``sql`` names, as whole words — bare, in a
    ``{placeholder}`` or qualified (`project.dataset.table`)."""
    return {n for n in names if re.search(rf"(?<!\w){re.escape(n)}(?!\w)", sql)}


def render_views(catalog: Catalog, names) -> str:
    """Just the entries of ``names``, in catalog order — what the interpretation
    step of the selected stage reads about the views its query used."""
    return "\n\n".join(_format_view(catalog.views[n]) for n in sorted(catalog.views) if n in set(names))


def render_catalog(catalog: Catalog, *, qualify=lambda t: t, views=None) -> str:
    """The catalog as the markdown block that goes into the SQL prompt.

    ``views`` limits it to those views (and the joins and patterns among
    them); None renders everything.
    """
    keep = set(catalog.views) if views is None else set(views) & set(catalog.views)
    relationships = [r for r in catalog.join_relationships if {r["view_a"], r["view_b"]} <= keep]
    examples = [e for e in catalog.query_examples if tables_in(e["sql"], catalog.views) <= keep]

    parts = ["## Available Tables", ""]
    for name in sorted(keep):
        parts.append(_format_view(catalog.views[name]))
        parts.append("")

    if relationships:
        parts += [
            "## Table Relationships (for JOINs)",
            "",
            "| Table A | Table B | JOIN keys |",
            "|---------|---------|-----------|",
        ]
        for rel in relationships:
            keys = ", ".join(f"`{k}`" for k in rel["keys"])
            parts.append(f"| {rel['view_a']} | {rel['view_b']} | {keys} |")
        for note in catalog.join_notes:
            parts.append(f"- {note}")
        parts.append("")

    if examples:
        parts.append("## Query Patterns")
        for ex in examples:
            sql = ex["sql"].strip()
            for table in catalog.views:
                sql = sql.replace(f"{{{table}}}", qualify(table))
            parts.append(f"\n### {ex['name']}")
            parts.append(f"```sql\n{sql}\n```")
        parts.append("")

    if catalog.ai_warnings:
        parts.append("## Important Notes")
        parts += [f"- {w}" for w in catalog.ai_warnings]

    return "\n".join(parts).rstrip() + "\n"
