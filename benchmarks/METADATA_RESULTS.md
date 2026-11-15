# Metadata-filter routing comparison

The local application candidate adds a compact Decisions call over database metadata tags
before table scoring. A table can carry multiple labels. Routing takes the union
of matching tables, keeps untagged tables, and applies the existing table
relevance, foreign-key expansion and column-selection stages to that candidate
set. No matching tags falls back to the full catalog. Completely untagged
catalogs skip the extra call.

**Rollout: HELD.** All 336 attempts completed. Estimated model costs fell and
aggregate task accuracy held, but analytical p95 latency increased materially.
The implementation and architecture updates remain local; no push or deployment
was performed. The deployed version continues using full-catalog routing.

The [complete recorded evidence](metadata-results.json) includes the manifest,
every attempt and trial, SQL, returned data, model usage, scoring checks and
metadata-filter diagnostics.

## Evaluation protocol

The paired experiment compares `full-catalog` with `metadata-filtered` routing.
Only the metadata filter changes. Both methods share the same built 65-table
warehouse, gate, table/column relevance prompts, selected-schema rendering, ISO
vocabulary, SQL/answer model, repair budget and scoring. Labels describe table
capabilities and were authored independently of evaluation questions. Reference
SQL and required-table labels are used for scoring only.

The frozen workload contains all 30 analytical comparison questions and all 26
application regression cases. Three trials for each case and method produce
**336 attempts**: 90 per method in the analytical suite and 78 per method in the
regression suite. Seeded shuffled method/question order is fixed before model
execution. Attempts run serially; column scoring retains four concurrent workers.
The analytical suite uses a 25-table budget and 4,096 SQL output tokens; regression
uses the application defaults of 10 tables and 1,600 tokens. Tag, table and column
relevance thresholds are 0.2.

Task correctness requires the expected response state and reference-matching SQL
evidence. The stricter `checks_passed` diagnostic additionally covers routing and
answer presentation. Behavior cases require the expected state and no SQL calls.
Every attempt, including failures, stays in the denominator. Candidate recall
measures the required tables available after metadata filtering and recoverable
foreign-key expansion; final required-table recall measures the actual selection.

The practical rollout gate was fixed before the paid run: no more than a
**2 percentage-point observed accuracy loss in either suite**, no newly failed
behavior attempt, and lower mean estimated model cost in each suite. A median or
p95 latency increase above 10% requires separate review. This is an observed
development-set gate, not a statistical noninferiority claim. Paired bootstrap
intervals resample questions as clusters, keeping all repeats together.

Latency covers only the answer pipeline, ending before client cleanup and grading.
Model cost includes the gate, added metadata call, table and column Decisions,
SQL generation, repairs and answering. Both provider-reported cached-token
estimates and equivalent costs treating all input tokens as uncached are compared.
Rates are configured estimates, not billing records; unavailable failed-call
billing is excluded. The manifest fingerprints schema metadata including tags,
questions, routing prompts and vocabulary, and records model versions and runtime
settings.

## Results

Run date: November 15, 2026 (America/New_York). Both Decisions and Responses use
`gpt-6-luna`. The complete run contains **336 attempts**: 180 analytical attempts
and 156 application regression attempts. No failed or unfavorable attempt was
removed.

### Analytical tasks

| Measurement | Full catalog | Metadata filtered |
| --- | --- | --- |
| Trial 1 task correct | 28/30 | 29/30 |
| Trial 2 task correct | 30/30 | 29/30 |
| Trial 3 task correct | 28/30 | 28/30 |
| Cumulative task correct | 86/90 · 95.56% | 86/90 · 95.56% |
| All stricter checks passed | 13/90 · 14.44% | 15/90 · 16.67% |
| Candidate-table recall | 100% | 100% |
| Final required-table recall | 100% | 100% |
| Mean candidate tables | 65.00 | 23.43 |
| Mean selected tables | 5.50 | 5.47 |
| Mean selected columns | 24.77 | 24.67 |
| Mean pipeline input tokens | 45,050.62 | 25,378.81 |
| Mean routing input tokens | 41,084.00 | 21,482.57 |
| Mean estimated cost / attempt | $0.00441647 | $0.00246955 |
| Mean cost with all input uncached | $0.00465171 | $0.00268719 |
| Mean end-to-end latency | 5.543 s | 5.613 s |
| Median end-to-end latency | 4.689 s | 4.862 s |
| p95 end-to-end latency | 8.464 s | 12.219 s |
| Median schema-routing latency | 1.026 s | 1.095 s |
| p95 schema-routing latency | 2.017 s | 1.714 s |
| p95 first-answer-token latency | 8.182 s | 9.680 s |
| Failed provider calls | 0 | 0 |

Estimated mean model cost fell **44.08%**, or **42.23%** when all input tokens are
priced as uncached. The metadata filter reduced the mean candidate set by
**63.95%**, while retaining every required table in all 90 attempts. Column
selection and final schema size changed little; the main token reduction occurs
before table relevance scoring.

Task accuracy was unchanged in aggregate. The case-cluster bootstrap 95% interval
for metadata-filtered minus full-catalog accuracy is **−6.67 to +6.67 percentage
points**. This inspected, 30-question suite does not establish statistical
noninferiority within the practical 2-point rollout margin.

Latency needs review: the mean increased **1.25%**, the median increased
**3.69%**, and p95 increased **44.35%** from 8.464 to 12.219 seconds, exceeding
the predeclared 10% review threshold. First-answer-token p95 increased **18.31%**.
Equal aggregate task accuracy and lower costs therefore do not by themselves
satisfy the user's full performance condition.

