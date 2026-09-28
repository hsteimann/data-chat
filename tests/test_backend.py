import pytest

from data_chat.backend import BigQueryBackend, DuckDbBackend, SqlRejected


def test_duckdb_runs_a_query(backend):
    df = backend.execute("SELECT COUNT(*) AS n FROM campaigns")
    assert int(df.n[0]) == 8


@pytest.mark.parametrize("sql", [
    "SELECT revenue FROM shop_orders_daily",      # unknown column
    "SELECT * FROM orders",                       # unknown table
    "SELEC 1",                                    # syntax
])
def test_duckdb_refusal_becomes_sql_rejected_with_its_message(backend, sql):
    with pytest.raises(SqlRejected) as caught:
        backend.execute(sql)
    assert str(caught.value)  # the database's own words go back to the model


def test_duckdb_opens_read_only(backend):
    with pytest.raises(Exception):
        backend.execute("DELETE FROM campaigns")
    assert int(backend.execute("SELECT COUNT(*) AS n FROM campaigns").n[0]) == 8


def test_missing_database_file_says_what_to_do(tmp_path):
    with pytest.raises(FileNotFoundError, match="demo-data"):
        DuckDbBackend(tmp_path / "nope.duckdb")


def test_bigquery_qualifies_tables():
    b = BigQueryBackend("proj", "ds", client=object())
    assert b.qualify("campaigns") == "`proj.ds.campaigns`"


def test_bigquery_refusal_becomes_sql_rejected():
    exceptions = pytest.importorskip("google.api_core.exceptions")
    pytest.importorskip("google.cloud.bigquery")

    class Client:
        def query(self, sql, job_config=None):
            raise exceptions.BadRequest("Unrecognized name: revenue")

    with pytest.raises(SqlRejected, match="Unrecognized name"):
        BigQueryBackend("proj", "ds", client=Client()).execute("SELECT revenue FROM t")
