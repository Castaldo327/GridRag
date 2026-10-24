<p align="center">
  <img src="app/static/logo-mark.png" alt="Grid Status logo" width="96" height="96">
</p>
<h1 align="center">GridRag</h1>
<p align="center"><strong>Ask the grid.</strong><br>
A small SQL-RAG system built for time-series analysis of fictional US electricity grid data.</p>
<p align="center">
  <a href="#run-locally">Run locally</a> ·
  <a href="#architecture">Architecture</a> ·
  <a href="gridrag/warehouse/SCHEMA.md">Schema</a> ·
  <a href="#evaluation">Evaluation</a> ·
  <a href="#production-boundary">Production boundary</a>
</p>

## What it does

GridRag is a Retrieval-Augmented Generation (RAG) system tailored specifically for time-series energy data.

Standard RAG retrieves textual chunks—an approach that falls short for hourly and five-minute grid measurements, where accurate answers depend on relational joins and aggregations. Instead of retrieving text documents, GridRag retrieves database schemas and generates evidence using SQL.

Rather than relying on hand-crafted routing rules, GridRag scores every documented physical table against the question in one decision-model call. It keeps relevant tables and their referenced dimensions, then scores the columns of those selected tables in parallel. Only the selected column definitions reach the SQL model, with identifiers and time columns retained for joins and filters. The database guard independently limits queries to the routed tables.

Users can query grid demand, generation, pricing, forecasts, energy storage, or interconnection queues. GridRag isolates the necessary schema, executes read-only SQL queries, and synthesizes answers directly from the returned dataset. The UI provides real-time execution visibility—displaying selected schemas, generated SQL, raw evidence, latency metrics, and estimated API costs at each step.

## Architecture

[![GridRag architecture: request gate, schema selection, SQL execution and evidence-backed answers](docs/architecture.svg)](docs/architecture.svg)

[View full size](docs/architecture.svg) · [Edit in draw.io](docs/architecture.drawio)

This is **structured-data RAG**: schema retrieval supplies context, SQL retrieves and aggregates evidence, and the model explains it. A vector database is not required.

The flow is:

1. **Read the catalog.** Load the approved table definitions and cache their columns, keys, and references.
2. **Tag table relevance.** One Decisions call scores every physical table against the question.
3. **Expand the selection.** Follow foreign-key references transitively and enforce the table budget before starting column requests.
4. **Tag column relevance in parallel.** One Decisions call per retained table scores its columns, with at most four requests running at once. Keep declared keys, time columns, and identifier/code columns even when their scores are low.
5. **Build SQL context.** Assemble selected column definitions with table documentation and applicable key constraints, in stable catalog order.
6. **Query and answer.** Generate guarded, read-only SQL, repair errors within the call budget, and stream answer text after query evidence arrives.

Missing or malformed scores retain context unless more than half the scores in a
single decision are unusable; that decision fails rather than silently discarding
schema. Both thresholds and concurrency are configurable. Column pruning reduces
model context; it does **not** enforce column-level permissions. The database guard
restricts tables, not individual columns.

With N retained tables, routing uses **1 + N model calls**. Parallelism overlaps the
column calls but does not reduce their token cost. Whether the smaller SQL prompt
outweighs that extra work needs live measurement on this router. Family metadata is
for documentation; routing no longer scores one shared definition per product.


| Layer | What it does |
| --- | --- |
| Gate → routing | Checks relevance and possible abuse; it does not grant data access. |
| Routing → SQL | Scores all tables, includes referenced dimensions, then scores selected tables' columns in parallel. Mostly unusable scores fail the request instead of silently dropping context. |
| SQL → database | Independently enforces read-only access, the routed catalog tables (matched case-insensitively), and execution/result budgets; it runs the query as DuckDB's parser regenerates it, so comments cannot change what runs. |
| Results → answer | Preserves query evidence and failures for inspection; SQL errors can be repaired within a fixed budget. |

## Run locally

Requires Python **3.11–3.13** and **uv**. 


```sh
brew install uv
```

From the repository root:

```sh
uv sync --locked
uv run python -m gridrag.warehouse.build
uv run python -m app
```

`uv sync --locked` installs the dependencies from `uv.lock` and creates the
project's `.venv` automatically. You do not need to create or activate a virtual
environment yourself. The dependencies are declared in `pyproject.toml`; there
is no separate `requirements.txt`.

Open **http://127.0.0.1:8000**. Add `OPENAI_API_KEY=your-key` to a local `.env`
to run model questions. Building the database requires no API key or external
data downloads. Model access must support the
configured Decisions and Responses calls.

