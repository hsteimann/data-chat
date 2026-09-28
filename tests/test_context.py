import pytest

from data_chat.context import STAGES, build_context
from data_chat.prompts import sql_system_prompt


def test_schema_stage_is_what_the_database_says(backend):
    text = build_context("schema", backend)
    assert "### ads_campaign_daily" in text and "- cost (BIGINT)" in text
    assert "cents" not in text


def test_freetext_stage_adds_table_level_notes(backend):
    text = build_context("freetext", backend)
    assert text.startswith(build_context("schema", backend))
    assert "## Notes on the data" in text
    assert "cents" not in text  # table level: no field definitions


def test_catalog_stage_carries_field_definitions(backend):
    text = build_context("catalog", backend)
    assert "euro cents" in text and "19 % VAT" in text


def test_only_the_context_block_differs_between_stages(backend):
    prompts = [sql_system_prompt(backend.dialect, build_context(s, backend)) for s in STAGES]
    heads = {p.split("## Available Tables")[0] for p in prompts}
    tails = {p.split("## Rules")[1] for p in prompts}
    assert len(heads) == 1 and len(tails) == 1


def test_unknown_stage_is_refused(backend):
    with pytest.raises(ValueError, match="unknown stage"):
        build_context("everything", backend)
