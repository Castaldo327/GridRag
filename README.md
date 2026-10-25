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

GridRag is a Retrieval-Augmented Generation (RAG) system for time-series energy
data. Text retrieval alone cannot reliably answer questions that require joins,
time filters, or aggregation across hourly and five-minute measurements.
GridRag therefore retrieves schema context and uses SQL to produce evidence from
the underlying data.

One routing call scores every documented table. The router then adds referenced
tables and scores each selected table's columns in a separate call; those column
calls run in parallel. The SQL model receives a compact schema containing the
relevant columns and the keys and time fields needed for valid queries. A
separate database guard restricts SQL to the routed tables and enforces read-only
execution limits.

Users can ask about demand, generation, prices, forecasts, storage, outages,
curtailment, and interconnection projects. The UI streams the answer and shows
the selected schema, SQL, returned evidence, latency, and estimated model cost.

## Architecture

[![GridRag architecture: request gate, schema selection, SQL execution and evidence-backed answers](docs/architecture.svg)](docs/architecture.svg)

[View full size](docs/architecture.svg)

This is **structured-data RAG**: schema retrieval supplies context, SQL produces
the evidence, and the model explains the result.

For each question, GridRag:

1. Gate the request for relevance and misuse.
2. Score all catalog tables in one decision-model call.
3. Add their foreign-key dependencies.
4. Make one column-scoring call per selected table, run those calls in parallel,
   and retain structural fields.
5. Send the reduced schema to the SQL model.
6. Validate and run read-only SQL, then stream an answer from the returned rows.

Unusable routing scores retain context when possible; widespread scoring failure
stops the request. The database guard independently enforces table access, query
budgets, and read-only SQL.

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

Open **http://127.0.0.1:8000**. Add `OPENAI_API_KEY=your-key` to a local `.env`
to run model questions. The database build is deterministic and requires no API
key or external download. Stop the app before rebuilding it. The configured
model must support the Decisions and Responses APIs.

The build command creates `data/warehouse.duckdb` from checked-in definitions,
generators, and a fixed seed.

The CLI uses the same pipeline:

```sh
uv run python -m gridrag "What was ERCOT's highest hourly demand on October 19, 2026?"
```

Add `--verbose` for routing scores and model-call diagnostics. Provider requests
include the question, relevant schema definitions, and returned query rows.

## Warehouse and schema

**65 tables · 7 ISOs · entirely fictional data**

| Data | Coverage |
| --- | --- |
| Hourly balance and generation | All ISOs; Jan 1, 2025–Oct 21, 2026 |
| Five-minute load and generation | CAISO and ERCOT; Oct 15–21, 2026 |
| Prices, forecasts, ancillary, storage, outages, curtailment | Eight products per ISO; Oct 15–21, 2026 |
| Interconnection queue | Snapshot as of Oct 21, 2026 |

[Base DDL](gridrag/warehouse/schema.sql), [product definitions](gridrag/warehouse/products.py),
and [database builder](gridrag/warehouse/build.py) are included. The
[schema reference](gridrag/warehouse/SCHEMA.md) explains keys, grains, units,
coverage, and time semantics. The catalog is explicitly registered; adding a
database table does not expose it to the model or SQL guard.

## Evaluation

```sh
# Deterministic checks; no provider requests, even if an API key is present.
uv run python -m unittest discover -s tests

# Explicitly opt into paid, live-model evaluations.
GRIDRAG_LIVE_TESTS=1 uv run python -m unittest discover -s tests -p 'test_live.py'
```

Offline tests cover the database build, routing, SQL safeguards, failure
handling, streaming, and configuration without making provider calls.

The shared cases in [gridrag/warehouse/evals.py](gridrag/warehouse/evals.py)
pair questions with independent reference SQL and expected outcomes. Labelled
cases also appear as UI presets. The separate **Evaluation** tab runs every
case in order through the configured model and reports each check, answer,
SQL query, elapsed time, and estimated cost. It includes clarification and
decline cases as well as numeric questions. Reference SQL is run independently
and never sent to the model. Running the tab makes paid provider requests.
The optional live test command runs the same cases without the UI.

## Code and configuration

- `answer.py` coordinates the pipeline and progress events.
- `gate.py` checks the request.
- `catalog.py` reads and caches schema metadata.
- `route.py` selects tables and columns.
- `sql/agent.py` generates SQL, handles repair, and produces the answer.
- `db.py` validates and runs read-only SQL.
- `llm.py` owns provider calls, streaming, usage, and cost accounting.
- `config.py` provides Pydantic-validated settings.

Set `GRIDRAG_DECISIONS_MODEL` or `GRIDRAG_ANSWER_MODEL` in `.env` or the process
environment to change the models. Cost estimates use configured reference rates
and are not billing records.

## Production boundary

This repository is a local demo. A production deployment would also need
authentication, data entitlements, global request limits, process isolation,
and broader accuracy and adversarial evaluation.
