"""Pydantic models for the data_context Reasoning API.

These are the typed contracts returned by `adp.data_context`. The catalog/registry
YAMLs are the source of truth — these models guard reasoning consumers against
silent schema drift in YAML.

Note: There is intentionally no `TableMetadata` here. Raw-table metadata lives in
`adp.services.registry.RegistryService` and is *not* part of the reasoning surface
(see `docs/plan-data-context-api.md`, design principle 4).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class KpiDefinition(BaseModel):
    """A business KPI with formula, unit, and reasoning hints.

    Mirrors `adp.models.registry.KpiDefinition` but with stricter typing and
    a stable shape for reasoning consumers. `key` is the registry dict key
    (e.g. ``"acos"``), `name` is the human label.
    """

    name: str
    key: str
    formula: str
    components: dict | None = None
    unit: Literal["percentage", "ratio", "currency", "score"]
    direction: Literal["lower_is_better", "higher_is_better"] | None = None
    typical_range: tuple[float, float] | None = None
    aggregation: Literal["recalculate", "sum", "none"] | None = None
    interpretation: str | None = None
    warning: str | None = None
    requires_sources: list[str] | None = None
    sql_hint: str | None = None
    note: str | None = None


class CrossSourceWarning(BaseModel):
    """A pre-cooked cross-source insight candidate ("when X disagrees with Y…")."""

    id: str
    fields: list[str]
    warning: str


class ColumnMetadata(BaseModel):
    """One column inside a queryable view or queryable raw table.

    Most fields are optional because `data_catalog.yaml` only carries
    `name`, `bq_type`, `description`, `definition` today. Richer hints
    (role, aggregation, unit, …) come from the registry layer in later
    phases — the model accepts them now so the contract is stable.
    """

    name: str
    bq_type: str | None = None
    role: Literal["timestamp", "identifier", "dimension", "metric"] | None = None
    aggregation: Literal["sum", "recalculate", "none"] | None = None
    unit: str | None = None
    attribution: str | None = None
    values: list[str] | None = None
    description: str | None = None
    definition: str | None = None


class ViewMetadata(BaseModel):
    """One queryable entry from `data_catalog.yaml: views:`.

    From the reasoning consumer's perspective everything in `list_views()` is
    "queryable" — `is_raw_table` is informative only and is *not* an API filter
    axis (see plan F2).
    """

    name: str
    is_raw_table: bool
    source: str  # "ads", "rainforest", "sc", or "system" — used by the scope filter
    description: str
    grain: str | None = None
    important: str | None = None
    use_for: str | None = None
    typical_questions: list[str] = []
    extra_context: str | None = None
    columns: list[ColumnMetadata]
