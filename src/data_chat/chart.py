"""The chart that goes with an answer: check the model's spec, draw it.

The model writes the spec in the same call as the answer, after it has seen
the result: one JSON line, ``{"chart_type", "x", "y", "color"}``
(`prompts.INTERPRETATION_SYSTEM`). Choosing the chart is the model's part.
Everything after that is deterministic: `parse_chart_spec` checks the spec
against the result's columns, `chart_figure` draws it.

Copied from the Nakoa Brain at ea1e586 (2026-09-28):
``src/adp/services/answer_chart.py`` (``CHART_TYPES``, ``ChartSpecInvalid``,
``parse_chart_spec``) and ``src/adp/services/answer_chart_figure.py``
(``answer_figure``, ``truncate_categorical_ticks``). Logic unchanged, with three parts left out: the trend
continuation keys ``dashed`` and ``band`` (this prompt does not offer them),
the colour pinning that keeps colours stable under the Brain's table filter
(there is no filter here), and the Brain's theme tokens (a neutral palette
instead).

`parse_chart_spec` is pure. `chart_figure` needs ``plotly``
(``uv sync --extra chart``).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import pandas as pd

#: The chart types the interpretation prompt offers.
CHART_TYPES: tuple[str, ...] = ("bar", "line", "scatter", "pie")

#: A neutral categorical palette. The Brain passes its brand palette here.
PALETTE: tuple[str, ...] = (
    "#17406D", "#F28371", "#3C8DBC", "#8FB339", "#A05195", "#F4B400", "#5F7186", "#00A6A6",
)


class ChartSpecInvalid(ValueError):
    """The spec cannot be drawn against these columns. The message says why."""


@dataclass(frozen=True)
class Chart:
    """A spec checked against a result: ``x`` and ``y`` exist in it, ``color``
    only when its column exists too."""

    chart_type: str
    x: str
    y: str
    color: str | None = None


def parse_chart_spec(spec: dict[str, Any], columns: Iterable[str]) -> Chart:
    """Check *spec* against the result's *columns*.

    Raises `ChartSpecInvalid` when the chart type is unknown or ``x``/``y`` do
    not name a column of the result. A colour column the result lacks is
    dropped instead.
    """
    cols = set(columns)
    x, y = spec.get("x"), spec.get("y")
    for axis, col in (("x", x), ("y", y)):
        if not isinstance(col, str) or not col:
            raise ChartSpecInvalid(f"Chart spec names no {axis} column.")
        if col not in cols:
            raise ChartSpecInvalid(f"Chart column '{col}' not found in results.")
    chart_type = spec.get("chart_type")
    if chart_type not in CHART_TYPES:
        raise ChartSpecInvalid(f"Unknown chart type: {chart_type}")
    color = spec.get("color")
    return Chart(chart_type, x, y, color if isinstance(color, str) and color in cols else None)


def check_chart(spec: dict | None, df: pd.DataFrame | None) -> tuple[Chart | None, str]:
    """The chart for a result, and a status: ``drawn``, ``no chart``, or the
    reason the spec cannot be drawn. The page and the evaluation both read it."""
    if not spec or df is None or df.empty:
        return None, "no chart"
    try:
        return parse_chart_spec(spec, df.columns), "drawn"
    except ChartSpecInvalid as e:
        return None, str(e)


def chart_figure(df: pd.DataFrame, chart: Chart, *, palette: Iterable[str] = PALETTE):
    """The Plotly figure for *chart* over *df*."""
    import plotly.express as px

    seq = list(palette)
    x, y, color = chart.x, chart.y, chart.color
    if chart.chart_type == "bar":
        fig = px.bar(df, x=x, y=y, color=color, height=400, color_discrete_sequence=seq)
    elif chart.chart_type == "line":
        fig = px.line(df, x=x, y=y, color=color, height=400, markers=True,
                      color_discrete_sequence=seq)
    elif chart.chart_type == "scatter":
        fig = px.scatter(df, x=x, y=y, color=color, height=400, color_discrete_sequence=seq)
    else:  # pie — parse_chart_spec admits nothing else
        fig = px.pie(df, names=x, values=y, height=400, color_discrete_sequence=seq)
    fig.update_layout(
        margin=dict(t=30, b=40),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter, sans-serif", size=12),
        legend_title_text="",
        legend=dict(orientation="h", yref="container", y=0.005, yanchor="bottom",
                    x=0, xanchor="left"),
    )
    fig.update_xaxes(gridcolor="#E3E8EE", zeroline=False)
    fig.update_yaxes(gridcolor="#E3E8EE", zeroline=False)
    truncate_categorical_ticks(fig)
    return fig


#: Tick labels longer than this are shortened (the hover keeps the full name).
TICK_LABEL_LIMIT = 24


def truncate_categorical_ticks(fig, limit: int = TICK_LABEL_LIMIT) -> None:
    """Shorten long categorical x labels — campaign names run long, and rotated
    they eat more height than the plot itself. Only str-valued axes are
    touched; dates and numbers pass through untouched."""
    cats: list[str] = []
    for trace in fig.data:
        xs = getattr(trace, "x", None)
        if xs is None:
            return
        for v in xs:
            if v is None:
                continue
            if not isinstance(v, str):
                return
            if v not in cats:
                cats.append(v)
    if not cats or max(len(c) for c in cats) <= limit:
        return
    fig.update_xaxes(
        tickvals=cats,
        ticktext=[c if len(c) <= limit else c[: limit - 1] + "…" for c in cats],
    )
