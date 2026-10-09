# data-chat

Ask a question about marketing data in plain language, get back **a SQL statement you can read and rerun**, its result, and a short answer.

The idea behind it, in one line: **first make sure the data is right, then reason about it.** The language model writes one deterministic SQL query. The number comes from the database, not from the model, and the query sits next to the answer, so anyone can check it.

This repository is an excerpt of the **Nakoa Brain**, the data platform we run for our clients at [Nakoa](https://nakoa.digital), published after the fact and made runnable on its own.

> **Demo data:** everything under `data/` is **generated** by `src/data_chat/demo_data.py`. It describes a fictional outdoor-sports shop. It is not a real business, and no client data is in this repository.

---

## How it came about

1. **Before.** Marketplace data, Google Analytics and Google Ads sat in BigQuery. Every question meant hand-written SQL, with the result shown in Looker Studio (formerly Data Studio).
2. **The idea, late 2025.** Let a language model write the SQL. Without context the results were unreliable. With a hand-written free-text description of the tables they got better.
3. **The data catalog.** A discussion with a partner company produced the insight this repository is about: **every column and every metric has to be described on its own**: what it is, how it is defined, where its limits are, and what it can be combined with. Only then does the model produce precise results.
4. **Research agents.** For the standard sources (Amazon Ads, Google Ads, Google Analytics) there are public field-level descriptions. Agents collect them and fill the catalog. Some queries only become possible this way, because the relationships between tables are finally written down. *(Not part of this repository yet.)*

Steps 1–2 predate the code history: the code existed before it was ever committed. The history here starts on 2026-03-08 with the hand-written free text already in place.

## Two layers

### Layer 1: real history (`history/`)

**An excerpt from the development of the Nakoa Brain, states from 2026-03-08 to 2026-05-09, published retrospectively.**

- 33 commits, taken from the Brain's own repository with `git filter-repo` on a fresh clone, limited to the Data Chat component: the SQL generation, its schema context, the data catalog, their tests, and four design documents.
- Author, author date and committer date of every commit are unchanged.
- The commit hashes are new, because filtering rewrites them.
- Client names, their BigQuery datasets, brand names and cloud project IDs were replaced **throughout the history**, in file contents and commit messages alike, with placeholders (`client_07`, `adp_client_07`, `Brand 07a`, `example-gcp-project`). Thirteen of the 27 commits that change files are therefore different in content. Nothing else was edited.
- Some commits are fragments: they changed mostly other parts of the Brain and touched the Data Chat code or the catalog on the side. Their message describes the whole change, while the excerpt keeps only the Data Chat part.
- The files moved under `history/` in the first commit of layer 2; `git log --follow history/<path>` walks back to 2026-03-08.
- This code is **not runnable** here. It depends on Streamlit, BigQuery and the rest of the Brain. It is here to be read.

The stages are visible in the history:

| Commit | Date | What happened |
|---|---|---|
| `761c059` | 2026-03-08 | First commit. The schema is a **hand-written free text** (`SCHEMA_CONTEXT` in `history/dashboard/chat_schema.py`). |
| `f33779d` | 2026-03-13 | The first fix for **schema drift**: the free text no longer matched the tables. See `history/docs/bug-data-chat-schema-drift.md`. |
| `c9dd91b` | 2026-04-02 | `views_registry.yaml`: views and columns as structured data. The prompt is built from it. |
| `129a84b` | 2026-04-02 | Renamed to **`data_catalog.yaml`**. |
| `dd73e38` | 2026-04-03 | The schema is filtered per client to the tables that exist. |
| `d7cb151` | 2026-05-07 | **Every column gets a `definition`**, and the definitions go into the prompt. |
| `51bbdba` | 2026-05-08 | The database's error goes back to the model for one retry. |
| `87a18a2` | 2026-05-09 | The free-text fallback is removed. The catalog is the only path from here on. |

### Layer 2: a runnable frame (the rest of the repository)

New commits from 2026-09-28 on, with their real dates. They make the pattern run on its own:

- **Ports instead of the Brain's infrastructure.** An `LlmClient` (the same two-method port the Brain uses since 2026-09-28) and a `SqlBackend`. The model is Anthropic or any OpenAI-compatible API. The database is DuckDB locally, or BigQuery as an option.
- **The Brain's pipeline shape:** context block, numbered rules, question with date range, one retry with the database error, a chart spec as a JSON line in the answer.
- **Pure helpers copied from the Brain** (`src/data_chat/sql.py`, each marked with its origin): SQL extraction from the model's reply, the read-only check, chart-spec extraction.
- **The catalog format of the Brain** (`catalog/data_catalog.yaml`) for the demo data.
- **The same question at three stages**, and an evaluation that scores them.
- **The chart after the answer** (component 2, see below): the model's chart spec checked against the result and drawn with Plotly, copied from the Brain.

## Quickstart

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run data-chat demo-data                 # writes data/demo.duckdb (generated)
uv run pytest                              # offline, no API key

# See what the model would be given, per stage. No API key needed:
uv run data-chat prompt --stage schema
uv run data-chat prompt --stage catalog
```

With a model:

```bash
uv sync --extra anthropic
export ANTHROPIC_API_KEY=...
uv run data-chat ask "What was our net revenue in August 2026?" --stage catalog
uv run data-chat eval                      # 10 questions × 3 stages

# The answer with its chart as a self-contained HTML page:
uv sync --extra anthropic --extra chart
uv run data-chat ask "What was our ad spend per channel in August 2026?" --chart answer.html
uv run data-chat eval --stage catalog --charts   # also checks each chart spec
```

The larger dataset and the fourth stage (see [below](#the-fourth-stage-only-the-views-the-question-needs)):

```bash
uv run data-chat --dataset demo-large demo-data                   # data/demo-large.duckdb, 35 tables (generated)
uv run data-chat --dataset demo-large prompt --selection          # the selection step's prompt, no API key
uv run data-chat --dataset demo-large ask "What was our net revenue after returns in August 2026?" --stage catalog_selected
uv run data-chat --dataset demo-large eval                        # 20 questions × catalog and catalog_selected
```

Other providers: `uv sync --extra openai` and `DATA_CHAT_LLM_PROVIDER=openai` (plus `OPENAI_BASE_URL` for a compatible gateway). Choose the model with `DATA_CHAT_MODEL`. BigQuery: `uv sync --extra bigquery`, then `--bigquery PROJECT.DATASET`.

## The three stages

Between the stages, only the context block of the prompt changes. The question, the rules, the model and the database stay the same.

| Stage | The model is given | Corresponds to |
|---|---|---|
| `schema` | Table and column names with their types, read from the database | nobody has written anything down |
| `freetext` | The same, plus a hand-written note per table (`catalog/freetext.md`) | the Brain from 2026-03-08 |
| `catalog` | Every column described, with a definition wherever misuse gives a plausible wrong number (`catalog/data_catalog.yaml`) | the Brain from 2026-05-07 |

The free-text note is written **at table level** on purpose. Table level versus field level is the variable being tested. The notes are accurate and in good faith; they just do not go down to the column.

The demo data contains the properties that turn a plausible query into a wrong number, as real marketing data does:

- ad cost stored in **cents**
- shop revenue **including VAT**
- traffic with **one row per day and channel**
- rates that must be **ratios of sums**
- campaign names that exist **only in a dimension table**

`eval/questions.yaml` holds ten questions, each with the trap it contains and a reference query. The evaluation compares the result table of the generated SQL with the reference result, not the prose answer. Scoring rules are in `src/data_chat/evaluation.py`.

## Results

Measured on 2026-09-28 with **`claude-haiku-4-5`**, three runs of all ten questions per stage. The per-question SQL of every run is in `eval/runs/2026-09-28-claude-haiku-4-5/`.

| Question (trap) | schema | freetext | catalog |
|---|---|---|---|
| spend_august (cost in cents) | 0/3 | 0/3 | 3/3 |
| roas_by_channel (cents, join for channel) | 1/3 | 1/3 | 3/3 |
| net_revenue_august (VAT included) | 0/3 | 0/3 | 3/3 |
| return_rate_by_category (join, ratio of sums) | 3/3 | 3/3 | 3/3 |
| top_campaigns_clicks (join for names) | 3/3 | 3/3 | 3/3 |
| paid_search_conversion_rate (channel vocabulary) | 0/3 | 0/3 | 3/3 |
| avg_daily_sessions (five rows per day) | 0/3 | 0/3 | 3/3 |
| display_ctr (join, ratio of sums) | 3/3 | 3/3 | 3/3 |
| running_units_september (join for category) | 3/3 | 3/3 | 3/3 |
| cost_per_order (cost in cents) | 0/3 | 0/3 | 3/3 |
| **all** | **13/30** | **13/30** | **30/30** |

What the failures look like, from the recorded SQL:

- Without the catalog the model sums `cost` as euros (100× too high). For ROAS it once divided by 100 on its own, in the other two runs it did not.
- It guesses the channel value and finds nothing: `'paid search'` with the schema alone, `'search'` with the free text, in all three runs. The value is `paid_search`. The free-text word comes from the note on the *campaigns* table ("channel (search or display)"), carried over to web traffic, which uses other values. The catalog's definition of `campaigns.channel` warns about exactly this.
- It takes `AVG(sessions)` over rows that are one per day **and channel**.
- It reports gross revenue as revenue (no division by 1.19 in any run).

Read these numbers with their limits:

- **One small model.** Haiku is what the sandbox this was built in allows. The Brain runs a larger model, not measured here.
- **Ten questions, written together with the demo data.** The traps are real ones, but they are chosen, so this shows the mechanism, not a rate you should expect elsewhere.
- **Free text = schema here.** The free-text note is table level, and every miss above is a field-level trap, so the note changes nothing. In the Brain's own history, free text was the step up from *no* context at all. This setup does not measure that step: its baseline already has the table and column names.
- **Scored on the result table** (`src/data_chat/evaluation.py`), not on the prose answer.

## The fourth stage: only the views the question needs

The three stages above ask how **well** the data has to be described. The fourth asks how **much** of that description the model should see for one question.

A real client's platform has dozens of views, and their catalog entries are long. Putting all of them into every SQL prompt is expensive, and the views that are easy to confuse all sit next to each other. The Nakoa Brain therefore runs a step first (since 2026-10-06): a small model reads one short card per view and names the views the question needs; the SQL prompt then describes only those.

`catalog_selected` does the same here, re-described rather than copied from the Brain (`src/data_chat/selection.py`):

1. **Selection.** One card per view: description, grain, what it is for, up to three typical questions, the column *names*. Not the column definitions; those are for the SQL step. The reply is structured output: a list of view names, restricted to the catalog's views by the schema, so an invented name cannot come back. The prompt leans towards including, because a missing view makes the question unanswerable and an extra one only costs tokens. The cards are the same for every question, so this prompt is cached.
2. **SQL.** The catalog, but only the selected views, and only the joins and query patterns among them. The general notes stay.
3. **Interpretation.** The question, the result and the catalog entries of the views the query actually used.

The selected views are shown next to the SQL and the answer (`ask`, `ask --chart`), so it is visible what the answer rests on.

**Fallbacks**, as in the Brain: no selection below 12 views; a failed or empty selection runs on the full catalog; a narrowed prompt that yields no query on the catalog's tables is asked once more with the full catalog; the retry after a database error always gets the full catalog. **Left out**, because a demo has nothing to feed them: the Brain always adds a client's two most-used views (from its query log) and the previous turn's views, and it has a keyword rule for revenue questions that is specific to its sources.

### The large dataset

Five tables cannot show this, so `demo-large` describes the same fictional shop the way a client's platform sees it: own web shop, two marketplaces, five ad channels and web analytics. It has **35 tables and 300 columns**, all **generated** (`src/data_chat/demo_large.py`, fixed seed). It is built to be confusable, as real data is:

- the same figures as a daily, a weekly and a monthly table;
- one table per ad channel with similar columns, in micros, cents or euros, and a cross-channel table whose conversions mix attribution windows;
- gross and net revenue, revenue before and after returns, and a marketplace that reports net next to one that reports gross;
- the shop's orders under last-click, first-click and data-driven attribution, with the same total and a different split per channel;
- two deprecated `*_v1` tables next to their successors;
- tables close to a question's subject that do not answer it (inventory, fees, site search, email, budgets);
- the columns real exports carry, many of them precomputed per-row ratios (`ctr`, `acos_14d`, `frequency`) that are right on their row and wrong when averaged.

Every aggregate is computed from the rows below it and checked by a test, so each question has one right answer. The catalog (`catalog/demo-large/data_catalog.yaml`) describes every column. As an SQL prompt it is **16,437 tokens**, counted with the API's token counter for `claude-haiku-4-5`, against 1,886 for the five-table demo.

`eval/demo-large/questions.yaml` holds **twenty questions**, written and committed before the first run. Each has its trap, a reference query and the views a correct answer needs (`a|b` where either will do). The selection is scored against those: **recall** (were all needed views picked?) and **precision** (how many of the picked views were needed?).

### Results

Measured on 2026-10-09 with **`claude-haiku-4-5`** for every step, three runs of all twenty questions per stage. Every run is in `eval/runs/2026-10-09-claude-haiku-4-5-demo-large/`, with the SQL, the views the SQL step saw, and the tokens and time of each model call.

| Stage | correct | correct, two-decimal rounding counts | prompt tokens / question (selection + SQL) | cost / question, cache warm | cost / question, cache cold | seconds / question |
|---|---|---|---|---|---|---|
| `schema` | 32/60 | 35/60 | 3,659 | $0.0043 | — | 1.7 |
| `freetext` | 35/60 | 39/60 | 4,006 | $0.0046 | — | 1.7 |
| `catalog` | **52/60** | **56/60** | 16,437 | $0.0022 | $0.0210 | 1.7 |
| `catalog_selected` | **47/60** | **53/60** | 5,444 + 1,321 | $0.0025 | $0.0087 | 2.9 |

Selection: **98 % recall, 96 % precision**, and no fallback to the full catalog in 60 questions.

- **Cost, cache warm** is what was measured. The questions ran back to back, so the full catalog was read from the prompt cache at a tenth of the price almost every time. **Cost, cache cold** is computed from the same token counts for questions that arrive with pauses in between, so the cache has to be written again. That is the usual case in the Brain's real traffic. Prices are the Haiku 4.5 list prices: $1 input, $5 output, $1.25 cache write and $0.10 cache read per million tokens.
- **Two-decimal rounding:** the SQL prompt asks for two decimals, and the strict scorer accepts a rounded value only from 1 upwards. A correct query for a rate of 0.1153 that returns 0.12 therefore counts as wrong. The second column also accepts that. Both are reported; the strict one is the score of record, as in the results above.

What this shows, and what it does not:

- **Accuracy did not improve here.** With the whole catalog the model was right slightly more often: 52 against 47 (strict), 56 against 53 (with rounding). On twenty questions that is one or two questions; it is not a rate.
- **The SQL step sees 92 % less catalog** (1,321 instead of 16,437 tokens). What that saves depends on the cache. With a warm cache it saves nothing: the narrowed prompt is too short to be cached, and the selection is one more call. With a cold cache it saves about 60 % per question.
- **It is slower.** One more model call means 2.9 instead of 1.7 seconds. The Brain's own measurement came to the same conclusion: the selection saves cost, not time.

From the recorded runs, three cases worth looking at:

- **The full catalog picks the wrong table.** *"How many orders did we receive in the week from Monday 10 August to Sunday 16 August 2026?"* With the whole catalog the model was right 0 of 3 times: it used `shop_sales_weekly` with `week_start = '2026-08-12'`, a Wednesday, so no row matched. With the selection it was right 3 of 3 times, from `shop_sales_daily`.
- **The selection silently misses views it needs.** *"What share of the units ordered in June 2026 was returned, per product category?"* The selection picked `shop_product_sales_daily`, `shop_returns` and `products`, but not `shop_order_items` and `shop_orders`, which the question needs. The result was 0 of 3, with return rates above 100 %. The fallback did not help, because a query came back, just on the wrong tables. This is the new failure the step brings.
- **The selection removes context that lived in another view.** *"Under first-click attribution, how many purchases did paid social start in July 2026?"* With the selection the model was right 0 of 3 times: it filtered on `'Paid Social'`. The values (`paid_social`, …) are listed in the description of `web_sessions_daily`, which a model with the full catalog sees and the narrowed prompt does not. Once a model only sees a few entries, each entry has to stand on its own. The catalog was not changed after this was found.

Read these numbers with their limits:

- **One small model, one dataset, twenty chosen questions.** The traps are real ones, but they were chosen. This shows the mechanism, not a rate to expect elsewhere. An attempt with a larger model could not run from the environment this was built in and is not reported.
- **The catalog here is small for the purpose.** At about 16,000 tokens the full catalog is long, but a model can still keep it in view. In the Brain a client's SQL prompt is many times that size, and that is where the selection was introduced. Whether the accuracy picture changes with a catalog that large is not measured here.
- **The catalog's query patterns** cover some of the calculations the questions need, such as a ratio of sums or a return-rate cohort. They are in the full catalog and, when their tables are selected, in the narrowed one.
- **Scored on the result table**, not on the prose answer. The answer step was not run in this evaluation.

> Background and discussion: *[link to the post on steimann.de, to be added]*

## The chart after the answer

The second component of the Brain's Data Chat: a chart drawn from the result, next to the SQL and the answer.

**The model chooses, the code draws.** In the same call that writes the answer, after it has seen the result rows, the model adds one JSON line: `{"chart_type": "bar|line|scatter|pie", "x": …, "y": …, "color": …}` (rules in `src/data_chat/prompts.py`: a date column → line, categories → bar, a pie only up to six slices, no chart for a single value). Everything after that is deterministic:

- `parse_chart_spec` checks the spec against the result's columns. An unknown type or an `x`/`y` the result does not have is refused with the reason. A missing colour column is dropped.
- `chart_figure` draws it with Plotly.
- `data-chat ask --chart page.html` writes one page: the question, **the SQL first**, the answer, the chart, and the table it was drawn from. When the spec does not fit, the page says why instead of drawing something else.

In the Brain the same contract feeds three renderers: the dashboard (Plotly), an inline PNG for MCP clients (matplotlib) and an Excel chart. Until 2026-09-28 each of the three checked the spec on its own; the refactoring that gave them one contract is the code copied here (`src/data_chat/chart.py`, origin in its docstring). Left out: the trend-continuation keys, the colour pinning for the dashboard's table filter, and the Brain's theme.

**Measured** on 2026-09-28 with `claude-haiku-4-5`, catalog stage, three runs (`eval/runs/2026-09-28-claude-haiku-4-5-charts/`): in all 30 answers the chart was what the prompt asks for. The three questions with more than one result row got a bar chart with the right columns (ROAS per channel, return rate per category, clicks per campaign); the seven single-value questions got none, as the prompt says. No spec was refused.

Read that with its limit: **the ten questions contain no time series, no share of a total and no correlation**, so the model's choice of a line, a pie or a scatter is not measured here. The offline tests draw all four types; they do not test the choice.

## Layout

```
history/                 Layer 1: the excerpt of the Brain's history (read-only)
src/data_chat/
  llm.py                 LlmClient port, Anthropic and OpenAI adapters
  backend.py             SqlBackend port, DuckDB and BigQuery, SqlRejected
  catalog.py             catalog format and its rendering into the prompt
  context.py             the stages: schema, freetext, catalog, catalog_selected
  selection.py           the selection step: one card per view, structured output
  prompts.py             system prompts
  sql.py                 pure helpers copied from the Brain
  pipeline.py            question → [selection] → SQL → result → answer, one retry, tokens per call
  chart.py               the answer's chart: spec check and Plotly figure
  page.py                one answer as an HTML page (SQL, answer, chart, table)
  evaluation.py          scoring per stage
  demo_data.py           GENERATED demo data (5 tables)
  demo_large.py          GENERATED demo data, large (35 tables)
  datasets.py            which database, catalog, notes and questions belong together
  cli.py                 data-chat [--dataset] demo-data | prompt | ask [--chart] | eval [--charts]
catalog/                 data_catalog.yaml (field level), freetext.md (table level)
catalog/demo-large/      the same for the large dataset
eval/questions.yaml      questions, traps, reference queries
eval/demo-large/         twenty questions, each with the views it needs
eval/runs/               every published run, per question
tests/                   offline tests
```

## More

How this came about, in more detail: [steimann.de](https://steimann.de)

## License

MIT, see [LICENSE](LICENSE).
