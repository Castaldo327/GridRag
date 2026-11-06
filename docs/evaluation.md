# Schema retrieval evaluation

## Question

Compare GridRag's model-scored table/column routing with a practical embedded schema
retriever. Both must produce SQL evidence from the same synthetic warehouse. A
full-schema prompt baseline is intentionally excluded.

## Protocol

- **Catalog:** 65 explicitly registered tables with identical DDL documentation.
- **Routed:** current table and column probability thresholds; foreign-key closure;
  structural keys and time columns retained.
- **Dense:** local `BAAI/bge-small-en-v1.5`, cosine similarity in Qdrant, one DDL document
  per table, top 4 or top 6 documents followed by identical foreign-key closure.
  All 65 documents fit within the embedding model’s 512-token window (largest: 301
  tokens in this catalog). All columns of retrieved tables go to the SQL model. These sizes are fixed before
  evaluating, not tuned on the results. Embedding similarity is not a probability.
- **Shared:** relevance gate, SQL/answer model, prompt rules, 10-table budget, repair
  rounds, read-only guard, resource limits and synthetic database.
- **Cases:** 12 existing public cases plus 6 additional author-written questions.
  Fifteen numerical questions and three behavior cases. The additions vary regions,
  dates and products; they are not an independently collected holdout dataset.
- **Runs:** three attempts per question per method; seeded, shuffled order. No
  outcome-based retries or discarded failures. API transport retries follow the same
  application settings for every method.
- **Ground truth:** independent SQL computed before the run. Reference SQL and
  expected values never reach the model. Numeric questions append the same request
  for a one-row, one-column final SQL result for each method.

## Measured run · November 5, 2026

18 questions × 3 repetitions × 3 methods = **162 attempts**. The same `gpt-6-luna` model handled SQL and answers for every method. Qdrant server: `v1.16.3`.

| Method | Overall accuracy | Numeric accuracy | Median latency | p95 latency | Est. model cost / question |
| --- | ---: | ---: | ---: | ---: | ---: |
| Routed schema | 92.6% | 91.1% | 4.50 s | 8.35 s | $0.002947 |
| Qdrant top 4 | 64.8% | 64.4% | 3.39 s | 13.73 s | $0.000271 |
| Qdrant top 6 | 72.2% | 73.3% | 3.44 s | 11.12 s | $0.000272 |

Routed retrieval selected every required table on the numeric cases, but still made four incorrect answers: three California-to-ISO alias mistakes and one interval-alignment mistake. Schema recall alone does not establish answer correctness.

Against top-6 retrieval, the observed overall accuracy difference was **+20.4 percentage points** (95% case-bootstrap interval: **+1.9 to +40.7 points**). The routed approach used about **10.8×** the estimated model cost and added **1.06 seconds** to median latency. Table/column scoring dominates that extra cost; a smaller final SQL schema does not imply fewer total input tokens.

The embedding baselines missed context needed for hourly demand, five-minute generation and the multi-product forecast-error case. Both also answered the over-broad scope question instead of asking for clarification. Their cheaper, faster median responses are a real tradeoff in this experiment, not a claim that dense retrieval is generally inferior.

Index construction took **3.88 seconds** with the embedding weights already cached. All numerical documents fit the embedding context window. Recorded outcome and evidence: [benchmark JSON](../app/static/benchmark.json). The `failures` aggregate counts pipeline failure states; wrong answers and SQL write failures remain in the accuracy denominator.

## Measurements

**Primary accuracy:** expected end state and exact scalar evidence within each
case's numeric tolerance. Behavior cases require the expected decline/clarification
and no SQL calls. Merely finding the expected number somewhere in a large result
is insufficient. This metric measures SQL outcome correctness, not the full semantic
quality of the natural-language explanation. Prose and routing checks are secondary.

**Retrieval:** recall of required tables including foreign-key dependencies; all
required tables present; extra table count; delivered schema characters. Alternative
valid SQL can use different tables, so extra-table count is not called precision.

**Latency:** end-to-end wall time, median and nearest-rank p95. Routing timing is
also retained for each attempt. Index construction is measured separately and
excluded from per-question latency. These are local-client timings, not Vercel
cold-start benchmarks, and the vector cache is warm after initial indexing.

**Cost:** model input/output tokens at the application's configured rates. Cached
input is accounted for separately. This excludes local embedding computation,
Qdrant hosting, database hosting and any unreported billing on failed requests.
It is not an invoice or total operating cost. All configured rates are in the JSON.

**Uncertainty:** paired accuracy differences, with a seeded 2,000-sample bootstrap
resampling cases and preserving repetitions within each case. Repeated attempts
are not independent new questions. An interval crossing zero does not establish
which method has higher accuracy.

## Reproduction and artifacts

Follow the commands in the [README](../README.md#reproduce-the-comparison).
`artifacts/benchmark.json` holds the full local run: manifest, outcomes, generated
SQL, evidence, timings and usage. It is written atomically after each attempt.
An interrupted run is a partial artifact and must not be represented as complete.
The manifest records model names, package versions and schema/case fingerprints.

The website publishes a reviewed JSON projection under
`app/static/benchmark.json`, including all per-attempt outcomes and aggregate metrics.
It contains no environment configuration, credentials, personal paths or Git metadata.
The app shows an explicit unpublished state if no artifact exists.

## Limits

This small synthetic catalog is especially suited to examining grain, time, region,
forecast vintage and units. It cannot establish performance on thousands of tables,
unfamiliar organizational schemas, multilingual questions, changing schemas or
messy real-world data. Dense retrieval can be improved with chunking, hybrid search,
reranking, query decomposition or learned abstention; this experiment does not
claim to represent those systems. Both approaches still depend on the SQL model.

The top-k baseline can return a plausible partial answer for a broad multi-region
question because retrieval always selects a bounded number of tables. Its behavior
on that case is part of the reported comparison, not a numeric-query failure.
Read numeric-only and behavior-only outcomes alongside overall accuracy.

[Qdrant local setup](https://qdrant.tech/documentation/quickstart/) and
[FastEmbed schema/document embedding](https://qdrant.tech/documentation/fastembed/fastembed-semantic-search/)
provide the upstream retrieval implementation references.
