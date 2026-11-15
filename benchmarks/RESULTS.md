# Recorded results after DuckDB catalog simplification

Run date: November 14, 2026 (America/New_York). Experiment `decisions-vs-reranker-30-v3`: 30 unchanged analyst questions, three trials per pipeline, 180 attempts. All attempts are included. Models: `gpt-6-luna` for Decisions and `gpt-6-luna` for SQL and answers. These are synthetic development results, not a production accuracy estimate.

This rerun uses the simplified architecture: a cached catalog read from DuckDB metadata, persisted table/column descriptions, one assessment per attempt using precomputed references, and report format 9. Questions, reference SQL, scoring tolerances, candidate policy, model names and shared evaluation budgets were not tuned after observing this run.

Qdrant uses `ceil(0.20 × 65) = 13` candidates. Dense and keyword retrieval each propose up to 13 tables; fusion caps their combined shortlist at 13 before Decisions reranking. Foreign-key references are expanded afterward. The shared SQL context budget is 25 tables and 4,096 output tokens.

| Pipeline | Trial 1 | Trial 2 | Trial 3 | Cumulative correct | Median time | Est. cost / attempt |
| --- | --- | --- | --- | --- | --- | --- |
| GridRag | 24/30 | 24/30 | 24/30 | 72/90 · 80.0% | 4.58 s | $0.00392 |
| Vector + Decisions reranker (20% cap) | 19/30 | 19/30 | 19/30 | 57/90 · 63.3% | 3.77 s | $0.00094 |

## Selection, latency and model use

| Measurement | GridRag | Vector + Decisions reranker |
| --- | --- | --- |
| Candidate-table recall | 100.00% | 88.63% |
| Final required-table recall | 94.85% | 81.90% |
| Attempts with candidate omissions | 0/90 | 30/90 |
| Attempts whose reference exceeds the candidate cap | 0/90 | 3/90 |
| Mean selected columns | 22.0 | 21.7 |
| Mean schema characters | 3,393 | 2,996 |
| Mean pipeline input tokens | 39,694 | 10,152 |
| p95 answer-pipeline latency | 15.82 s | 13.01 s |
| Median request-gate latency | 0.28 s | 0.28 s |
| Median schema-selection latency | 1.03 s | 0.30 s |
| Median SQL and answer latency (when reached) | 3.17 s | 3.42 s |

GridRag minus reranker accuracy difference: **+16.7 percentage points**; 95% case-cluster bootstrap interval **[+3.3, +30.0] points**. Repeated attempts stay clustered by question. This interval describes this development suite, not production reliability.

One-time embedding/index initialization: 4.92 s, excluded from per-question latency. Total estimated comparison model cost: $0.4375. Latency and cost include unsuccessful attempts and abstentions. Costs exclude local embedding compute, Qdrant hosting and unreported failed-call billing.

**Timing boundary:** format 9 times only the answer pipeline, stopping before grading and client cleanup. The previous format-8 report included evaluator work. Its latency figures are not directly comparable. The catalog text and table order also changed, so differences from the earlier accuracy result (80/90 versus 59/90) cannot be attributed to parser removal alone.

## Results by capability

| Capability | Questions | GridRag correct | Reranker correct |
| --- | --- | --- | --- |
| joins | 5 | 12/15 | 12/15 |
| operations | 6 | 15/18 | 15/18 |
| products | 6 | 18/18 | 18/18 |
| regional | 5 | 9/15 | 0/15 |
| scope | 3 | 9/9 | 6/9 |
| temporal | 5 | 9/15 | 6/15 |

## Questions with incorrect attempts

Inspect the recorded SQL, selected columns and returned data in the Evaluation page. Missing required tables are diagnostics against the fixed reference; alternative valid queries can exist. Full table recall does not guarantee correct SQL or selected columns.

| Question | GridRag correct | Reranker correct | Reranker diagnostic |
| --- | --- | --- | --- |
| `pjm_proposed_batteries` | 3/3 | 0/3 | candidate omissions in 3/3; final table omissions in 3/3 |
| `pjm_pre_delivery_bias` | 0/3 | 0/3 | candidate omissions in 3/3; final table omissions in 3/3 |
| `spp_available_wind_share` | 0/3 | 0/3 | candidate omissions in 3/3; final table omissions in 3/3 |
| `new_england_demand_ramp` | 3/3 | 0/3 | candidate omissions in 3/3; final table omissions in 3/3 |
| `annual_regional_peak_gap` | 3/3 | 0/3 | candidate omissions in 3/3; final table omissions in 3/3 |
| `new_york_forecast_mae` | 0/3 | 0/3 | candidate omissions in 3/3; final table omissions in 3/3 |
| `california_net_load_peak_price` | 0/3 | 0/3 | candidate omissions in 3/3; final table omissions in 3/3 |
| `regional_peak_renewable_gap` | 3/3 | 0/3 | candidate omissions in 3/3; final table omissions in 3/3 |
| `all_region_forecast_error` | 0/3 | 0/3 | candidate omissions in 3/3; final table omissions in 3/3 |
| `all_region_battery_energy` | 0/3 | 0/3 | candidate omissions in 0/3; final table omissions in 3/3 |
| `all_iso_prices` | 3/3 | 0/3 | reference exceeds candidate cap |

## Live regression suite

The separate 26-case suite used application defaults (10 tables / 1,600 output tokens): **5/26 passed every diagnostic check; 23/26 met task-level state/evidence criteria**. Twenty-one cases lacked an explicit answer-unit label; 17 failed only that check. Three cases also failed task criteria, and two selected excluded tables. All four behavior cases passed their full checks. See the [complete regression results](REGRESSION_RESULTS.md). The live regression unittest command therefore failed; it is not reported as a passing test suite.

## POC limitations

The 20% cap prevents nearly exhaustive candidate retrieval in this 65-table catalog. A fixed percentage does not reproduce a production-sized database or establish a production-optimal top_k. These implementations also differ in column selection, so results measure whole pipelines and do not isolate candidate generation.

The broad price task requires 21 independent source tables, exceeding the 13-candidate budget even with perfect ranking. All three vector attempts remain scored and are labeled as structurally constrained. Its failures cannot by themselves establish poor vector ranking. Other questions can lose required sources through candidate ranking or subsequent relevance filtering.

The public evidence is in [`app/static/benchmark.json`](../app/static/benchmark.json). The fixed questions are in [QUESTIONS.md](QUESTIONS.md); [README.md](README.md) describes the protocol. The complete raw rerun is retained locally at `artifacts/benchmark-duckdb-format9-2026-11-14-3trials.json` (ignored by Git).
