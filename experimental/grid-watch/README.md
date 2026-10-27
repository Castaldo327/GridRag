# Grid Watch

A deliberately small, local demo of intelligent grid alerts. The configured models generate six SQL queries, evaluate five alert conditions against new data, and summarize a fictional July 22 event.

## Run

From the repository root:

```sh
./experimental/grid-watch/run.sh
```

Open **http://127.0.0.1:8011**. Live mode is the default. It reads the existing project configuration: `OPENAI_API_KEY`, `GRIDRAG_ANSWER_MODEL` and `GRIDRAG_DECISIONS_MODEL` (including the repository `.env`). The current configured setup and decision models are both `gpt-6-luna`. The key stays on the server. The existing virtual environment has the dependencies; `requirements.txt` lists them for another environment.

Add `--play` to start immediately, `--port 8012` to choose another port, or `--offline` to run the original scripted version without API calls. Live mode makes paid OpenAI calls; only fictional evidence, questions and schema are sent. Actions remain local. Stop the server with Ctrl+C. Startup and **Reset replay** rebuild this demo's runtime database and clear its alerts/tasks. The parent application's data is never touched. Validated model-generated plans and API usage logs survive replay resets; cached plans are revalidated at startup.

## A two-minute walkthrough

1. Click **Play replay** or **Jump to 2:00 PM event**. Each tick delivers one minute of observations, then awaits one batched Decisions API call. The speed selector sets the delay between ticks; API time is additional.
2. Watch the chart, metrics and five saved watches update. Each watch runs real SQL after every new batch of data.
3. Open any watch or alert's **View evidence** link to see the exact result, definition and saved query.
4. Click **Create local task** on an alert. Or enable automatic local tasks in a watch's details. Tasks remain inside this demo; repeated requests for the same alert return the same task.
5. Open **Event review** for “Show me everything that changed around the July 22 event.” **Replay to the end** fills in the whole story. **Generate summary** calls the configured Responses model using only observed events and alerts; its timestamp tells you how far that summary covers.
6. Open **Data & queries** to inspect table sizes, assumptions and the database structure check. The replay CSV is downloadable there.

## The six questions

| Question | Demo meaning | First trigger (Eastern) |
| --- | --- | --- |
| Dominion load drops more than 1,000 MW in 10 minutes | Latest reading versus exactly 10 minutes earlier; strictly greater than 1,000 MW | 2:02 PM |
| A 230 kV or higher line goes out in Northern Virginia | Voltage ≥230 kV and exact region match | 2:00 PM |
| ERCOT reserves fall below normal for this time of year | Below the 10th percentile from the prior three years, July 8–August 5, at the matching hour | 2:04 PM |
| Congestion at my node is in the top 5% of the last 90 days | Signed congestion $/MWh at fictional node `NVA-DEMO-01`, at or above the trailing 95th percentile; excludes the current reading | 2:05 PM |
| Load runs 5% above forecast while a line is out | Dominion load >105% of its forecast, with a qualifying Northern Virginia line out at that minute | 2:07 PM |
| Everything that changed around the July 22 event | All scripted source changes observed so far in the 1:40–2:20 PM replay, with related alerts and recoveries | Event review |

Lower-voltage and out-of-region outages happen earlier as negative examples. Five alerts fire once each. All five conditions recover by 2:15 PM. The 40-minute replay completes at 2:20 PM.

## What is real, and what is simplified?

**Working:** deterministic dataset generation, timestamped data ingestion, saved SQL execution, live server-sent updates, evidence inspection, missing-data handling, repeat-alert suppression, recovery messages, database structure checks and local follow-up tasks.

**Live models:** the configured Responses model generates each query from the question, its agreed definition, schema and evidence-field contract. The reference SQL is not supplied to the model. A parser guard permits only a single SELECT over allowed tables; database file/network access is disabled and queries have time, memory and row limits. Generated queries must reproduce the independent fixture results at all 41 timestamps before being activated, including a check that future rows stay out. Up to three setup attempts are allowed per query. Validated plans are saved for reuse.

