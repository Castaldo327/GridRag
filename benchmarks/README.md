# Grounding and capability evaluation

The benchmark has 30 answerable development questions: 7 easy, 8 medium,
8 hard and 7 very hard. Difficulty describes analytical operations, not measured
model outcomes. Questions cover lookups, aggregates, fuel shares, queue filters,
forecast cutoffs, UTC boundaries, storage, outages, curtailment, window rankings,
revenue, and multi-step comparisons. These inspected questions are not a held-out
production test.

## Shared schema context

All three methods use supplied schema documentation plus the same seven-ISO
entity vocabulary in SQL generation. California → `CAISO`, Texas → `ERCOT`,
New England → `ISONE`, and the remaining ISO names map to exact values in the
ISO code column. These are catalog metadata, scoped to selected columns; custom
catalogs receive no demo entities. There are no fuel, location, or queue-status
aliases. The vocabulary is not used by embeddings, BM25, or reranking.

The request gate classifies analytical database requests rather than a fixed
industry. SQL instructions use documented units and time semantics. Structural
columns follow declared keys, references, and date/time types. Table-specific
relevance rules and custom metadata scorers remain removed. The synthetic
warehouse and independent reference queries remain evaluation fixtures.

## Retrieval settings

- **Routed:** independently score all tables, expand references, then score columns.
- **Dense (`vector-k21`):** BGE-small + Qdrant, top 21 tables, reference expansion,
  and all columns.
- **Hybrid (`vector-hybrid-k25`):** retrieve 48 dense candidates and add up to 12
  BM25 matches over supplied schema documents. Fuse semantic/keyword scores with
  weights 0.6875/0.3125, preserving their previous relative weighting. There are no
  table-specific scoring rules or domain alias expansions. Region, measure,
  cadence and coverage are interpreted from schema documentation by the reranker.
  Rerank the entire union (at most 60 tables) against the full question with one
  OpenAI Decisions API call (`POST /v1/decisions`, `gpt-6-luna`). Each candidate
  gets a predicate relevance probability; candidates are sorted by that probability,
  with fusion scores breaking ties. Keep relevant candidates up to 25, then expand
  references.
  The total 25-table budget still applies after expansion; excess context asks
  for clarification and fails an answerable task. The reranker is paid and its
  calls, tokens, latency and estimated cost are included.

All methods share the same gate, SQL model, seven-ISO entity vocabulary, repair budget, guard,
**25-table total evaluation budget**, and **4,096 SQL output-token limit**.
The playground's default limits remain unchanged. Mostly unusable reranker scores
fail explicitly; partially unusable scores retain candidates conservatively.
No reference SQL, expected values or required-table labels reach retrieval.
The manifest records settings, versions, schema and case hashes. Settings stay
fixed during the run; all failures are retained.

Current runs record pipeline version `schema-driven-iso-entities-v1`, grounding
version `iso-entities-v1`, the seven-entry vocabulary hash, and fusion version
`semantic-bm25-v1`. Publication requires a fresh run with this shared ISO-only
vocabulary and no custom metadata scoring. The checked-in results
come from a fresh run of this pipeline.

Removing these rules supports reuse of the query logic; this single synthetic
domain does not establish cross-domain production accuracy or catalog-scale
performance. BM25 currently scans schema documents per question.

## Scoring

Each of the 30 questions runs three times for each of 3 methods: 270 attempts.
Each method has 90 attempts. Cumulative accuracy is the number of correct
answers divided by all 90 attempts, including failures. Each trial also has a
separate 30-question score per method; no best-trial or best-answer selection is used. Scalar
questions require one finite numeric value in the complete final SQL result,
matching the independent reference within the case tolerance. The seven-ISO price
comparison requires all 21 ISO/product keys and numeric values, without duplicates,
missing or extra rows, in any row order. Its expected result is an answer, not a
budget refusal. Table recall and prose diagnostics are separate from correctness.

The three observed trial scores show run-to-run variation. Case-bootstrap
intervals keep repeated attempts clustered within each question and describe
uncertainty over these questions; three trials do not establish model reliability. Safety/refusal
checks remain in the separate 26-case regression suite and are not mixed into the
capability accuracy score. Changing the suite or budgets prevents direct causal
comparison with earlier results.

## Reproduce

```sh
uv sync --locked --extra eval
docker compose up -d qdrant
uv run --extra eval python -m benchmarks.run --live --repeats 3 --max-tables 25 --output artifacts/benchmark-iso-entities-3trials.json
uv run python -m scripts.publish_benchmark --input artifacts/benchmark-iso-entities-3trials.json
docker compose stop qdrant
```

Reports checkpoint every completed attempt. The publisher requires a complete
live report and writes the sanitized local `app/static/benchmark.json`; it does
not deploy. The exported JSON includes cumulative summaries, per-trial summaries,
and every recorded attempt. Retrieval-only runs omit `--live`; hybrid then uses fusion without
the paid reranker and may exceed the table budget. Those diagnostics are not
substitutes for live capability scores.

Each live trace records the Decisions endpoint and configured model. Repeated
trials can differ with identical retrieval settings; score differences
alone do not establish an algorithmic improvement. See the
[OpenAI Decisions guide](https://developers.openai.com/api/docs/guides/decisions)
for the predicate relevance-scoring contract.
