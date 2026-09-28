"""One answer as a self-contained HTML page: question, SQL, answer, chart, table.

The order is the argument of this repository: the SQL comes before the
answer, and the chart is drawn from the same rows as the table underneath it.
When the model's chart spec does not fit the result, the page says why
instead of drawing something else.

Not copied from the Brain, which shows the same parts in its dashboard.
"""

from __future__ import annotations

import html

from data_chat.chart import chart_figure, check_chart
from data_chat.pipeline import Answer

_STYLE = """
body { font-family: Inter, system-ui, sans-serif; max-width: 960px; margin: 2rem auto;
       padding: 0 16px; color: #1B2733; background: #fff; line-height: 1.5; }
h1 { font-size: 1.3rem; }
h2 { font-size: .8rem; text-transform: uppercase; letter-spacing: .06em; color: #5F7186;
     margin-top: 2rem; }
pre { background: #F4F6F9; padding: 12px; overflow-x: auto; font-size: .85rem; }
table { border-collapse: collapse; font-size: .85rem; }
th, td { border-bottom: 1px solid #E3E8EE; padding: 4px 10px; text-align: right; }
th:first-child, td:first-child { text-align: left; }
.answer { white-space: pre-line; }
.note { color: #5F7186; font-size: .85rem; }
"""


def chart_section(result: Answer) -> tuple[str, str]:
    """The chart's HTML and its status (`chart.check_chart`)."""
    chart, status = check_chart(result.chart_spec, result.data)
    if chart is None and status == "no chart":
        return "<p class='note'>The model gave no chart for this result.</p>", status
    if chart is None:
        return f"<p class='note'>Chart not drawn: {html.escape(status)}</p>", status
    return chart_figure(result.data, chart).to_html(full_html=False, include_plotlyjs=True), status


def answer_page(result: Answer, *, model: str, stage: str) -> str:
    esc = html.escape
    parts = [f"<h1>{esc(result.question)}</h1>",
             f"<p class='note'>stage: {esc(stage)} · model: {esc(model)}"
             + (" · retried once" if result.retried else "") + "</p>"]
    if result.sql:
        parts += ["<h2>SQL</h2>", f"<pre>{esc(result.sql)}</pre>"]
    if result.failure:
        parts += ["<h2>No answer</h2>", f"<p>[{esc(result.failure)}] {esc(result.error or '')}</p>"]
    else:
        if result.answer:
            parts += ["<h2>Answer</h2>", f"<p class='answer'>{esc(result.answer)}</p>"]
        chart_html, _ = chart_section(result)
        parts += ["<h2>Chart</h2>", chart_html]
        parts += ["<h2>Result</h2>", result.data.to_html(index=False, border=0)]
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{esc(result.question)}</title><style>{_STYLE}</style></head><body>"
        + "\n".join(parts) + "</body></html>"
    )
