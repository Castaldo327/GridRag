# Grid Watch

A local experiment in intelligent grid alerts. Experimental and not part of submission. Four watches check incoming measurements every five simulated minutes. An alert reports a measured condition; its cause remains unknown.

## Run

From the repository root:

```sh
./experimental/grid-watch/run.sh
```

Open **http://127.0.0.1:8011**. Live mode uses the existing `OPENAI_API_KEY`, `GRIDRAG_ANSWER_MODEL` and `GRIDRAG_DECISIONS_MODEL` configuration, including the repository `.env`. The API key stays on the server. Fictional measurements, questions and schema go to OpenAI; follow-up tasks stay local.

Use `--offline` for scripted decisions without API calls, `--play` to start immediately, or `--port 8012` to choose a different port. Stop with Ctrl+C. Startup and **Reset replay** rebuild this demo's database and clear alerts/tasks. Validated model-generated queries and usage logs survive resets.

## Try it

1. Click **Play replay** or **Jump to 2:00 PM**. Each tick ingests five minutes of minute-level readings, then awaits one batched Decisions API call. The speed selector sets the delay between ticks; API time is additional.
2. Watch reported load, reserves and congestion update. The chart compares actual load with forecast; it does not attribute changes to an operational event.
3. Open a watch or click **View evidence** to inspect the query, measurements and decision.
4. Click **Create local task** on a triggered alert, or enable automatic local tasks in that watch's details. Nothing is sent to another service.
5. Open **Data & queries** to inspect the tables, definitions and database structure check, or download the replay CSV.

## Watches

| Watch | Condition | First detection (Eastern) |
| --- | --- | --- |
| Sudden load drop | Dominion load drops strictly more than 1,000 MW versus exactly 10 minutes earlier | 2:05 PM |
| Unusually low reserves | ERCOT reserves fall below the seasonal 10th percentile | 2:05 PM |
| Unusual node congestion | Congestion at fictional node `NVA-DEMO-01` reaches the trailing 90-day 95th percentile | 2:05 PM |
| Load above forecast | Dominion actual load exceeds 105% of its matching forecast | 2:10 PM |

Checks run at 1:40, 1:45, 1:50 PM and so on. Detection can lag a measurement change by up to five simulated minutes. Each condition triggers once and later clears; the replay ends at 2:20 PM. A condition clearing means the latest reading no longer meets the rule. It does not establish that a grid incident has been resolved.

All data is fictional. The stream contains load, forecasts, reserves and congestion, with historical baselines. It contains no line-status reports or prewritten explanations of what influenced the readings. Dominion and ERCOT are separate markets; coincident changes do not establish a connection.

## Model behavior

The configured Responses model generates four evidence queries from the questions, agreed definitions, schema and field contracts. Reference SQL is never supplied to the model. Each query must pass the read-only parser guard and independent fixture comparisons at all 41 timestamps before activation. Queries have time, memory and row limits; database file/network access is disabled. Validated queries are saved and reused.

Each tick sends the resulting measurements to the configured Decisions model, which selects `match`, `clear` or `unknown` for each enabled watch. Application code checks freshness, suppresses repeated matches and applies local task permissions. The short alert descriptions format the observed numbers; they do not explain causes. Failed API calls pause playback and produce unknown results. **Retry check** retries the same minute without clearing alert history.

This is a bounded, single-user demo. DuckDB supplies the local database. ClickHouse, MCP and external notification destinations are not connected. `--offline` explicitly uses reviewed SQL and deterministic decisions instead of model calls.

## Baselines and structure checks

- Reserves: 174 historical observations across 2023–2025, July 8–August 5, comparing the same UTC hour (the same local hour in July).
- Congestion: 91 days of hourly history plus minute-level incoming readings; the percentile uses available observations in the preceding 90 days and excludes the current reading.
- All timestamps are stored in UTC and displayed in Eastern time.
- Database structure is checked at startup, every 24 hours and on demand. Changes pause playback until reset. Missing readings produce unknown results and do not clear an existing alert.

## Files

All demo files are in this folder:

- `dataset.py`: reproducible readings and historical baselines.
- `rules.py`: four watch definitions and independent reference SQL.
- `live_models.py`: SQL generation, validation, batched decisions and API usage accounting.
- `engine.py`: five-minute replay, checks, alerts and local tasks.
- `server.py`, `static/`: local HTTP service and UI.
- `runtime/grid.duckdb`: generated readings, checks, alerts and tasks.
- `runtime/replay.csv`: full replay fixture, including future rows for offline inspection; running queries receive only ingested rows.
- `runtime/model_plans.json`, `runtime/saved_rules.json`: generated and active query plans.
- `runtime/model_calls.jsonl`, `runtime/setup_attempts.jsonl`: call usage and generated SQL attempts, without API keys.
- `runtime/live_validation.json`: latest live replay validation report.

Runtime files are ignored by Git. Playback and watch switches reset on restart. API history is retained for accurate usage reporting, including earlier development runs.

## Usage and verification

Stable instructions precede changing evidence, with an explicit cache breakpoint. The UI reports actual input/output tokens, cache reads and cache writes. Zero cached tokens means zero reported reuse; no discount is assumed. These counts are not a billing estimate.

```sh
.venv/bin/python -m unittest discover -s experimental/grid-watch/tests -v
node --check experimental/grid-watch/static/app.js
```

Offline tests cover trigger timing, five-minute polling, threshold boundaries, missing/future data, model failures, read-only access, repeated alerts, tasks and startup behavior. A paid live replay validates all four generated queries and decision outcomes.
