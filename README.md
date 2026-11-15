<p align="center"><img src="app/static/logo-mark.png" alt="Grid Status demo" width="72" height="72"></p>
<h1 align="center">GridRag · Grid Status Demo</h1>
<p align="center"><strong>Ask the grid. Follow the evidence.</strong><br>
An independent Grid Status demo exploring schema retrieval for energy analytics.</p>
<p align="center"><a href="https://gridrag.vercel.app/">Live demo ↗</a> · <a href="#try-it">Run locally</a> · <a href="#the-experiment">The experiment</a> · <a href="gridrag/warehouse/SCHEMA.md">Data dictionary</a></p>

Electricity questions are rarely just text lookups. A price spread requires aligned
intervals. Battery energy requires a conversion from MW to MWh. A historical
forecast requires knowing when it was published. GridRag retrieves the relevant
schema, executes guarded SQL, and makes the resulting evidence visible.

**65 documented tables · 7 US grid regions · entirely fictional data**

This is a personal research project. It uses no employer, customer, or proprietary
operational data, and makes no claim of affiliation with an energy company.

## Try it

The app has four pages:

| Page | What it shows | Key required? |
| --- | --- | --- |
| **Demo** | The playground flow with seven prepared questions, staged progress, streamed answers, and verified SQL evidence | No |
| **Playground** | Live questions, streaming answers, SQL evidence, data coverage and searchable table definitions | Yes, for hosted questions |
| **Evaluation** | Actual recorded answers from GridRag and vector retrieval with Decisions reranking, with difficulty filters, SQL evidence, table recall, latency, and cost | No |
| **Architecture** | The retrieval and execution diagram, design choices, measured tradeoffs, and hosting boundaries | No |

The demo replays prepared answers and verified reference queries entirely in the
browser. Its stage transitions and text reveal are illustrative; no model runs,
API charges, or measured performance statistics are involved. Choose an example,
select **Ask the grid**, and inspect the answer, selected tables, SQL, and returned data.
The evaluation page is read-only. Browse the recorded answers and evidence without
a key or running model calls. Demo, Evaluation, and Architecture load static assets;
the browser only requests live API metadata when you open Playground.

