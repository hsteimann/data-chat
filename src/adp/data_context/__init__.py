"""Reasoning-only data context API.

Single import surface for reasoning consumers (Insights, Data Chat, Alerts,
future briefings). Wraps the internal ``CatalogLoader`` and selectively
re-exposes parts of ``RegistryService`` that belong to the reasoning layer
(KPIs, cross-source warnings, client → source mapping).

Design principles (see ``docs/plan-data-context-api.md``):

- Reasoning ≠ raw. Raw-table metadata lives in ``RegistryService`` and is
  *not* re-exported here.
- Filters live in the API. Consumers pass ``client=`` and/or ``scope=`` and
  receive the pre-filtered slice — no per-consumer filter logic.
- Fail loud. Missing YAML / unknown scope / unknown KPI → exception.
- Caching is internal. ``reload()`` is a test hook.

Public surface (MVP):

    list_views(client=None, scope=None) -> list[str]
    get_view_metadata(view_name) -> ViewMetadata
    get_kpi(key) -> KpiDefinition
    get_kpis(client=None, scope=None) -> dict[str, KpiDefinition]
    get_cross_source_warnings(client=None, scope=None) -> list[CrossSourceWarning]
    reload() -> None
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from adp.clients import load_clients
from adp.data_context._catalog import load_views
from adp.data_context._scope import (
    SCOPES,
    assert_known_scope,
    source_to_scope,
    view_to_scope,
)
from adp.models.data_context import (
    ColumnMetadata,
    CrossSourceWarning,
    KpiDefinition,
    ViewMetadata,
)
from adp.services.data_sources import get_tables_for_sources
from adp.services.registry import RegistryService

__all__ = [
    # Pydantic models (re-exported so consumers don't reach into adp.models)
    "ColumnMetadata",
    "CrossSourceWarning",
    "KpiDefinition",
    "ViewMetadata",
    # Public API
    "list_views",
    "get_view_metadata",
    "get_kpi",
    "get_kpis",
    "get_cross_source_warnings",
    "reload",
]


# ---------------------------------------------------------------------------
# Internal bundle: loaded once per process, invalidated by reload()
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Bundle:
    views: dict[str, ViewMetadata]
    kpis: dict[str, KpiDefinition]
    warnings: list[CrossSourceWarning]


@lru_cache(maxsize=1)
def _bundle() -> _Bundle:
    """Load all reasoning context once. Idempotent within a process.

    Composition:
    - Views + columns from ``data_catalog.yaml`` via ``CatalogLoader``.
    - KPIs and cross-source warnings from ``RegistryService`` (translated into
      the reasoning-typed models from ``adp.models.data_context``).
    """
    views = load_views()
    registry = RegistryService(load_schemas=False)

    kpis = {
        key: _kpi_from_registry(key, k) for key, k in registry.registry.kpis.items()
    }
    warnings = [
        CrossSourceWarning(id=w.id, fields=list(w.fields), warning=w.warning)
        for w in registry.registry.cross_source_warnings
    ]
    return _Bundle(views=views, kpis=kpis, warnings=warnings)


def _kpi_from_registry(key: str, k) -> KpiDefinition:
    """Translate a registry ``KpiDefinition`` into the data_context model."""
    typical = None
    if k.typical_range and len(k.typical_range) == 2:
        typical = (float(k.typical_range[0]), float(k.typical_range[1]))

    return KpiDefinition(
        key=key,
        name=k.name,
        formula=k.formula,
        components=k.components or None,
        unit=k.unit,
        direction=k.direction or None,
        typical_range=typical,
        aggregation=k.aggregation or None,
        interpretation=k.interpretation or None,
        warning=k.warning or None,
        requires_sources=list(k.requires_sources) if k.requires_sources else None,
        sql_hint=None,  # not in the registry yet — reserved for Phase 1c
        note=k.note or None,
    )


def reload() -> None:
    """Drop cached bundle. Subsequent calls re-read all YAMLs.

    Test hook and operational re-load lever (e.g. when GCS-FUSE config has
    been refreshed). Cheap: total YAML is ~4.5k lines.
    """
    _bundle.cache_clear()


# ---------------------------------------------------------------------------
# Filter primitives
# ---------------------------------------------------------------------------


def _client_source_names(client: str) -> set[str]:
    """Raw source names available for ``client`` per ``clients.yaml``.

    Looks up ``clients.<key>.data_sources`` and resolves each source ID to its
    raw tables via ``data_sources.yaml`` (e.g. ``"amazon_ads"`` → all
    ``ads_*`` raw tables). Fails loud if the client key is unknown — that
    matches the rest of the API's error model.

    Note (plan F3): ``data_registry.yaml: clients.*.managed_sources`` is
    *not* consulted here.
    """
    clients = load_clients()
    cfg = clients.get(client)
    if cfg is None:
        raise KeyError(
            f"Unknown client '{client}'. "
            f"Known: {sorted(clients.keys())}"
        )
    if not cfg.data_sources:
        return set()
    return set(get_tables_for_sources(cfg.data_sources))


def _client_scopes(client: str) -> set[str]:
    """Set of scopes that have at least one source available for the client."""
    scopes: set[str] = set()
    for src in _client_source_names(client):
        s = source_to_scope(src)
        if s is not None:
            scopes.add(s)
    return scopes


# ---------------------------------------------------------------------------
# Public API — Views
# ---------------------------------------------------------------------------


def list_views(
    client: str | None = None,
    scope: str | None = None,
) -> list[str]:
    """Return queryable view names, optionally filtered.

    - ``client``: restrict to scopes that the client has data for
      (per ``clients.yaml: clients.<key>.data_sources``).
    - ``scope``: one of ``"ads"``, ``"rainforest"``, ``"sc"``.

    System/meta views (e.g. ``data_chat_feedback_summary``) are returned by
    the unfiltered call but excluded once any filter narrows the result.
    """
    if scope is not None:
        assert_known_scope(scope)

    bundle = _bundle()
    allowed_scopes: set[str] | None = None

    if client is not None:
        allowed_scopes = _client_scopes(client)
    if scope is not None:
        allowed_scopes = (
            {scope} if allowed_scopes is None else allowed_scopes & {scope}
        )

    if allowed_scopes is None:
        # No filter → everything (including system views).
        return list(bundle.views.keys())

    out: list[str] = []
    for name in bundle.views:
        view_scope = view_to_scope(name)
        if view_scope is None:
            continue  # system view, excluded once a filter is active
        if view_scope in allowed_scopes:
            out.append(name)
    return out


def get_view_metadata(view_name: str) -> ViewMetadata:
    """Return metadata for one view. Raises ``KeyError`` if unknown."""
    bundle = _bundle()
    if view_name not in bundle.views:
        raise KeyError(
            f"Unknown view '{view_name}'. "
            f"Known views: {sorted(bundle.views.keys())}"
        )
    return bundle.views[view_name]


# ---------------------------------------------------------------------------
# Public API — KPIs
# ---------------------------------------------------------------------------


def get_kpi(key: str) -> KpiDefinition:
    """Return one KPI definition by key. Raises ``KeyError`` if unknown."""
    bundle = _bundle()
    if key not in bundle.kpis:
        raise KeyError(
            f"Unknown KPI '{key}'. Known: {sorted(bundle.kpis.keys())}"
        )
    return bundle.kpis[key]


def _kpi_scopes(kpi: KpiDefinition) -> set[str]:
    """All scopes a KPI participates in.

    Derived from ``requires_sources`` first, then ``components[*].sources``
    as a fallback. The fallback matters for the canonical ratio KPIs
    (``acos``, ``roas``, ``ctr``, ``cpc``, ``cvr``) — they don't pin a single
    source via ``requires_sources`` but their components reference ads-API
    raw tables, making them ads-scoped.
    """
    scopes: set[str] = set()
    sources: list[str] = []
    if kpi.requires_sources:
        sources.extend(kpi.requires_sources)
    if kpi.components:
        for comp in kpi.components.values():
            if isinstance(comp, dict):
                sources.extend(comp.get("sources", []) or [])
    for s in sources:
        sc = source_to_scope(s)
        if sc is not None:
            scopes.add(sc)
    return scopes


def get_kpis(
    client: str | None = None,
    scope: str | None = None,
) -> dict[str, KpiDefinition]:
    """Return KPIs, optionally filtered by client and/or scope.

    Filtering rules:
    - ``client``: a KPI is included iff every entry in ``requires_sources``
      is one of the client's raw sources. KPIs without ``requires_sources``
      are always available (they don't pin specific sources).
    - ``scope``: a KPI is included iff its source set (``requires_sources``
      ∪ ``components[*].sources``) maps to ``scope`` — OR if the KPI has no
      source signal at all (purely formula-defined ratio KPIs like ``roas``,
      ``ctr``, ``cvr``, ``cpc`` are treated as scope-agnostic and always
      included). This is a pragmatic rule until those KPIs declare
      ``requires_sources`` explicitly (flagged for Phase 1c follow-up).
    """
    if scope is not None:
        assert_known_scope(scope)

    bundle = _bundle()
    client_sources: set[str] | None = (
        _client_source_names(client) if client is not None else None
    )

    out: dict[str, KpiDefinition] = {}
    for key, kpi in bundle.kpis.items():
        if client_sources is not None:
            if kpi.requires_sources and not all(
                s in client_sources for s in kpi.requires_sources
            ):
                continue
        if scope is not None:
            kpi_scopes = _kpi_scopes(kpi)
            if kpi_scopes and scope not in kpi_scopes:
                continue
        out[key] = kpi
    return out


# ---------------------------------------------------------------------------
# Public API — Cross-source warnings
# ---------------------------------------------------------------------------


def get_cross_source_warnings(
    client: str | None = None,
    scope: str | None = None,
) -> list[CrossSourceWarning]:
    """Return cross-source warnings, optionally filtered.

    A warning's "scopes" are derived from its ``fields`` (each entry is
    ``"<source>.<column>"``).

    Filtering rules:
    - ``client``: include the warning iff at least two of its referenced
      sources are available for the client. Mirrors the "warning is only
      relevant when the consumer can actually mix the sources" semantics
      already in ``RegistryService.get_warnings_for_sources``.
    - ``scope``: include the warning iff at least one of its referenced
      sources maps to ``scope``. (We deliberately don't require *all* —
      cross-source warnings *cross* scopes; the ads-vs-pma warning is
      relevant to both ads and sc consumers.)
    """
    if scope is not None:
        assert_known_scope(scope)

    bundle = _bundle()
    client_sources: set[str] | None = (
        _client_source_names(client) if client is not None else None
    )

    out: list[CrossSourceWarning] = []
    for w in bundle.warnings:
        warning_sources = {f.split(".")[0] for f in w.fields}
        if client_sources is not None:
            if len(warning_sources & client_sources) < 2:
                continue
        if scope is not None:
            if not any(source_to_scope(s) == scope for s in warning_sources):
                continue
        out.append(w)
    return out


# Surface the canonical scope tuple for callers that want to introspect
# (e.g. CLI help text). Not in __all__; reach in via ``data_context.SCOPES``.
__all__.append("SCOPES")
