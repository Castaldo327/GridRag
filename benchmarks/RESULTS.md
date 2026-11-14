# Recorded results with a fixed 20% candidate cap

Experiment `decisions-vs-reranker-30-v3`: 30 unchanged analyst questions, three trials per pipeline, 180 attempts. All attempts are included. These are synthetic development results, not a production accuracy estimate.

Qdrant uses `ceil(0.20 × 65) = 13` candidates. Dense and keyword retrieval each propose up to 13 tables; fusion caps their combined shortlist at 13 before Decisions reranking. Foreign-key references are expanded afterward. The candidate policy was fixed before the run, without a sweep or outcome-based tuning.

| Pipeline | Trial 1 | Trial 2 | Trial 3 | Cumulative correct | Median time | Est. cost / attempt |
| --- | --- | --- | --- | --- | --- | --- |
| GridRag | 27/30 | 26/30 | 27/30 | 80/90 · 88.9% | 4.40 s | $0.00359 |
| Vector + Decisions reranker (20% cap) | 20/30 | 19/30 | 20/30 | 59/90 · 65.6% | 3.71 s | $0.00091 |

## Selection, latency and model use

| Measurement | GridRag | Vector + Decisions reranker |
| --- | --- | --- |
| Candidate-table recall | 100.00% | 88.63% |
| Final required-table recall | 98.80% | 83.62% |
| Attempts with candidate omissions | 0/90 | 30/90 |
| Attempts whose reference exceeds the candidate cap | 0/90 | 3/90 |
| Mean selected columns | 22.0 | 21.8 |
| Mean schema characters | 3,075 | 2,749 |
| Mean pipeline input tokens | 35,869 | 9,595 |
| p95 total latency | 7.49 s | 9.64 s |
| Median request-gate latency | 0.28 s | 0.31 s |
| Median schema-selection latency | 1.00 s | 0.32 s |
| Median SQL and answer latency (when reached) | 2.91 s | 2.97 s |

GridRag minus reranker accuracy difference: **+23.3 percentage points**; 95% case-cluster bootstrap interval **[+7.8, +38.9] points**. Repeated attempts stay clustered by question. This interval describes this development suite, not production reliability.

One-time embedding/index initialization: 3.83 s, excluded from per-question latency. Total estimated model cost: $0.4047. Latency and cost cover all attempts, including abstentions; lower time or cost alone does not establish better successful-answer performance. Both methods include the same request gate in total latency and cost, plus selection, SQL, repair and answering. Costs exclude local embedding compute, Qdrant hosting and unreported failed-call billing.

## POC limitations

The 20% cap prevents nearly exhaustive candidate retrieval in this 65-table catalog. A fixed percentage does not reproduce a production-sized database or establish a production-optimal top_k. These implementations also differ in column selection, so results measure whole pipelines and do not isolate candidate generation.

The broad price task requires 21 independent source tables, exceeding the 13-candidate budget even with perfect ranking. All three vector attempts remain scored and are labeled as structurally constrained. Its failures cannot by themselves establish poor vector ranking. Other questions can lose required sources through candidate ranking or subsequent relevance filtering. The shared SQL context budget remains 25 tables including references.

The questions, scoring, SQL model, request gate, thresholds and grounding are unchanged. Earlier experiment v2 used up to 60 reranking candidates; its scores are historical and are not current-policy results.

## Results by capability

| Capability | Questions | GridRag correct | Reranker correct |
| --- | --- | --- | --- |
| joins | 5 | 14/15 | 12/15 |
| operations | 6 | 17/18 | 15/18 |
| products | 6 | 16/18 | 18/18 |
| regional | 5 | 9/15 | 2/15 |
| scope | 3 | 9/9 | 6/9 |
| temporal | 5 | 15/15 | 6/15 |

## Questions with incorrect attempts

Inspect the recorded SQL, selected columns and returned data in the Evaluation page. Missing required tables are diagnostics against the fixed reference; alternative valid queries can exist. Full table recall does not guarantee correct SQL or selected columns.

| Question | GridRag correct | Reranker correct | Reranker diagnostic |
| --- | --- | --- | --- |
| `pjm_proposed_batteries` | 3/3 | 0/3 | candidate omissions in 3/3; final table omissions in 3/3 |
| `california_daily_spread` | 1/3 | 3/3 | candidate omissions in 0/3; final table omissions in 0/3 |
| `pjm_pre_delivery_bias` | 3/3 | 0/3 | candidate omissions in 3/3; final table omissions in 3/3 |
| `spp_available_wind_share` | 2/3 | 0/3 | candidate omissions in 3/3; final table omissions in 3/3 |
| `new_england_demand_ramp` | 3/3 | 0/3 | candidate omissions in 3/3; final table omissions in 3/3 |
| `annual_regional_peak_gap` | 3/3 | 0/3 | candidate omissions in 3/3; final table omissions in 3/3 |
| `new_york_forecast_mae` | 3/3 | 0/3 | candidate omissions in 3/3; final table omissions in 3/3 |
| `california_net_load_peak_price` | 2/3 | 0/3 | candidate omissions in 3/3; final table omissions in 3/3 |
| `regional_peak_renewable_gap` | 3/3 | 2/3 | candidate omissions in 3/3; final table omissions in 3/3 |
| `all_region_forecast_error` | 0/3 | 0/3 | candidate omissions in 3/3; final table omissions in 3/3 |
| `all_region_battery_energy` | 0/3 | 0/3 | candidate omissions in 0/3; final table omissions in 3/3 |
| `all_iso_prices` | 3/3 | 0/3 | reference exceeds candidate cap |

The public evidence is in [`app/static/benchmark.json`](../app/static/benchmark.json). The fixed questions are in [QUESTIONS.md](QUESTIONS.md); [README.md](README.md) describes the protocol.
