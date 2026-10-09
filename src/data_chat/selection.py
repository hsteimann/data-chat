"""Pick the views a question needs before the SQL prompt is built.

The SQL prompt of the ``catalog`` stage describes every view, field by
field. A question's query uses one to three of them. So a first, small step
reads one short card per view and names the views the query may need; the
SQL prompt then describes only those (``render_catalog(views=…)``).

The mechanism follows the Nakoa Brain's view router
(``src/adp/services/data_chat_router.py``, 2026-10-06, #1052), re-described
here rather than copied:

- **Input:** one card per view — name, description, grain, what it is for, up
  to three typical questions, and the column NAMES. Not the column
  definitions: those are what the SQL step reads.
- **Output:** a forced tool call whose only argument is a list of view names
  restricted to the catalog's views (``enum``), so a name the catalog does
  not have cannot come back. No reasons: what was picked is shown next to the
  SQL and the answer instead.
- **The instruction leans towards including:** a missing view makes the
  question unanswerable, an extra one only costs tokens.
- **Below ``MIN_VIEWS`` views nothing is selected** — the whole catalog is
  already small, and a missed view would cost more than selection saves.
- **Any failure here means "no selection"**, never a failed question: the
  caller builds the full-catalog prompt. The caller also falls back to the
  full catalog when the narrowed prompt yields no query, and for the retry
  after a database error (``pipeline.ask``).

Left out on purpose, because they need what a demo does not have: the Brain
always adds a client's two most-used views (from its query log) and the
previous turn's views, and it has a keyword rule for revenue questions that
is specific to its sources.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from data_chat.catalog import Catalog, CatalogView
from data_chat.llm import NO_USAGE, LlmClient, Usage

#: Fewer views than this are not narrowed (the Brain's threshold).
MIN_VIEWS = 12

TOOL_NAME = "pick_views"

SYSTEM = """You choose the database views a SQL query needs to answer an analyst's question about a shop's sales, advertising and web analytics data. A second model writes the SQL afterwards and will see ONLY the views you choose, described in full.

Choose every view the query may need: the view or views that hold the metrics asked for, and any view it has to JOIN for names, categories or other attributes. When you are unsure whether a view is needed, include it — a missing view makes the question unanswerable, an extra one only costs a little. Most questions need one to three views.

Answer by calling the tool {tool} with the names of the views.

## The views
{cards}"""


def card(view: CatalogView) -> str:
    """One view, short: what it is and what it is for, with its column names —
    not the column definitions the SQL step reads."""
    lines = [f"### {view.name}", view.description]
    if view.grain:
        lines.append(f"Grain: {view.grain}")
    if view.use_for:
        lines.append(f"Use for: {view.use_for}")
    if view.typical_questions:
        lines.append("Typical: " + " | ".join(q.strip() for q in view.typical_questions[:3]))
    lines.append("Columns: " + ", ".join(c.name for c in view.columns))
    return "\n".join(lines)


def selection_prompt(catalog: Catalog) -> str:
    """The system prompt: the same for every question, so it caches."""
    cards = "\n\n".join(card(catalog.views[n]) for n in sorted(catalog.views))
    return SYSTEM.format(tool=TOOL_NAME, cards=cards)


def tool(names: list[str]) -> dict:
    return {
        "name": TOOL_NAME,
        "description": "The views the SQL query needs.",
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["views"],
            "properties": {
                "views": {"type": "array", "items": {"type": "string", "enum": names}},
            },
        },
    }


@dataclass
class Selection:
    """What the selection step decided.

    ``views`` is None when the full catalog is used; ``skipped`` then says why
    ("small catalog", "selection failed: …", "nothing selected").
    """

    views: list[str] | None
    skipped: str | None = None
    usage: Usage = NO_USAGE
    seconds: float = 0.0


def select_views(
    question: str,
    catalog: Catalog,
    *,
    llm: LlmClient,
    model: str,
    previous_question: str | None = None,
) -> Selection:
    """The views the narrowed SQL prompt describes, or a reason to describe all."""
    names = sorted(catalog.views)
    if len(names) < MIN_VIEWS:
        return Selection(None, "small catalog")
    user = f"Question: {question}"
    if previous_question:
        user = f"Previous question in this conversation: {previous_question}\n\n{user}"
    started = time.perf_counter()
    try:
        reply = llm.call_tool(
            phase="select",
            model=model,
            system=selection_prompt(catalog),
            messages=[{"role": "user", "content": user}],
            tool=tool(names),
            max_tokens=1024,
        )
        usage = getattr(reply, "usage", NO_USAGE)
        picked = sorted({v for v in reply.get("views") or [] if v in catalog.views})
    except Exception as e:  # any failure is "no selection", never a failed question
        return Selection(None, f"selection failed: {e}", seconds=time.perf_counter() - started)
    seconds = time.perf_counter() - started
    if not picked:
        return Selection(None, "nothing selected", usage, seconds)
    return Selection(picked, None, usage, seconds)
