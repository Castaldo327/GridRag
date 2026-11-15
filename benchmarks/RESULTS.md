# Recorded results with restored 0.2 relevance thresholds

Run date: November 15, 2026 (America/New_York). Experiment `decisions-vs-reranker-30-v3`: 30 unchanged analyst questions, three trials per pipeline, 180 attempts. All attempts are included. Models: `gpt-6-luna` for Decisions and `gpt-6-luna` for SQL and answers. These are synthetic development results, not a production accuracy estimate.

This rerun restores both table and column relevance thresholds from **0.3 to 0.2**. The table threshold is shared by both pipelines; column pruning applies to GridRag. The DuckDB metadata catalog, question/reference hashes, scoring, model names, candidate policy and shared evaluation budgets match both earlier format-9 runs. Settings were fixed before execution, with all attempts retained.

Qdrant uses `ceil(0.20 × 65) = 13` candidates. Dense and keyword retrieval each propose up to 13 tables; fusion caps their combined shortlist at 13 before Decisions reranking. Foreign-key references are expanded afterward. The shared SQL context budget is 25 tables and 4,096 output tokens.

| Pipeline | Trial 1 | Trial 2 | Trial 3 | Cumulative correct | Median time | Est. cost / attempt |
| --- | --- | --- | --- | --- | --- | --- |
| GridRag | 24/30 | 24/30 | 24/30 | 72/90 · 80.0% | 4.81 s | $0.00388 |
| Vector + Decisions reranker (20% cap) | 19/30 | 19/30 | 19/30 | 57/90 · 63.3% | 4.21 s | $0.00092 |

The preceding 0.3 run scored 67/90 for GridRag and 57/90 for the reranker. This restored 0.2 run scores 72/90 and 57/90, respectively. The original November 14 run at 0.2 scored 72/90 and 57/90. These before/after observations include model run variability and do not isolate the effect of either threshold independently.

## Changes from the preceding 0.3 run

| Question | GridRag at 0.3 | GridRag at restored 0.2 | Reranker at 0.3 | Reranker at restored 0.2 |
| --- | --- | --- | --- | --- |
| `pjm_solar_share` | 1/3 | 3/3 | 2/3 | 3/3 |
| `regional_peak_renewable_gap` | 3/3 | 3/3 | 1/3 | 0/3 |
| `all_iso_prices` | 0/3 | 3/3 | 0/3 | 0/3 |

For a concrete routing example, trial 1 of `all_iso_prices` scored `core.caiso_lmp_rt_bus_5min` at 0.24 in both runs. The 0.3 threshold excluded it; the restored 0.2 threshold included it. GridRag then had all 21 independent price-product sources, and this attempt changed from incorrect to correct. This identifies a direct table-selection effect for that attempt; it does not attribute every score change to the thresholds.

## Selection, latency and model use

| Measurement | GridRag | Vector + Decisions reranker |
| --- | --- | --- |
| Candidate-table recall | 100.00% | 88.63% |
| Final required-table recall | 94.85% | 81.90% |
| Attempts with candidate omissions | 0/90 | 30/90 |
| Attempts whose reference exceeds the candidate cap | 0/90 | 3/90 |
| Mean selected columns | 22.0 | 21.7 |
| Mean schema characters | 3,393 | 2,996 |
| Mean pipeline input tokens | 39,564 | 10,137 |
| p95 answer-pipeline latency | 12.64 s | 13.16 s |
| Median request-gate latency | 0.30 s | 0.28 s |
| Median schema-selection latency | 1.10 s | 0.32 s |
| Median SQL and answer latency (when reached) | 3.37 s | 3.83 s |

GridRag minus reranker accuracy difference: **+16.7 percentage points**; 95% case-cluster bootstrap interval **[+3.3, +30.0] points**. Repeated attempts stay clustered by question. This interval describes this development suite, not production reliability.

One-time embedding/index initialization: 4.87 s, excluded from per-question latency. Total estimated comparison model cost: $0.4320. Latency and cost include unsuccessful attempts and abstentions. Costs exclude local embedding compute, Qdrant hosting and unreported failed-call billing.

**Timing boundary:** format 9 times only the answer pipeline, stopping before grading and client cleanup. Older format-8 reports included evaluator work, so their latency figures are not directly comparable.

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

The separate 26-case suite used the restored 0.2 thresholds with application defaults (10 tables / 1,600 output tokens): **4/26 passed every diagnostic check; 23/26 met task-level state/evidence criteria**. See the [complete regression results](REGRESSION_RESULTS.md) for individual checks and the live unittest outcome.

## POC limitations

The 20% cap prevents nearly exhaustive candidate retrieval in this 65-table catalog. A fixed percentage does not reproduce a production-sized database or establish a production-optimal top_k. These implementations also differ in column selection, so results measure whole pipelines and do not isolate candidate generation.

The broad price task requires 21 independent source tables, exceeding the 13-candidate budget even with perfect ranking. All three vector attempts remain scored and are labeled as structurally constrained. Its failures cannot by themselves establish poor vector ranking. Other questions can lose required sources through candidate ranking or subsequent relevance filtering.

The public evidence is in [`app/static/benchmark.json`](../app/static/benchmark.json). The fixed questions are in [QUESTIONS.md](QUESTIONS.md); [README.md](README.md) describes the protocol. The complete raw rerun is retained locally at `artifacts/benchmark-threshold-p20-restored-format9-2026-11-15-3trials.json` (ignored by Git). Both earlier format-9 reports remain available in Git history and local artifacts.
