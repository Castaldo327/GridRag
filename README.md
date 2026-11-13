<p align="center"><img src="app/static/logo-mark.png" alt="Grid Status demo" width="72" height="72"></p>
<h1 align="center">GridRag · Grid Status Demo</h1>
<p align="center"><strong>Ask the grid. Follow the evidence.</strong><br>
An independent Grid Status demo exploring schema retrieval for energy analytics.</p>
<p align="center"><a href="https://gridrag.vercel.app/">Live demo ↗</a> · <a href="#try-it">Run locally</a> · <a href="#the-experiment">The experiment</a> · <a href="gridrag/warehouse/SCHEMA.md">Data dictionary</a> · <a href="SECURITY.md">Security</a></p>

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
| **Evaluation** | Actual recorded answers from routed, dense, and hybrid retrieval, with difficulty filters, SQL evidence, table recall, latency, and cost | No |
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
5. Generate SQL from the selected schema documentation, validate it independently, and execute against a read-only warehouse.
6. Answer from returned rows, with the selected schema, SQL, timing and token use visible.

The [architecture page](https://gridrag.vercel.app/#architecture)
explains this design with the system diagram, a full-size SVG, and a stage-by-stage
text walkthrough. The diagram source lives in `app/static/architecture.svg` and is
copied to `public/static/architecture.svg` on every build. Its distinguishing
choice is independent relevance scoring followed by reference expansion and column
selection. It makes an inspectable schema selection for SQL, with a measured
accuracy/cost tradeoff; it does not establish a claim of research novelty.

The comparison replaces steps 2–4 with **BGE-small embeddings + Qdrant**.
Dense retrieval selects the top **21** tables. Hybrid retrieval combines **48**
semantic candidates with up to **12** BM25 keyword matches over the supplied
schema documents, then reranks the entire candidate union against the question.
Retrieval contains no table-specific rules, domain alias expansion, or hand-coded
region, measure, cadence, or coverage scoring. Both supply full columns after
reference expansion. The hybrid method's second pass calls the OpenAI Decisions
API (`gpt-6-luna`) once to score candidate relevance, then sorts those probabilities before reference expansion. Its time
and estimated model cost are included.

The fresh recorded comparison uses the schema-driven pipeline: no curated entity
aliases, demo-specific relevance rules, grid-only gate, or special power/time SQL
instructions. Declared keys and date/time types determine structural columns.

All three methods share the SQL model, schema-only entity context, gate, repair
budget, and SQL guard. Evaluation allows **25 tables including references** and
**4,096 output tokens** per SQL-model call; the playground retains its existing
limits. The model resolves terminology from supplied schema documentation. No
hand-maintained entity vocabulary is injected into this comparison.
See the [experiment specification](benchmarks/README.md) for settings and scoring.
There is no full-schema prompt baseline.

### Reproduce the comparison

```sh
uv sync --locked --extra eval
docker compose up -d qdrant
# Retrieval only: local embeddings; no OpenAI calls.
uv run --extra eval python -m benchmarks.run --repeats 1
# End-to-end: paid provider calls using your local key.
uv run --extra eval python -m benchmarks.run --live --repeats 3 --max-tables 25 --output artifacts/benchmark-schema-driven-3trials.json
uv run python -m scripts.publish_benchmark --input artifacts/benchmark-schema-driven-3trials.json
# Stop the database when finished; keep its named volume.
docker compose stop qdrant
```

Qdrant binds only to localhost. Embeddings run locally; the model download is
cached in an ignored directory. Each benchmark owns a uniquely named collection
and removes only that collection afterward. The eval dependencies are optional
and are not installed for the Vercel app.

The capability benchmark contains **30 answerable questions**: 7 easy, 8 medium,
8 hard, and 7 very hard. Three trials per question and method produce **270 recorded
attempts**, with **90 attempts per method**, in seeded shuffled order. Difficult
questions combine forecast vintages,
window rankings, dimensional joins, interval alignment, energy conversion, and
cross-region comparisons. Independent reference SQL never reaches the models.

Scalar questions require the complete final SQL result to match one numeric
reference. The seven-ISO price comparison requires all **21 region/product rows**
and their values; partial answers and missing-series claims fail. Clarification is
not counted as a correct analytical answer. Refusal and table-budget behavior
remain in the separate developer regression suite.

| Method | Trial 1 | Trial 2 | Trial 3 | Cumulative correct | Required-table recall | Median time |
| --- | --- | --- | --- | --- | --- | --- |
| Routed schema | 27/30 | 27/30 | 27/30 | 81/90 · 90.0% | 100.0% | 4.82 s |
| Qdrant → Decisions | 28/30 | 26/30 | 28/30 | 82/90 · 91.1% | 100.0% | 4.14 s |
| Dense vector · top21 | 24/30 | 23/30 | 23/30 | 70/90 · 77.8% | 92.5% | 4.12 s |

Cumulative accuracy is correct answers divided by all 90 attempts for each method,
including failed attempts. Trial scores show variation across the three runs.
This small synthetic development suite does not estimate production accuracy.
Required-table recall, query
results, latency, schema size, tokens, and estimated costs are recorded separately.

### Read the recorded answers

The [evaluation page](https://gridrag.vercel.app/#evaluation) shows all 30 questions,
with filters from easy to very hard. Each question has Trial 1, Trial 2, and Trial 3
controls for routed schema, top-21 vectors, and hybrid reranking, with selected tables,
SQL, CSV evidence, time, and estimated cost. Complete table references are visible
for comparison questions. Scores include failed attempts and cover the selected
questions across all three trials. Selecting a trial changes the displayed
evidence while cumulative scores continue to include every attempt. Browsing
never makes paid model calls.

The separate 26-case regression suite in `gridrag/warehouse/suite.py` remains
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
[builder](gridrag/warehouse/build.py) are included. Adding a database table does not
automatically expose it to the model or SQL guard.

## Verification

```sh
# Offline: no provider requests, even with a key present.
uv run python -m unittest discover -s tests
node --check app/static/app.js
node --test tests/test_*.js
uv run python -m scripts.security_audit --history
uv run python -m scripts.public_release
```

The checks cover schema parsing, read-only SQL enforcement, resource
limits, request-scoped credentials, failed requests, streaming, reference queries
and benchmark scoring. See [contributing](CONTRIBUTING.md).

## GitHub and Vercel

Use the generated **`artifacts/public-source/`** snapshot for a new public repository
when the working repo has private historical content. It has an explicit file
manifest and excludes Git history, local environment files, Vercel project metadata,
experiments, screenshots, generated databases and caches. Your original working
repository and history remain intact. Configure a public-safe Git author identity
before committing the snapshot. See [release privacy details](SECURITY.md).

Connect that GitHub repository to Vercel using the checked-in `vercel.json`. No owner
OpenAI key is needed. The public endpoints always require a visitor key, even if an
owner key was configured accidentally.

Set **Root Directory** to the repository root (`.`) and **Framework Preset** to
**Other**. Leave build and output overrides disabled: `vercel.json` sets the build
command to `uv run --locked python -m scripts.vercel_build` and output to `public`.

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
performance. BM25 currently scans schema documents per question; an indexed
keyword backend and larger, independent datasets remain necessary. The application
is still a demonstration. Authentication, tenant entitlements, distributed request
limits, process isolation, operational monitoring and broader adversarial evaluation
are necessary before connecting real organizational data.
