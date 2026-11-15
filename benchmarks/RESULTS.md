# Recorded results after generic table-scoring prompt update

This is the historical full-catalog GridRag versus vector comparison, before
metadata filtering. For the current routing flow and its direct cost/quality
comparison, see [metadata-routing results](METADATA_RESULTS.md).

Run date: November 15, 2026 (America/New_York). Experiment `decisions-vs-reranker-30-v3`: 30 unchanged analyst questions, three trials per pipeline, 180 attempts. All attempts are included. Models: `gpt-6-luna` for Decisions and `gpt-6-luna` for SQL and answers. These are synthetic development results, not a production accuracy estimate.

This rerun changes the shared table-relevance prompt to recognize tables supplying any required input and to apply column-specific limitations to the affected measure. It contains no question-specific rules or table names. Both relevance thresholds remain **0.2**. The DuckDB catalog, questions, references, SQL instructions, models, candidate policy and evaluation budgets match the preceding run. The manifest now fingerprints the table-scoring prompt. All attempts were retained.

Qdrant uses `ceil(0.20 × 65) = 13` candidates. Dense and keyword retrieval each propose up to 13 tables; fusion caps their combined shortlist at 13 before Decisions reranking. Foreign-key references are expanded afterward. The shared SQL context budget is 25 tables and 4,096 output tokens.

| Pipeline | Trial 1 | Trial 2 | Trial 3 | Cumulative correct | Median time | Est. cost / attempt |
| --- | --- | --- | --- | --- | --- | --- |
| GridRag | 29/30 | 28/30 | 29/30 | 86/90 · 95.6% | 4.52 s | $0.00446 |
| Vector + Decisions reranker (20% cap) | 19/30 | 20/30 | 20/30 | 59/90 · 65.6% | 3.61 s | $0.00100 |

The preceding prompt scored 72/90 for GridRag and 57/90 for the reranker. The updated prompt scores 86/90 and 59/90. All 24 previously correct GridRag questions remained correct across every trial. The six previously incorrect questions recovered 14 of 18 attempts. These are inspected development results and include model run variability.

## Selection, latency and model use

| Measurement | GridRag | Vector + Decisions reranker |
| --- | --- | --- |
| Candidate-table recall | 100.00% | 88.63% |
| Final required-table recall | 100.00% | 83.15% |
| Attempts with candidate omissions | 0/90 | 30/90 |
| Attempts whose reference exceeds the candidate cap | 0/90 | 3/90 |
| Mean selected columns | 24.8 | 24.1 |
| Mean schema characters | 3,852 | 3,352 |
| Mean pipeline input tokens | 45,299 | 11,189 |
| p95 answer-pipeline latency | 7.34 s | 8.32 s |
| Median request-gate latency | 0.30 s | 0.28 s |
| Median schema-selection latency | 1.15 s | 0.33 s |
| Median SQL and answer latency (when reached) | 2.93 s | 2.97 s |

GridRag minus reranker accuracy difference: **+30.0 percentage points**; 95% case-cluster bootstrap interval **[+14.4, +45.6] points**. Repeated attempts stay clustered by question. This interval describes this development suite, not production reliability.

One-time embedding/index initialization: 4.90 s, excluded from per-question latency. Total estimated comparison model cost: $0.4918. Latency and cost include unsuccessful attempts and abstentions. Costs exclude local embedding compute, Qdrant hosting and unreported failed-call billing.

**Timing boundary:** format 9 times only the answer pipeline, stopping before grading and client cleanup. Older format-8 reports included evaluator work, so their latency figures are not directly comparable.

## Routing fix and remaining errors

All six previously incorrect GridRag questions omitted required inputs during routing. PJM and New York forecast errors, the all-region forecast calculation and California net load lost the actual-demand table. SPP wind availability lost observed generation, and the all-region battery calculation lost three regional dispatch tables. The updated generic prompt recovered complete required-table coverage in all 90 GridRag attempts. PJM forecast error, New York MAE and all-region battery energy each improved from 0/3 to 3/3.

The remaining four incorrect GridRag attempts concern SQL grain alignment. All three California attempts equality-joined five-minute prices to an hourly timestamp, retaining the boundary reading rather than averaging the full hour. One SPP attempt repeated its hourly generation denominator across five-minute curtailment rows. SQL instructions and grading were held fixed in this comparison.

