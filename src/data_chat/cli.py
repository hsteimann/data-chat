"""Command line: build the demo data, show a prompt, ask a question, run the evaluation.

    data-chat demo-data                       # data/demo.duckdb (generated)
    data-chat --dataset demo-large demo-data  # data/demo-large.duckdb, 35 tables (generated)
    data-chat prompt --stage catalog          # the SQL system prompt — no API key needed
    data-chat ask "What was our ad spend in August 2026?" --stage catalog
    data-chat ask "Ad spend per channel in August 2026?" --chart answer.html
    data-chat eval                            # all questions × all three stages
    data-chat --dataset demo-large ask "Ad spend per channel in August 2026?" --stage catalog_selected
    data-chat --dataset demo-large eval       # catalog against catalog_selected

DATA_CHAT_SELECT_MODEL sets the model of the selection step (default: the
same model as the SQL step).
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import os

from data_chat.context import REPO_ROOT, STAGES, build_context, selection_setup
from data_chat.datasets import DATASETS, get_dataset



def _context(args, stage: str, backend) -> str:
    ds = get_dataset(args.dataset)
    return build_context(stage, backend, freetext_path=ds.freetext, catalog_path=ds.catalog)


def _select_model(model: str) -> str:
    return os.environ.get("DATA_CHAT_SELECT_MODEL") or model


def _backend(args):
    from data_chat.backend import BigQueryBackend, DuckDbBackend

    if args.bigquery:
        project, _, dataset = args.bigquery.partition(".")
        if not dataset:
            sys.exit("--bigquery expects PROJECT.DATASET")
        return BigQueryBackend(project, dataset)
    return DuckDbBackend(args.db or get_dataset(args.dataset).db)


def _period(args) -> tuple[date, date]:
    START, END = get_dataset(args.dataset).period
    return (
        date.fromisoformat(args.start) if args.start else START,
        date.fromisoformat(args.end) if args.end else END,
    )


def cmd_demo_data(args) -> None:
    path = get_dataset(args.dataset).write_duckdb(args.db)
    print(f"Wrote GENERATED demo data ({args.dataset}) to {path}")


def cmd_prompt(args) -> None:
    from data_chat.prompts import sql_system_prompt

    backend = _backend(args)
    if args.selection or args.views:
        from data_chat.catalog import load_catalog, render_catalog
        from data_chat.selection import selection_prompt

        catalog = load_catalog(get_dataset(args.dataset).catalog)
        if args.selection:
            print(selection_prompt(catalog))
            return
        views = [v.strip() for v in args.views.split(",") if v.strip()]
        print(sql_system_prompt(backend.dialect, render_catalog(catalog, qualify=backend.qualify, views=views)))
        return
    print(sql_system_prompt(backend.dialect, _context(args, args.stage, backend)))


def cmd_ask(args) -> None:
    from data_chat.llm import llm_from_env
    from data_chat.pipeline import ask

    backend = _backend(args)
    llm, model = llm_from_env()
    start, end = _period(args)
    result = ask(
        args.question, llm=llm, model=model, backend=backend,
        context=_context(args, args.stage, backend), start_date=start, end_date=end,
        selection=selection_setup(args.stage, backend, model=_select_model(model),
                                  catalog_path=get_dataset(args.dataset).catalog),
    )
    print(f"-- stage: {args.stage} · model: {model}" + (" · retried once" if result.retried else ""))
    if args.stage == "catalog_selected":
        print(f"-- views: {', '.join(result.selected_views or []) or 'all (' + (result.selection_skipped or '') + ')'}"
              + (f" · fell back to the full catalog: {result.fallback}" if result.fallback else ""))
    tokens = sum(s.usage.prompt_tokens for s in result.steps)
    print(f"-- {len(result.steps)} model calls · {tokens:,} prompt tokens · {result.seconds:.1f} s")
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
    questions_path = args.questions or get_dataset(args.dataset).questions
    questions = load_questions(questions_path)
    stages = tuple(args.stage) if args.stage else get_dataset(args.dataset).default_stages
    outcomes = run_eval(
        questions, llm=llm, model=model, backend=backend, stages=stages,
        start_date=start, end_date=end, charts=args.charts,
        catalog_path=get_dataset(args.dataset).catalog, freetext_path=get_dataset(args.dataset).freetext,
        select_model=_select_model(model),
    )
    print(summary_table(outcomes, questions))
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = write_outcomes(
        outcomes,
        REPO_ROOT / "eval" / "results" / f"{stamp}.json",
        {"model": model, "select_model": _select_model(model), "dataset": args.dataset, "stages": list(stages), "questions": str(questions_path),
         "charts": args.charts, "run_at": stamp},
    )
    print(f"\nPer-question SQL and errors: {path}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="data-chat", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", choices=list(DATASETS), default="demo",
                        help="demo (5 tables, the original setup) or demo-large (35 tables)")
    parser.add_argument("--db", type=Path, help="DuckDB file (default: the dataset's, e.g. data/demo.duckdb)")
    parser.add_argument("--bigquery", metavar="PROJECT.DATASET", help="query BigQuery instead of DuckDB")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("demo-data", help="write the generated demo data").set_defaults(func=cmd_demo_data)

    p = sub.add_parser("prompt", help="print the SQL system prompt for a stage")
    p.add_argument("--stage", choices=STAGES, default="catalog")
    p.add_argument("--selection", action="store_true",
                   help="print the selection step's prompt (the view cards) instead")
    p.add_argument("--views", metavar="A,B", help="print the SQL prompt narrowed to these views")
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
                           help="repeatable; default: the dataset's (demo: the first three, "
                                "demo-large: catalog and catalog_selected)")
            p.add_argument("--questions", type=Path, help="default: the dataset's question set")
            p.add_argument("--charts", action="store_true",
                           help="also ask for the answer and check its chart spec (one more call per question)")
        p.add_argument("--start", help="date range start, YYYY-MM-DD (default: demo data start)")
        p.add_argument("--end", help="date range end, YYYY-MM-DD (default: demo data end)")
        p.set_defaults(func=func)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