Each live tick sends the resulting evidence to the configured Decisions model, which chooses `match`, `clear` or `unknown` for each enabled watch. SQL returns measurements, not the final match flag. Application code enforces freshness, handles repeated matches, and creates local tasks. The short numeric alert explanations are formatted from evidence; the event-review summary is model-written. API failures pause playback and produce unknown results. **Retry check** retries the same minute without clearing alerts; there is no silent scripted fallback.

**Bounded scope:** the six questions are presets, not an unrestricted chat interface. In explicit `--offline` mode, SQL templates and deterministic decisions replace the models.

**Database:** DuckDB stands in for the diagram's ClickHouse service, so the demo needs no running Docker engine. This is a real local database, not canned UI responses. A ClickHouse version would need a database adapter and SQL dialect changes.

**Actions:** the local task list demonstrates the last architecture step. MCP, email, Slack and external APIs are not connected. Nothing is sent outside the app.

**Schema checks:** run at startup, every 24 hours of server uptime, and on demand. A changed structure pauses playback until reset; this demo does not use a model to repair SQL. A query failure produces an unknown result and pauses playback. Missing current rows produce an unknown result and do not close an existing incident.

**Historical comparisons:** reserve history has 174 observations across 2023–2025. Congestion history covers 91 days at hourly intervals; new observations arrive each minute. The percentile is over available observations, not time-weighted. All timestamps are stored in UTC and displayed in Eastern time. The July timing avoids daylight-saving ambiguity.

All names, readings, lines and incidents are fictional. ERCOT and PJM are separate examples; the shared timeline does not establish causation.

## Files and generated data

All demo files stay in this folder:

- `dataset.py` — tables, historical baselines and replay records.
- `rules.py` — the five questions, definitions and read-only SQL plans.
- `engine.py` — replay clock, data ingestion, checks, alert state and tasks.
- `live_models.py` — model-generated SQL, fixture validation, batched decisions, summaries and actual token accounting.
- `server.py` — loopback-only HTTP server and server-sent event stream.
- `static/` — UI and a reference copy of the proposed architecture diagram.
- `runtime/grid.duckdb` — generated database, including readings, checks, alerts and tasks.
- `runtime/replay.csv` — the full reproducible replay fixture. It contains future replay rows intentionally; queries/UI receive only ingested rows.
- `runtime/saved_rules.json` — the active SQL plans and definitions.
- `runtime/model_plans.json` — validated model-generated queries with a configuration/schema cache key.
- `runtime/setup_attempts.jsonl` — generated SQL from setup attempts.
- `runtime/model_calls.jsonl` — API call metadata and actual provider-reported token usage (never the API key).
- `runtime/live_validation.json` — the completed live replay validation report.

Runtime files are ignored by Git. Watch switches and playback state are in memory; resetting/restarting returns to the initial state. This is a single-user demo, not a production notification service.

## Prompt caching and usage

The stable decision instructions and definitions precede the changing evidence. An explicit prefix cache breakpoint requests reuse with the Decisions API's supported 30-minute lifetime. The UI shows actual API calls, input/output tokens, cached input and cache writes across the saved call history, including setup/validation runs. A counter of zero means the provider reported no cached tokens; it is not replaced with an assumed discount. These are token counts, not a billing estimate.

API references: [Decisions](https://developers.openai.com/api/docs/guides/decisions), [structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs), [prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching).

## Verify

```sh
.venv/bin/python -m unittest discover -s experimental/grid-watch/tests -v
node --check experimental/grid-watch/static/app.js
```

The 15 offline tests make no API calls. They check the live integration with a fake provider, model-failure handling, SQL access restrictions, expected trigger times, strict thresholds, both sides of the combined condition, voltage/region exclusions, no future-data leakage, missing-data behavior, duplicate suppression, task idempotency, pause/reset, schema changes and the event timeline.

A separate paid end-to-end replay was also completed: 205 SQL checks, all five expected first-trigger times, five recoveries, and a live event summary. Its report is in `runtime/live_validation.json`. Model behavior can vary on later runs.
