"""Internal catalog loader for ``data_catalog.yaml``.

Read-only YAML loader that produces ``ViewMetadata`` objects. Public reasoning
consumers go through ``adp.data_context``; this module is intentionally not
re-exported.

Fail-loud: a missing or malformed catalog raises immediately. Silent fallbacks
are forbidden by design principle 6 in the plan.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from adp.config import settings
from adp.data_context._scope import view_source_label
from adp.models.data_context import ColumnMetadata, ViewMetadata


def load_views(catalog_path: Path | None = None) -> dict[str, ViewMetadata]:
    """Load all views from ``data_catalog.yaml`` as ``ViewMetadata`` objects.

    Parameters
    ----------
    catalog_path:
        Override path. Defaults to ``settings.data_catalog_file``.

    Raises
    ------
    FileNotFoundError
        If the catalog file is missing.
    ValueError
        If the YAML is malformed, empty, or has no ``views:`` section.
    """
    path = catalog_path or settings.data_catalog_file

    try:
        with open(path) as f:
            raw = yaml.safe_load(f)
    except FileNotFoundError:
        raise FileNotFoundError(f"Data catalog file not found: {path}")
    except yaml.YAMLError as e:
        raise ValueError(f"Failed to parse {path}: {e}")

    if not raw:
        raise ValueError(f"Empty data catalog file: {path}")
    if "views" not in raw or not isinstance(raw["views"], dict):
        raise ValueError(f"Data catalog at {path} has no 'views:' section.")

    views: dict[str, ViewMetadata] = {}
    for name, view_raw in raw["views"].items():
        views[name] = _parse_view(name, view_raw)
    return views


def _parse_view(name: str, raw: dict) -> ViewMetadata:
    columns = [_parse_column(c) for c in raw.get("columns", [])]
    return ViewMetadata(
        name=name,
        is_raw_table=bool(raw.get("is_raw_table", False)),
        source=view_source_label(name),
        description=raw.get("description", ""),
        grain=raw.get("grain"),
        important=raw.get("important"),
        use_for=raw.get("use_for"),
        typical_questions=list(raw.get("typical_questions", []) or []),
        extra_context=raw.get("extra_context"),
        columns=columns,
    )


def _parse_column(raw: dict) -> ColumnMetadata:
    # data_catalog.yaml today only carries name/type/description/definition.
    # Richer fields (role, aggregation, unit, attribution, values) are accepted
    # for forward-compatibility but currently always None.
    return ColumnMetadata(
        name=raw["name"],
        bq_type=raw.get("type") or raw.get("bq_type"),
        role=raw.get("role"),
        aggregation=raw.get("aggregation"),
        unit=raw.get("unit"),
        attribution=raw.get("attribution"),
        values=raw.get("values"),
        description=raw.get("description"),
        definition=raw.get("definition"),
    )
