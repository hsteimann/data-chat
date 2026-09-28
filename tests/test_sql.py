from data_chat.sql import extract_chart_spec, extract_sql, validate_sql


def test_extract_sql_strips_fences_and_preamble():
    text = "I will sum the cost.\n```sql\nSELECT SUM(cost) FROM t\n```\nThat's it."
    assert extract_sql(text) == "SELECT SUM(cost) FROM t"


def test_extract_sql_slices_from_the_query_start():
    text = "With the cents in mind, here is the query:\nWITH x AS (SELECT 1 AS a)\nSELECT a FROM x"
    assert extract_sql(text) == "WITH x AS (SELECT 1 AS a)\nSELECT a FROM x"


def test_extract_sql_cuts_prose_after_the_query():
    text = "SELECT a\nFROM t\nLIMIT 10\n\n**Notes:**\n- cost is in cents"
    assert extract_sql(text) == "SELECT a\nFROM t\nLIMIT 10"


def test_extract_sql_leaves_pure_prose_for_the_validator():
    text = "This cannot be answered from the data."
    assert extract_sql(text) == text
    assert validate_sql(text)[0] is False


def test_validate_sql_accepts_read_only_queries():
    assert validate_sql("SELECT * FROM t WHERE event = 'INSERT'") == (True, "")
    assert validate_sql("WITH a AS (SELECT 1) SELECT * FROM a")[0]


def test_validate_sql_refuses_writes():
    ok, reason = validate_sql("SELECT 1; DROP TABLE campaigns")
    assert not ok and "DROP" in reason
    assert validate_sql("DELETE FROM t")[0] is False


def test_extract_chart_spec_splits_the_json_line():
    answer, spec = extract_chart_spec('Spend fell.\n{"chart_type": "line", "x": "date", "y": "spend"}')
    assert answer == "Spend fell."
    assert spec == {"chart_type": "line", "x": "date", "y": "spend"}


def test_extract_chart_spec_handles_nested_objects_and_no_spec():
    text = 'ok {"chart_type": "line", "x": "d", "band": {"lower": "lo", "upper": "hi"}}'
    assert extract_chart_spec(text)[1]["band"] == {"lower": "lo", "upper": "hi"}
    assert extract_chart_spec("no chart here") == ("no chart here", None)
