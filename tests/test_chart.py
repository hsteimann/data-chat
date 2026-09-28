"""Component 2: the chart that goes with an answer.

The model chooses the chart; checking and drawing it is deterministic. These
tests hold the deterministic part and its contract with the prompt.
"""

from datetime import date

import pandas as pd
import pytest

from data_chat.chart import (
    CHART_TYPES,
    Chart,
    ChartSpecInvalid,
    chart_figure,
    check_chart,
    parse_chart_spec,
)
from data_chat.context import build_context
from data_chat.evaluation import Question, chart_as_asked, run_eval, summary_table
from data_chat.page import answer_page
from data_chat.pipeline import ask
from data_chat.prompts import INTERPRETATION_SYSTEM
from data_chat.sql import extract_chart_spec
from tests.conftest import ScriptedLlm

COLUMNS = ["channel", "spend_eur"]
PERIOD = dict(start_date=date(2026, 6, 1), end_date=date(2026, 9, 27))
SPEND_BY_CHANNEL = (
    "SELECT c.channel, SUM(d.cost) / 100 AS spend_eur FROM ads_campaign_daily d "
    "JOIN campaigns c USING (campaign_id) GROUP BY 1 ORDER BY 2 DESC"
)


class TestParse:
    def test_a_plain_spec(self):
        spec = {"chart_type": "bar", "x": "channel", "y": "spend_eur"}
        assert parse_chart_spec(spec, COLUMNS) == Chart("bar", "channel", "spend_eur")

    @pytest.mark.parametrize("spec, message", [
        ({"chart_type": "bar", "x": "campaign", "y": "spend_eur"}, "Chart column 'campaign' not found"),
        ({"chart_type": "bar", "y": "spend_eur"}, "names no x column"),
        ({"chart_type": "area", "x": "channel", "y": "spend_eur"}, "Unknown chart type: area"),
    ])
    def test_what_cannot_be_drawn_says_why(self, spec, message):
        with pytest.raises(ChartSpecInvalid, match=message):
            parse_chart_spec(spec, COLUMNS)

    def test_a_colour_the_result_lacks_is_dropped_not_fatal(self):
        spec = {"chart_type": "bar", "x": "channel", "y": "spend_eur", "color": "device"}
        assert parse_chart_spec(spec, COLUMNS).color is None


def test_the_prompt_offers_exactly_the_chart_types_the_parser_accepts():
    _, template = extract_chart_spec(INTERPRETATION_SYSTEM)
    assert tuple(template["chart_type"].split("|")) == CHART_TYPES
    assert set(template) == {"chart_type", "x", "y", "color"}


@pytest.mark.parametrize("chart_type", CHART_TYPES)
def test_every_chart_type_draws(chart_type):
    df = pd.DataFrame({"channel": ["search", "display"], "spend_eur": [3.0, 1.0]})
    fig = chart_figure(df, Chart(chart_type, "channel", "spend_eur"))
    assert len(fig.data) >= 1


def test_long_category_names_are_shortened_on_the_axis_only():
    df = pd.DataFrame({"campaign": ["x" * 40, "short"], "clicks": [1, 2]})
    fig = chart_figure(df, Chart("bar", "campaign", "clicks"))
    assert fig.layout.xaxis.ticktext[0].endswith("…")
    assert fig.data[0].x[0] == "x" * 40


def test_check_chart_says_drawn_no_chart_or_why():
    df = pd.DataFrame({"channel": ["search"], "spend_eur": [1.0]})
    assert check_chart({"chart_type": "bar", "x": "channel", "y": "spend_eur"}, df)[1] == "drawn"
    assert check_chart(None, df) == (None, "no chart")
    assert check_chart({"chart_type": "bar", "x": "nope", "y": "spend_eur"}, df)[1] == (
        "Chart column 'nope' not found in results."
    )


def test_the_page_puts_sql_before_answer_and_draws_the_result(backend):
    llm = ScriptedLlm(
        SPEND_BY_CHANNEL,
        'Search carries most of the spend.\n{"chart_type": "bar", "x": "channel", "y": "spend_eur"}',
    )
    result = ask("Ad spend per channel?", llm=llm, model="m", backend=backend,
                 context=build_context("catalog", backend), **PERIOD)
    page = answer_page(result, model="m", stage="catalog")
    assert page.index("<h2>SQL</h2>") < page.index("<h2>Answer</h2>") < page.index("<h2>Chart</h2>")
    assert "Plotly.newPlot" in page
    assert "Search carries most of the spend." in page


def test_the_page_says_why_a_chart_was_not_drawn(backend):
    llm = ScriptedLlm(
        SPEND_BY_CHANNEL,
        'Search leads.\n{"chart_type": "bar", "x": "campaign_name", "y": "spend_eur"}',
    )
    result = ask("Ad spend per channel?", llm=llm, model="m", backend=backend,
                 context=build_context("catalog", backend), **PERIOD)
    page = answer_page(result, model="m", stage="catalog")
    assert "Chart not drawn: Chart column &#x27;campaign_name&#x27; not found" in page
    assert "Plotly.newPlot" not in page


def test_eval_records_the_chart_next_to_the_score_without_changing_it(backend):
    q = Question(id="spend_by_channel", question="Ad spend per channel?",
                 expected_sql=SPEND_BY_CHANNEL)
    llm = ScriptedLlm(SPEND_BY_CHANNEL, 'ok\n{"chart_type": "pie", "x": "channel", "y": "cost"}')
    [outcome] = run_eval([q], llm=llm, model="m", backend=backend, stages=("catalog",),
                         charts=True, **PERIOD)
    assert outcome.correct
    assert outcome.chart == "Chart column 'cost' not found in results."
    assert outcome.chart_ok is False
    assert summary_table([outcome], [q]).splitlines()[-1] == "| chart as the prompt asks | 0/1 |"


def test_a_single_value_is_asked_to_have_no_chart():
    assert chart_as_asked("no chart", rows=1)
    assert not chart_as_asked("drawn", rows=1)
    assert chart_as_asked("drawn", rows=2)
    assert not chart_as_asked("no chart", rows=2)
    assert not chart_as_asked("Unknown chart type: area", rows=2)


def test_eval_without_charts_makes_no_answer_call(backend):
    q = Question(id="q", question="Ad spend per channel?", expected_sql=SPEND_BY_CHANNEL)
    llm = ScriptedLlm(SPEND_BY_CHANNEL)
    [outcome] = run_eval([q], llm=llm, model="m", backend=backend, stages=("catalog",), **PERIOD)
    assert outcome.chart is None
    assert [c["phase"] for c in llm.calls] == ["sql"]
