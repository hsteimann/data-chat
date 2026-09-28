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
- It filters `channel = 'paid search'` while the value is `paid_search`, so the query finds nothing. The catalog names the values.
- It takes `AVG(sessions)` over rows that are one per day **and channel**.
- It reports gross revenue as revenue.

Read these numbers with their limits:

- **One small model.** Haiku is what the sandbox this was built in allows. The Brain runs a larger model, not measured here.
- **Ten questions, written together with the demo data.** The traps are real ones, but they are chosen, so this shows the mechanism, not a rate you should expect elsewhere.
- **Free text = schema here.** The free-text note is table level, and every miss above is a field-level trap, so the note changes nothing. In the Brain's own history, free text was the step up from *no* context at all. This setup does not measure that step: its baseline already has the table and column names.
- **Scored on the result table** (`src/data_chat/evaluation.py`), not on the prose answer.

## Layout

```
history/                 Layer 1: the excerpt of the Brain's history (read-only)
src/data_chat/
  llm.py                 LlmClient port, Anthropic and OpenAI adapters
  backend.py             SqlBackend port, DuckDB and BigQuery, SqlRejected
  catalog.py             catalog format and its rendering into the prompt
  context.py             the three stages
  prompts.py             system prompts
  sql.py                 pure helpers copied from the Brain
  pipeline.py            question → SQL → result → answer, one retry
  evaluation.py          scoring per stage
  demo_data.py           GENERATED demo data
  cli.py                 data-chat demo-data | prompt | ask | eval
catalog/                 data_catalog.yaml (field level), freetext.md (table level)
eval/questions.yaml      questions, traps, reference queries
tests/                   offline tests
```

## Links

- Workshop article on steimann.de: *(link follows)*
- About the Nakoa Brain: *(link follows)*

## License

MIT, see [LICENSE](LICENSE).
