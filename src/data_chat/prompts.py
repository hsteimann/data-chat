"""The two system prompts: one to write SQL, one to answer from the result.

Same structure as the Nakoa Brain's prompts
(``src/adp/services/data_chat_prompts.py`` at b054abe, 2026-09-28): the
context block first, then numbered rules, the question in the user turn with
the date range in front of it, and a retry turn that feeds the database's
error back. The rules are the Brain's general ones; its rules about its own
views (Amazon campaign structure, trend continuation with BigQuery's
``AI.FORECAST``) are left out, because none of those tables exist here.
"""

from __future__ import annotations

import re

SQL_SYSTEM_TEMPLATE = """You are a SQL expert for marketing and e-commerce analytics data.
Given a user question, generate a SQL query to answer it.

The database is {dialect}. Only the tables listed below exist.

{context}
## Rules
1. Write SQL for {dialect}. Reference tables exactly as listed.
2. Always include LIMIT (maximum 1000 rows).
3. For date ranges, use BETWEEN with 'YYYY-MM-DD' dates.
4. Guard every division against a zero denominator (NULLIF).
5. Return ONLY the SQL query. Start your reply DIRECTLY with `SELECT` or `WITH` — no preamble, no reasoning, no explanation, no markdown code fences.
6. For aggregations, use appropriate GROUP BY clauses.
7. Round numeric results to 2 decimal places where appropriate.
8. JOINs across tables are allowed when the question requires it. Use table aliases.
9. CTEs (`WITH name AS (...)`) are allowed and encouraged for readability.
10. This is a multi-turn conversation. Use previous questions and SQL to understand follow-up requests.
"""

DATE_LINE = "Date range: {start_date} to {end_date}"
SQL_USER_TEMPLATE = DATE_LINE + "\n\nQuestion: {question}"

RETRY_TEMPLATE = "The previous query failed with this database error:\n{error}\n\nPlease fix the SQL."

INTERPRETATION_SYSTEM = """You are a marketing and e-commerce data analyst. The user asked a question, a SQL query was run, and you received the results.

Output two parts in this order:

1. A concise, actionable answer (2-4 sentences max). Use bullet points only when listing multiple findings. Do not repeat the raw numbers row-by-row — the table is already shown.

2. ONE chart spec as JSON on its own line. Skip it only for single-value results or empty results.
   Format: {"chart_type": "bar|line|scatter|pie", "x": "<column>", "y": "<column>", "color": "<column or omit>"}

## Choosing the right chart

- **Time series** (a `date` column is present): chart_type="line", x="date", y=primary metric. Set color only if the candidate color column has ≤8 distinct values.
- **Comparing categories** at one point in time: chart_type="bar", x=category column, y=metric.
- **Composition of a total**: chart_type="pie", only with ≤6 slices. Otherwise use "bar".
- **Two metrics correlation**: chart_type="scatter", x=metric1, y=metric2.

## Hard rules

- Use only column names that actually appear in the result. Never invent a column.
- If you cannot produce a sensible chart, omit the JSON line entirely.
- Reply in the language the QUESTION is written in, and format numbers the way that language does."""

INTERPRETATION_USER_TEMPLATE = """Question: {question}

Query results ({row_count} rows):
{results}

{language_line}"""


def sql_system_prompt(dialect: str, context: str) -> str:
    return SQL_SYSTEM_TEMPLATE.format(dialect=dialect, context=context.rstrip() + "\n")


# Copied from the Brain (``question_language`` / ``answer_language_line``):
# the language line sits next to the result, last, because between a rule in
# the system prompt and the answer lie the result rows — German product
# names pulled an English question's answer into German when the rule was
# only in the system prompt.
_DE_MARKERS = frozenset(
    "welche welcher welches wie was wann warum wieviel wieviele und oder der die das "
    "den dem des ein eine einen einem einer im am um zum zur mit von bei nach für "
    "über unter ist sind war waren hat haben wurde wurden nicht kein keine letzte "
    "letzten letztes diese dieser dieses monat woche jahr quartal umsatz kosten "
    "ausgaben produkte kampagnen".split()
)
_EN_MARKERS = frozenset(
    "which what how when why many much and or the a an in on at to for of with by "
    "from is are was were has have had not no last this these month week year "
    "quarter revenue spend cost products campaigns".split()
)


def question_language(question: str) -> str | None:
    """'de' / 'en' when the question's function words make it obvious, else None."""
    words = re.findall(r"[a-zäöüß]+", question.lower())
    if any(ch in question.lower() for ch in "äöüß"):
        return "de"
    de = sum(w in _DE_MARKERS for w in words)
    en = sum(w in _EN_MARKERS for w in words)
    if de > en:
        return "de"
    if en > de:
        return "en"
    return None


def answer_language_line(question: str) -> str:
    lang = question_language(question)
    if lang == "de":
        return "Answer in German (Deutsch), with German number formatting."
    if lang == "en":
        return "Answer in English, with English number formatting."
    return "Answer in the language the question above is written in."