Requires Python **3.11–3.13** and [uv](https://docs.astral.sh/uv/).

```sh
uv sync --locked
uv run python -m gridrag.warehouse.build
uv run python -m scripts.public_assets
uv run python -m app
```

Open **http://127.0.0.1:8000**. The default page needs no key. In the playground,
enter your OpenAI key and select **Use key**. The configured model requires both
Decisions and Responses API access. The password input is cleared; the active key
stays in tab memory, and the backend uses a separate provider client per request.
Reload or select **Remove** to clear the key. API usage is billed to your project.

The CLI can use `OPENAI_API_KEY` in an ignored local `.env` or environment variable:

```sh
uv run python -m gridrag "What was ERCOT's highest hourly demand on October 19, 2026?"
```

Set `GRIDRAG_DECISIONS_MODEL` and `GRIDRAG_ANSWER_MODEL` to change models. Add
`--verbose` to the CLI for model and routing diagnostics. Provider requests include
the question, relevant schema and returned synthetic rows.

## The experiment

Does scoring tables and columns preserve the context needed for SQL better than
retrieving embedded table definitions? What does that trade in latency and cost?

The main pipeline:

1. Check for an analytical database request and misuse using domain-neutral instructions.
2. Score all catalog tables in one decision-model call.
3. Include referenced tables, then score selected tables' columns concurrently.
4. Preserve structural keys and time fields in the reduced schema.
5. Add the catalog's optional entity vocabulary and generate SQL from the selected schema documentation, validate it independently, and execute against a read-only warehouse.
6. Answer from returned rows, with the selected schema, SQL, timing and token use visible.

The [architecture page](https://gridrag.vercel.app/#architecture)
explains this design with the system diagram, a full-size SVG, and a stage-by-stage
text walkthrough. The diagram source lives in `app/static/architecture.svg` and is
copied to `public/static/architecture.svg` on every build. Its distinguishing
choice is independent relevance scoring followed by reference expansion and column
selection. It makes an inspectable schema selection for SQL, with a measured
accuracy/cost tradeoff; it does not establish a claim of research novelty.

The comparison replaces steps 2–4 with **BGE-small embeddings + Qdrant +
Decisions reranking**. Its candidate cap is fixed at **20% of catalog tables**,
rounded up: **13 of 65**. Dense and BM25 retrieval each propose up to 13 tables;
fusion limits their combined shortlist to 13 before the same Decisions
table-relevance prompt used by GridRag. Candidates meeting the shared relevance
threshold are expanded through foreign keys and supplied with all columns. There is no standalone vector top-k baseline.

Both methods share the SQL model, seven-ISO entity context, request gate, repair
budget, and SQL guard. Evaluation allows **25 tables including references** and
**4,096 output tokens** per SQL-model call; the playground retains its defaults.
Custom catalogs supply their own optional vocabulary. Retrieval uses no table-specific
rules or domain alias expansion. The experiment measures these complete pipelines;
it does not isolate candidate generation from column selection or establish an
exclusive foreign-key advantage for either method.

The question is: **Can OpenAI's Decisions API simplify schema selection for
text-to-SQL, and what are the tradeoffs in accuracy, latency, and cost?**
See the [experiment specification](benchmarks/README.md) and the
[30-question design matrix](benchmarks/QUESTIONS.md). There is no full-schema prompt baseline.

### Reproduce the comparison

```sh
uv sync --locked --extra eval
docker compose up -d qdrant
# Retrieval only: local embeddings; no OpenAI calls.
uv run --extra eval python -m benchmarks.run --repeats 1
# End-to-end: paid provider calls using your local key.
uv run --extra eval python -m benchmarks.run --live --repeats 3 --max-tables 25 --output artifacts/benchmark-decisions-vs-reranker-p20-3trials.json
uv run python -m scripts.publish_benchmark --input artifacts/benchmark-decisions-vs-reranker-p20-3trials.json
# Stop the database when finished; keep its named volume.
docker compose stop qdrant
```

Qdrant binds only to localhost. Embeddings run locally; the model download is
cached in an ignored directory. Each benchmark owns a uniquely named collection
and removes only that collection afterward. The eval dependencies are optional
and are not installed for the Vercel app.

The benchmark contains **30 realistic analyst questions**: 7 easy, 8 medium,
8 hard, and 7 very hard. Three trials per question and method produce **180 recorded
attempts**, with **90 attempts per method**, in seeded shuffled order. The questions
cover historical and regional scope, similar market products, implicit denominators,
forecast cutoffs, operational calculations, and broad multi-region retrieval.
They and their independent references are fixed before execution; model outcomes
are not used to edit the suite or select favorable attempts.

Scalar answers must match the complete final SQL result to the numeric reference.
The broad price comparison must return all **21 region/product rows** and their
values. Clarifications and execution failures count as incorrect. Candidate-table
recall diagnoses shortlist omissions separately from final required-table recall.
Selected columns, total input tokens, estimated cost and latency expose the cost
of column pruning as well as its effect on SQL context. The fixed 20% cap avoids
retrieving most of this small catalog, but does not reproduce production database
scale. The broad price task needs 21 independent source tables and therefore
exceeds the 13-candidate budget; it remains scored and is labeled in the UI.

<!-- benchmark-results:start -->
| Pipeline | Trial 1 | Trial 2 | Trial 3 | Cumulative correct | Median time | Est. cost / attempt |
| --- | --- | --- | --- | --- | --- | --- |
| GridRag | 27/30 | 26/30 | 27/30 | 80/90 · 88.9% | 4.40 s | $0.00359 |
| Vector + Decisions reranker (20% cap) | 20/30 | 19/30 | 20/30 | 59/90 · 65.6% | 3.71 s | $0.00091 |

See the [results and failure analysis](benchmarks/RESULTS.md).
<!-- benchmark-results:end -->

This small synthetic development suite does not estimate production accuracy.
One-time embedding/index construction is reported separately from query latency.
Model costs exclude local embedding compute and Qdrant hosting. The questions are
unchanged from v2; the candidate policy changed, so these results use experiment v3.

### Read the recorded answers

The [evaluation page](https://gridrag.vercel.app/#evaluation) shows all 30 questions,
with filters from easy to very hard. Each question has Trial 1, Trial 2, and Trial 3
controls for GridRag and vector retrieval with Decisions reranking, with selected tables,
SQL, CSV evidence, time, and estimated cost. Complete table references are visible
for comparison questions. Scores include failed attempts and cover the selected
questions across all three trials. Selecting a trial changes the displayed
evidence while cumulative scores continue to include every attempt. Browsing
never makes paid model calls.

The recorded comparison used the earlier DDL-text catalog representation. Current
runs read DuckDB metadata and stored descriptions; the live comparison must be
rerun to measure the effect of the new schema representation.

The separate 26-case regression suite in `gridrag/evals/suite.py` remains
available for explicit local testing, including scope and safety behavior.
Markdown is rendered with pinned, locally vendored Marked and DOMPurify bundles.

## Data coverage

| Data | Coverage |
| --- | --- |
| Hourly balance and generation by fuel | All 7 ISOs; Jan 1, 2025–Oct 21, 2026 |
| Five-minute load and generation | CAISO and ERCOT; Oct 15–21, 2026 |
| Prices, forecasts, ancillary services, storage, outages and curtailment | Eight products per ISO; Oct 15–21, 2026 |
| Interconnection queue | Snapshot as of Oct 21, 2026 |

This is a fixed snapshot, not live market data. Use a region, measure and explicit
date. The playground explains the limits and exposes the table definitions.

The [schema reference](gridrag/warehouse/SCHEMA.md) documents keys, grains, units,
coverage and time semantics. The [DDL](gridrag/warehouse/schema.sql),
[product definitions](gridrag/warehouse/products.py) and deterministic
[builder](gridrag/warehouse/build.py) are included. The catalog reads persistent
base tables from the approved `core` schema. Other schemas, views, temporary
tables and attached databases are excluded.

## Code layout

```text
gridrag/
├── __main__.py       # Command-line entry point
├── answer.py         # Question-to-answer orchestration
├── gate.py           # Request relevance and misuse checks
├── route.py          # Table and column selection
├── llm.py            # Provider calls and usage accounting
├── records.py        # Shared request and result contracts
├── config.py         # Validated runtime settings
├── catalog/
│   ├── __init__.py   # Public catalog API
│   ├── models.py     # Immutable metadata and schema prompt rendering
│   └── duckdb.py     # Read tables, columns, constraints and stored comments
├── sql/
│   ├── agent.py      # SQL generation, repair and evidence-based answers
│   └── db.py         # Guarded read-only SQL execution
├── warehouse/        # Fictional schema, fixtures and data generation
│   └── catalog.py    # Demo catalog assembly and approved ISO vocabulary
└── evals/            # Regression cases and deterministic scoring
```

Use `gridrag.catalog` for catalog imports. `demo_catalog()` reads the built
warehouse in read-only mode and caches its metadata once per process. Table and
column descriptions are persisted with `COMMENT ON` statements in `schema.sql`
and the generated product DDL. Rebuild the warehouse after changing the schema or
descriptions, then restart the application to refresh the cached catalog.

Custom catalogs use the same metadata reader with an existing DuckDB connection:

```python
import duckdb
from gridrag.catalog import read_catalog

with duckdb.connect("retail.duckdb", read_only=True) as connection:
    catalog = read_catalog(connection, schemas=("retail",))
```

The catalog remains usable after the connection closes. Optional approved
vocabulary can be passed to `read_catalog(..., vocabulary=...)`. This replaces
the previous `Table.parse()` and script `parse()` helpers; DuckDB interprets DDL
when the database is created.

The SQL agent and execution guard live together in `gridrag.sql`. The web app,
benchmark retrieval alternatives and build scripts live in `app/`, `benchmarks/`
and `scripts/` respectively.

## Verification

```sh
# Offline: no provider requests, even with a key present.
uv run ruff check .
uv run ruff format --check .
uv run python -m unittest discover -s tests
node --check app/static/app.js
node --test tests/test_*.js
uv run python -m scripts.security_audit --history
```

The checks cover catalog introspection, stored documentation, read-only SQL enforcement, resource
limits, request-scoped credentials, failed requests, streaming, reference queries
and benchmark scoring.

## GitHub and Vercel

Connect the GitHub repository to Vercel using the checked-in `vercel.json`. No owner
OpenAI key is needed. The public endpoints always require a visitor key, even if an
owner key was configured accidentally.

Set **Root Directory** to the repository root (`.`) and **Framework Preset** to
**Other**. Leave build and output overrides disabled: `vercel.json` sets the build
command to `uv run --locked --no-dev python -m scripts.vercel_build` and output to `public`.

The Vercel build generates the fictional warehouse and copies only approved frontend
assets into `public/`. The DuckDB file is bundled privately with the Python function,
opened read-only, and queried through the backend. Visitors need no database setup.
This works for a fixed dataset; a changing production warehouse should live in an
external data service. See [Vercel's Python file bundling documentation](https://vercel.com/docs/functions/runtimes/python).

The recorded comparison is static. Qdrant runs locally for reproducible experiments;
it is not part of the hosted function. Each live web request has a configured
300-second limit. Deployment completion and cloud bundle size must be verified
in the target Vercel project before announcing the URL.

## Production boundary

The code has explicit contracts, independent SQL safeguards, reproducible data,
request-scoped credentials, security headers and regression tests. This synthetic
dataset does not establish cross-domain accuracy or catalog-scale
performance. Hybrid retrieval indexes schema tokens once per retriever and scores
matching keyword postings per question; larger, independent datasets and a
production retrieval service still need evaluation. The application
is still a demonstration. Authentication, tenant entitlements, distributed request
limits, process isolation, operational monitoring and broader adversarial evaluation
are necessary before connecting real organizational data.