The build command creates `data/warehouse.duckdb` from checked-in code. To
rebuild, stop the app and rerun that command; it replaces the demo database.
The fixed seed and dates make the data reproducible. Generated data and `.env`
are ignored by Git.

The CLI uses the same pipeline:

```sh
uv run python -m gridrag "What was ERCOT's highest hourly demand on October 19, 2026?"
```

Add `--verbose` for table and column scores and per-call diagnostics. API calls transmit
the question, selected context, and query results to the configured provider.

## Warehouse and schema

**65 tables · 7 ISOs · entirely fictional data**

| Data | Coverage |
| --- | --- |
| Hourly balance and generation | All ISOs; Jan 1, 2025–Oct 21, 2026 |
| Five-minute load and generation | CAISO and ERCOT; Oct 15–21, 2026 |
| Prices, forecasts, ancillary, storage, outages, curtailment | Eight products per ISO; Oct 15–21, 2026 |
| Interconnection queue | Current snapshot as of Oct 21, 2026 |

[Base DDL](gridrag/warehouse/schema.sql), [product definitions](gridrag/warehouse/products.py),
and [generator](gridrag/warehouse/build.py) are all included. The
[schema reference](gridrag/warehouse/SCHEMA.md) explains keys, grains, units,
coverage, and time semantics. The catalog is explicitly registered; adding a
database table alone does not expose it to the model, and the SQL guard only
allows catalog tables. Each ISO has an explicit id, and each product defines its
columns and the generator that fills its tables.

## Evaluation

```sh
# Deterministic checks; no provider requests, even if an API key is present.
uv run python -m unittest discover -s tests

# Explicitly opt into paid, live-model evaluations.
GRIDRAG_LIVE_TESTS=1 uv run python -m unittest discover -s tests -p 'test_live.py'
```

Offline tests cover SQL restrictions and normalization, timeout recovery,
precision, table and column routing and routing uncertainty, tool budgets, failures,
settings, and warehouse invariants.

Evaluation questions live in one table,
[gridrag/warehouse/evals.py](gridrag/warehouse/evals.py): each case pairs a
question with independent reference SQL, its expected end state, and tables the
route must or must not include. The UI offers the labelled cases as preset
questions. Live evaluations ask every case (fuel shares, interval values, queue
counts, bus and hub prices, price spreads, forecast cutoffs, battery energy, a
too-broad request, and declined requests) and require the answer to state the
reference value in query evidence and in the answer at its displayed precision.
The [live verification report](docs/live-verification.md) records the prompt comparison,
measured latency/cost, and 15 reviewed runs for the previous family-level router.
The table-and-column router needs a fresh live evaluation before its answer quality and
latency can be compared. Broader unseen-schema and adversarial evaluations are required before deployment.

## Code and configuration

`answer.py` orchestrates; `gate.py` and `route.py` classify; `sql/agent.py`
prompts for SQL and handles repair; `db.py` enforces database restrictions;
`llm.py` owns provider calls and usage accounting. Its `Model` protocol defines
the injected model interface used by the pipeline and test doubles. `records.py` defines the
records each stage returns or streams, as TypedDicts, and the `State` and `Stage`
names. `catalog.py` owns immutable, cached schema metadata (name, DDL, columns, keys, references) and
per-ISO product families as documentation metadata; `demo_catalog()` adapts the demo
schema, and `answer(..., catalog=...)` accepts any other `Catalog`. `app/` and
`gridrag/warehouse/` are demo infrastructure.

[config.py](gridrag/config.py) defines one frozen, Pydantic-validated `Settings` dataclass with
thresholds, budgets, models, and illustrative cost rates, loaded once from `.env`
and the environment. Set `GRIDRAG_DECISIONS_MODEL` or `GRIDRAG_ANSWER_MODEL` in
either place to override model defaults. Modules read `config.settings` when they
need a value, so tests replace it in one place. Prompts stay beside their owning
stages; protocol strings stay literal. Cost estimates are not billing figures.

Pydantic validates configuration types and ranges at construction and validates
provider probabilities without coercing strings or booleans into scores. Internal
JSON records remain TypedDicts; immutable catalog objects own their structural
checks. The DDL adapter supports this repository's documented schema format, not
arbitrary SQL dialects or automatic database discovery.

Column workers share the pooled provider client; usage recording is locked. A failed
column batch cancels queued requests and waits for already-running requests to finish
under their configured timeouts. The worker limit applies per question, not globally
across a deployment. See the [code audit](docs/code-audit.md) for findings and limits.

## Production boundary

This repo is just a demo, not production-ready code. Features like the web app and warehouse setup are meant to get you up and running quickly.