The filter adds a sequential Decisions request before table scoring; its time and
usage are included. Schema-routing median increased by 69 ms, while its p95 fell
15.02%. The tables and columns delivered to SQL were identical in **87 of 90
paired attempts**. End-to-end tail variation therefore cannot be attributed to
the added metadata request alone. This small run establishes neither an expected
tail regression nor tail equivalence. The observed p95 increase is the reason
rollout was held after review.

All 180 attempts returned an answer. The four incorrect attempts per method had
numeric evidence mismatches despite complete required-table coverage:

| Case | Full-catalog incorrect trials | Metadata-filtered incorrect trials |
| --- | --- | --- |
| `california_net_load_peak_price` | 1, 3 | 3 |
| `pjm_solar_share` | 1, 3 | None |
| `all_region_forecast_error` | None | 1 |
| `spp_available_wind_share` | None | 2, 3 |

No attempt had a metadata candidate omission. The stricter diagnostic pass rates
are much lower than task accuracy: the answer-unit label check failed in 76
full-catalog and 73 metadata-filtered attempts. Those checks remain reported;
**86/90 task correct does not mean 86/90 complete regression-check passes**.

### Application regression

| Measurement | Full catalog | Metadata filtered |
| --- | --- | --- |
| Trial 1 task correct | 24/26 | 24/26 |
| Trial 2 task correct | 24/26 | 24/26 |
| Trial 3 task correct | 23/26 | 24/26 |
| Cumulative task correct | 71/78 · 91.03% | 72/78 · 92.31% |
| All stricter checks passed | 15/78 · 19.23% | 16/78 · 20.51% |
| Behavior attempts correct | 12/12 | 12/12 |
| Candidate-table recall | 100% | 100% |
| Final required-table recall | 100% | 100% |
| Mean candidate tables | 65.00 | 22.35 |
| Mean selected tables | 4.87 | 4.78 |
| Mean selected columns | 14.78 | 14.48 |
| Mean pipeline input tokens | 36,075.47 | 18,029.36 |
| Mean routing input tokens | 33,406.27 | 15,610.58 |
| Mean estimated cost / attempt | $0.00354385 | $0.00175463 |
| Mean cost with all input uncached | $0.00368380 | $0.00187011 |
| Mean end-to-end latency | 3.933 s | 3.807 s |
| Median end-to-end latency | 4.146 s | 4.169 s |
| p95 end-to-end latency | 7.432 s | 7.365 s |
| Failed provider calls | 0 | 0 |

Mean estimated cost fell **50.49%**, or **49.23%** with uncached input pricing.
Median latency increased **0.56%** and p95 decreased **0.91%**. Candidate averages
cover requests reaching routing; gate-declined requests have no candidate set.
There were no candidate omissions or newly failed behavior attempts. The paired
task-accuracy change is **+1.28 percentage points**, with a case-cluster bootstrap
95% interval of **0.00 to +3.85 points**.

Both methods missed the same six analytical regression attempts. In all three
`share` trials they used UTC month boundaries rather than the reference's local
calendar month, returning 42.06103487% against 42.07465179%; this is a time-filter
error. In all three `isone_spread` trials they selected 12 tables including
references, exceeding the 10-table budget and returning clarification before SQL.
Complete required-table recall therefore does not imply that the route fits the
execution budget.

The additional full-catalog miss was `spread_forecast_error`, trial 3. Its SQL
grouped five-minute readings by their exact timestamp instead of the hour, then
required 12 readings per group, eliminating the hourly candidates. Later
diagnostic queries did not supply the required scalar evidence. The
metadata-filtered attempt returned the correct scalar; both had the same selected
tables and columns. This difference occurs after retrieval.

Stricter diagnostics passed in only 15 versus 16 attempts. The answer-unit label
check failed 62 times in each method. Task-level correctness and full diagnostic
passes remain separate measurements.

### Rollout decision

**HELD — no push or deployment.** The complete run passes the predeclared
observed quality/cost gate: analytical task accuracy is unchanged, regression
accuracy is slightly higher, all behavior attempts remain correct, and estimated
costs fall in both suites. However, analytical p95 rises **44.35%**, from 8.464 to
12.219 seconds, which is a material observed performance tradeoff under the
user's condition. The separate latency review therefore rejects rollout despite
the automated quality/cost gate passing.

The metadata implementation, evaluation runner, evidence and architecture
documentation remain available locally for review and further work. Runtime
configuration is unchanged from the evaluated candidate. The hosted application
and recorded vector comparison retain the prior full-catalog flow. This small
synthetic development suite is not a production accuracy or latency guarantee.

## Reproduce

The Evaluation page keeps its existing GridRag-versus-Qdrant layout, questions,
filters and trial controls. Its GridRag column now uses the 90 analytical
metadata-filtered attempts. Qdrant retains its earlier 90 recorded attempts;
the existing run details identify both source runs. This display refresh is not
a new paired experiment with Qdrant. The full paired results above remain the
source for comparing metadata routing with the previous full-catalog approach.

Refresh the existing page artifact without model calls:

```sh
uv run python -m scripts.publish_metadata
```

Rebuild the warehouse after changing tags, then run:

```sh
uv run python -m gridrag.warehouse.build
uv run python -m benchmarks.metadata --live --suite all --repeats 3 --workers 1 --output artifacts/metadata-prefilter-2026-11-15-3trials-live.json
```

The runner requires a new output path, precomputes all references before paid
calls, and checkpoints each completed attempt. `Settings.route_metadata_prefilter`
controls the default runtime flow. `route(..., metadata_prefilter=False)` preserves
the legacy baseline. The earlier [vector comparison](RESULTS.md) remains a
historical measurement of full-catalog routing and is not relabeled as evidence
for metadata filtering.
