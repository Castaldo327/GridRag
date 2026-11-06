<p align="center"><img src="app/static/energy-mark.svg" alt="GridRag" width="72" height="72"></p>
<h1 align="center">GridRag</h1>
<p align="center"><strong>Ask the grid. Follow the evidence.</strong><br>
An independent exploration of schema retrieval for energy analytics.</p>
<p align="center"><a href="https://sunairio-energy-demo.vercel.app/">Live demo ↗</a> · <a href="#try-it">Run locally</a> · <a href="#the-experiment">The experiment</a> · <a href="gridrag/warehouse/SCHEMA.md">Data dictionary</a> · <a href="SECURITY.md">Security</a></p>

Electricity questions are rarely just text lookups. A price spread requires aligned
intervals. Battery energy requires a conversion from MW to MWh. A historical
forecast requires knowing when it was published. GridRag retrieves the relevant
schema, executes guarded SQL, and makes the resulting evidence visible.

**65 documented tables · 7 US grid regions · entirely fictional data**

This is a personal research project. It uses no employer, customer, or proprietary
operational data, and makes no claim of affiliation with an energy company.

## Try it

The app has three pages:

| Page | What it shows | Key required? |
| --- | --- | --- |
| **Demo** | The playground flow with seven prepared questions, staged progress, streamed answers, and verified SQL evidence | No |
| **Playground** | Live questions, streaming answers, SQL evidence, data coverage and searchable table definitions | Yes, for hosted questions |
| **Evaluation** | Recorded accuracy, latency and estimated cost for routed versus embedded schema retrieval | No, to view results |

The demo replays prepared answers and verified reference queries entirely in the
browser. Its stage transitions and text reveal are illustrative; no model runs,
API charges, or measured performance statistics are involved. Choose an example,
select **Ask the grid**, and inspect the answer, selected tables, SQL, and returned data.
The evaluation page also offers an optional live pipeline check suite with your key.
That suite is separate from the recorded Qdrant comparison.

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

1. Check the question for domain relevance and misuse.
2. Score all catalog tables in one decision-model call.
3. Include referenced tables, then score selected tables' columns concurrently.
4. Preserve structural keys and time fields in the reduced schema.
5. Generate SQL, validate it independently, and execute against a read-only warehouse.
6. Answer from returned rows, with the selected schema, SQL, timing and token use visible.

The comparison replaces steps 2–4 with **BGE-small embeddings + Qdrant**: one
embedded document per table, top-4 or top-6 retrieval, foreign-key expansion and
full columns. Both methods use the same gate, SQL model, repair budget and SQL
guard. There is no full-schema prompt baseline.

### Reproduce the comparison

```sh
uv sync --locked --extra eval
docker compose up -d qdrant
# Retrieval only: local embeddings; no OpenAI calls.
uv run --extra eval python -m benchmarks.run --repeats 1
# End-to-end: paid provider calls using your local key.
uv run --extra eval python -m benchmarks.run --live --repeats 3
# Stop the database when finished; keep its named volume.
docker compose stop qdrant
```

Qdrant binds only to localhost. Embeddings run locally; the model download is
cached in an ignored directory. Each benchmark owns a uniquely named collection
and removes only that collection afterward. The eval dependencies are optional
and are not installed for the Vercel app.

The benchmark includes 18 fixed questions, three repetitions per method, shuffled
case/method order, independent reference SQL, and case-bootstrap uncertainty.
Every completed attempt, including failures, contributes to the denominator.
Numeric accuracy requires the entire final scalar SQL result to match the reference;
required-table recall and prose matching are reported separately. Results include
latency, schema size, tokens, estimated model cost and environment metadata.

The recorded run scored **92.6%** for routed schema versus **72.2%** for top-6
embeddings, with median latency **4.50 s vs 3.44 s** and roughly **10.8×** estimated
model cost. That is a measured accuracy/latency/cost tradeoff on this suite.

See [methodology and measured results](https://sunairio-energy-demo.vercel.app/#evaluation). This is a small synthetic
experiment, not evidence of general superiority or production accuracy.

### Live regression suite

The Evaluation page also provides a separate, versioned **28-question** suite:
22 numeric cases and 6 scope/safety cases across core analytics, time and forecast
vintages, storage and operations, regional retrieval, and request behavior. Browse
the questions, expected values, tolerances, and evidence contracts without a key.
Select a category and one or three trials per question, then run with your own key.
Each trial uses a bounded Vercel request; stopping waits for the current case.

Task correctness requires the expected end state plus the complete final scalar
SQL result, or no SQL for a behavior case. Numeric requests explicitly ask for one
row and one numeric column. Truncated results, extra rows/columns, nonfinite values,
and a failed final query cannot pass by matching an earlier or incidental number.
The stricter all-check score also checks required/excluded tables, forbidden SQL,
answer value, and unit labels. Valid alternative routes can therefore be task-correct
while failing a routing check. Prose checks are deterministic diagnostics, not a
semantic guarantee. Repaired SQL errors remain visible in each attempt's trace.

Reports retain each trial, failures, expected/observed values, SQL and CSV evidence,
model use, latency, suite/schema fingerprints, and partial-run status. Export JSON
before starting a new run; reports contain no API keys. Cost uses reported configured
token rates and excludes hosting and unreported failed-call billing. Reference SQL
and expected values never reach the model. The recorded 18-question comparison above
remains a historical artifact; the expanded live suite does not rewrite its scores.

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
request-scoped credentials, security headers and regression tests. The application
is still a demonstration. Authentication, tenant entitlements, distributed request
limits, process isolation, operational monitoring and broader adversarial evaluation
are necessary before connecting real organizational data.
