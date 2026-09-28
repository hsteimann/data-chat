"""Scope ↔ source mapping for the data_context API.

A *scope* is the consumer-facing partition of the reasoning surface
(``"ads"``, ``"rainforest"``, ``"sc"``). Internally the catalog and registry
work with finer-grained concepts:

- KPIs declare ``requires_sources`` listing raw-source names
  (``ads_sp_campaigns``, ``rf_products``, ``pma_orders``, …).
- Views in ``data_catalog.yaml`` are named with conventional prefixes
  (``v_ads_*`` → SQL view over ads, ``rf_*`` → Rainforest raw table,
  ``pma_*`` → PMA / Seller-Central raw tables).

This module owns those two mappings. If a fourth scope ever appears
(competitor data, GA4, …), extend the constants here — that is a deliberate
design touchpoint, not a hot-fix in five consumers.
"""

from __future__ import annotations

# Canonical scope identifiers (the only values accepted as ``scope=``).
SCOPES: tuple[str, ...] = ("ads", "rainforest", "sc")

# Raw source-name prefix → scope. Used to bucket KPI ``requires_sources`` and
# cross-source-warning fields. Order matters: longer prefixes first.
_SOURCE_PREFIX_TO_SCOPE: tuple[tuple[str, str], ...] = (
    ("ads_", "ads"),
    ("rf_", "rainforest"),
    ("pma_", "sc"),
)

# View-name prefix → scope. Used to bucket entries in ``data_catalog.yaml: views:``.
_VIEW_PREFIX_TO_SCOPE: tuple[tuple[str, str], ...] = (
    ("v_ads_", "ads"),
    ("rf_", "rainforest"),
    ("pma_", "sc"),
)

# Views that don't belong to any user-facing scope (system / meta views).
# They are kept in ``list_views()`` without a scope filter, but excluded once
# ``scope=`` is set.
_SYSTEM_VIEWS: frozenset[str] = frozenset({"data_chat_feedback_summary"})


def source_to_scope(source_name: str) -> str | None:
    """Return the scope for a raw source name, or ``None`` if unknown.

    Used for KPI filtering: a KPI is in scope ``s`` iff at least one of its
    ``requires_sources`` maps to ``s``. KPIs with no ``requires_sources`` are
    treated as scope-agnostic (callers decide whether to include them).
    """
    for prefix, scope in _SOURCE_PREFIX_TO_SCOPE:
        if source_name.startswith(prefix):
            return scope
    return None


def view_to_scope(view_name: str) -> str | None:
    """Return the scope for a view name, or ``None`` for system/meta views."""
    if view_name in _SYSTEM_VIEWS:
        return None
    for prefix, scope in _VIEW_PREFIX_TO_SCOPE:
        if view_name.startswith(prefix):
            return scope
    return None


def view_source_label(view_name: str) -> str:
    """Return the ``ViewMetadata.source`` label for a view name.

    Same as ``view_to_scope`` but never returns ``None`` — system views get the
    string ``"system"`` so the field stays non-optional in the model. Fail-loud
    if a view is wholly unrecognised; that is a YAML bug we want to see.
    """
    if view_name in _SYSTEM_VIEWS:
        return "system"
    scope = view_to_scope(view_name)
    if scope is None:
        raise ValueError(
            f"Cannot determine scope for view '{view_name}'. "
            f"Add the prefix to adp.data_context._scope or list it in _SYSTEM_VIEWS."
        )
    return scope


def assert_known_scope(scope: str) -> None:
    """Fail loud if ``scope`` is not one of the canonical scopes."""
    if scope not in SCOPES:
        raise ValueError(
            f"Unknown scope '{scope}'. Expected one of: {', '.join(SCOPES)}."
        )
