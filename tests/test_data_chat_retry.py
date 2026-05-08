"""Tests for the SQL retry mechanism in data_chat service."""
from unittest.mock import MagicMock, patch, call
import pytest
from google.api_core.exceptions import BadRequest


def test_generate_sql_includes_correction_turn():
    """generate_sql with previous_sql+bq_error adds correction messages."""
    from adp.services.data_chat import generate_sql
    from datetime import date

    mock_response = MagicMock()
    mock_response.stop_reason = "end_turn"
    mock_response.content = [MagicMock(text="SELECT date, cost FROM t LIMIT 10")]
    mock_response.usage = MagicMock(
        input_tokens=100, output_tokens=20,
        cache_read_input_tokens=0, cache_creation_input_tokens=0,
    )

    with patch("adp.services.data_chat._anthropic_client") as mock_client_fn:
        mock_client = MagicMock()
        mock_client_fn.return_value = mock_client
        mock_client.messages.create.return_value = mock_response

        generate_sql(
            question="Show daily cost",
            dataset="adp_test",
            gcp_project="test-project",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
            previous_sql="SELECT date, SUM(cost) FROM t",
            bq_error="SELECT list expression references column cost which is neither grouped nor aggregated",
        )

        call_args = mock_client.messages.create.call_args
        messages = call_args.kwargs["messages"]

        # Should have: user (question), assistant (bad sql), user (error fix request)
        assert len(messages) == 3
        assert messages[0]["role"] == "user"
        assert messages[1]["role"] == "assistant"
        assert "SELECT date, SUM(cost) FROM t" in messages[1]["content"]
        assert messages[2]["role"] == "user"
        assert "BigQuery error" in messages[2]["content"]


def test_run_query_retries_on_bad_request(tmp_path):
    """run_query retries SQL generation when BQ returns BadRequest."""
    from adp.services.data_chat import run_query

    mock_cfg = MagicMock()
    mock_cfg.name = "Test Client"
    mock_cfg.bq_dataset = "adp_test"

    mock_df = MagicMock()
    mock_df.empty = False
    mock_df.__len__ = lambda self: 5
    mock_df.head.return_value = mock_df
    mock_df.to_dict.return_value = []
    mock_df.to_markdown.return_value = "| col |"

    mock_answer_response = MagicMock()
    mock_answer_response.content = [MagicMock(text="Some insight.")]
    mock_answer_response.usage = MagicMock(
        input_tokens=50, output_tokens=10,
        cache_read_input_tokens=0, cache_creation_input_tokens=0,
    )

    with (
        patch("adp.services.data_chat.generate_sql", side_effect=["SELECT bad SQL", "SELECT fixed SQL"]) as mock_gen,
        patch("adp.services.data_chat.validate_sql", return_value=(True, "")),
        patch("adp.services.data_chat.execute_query", side_effect=[
            BadRequest("GROUP BY required"),
            (mock_df, "job-123"),
        ]),
        patch("adp.services.data_chat.interpret_results", return_value=("answer", None)),
        patch("adp.clients.load_clients", return_value={"testclient": mock_cfg}),
        patch("adp.config.settings") as mock_settings,
    ):
        mock_settings.gcp_project = "test-project"
        result = run_query("testclient", "Show daily cost")

    assert "error" not in result
    assert mock_gen.call_count == 2
    # Second call should include previous_sql and bq_error
    second_call = mock_gen.call_args_list[1]
    assert second_call.kwargs.get("previous_sql") == "SELECT bad SQL LIMIT 1000"
    assert "GROUP BY required" in second_call.kwargs.get("bq_error", "")
