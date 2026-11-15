# Recorded results with 0.3 relevance thresholds

Run date: November 15, 2026 (America/New_York). Experiment `decisions-vs-reranker-30-v3`: 30 unchanged analyst questions, three trials per pipeline, 180 attempts. All attempts are included. Models: `gpt-6-luna` for Decisions and `gpt-6-luna` for SQL and answers. These are synthetic development results, not a production accuracy estimate.

This rerun raises both table and column relevance thresholds from **0.2 to 0.3**. The table threshold is shared by both pipelines; column pruning applies to GridRag. The DuckDB metadata catalog, question/reference hashes, scoring, model names, candidate policy and shared evaluation budgets match the November 14 format-9 run. Settings were fixed before execution. An earlier attempt stopped when the API account had no credits; that incomplete artifact is retained locally and is not mixed into this complete rerun.

Qdrant uses `ceil(0.20 × 65) = 13` candidates. Dense and keyword retrieval each propose up to 13 tables; fusion caps their combined shortlist at 13 before Decisions reranking. Foreign-key references are expanded afterward. The shared SQL context budget is 25 tables and 4,096 output tokens.

| Pipeline | Trial 1 | Trial 2 | Trial 3 | Cumulative correct | Median time | Est. cost / attempt |
| --- | --- | --- | --- | --- | --- | --- |
| GridRag | 22/30 | 23/30 | 22/30 | 67/90 · 74.4% | 4.43 s | $0.00389 |
| Vector + Decisions reranker (20% cap) | 19/30 | 19/30 | 19/30 | 57/90 · 63.3% | 3.56 s | $0.00092 |

The previous 0.2 run scored 72/90 for GridRag and 57/90 for the reranker. The new 0.3 run scores 67/90 and 57/90, respectively. This before/after observation includes model run variability and does not isolate the effect of either threshold independently.

## Selection, latency and model use

| Measurement | GridRag | Vector + Decisions reranker |
| --- | --- | --- |
| Candidate-table recall | 100.00% | 88.63% |
| Final required-table recall | 93.59% | 79.68% |
| Attempts with candidate omissions | 0/90 | 30/90 |
| Attempts whose reference exceeds the candidate cap | 0/90 | 3/90 |
| Mean selected columns | 19.8 | 20.6 |
| Mean schema characters | 2,991 | 2,819 |
| Mean pipeline input tokens | 39,480 | 9,987 |
| p95 answer-pipeline latency | 11.98 s | 12.25 s |
| Median request-gate latency | 0.28 s | 0.29 s |
| Median schema-selection latency | 1.07 s | 0.31 s |
| Median SQL and answer latency (when reached) | 3.10 s | 3.02 s |

GridRag minus reranker accuracy difference: **+11.1 percentage points**; 95% case-cluster bootstrap interval **[+1.1, +23.3] points**. Repeated attempts stay clustered by question. This interval describes this development suite, not production reliability.

One-time embedding/index initialization: 4.92 s, excluded from per-question latency. Total estimated comparison model cost: $0.4328. Latency and cost include unsuccessful attempts and abstentions. Costs exclude local embedding compute, Qdrant hosting and unreported failed-call billing.

**Timing boundary:** format 9 times only the answer pipeline, stopping before grading and client cleanup. Older format-8 reports included evaluator work, so their latency figures are not directly comparable.

## Results by capability

| Capability | Questions | GridRag correct | Reranker correct |
| --- | --- | --- | --- |
| joins | 5 | 10/15 | 11/15 |
| operations | 6 | 15/18 | 15/18 |
| products | 6 | 18/18 | 18/18 |
| regional | 5 | 6/15 | 1/15 |
| scope | 3 | 9/9 | 6/9 |
| temporal | 5 | 9/15 | 6/15 |

## Questions with incorrect attempts

Inspect the recorded SQL, selected columns and returned data in the Evaluation page. Missing required tables are diagnostics against the fixed reference; alternative valid queries can exist. Full table recall does not guarantee correct SQL or selected columns.

| Question | GridRag correct | Reranker correct | Reranker diagnostic |
| --- | --- | --- | --- |
| `pjm_solar_share` | 1/3 | 2/3 | candidate omissions in 0/3; final table omissions in 0/3 |
| `pjm_proposed_batteries` | 3/3 | 0/3 | candidate omissions in 3/3; final table omissions in 3/3 |
| `pjm_pre_delivery_bias` | 0/3 | 0/3 | candidate omissions in 3/3; final table omissions in 3/3 |
| `spp_available_wind_share` | 0/3 | 0/3 | candidate omissions in 3/3; final table omissions in 3/3 |
| `new_england_demand_ramp` | 3/3 | 0/3 | candidate omissions in 3/3; final table omissions in 3/3 |
| `annual_regional_peak_gap` | 3/3 | 0/3 | candidate omissions in 3/3; final table omissions in 3/3 |
| `new_york_forecast_mae` | 0/3 | 0/3 | candidate omissions in 3/3; final table omissions in 3/3 |
| `california_net_load_peak_price` | 0/3 | 0/3 | candidate omissions in 3/3; final table omissions in 3/3 |
| `regional_peak_renewable_gap` | 3/3 | 1/3 | candidate omissions in 3/3; final table omissions in 3/3 |
| `all_region_forecast_error` | 0/3 | 0/3 | candidate omissions in 3/3; final table omissions in 3/3 |
| `all_region_battery_energy` | 0/3 | 0/3 | candidate omissions in 0/3; final table omissions in 3/3 |
| `all_iso_prices` | 0/3 | 0/3 | reference exceeds candidate cap |

## Live regression suite

The separate 26-case suite used the same 0.3 thresholds with application defaults (10 tables / 1,600 output tokens): **4/26 passed every diagnostic check; 24/26 met task-level state/evidence criteria**. See the [complete regression results](REGRESSION_RESULTS.md) for individual checks and the live unittest outcome.

## POC limitations

The 20% cap prevents nearly exhaustive candidate retrieval in this 65-table catalog. A fixed percentage does not reproduce a production-sized database or establish a production-optimal top_k. These implementations also differ in column selection, so results measure whole pipelines and do not isolate candidate generation.

The broad price task requires 21 independent source tables, exceeding the 13-candidate budget even with perfect ranking. All three vector attempts remain scored and are labeled as structurally constrained. Its failures cannot by themselves establish poor vector ranking. Other questions can lose required sources through candidate ranking or subsequent relevance filtering.

The public evidence is in [`app/static/benchmark.json`](../app/static/benchmark.json). The fixed questions are in [QUESTIONS.md](QUESTIONS.md); [README.md](README.md) describes the protocol. The complete raw rerun is retained locally at `artifacts/benchmark-threshold-p30-format9-2026-11-15-3trials.json` (ignored by Git). The November 14 results remain available in Git history.
