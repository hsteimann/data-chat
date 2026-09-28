"""Command line: build the demo data, show a prompt, ask a question, run the evaluation.

    data-chat demo-data                       # data/demo.duckdb (generated)
    data-chat prompt --stage catalog          # the SQL system prompt — no API key needed
    data-chat ask "What was our ad spend in August 2026?" --stage catalog
    data-chat ask "Ad spend per channel in August 2026?" --chart answer.html
    data-chat eval                            # all questions × all three stages
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from data_chat.context import REPO_ROOT, STAGES, build_context

DEFAULT_DB = REPO_ROOT / "data" / "demo.duckdb"
DEFAULT_QUESTIONS = REPO_ROOT / "eval" / "questions.yaml"


def _backend(args):
    from data_chat.backend import BigQueryBackend, DuckDbBackend

    if args.bigquery:
        project, _, dataset = args.bigquery.partition(".")
        if not dataset:
            sys.exit("--bigquery expects PROJECT.DATASET")
        return BigQueryBackend(project, dataset)
    return DuckDbBackend(args.db)


def _period(args) -> tuple[date, date]:
    from data_chat.demo_data import END, START

    return (
        date.fromisoformat(args.start) if args.start else START,
        date.fromisoformat(args.end) if args.end else END,
    )


def cmd_demo_data(args) -> None:
    from data_chat.demo_data import write_duckdb

    path = write_duckdb(args.db)
    print(f"Wrote GENERATED demo data to {path}")


def cmd_prompt(args) -> None:
    from data_chat.prompts import sql_system_prompt

    backend = _backend(args)
    print(sql_system_prompt(backend.dialect, build_context(args.stage, backend)))


def cmd_ask(args) -> None:
    from data_chat.llm import llm_from_env
    from data_chat.pipeline import ask

    backend = _backend(args)
    llm, model = llm_from_env()
    start, end = _period(args)
    result = ask(
        args.question, llm=llm, model=model, backend=backend,
        context=build_context(args.stage, backend), start_date=start, end_date=end,
    )
    print(f"-- stage: {args.stage} · model: {model}" + (" · retried once" if result.retried else ""))
    if result.sql:
        print(result.sql)
    if result.failure:
        print(f"\n[{result.failure}] {result.error}")
        return
    print()
    print(result.data.to_markdown(index=False))
    if result.answer:
        print()
        print(result.answer)
    if result.chart_spec:
        print(f"\nchart: {result.chart_spec}")
    if args.chart:
        from data_chat.page import answer_page, chart_section

        args.chart.write_text(answer_page(result, model=model, stage=args.stage), encoding="utf-8")
        print(f"chart {chart_section(result)[1]} · page written to {args.chart}")


def cmd_eval(args) -> None:
    from data_chat.evaluation import load_questions, run_eval, summary_table, write_outcomes
    from data_chat.llm import llm_from_env

    backend = _backend(args)
    llm, model = llm_from_env()
    start, end = _period(args)
    questions = load_questions(args.questions)
    stages = tuple(args.stage) if args.stage else STAGES
    outcomes = run_eval(
        questions, llm=llm, model=model, backend=backend, stages=stages,
        start_date=start, end_date=end, charts=args.charts,
    )
    print(summary_table(outcomes, questions))
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = write_outcomes(
        outcomes,
        REPO_ROOT / "eval" / "results" / f"{stamp}.json",
        {"model": model, "stages": list(stages), "questions": str(args.questions),
         "charts": args.charts, "run_at": stamp},
    )
    print(f"\nPer-question SQL and errors: {path}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="data-chat", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="DuckDB file (default: data/demo.duckdb)")
    parser.add_argument("--bigquery", metavar="PROJECT.DATASET", help="query BigQuery instead of DuckDB")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("demo-data", help="write the generated demo data").set_defaults(func=cmd_demo_data)

    p = sub.add_parser("prompt", help="print the SQL system prompt for a stage")
    p.add_argument("--stage", choices=STAGES, default="catalog")
    p.set_defaults(func=cmd_prompt)

    for name, func, helptext in (("ask", cmd_ask, "answer one question"),
                                 ("eval", cmd_eval, "score the question set per stage")):
        p = sub.add_parser(name, help=helptext)
        if name == "ask":
            p.add_argument("question")
            p.add_argument("--stage", choices=STAGES, default="catalog")
            p.add_argument("--chart", type=Path, metavar="PAGE.html",
                           help="write the answer with its chart as an HTML page (needs --extra chart)")
        else:
            p.add_argument("--stage", choices=STAGES, action="append",
                           help="repeatable; default: all three")
            p.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS)
            p.add_argument("--charts", action="store_true",
                           help="also ask for the answer and check its chart spec (one more call per question)")
        p.add_argument("--start", help="date range start, YYYY-MM-DD (default: demo data start)")
        p.add_argument("--end", help="date range end, YYYY-MM-DD (default: demo data end)")
        p.set_defaults(func=func)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
