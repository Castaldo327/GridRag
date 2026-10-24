# Core audit — October 24, 2026

Reviewed the table-and-column router, catalog adapter, model interface and usage recording, configuration, orchestration, SQL execution boundary, CLI, and their tests. The web app and warehouse generator remain demo infrastructure. Existing in-progress edits were preserved.

## Changes made

| Finding | Resolution |
| --- | --- |
| Column definitions were reparsed during scoring, selection, and schema rendering. | Cache immutable definitions, column mappings, and structural-column sets on each table. |
| Column pruning could drop a table-level foreign-key column or a unique referenced key whose name lacked an identifier suffix. | Retain declared primary, foreign, and unique keys; retain matching constraints in the SQL context. Keep the existing conservative identifier/time fallback. |
| Commas and parentheses in quoted defaults could corrupt column splitting; incomplete definitions could be accepted. | Treat quoted literals and comments as opaque, reject incomplete/unsupported definitions, and test executable excerpts. This is still a scoped DDL adapter. |
| Invalid worker counts and probability thresholds failed late or silently changed routing behavior. | Validate frozen Settings and Rates dataclasses with Pydantic, including strict types, finite numbers, and ranges. Preserve dataclasses.replace and immutable price mappings. |
| Provider scores needed consistent runtime validation. | Validate probabilities through a small Pydantic model. Malformed values remain uncertainty rather than becoming false rejections. |
| Column output was validated only after all requests completed. | Validate results as they complete, cancel queued requests on failure, and assemble successful selections in catalog order. Already-running requests still finish under their provider timeouts. |

## Responsibilities

- `catalog.py`: trusted schema metadata, immutable cached parsing, and schema excerpts.
- `route.py`: table scoring, dependency closure, column scoring with bounded workers, and selection policy. Concurrency is isolated from the main orchestration function.
- `config.py`: validated settings and environment loading.
- `llm.py`: provider calls, score validation, streaming, and locked usage accounting. Injected Model implementations must support concurrent decide calls.
- `answer.py`: stage orchestration, progress, timing, and safe failure records.
- `sql/agent.py` and `db.py`: model/tool repair and independently guarded database execution.
- `records.py`: internal JSON-compatible TypedDict contracts. These are static types, not runtime validators; Pydantic is used at configuration/provider-value boundaries.

## Remaining limits and tradeoffs

1. **Quality and latency need fresh live evaluation.** The previous report measured family routing. The new router scores all 65 physical tables, then makes one additional call per selected table. Four workers overlap calls but do not reduce billable work. Column pruning can omit a necessary measure even when table selection is correct.
2. **Column pruning is not authorization.** The SQL guard enforces selected tables, not selected columns. The gate is also a classifier, not an entitlement check.
3. **Concurrency is per question.** A deployed service needs an overall admission/rate limit and request deadline. Canceling a Future cannot stop an HTTP request already running; SDK timeout/retry settings govern that work.
4. **The catalog adapter has a defined scope.** It supports this project's unquoted schema/table/column names and documented CREATE TABLE format. It is not a general SQL parser or live introspector. A broader SQL dialect needs a deliberate catalog adapter, not more routing conditionals.
5. **Successful SQL is not proof of a correct answer.** Join multiplicity, temporal alignment, coverage and interpretation still require evaluations. Read-only access and best-effort query interruption do not replace process isolation for untrusted workloads.

## Validation

61 offline tests passed; the paid live evaluation test was skipped. Checks cover bounded parallel column decisions, failure on unusable column output, key retention, quoted defaults, malformed score/configuration rejection, SQL restrictions, streaming, and existing API/CLI contracts. `uv lock --check --offline` and `git diff --check` passed. Pydantic is now a direct dependency; existing locked package versions were retained.
