# Decisions versus vector retrieval with reranking

**Can OpenAI's Decisions API simplify schema selection for text-to-SQL, and what
are the tradeoffs in accuracy, latency, and cost?**

This experiment compares two complete schema-selection pipelines. It contains no
standalone vector top-k baseline. Both approaches use Decisions; the experiment
asks whether starting from the full catalog can replace an embedding/index/retrieval
pipeline, and what column selection adds to the resulting tradeoffs.

## Thirty realistic tasks

The [question matrix](QUESTIONS.md) lists every question, its analytical difficulty,
and the capability it probes. The suite includes 7 easy, 8 medium, 8 hard and
7 very hard questions, spanning six areas:

- **Scope:** historical coverage, regional names, actual demand and proposed capacity.
- **Products:** bus versus hub, day-ahead versus real-time, reserves versus energy,
  and generated versus curtailed power.
- **Joins and denominators:** fuel shares, capacity weighting and protection against
  multiplying a denominator through a one-to-many join.
- **Temporal reasoning:** UTC versus local dates, publication cutoffs, per-hour
  forecast vintages and consecutive readings.
- **Operations:** dispatch, outages, energy conversion, revenue and weighted prices.
- **Regional breadth:** independent regional peaks and comparisons requiring seven
  forecast tables, seven dispatch tables, or all 21 regional price products.

All 30 are answerable against the fictional warehouse. Questions, independent
reference queries, tolerances and settings are fixed before the live run. Questions
are not chosen or rewritten after seeing which method wins; failed attempts are
retained. This is an inspected development suite, not a held-out production test.
Unavailable-data and misuse checks stay in the separate 26-case regression suite
rather than mixing abstention behavior into analytical accuracy.

## Pipelines

- **GridRag (`routed`):** score every catalog table independently in one Decisions
  call, retain scores at or above 0.2, recursively expand outgoing foreign-key
  references, then score each selected table's columns concurrently (four workers).
  Retain columns at or above 0.2 plus declared keys and date/time fields.
- **Vector retrieval + reranking (`vector-hybrid-p20`):** embed documented tables
  using BGE-small and index them in Qdrant. Fix candidate top_k at 20% of the
  catalog, rounded up: **13 of 65 tables**. Retrieve up to 13 dense and 13 BM25
  candidates over the same schema documentation. Fusion weights remain semantic
  0.6875 / keyword 0.3125; truncate the combined ranking to 13 tables **before**
  Decisions reranking. Keyword matches cannot expand that cap. Use exactly the
  same table relevance prompt and 0.2 threshold as GridRag, then recursively
  expand foreign-key references. Supply all columns from the selected tables.

Both share the documented DDL, seven-ISO entity vocabulary in SQL generation,
request gate, SQL model, repair budget, read-only guard, **25-table total evaluation
budget including references**, and **4,096 SQL output-token limit**. The playground
keeps its existing defaults. No table-specific rules, query aliases, expected
values, required-table labels or reference SQL reach retrieval. The vocabulary
contains ISO names only; it is not used by embedding retrieval, BM25 or reranking.

Reference expansion is shared, and vectors can also support column selection.
These two implementations differ in both candidate generation and column pruning;
this experiment measures the whole pipelines and does not identify either change's
independent causal effect. The previous 48-dense-plus-12-keyword setting could
expose up to 60 of 65 tables to Decisions. Those results belong to experiment v2
and are not presented as evidence for the new policy. The fixed 20% policy is
chosen before this run, without tuning to its outcomes or a candidate-budget sweep.

This synthetic POC is not a production-sized warehouse. A percentage cap reduces
nearly exhaustive retrieval but does not establish production-scale performance.
The broad price task requires 21 independent price tables and is structurally
uncoverable under the 13-candidate cap. It stays in the suite and accuracy
denominator; the UI labels its candidate-budget shortfall. Other tasks can also
lose required tables through ranking. Foreign-key expansion happens after the
candidate cap and can increase final table count within the shared 25-table limit.

## Measurements and scoring

Each question runs three times per pipeline: **180 attempts total, 90 per method**.
Seeded shuffled question and method order is fixed before execution. Cumulative
accuracy includes all attempts and failures, with trial scores reported separately.

Scalar tasks require exactly one finite numeric value in the complete final SQL
result, within the reference's absolute tolerance (normally 0.01). The price
comparison requires all 21 ISO/product keys and matching numeric values, without
missing, duplicate or extra rows. Clarification fails an answerable task. Route
and prose diagnostics are reported separately from evidence-based task correctness.
Reference SQL is evaluated before the first paid model call.

The report and UI include:

- End-to-end accuracy, median and p95 latency, estimated model cost, and input tokens.
- Required-table recall after selection, including reference expansion.
- Candidate-table recall before relevance filtering, including references that
  remain recoverable; missing candidate tables and structural budget shortfalls
  are listed per attempt. GridRag
  starts with the full catalog, so its candidate recall is 100% by construction.
- Selected column count and schema characters, with per-attempt schema-selection
  timing, SQL, returned data and answers.
- Trial summaries and a paired case-cluster bootstrap interval for the accuracy
  difference. Repeated attempts stay clustered within each question.

Latency is warm-index query latency: one-time embedding/index construction is
reported separately as `index_seconds`. Estimated costs include the request gate,
Decisions table/column scoring or reranking, SQL generation, repairs and answering.
They exclude local embedding compute, Qdrant hosting and unreported failed-call
billing; configured token rates are estimates, not billing records. Fewer columns
in the SQL prompt do not necessarily mean fewer total pipeline tokens.

The versioned manifest records experiment `decisions-vs-reranker-30-v3`, pipeline
`schema-driven-iso-entities-v1`, question and schema hashes, model and package
versions, budgets, thresholds, worker count, seed, vocabulary hash and fusion
version, catalog size, candidate percentage, derived k and cap policy version.
Questions are unchanged from v2; the candidate policy changed, so results carry
a new experiment version. No claim of production accuracy or catalog-scale performance follows
from this small synthetic suite.

The [recorded results and failure analysis](RESULTS.md) summarize the completed run.

## Reproduce

```sh
uv sync --locked --extra eval
docker compose up -d qdrant
uv run --extra eval python -m benchmarks.run --live --repeats 3 --max-tables 25 --output artifacts/benchmark-decisions-vs-reranker-p20-3trials.json
uv run python -m scripts.publish_benchmark --input artifacts/benchmark-decisions-vs-reranker-p20-3trials.json
docker compose stop qdrant
```

The live run uses the configured API key and incurs model usage. Reports checkpoint
every completed attempt. Publication requires a complete live run of both methods
with the current question hash, experiment version, shared context and 20%
combined candidate cap. Per-attempt shortlist sizes are checked before publication. It writes
sanitized local `app/static/benchmark.json` and does not deploy the site.

Without `--live`, only the vector candidate/fusion diagnostic runs, with no reranking
or model calls. These retrieval-only results are not a substitute for live accuracy.
Each run owns and removes its own Qdrant collection, preserving other collections.
