# Grounding and capability evaluation

The benchmark has 30 answerable development questions: 7 easy, 8 medium,
8 hard and 7 very hard. Difficulty describes analytical operations, not measured
model outcomes. Questions cover lookups, aggregates, fuel shares, queue filters,
forecast cutoffs, UTC boundaries, storage, outages, curtailment, window rankings,
revenue, and multi-step comparisons. These inspected questions are not a held-out
production test.

## Shared grounding

The approved catalog vocabulary maps terminology to exact database values:
California/California ISO → `CAISO`, Texas → `ERCOT`, and New England/ISO New
England → `ISONE`, plus fuel codes, fictional price locations and queue statuses.
A project's state is separate: `state = 'CA'` differs from `iso_code = 'CAISO'`.
Only vocabulary for selected columns reaches SQL. Custom catalogs opt in with
their own metadata. Grounding does not expand SQL permissions or alter the
embedding documents.

## Retrieval settings

- **Routed:** independently score all tables, expand references, then score columns.
- **Dense (`vector-k21`):** BGE-small + Qdrant, top 21 tables, reference expansion,
  and all columns.
- **Hybrid (`vector-hybrid-k25`):** retrieve 48 dense candidates and add up to 12
  BM25 matches. Fuse semantic/keyword/metadata signals with weights 0.55/0.25/0.20.
  Metadata covers region, physical measure, cadence and documented coverage.
  Rerank the entire union (at most 60 tables) against the full question with one
  Decisions call. Keep relevant candidates up to 25, then expand references.
  The total 25-table budget still applies after expansion; excess context asks
  for clarification and fails an answerable task. The reranker is paid and its
  calls, tokens, latency and estimated cost are included.

All methods share the same gate, SQL model, grounding, repair budget, guard,
**25-table total evaluation budget**, and **4,096 SQL output-token limit**.
The playground's default limits remain unchanged. Mostly unusable reranker scores
fail explicitly; partially unusable scores retain candidates conservatively.
No reference SQL, expected values or required-table labels reach retrieval.
The manifest records settings, versions, schema and case hashes. Settings stay
fixed during the run; all failures are retained.

## Scoring

Each of the 30 questions runs once for each of 3 methods: 90 attempts. Scalar
questions require one finite numeric value in the complete final SQL result,
matching the independent reference within the case tolerance. The seven-ISO price
comparison requires all 21 ISO/product keys and numeric values, without duplicates,
missing or extra rows, in any row order. Its expected result is an answer, not a
budget refusal. Table recall and prose diagnostics are separate from correctness.

One attempt cannot estimate model variability. Case-bootstrap intervals describe
uncertainty over these questions, not repeated-trial reliability. Safety/refusal
checks remain in the separate 26-case regression suite and are not mixed into the
capability accuracy score. Changing the suite or budgets prevents direct causal
comparison with earlier results.

## Reproduce

```sh
uv sync --locked --extra eval
docker compose up -d qdrant
uv run --extra eval python -m benchmarks.run --live --repeats 1 --max-tables 25
uv run python -m scripts.publish_benchmark
docker compose stop qdrant
```

Reports checkpoint every completed attempt. The publisher requires a complete
live report and writes the sanitized local `app/static/benchmark.json`; it does
not deploy. Retrieval-only runs omit `--live`; hybrid then uses fusion without
the paid reranker and may exceed the table budget. Those diagnostics are not
substitutes for live capability scores.