A separate populated synthetic database tested ten retail, weather and warehouse questions, once per prompt. The updated prompt answered all nine answerable tasks correctly, versus eight with the prior prompt. Both scored 9/10 under strict task/state checks: the new prompt correctly explained that historical stock was unavailable after a diagnostic query, but the application labeled the response `answered` rather than `abstained`. No inventory value was fabricated. Questions, data and independent references were fixed before those calls. These small synthetic checks are not a production holdout.

Broader selection increased GridRag's mean selected tables from 4.93 to 5.50 and estimated cost per attempt by about 15%. With the recorded benchmark wording, the California net-load selection contains 16 tables and the all-price selection 23. These fit the comparison's 25-table budget but exceed the unchanged ten-table playground budget.

## Results by capability

| Capability | Questions | GridRag correct | Reranker correct |
| --- | --- | --- | --- |
| joins | 5 | 14/15 | 12/15 |
| operations | 6 | 15/18 | 14/18 |
| products | 6 | 18/18 | 18/18 |
| regional | 5 | 15/15 | 3/15 |
| scope | 3 | 9/9 | 6/9 |
| temporal | 5 | 15/15 | 6/15 |

## Questions with incorrect attempts

Inspect the recorded SQL, selected columns and returned data in the Evaluation page. Missing required tables are diagnostics against the fixed reference; alternative valid queries can exist. Full table recall does not guarantee correct SQL or selected columns.

| Question | GridRag correct | Reranker correct | Reranker diagnostic |
| --- | --- | --- | --- |
| `spp_battery_discharge` | 3/3 | 2/3 | candidate omissions in 0/3; final table omissions in 0/3 |
| `pjm_proposed_batteries` | 3/3 | 0/3 | candidate omissions in 3/3; final table omissions in 3/3 |
| `pjm_pre_delivery_bias` | 3/3 | 0/3 | candidate omissions in 3/3; final table omissions in 3/3 |
| `spp_available_wind_share` | 2/3 | 0/3 | candidate omissions in 3/3; final table omissions in 3/3 |
| `new_england_demand_ramp` | 3/3 | 0/3 | candidate omissions in 3/3; final table omissions in 3/3 |
| `annual_regional_peak_gap` | 3/3 | 0/3 | candidate omissions in 3/3; final table omissions in 3/3 |
| `new_york_forecast_mae` | 3/3 | 0/3 | candidate omissions in 3/3; final table omissions in 3/3 |
| `california_net_load_peak_price` | 0/3 | 0/3 | candidate omissions in 3/3; final table omissions in 3/3 |
| `regional_peak_renewable_gap` | 3/3 | 0/3 | candidate omissions in 3/3; final table omissions in 3/3 |
| `all_region_forecast_error` | 3/3 | 0/3 | candidate omissions in 3/3; final table omissions in 3/3 |
| `all_iso_prices` | 3/3 | 0/3 | reference exceeds candidate cap |

## Live regression suite

The separate 26-case suite used the same 0.2 thresholds with application defaults (10 tables / 1,600 output tokens): **6/26 passed every diagnostic check; 24/26 met task-level state/evidence criteria**. See the [complete regression results](REGRESSION_RESULTS.md) for individual checks and the live unittest outcome.

## POC limitations

The 20% cap prevents nearly exhaustive candidate retrieval in this 65-table catalog. A fixed percentage does not reproduce a production-sized database or establish a production-optimal top_k. These implementations also differ in column selection, so results measure whole pipelines and do not isolate candidate generation.

The broad price task requires 21 independent source tables, exceeding the 13-candidate budget even with perfect ranking. All three vector attempts remain scored and are labeled as structurally constrained. Its failures cannot by themselves establish poor vector ranking. Other questions can lose required sources through candidate ranking or subsequent relevance filtering.

The public evidence is in [`app/static/benchmark.json`](../app/static/benchmark.json). The fixed questions are in [QUESTIONS.md](QUESTIONS.md); [README.md](README.md) describes the protocol. The complete raw rerun is retained locally at `artifacts/benchmark-table-input-prompt-format9-2026-11-15-3trials.json` (ignored by Git). Earlier reports remain available in Git history and local artifacts.
