"""The database port: run a query, name a table, say which dialect to write.

The pipeline never imports a database driver. A backend answers four things:
the SQL dialect the model should write, how a table is referenced, which
tables and columns exist (for the context stage that has nothing else), and
the result of a query — raising ``SqlRejected`` when the database refuses the
SQL itself, the one error worth a retry.

``DuckDbBackend`` is the default and runs on a local file. ``BigQueryBackend``
is the database the Nakoa Brain uses; it needs the ``bigquery`` extra and a
Google Cloud credential, and it is not exercised against a live project by
this repository's tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import pandas as pd


class SqlRejected(Exception):
    """The database refused the generated SQL.

    Carries the database's own message unchanged, because that text is what
    goes back to the model in the retry turn. Same type, same role as in the
    Nakoa Brain (``data_chat_failures.SqlRejected``).
    """


@dataclass(frozen=True)
class Column:
    name: str
    type: str


class SqlBackend(Protocol):
    dialect: str

    def qualify(self, table: str) -> str:
        """How a query references *table*."""
        ...

    def list_columns(self) -> dict[str, list[Column]]:
        """Every table the model may query, with its columns."""
        ...

    def execute(self, sql: str) -> pd.DataFrame:
        """Run *sql*; raise ``SqlRejected`` if the database refuses it."""
        ...


class DuckDbBackend:
    """A local DuckDB file, opened read-only."""

    dialect = "DuckDB"

    def __init__(self, path: str | Path) -> None:
        import duckdb

        self._path = Path(path)
        if not self._path.exists():
            raise FileNotFoundError(
                f"{self._path} does not exist — run `data-chat demo-data` first."
            )
        self._duckdb = duckdb
        self._con = duckdb.connect(str(self._path), read_only=True)

    def qualify(self, table: str) -> str:
        return table

    def list_columns(self) -> dict[str, list[Column]]:
        rows = self._con.execute(
            "SELECT table_name, column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = 'main' ORDER BY table_name, ordinal_position"
        ).fetchall()
        tables: dict[str, list[Column]] = {}
        for table, column, dtype in rows:
            tables.setdefault(table, []).append(Column(column, dtype))
        return tables

    def execute(self, sql: str) -> pd.DataFrame:
        try:
            return self._con.execute(sql).fetchdf()
        except (self._duckdb.ParserException, self._duckdb.BinderException,
                self._duckdb.CatalogException, self._duckdb.ConversionException) as e:
            raise SqlRejected(str(e)) from e


class BigQueryBackend:
    """One BigQuery dataset. Needs ``uv sync --extra bigquery`` and ADC."""

    dialect = "BigQuery (GoogleSQL)"

    def __init__(self, project: str, dataset: str, *, max_bytes_billed: int = 10 * 1024**3,
                 client=None) -> None:
        if client is None:
            from google.cloud import bigquery

            client = bigquery.Client(project=project)
        self._client = client
        self._project = project
        self._dataset = dataset
        self._max_bytes_billed = max_bytes_billed

    def qualify(self, table: str) -> str:
        return f"`{self._project}.{self._dataset}.{table}`"

    def list_columns(self) -> dict[str, list[Column]]:
        df = self.execute(
            "SELECT table_name, column_name, data_type "
            f"FROM `{self._project}.{self._dataset}.INFORMATION_SCHEMA.COLUMNS` "
            "ORDER BY table_name, ordinal_position"
        )
        tables: dict[str, list[Column]] = {}
        for row in df.itertuples(index=False):
            tables.setdefault(row.table_name, []).append(Column(row.column_name, row.data_type))
        return tables

    def execute(self, sql: str) -> pd.DataFrame:
        from google.api_core.exceptions import BadRequest
        from google.cloud import bigquery

        config = bigquery.QueryJobConfig(maximum_bytes_billed=self._max_bytes_billed)
        try:
            return self._client.query(sql, job_config=config).to_dataframe()
        except BadRequest as e:
            raise SqlRejected(str(e)) from e
