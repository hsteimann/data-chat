"""Pure helpers around the model's answer: pull out the SQL, check it, split off the chart.

Copied from the Nakoa Brain, ``src/adp/services/data_chat.py`` at b054abe
(2026-09-28): ``_extract_sql``, ``_cut_trailing_prose``, ``validate_sql``,
``extract_chart_spec``. Logic unchanged; names made public, and the
Brain-specific parts left out — the placeholder check for saved widgets and
the dataset-scope guard for its multi-client setup.
"""

from __future__ import annotations

import json
import re

_SQL_START_RE = re.compile(r"(?m)^[ \t]*(?:WITH\s+\w+\s+AS\s*\(|SELECT\b)")

#: A line at column 0 that opens prose, not SQL: markdown bold or heading, a
#: bullet, a fence. SQL lines never start that way — a continued arithmetic
#: line that begins with "-" is indented inside its SELECT.
_PROSE_LINE_RE = re.compile(r"^(?:\*\*|#{1,6}\s|[-*•]\s+\S|```)")
#: First words a line of a query can start with at column 0.
_SQL_LINE_START_RE = re.compile(
    r"^(?:[\s(),;]|--|/\*|\*/|\w+\s+AS\s*\(|(?:SELECT|FROM|WHERE|GROUP|ORDER|HAVING|QUALIFY|WINDOW|LIMIT|"
    r"UNION|INTERSECT|EXCEPT|WITH|JOIN|LEFT|RIGHT|INNER|FULL|CROSS|ON|AND|OR|CASE|WHEN|THEN|ELSE|END)\b)",
    re.IGNORECASE,
)

_FORBIDDEN_RE = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|TRUNCATE|ALTER|CREATE|GRANT|REVOKE|MERGE)\b",
    re.IGNORECASE,
)
_LINE_COMMENT_RE = re.compile(r"--[^\n]*")
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_SINGLE_QUOTED_RE = re.compile(r"'[^']*'")
_DOUBLE_QUOTED_RE = re.compile(r'"[^"]*"')


def cut_trailing_prose(sql: str) -> str:
    """Drop what the model wrote after the query.

    Observed in production: a correct query followed by a bold "notes"
    heading and four bullets. It passed the read-only check, the database
    rejected it as a syntax error, the retry did the same, and the user was
    told the question could not be answered. The query ends at the first line
    that opens prose — a markdown marker, or anything after a blank line that
    does not read as SQL.
    """
    lines = sql.splitlines()
    after_blank = False
    for i, line in enumerate(lines):
        if i and _PROSE_LINE_RE.match(line):
            return "\n".join(lines[:i]).rstrip()
        if not line.strip():
            after_blank = True
            continue
        if after_blank and not _SQL_LINE_START_RE.match(line):
            return "\n".join(lines[:i]).rstrip()
        after_blank = False
    return sql


def extract_sql(text: str) -> str:
    """Extract a bare SQL query from the model's raw response.

    Handles the three ways the model deviates from "return ONLY the SQL":
    markdown fences (stripped), a prose preamble (sliced from the first line
    that starts the real query), and prose after the query (cut by
    ``cut_trailing_prose``). The start match is case-sensitive and the WITH
    branch requires CTE structure, so an English sentence that begins with
    "With ..." is not mistaken for SQL. Pure prose comes back unchanged, so
    ``validate_sql`` fails it honestly instead of sending it to the database.
    """
    sql = text.strip()
    fenced = re.search(r"```sql\s*\n(.*?)```", sql, flags=re.DOTALL)
    if fenced:
        sql = fenced.group(1)
    sql = re.sub(r"^```sql\s*", "", sql, flags=re.MULTILINE)
    sql = re.sub(r"^```\s*", "", sql, flags=re.MULTILINE)
    sql = re.sub(r"\s*```$", "", sql)
    sql = sql.strip()
    m = _SQL_START_RE.search(sql)
    if m:
        sql = cut_trailing_prose(sql[m.start():].strip())
    return sql


def validate_sql(sql: str) -> tuple[bool, str]:
    """Check that the SQL is a read-only SELECT/WITH query.

    Comments and string literals are stripped before the keyword check, so a
    value like ``WHERE event = 'INSERT'`` is not flagged. Returns (ok, reason).
    """
    sql_clean = sql.strip()
    if not sql_clean:
        return False, "Empty SQL"

    sql_no_comments = _LINE_COMMENT_RE.sub("", sql_clean)
    sql_no_comments = _BLOCK_COMMENT_RE.sub("", sql_no_comments)
    sql_upper = sql_no_comments.upper().strip()

    if not (sql_upper.startswith("SELECT") or sql_upper.startswith("WITH")):
        return False, "Only SELECT/WITH queries are allowed."

    sql_no_strings = _SINGLE_QUOTED_RE.sub("''", sql_upper)
    sql_no_strings = _DOUBLE_QUOTED_RE.sub('""', sql_no_strings)

    m = _FORBIDDEN_RE.search(sql_no_strings)
    if m:
        return False, f"Query contains forbidden keyword: {m.group(1).upper()}"
    return True, ""


def extract_chart_spec(answer: str) -> tuple[str, dict | None]:
    """Split the chart-spec JSON off the model's answer.

    The spec may nest one level, so a flat ``{[^}]*}`` match is not enough:
    walk back from ``"chart_type"`` to each ``{`` and take the first that
    decodes to an object containing the key.
    """
    key = answer.find('"chart_type"')
    if key < 0:
        return answer, None
    decoder = json.JSONDecoder()
    for start in range(key, -1, -1):
        if answer[start] != "{":
            continue
        try:
            obj, end = decoder.raw_decode(answer, start)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and "chart_type" in obj:
            return (answer[:start] + answer[end:]).strip(), obj
    return answer, None
